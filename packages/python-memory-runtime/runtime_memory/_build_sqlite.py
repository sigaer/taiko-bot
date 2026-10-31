"""Short-lived public-master importer. No user data, credentials, or network."""
import resource
resource.setrlimit(resource.RLIMIT_AS, (768*1024**2, 768*1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
import hashlib
import json
import os
import sqlite3
import sys


def revision(stat):
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


try:
    source, output = sys.argv[1:]
    digest = hashlib.sha256()
    with open(source, 'rb') as f:
        before = revision(os.fstat(f.fileno()))
        while chunk := f.read(1024*1024):
            digest.update(chunk)
        f.seek(0)
        rows = json.load(f)
        if before != revision(os.fstat(f.fileno())) or before != revision(os.stat(source)):
            raise ValueError('master changed while importing')
    if not isinstance(rows, list):
        raise ValueError('master rows must be a list')
    db = sqlite3.connect(output)
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA mmap_size=0')
    db.execute('CREATE TABLE rows(position INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE ids(id TEXT PRIMARY KEY, first_position INTEGER NOT NULL, last_position INTEGER NOT NULL)')
    for position, row in enumerate(rows):
        key = str(int(row['id']))
        db.execute('INSERT INTO rows VALUES(?,?)', (position, json.dumps(row, ensure_ascii=False, separators=(',', ':'))))
        db.execute('INSERT INTO ids VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_position=excluded.last_position', (key, position, position))
    db.execute('CREATE INDEX id_order ON ids(first_position)')
    db.commit()
    assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    db.close()
    with open(output, 'rb') as f:
        os.fsync(f.fileno())
    print(json.dumps(dict(source=before, sha256=digest.hexdigest(), rows=len(rows))))
except Exception as error:
    print(type(error).__name__, file=sys.stderr)
    raise SystemExit(1)
