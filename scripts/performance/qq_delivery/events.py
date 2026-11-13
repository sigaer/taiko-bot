"""Read native production event logs privately, never export message contents."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import subprocess
import time

from .config import Blocked


@dataclass(repr=False)
class Trigger:
    bot_id: str
    group_openid: str
    admin_openid: str
    message_id: str
    received_at: float


def journal_trigger(config, mode, *, bootstrap=False):
    expected = "开始测试" if bootstrap else f"/qqprobe {mode}"
    # Anchor both the logger namespace and adapter event description. A user's
    # message containing a fake log prefix cannot impersonate the outer event.
    pattern = re.compile(
        r"^QQ (?P<bot>[^\s|]+) \| \[(?:EventType\.GROUP_(?:AT_)?MESSAGE_CREATE|message\.group_at_message_create)\]: "
        r"Message (?P<message>[^\s]+) from (?P<admin>[^\s]+)@\[Group:(?P<group>[^\]\s]+)\]: (?P<text>.*)$"
    )
    result = subprocess.run(["journalctl", "-u", "taiko-bot.service", "--since", "1 hour ago" if bootstrap else "3 minutes ago",
        "-o", "json", "--all", "--no-pager"], capture_output=True, text=True)
    if result.returncode:
        raise Blocked("private_event_journal_unavailable")
    from nonebot.adapters.qq import Message
    expected_reprs = {repr(Message(expected)), repr(Message(" " + expected))}
    events = []
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
            message = row.get("MESSAGE")
            if not isinstance(message, str):
                continue
            text = re.sub(r"\x1b\[[0-9;]*m", "", message)
            prefix, sep, body = text.partition(" | ")
            if not sep or prefix.rsplit(" ", 1)[-1] != "nonebot":
                continue
            match = pattern.fullmatch(body)
            if not match or match["text"] not in expected_reprs:
                continue
            stamp = int(row["__REALTIME_TIMESTAMP"]) / 1e6
            if not 0 <= time.time() - stamp <= (3600 if bootstrap else 120):
                continue
            event = Trigger(match["bot"], match["group"], match["admin"], match["message"], stamp)
            if config is None or (event.bot_id == config.bot_id and event.group_openid == config.group_openid
                    and event.admin_openid in config.admin_openids):
                events.append(event)
        except (ValueError, TypeError, KeyError):
            continue
    if not events:
        raise Blocked("fresh_authorized_test_group_event_required")
    if config is None and len({(e.bot_id, e.group_openid, e.admin_openid) for e in events}) != 1:
        raise Blocked("ambiguous_start_test_target")
    return events[-1]


def validate_trigger(config, event, *, active_protocol=False):
    if not isinstance(event, Trigger):
        raise Blocked("verified_trigger_required")
    if event.bot_id != config.bot_id or event.group_openid != config.group_openid or event.admin_openid not in config.admin_openids:
        raise Blocked("event_target_or_admin_mismatch")
    if not event.message_id or not 0 <= time.time() - event.received_at <= (3600 if active_protocol else 120):
        raise Blocked("fresh_passive_event_required")


def standalone_bot(config):
    """No server, gateway startup, business plugins or changes to the live Bot.

    The existing process's Python objects are not reachable from a CLI. This
    explicit alternative uses its config and the installed SDK in an isolated
    worker, with a separate auth cache. Transport also accepts an in-process Bot.
    """
    import logging
    import nonebot
    from nonebot.adapters.qq import Adapter, Bot
    from taiko_bot.runtime.player.center.runtime_env import load_runtime_environment
    nonebot.logger.remove()  # Private worker: never emit SDK validation/body logs.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    load_runtime_environment()
    nonebot.init(driver="~none+~httpx+~websockets", _env_file=config.runtime_env_file)
    adapter = Adapter(nonebot.get_driver())
    matches = [b for b in adapter.qq_config.qq_bots if str(b.id) == config.bot_id]
    if len(matches) != 1:
        raise Blocked("selected_test_bot_not_in_existing_configuration")
    return Bot(adapter, config.bot_id, matches[0])
