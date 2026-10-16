"""Actual endpoint handlers on isolated loopback, real signatures, memory writer.

No production application imports, configuration, data, remote sockets or SQL. Taiko package public API handler is loaded whole,
with unrelated public-score and runtime root imports stubbed to prevent application IO.
This source test does not import an installed wheel or modify its environment.
"""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module
control=load('taiko_bot.services.credential_control','taiko_bot/services/credential_control.py')
signed_upload=load('isolated_operator_client','taiko_bot/cli/credential_control.py').signed_upload


def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')


def upstream(owner=293, expiry=None):
    # Credential payload is opaque to caller auth; this is not a real login.
    return encode({'alg': 'HS256', 'typ': 'JWT'}) + '.' + encode({'id': owner, 'exp': int(time.time()) + 600 if expiry is None else expiry}) + '.c3ludGhldGlj'


def change_signed(header, secret, **claims):
    parts = header[7:].split('.')
    body = json.loads(control._decode(parts[1]));body.update(claims)
    unsigned = parts[0] + '.' + encode(body)
    return 'Bearer ' + unsigned + '.' + base64.urlsafe_b64encode(hmac.digest(bytes.fromhex(secret), unsigned.encode(), 'sha256')).decode().rstrip('=')


class ControlCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='credential-control-test-', dir='/var/tmp'))
        self.config = self.root / 'control.json'
        self.secret = secrets.token_hex(32)
        self.policy = {'schema': 1, 'ownerId': '293', 'clients': {'synthetic-operator': {
            'keyHex': self.secret, 'status': 'active', 'expiresAt': int(time.time()) + 3600,
            'owners': ['293'], 'audiences': ['taiko-token', 'miku-taiko-login'], 'scopes': [control.SCOPE]}}}
        self.save()
        self.previous = os.environ.get('TAIKO_CREDENTIAL_CONTROL_CONFIG')
        os.environ['TAIKO_CREDENTIAL_CONTROL_CONFIG'] = str(self.config)
        self.received = []
        self.servers = []
        self.current = threading.local()
        self.modules = {}

    def save(self):
        self.config.write_text(json.dumps(self.policy));self.config.chmod(0o600)

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown();server.server_close();thread.join(3)
            self.assertFalse(thread.is_alive())
        if self.previous is None:os.environ.pop('TAIKO_CREDENTIAL_CONTROL_CONFIG', None)
        else:os.environ['TAIKO_CREDENTIAL_CONTROL_CONFIG'] = self.previous
        import shutil
        shutil.rmtree(self.root)

    def start(self, audience):
        owner = self
        if audience == 'taiko-token':
            stub = types.ModuleType('taiko_bot.runtime.player.center.public_score_token')
            stub.PublicScoreTokenError = RuntimeError
            stub.fetch_latest_userdata_by_token = lambda *args: (_ for _ in ()).throw(AssertionError('public score not exercised'))
            key = stub.__name__;prior = sys.modules.get(key);sys.modules[key] = stub
            try:
                paths=types.ModuleType('taiko_bot.runtime.paths');paths.root=lambda:self.root
                sys.modules[paths.__name__]=paths
                spec = importlib.util.spec_from_file_location('synthetic_control_server', ROOT / 'taiko_bot/services/public_api.py')
                module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            finally:
                if prior is None:sys.modules.pop(key, None)
                else:sys.modules[key] = prior
            self.modules[audience] = (module, module.update_cookie)
            module.update_cookie = owner.received.append
            class Handler(module.SongDataHandler):
                def log_message(self, *args):pass
            path = '/api/token'
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever);thread.start()
        self.servers.append((server, thread))
        return server.server_port, path

    def ask(self, endpoint, body, authorization=None):
        connection = HTTPConnection('127.0.0.1', endpoint[0], timeout=3)
        try:
            headers = {'Content-Type': 'application/json'}
            if authorization is not None:headers['Authorization'] = authorization
            connection.request('POST', endpoint[1], body, headers)
            response = connection.getresponse();raw = response.read(4097)
            self.assertLess(len(raw), 4097)
            self.assertIn('no-store', response.getheader('Cache-Control', ''))
            self.assertNotIn(upstream().encode(), raw)
            self.assertNotIn(self.secret.encode(), raw)
            return response.status
        finally:connection.close()

    def signed(self, audience, credential=None):
        return signed_upload(dict(clientId='synthetic-operator', keyHex=self.secret, ownerId='293', audience=audience), credential or upstream())

    def test_both_anonymous_original_probe_requests_denied_no_writer_or_ledger(self):
        for audience in ('taiko-token',):
            endpoint = self.start(audience)
            old_encode=lambda value:base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
            original_token='synthetic-not-an-upstream-credential' if audience=='taiko-token' else old_encode({'alg':'HS256','typ':'JWT'})+'.'+old_encode({'id':1,'exp':1})+'.c3ludGhldGlj'
            self.assertEqual(self.ask(endpoint, json.dumps({'token':original_token}).encode()),401)
        self.assertEqual(self.received, [])
        self.assertFalse((self.root/'credential-nonces.sqlite3').exists())

    def test_both_valid_signed_consumer_exactly_one_write_then_replay_denied(self):
        for audience in ('taiko-token',):
            endpoint = self.start(audience);body, authorization = self.signed(audience)
            before = len(self.received)
            self.assertEqual(self.ask(endpoint, body, authorization), 200)
            self.assertEqual(len(self.received), before+1)
            self.assertEqual(self.ask(endpoint, body, authorization), 409)
            self.assertEqual(len(self.received), before+1)

    def test_both_negative_authorization_matrix_no_writer(self):
        for audience in ('taiko-token',):
            endpoint = self.start(audience);body, authorization = self.signed(audience);now=int(time.time())
            cases = [
                ('developer token', 'Bearer ordinary-developer-key-12345678901234567890', body, 401),
                ('wrong signature', authorization[:-8] + 'AAAAAAAA', body, 401),
                ('wrong issuer', change_signed(authorization,self.secret,iss='other'), body, 401),
                ('wrong audience', change_signed(authorization,self.secret,aud='other'), body, 403),
                ('wrong subject', change_signed(authorization,self.secret,sub='another-client'), body, 401),
                ('wrong scope', change_signed(authorization,self.secret,scope='source_read'), body, 403),
                ('wrong owner', change_signed(authorization,self.secret,ownerId='294'), body, 403),
                ('expired', change_signed(authorization,self.secret,iat=now-61,nbf=now-61,exp=now-1), body, 401),
                ('not yet valid', change_signed(authorization,self.secret,nbf=now+20), body, 401),
                ('overlong ttl', change_signed(authorization,self.secret,exp=now+600), body, 401),
                ('changed body', authorization, body.replace(b'293',b'294'), 403),
                ('missing owner payload', change_signed(authorization,self.secret,bodySha256=hashlib.sha256(b'{}').hexdigest()), b'{}', 403),
            ]
            for name, header, raw, expected in cases:
                with self.subTest(route=audience, case=name):self.assertEqual(self.ask(endpoint,raw,header),expected)
        self.assertEqual(self.received, [])
        self.assertFalse((self.root/'credential-nonces.sqlite3').exists())

    def test_both_missing_config_revoked_client_and_unavailable_policy_no_writer(self):
        for audience in ('taiko-token',):
            endpoint=self.start(audience);body,header=self.signed(audience)
            os.environ.pop('TAIKO_CREDENTIAL_CONTROL_CONFIG')
            self.assertEqual(self.ask(endpoint,body,header),503)
            os.environ['TAIKO_CREDENTIAL_CONTROL_CONFIG']=str(self.config)
            for update in [{'status':'revoked'},{'expiresAt':1},{'owners':['294']},{'audiences':[]},{'scopes':[]}]:
                client=self.policy['clients']['synthetic-operator'];old=client.copy();client.update(update);self.save()
                self.assertIn(self.ask(endpoint,body,header),[401,403])
                self.policy['clients']['synthetic-operator']=old;self.save()
            for field in ('owners', 'audiences', 'scopes'):
                client=self.policy['clients']['synthetic-operator'];old=client[field];client[field]=' '.join(old);self.save()
                self.assertEqual(self.ask(endpoint,body,header),503)
                client[field]=old;self.save()
            self.config.chmod(0o644)
            self.assertEqual(self.ask(endpoint,body,header),503);self.config.chmod(0o600)
        self.assertEqual(self.received,[])
        self.assertFalse((self.root/'credential-nonces.sqlite3').exists())

    def test_both_cross_audience_and_upstream_target_mismatch_denied(self):
        for audience in ('taiko-token',):
            endpoint=self.start(audience);body,header=self.signed(next(a for a in control.AUDIENCES if a != audience))
            self.assertEqual(self.ask(endpoint,body,header),403)
            own_body,own_header=self.signed(audience)
            mismatched=json.dumps({'token':upstream(owner=294),'ownerId':'293'},separators=(',',':')).encode()
            header=change_signed(own_header,self.secret,bodySha256=hashlib.sha256(mismatched).hexdigest())
            self.assertEqual(self.ask(endpoint,mismatched,header),403)
        self.assertEqual(self.received,[])

    def test_both_authorized_malformed_or_expired_upstream_payload_rejected(self):
        for audience in ('taiko-token',):
            endpoint=self.start(audience);_,header=self.signed(audience)
            for credential in ('synthetic-not-an-upstream-credential', upstream(expiry=1)):
                body=json.dumps({'token':credential,'ownerId':'293'},separators=(',',':')).encode()
                signed=change_signed(header,self.secret,bodySha256=hashlib.sha256(body).hexdigest())
                self.assertEqual(self.ask(endpoint,body,signed),400)
        self.assertEqual(self.received,[])
        self.assertFalse((self.root/'credential-nonces.sqlite3').exists())

    def test_concurrent_replay_is_at_most_once(self):
        endpoint=self.start('taiko-token');body,header=self.signed('taiko-token')
        with ThreadPoolExecutor(max_workers=4) as pool:statuses=list(pool.map(lambda _:self.ask(endpoint,body,header),range(8)))
        self.assertEqual(statuses.count(200),1);self.assertEqual(statuses.count(409),7)
        self.assertEqual(len(self.received),1)

    def test_actual_center_writer_preserves_config_and_makes_credential_private(self):
        endpoint=self.start('taiko-token');module,writer=self.modules['taiko-token']
        config=self.root/'synthetic-app.json';config.write_text(json.dumps({'other':'preserved','cookie':'old'}));config.chmod(0o644)
        module.CONFIG_PATH=config;module.update_cookie=writer
        body,header=self.signed('taiko-token')
        self.assertEqual(self.ask(endpoint,body,header),200)
        data=json.loads(config.read_text())
        self.assertEqual(data['other'],'preserved');self.assertEqual(data['cookie'],json.loads(body)['token'])
        self.assertEqual(config.stat().st_mode & 0o777,0o600)
        self.assertEqual(list(self.root.glob('.credential-*')),[])

    def test_center_rejects_query_without_write(self):
        port,path=self.start('taiko-token');body,header=self.signed('taiko-token')
        self.assertEqual(self.ask((port,path+'?token=synthetic-only'),body,header),400)
        self.assertEqual(self.received,[])

    def test_writer_failure_consumes_nonce_no_retry_or_diagnostics(self):
        body,header=self.signed('taiko-token');calls=[]
        def fail(token):calls.append(1);raise RuntimeError('secret diagnostic')
        with self.assertRaises(control.ControlError) as caught:control.authorized_update(header,body,'taiko-token',fail)
        self.assertEqual(caught.exception.status,503);self.assertNotIn('secret',str(caught.exception))
        with self.assertRaises(control.ControlError) as caught:control.authorized_update(header,body,'taiko-token',fail)
        self.assertEqual(caught.exception.status,409);self.assertEqual(calls,[1])

if __name__ == '__main__':unittest.main()
