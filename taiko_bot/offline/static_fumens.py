"""Publish ONLY explicit hash-bound public grants, verify HTTPS, then manifest.

Never invoked by a player query or the daily production updater. The operator
provides an already-approved isolated/static publication root and policy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import httpx
from PIL import Image

from taiko_bot.static_fumens import (
    MAX_BYTES, MAX_LEASE, MAX_PIXELS, MANIFEST, POLICY, asset_url, base_url,
    canonical, digest, key, policy_grants, read_bounded, safe_file, validate_manifest,
)


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.static-fumen-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def checked_image(path, sha256):
    if not 8 <= path.stat().st_size <= MAX_BYTES:
        raise ValueError('image_size')
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            hasher.update(chunk)
    if hasher.hexdigest() != sha256:
        raise ValueError('source_hash')
    with Image.open(path) as image:
        width, height = image.size
        if (image.format != 'PNG' or not 0 < width <= 8192 or not 0 < height <= 65536
                or width*height > MAX_PIXELS):
            raise ValueError('image_geometry')
        image.verify()
    with Image.open(path) as image:
        image.load()
    return width, height


def copy_verified(source, destination, expected_hash):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError('publication_symlink')
    destination.parent.chmod(0o755)
    fd, temporary = tempfile.mkstemp(prefix='.static-fumen-', dir=destination.parent)
    try:
        hasher = hashlib.sha256()
        size = 0
        with os.fdopen(fd, 'wb') as target, source.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('source_grew')
                hasher.update(chunk)
                target.write(chunk)
            if hasher.hexdigest() != expected_hash:
                raise ValueError('source_changed')
            target.flush()
            os.fchmod(target.fileno(), 0o644)
            os.fsync(target.fileno())
        # Content addressed paths can only ever be replaced by identical bytes.
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_https(client, url, sha256, expected_size):
    hasher, size = hashlib.sha256(), 0
    with client.stream('GET', url, follow_redirects=False) as response:
        if response.status_code != 200 or response.headers.get('content-type', '').split(';')[0].strip().lower() != 'image/png':
            raise ValueError('https_status_or_type')
        for chunk in response.iter_bytes(65536):
            size += len(chunk)
            if size > MAX_BYTES or size > expected_size:
                raise ValueError('https_size')
            hasher.update(chunk)
    if size != expected_size or hasher.hexdigest() != sha256:
        raise ValueError('https_content')


def publish(root, publication_root, allowed_base, client, *, now=None, lease=300):
    now = time.time() if now is None else now
    if not 1 <= lease <= MAX_LEASE:
        raise ValueError('invalid verification lease')
    root, publication_root = Path(root), Path(publication_root)
    if publication_root.is_symlink() or not publication_root.is_absolute():
        raise ValueError('invalid publication root')
    base = base_url(allowed_base)
    songs = safe_file(root, 'songs')
    policy_path = safe_file(songs, POLICY)
    policy_bytes = read_bounded(policy_path, 4*1024*1024)
    policy = json.loads(policy_bytes)
    policy_hash = digest(policy_bytes)
    grants = policy_grants(policy, base, now)
    publication_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    marker = safe_file(publication_root, '.static-fumen-publication')
    if marker.exists():
        if read_bounded(marker, 64) != b'public-static-fumen-v1\n':
            raise ValueError('unknown publication directory')
    else:
        if any(publication_root.iterdir()):
            raise ValueError('dedicated empty publication directory required')
        atomic_write(marker, b'public-static-fumen-v1\n')
    publication_root.chmod(0o755)
    entries, rejected = [], []
    for grant in policy['grants']:
        difficulty, sid = grant['difficulty'], str(grant['song_id'])
        item_key = key(difficulty, sid)
        try:
            directory = safe_file(safe_file(root, 'assets'), 'fumens')
            source = safe_file(safe_file(directory, difficulty), sid+'.png')
            width, height = checked_image(source, grants[item_key])
            destination = safe_file(safe_file(publication_root, 'sha256'), grants[item_key]+'.png')
            copy_verified(source, destination, grants[item_key])
            url = asset_url(base, grants[item_key])
            verify_https(client, url, grants[item_key], source.stat().st_size)
            entries.append(dict(difficulty=difficulty, song_id=sid, url=url, width=width, height=height,
                                sha256=grants[item_key], resource_version=grants[item_key]))
        except (OSError, ValueError, httpx.HTTPError, Image.DecompressionBombError):
            rejected.append(item_key)
    # If rights changed during preparation, nothing may switch to this manifest.
    if digest(read_bounded(policy_path, 4*1024*1024)) != policy_hash:
        raise ValueError('authorization changed during publication')
    entries.sort(key=lambda row: (row['difficulty'], int(row['song_id'])))
    payload = dict(schema=1, policy_sha256=policy_hash, checked_at=now,
                   valid_until=min(now+lease, policy['valid_until']), entries=entries,
                   resource_version=digest(canonical(dict(policy_sha256=policy_hash, entries=entries))))
    validate_manifest(payload, policy, policy_hash, base, now)
    atomic_write(safe_file(songs, MANIFEST), canonical(payload)+b'\n')
    return dict(published=len(entries), rejected=rejected, resource_version=payload['resource_version'])


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--publication-root', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    args = parser.parse_args()
    if not os.environ.get('QA_RUN_ID'):
        parser.error('run this offline publication command through the memory QA runner')
    # Offline publishing is a deliberate separate action, never a startup side effect.
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        result = publish(args.root, args.publication_root, args.base_url, client)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
