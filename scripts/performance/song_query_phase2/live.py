"""Bounded passive QQ acceptance worker; never starts or alters the service.

Reuse the previous private test target, not old message IDs. Three fresh
/qqprobe C events authorize baseline, first static URL, repeat static URL.
API acknowledgement is NOT evidence of native client receipt/rendering.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from types import ModuleType, SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qq_delivery.config import Blocked, Config, private_directory
from qq_delivery.events import journal_trigger, standalone_bot, validate_trigger
from qq_delivery.state import State, atomic_json
from qq_delivery.transport import ApiFailure, Transport


def prepare(args):
    from taiko_bot.offline.static_fumens import atomic_write, publish
    from taiko_bot.static_fumens import POLICY, canonical, digest
    import httpx
    old = Config.load(args.previous_config)
    if not old.markdown_authorized or not old.domain_whitelisted:
        raise Blocked('previous_markdown_domain_not_confirmed')
    private_directory(args.private)
    config_path = args.private/'config.json'
    if config_path.exists():
        raise Blocked('existing_experiment_do_not_overwrite')
    config = Config(**asdict(old))
    config.private_dir = str(args.private)
    config.phase, config.round_id = 'protocol', 'song-query-phase2'
    config.max_sends_per_round, config.max_samples_per_mode = 3, 3
    config.interval_seconds = 25
    config.static_root = str(Path(old.static_root)/'song-query-phase2')
    config.static_base_url = old.static_base_url.rstrip('/')+'/song-query-phase2'
    config.validate_live()
    root = args.private/'runtime'
    (root/'songs').mkdir(parents=True)
    for name in ('song_data.json', 'song_alias.json'):
        shutil.copyfile(args.catalog/'songs'/name, root/'songs'/name)
    source = root/'assets/fumens/Oni/649.png'
    source.parent.mkdir(parents=True)
    shutil.copyfile(args.chart, source)
    sha = digest(source.read_bytes())
    policy = dict(schema=1, scope='public-static-fumen', base_url=config.static_base_url,
                  valid_until=time.time()+86400, grants=[dict(difficulty='Oni', song_id='649',
                  sha256=sha, public=True, authorization_ref='User 2026-11-13: 全都允许')])
    atomic_write(root/'songs'/POLICY, canonical(policy))
    # Dedicated temporary public namespace; no production bot manifest/config.
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        result = publish(root, Path(config.static_root), config.static_base_url, client, lease=900)
    if result['published'] != 1:
        raise Blocked('test_asset_https_verification_failed')
    atomic_json(config_path, asdict(config))
    print(json.dumps(dict(prepared=True, public_assets=1, https_sha256_verified=True,
                          private_config=str(config_path)), ensure_ascii=False), flush=True)


def public_package(source, root, label):
    name = '_song_live_'+label
    package = ModuleType(name)
    package.__path__ = [str(source/'taiko_bot/runtime/public')]
    config = ModuleType(name+'.config')
    config.root, config.profile = lambda: root, lambda: 'center'
    sys.modules[name], sys.modules[name+'.config'] = package, config
    return importlib.import_module(name+'.provider'), importlib.import_module(name+'.delivery')


def export(state, output):
    # Explicit allowlist: never export target IDs, credentials or platform bodies.
    fields = ('sample', 'variant', 'status', 'calls', 'error', 'pipeline_ms',
              'search_command_ms', 'brief_ms', 'markdown_ms', 'png_reads',
              'temporary_writes', 'observations', 'image_sha256', 'finished_at')
    result = dict(schema=1, qa_run_id=os.environ['QA_RUN_ID'],
                  target='same private target as previous QQ image test',
                  service_changed=False, passive_only=True,
                  samples=[{k: row[k] for k in fields if k in row} for row in state.data['rows']],
                  native_client_first_ms=None, native_client_repeat_ms=None,
                  note='Acknowledged API calls do not prove client delivery/rendering. No automatic retry.')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


async def listen(args):
    config = Config.load(args.private/'config.json')
    config.validate_live()
    root = args.private/'runtime'
    os.environ.update(TAIKO_BOT_ROOT=str(root), TAIKO_RUNTIME_ROOT=str(root),
                      TAIKO_STATIC_FUMEN_ENABLED='1', TAIKO_STATIC_FUMEN_BASE_URL=config.static_base_url)
    bot = standalone_bot(config)
    before = public_package(args.baseline, root, 'before')
    after = public_package(args.source, root, 'after')
    for provider, _ in (before, after):
        provider.get_snapshot()  # Separate startup cost from real API samples.
    import taiko_bot.runtime.center_markdown_media as cache
    from taiko_application.commands import CommandContext, SongPorts, execute_song
    from nonebot.adapters.qq import MessageSegment
    from nonebot.exception import FinishedException
    cache.QQ_MARKDOWN_IMAGE_CACHE_DIR = Path(config.static_root)/'baseline'
    cache.QQ_MARKDOWN_IMAGE_BASE_URL = config.static_base_url+'/baseline'
    transport = Transport(bot, config, connected=False)
    deadline = time.monotonic()+args.seconds
    with State(config).locked() as state:
        export(state, args.output)
        print(json.dumps(dict(listening=True, fresh_events_needed=3-len(state.data['rows']),
                              seconds=args.seconds)), flush=True)
        while time.monotonic() < deadline and len(state.data['rows']) < 3:
            try:
                trigger = journal_trigger(config, 'C')
                validate_trigger(config, trigger)
                if trigger.received_at < args.not_before:
                    raise Blocked('fresh_authorized_test_group_event_required')
                sha = hashlib.sha256((root/'assets/fumens/Oni/649.png').read_bytes()).hexdigest()
                row = state.reserve('C', trigger.message_id, sha)
            except Blocked as exc:
                if str(exc) in ('fresh_authorized_test_group_event_required', 'event_already_consumed',
                                'minimum_interval_not_elapsed'):
                    await asyncio.sleep(1)
                    continue
                raise
            index = len(state.data['rows'])-1
            row['variant'] = ('before', 'static-first', 'static-repeat')[index]
            provider, delivery = before if index == 0 else after
            metrics = dict(png_reads=0, temporary_writes=0, brief_ms=0., markdown_ms=0.)
            originals = []
            def measured(obj, name, metric, count=False):
                original = getattr(obj, name)
                def wrapped(*a, **kw):
                    started = time.perf_counter()
                    try:
                        return original(*a, **kw)
                    finally:
                        metrics[metric] += 1 if count else (time.perf_counter()-started)*1000
                originals.append((obj, name, original))
                setattr(obj, name, wrapped)
            measured(provider, 'brief', 'brief_ms')
            measured(cache, 'write_public_image', 'temporary_writes', True)
            measured(MessageSegment, 'markdown', 'markdown_ms')
            # Instrument the known source file only; no production file patches.
            old_open = Path.open
            def opened(path, *a, **kw):
                if path == root/'assets/fumens/Oni/649.png':
                    metrics['png_reads'] += 1
                return old_open(path, *a, **kw)
            originals.append((Path, 'open', old_open))
            Path.open = opened
            sends = 0
            class Matcher:
                async def send(self, message):
                    nonlocal sends
                    # A baseline exception handler cannot issue a second API.
                    if sends:
                        raise Blocked('second_send_forbidden')
                    sends += 1
                    if len(message) != 1 or message[0].type != 'markdown':
                        raise Blocked('unexpected_message')
                    if index and (metrics['png_reads'] or metrics['temporary_writes']):
                        raise Blocked('static_path_unexpected_png_io')
                    row.update(metrics)
                    row['pipeline_ms'] = (time.perf_counter()-started)*1000
                    call = {}
                    row['calls'].append(call)
                    state.save()
                    await transport.call('post_group_messages', dict(group_openid=config.group_openid,
                        msg_type=2, markdown=message[0].data['markdown'], msg_id=trigger.message_id,
                        msg_seq=1), call, state.save)
                async def finish(self, message=None, **kwargs):
                    if message is not None:
                        await self.send(message)
                    raise FinishedException
            started = time.perf_counter()
            try:
                with provider.catalog_request():
                    search_start = time.perf_counter()
                    result = execute_song(CommandContext(text='id649是什么歌'), SongPorts(
                        _extract_what_song_query=lambda text: 'id649',
                        _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
                        _resolve_what_song_query=provider.resolve))
                    row['search_command_ms'] = (time.perf_counter()-search_start)*1000
                    await delivery.deliver(Matcher(), SimpleNamespace(group_openid=config.group_openid,
                        id=trigger.message_id), result)
            except FinishedException:
                row['status'] = 'acknowledged'
            except BaseException as exc:
                # Baseline may catch a transport exception; consult write-ahead
                # call state as well. Never retry timeout/unknown results.
                unknown = ((isinstance(exc, ApiFailure) and exc.unknown)
                    or any(c.get('status') == 'unknown' or c.get('http_status', 0) >= 500
                           or c.get('http_status') in (201, 202) for c in row['calls']))
                row['status'] = 'unknown' if unknown else 'error'
                row['error'] = exc.public() if isinstance(exc, ApiFailure) else {'category': type(exc).__name__}
                state.data['blocked_modes'].append('C')
            finally:
                for obj, name, original in reversed(originals):
                    setattr(obj, name, original)
                row['finished_at'] = time.time()
                state.data['last_finished'] = row['finished_at']
                state.save()
                export(state, args.output)
            print(json.dumps(dict(sample=row['sample'], variant=row['variant'], status=row['status'],
                                  api_calls=sum(c.get('http_requests', 0) for c in row['calls']))), flush=True)
            if row['status'] != 'acknowledged':
                break
        export(state, args.output)
        print(json.dumps(dict(completed=len(state.data['rows']),
                              native_client_acceptance='PENDING')), flush=True)


def clean(args):
    """Remove ONLY this experiment's public files; preserve private evidence."""
    config = Config.load(args.private/'config.json')
    publication = Path(config.static_root)
    if publication.name != 'song-query-phase2':
        raise Blocked('cleanup_namespace_mismatch')
    from taiko_bot.static_fumens import MANIFEST, read_bounded
    if read_bounded(publication/'.static-fumen-publication', 64) != b'public-static-fumen-v1\n':
        raise Blocked('cleanup_marker_mismatch')
    (args.private/'runtime/songs'/MANIFEST).unlink(missing_ok=True)
    # Namespace ownership was checked before publication; never delete parent.
    shutil.rmtree(publication)
    print(json.dumps(dict(owned_public_test_assets_removed=True)), flush=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('action', choices=['prepare', 'listen', 'clean'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--previous-config', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--chart', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seconds', type=int, default=480)
    parser.add_argument('--not-before', type=float, default=time.time())
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('QA_RUN_ID') or not args.live:
        raise Blocked('use_memory_qa_runner_and_explicit_live_opt_in')
    if not 1 <= args.seconds <= 600:
        raise Blocked('listener_time_budget')
    sys.path[:0] = [str(args.source), str(args.source/'packages/taiko-application/src')]
    if args.action == 'prepare':
        prepare(args)
    elif args.action == 'clean':
        clean(args)
    else:
        asyncio.run(listen(args))


if __name__ == '__main__':
    try:
        main()
    except Blocked as exc:
        print(json.dumps(dict(blocked=str(exc))), flush=True)
        sys.exit(2)
    except Exception as exc:
        # SDK errors may contain private request/response fields.
        print(json.dumps(dict(error_type=type(exc).__name__)), flush=True)
        sys.exit(1)
