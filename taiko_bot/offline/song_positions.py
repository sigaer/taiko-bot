"""Refresh the compact national position index, independently of other jobs."""
import argparse
from collections import defaultdict
from datetime import datetime
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import requests

from taiko_bot.song_positions import GENRES, INDEX_NAME, MAX_INDEX_BYTES, load_index, validate_index
from .paths import root
from .song_position_matching import SongTable, match_song, normalize_title

LOGGER = logging.getLogger(__name__)
BASE_URL = 'https://taiko.namco-ch.net/taiko/en/songlist/'
MAX_PAGE_BYTES = 1_000_000


def fetch_official_pages(session):
    pages = {}
    for slug in GENRES:
        with session.get(BASE_URL + slug + '.php', timeout=(10, 20), stream=True) as response:
            response.raise_for_status()
            blob = bytearray()
            for chunk in response.iter_content(65536):
                blob.extend(chunk)
                if len(blob) > MAX_PAGE_BYTES:
                    raise ValueError('Official song page exceeds size budget')
        parser = SongTable()
        parser.feed(blob.decode('utf-8'))
        if len(parser.rows) < 20:
            raise ValueError('Official song page missing or markup changed: ' + slug)
        pages[slug] = parser.rows
    return pages


def build_index(live_rows, official_pages, *, updated_at=None):
    by_id, by_title, memberships = {}, defaultdict(set), {name: set() for name in GENRES.values()}
    for row in live_rows:
        sid, genre = row.get('id'), row.get('type')
        if type(sid) is not int or sid < 0 or genre not in memberships:
            raise ValueError('Invalid live national song record')
        by_id.setdefault(sid, row)
        memberships[genre].add(sid)
        for key in ('song_name_jp', 'song_name'):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                by_title[normalize_title(value)].add(sid)
    if not by_id or set(official_pages) != set(GENRES):
        raise ValueError('Missing national roster or official categories')
    categories = {}
    for slug, genre in GENRES.items():
        ordered, seen = [], set()
        for row in official_pages[slug]:
            sid = match_song(slug, row, by_title, by_id)
            if sid is None or sid not in memberships[genre]:
                continue
            if sid in seen:
                raise ValueError('Conflicting duplicate reference song: ' + str(sid))
            ordered.append(sid)
            seen.add(sid)
        categories[genre] = {'ordered': ordered, 'pending': sorted(memberships[genre] - seen)}
    payload = {'version': 1, 'updated_at': updated_at or datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
               'categories': categories}
    return validate_index(payload)


def _atomic_bytes(path, blob):
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp', delete=False) as handle:
            name = handle.name
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        name = None
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def publish_index(path, payload):
    validate_index(payload)
    blob = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
    if len(blob) > MAX_INDEX_BYTES:
        raise ValueError('Position index exceeds size limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            # Do not replace an unreadable generation without an explicit repair.
            load_index(path)
            _atomic_bytes(path.with_suffix(path.suffix + '.previous'), path.read_bytes())
        _atomic_bytes(path, blob)
    return len(blob)


def refresh_positions(live_rows, *, output_path=None, official_pages=None):
    if not isinstance(live_rows, list) or not 500 <= len({row.get('id') for row in live_rows if isinstance(row, dict)}) < 3000:
        raise ValueError('National listing incomplete; positions not published')
    if official_pages is None:
        with requests.Session() as session:
            official_pages = fetch_official_pages(session)
    payload = build_index(live_rows, official_pages)
    categories = payload['categories']
    matched = {sid for category in categories.values() for sid in category['ordered']}
    total = {sid for category in categories.values() for key in ('ordered', 'pending') for sid in category[key]}
    if len(matched) < .8 * len(total):
        raise ValueError('Reference matching coverage dropped; positions not published')
    path = output_path or root() / 'songs' / INDEX_NAME
    size = publish_index(Path(path), payload)
    return {'songs': len(total), 'matched': len(matched),
            'pending_memberships': sum(len(category['pending']) for category in categories.values()), 'bytes': size}


def refresh_positions_safely(live_rows, *, output_path=None):
    try:
        result = refresh_positions(live_rows, output_path=output_path)
        LOGGER.info('国行位置索引更新完成: songs=%d matched=%d pending=%d bytes=%d',
                    result['songs'], result['matched'], result['pending_memberships'], result['bytes'])
        return result
    except Exception:
        LOGGER.exception('国行位置索引更新失败，保留上一份数据')
        return None


def main():
    parser = argparse.ArgumentParser(description='Refresh only the compact national song positions')
    parser.add_argument('--output', type=Path, default=root() / 'songs' / INDEX_NAME)
    args = parser.parse_args()
    # Same read-only listing used by the daily updater. Keep its token private.
    config = json.loads((root() / 'config.json').read_text(encoding='utf-8'))
    with requests.Session() as session:
        response = session.post('https://wl-taiko.wahlap.net/api/user/all/songs',
                                json={'page': 1, 'pageSize': 3000, 'sort': 1, 'isPlayed': True},
                                headers={'Authorization': config['cookie'],
                                         'Referer': 'https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html'}, timeout=(10, 30))
        response.raise_for_status()
        live_rows = response.json()['data']['list']
        result = refresh_positions(live_rows, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
