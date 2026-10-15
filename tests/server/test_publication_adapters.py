"""Real center acquisition adapter, synthetic disk, frozen legacy oracle."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from taiko_store import PublicationStore, PublicationError

ROOT = Path(__file__).resolve().parent
import taiko_bot.runtime.player.center as _owner
OWNED = Path(_owner.__file__).parent


class FrozenClock(datetime):
    instant = datetime(2026, 10, 11, 9, 0, 0)

    @classmethod
    def now(cls):
        return cls.instant


def load_storage(source, name):
    package = types.ModuleType(name)
    package.__path__ = []
    daily = types.ModuleType(name + ".daily_ability")
    daily.capture_snapshot = lambda *_args, **_kwargs: None
    module = types.ModuleType(name + ".userdata_storage")
    module.__package__ = name
    runtime_env = types.ModuleType("taiko_runtime.runtime_env")
    runtime_env.load_runtime_environment = lambda: None
    with patch.dict(sys.modules, {name: package, name + ".daily_ability": daily, "taiko_runtime.runtime_env": runtime_env}):
        exec(compile(source, str(OWNED / "userdata_storage.py"), "exec"), module.__dict__)
    return module, {name: package, name + ".daily_ability": daily}


def song(number, stage, score):
    return {"song_no": number, "level": 4, "high_score": score, "stage_cnt": stage,
            "clear_cnt": 1, "full_combo_cnt": 0, "dondaful_combo_cnt": 0,
            "update_datetime": "2026-10-11 08:00:00", "good_cnt": 10}


def payload(songs):
    return {"profile": {"userid": "synthetic", "mydon_name": "Synthetic"},
            "achievement": {"ary_crown_count": [1, 0, 0]}, "songs": songs, "dojo": {}}


class AcquisitionPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (OWNED / "userdata_storage.py").read_text()
        legacy = (ROOT / "fixtures/userdata_storage_legacy.py").read_text()
        cls.actual, cls.actual_modules = load_storage(source, "publication_actual_fixture")
        cls.legacy, cls.legacy_modules = load_storage(legacy, "publication_legacy_fixture")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="publication-adapter-", dir="/var/tmp")
        self.root = Path(self.temporary.name)
        env = patch.dict(os.environ)
        env.start(); self.addCleanup(env.stop)
        os.environ.pop("TAIKO_USERDATA_DIR", None)

    def tearDown(self):
        self.temporary.cleanup()

    def configure(self, module, directory):
        module.TAIKO_SONG_DIR = str(directory)
        module.datetime = FrozenClock
        module._load_locked_song_keys = lambda _identity: {(1, 4)}

    def test_actual_acquisition_current_and_full_delta_equal_legacy(self):
        cases = [payload([song(1, 1, 800_000), song(2, 1, 600_000)]),
                 payload([song(1, 2, 810_000), song(2, 2, 650_000), song(3, 1, 500_000)]),
                 payload([song(3, 2, 520_000)])]
        for module, directory in ((self.actual, self.root / "actual"), (self.legacy, self.root / "legacy")):
            self.configure(module, directory)
        with patch.dict(sys.modules, self.actual_modules | self.legacy_modules), patch("pymysql.connect", side_effect=AssertionError("DB forbidden")):
            for index, incoming in enumerate(cases):
                FrozenClock.instant = datetime(2026, 10, 11, 9, index, 0)
                for module in (self.legacy, self.actual):
                    module.save_userdata("synthetic", incoming, source="hiroba")
        old_current = (self.root / "legacy/syntheticdata.json").read_bytes()
        new_current = (self.root / "actual/syntheticdata.json").read_bytes()
        self.assertEqual(hashlib.sha256(old_current).hexdigest(), hashlib.sha256(new_current).hexdigest())
        history = lambda directory: [json.loads(path.read_text()) for path in sorted((directory / "synthetic").glob("data_*.json"))]
        self.assertEqual(history(self.root / "legacy"), history(self.root / "actual"))
        with PublicationStore(self.root / "actual", "synthetic").shared() as store:
            self.assertEqual(store.view()["sequence"], 3)
            self.assertEqual(len(store.reader().history_names()), 3)

    def test_repeated_clock_value_keeps_both_real_acquisition_observations(self):
        self.configure(self.actual, self.root)
        nonces = iter(["f" * 32, "a" * 32])
        nonce_source = types.SimpleNamespace(uuid4=lambda: types.SimpleNamespace(hex=next(nonces)))
        with patch.dict(sys.modules, self.actual_modules), patch.object(self.actual, "uuid", nonce_source):
            FrozenClock.instant = datetime(2026, 10, 11, 9, 0, 0)
            for stage in (1, 2):
                self.actual.save_userdata("synthetic", payload([song(2, stage, 600_000)]), source="wahlap")
        with PublicationStore(self.root, "synthetic").shared() as store:
            reader = store.reader()
            self.assertEqual(len(reader.history_names()), 2)
            records = [json.loads(reader.history_raw(name)) for name in sorted(reader.history_names())]
            self.assertEqual(records[0]["songs"][0]["stage_cnt"], 1)
            self.assertEqual(records[1]["songs"][0]["stage_cnt"], 2)

    def test_daily_capture_receives_the_actual_publication_root(self):
        self.configure(self.actual, self.root)
        calls = []
        daily = self.actual_modules[self.actual.__package__ + ".daily_ability"]
        with patch.dict(sys.modules, self.actual_modules), patch.object(daily, "capture_snapshot", side_effect=lambda *_args, **kwargs: calls.append(Path(kwargs["userdata_dir"]))):
            self.actual.save_userdata("synthetic", payload([song(2, 1, 600_000)]), source="wahlap")
        self.assertEqual(calls, [self.root])

    def test_lock_lookup_failure_stops_real_acquisition_without_new_commit(self):
        self.configure(self.actual, self.root)
        with patch.dict(sys.modules, self.actual_modules):
            self.actual.save_userdata("synthetic", payload([song(1, 1, 800_000)]), source="wahlap")
            with PublicationStore(self.root, "synthetic").shared() as store:
                before = store.view()["commitId"]
            with patch.object(self.actual, "_load_locked_song_keys", side_effect=PublicationError("Synthetic lock lookup failure")):
                with self.assertRaises(PublicationError):
                    self.actual.save_userdata("synthetic", payload([song(1, 2, 810_000)]), source="wahlap")
            with PublicationStore(self.root, "synthetic").shared() as store:
                self.assertEqual(store.view()["commitId"], before)
                self.assertEqual(json.loads(store.reader().current_raw())["songs"][0]["high_score"], 800_000)

    def test_reader_expires_at_lease_end_and_does_not_rebind_to_new_lease(self):
        store = PublicationStore(self.root, "synthetic")
        with store.exclusive():
            store.commit({"current": b'{"songs":[]}'})
            reader = store.reader()
            self.assertTrue(reader.current_raw() == b'{"songs":[]}', "Current raw mismatch")
        with self.assertRaises(PublicationError):
            reader.current_raw()
        with store.shared(), self.assertRaisesRegex(PublicationError, "expired lease"):
            reader.current_raw()

    def test_reader_uses_canonical_objects_and_keeps_legacy_invalid_evidence(self):
        directory = self.root / "synthetic"
        directory.mkdir()
        (self.root / "syntheticdata.json").write_text('{"songs":[]}')
        (directory / "data_bad.json").write_text("invalid")
        store = PublicationStore(self.root, "synthetic")
        with store.shared():
            reader = store.reader()
            self.assertIsNone(reader.publication)
            self.assertEqual(reader.history_names(), ["data_bad.json"])
        with store.exclusive():
            store.commit({"history/data_good.json": b'{"songs":[]}'})
        # Removing a compatibility projection cannot make committed data vanish.
        (directory / "data_good.json").unlink()
        with store.shared():
            reader = store.reader()
            self.assertTrue(reader.history_raw("data_bad.json") == b'invalid', "Invalid evidence changed")
            self.assertTrue(reader.history_raw("data_good.json") == b'{"songs":[]}', "Canonical history lost")


if __name__ == "__main__":
    unittest.main()
