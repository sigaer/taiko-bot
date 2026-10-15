"""Actual local dispatcher against the frozen, distinct runtime implementation."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
import http.client
import threading
from pathlib import Path
from unittest.mock import patch

from taiko_bot.services import sync_dispatch_server as live
from taiko_store import PublicationError, PublicationStore

ROOT = Path(__file__).resolve().parent
import taiko_bot.runtime.player.center as _owner
OWNED = Path(_owner.__file__).parent
spec = importlib.util.spec_from_file_location("scripts.sync_runtime_frozen", ROOT / "fixtures/sync_dispatch_runtime_legacy.py")
old = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = old
target_spec = importlib.util.spec_from_file_location("scripts.sync_targets_frozen", ROOT / "fixtures/sync_dispatch_targets_runtime_legacy.py")
frozen_targets = importlib.util.module_from_spec(target_spec)
sys.modules[target_spec.name] = frozen_targets
target_spec.loader.exec_module(frozen_targets)
_token = types.ModuleType("plugins.utils.public_score_token")
for _name in ("get_public_score_token_status", "issue_public_score_token_for_taiko_id", "revoke_public_score_token_for_taiko_id"):
    setattr(_token, _name, lambda *args, **kwargs: None)
_token.PublicScoreTokenError = RuntimeError
with patch.dict(sys.modules, {_token.__name__: _token, "scripts.sync_dispatch_targets": frozen_targets}):
    spec.loader.exec_module(old)


class SyncPublicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sync-publication-", dir="/var/tmp")
        self.root = Path(self.tmp.name)
        self.identity = "7123456789012345"
        self.current = self.root / (self.identity + "data.json")
        self.history = self.root / self.identity
        self.history.mkdir()
        self.payload = {"profile": {"userid": self.identity, "name": "合成用户"}, "achievement": {"gold": 3},
                        "songs": [{"song_no": 1, "level": 4, "high_score": 800000}], "dojo": {"2025": 4}}
        self.patches = [patch.object(live, "USERDATA_DIR", self.root), patch.object(old, "USERDATA_DIR", self.root),
                        patch.object(live, "get_snapshot_timestamp", return_value="20261011160000"),
                        patch.object(old, "get_snapshot_timestamp", return_value="20261011160000")]
        for p in self.patches:
            p.start()
        self.addCleanup(self.tmp.cleanup)
        for p in reversed(self.patches):
            self.addCleanup(p.stop)

    def seed(self, previous, history=None):
        self.current.write_text(json.dumps(previous, ensure_ascii=False))
        if history is not None:
            (self.history / "data_20260901.json").write_text(json.dumps(history, ensure_ascii=False))

    def assert_delta(self):
        self.assertEqual(live.build_delta_snapshot(self.current, self.history, self.payload, "20261011160000"),
                         old.build_delta_snapshot(self.current, self.history, self.payload, "20261011160000"))

    def test_actual_runtime_target_metadata_is_preserved(self):
        self.assertEqual([live.to_public_target(target) for target in live.get_sync_targets()],
                         [old.to_public_target(target) for target in old.get_sync_targets()])

    def test_frozen_full_without_current(self):
        self.assert_delta()

    def test_frozen_full_without_full_history(self):
        self.seed(self.payload, {"_meta": {"full": False}, "songs": []})
        self.assert_delta()

    def test_frozen_delta_changed_removed_order_and_duplicate(self):
        previous = self.payload | {"songs": [{"song_no": 2, "level": 4}, {"song_no": 1, "level": 4, "high_score": 700000}], "profile": {}}
        self.payload["songs"] += [{"song_no": 1, "level": 4, "high_score": 900000}, {"song_no": 3, "level": 3}]
        self.seed(previous, self.payload | {"_meta": {"full": True}})
        self.assert_delta()
        delta = live.build_delta_snapshot(self.current, self.history, self.payload, "20261011160000")
        self.assertEqual(delta["songs_removed"], [[2, 4]])
        self.assertEqual(delta["songs"][0]["high_score"], 900000)

    def test_frozen_old_full_and_invalid_history(self):
        self.seed(self.payload, self.payload)
        (self.history / "data_000.json").write_text("invalid")
        self.assert_delta()

    def test_frozen_raw_compression_and_complete_target_dto(self):
        self.seed(self.payload)
        before = live.read_local_userdata(self.identity)
        baseline = old.read_local_userdata(self.identity)
        self.assertTrue(before.raw_buffer == baseline.raw_buffer, "Current bytes differ")
        self.assertTrue(before.compressed_buffer == baseline.compressed_buffer, "Compressed bytes differ")
        target = live.get_sync_targets()[0]
        expected = old.dispatch_to_target(target, baseline)
        old_current = self.current.read_bytes()
        old_history = next(self.history.glob("data_*.json")).read_bytes()
        for p in self.history.glob("data_*.json"):
            p.unlink()
        self.current.unlink()
        actual = live.dispatch_to_target(target, before)
        self.assertEqual(actual, expected)
        self.assertTrue(old_current == self.current.read_bytes(), "Frozen current bytes mismatch")
        self.assertTrue(old_history == next(self.history.glob("data_*.json")).read_bytes(), "Frozen full snapshot bytes mismatch")
        with PublicationStore(self.root, self.identity).shared() as store:
            self.assertEqual(store.reader().publication["sequence"], 1)

    def test_same_clock_creates_two_observations(self):
        live.write_local_snapshot(self.identity, self.payload)
        live.write_local_snapshot(self.identity, self.payload)
        with PublicationStore(self.root, self.identity).shared() as store:
            view = store.reader()
            self.assertEqual(len(view.history_names()), 2)
            self.assertEqual(view.publication["sequence"], 2)

    def test_projection_loss_and_tamper_read_canonical(self):
        live.write_local_snapshot(self.identity, self.payload)
        expected = live.read_local_userdata(self.identity).raw_buffer
        self.current.unlink()
        self.assertTrue(live.read_local_userdata(self.identity).raw_buffer == expected)
        self.current.write_text('{"profile":{"userid":"foreign"}}')
        self.assertTrue(live.read_local_userdata(self.identity).raw_buffer == expected)

    def test_corrupt_canonical_is_unavailable(self):
        live.write_local_snapshot(self.identity, self.payload)
        store = PublicationStore(self.root, self.identity)
        with store.shared():
            reference = store.reader().manifest["files"]["current"]
        (store.objects / reference["sha256"]).unlink()
        with self.assertRaises(PublicationError):
            live.read_local_userdata(self.identity)
        with self.assertRaises(PublicationError):
            live.write_local_snapshot(self.identity, self.payload)

    def test_explicit_same_ex_only(self):
        store = PublicationStore(self.root, self.identity)
        with store.exclusive():
            live.write_local_snapshot(self.identity, self.payload, publication_store=store)
            self.assertEqual(live.read_local_userdata(self.identity, publication_store=store).parsed, self.payload)
            with self.assertRaises(PublicationError):
                live.write_local_snapshot("123", self.payload, publication_store=store)
        with self.assertRaises(PublicationError):
            live.write_local_snapshot(self.identity, self.payload, publication_store=store)
        with store.shared():
            with self.assertRaises(PublicationError):
                live.write_local_snapshot(self.identity, self.payload, publication_store=store)

    def test_refresh_preserves_actual_runtime_statuses_and_reuses_ex(self):
        update = types.ModuleType("taiko_bot.runtime.player.center.update_user")
        calls = []
        def acquire(identity, **kwargs):
            calls.append((identity, kwargs))
            return 0
        update.getUserData = acquire
        with patch.dict(sys.modules, {update.__name__: update, "plugins.utils.update_user": update}), patch.object(old, "_agent_log"):
            self.assertEqual(old.refresh_userdata_from_wahlap(self.identity), self.identity)
            store = PublicationStore(self.root, self.identity)
            with store.exclusive():
                self.assertEqual(live.refresh_userdata_from_wahlap(self.identity, publication_store=store), self.identity)
                self.assertIs(calls[-1][1]["publication_store"], store)
            for result, status in [(404, 404), (-1, 502), (None, 502)]:
                update.getUserData = lambda *args, **kwargs: result
                for module in [old, live]:
                    with self.assertRaises(module.RequestError) as caught:
                        module.refresh_userdata_from_wahlap(self.identity)
                    self.assertEqual(caught.exception.status, status)
            update.getUserData = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private password path"))
            with self.assertRaises(live.RequestError) as caught:
                live.refresh_userdata_from_wahlap(self.identity)
            self.assertNotIn("password", str(caught.exception))

    def test_retired_http_dispatch_ignores_forged_actor_before_sql_or_source(self):
        with patch.object(live, "refresh_userdata_from_wahlap", side_effect=AssertionError("Retired route fetched scores")):
            server = live.ThreadingHTTPServer(("127.0.0.1", 0), live.SyncDispatchHandler)
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05))
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            try:
                connection.request("POST", "/dispatch", json.dumps({"userid": self.identity, "userId": 1, "binding": {"source": "wahlap"}, "targetIds": ["sakura-bot"]}))
                response = connection.getresponse()
                self.assertEqual(response.status, 410)
                self.assertEqual(json.loads(response.read(2048))["error"], "sync_dispatch_retired")
                self.assertFalse(self.current.exists())
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_private_service_rejects_untrusted_requests_before_connect(self):
        from taiko_bot.cli import account_sync_cli  # Narrow real leaf modules, no Bot registry.
        from taiko_bot.runtime.player.center.account_sync import AccountSyncError, run_account_sync, sync_request_hash
        from taiko_bot.runtime.player.center.viewer_binding_authority import capture_viewer_binding, ViewerBindingDenied
        binding = {"id": "1", "taiko_id": self.identity, "source": "wahlap", "manual_account_id": None}
        request = {"userId": 1, "requestId": "a" * 32, "binding": binding, "targetIds": ["sakura-bot"]}
        request["requestHash"] = sync_request_hash(1, capture_viewer_binding(binding), request["targetIds"])
        bad = [{}, request | {"userId": True}, request | {"userId": 2**53}, request | {"requestId": "../nonce"},
               request | {"requestHash": "foreign"}, request | {"targetIds": []}, request | {"targetIds": ["sakura-bot", "sakura-bot"]},
               request | {"targetIds": ["../../foreign"]}, request | {"binding": binding | {"source": "manual"}}]
        for value in bad:
            with self.subTest(value=list(value)):
                with self.assertRaises(AccountSyncError):
                    run_account_sync(value, connection_factory=lambda: self.fail("Invalid request reached SQL"), userdata_root=self.root)
        for source in [{}, [], 1, None]:
            with self.assertRaises(ViewerBindingDenied):
                capture_viewer_binding(binding | {"source": source})


if __name__ == "__main__":
    unittest.main()
