"""Verify and materialize the Taiko-owned private resource manifest.

No network, credential discovery, player data or implicit production directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def verify(manifest, store):
    entries = json.loads(Path(manifest).read_text())['entries']
    if not isinstance(entries, list):
        raise ValueError('Invalid resource manifest')
    seen = set()
    resolved = []
    objects = Path(store) / 'objects'
    if objects.is_symlink():
        raise ValueError('Resource objects must not be a symlink')
    for entry in entries:
        path = PurePosixPath(entry['path'])
        digest = entry['sha256']
        if path.is_absolute() or '..' in path.parts or not path.parts or str(path) != entry['path'] or str(path) in seen:
            raise ValueError('Unsafe or duplicate resource path')
        if not re.fullmatch('[a-f0-9]{64}', digest) or type(entry['bytes']) is not int or entry['bytes'] < 0:
            raise ValueError('Invalid resource digest or size')
        seen.add(str(path))
        source = objects / digest
        if source.is_symlink() or not source.is_file() or source.stat().st_size != entry['bytes'] or sha256(source) != digest:
            raise ValueError('Resource content verification failed')
        resolved.append((path, source, digest))
    return resolved


def materialize(manifest, store, destination):
    entries = verify(manifest, store)
    destination = Path(destination).absolute()
    # Preflight the complete set before any writes; never replace differing runtime files.
    for relative, source, digest in entries:
        target = destination / relative
        if any(parent.is_symlink() for parent in (target, *target.parents)):
            raise ValueError('Resource destination contains a symlink')
        if target.exists() and (not target.is_file() or sha256(target) != digest):
            raise ValueError('Existing resource differs from manifest')
    written = 0
    for relative, source, digest in entries:
        target = destination / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.resource-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
                shutil.copyfileobj(stream, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if sha256(Path(temporary)) != digest:
                raise ValueError('Resource changed while copying')
            # link is an atomic no-overwrite installation; a racing writer wins safely.
            os.link(temporary, target)
            written += 1
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {'verified': len(entries), 'written': written}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'materialize'])
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.action == 'verify':
        result = {'verified': len(verify(args.manifest, args.store))}
    else:
        if args.destination is None:
            parser.error('materialize requires --destination')
        result = materialize(args.manifest, args.store, args.destination)
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
