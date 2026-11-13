"""Bounded public-resource audit; private test identities are never exported."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx
from PIL import Image

assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qq_delivery.config import Config

result = dict(authorization='User confirmed all chart images may be public in this conversation (2026-11-13).',
              folders={}, selected=[], https=[], qa_run_id=os.environ['QA_RUN_ID'])
source = Path('/home/sigaer/taiko/assets/fumens')
for difficulty in ('Kantan', 'Futsuu', 'Muzukashii', 'Oni', 'InnerOni'):
    files = list((source/difficulty).glob('*.png'))
    assert len(files) <= 20000
    result['folders'][difficulty] = dict(files=len(files), bytes=sum(path.stat().st_size for path in files))
    for sid in (649, 354):
        path = source/difficulty/f'{sid}.png'
        if path.is_file():
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(65536), b''):
                    hasher.update(chunk)
            with Image.open(path) as image:
                size = image.size
            result['selected'].append(dict(difficulty=difficulty, song_id=sid, sha256=hasher.hexdigest(),
                                           width=size[0], height=size[1], bytes=path.stat().st_size))
config = Config.load(Path('/var/tmp/taiko-qq-delivery-private/config.json'))
result['previous_test'] = dict(config_found=True, bot_configured=bool(config.bot_id), group_configured=bool(config.group_openid),
    administrators=len(config.admin_openids), active_permission=config.active_permission,
    group_active_allowed=config.group_active_allowed, active_test_authorized=config.active_test_authorized,
    markdown_authorized=config.markdown_authorized, domain_whitelisted=config.domain_whitelisted,
    static_root=config.static_root, static_base_url=config.static_base_url,
    cleanup_timer=config.cleanup_timer_unit, timeout_seconds=config.timeout_seconds)
with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
    for url in ('https://viewer.sakura-bot.cn/api/taiko/manifest',
                'https://viewer.sakura-bot.cn/api/content/songs/649/chart-image?difficulty=4'):
        start = time.perf_counter()
        row = dict(endpoint=url, method='GET')
        try:
            with client.stream('GET', url) as response:
                row.update(status=response.status_code, content_type=response.headers.get('content-type'),
                           cache_control=response.headers.get('cache-control'), etag=response.headers.get('etag'))
                size, hasher = 0, hashlib.sha256()
                for chunk in response.iter_bytes(65536):
                    size += len(chunk)
                    if size > 16*1024*1024:
                        raise ValueError('audit response exceeded budget')
                    hasher.update(chunk)
                row.update(bytes=size, sha256=hasher.hexdigest())
        except (httpx.HTTPError, ValueError) as error:
            row['error_type'] = type(error).__name__
        row['elapsed_ms'] = (time.perf_counter()-start)*1000
        result['https'].append(row)
output = Path('/var/tmp/taiko-song-query-phase2-evidence')
output.mkdir(parents=True, exist_ok=True)
(output/'resource-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(result, ensure_ascii=False))
