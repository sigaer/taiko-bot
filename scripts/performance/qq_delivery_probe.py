#!/usr/bin/env python3
"""Explicit opt-in QQ delivery probe. Default: inventory/dry-run, zero QQ APIs.

Run using /opt/taiko-bot/current/bin/python -I under the existing QA wrapper.
No Bot credentials or event IDs are accepted on the command line.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import time

# -I deliberately excludes the source checkout. Only this standalone tool's
# sibling modules are added; all application/SDK imports remain installed ones.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qq_delivery.config import Blocked, Config, MODES, private_directory
from qq_delivery.events import journal_trigger, standalone_bot
from qq_delivery.experiment import Experiment
from qq_delivery.images import cleanup_static
from qq_delivery.report import export
from qq_delivery.state import State, atomic_json
from qq_delivery.transport import inventory


async def listen(config, modes, seconds, output):
    """One worker, shared auth cache, one fresh administrator command per send."""
    config.validate_live()
    deadline=time.monotonic()+seconds
    seen=set()
    bot=None
    while time.monotonic()<deadline:
        with State(config).locked() as state:
            if state.data["paused"] or state.data["rounds"].get(config.round_id,0)>=config.max_sends_per_round:
                return
        for mode in modes:
            try:
                event=journal_trigger(config,mode)
            except Blocked as error:
                if str(error)=="fresh_authorized_test_group_event_required":
                    continue
                raise
            if event.message_id in seen:
                continue
            with State(config).locked() as state:
                if state.digest(event.message_id) in state.data["used_events"]:
                    seen.add(event.message_id)
                    continue
            if bot is None:
                bot=standalone_bot(config)
            try:
                result=await Experiment(config,bot,connected=False).run(mode,event,live=True)
            except Blocked as error:
                if str(error)=="minimum_interval_not_elapsed":
                    continue  # No API has been attempted or reserved.
                raise
            seen.add(event.message_id)
            with State(config).locked() as state:
                export(output,state)
            print(json.dumps(result),flush=True)
            if result["status"]!="acknowledged":
                return  # Unknown/rejected operations are never replayed.
        await asyncio.sleep(1)


def observe(state, sample, data):
    allowed = {"device", "received", "image_start_ms", "message_ms", "complete_ms", "duplicates",
               "render_ok", "clock_uncertainty_ms", "clock_synced", "quota_before", "quota_after",
               "url_cache_observation"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise Blocked("observation_schema")
    if data.get("device") not in ("android", "windows"):
        raise Blocked("observation_device")
    if any(type(data.get(k)) is not bool for k in ("received", "render_ok", "clock_synced")):
        raise Blocked("observation_boolean_fields")
    has_times=any(data.get(k) is not None for k in ("image_start_ms","message_ms","complete_ms"))
    if has_times and data["clock_synced"] is not True:
        raise Blocked("client_clock_synchronization_required")
    if type(data.get("duplicates")) is not int or not 0 <= data["duplicates"] <= 10:
        raise Blocked("observation_duplicate_count")
    for key in ("image_start_ms", "message_ms", "complete_ms", "clock_uncertainty_ms"):
        value = data.get(key)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 3_600_000):
            raise Blocked("observation_invalid_timing")
    if has_times and data.get("clock_uncertainty_ms") is None:
        raise Blocked("recording_uncertainty_required")
    if data.get("complete_ms") is not None and (
        not data["received"] or data.get("image_start_ms") is None or data["complete_ms"] < data["image_start_ms"]
    ):
        raise Blocked("observation_timing_order")
    if data.get("url_cache_observation") not in (None,"first","cached","unknown"):
        raise Blocked("invalid_url_cache_observation")
    rows=[r for r in state.data["rows"] if r["sample"]==sample]
    if len(rows)!=1:
        raise Blocked("sample_not_found")
    row=rows[0]
    if any(o["device"]==data["device"] for o in row["observations"]):
        raise Blocked("device_observation_already_recorded")
    for key in ("quota_before","quota_after"):
        value=data.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise Blocked("invalid_quota_observation")
    if (data.get("quota_before") is None)!=(data.get("quota_after") is None):
        raise Blocked("quota_pair_required")
    if data.get("quota_before") is not None:
        if data["quota_after"]>data["quota_before"]:
            raise Blocked("quota_changed_outside_experiment")
        if row["active_quota_before"] is not None and (row["active_quota_before"],row["active_quota_after"])!=(data["quota_before"],data["quota_after"]):
            raise Blocked("conflicting_quota_observation")
        row["active_quota_before"]=data["quota_before"]
        row["active_quota_after"]=data["quota_after"]
    row["observations"].append(data)
    if row["status"] in ("pending","unknown"):
        row["resolved"]=True  # Does not convert missing API ack into a success.
    if data["duplicates"] or not data["received"] or not data["render_ok"]:
        state.data["blocked_modes"].append(row["mode"])
        if row["mode"].startswith("B"):
            state.data["blocked_modes"].extend(["B-data","B-url"])
    state.save()


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path)
    p.add_argument("--output",type=Path,default=Path("/var/tmp/taiko-qq-delivery-report"))
    sub=p.add_subparsers(dest="command")
    sub.add_parser("inventory")
    bind=sub.add_parser("bind-start-event",help="Privately bind the unique native QQ 开始测试 target")
    bind.add_argument("--private-dir",type=Path,required=True)
    bind.add_argument("--authorize-active",action="store_true")
    bind.add_argument("--max-sends",type=int,default=3)
    run=sub.add_parser("run")
    run.add_argument("--mode",choices=MODES,default="A-data")
    run.add_argument("--live",action="store_true")
    run.add_argument("--start-trigger",action="store_true")
    run.add_argument("--active-trial",action="store_true",help="One explicit B protocol trial per path; no passive event or msg_id")
    run.add_argument("--wait-seconds",type=int,default=0,help="Wait up to 60s for one fresh event; never retry an API")
    watch=sub.add_parser("listen",help="Shared worker; sends only on new authorized test commands")
    watch.add_argument("--modes",nargs="+",choices=MODES,required=True)
    watch.add_argument("--seconds",type=int,default=300)
    watch.add_argument("--live",action="store_true")
    obs=sub.add_parser("observe")
    obs.add_argument("--sample",required=True)
    obs.add_argument("--observation",type=Path,required=True)
    sub.add_parser("report")
    sub.add_parser("pause")
    sub.add_parser("resume")
    clean=sub.add_parser("cleanup")
    clean.add_argument("--static-root",type=Path,required=True)
    clean.add_argument("--ttl",type=int,default=300)
    clean.add_argument("--all-generated",action="store_true",help="End experiment: delete only probe JPEGs in the marker directory")
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=="cleanup":
            print(json.dumps(dict(deleted=cleanup_static(args.static_root,args.ttl,all_generated=args.all_generated))))
            return 0
        if args.command=="bind-start-event":
            if not args.authorize_active or not 1<=args.max_sends<=6:
                raise Blocked("explicit_active_authorization_and_budget_required")
            event=journal_trigger(None,"B-data",bootstrap=True)
            private_directory(args.private_dir)
            config=Config(bot_id=event.bot_id,group_openid=event.group_openid,
                admin_openids=[event.admin_openid],active_test_authorized=True,
                max_sends_per_round=args.max_sends,private_dir=str(args.private_dir))
            config.validate_live()
            target=args.private_dir/"config.json"
            if target.exists():
                raise Blocked("private_config_already_exists")
            atomic_json(target,vars(config))
            print(json.dumps(dict(status="bound",private_config=str(target),identities_exported=False)))
            return 0
        if args.command in (None,"inventory") or (args.command in ("run","listen") and not args.live):
            mode=getattr(args,"mode","A-data")
            result=asyncio.run(Experiment(Config()).run(mode))
            env=inventory()
            export(args.output,environment=env,blockers=["dry_run_no_real_QQ_API_calls"])
            print(json.dumps(dict(**result,environment=env),ensure_ascii=False))
            return 0
        if args.config is None:
            raise Blocked("private_config_required")
        c=Config.load(args.config)
        c.validate_live()
        if args.command=="listen":
            if not 1<=args.seconds<=1800:
                raise Blocked("listener_limit_is_30_minutes")
            asyncio.run(listen(c,args.modes,args.seconds,args.output))
            return 0
        if args.command=="run":
            if not 0 <= args.wait_seconds <= 60:
                raise Blocked("event_wait_limit_is_60_seconds")
            if args.start_trigger and (not args.mode.startswith("B") or c.phase!="protocol"):
                raise Blocked("start_trigger_is_only_for_active_protocol")
            if args.active_trial and (not args.mode.startswith("B") or c.phase!="protocol" or args.start_trigger):
                raise Blocked("active_trial_only_for_B_protocol")
            deadline=time.monotonic()+args.wait_seconds
            event=None
            while not args.active_trial:
                try:
                    event=journal_trigger(c,args.mode,bootstrap=args.start_trigger)
                    break
                except Blocked as error:
                    if str(error)!="fresh_authorized_test_group_event_required" or time.monotonic()>=deadline:
                        raise
                    time.sleep(1)
            bot=standalone_bot(c)
            result=asyncio.run(Experiment(c,bot,connected=False).run(args.mode,event,live=True,active_trial=args.active_trial))
            with State(c).locked() as state:
                export(args.output,state)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result["status"]=="acknowledged" else 3
        with State(c).locked() as state:
            if args.command=="observe":
                if args.observation.is_symlink() or args.observation.stat().st_mode&0o077:
                    raise Blocked("observation_file_must_be_private")
                try:
                    observation=json.loads(args.observation.read_text())
                except Exception:
                    raise Blocked("observation_invalid_json") from None
                observe(state,args.sample,observation)
            elif args.command in ("pause","resume"):
                state.data["paused"]=args.command=="pause"
                state.save()
            result=export(args.output,state)
        print(json.dumps(dict(status="recorded",samples=len(result["samples"]),real_QQ_API_calls=0)))
        return 0
    except Blocked as error:
        print(json.dumps(dict(status="blocked",reason=str(error),automatic_retry=False)))
        return 2
    except KeyboardInterrupt:
        print(json.dumps(dict(status="interrupted",automatic_retry=False)))
        return 130
    except Exception:
        # SDK, HTTP, Pydantic and OS exceptions may contain credentials or URLs.
        print(json.dumps(dict(status="blocked",reason="private_worker_error_details_suppressed",automatic_retry=False)))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
