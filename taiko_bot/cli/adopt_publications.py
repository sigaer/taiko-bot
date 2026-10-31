"""Explicit, bounded legacy C/H migration; no SQL or score reconstruction."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat

from taiko_store.publication import PublicationError, PublicationStore, _identity, _history_name

MAX_IDENTITIES = 4096
MAX_TOTAL_BYTES = 4 * 1024**3


def inspect(root, identity):
    """Preflight without constructing a store or acquiring a recovery lease."""
    identity = _identity(identity)
    for directory in (root, root / '.taiko-publications', root / '.taiko-publications' / identity):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise PublicationError('Migration directory is not plain')
    manifest = root / '.taiko-publications' / identity / 'committed.json'
    if manifest.is_symlink():
        raise PublicationError('Migration manifest is not plain')
    if manifest.exists():
        return {'status': 'managed', 'files': 0, 'bytes': 0}
    current = root / (identity + 'data.json')
    if current.is_symlink():
        raise PublicationError('Migration current is not plain')
    if not current.exists():
        return {'status': 'missing_current', 'files': 0, 'bytes': 0}
    paths = [current]
    history = root / identity
    if history.is_symlink() or (history.exists() and not history.is_dir()):
        raise PublicationError('Migration history is not plain')
    if history.exists():
        for path in history.iterdir():
            if path.name.startswith('data_') and path.name.endswith('.json'):
                _history_name(path.name)
                paths.append(path)
                if len(paths) > 50001:
                    raise PublicationError('Migration history file limit exceeded')
    total, history_bytes = 0, 0
    for path in paths:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024**2:
            raise PublicationError('Migration input is not a bounded plain file')
        total += info.st_size
        if path != current:
            history_bytes += info.st_size
    if history_bytes > 2 * 1024**3:
        raise PublicationError('Migration history byte limit exceeded')
    return {'status': 'legacy', 'files': len(paths), 'bytes': total}


def migrate(root, identities, *, apply=False, writers_coordinated=False):
    root = Path(root).absolute()
    if not root.is_dir() or root.is_symlink():
        raise PublicationError('Migration root must be an existing plain directory')
    if (not isinstance(identities, list) or not 1 <= len(identities) <= MAX_IDENTITIES
            or any(not isinstance(identity, str) for identity in identities)
            or len(set(identities)) != len(identities)):
        raise PublicationError('Migration identity list is invalid')
    if apply and not writers_coordinated:
        raise PublicationError('Fence legacy writers before migration')
    plan = [(identity, inspect(root, identity)) for identity in identities]
    total = sum(item['bytes'] for _, item in plan)
    if total > MAX_TOTAL_BYTES:
        raise PublicationError('Migration batch byte limit exceeded')
    if apply and shutil.disk_usage(root).free < total + 256 * 1024**2:
        raise PublicationError('Insufficient migration disk headroom')
    summary = {'legacy': 0, 'managed': 0, 'missing_current': 0,
               'files': 0, 'bytes': total, 'adopted': 0}
    for identity, item in plan:
        summary[item['status']] += 1
        summary['files'] += item['files']
        if apply and item['status'] != 'missing_current':
            store = PublicationStore(root, identity)
            with store.exclusive():
                # Recheck after EX; a new protocol writer may already have
                # adopted/published since preflight. Never rewind that head.
                previous = store.view()
                if previous is None:
                    fresh = inspect(root, identity)
                    if fresh['status'] != 'legacy' or fresh['bytes'] > item['bytes']:
                        raise PublicationError('Migration inputs changed; inspect again')
                manifest = store.adopt()
                for reference in manifest['files'].values():
                    store.read_object(reference)
                summary['adopted'] += previous is None
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--identities-file', required=True, help='Private JSON array; at most 4096 identities')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-coordinated', action='store_true', help='Old writers stopped; remaining writers use Source EX')
    args = parser.parse_args()
    try:
        fd = os.open(args.identities_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as incoming:
            if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                raise PublicationError('Migration list is not a plain file')
            raw = incoming.read(1024**2 + 1)
        if len(raw) > 1024**2:
            raise PublicationError('Migration list is too large')
        result = migrate(args.root, json.loads(raw), apply=args.apply, writers_coordinated=args.writers_coordinated)
        print(json.dumps({'ok': True, 'applied': args.apply, **result}))
    except (OSError, ValueError, PublicationError):
        # Paths and score identities remain in the private input, never logs.
        print(json.dumps({'ok': False, 'error': 'publication_migration_failed'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
