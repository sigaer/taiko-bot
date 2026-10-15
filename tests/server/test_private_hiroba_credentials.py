"""Compatible crypto, bounded raw card discovery and private retry fingerprints."""
import base64
import hashlib
import importlib
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parent
import taiko_bot.runtime.player.center as _owner
OWNED = Path(_owner.__file__).parent
for name, path in (("credential_worker_fixture", OWNED), ("credential_worker_fixture.hiroba", OWNED / "hiroba")):
    package = types.ModuleType(name); package.__path__ = [str(path)]; sys.modules[name] = package
worker = importlib.import_module("credential_worker_fixture.hiroba.private_credentials")
frozen = json.loads((ROOT / "fixtures/hiroba_credential_legacy.json").read_text())


class PrivateCredentialsTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"HIROBA_CRED_KEY": "owned-synthetic-key"})
        env.start(); self.addCleanup(env.stop)
        self.request = dict(operationId="a" * 32, mode="discover", email="demo@example.test", password="synthetic-password", target="", principal="onebot_v11:12345")
        self.old = dict(base64=base64, hashlib=hashlib, os=os, Fernet=Fernet, InvalidToken=InvalidToken)
        for code in frozen.values(): exec(code, self.old)

    def card(self, identity): return types.SimpleNamespace(taiko_no=identity)

    def test_both_crypto_directions_match_frozen_legacy(self):
        old = self.old["encrypt_password"](self.request["password"])
        self.assertTrue(worker.run_private_credentials(dict(operationId="a" * 32, mode="decode", passwordEnc=old))["hasCredentials"])
        actual = worker.run_private_credentials(self.request, discovery=lambda *args: [self.card("12345678901")])
        self.assertEqual(self.old["decrypt_password"](actual["passwordEnc"]), self.request["password"])
        self.assertNotIn(self.request["password"], json.dumps(actual))

    def test_discovery_preserves_order_target_filter_and_empty_ids(self):
        cards = [self.card("22222222222"), self.card("11111111111"), self.card("")]
        self.assertEqual(worker.run_private_credentials(self.request, discovery=lambda *args: cards)["taikoIds"], ["22222222222", "11111111111"])
        self.assertEqual(worker.run_private_credentials({**self.request, "target": "11111111111"}, discovery=lambda *args: cards)["taikoIds"], ["11111111111"])
        self.assertEqual(worker.run_private_credentials({**self.request, "target": "33333333333"}, discovery=lambda *args: cards)["taikoIds"], [])

    def test_stable_fingerprint_covers_every_intent_field_and_private_key(self):
        request = {**self.request, "mode": "fingerprint"}
        value = worker.run_private_credentials(request)["intentHash"]
        self.assertEqual(value, worker.run_private_credentials({**request, "operationId": "b" * 32})["intentHash"])
        for field in ("email", "password", "target", "principal"):
            altered = {**request, field: "12345678901" if field == "target" else request[field] + "x"}
            self.assertNotEqual(value, worker.run_private_credentials(altered)["intentHash"])
        with patch.dict(os.environ, {"HIROBA_CRED_KEY": "another-key"}):
            self.assertNotEqual(value, worker.run_private_credentials(request)["intentHash"])
        self.assertNotEqual(value, hashlib.sha256(self.request["password"].encode()).hexdigest())

    def test_fingerprint_does_not_discover_or_write_sql(self):
        result = worker.run_private_credentials({**self.request, "mode": "fingerprint"}, discovery=lambda *args: self.fail("Discovery during retry proof"))
        self.assertEqual(set(result), {"operationId", "intentHash"})

    def test_bad_cipher_has_no_plaintext_result(self):
        with self.assertRaises(ValueError): worker.run_private_credentials(dict(operationId="a" * 32, mode="decode", passwordEnc="invalid"))

    def test_private_upstream_error_is_fixed(self):
        def failed(*args): raise RuntimeError("private-password /remote/path")
        with self.assertRaises(worker.CredentialWorkerError) as caught: worker.run_private_credentials(self.request, discovery=failed)
        self.assertEqual((caught.exception.status, str(caught.exception)), (502, "hiroba_login_failed"))

    def test_unsafe_manual_duplicate_and_over_capacity_cards_fail_closed(self):
        for cards in ([self.card("../private")], [self.card("980000000000000001")], [self.card("1"), self.card("1")], [self.card(str(i)) for i in range(129)]):
            with self.assertRaises(worker.CredentialWorkerError): worker.run_private_credentials(self.request, discovery=lambda *args: cards)

    def test_request_bounds_and_identity_are_strict(self):
        for change in (dict(operationId="bad"), dict(mode="bad"), dict(email=""), dict(password=""), dict(password="a" * 4097), dict(email="a" * 256), dict(target="../bad"), dict(email=" spaced ")):
            with self.assertRaises(worker.CredentialWorkerError): worker.run_private_credentials({**self.request, **change})
