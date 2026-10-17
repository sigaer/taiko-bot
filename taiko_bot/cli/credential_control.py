"""Explicit operator CLI. Read a captured credential from stdin; never log it.

Signer configuration is a private file with clientId/keyHex/ownerId/audience/url.
The target is fixed by that file, never accepted from the captured credential.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from taiko_bot.services.credential_control import AUDIENCES, ISSUER, SCOPE, ControlError, _private_file, _object, validate_upstream_payload


def signed_upload(config, credential, now=None):
    now = int(time.time()) if now is None else now
    client = config.get('clientId')
    owner = config.get('ownerId')
    audience = config.get('audience')
    if not isinstance(client, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', client) or not isinstance(owner, str) or not re.fullmatch(r'[1-9][0-9]{0,24}', owner) or audience not in AUDIENCES:
        raise ControlError()
    try:
        key = bytes.fromhex(config['keyHex'])
        if len(key) < 32:
            raise ValueError()
    except Exception:
        raise ControlError() from None
    credential = validate_upstream_payload(credential, owner, now)
    body = json.dumps({'token': credential, 'ownerId': owner}, separators=(',', ':')).encode()
    claims = {'iss': ISSUER, 'aud': audience, 'sub': client, 'scope': SCOPE, 'ownerId': owner,
              'iat': now, 'nbf': now, 'exp': now + 45, 'jti': uuid.uuid4().hex,
              'bodySha256': hashlib.sha256(body).hexdigest()}
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    unsigned = encode({'alg': 'HS256', 'typ': 'JWT', 'kid': client}) + '.' + encode(claims)
    signature = base64.urlsafe_b64encode(hmac.digest(key, unsigned.encode(), 'sha256')).decode().rstrip('=')
    return body, 'Bearer ' + unsigned + '.' + signature


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ControlError()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--envelope-output', type=Path, help='Optional one-use Surge argument envelope; no network send')
    args = parser.parse_args()
    try:
        config = _object(_private_file(args.config))
        raw = sys.stdin.buffer.read(8194)
        if len(raw) > 8193:
            raise ControlError(400)
        credential = raw.decode('ascii').strip()
        body, authorization = signed_upload(config, credential)
        if args.envelope_output:
            path = args.envelope_output
            if not path.is_absolute() or path.parent.resolve() != path.parent or (path.parent.stat().st_mode & 0o077 or path.parent.stat().st_uid != os.geteuid()):
                raise ControlError()
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'authorization': authorization, 'ownerId': config['ownerId']}, stream)
            print('{"status":"one-use-envelope-created","expiresInSeconds":45}')
            return 0
        target = urlparse(config['url'])
        expected_path = '/api/token' if config['audience'] == 'taiko-token' else '/uploadTaikoLogin'
        if target.scheme != 'https' or not target.hostname or target.username or target.password or target.query or target.fragment or target.path != expected_path:
            raise ControlError()
        request = Request(config['url'], data=body, headers={'Content-Type': 'application/json', 'Authorization': authorization}, method='POST')
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            if response.status != 200 or len(response.read(4097)) > 4096:
                raise ControlError()
        print('{"status":"credential-updated"}')
        return 0
    except Exception:
        print('{"status":"credential-update-denied-or-unavailable"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
