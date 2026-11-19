#!/usr/bin/env python3
"""Remove older installed releases only after successful activation.

Current/newer releases and versions referenced by processes or service/cron
configuration survive. Inspection errors fail closed; no business data is read.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time

ROOT = Path('/opt/taiko-bot')
VERSION = re.compile(r'\d+\.\d+\.\d+')


def version_key(value):
    if not VERSION.fullmatch(value):
        raise ValueError('Invalid release version')
    return tuple(map(int, value.split('.')))


def consumers(root=ROOT, proc=Path('/proc'), configs=Path('/etc')):
    found = set()
    deadline = time.monotonic() + 30
    pattern = re.compile(re.escape(str(root / 'releases')) + r'/(\d+\.\d+\.\d+)(?=[/\s\x00\"\']|$)')

    def capture(raw):
        if time.monotonic() > deadline:
            raise RuntimeError('Release consumer scan timed out')
        found.update(pattern.findall(raw))

    def read(path):
        with path.open('rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RuntimeError('Release consumer metadata exceeds budget')
        capture(raw.decode(errors='replace'))

    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            for key in ('cwd', 'exe'):
                try:
                    capture(os.readlink(process / key))
                except FileNotFoundError:
                    pass
            for key in ('cmdline', 'environ', 'maps'):
                try:
                    read(process / key)
                except (FileNotFoundError, ProcessLookupError):
                    pass
            for fd in (process / 'fd').iterdir():
                try:
                    capture(os.readlink(fd))
                except FileNotFoundError:
                    pass
        except (FileNotFoundError, ProcessLookupError):
            continue
    # Include inactive services and scheduled jobs that still pin an interpreter.
    for base in (configs / 'systemd/system', configs / 'cron.d'):
        for here, dirs, files in os.walk(base, onerror=lambda error: (_ for _ in ()).throw(error)):
            for name in dirs + files:
                path = Path(here) / name
                if path.is_symlink():
                    capture(str(path.resolve()))
                if path.is_file():
                    read(path)
    return found


def prune(version, *, apply=False, root=ROOT, scan=consumers):
    releases = root / 'releases'
    current = root / 'current'
    expected = releases / version
    if releases.is_symlink() or expected.is_symlink() or current.resolve(strict=True) != expected:
        raise RuntimeError('Current release does not match successful deployment')
    refs = scan(root)
    candidates = []
    for path in sorted(releases.iterdir()):
        if (not VERSION.fullmatch(path.name) or path.is_symlink() or not path.is_dir()
                or version_key(path.name) >= version_key(version)):
            continue
        if path.name not in refs:
            info = path.stat()
            candidates.append((path, info.st_dev, info.st_ino))
    result = {'current': version, 'protected': sorted(refs), 'selected': [p.name for p, _, _ in candidates],
              'removed': [], 'mode': 'apply' if apply else 'dry-run'}
    if apply:
        # Complete a second scan before the first deletion.
        refs |= scan(root)
        for path, device, inode in candidates:
            if current.resolve(strict=True) != expected:
                raise RuntimeError('Current release changed during cleanup')
            if path.name in refs:
                continue
            info = path.lstat()
            if path.is_symlink() or (info.st_dev, info.st_ino) != (device, inode):
                raise RuntimeError('Release identity changed during cleanup')
            shutil.rmtree(path)
            result['removed'].append(path.name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    version_key(args.version)
    print(json.dumps(prune(args.version, apply=args.apply)))


if __name__ == '__main__':
    main()
