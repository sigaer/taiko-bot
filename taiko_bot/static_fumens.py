"""Opt-in, local-only URL lookup for explicitly authorized static chart images.

Owner: public-song delivery. One bounded manifest/policy pair per process; no
image bytes or query-result cache. Invalid/revoked/expired input fails closed.
Publication/HTTPS verification is offline; this module never opens a socket.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
import time
from types import MappingProxyType
from urllib.parse import urlsplit

DIFFICULTIES = ('Kantan', 'Futsuu', 'Muzukashii', 'Oni', 'InnerOni')
MAX_ENTRIES = 20000
MAX_PIXELS = 64 * 1024 * 1024
MAX_BYTES = 16 * 1024 * 1024
MAX_LEASE = 900
MANIFEST = 'static_fumen_manifest.json'
POLICY = 'static_fumen_policy.json'
HEX = re.compile(r'[0-9a-f]{64}')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def base_url(value):
    """The operator pins a single HTTPS origin AND path prefix, never a glob."""
    parsed = urlsplit(value)
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('invalid static HTTPS port')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not value.isascii() or parsed.netloc.endswith(':')
            or not re.fullmatch(r'[A-Za-z0-9.:-]+', parsed.netloc)
            or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+/?', parsed.path)):
        raise ValueError('invalid static HTTPS allowlist')
    return value.rstrip('/')


def key(difficulty, song_id):
    if difficulty not in DIFFICULTIES or not re.fullmatch(r'[1-9][0-9]{0,9}', str(song_id)):
        raise ValueError('invalid static chart key')
    return f'{difficulty}/{song_id}'


def asset_url(base, sha256):
    if not isinstance(sha256, str) or not HEX.fullmatch(sha256):
        raise ValueError('invalid static content hash')
    return f'{base_url(base)}/sha256/{sha256}.png'


def safe_file(directory, name):
    directory = Path(directory)
    path = directory/name
    # The caller fixes the filename; deny symlinks in every component below the
    # configured root as well as a symlink at the file itself.
    if directory.is_symlink() or path.is_symlink() or path.resolve() != directory.resolve()/name:
        raise ValueError('static resource path escaped allowlist')
    return path


def read_bounded(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('static metadata must be a bounded regular file')
        data = stream.read(limit+1)
    if len(data) > limit:
        raise ValueError('static metadata exceeds budget')
    return data


def signature(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def policy_grants(payload, allowed_base, now):
    if (payload.get('schema') != 1 or payload.get('scope') != 'public-static-fumen'
            or payload.get('base_url') != base_url(allowed_base)
            or type(payload.get('valid_until')) not in (int, float)
            or not now < payload['valid_until'] <= now+366*86400
            or not isinstance(payload.get('grants'), list) or len(payload['grants']) > MAX_ENTRIES):
        raise ValueError('invalid or expired public authorization policy')
    result = {}
    for grant in payload['grants']:
        item_key = key(grant['difficulty'], grant['song_id'])
        if item_key in result:
            raise ValueError('duplicate public authorization')
        if (grant.get('public') is not True or not isinstance(grant.get('authorization_ref'), str)
                or not grant['authorization_ref'].strip() or len(grant['authorization_ref']) > 512
                or not HEX.fullmatch(grant.get('sha256', ''))):
            raise ValueError('explicit hash-bound public authorization required')
        result[item_key] = grant['sha256']
    return result


@dataclass(frozen=True)
class StaticFumen:
    difficulty: str
    song_id: str
    url: str
    width: int
    height: int
    sha256: str
    resource_version: str


def validate_manifest(payload, policy, policy_hash, allowed_base, now):
    grants = policy_grants(policy, allowed_base, now)
    if (payload.get('schema') != 1 or payload.get('policy_sha256') != policy_hash
            or type(payload.get('checked_at')) not in (int, float)
            or type(payload.get('valid_until')) not in (int, float)
            or not payload['checked_at'] <= now < payload['valid_until']
            or not 0 < payload['valid_until']-payload['checked_at'] <= MAX_LEASE
            or payload['valid_until'] > policy['valid_until']
            or not isinstance(payload.get('entries'), list) or len(payload['entries']) > MAX_ENTRIES):
        raise ValueError('invalid or expired static manifest')
    version = digest(canonical(dict(policy_sha256=policy_hash, entries=payload['entries'])))
    if payload.get('resource_version') != version:
        raise ValueError('static manifest version mismatch')
    entries = {}
    for row in payload['entries']:
        item_key = key(row['difficulty'], row['song_id'])
        if (item_key in entries or grants.get(item_key) != row['sha256']
                or row['url'] != asset_url(allowed_base, row['sha256'])
                or row.get('resource_version') != row['sha256']
                or type(row.get('width')) is not int or type(row.get('height')) is not int
                or not 0 < row['width'] <= 8192 or not 0 < row['height'] <= 65536
                or row['width']*row['height'] > MAX_PIXELS):
            raise ValueError('untrusted static manifest entry')
        entries[item_key] = StaticFumen(**row)
    return MappingProxyType(entries), version


class StaticFumenStore:
    def __init__(self):
        self._lock = Lock()
        self._state = None
        self._checked_at = 0.0
        self.hits = self.misses = self.loads = self.failures = 0

    def lookup(self, root, allowed_base, difficulty, song_id, *, now=None):
        now = time.time() if now is None else now
        try:
            item_key = key(difficulty, song_id)
            base = base_url(allowed_base)
            directory = safe_file(Path(root), 'songs')
            paths = safe_file(directory, POLICY), safe_file(directory, MANIFEST)
            with self._lock:
                signatures = tuple(signature(p) for p in paths)
                cache_key = (*paths, base, signatures)
                old = self._state
                # Lease expiration is checked on every lookup, even unchanged files.
                if (old is None or old[0] != cache_key or now-self._checked_at >= 30
                        or not old[1] <= now < old[2] or now >= old[3]):
                    policy_bytes = read_bounded(paths[0], 4*1024*1024)
                    manifest_bytes = read_bounded(paths[1], 8*1024*1024)
                    hashes = digest(policy_bytes), digest(manifest_bytes)
                    after = tuple(signature(p) for p in paths)
                    if signatures != after:
                        raise ValueError('static metadata changed during read')
                    if (old is not None and old[0][:-1] == cache_key[:-1] and old[6] == hashes
                            and old[1] <= now < old[2] and now < old[3]):
                        # Identical bytes need no JSON parsing or map rebuild.
                        self._state = (cache_key, *old[1:])
                    else:
                        payload, policy = json.loads(manifest_bytes), json.loads(policy_bytes)
                        entries, version = validate_manifest(payload, policy, hashes[0], base, now)
                        self._state = (cache_key, payload['checked_at'], payload['valid_until'],
                                       policy['valid_until'], entries, version, hashes)
                        self.loads += 1
                    self._checked_at = now
                entry = self._state[4].get(item_key)
                if entry is None:
                    self.misses += 1
                else:
                    self.hits += 1
                return entry
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            # Unlike the song catalog, stale authorization/health is never used.
            with self._lock:
                self._state = None
                self.failures += 1
                self.misses += 1
            return None
