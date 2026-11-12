"""Build bounded PNG backfill plans from the same verified chart sources."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import shutil

from .catalog_downloads import catalog_resource_root
from .catalog_resources import safe_resource
from .ourtaiko_catalog import atomic_json, positive_id

COURSES = ('easy', 'normal', 'hard', 'oni', 'edit')
FOLDERS = ('Kantan', 'Futsuu', 'Muzukashii', 'Oni', 'InnerOni')
ARCHIVE_MARKER = 'logs/catalog_image_archive_pending.json'


def image_plan(catalog, *, root, ese_root, output_root=None):
    output_root = Path(output_root or root)
    jobs, issues = [], []
    for song in catalog:
        source_root = catalog_resource_root(song, ese_root, runtime_root=root)
        path = safe_resource(source_root, song.get('tja_path'))
        profiles = {(i, 'single'): positive_id(song.get(f'level_{i}')) for i in range(1, 6)}
        for row in song.get('ourtaiko_difficulties', []):
            if row.get('side') in ('p1', 'p2'):
                profiles[(int(row['difficulty']), row['side'])] = positive_id(row.get('level'))
        for (difficulty, side), level in profiles.items():
            if not level or difficulty not in range(1, 6):
                continue
            name = str(song['id']) + ('' if side == 'single' else '-' + side) + '.png'
            relative = Path('assets/fumens') / FOLDERS[difficulty - 1] / name
            if (Path(root) / relative).is_file() or (output_root / relative).is_file():
                continue
            if path is None:
                issues.append({'id': song['id'], 'course': COURSES[difficulty - 1], 'side': side, 'reason': 'tja_unavailable'})
                continue
            combos = song.get('max_combo') or ['-'] * 5
            notes = positive_id(combos[difficulty - 1]) if side == 'single' and len(combos) >= difficulty else None
            jobs.append({'id': song['id'], 'course': COURSES[difficulty - 1], 'side': side, 'level': level,
                         'notes': notes, 'title': (song.get('song_name') or song.get('song_name_jp') or str(song['id'])) + ('' if side == 'single' else f' [{side.upper()}]'),
                         'tja': str(path), 'output': str(output_root / relative)})
    return {'jobs': jobs, 'issues': issues, 'report': str(output_root / 'logs/catalog_image_report.json')}


def backfill_images(catalog, *, root, ese_root, limit=0):
    plan = image_plan(catalog, root=root, ese_root=ese_root)
    plan_path = Path(root) / 'logs/catalog_image_plan.json'
    atomic_json(plan_path, plan)
    if not plan['jobs']:
        report = {'planned': 0, 'generated': [], 'existing': [], 'issues': plan['issues']}
        atomic_json(Path(plan['report']), report)
        return report
    node = shutil.which('node')
    renderer = Path(root) / 'taiko-forum/taiko_viewer/scripts/render_catalog_images.mjs'
    if not node or not renderer.is_file():
        raise RuntimeError('Pinned chart image renderer unavailable')
    process = subprocess.Popen([node, str(renderer), str(plan_path), str(limit)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=600)
        if process.returncode:
            raise RuntimeError('Chart image renderer failed: ' + stderr[-500:])
    except BaseException:
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.communicate()
        raise
    finally:
        # Retain a retry marker even if a later chart or archive build fails.
        if any(Path(job['output']).is_file() for job in plan['jobs']):
            atomic_json(Path(root) / ARCHIVE_MARKER, {'pending': True})
    return json.loads(Path(plan['report']).read_text(encoding='utf-8'))


def publish_image_archives(*, root):
    marker = Path(root) / ARCHIVE_MARKER
    if not marker.is_file():
        return False
    script = Path('/home/sigaer/taiko-bot/scripts/build_open_resource_archives.sh')
    environment = dict(os.environ, TAIKO_SOURCE_ROOT=str(root))
    process = subprocess.Popen(['/bin/bash', str(script), 'fumens'], env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        _, stderr = process.communicate(timeout=900)
        if process.returncode:
            raise RuntimeError('Chart image archives failed: ' + stderr[-500:])
    except BaseException:
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); process.communicate()
        raise
    marker.unlink(missing_ok=True)
    return True


def main():
    from .paths import root as runtime_root
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=runtime_root())
    parser.add_argument('--ese-root', type=Path, default=Path('/home/sigaer/git/ESE_autosync'))
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    catalog = json.loads((args.root / 'songs/song_data.json').read_text(encoding='utf-8'))
    report = backfill_images(catalog, root=args.root, ese_root=args.ese_root, limit=args.limit)
    print(json.dumps({'generated': len(report['generated']), 'issues': len(report['issues'])}))


if __name__ == '__main__': main()
