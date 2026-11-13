"""Same real chart, three official-QQ paths, six fresh passive test events.

Run through memory/run_qa.sh. Reuses the previously approved private target;
never starts a gateway, changes production, retries or sends proactively.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qq_delivery.config import Blocked, Config, private_directory
from qq_delivery.events import journal_trigger, standalone_bot, validate_trigger
from qq_delivery.state import State, atomic_json
from qq_delivery.transport import ApiFailure, Transport, inventory


def export(state, args, preflight):
    fields = ('sample', 'variant', 'status', 'calls', 'error', 'api_total_ms',
              'local_prepare_ms', 'finished_at', 'image_sha256')
    args.output.write_text(json.dumps(dict(schema=1, qa_run_id=os.environ['QA_RUN_ID'],
        preflight=preflight, environment=inventory(), auth_warmed_before_samples=True,
        service_changed=False, passive_only=True,
        samples=[{k: row[k] for k in fields if k in row} for row in state.data['rows']],
        scope='Official QQ API only; client display, client profile, OneBot OUT OF SCOPE',
        note='Interleaved exploratory samples; no automatic retry; native total includes upload and message API.'
    ), ensure_ascii=False, indent=2)+'\n')


async def run(args):
    import httpx
    from nonebot.adapters.qq import MessageSegment
    from nonebot.adapters.qq.models import Media
    # Only this experiment's new config/state, never the old config or service.
    old = Config.load(args.previous_config)
    if not old.markdown_authorized or not old.domain_whitelisted:
        raise Blocked('existing_markdown_domain_authorization_required')
    private_directory(args.private)
    config_path = args.private/'config.json'
    if config_path.exists():
        raise Blocked('existing_experiment_do_not_resume_automatically')
    config = Config(**asdict(old))
    config.private_dir = str(args.private)
    config.phase, config.round_id = 'protocol', 'fixed-url-comparison'
    config.max_sends_per_round, config.max_samples_per_mode = 6, 2
    config.interval_seconds = 25
    config.validate_live()
    atomic_json(config_path, asdict(config))

    package = ModuleType('_qq_chart_compare')
    package.__path__ = [str(args.source/'taiko_bot/runtime/public')]
    module = ModuleType(package.__name__+'.config')
    module.root, module.profile = lambda: args.root, lambda: 'center'
    sys.modules[package.__name__], sys.modules[module.__name__] = package, module
    images = importlib.import_module(package.__name__+'.fumen_url')
    messages = importlib.import_module(package.__name__+'.center_messages')
    os.environ['TAIKO_QQ_FIXED_FUMEN_URL'] = '1'
    markup = images.markdown_image('Oni', '649')
    if markup is None:
        raise Blocked('local_chart_unavailable')
    chart = args.root/'assets/fumens/Oni/649.png'
    payload = chart.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()  # Benchmark equality only.
    url = markup.split('](', 1)[1][:-1]
    async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
        response = await client.get(url)  # Outside player path and API timing.
    if (response.status_code != 200 or response.headers.get('content-type', '').split(';')[0] != 'image/png'
            or hashlib.sha256(response.content).hexdigest() != sha):
        raise Blocked('viewer_chart_not_identical_or_unavailable')
    preflight = dict(url=url, status=200, bytes=len(payload), sha256=sha,
                     https_verified=True, equal_to_local=True)
    bot = standalone_bot(config)
    await bot.get_authorization_header()  # Exclude cold token fetch equally.
    transport = Transport(bot, config, connected=False)
    # Use the normal existing 30-minute cache, cleaned by the existing service.
    # Globals are local to this isolated worker; no production cache-policy edit.
    import taiko_bot.runtime.center_markdown_media as cache
    cache.QQ_MARKDOWN_IMAGE_CACHE_DIR = Path('/home/sigaer/taiko/output/qq_markdown_cache')
    cache.QQ_MARKDOWN_IMAGE_BASE_URL = 'https://viewer.sakura-bot.cn/qqbot-cache/taiko'
    order = ('native', 'random', 'fixed', 'fixed', 'random', 'native')
    provider = importlib.import_module(package.__name__+'.provider')
    hint = '你要找的是不是：\n魔王 id649\n'+provider.brief('649')
    not_before = time.time()
    deadline = time.monotonic()+args.seconds
    with State(config).locked() as state:
        export(state, args, preflight)
        print(json.dumps(dict(listening=True, fresh_events_needed=6, seconds=args.seconds)), flush=True)
        while time.monotonic() < deadline and len(state.data['rows']) < len(order):
            try:
                event = journal_trigger(config, 'C')
                validate_trigger(config, event)
                if event.received_at < not_before:
                    raise Blocked('fresh_authorized_test_group_event_required')
                variant = order[len(state.data['rows'])]
                row = state.reserve({'native': 'A-data', 'random': 'C', 'fixed': 'D'}[variant], event.message_id, sha)
            except Blocked as exc:
                if str(exc) in ('fresh_authorized_test_group_event_required', 'event_already_consumed',
                                'minimum_interval_not_elapsed'):
                    await asyncio.sleep(1)
                    continue
                raise
            row['variant'] = variant
            def call(api, **arguments):
                record = {}
                row['calls'].append(record)
                state.save()
                return transport.call(api, arguments, record, state.save)
            try:
                start = time.perf_counter()
                common = dict(group_openid=config.group_openid, msg_id=event.message_id, msg_seq=1)
                if variant == 'native':
                    data = chart.read_bytes()
                    row['local_prepare_ms'] = (time.perf_counter()-start)*1000
                    uploaded = await call('post_group_files', group_openid=config.group_openid,
                                          file_type=1, file_data=data, srv_send_msg=False)
                    await call('post_group_messages', **common, msg_type=7, content=hint,
                               media=Media(file_info=uploaded.file_info))
                else:
                    if variant == 'random':
                        message = messages._build_qq_reply_message(SimpleNamespace(id=event.message_id),
                            text=hint, image_bytes=BytesIO(chart.read_bytes()))
                        if len(message) != 1 or message[0].type != 'markdown':
                            raise Blocked('random_markdown_preparation_failed')
                        markdown = message[0].data['markdown']
                    else:
                        markdown = MessageSegment.markdown(hint+'\n\n'+images.markdown_image('Oni', '649')).data['markdown']
                    row['local_prepare_ms'] = (time.perf_counter()-start)*1000
                    await call('post_group_messages', **common, msg_type=2, markdown=markdown)
                row['status'] = 'acknowledged'
            except BaseException as exc:
                unknown = (isinstance(exc, ApiFailure) and exc.unknown
                           or any(c.get('status') == 'unknown' for c in row['calls']))
                row['status'] = 'unknown' if unknown else 'error'
                row['error'] = exc.public() if isinstance(exc, ApiFailure) else dict(category=type(exc).__name__)
            finally:
                row['api_total_ms'] = sum(c.get('total_ms', 0) for c in row['calls'])
                row['finished_at'] = time.time()
                state.data['last_finished'] = row['finished_at']
                state.save()
                export(state, args, preflight)
            print(json.dumps(dict(variant=variant, status=row['status'], api_total_ms=row['api_total_ms'])), flush=True)
            if row['status'] != 'acknowledged':
                break  # No fallback/retry after any attempted send/upload.
        print(json.dumps(dict(completed=len(state.data['rows']), expected=6)), flush=True)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--previous-config', type=Path, required=True)
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('QA_RUN_ID') or not args.live or not 1 <= args.seconds <= 600:
        raise Blocked('bounded_memory_qa_runner_and_explicit_live_required')
    sys.path[:0] = [str(args.source), str(args.source/'packages/taiko-application/src')]
    asyncio.run(run(args))


if __name__ == '__main__':
    try:
        main()
    except Blocked as exc:
        print(json.dumps(dict(blocked=str(exc))), flush=True)
        sys.exit(2)
    except Exception as exc:
        print(json.dumps(dict(error_type=type(exc).__name__)), flush=True)
        sys.exit(1)
