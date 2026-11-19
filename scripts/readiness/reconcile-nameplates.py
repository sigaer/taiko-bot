"""Reconcile every official nameplate locally, with no network downloads.

Stage all canonical images before touching the source. Only obsolete IDs
explicitly identified by the archive and byte-identical to a canonical image
can be removed. Derived backgrounds and other resources are preserved.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from taiko_bot.offline.dress_import.package import DataParser, read_service
from taiko_bot.offline.nameplate_import import MODULE_MARKER, parse_nameplate_assets, validate_png


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bounded_png(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected a regular PNG: {path.name}')
    with path.open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024)
    dimensions = validate_png(raw)
    return raw, dimensions


def catalog(service):
    expected = parse_nameplate_assets(service)
    start = service.index(MODULE_MARKER) + len(MODULE_MARKER)
    end = service.find('},"./', start)
    module = service[start:end if end >= 0 else len(service)]
    match = re.search(r'\bvar\s+\w+\s*=\s*(\[)', module)
    rows = DataParser(module[match.start(1):], {}, {}).value()
    obsolete = {}
    for row in rows:
        background = row.get('rarity', row['id'])
        if background == row['id']:
            continue
        for prefix in ('name_plate_', 'name_plate_dani_'):
            old = f"{prefix}{row['id']}.png"
            canonical = f'{prefix}{background}.png'
            # An old ID can be another valid current background: never delete it.
            if old not in expected:
                obsolete[old] = canonical
    return expected, obsolete


def reconcile(service, source, stage, *, apply=False):
    source = source.resolve(strict=True)
    stage = stage.resolve()
    if stage.is_relative_to(source) or source.is_relative_to(stage):
        raise ValueError('Staging must be outside the source assets')
    expected, obsolete = catalog(service)
    images = stage / 'name_plate'
    images.mkdir(parents=True, exist_ok=False)
    manifest = {'files': {}, 'obsolete': {}, 'preserved': [], 'removed': []}
    # Validate the entire catalog, including collisions, before source mutations.
    for name, url in expected.items():
        candidates = [source / name]
        candidates.extend(source / old for old, current in obsolete.items() if current == name)
        available = [path for path in candidates if path.exists() or path.is_symlink()]
        if not available:
            raise ValueError(f'Missing image: {name}')
        raw, dimensions = bounded_png(available[0])
        sha = hashlib.sha256(raw).hexdigest()
        for path in available[1:]:
            alias, _ = bounded_png(path)
            if hashlib.sha256(alias).hexdigest() != sha:
                raise ValueError(f'Conflicting local image: {path.name}')
        (images / name).write_bytes(raw)
        manifest['files'][name] = {'url': url, 'sha256': sha, 'size': len(raw),
                                   'dimensions': dimensions, 'reusedFrom': available[0].name}
    for old, current in obsolete.items():
        path = source / old
        if path.exists() or path.is_symlink():
            raw, _ = bounded_png(path)
            sha = hashlib.sha256(raw).hexdigest()
            if sha != manifest['files'][current]['sha256']:
                raise ValueError(f'Obsolete image differs: {old}')
            manifest['obsolete'][old] = {'canonical': current, 'sha256': sha}
    manifest['preserved'] = sorted(path.name for path in source.iterdir()
                                    if path.name not in expected and path.name not in manifest['obsolete'])
    report = stage / 'reconciliation.json'
    report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    if apply:
        # Recheck all source identities/content before publishing or deleting.
        for name, item in manifest['files'].items():
            path = source / item['reusedFrom']
            bounded_png(path)
            if digest(path) != item['sha256']:
                raise ValueError(f'Source changed: {path.name}')
        for old, item in manifest['obsolete'].items():
            bounded_png(source / old)
            if digest(source / old) != item['sha256']:
                raise ValueError(f'Source changed: {old}')
        for name, item in manifest['files'].items():
            path = source / name
            if not path.exists():
                with path.open('xb') as stream:
                    stream.write((images / name).read_bytes())
                path.chmod(0o644)
            bounded_png(path)
            if digest(path) != item['sha256']:
                raise ValueError(f'Canonical image changed: {name}')
        for old, item in manifest['obsolete'].items():
            path = source / old
            bounded_png(path)
            if digest(path) != item['sha256'] or digest(source / item['canonical']) != item['sha256']:
                raise ValueError(f'Image changed before cleanup: {old}')
            path.unlink()
            manifest['removed'].append(old)
        report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('source', type=Path)
    parser.add_argument('stage', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('QA_RUN_ID'):
        parser.error('Run through scripts/memory/run_qa.sh')
    result = reconcile(read_service(args.archive), args.source, args.stage, apply=args.apply)
    print(json.dumps({'canonicalFiles': len(result['files']), 'reusedFiles': len(result['files']),
                      'obsoleteFiles': len(result['obsolete']), 'removed': len(result['removed']),
                      'preserved': result['preserved'], 'downloads': 0}))


if __name__ == '__main__':
    main()
