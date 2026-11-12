#!/usr/bin/env python3
"""Plan or upload local covers using explicit OurTaiko catalog mappings."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import getpass
import json
import os
from pathlib import Path
import sys

# This is standalone maintenance tooling, including when launched with python -I.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ourtaiko_covers.client import APIError, BASE, Client
from ourtaiko_covers.matching import build_plan, digest


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def completed(path):
    rows = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # An interrupted final append cannot count as success.
            if row.get('status') == 'uploaded' and row.get('base') == BASE:
                rows[(row['chartId'], row['sourceSha256'])] = row
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--charts', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path('/home/sigaer/taiko'))
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--apply', action='store_true', help='Default only writes a matching plan')
    parser.add_argument('--username', default='sigaer')
    parser.add_argument('--credentials-file', type=Path, help='Private JSON with username/password; never passed in argv')
    parser.add_argument('--proxy', help='Optional HTTP/SOCKS proxy; otherwise use the current environment')
    parser.add_argument('--limit', type=int, default=0, help='Max uploads this invocation; zero means all')
    parser.add_argument('--interval', type=float, default=1.7, help='Minimum seconds between writes (>=1.7)')
    args = parser.parse_args()
    os.umask(0o077)
    state = args.state_dir or args.root / 'storage/ourtaiko-cover-upload'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / 'upload.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = build_plan(args.charts, args.root / 'songs/song_data.json', args.root / 'assets/cover')
        write_json(state / 'plan.json', plan)
        print(json.dumps(dict(Counter(row['status'] for row in plan['rows'])), ensure_ascii=False), flush=True)
        if not args.apply:
            return 0
        username = args.username
        if args.credentials_file:
            stat = args.credentials_file.stat()
            if stat.st_uid != os.geteuid() or stat.st_mode & 0o077:
                raise ValueError('Credentials file must be owned by caller and mode 0600')
            credentials = json.loads(args.credentials_file.read_text(encoding='utf-8'))
            username, password = credentials['username'], credentials.pop('password')
            credentials.clear()
        else:
            if not sys.stdin.isatty():
                raise ValueError('Non-interactive upload requires --credentials-file')
            password = getpass.getpass('OurTaiko password: ')
        client = Client(args.interval, args.proxy)
        results, count = [], 0
        journal_path = state / 'uploads.jsonl'
        previous = completed(journal_path)
        try:
            user = client.login(username, password)
            del password
            print(json.dumps({'loggedInAs': user.get('username'), 'isAdmin': user.get('isAdmin')}, ensure_ascii=False), flush=True)
            with journal_path.open('a', encoding='utf-8') as journal:
                for row in plan['rows']:
                    if row['status'] != 'ready':
                        continue
                    cid, source = row['chartId'], row['sourceSha256']
                    prior = previous.get((cid, source))
                    if prior and client.chart(cid).get('coverHash') == prior['coverHash']:
                        results.append({**row, 'status': 'resumed'})
                        continue
                    if args.limit and count >= args.limit:
                        results.append({**row, 'status': 'pending'})
                        continue
                    outcome = {**row, 'base': BASE, 'at': datetime.now(timezone.utc).isoformat()}
                    try:
                        path = Path(row['path'])
                        if digest(path) != source:
                            raise ValueError('Local cover changed since matching')
                        cover_hash = client.put_cover(cid, path)
                        if count == 0:
                            client.verify_download(cid, cover_hash)
                        outcome.update(status='uploaded', coverHash=cover_hash)
                    except APIError as error:
                        outcome.update(status='failed', httpStatus=error.status, code=error.code)
                    except (OSError, ValueError):
                        outcome.update(status='failed', code='LOCAL_FILE_CHANGED_OR_UNREADABLE')
                    journal.write(json.dumps(outcome, ensure_ascii=False) + '\n')
                    journal.flush()
                    os.fsync(journal.fileno())
                    results.append(outcome)
                    count += 1
                    print(json.dumps({k: outcome[k] for k in ('chartId', 'localId', 'title', 'status', 'code') if k in outcome}, ensure_ascii=False), flush=True)
                    write_json(state / 'summary.json', {'counts': dict(Counter(r['status'] for r in results)), 'results': results})
                    if outcome.get('httpStatus') in (401, 403) or outcome.get('code') == 'NETWORK_ERROR':
                        raise RuntimeError('Stopped after authentication/permission/network failure; see journal')
        finally:
            client.close()
            write_json(state / 'summary.json', {'counts': dict(Counter(r['status'] for r in results)), 'results': results})
        counts = dict(Counter(r['status'] for r in results))
        print(json.dumps(counts), flush=True)
        return int(bool(counts.get('failed')))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (APIError, RuntimeError, ValueError, OSError) as error:
        print(f'Upload stopped: {error}', file=sys.stderr)
        sys.exit(1)
