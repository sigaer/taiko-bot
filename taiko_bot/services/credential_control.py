"""Fail-closed service authorization for the singleton Wahlap credential.

The signed service JWT is NOT the uploaded upstream credential. The latter is
opaque to caller authorization; its decoded identity is only a consistency check.
No Developer key or browser session is accepted by this control plane.
"""
from contextlib import closing
import base64
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

ISSUER = 'taiko-credential-control'
SCOPE = 'wahlap:credential:write'
AUDIENCES = {'taiko-token', 'miku-taiko-login'}
MAX_BODY = 16384


class ControlError(Exception):
    def __init__(self, status=503):
        self.status = status
        super().__init__('Credential update unavailable' if status == 503 else 'Credential update denied')


def _decode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ControlError(401)
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except Exception:
        raise ControlError(401) from None


def _object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ControlError(400)
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except Exception:
        raise ControlError(400) from None


def _private_file(path):
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise ControlError()
    parent = path.parent.stat()
    if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise ControlError()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 65536:
            raise ControlError()
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            return stream.read(65537)
    finally:
        os.close(descriptor)


def _policy():
    try:
        path = Path(os.environ['TAIKO_CREDENTIAL_CONTROL_CONFIG'])
        raw = _private_file(path)
        policy = _object(raw)
        if policy.get('schema') != 1 or not re.fullmatch(r'[1-9][0-9]{0,24}', str(policy.get('ownerId', ''))):
            raise ControlError()
        if not isinstance(policy.get('clients'), dict):
            raise ControlError()
        return path, policy, hashlib.sha256(raw).digest()
    except Exception:
        raise ControlError() from None


def require_bearer(header):
    if not isinstance(header, str) or not re.fullmatch(r'Bearer [A-Za-z0-9_.-]{32,8192}', header):
        raise ControlError(401)
    return header[7:]


def validate_upstream_payload(value, owner, now):
    """Shape/identity check, NOT upstream signature authentication.

Only the fully signed body-specific operator request authorizes installation.
Wahlap's signing key is not possessed by this platform. Do not treat these
unverified claims as a login, resource grant, or proof of the upstream account.
"""
    if not isinstance(value, str) or len(value) > 8192:
        raise ControlError(400)
    pieces = value.split('.')
    if len(pieces) != 3:
        raise ControlError(400)
    header, claims = _object(_decode(pieces[0])), _object(_decode(pieces[1]))
    _decode(pieces[2])
    if header.get('alg') != 'HS256' or header.get('typ') != 'JWT':
        raise ControlError(400)
    if type(claims.get('id')) is not int or str(claims['id']) != owner:
        raise ControlError(403)
    if type(claims.get('exp')) is not int or claims['exp'] <= now:
        raise ControlError(400)
    return value


def _prove(authorization, raw, audience, now):
    token = require_bearer(authorization)
    path, policy, revision = _policy()
    if audience not in AUDIENCES or len(raw) > MAX_BODY:
        raise ControlError(400)
    pieces = token.split('.')
    if len(pieces) != 3:
        raise ControlError(401)
    header = _object(_decode(pieces[0]))
    if set(header) != {'alg', 'typ', 'kid'} or header['alg'] != 'HS256' or header['typ'] != 'JWT':
        raise ControlError(401)
    client_id = header['kid']
    if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', client_id):
        raise ControlError(401)
    client = policy['clients'].get(client_id)
    if not isinstance(client, dict) or client.get('status') != 'active':
        raise ControlError(401)
    if any(not isinstance(client.get(field), list) or any(not isinstance(item, str) for item in client[field]) for field in ('owners', 'audiences', 'scopes')):
        raise ControlError(503)
    try:
        secret = bytes.fromhex(client['keyHex'])
        if len(secret) < 32 or type(client['expiresAt']) is not int or client['expiresAt'] <= now:
            raise ValueError()
    except Exception:
        raise ControlError(401) from None
    expected = hmac.digest(secret, (pieces[0] + '.' + pieces[1]).encode('ascii'), 'sha256')
    if not hmac.compare_digest(expected, _decode(pieces[2])):
        raise ControlError(401)
    claims = _object(_decode(pieces[1]))
    required = {'iss', 'aud', 'sub', 'scope', 'ownerId', 'iat', 'nbf', 'exp', 'jti', 'bodySha256'}
    if set(claims) != required or claims['iss'] != ISSUER or claims['sub'] != client_id:
        raise ControlError(401)
    if claims['aud'] != audience or audience not in client.get('audiences', []) or claims['scope'] != SCOPE or SCOPE not in client.get('scopes', []):
        raise ControlError(403)
    if any(type(claims[name]) is not int for name in ['iat', 'nbf', 'exp']):
        raise ControlError(401)
    if not (claims['iat'] <= now < claims['exp'] and claims['nbf'] <= now and claims['iat'] <= claims['nbf'] < claims['exp'] and claims['exp'] - claims['iat'] <= 60):
        raise ControlError(401)
    owner = str(policy['ownerId'])
    if claims['ownerId'] != owner or owner not in client.get('owners', []):
        raise ControlError(403)
    if not isinstance(claims['jti'], str) or not re.fullmatch(r'[a-f0-9]{32}', claims['jti']):
        raise ControlError(401)
    if claims['bodySha256'] != hashlib.sha256(raw).hexdigest():
        raise ControlError(403)
    body = _object(raw)
    if set(body) != {'token', 'ownerId'} or body['ownerId'] != owner:
        raise ControlError(403)
    credential = validate_upstream_payload(body['token'], owner, now)
    return path, revision, client_id, claims, credential


def authorized_update(authorization, raw, audience, writer):
    """At-most-once: reserve jti durably before writer; failures require new consent.

All invalid requests finish before a replay DB or Writer is opened. Caller must
use one private config directory for both aliases; the lock serializes writers.
"""
    try:
        path, revision, client, claims, credential = _prove(authorization, raw, audience, int(time.time()))
        lock_path = path.parent / 'credential-update.lock'
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                raise ControlError()
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Configuration changes, expiry and revocation during queuing fail closed.
            live = _prove(authorization, raw, audience, int(time.time()))
            if live[1] != revision:
                raise ControlError(403)
            ledger = path.parent / 'credential-nonces.sqlite3'
            descriptor = os.open(ledger, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                    raise ControlError()
            finally:
                os.close(descriptor)
            with closing(sqlite3.connect(ledger, timeout=1)) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('CREATE TABLE IF NOT EXISTS nonces(client TEXT NOT NULL,jti TEXT NOT NULL,expires INTEGER NOT NULL,PRIMARY KEY(client,jti))')
                db.execute('DELETE FROM nonces WHERE expires < ?', (int(time.time()) - 120,))
                try:
                    db.execute('INSERT INTO nonces VALUES (?,?,?)', (client, claims['jti'], claims['exp']))
                    db.commit()
                except sqlite3.IntegrityError:
                    raise ControlError(409) from None
            writer(credential)
        finally:
            os.close(fd)
    except ControlError:
        raise
    except BlockingIOError:
        raise ControlError(409) from None
    except Exception:
        raise ControlError() from None
