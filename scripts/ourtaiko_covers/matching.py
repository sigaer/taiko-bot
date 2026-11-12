"""Resolve explicit catalog identifiers; never guess from similar titles."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import re


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def number(value):
    return str(value) if str(value).isdigit() and int(value) > 0 else None


def build_plan(charts_path, songs_path, covers):
    exported = json.loads(Path(charts_path).read_text(encoding='utf-8'))
    charts = exported['charts'] if isinstance(exported, dict) else exported
    songs = json.loads(Path(songs_path).read_text(encoding='utf-8'))
    indexes = {key: defaultdict(set) for key in ('source', 'nijiiro', 'official')}
    by_id = {}
    for song in songs:
        sid = number(song['id'])
        if sid is None or sid in by_id:
            raise ValueError('Invalid or duplicate local song ID')
        by_id[sid] = song
        indexes['nijiiro'][sid].add(sid)
        for source in song.get('ourtaiko_ids', []):
            indexes['source'][source].add(sid)
        if song.get('official_id'):
            indexes['official'][str(song['official_id'])].add(sid)
    rows, seen = [], set()
    for chart in charts:
        cid = chart.get('id', '')
        if not re.fullmatch('[0-9a-f]{32}', cid) or cid in seen:
            raise ValueError('Invalid or duplicate upstream chart ID')
        seen.add(cid)
        row = {'chartId': cid, 'title': chart.get('title', ''), 'status': 'unmatched'}
        rows.append(row)
        if chart.get('status', 'published') != 'published':
            row['status'] = 'unpublished'
            continue
        matches = {}
        values = {'source': cid, 'nijiiro': number(chart.get('nijiiro_id', chart.get('nijiiroId'))),
                  'official': chart.get('official_id', chart.get('officialId'))}
        for key, value in values.items():
            if value is not None and indexes[key].get(str(value)):
                matches[key] = indexes[key][str(value)]
        candidates = set().union(*matches.values()) if matches else set()
        if len(candidates) != 1:
            if candidates:
                row.update(status='ambiguous', candidates=sorted(candidates))
            continue
        sid = next(iter(candidates))
        # An explicitly supplied Nijiiro ID must agree even when absent locally.
        if values['nijiiro'] and values['nijiiro'] != sid:
            row.update(status='identifier_conflict', localId=sid)
            continue
        row.update(localId=sid, matchedBy=sorted(matches))
        files = [Path(covers) / (sid + ext) for ext in ('.png', '.jpg', '.jpeg', '.webp')]
        files = [p for p in files if p.is_file()]
        if not files:
            # Catalog reconciliation reserves these historical IDs for this song.
            # Read the existing art in place; never copy/rename production assets.
            files = [Path(covers) / (str(old) + ext)
                     for old in by_id[sid].get('legacy_ids', []) if number(old)
                     for ext in ('.png', '.jpg', '.jpeg', '.webp')]
            files = [p for p in files if p.is_file()]
            if files:
                row['coverFromLegacyId'] = True
        if not files:
            row['status'] = 'missing_cover'
            continue
        if len(files) != 1:
            row['status'] = 'ambiguous_cover'
            continue
        path = files[0].resolve()
        row.update(path=str(path), sourceSha256=digest(path),
                   hadCover=bool(chart.get('cover_file') or chart.get('coverHash')))
        # Decode locally before making any upload. Server performs its own validation.
        from PIL import Image
        try:
            with Image.open(path) as image:
                width, height = image.size
                if (image.format not in ('PNG', 'JPEG', 'WEBP') or
                        width * height > 16_000_000 or max(width, height) > 8192 or
                        path.stat().st_size > 8 * 1024 ** 2):
                    raise ValueError('Image exceeds server constraints')
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            row['status'] = 'invalid_cover'
            continue
        row['status'] = 'ready'
    return {'chartsSha256': digest(charts_path), 'songsSha256': digest(songs_path), 'rows': rows}
