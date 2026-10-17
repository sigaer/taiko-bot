"""Synthetic disk/process tests for the center publication boundary."""
import errno
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taiko_store import PublicationStore, PublicationError


def increment(root, ready, start):
    ready.put(True)
    start.wait(5)
    store = PublicationStore(root, "synthetic", lock_timeout=5)
    with store.exclusive():
        view = store.view()
        old = json.loads(store.read_object(view["files"]["current"]))
        old["count"] += 1
        store.commit({"current": json.dumps(old).encode(),
                      "history/data_20261011_090000_" + os.urandom(8).hex() + ".json": json.dumps(old).encode()})


def crash(root, point, nonce=None):
    def fault(name):
        if name == point:
            os._exit(73)
    store = PublicationStore(root, "synthetic", fault=fault)
    with store.exclusive():
        store.commit({"current": b'{"count":1}', "history/data_new.json": b'{"count":1}'}, transaction_id=nonce)


def reader(root, acquired, release):
    store = PublicationStore(root, "synthetic", lock_timeout=2)
    with store.shared():
        acquired.set()
        release.wait(5)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="domain-publication-", dir="/var/tmp")
        self.root = Path(self.temporary.name)
        self.store = PublicationStore(self.root, "synthetic")
        with self.store.exclusive():
            self.initial = self.store.commit({"current": b'{"count":0}', "history/data_initial.json": b'{"count":0}'})

    def tearDown(self):
        self.temporary.cleanup()

    def raw(self, key="current"):
        with self.store.shared():
            view = self.store.view()
            return self.store.read_object(view["files"][key])

    def test_cross_process_read_modify_write_keeps_both_changes(self):
        context = multiprocessing.get_context("spawn")
        ready, start = context.Queue(), context.Event()
        workers = [context.Process(target=increment, args=(str(self.root), ready, start)) for _ in range(2)]
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                self.assertTrue(ready.get(timeout=5))
            start.set()
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0, "Owned mutation process failed")
            self.assertEqual(json.loads(self.raw())["count"], 2)
            with self.store.shared():
                self.assertEqual(len(self.store.view()["files"]), 4)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            ready.close()
            ready.join_thread()

    def test_process_death_before_commit_restores_old_and_after_commit_preserves_new(self):
        context = multiprocessing.get_context("spawn")
        for point in ("objects-staged", "intent-durable", "projection-0", "projections-durable", "commit-durable"):
            with self.subTest(point=point):
                worker = context.Process(target=crash, args=(str(self.root), point))
                try:
                    worker.start()
                    worker.join(10)
                    self.assertEqual(worker.exitcode, 73, "Crash checkpoint was not reached")
                    expected = 1 if point == "commit-durable" else 0
                    self.assertEqual(json.loads(self.raw())["count"], expected)
                    self.assertEqual(json.loads((self.root / "syntheticdata.json").read_text())["count"], expected)
                    self.assertEqual((self.root / "synthetic/data_new.json").exists(), bool(expected))
                    self.assertFalse((self.store.base / "pending.json").exists())
                finally:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(5)

    def test_projection_io_failure_rolls_back_current_and_history(self):
        original = self.store._install
        calls = 0
        def fail_once(key, reference):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.ENOSPC, "Synthetic projection failure")
            return original(key, reference)
        with self.store.exclusive(), patch.object(self.store, "_install", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.store.commit({"current": b'{"count":1}', "history/data_new.json": b'{}'})
        self.assertEqual(hashlib.sha256(self.raw()).hexdigest(), hashlib.sha256(b'{"count":0}').hexdigest())
        self.assertFalse((self.root / "synthetic/data_new.json").exists())

    def test_staging_enospc_does_not_publish_or_mutate_projection(self):
        with self.store.exclusive(), patch.object(self.store, "_put_bytes", side_effect=OSError(errno.ENOSPC, "Synthetic stage failure")):
            with self.assertRaises(OSError):
                self.store.commit({"current": b'{}'})
            self.assertEqual(self.store.view()["commitId"], self.initial["commitId"])
        self.assertEqual(json.loads(self.raw())["count"], 0)

    def test_snapshot_objects_remain_immutable_across_later_commit(self):
        with self.store.exclusive():
            old = self.store.view()
            new = self.store.commit({"current": b'{"count":1}'})
            self.assertNotEqual(old["commitId"], new["commitId"])
            self.assertTrue(self.store.read_object(old["files"]["current"]) == b'{"count":0}', "Old immutable object changed")
            self.assertTrue(self.store.read_object(new["files"]["current"]) == b'{"count":1}', "New immutable object mismatch")

    def test_replace_history_is_one_commit_and_keeps_daily_archive(self):
        archive = self.root / "synthetic/daily-ability-v1-top20.json"
        archive.write_text('{"days":{"old":1}}')
        with self.store.exclusive():
            value = self.store.commit({"history/data_rebuilt.json": b'{}'}, replace_history=True)
            self.assertEqual(set(value["files"]), {"current", "history/data_rebuilt.json"})
        self.assertFalse((self.root / "synthetic/data_initial.json").exists())
        self.assertTrue(archive.read_text() == '{"days":{"old":1}}', "Daily archive changed")

    def test_identical_nonce_is_idempotent_different_input_is_rejected(self):
        nonce = "a" * 32
        with self.store.exclusive():
            first = self.store.commit({"current": b'{"count":1}'}, transaction_id=nonce)
            retry = self.store.commit({"current": b'{"count":1}'}, transaction_id=nonce)
            self.assertEqual(first["sequence"], retry["sequence"])
            with self.assertRaises(PublicationError):
                self.store.commit({"current": b'{"count":2}'}, transaction_id=nonce)

    def test_same_nonce_retry_after_owned_manifest_death_resumes_only_exact_input(self):
        context = multiprocessing.get_context("spawn")
        nonce = "b" * 32
        worker = context.Process(target=crash, args=(str(self.root), "objects-staged", nonce))
        try:
            worker.start()
            worker.join(10)
            self.assertEqual(worker.exitcode, 73, "Manifest crash was not reached")
            with self.store.exclusive():
                self.assertEqual(self.store.view()["commitId"], self.initial["commitId"])
                with self.assertRaises(PublicationError):
                    self.store.commit({"current": b'{"count":2}'}, transaction_id=nonce)
                restored = self.store.commit({"current": b'{"count":1}', "history/data_new.json": b'{"count":1}'}, transaction_id=nonce)
                self.assertEqual(restored["commitId"], nonce)
                self.assertEqual(restored["sequence"], self.initial["sequence"] + 1)
                retry = self.store.commit({"current": b'{"count":1}', "history/data_new.json": b'{"count":1}'}, transaction_id=nonce)
                self.assertEqual(retry["sequence"], restored["sequence"])
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)

    def test_uncommitted_nonce_cannot_rewind_a_later_head(self):
        def fail(name):
            if name == "objects-staged":
                raise OSError("Synthetic interrupted staged manifest")
        nonce = "c" * 32
        failed = PublicationStore(self.root, "synthetic", fault=fail)
        with failed.exclusive():
            with self.assertRaises(OSError):
                failed.commit({"current": b'{"count":1}'}, transaction_id=nonce)
        with self.store.exclusive():
            later = self.store.commit({"current": b'{"count":2}'})
            with self.assertRaises(PublicationError):
                self.store.commit({"current": b'{"count":1}'}, transaction_id=nonce)
            self.assertEqual(self.store.view()["commitId"], later["commitId"])

    def test_same_second_distinct_history_names_are_both_published(self):
        with self.store.exclusive():
            for ordinal in (1, 2):
                self.store.commit({f"history/data_20261011_090000_{ordinal:06d}.json": b'{}'})
            self.assertEqual(len(self.store.view()["files"]), 4)

    def test_corrupt_object_and_pending_metadata_fail_closed(self):
        with self.store.shared():
            reference = self.store.view()["files"]["current"]
        (self.store.objects / reference["sha256"]).write_bytes(b'{"count":9}')
        with self.assertRaisesRegex(PublicationError, "hash mismatch"):
            self.raw()
        (self.store.base / "pending.json").write_text('{"schema":1,"identity":"synthetic","changedKeys":[],"nextCommitId":"../escape"}')
        with self.assertRaises(PublicationError):
            with self.store.shared():
                self.store.view()

    def test_paths_symlinks_and_size_limits_fail_closed(self):
        for identity in ("../escape", "a/b", "", "a" * 129):
            with self.assertRaises(PublicationError):
                PublicationStore(self.root, identity)
        with self.store.exclusive():
            for key in ("../file", "history/../file", "history/data_x/escape.json"):
                with self.assertRaises(PublicationError):
                    self.store.commit({key: b'{}'})
        limited = PublicationStore(self.root, "bounded", max_file_bytes=4)
        with limited.exclusive(), self.assertRaises(PublicationError):
            limited.commit({"current": b'12345'})
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "symlink").symlink_to(outside, target_is_directory=True)
        linked = PublicationStore(self.root, "symlink")
        with linked.exclusive(), self.assertRaises(PublicationError):
            linked.commit({"history/data_x.json": b'{}'})
        self.assertEqual(list(outside.iterdir()), [])

    def test_operation_without_lock_is_rejected(self):
        with self.assertRaises(PublicationError):
            self.store.view()
        with self.store.shared(), self.assertRaises(PublicationError):
            self.store.commit({"current": b'{}'})

    def test_legacy_adoption_keeps_exact_bytes_and_invalid_history(self):
        (self.root / "legacy").mkdir()
        old = b'{ "count": 0 }\n'
        (self.root / "legacydata.json").write_bytes(old)
        (self.root / "legacy/data_bad.json").write_bytes(b'broken')
        legacy = PublicationStore(self.root, "legacy")
        with legacy.exclusive():
            adopted = legacy.commit({"history/data_new.json": b'{}'})
            self.assertTrue(legacy.read_object(adopted["files"]["current"]) == old, "Legacy raw bytes changed")
            self.assertTrue(legacy.read_object(adopted["files"]["history/data_bad.json"]) == b'broken', "Invalid history was silently removed")

    def test_two_readers_share_lease_and_block_collection(self):
        context = multiprocessing.get_context("spawn")
        acquired, release = context.Event(), context.Event()
        worker = context.Process(target=reader, args=(str(self.root), acquired, release))
        try:
            worker.start()
            self.assertTrue(acquired.wait(5))
            with self.store.shared():
                self.assertIsNotNone(self.store.view())
            blocked = PublicationStore(self.root, "synthetic", lock_timeout=0.05)
            with self.assertRaisesRegex(PublicationError, "deadline"):
                with blocked.exclusive():
                    blocked.collect()
        finally:
            release.set()
            worker.join(5)
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
        self.assertEqual(worker.exitcode, 0, "Owned lease process did not exit")

    def test_collection_keeps_current_previous_and_daily_archive(self):
        archive = self.root / "synthetic/daily-ability-v1-top20.json"
        archive.write_text('{"days":{"old":1}}')
        initial_hash = self.initial["files"]["current"]["sha256"]
        with self.store.exclusive():
            previous = self.store.commit({"current": b'{"count":1}', "history/data_initial.json": None})
            following = self.store.commit({"current": b'{"count":2}'})
            removed = self.store.collect()
            self.assertGreater(removed["commits"], 0)
            self.assertFalse((self.store.objects / initial_hash).exists())
            self.assertTrue(self.store.read_object(previous["files"]["current"]) == b'{"count":1}', "Previous recovery object lost")
            self.assertTrue(self.store.read_object(following["files"]["current"]) == b'{"count":2}', "Current object lost")
        self.assertTrue(archive.read_text() == '{"days":{"old":1}}', "Collection touched measurement archive")

    def test_collection_never_removes_other_source_projection_stage(self):
        unrelated = self.root / (".stage-other-" + "b" * 32)
        unrelated.write_bytes(b'other writer')
        with self.store.exclusive():
            self.store.collect()
        self.assertTrue(unrelated.read_bytes() == b'other writer', "Another source stage was removed")

    def test_local_bridge_stages_batch_and_eof_releases_kernel_lease(self):
        command = [sys.executable, "-m", "taiko_store.bridge", "--root", str(self.root),
                   "--identity", "synthetic", "--mode", "write", "--lifetime", "5"]
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(json.loads(child.stdout.readline())["ready"])
            for message in ({"method": "put", "key": "current", "body": '{"count":2}'},
                            {"method": "put", "key": "history/data_bridge.json", "body": '{"count":2}'},
                            {"method": "publish"}):
                child.stdin.write(json.dumps(message) + "\n")
                child.stdin.flush()
                response = json.loads(child.stdout.readline())
                self.assertNotIn("error", response)
            child.stdin.close()
            self.assertEqual(child.wait(5), 0, "Bridge EOF did not exit")
            self.assertEqual(json.loads(self.raw())["count"], 2)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(5)
            for pipe in (child.stdin, child.stdout, child.stderr):
                pipe.close()

    def test_read_bridge_rejects_mutation_without_leaking_payload(self):
        command = [sys.executable, "-m", "taiko_store.bridge", "--root", str(self.root),
                   "--identity", "synthetic", "--mode", "read", "--lifetime", "5"]
        result = subprocess.run(command, input='{"method":"put","key":"current","body":"PRIVATE_MARKER"}\n',
                                capture_output=True, text=True, timeout=7)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("PRIVATE_MARKER", result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["error"], "PUBLICATION_FAILURE")
        self.assertEqual(json.loads(self.raw())["count"], 0)

    def test_synthetic_backup_restores_exact_projection_and_recovers_interruption(self):
        restored_root = self.root / "restore"
        # Disk-backed synthetic source only; no production account or DB copy.
        shutil.copytree(self.root / ".taiko-publications", restored_root / ".taiko-publications")
        restored = PublicationStore(restored_root, "synthetic")
        install = restored._install
        attempts = 0
        def fail_once(key, reference):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError(errno.ENOSPC, "Synthetic restore interruption")
            return install(key, reference)
        with restored.exclusive(), patch.object(restored, "_install", side_effect=fail_once):
            with self.assertRaises(OSError):
                restored.restore_projections()
        self.assertTrue((restored.base / "pending.json").exists())
        with restored.shared():
            manifest = restored.view()
            self.assertEqual(manifest["commitId"], self.initial["commitId"])
        self.assertTrue((restored_root / "syntheticdata.json").read_bytes() == b'{"count":0}', "Restored C mismatch")
        self.assertTrue((restored_root / "synthetic/data_initial.json").read_bytes() == b'{"count":0}', "Restored H mismatch")
        self.assertFalse((restored.base / "pending.json").exists())

    def test_valid_json_pointer_corruption_and_fifo_metadata_are_rejected(self):
        pointer = self.store.base / "committed.json"
        value = json.loads(pointer.read_text())
        value["sequence"] += 1
        pointer.write_text(json.dumps(value))
        with self.assertRaisesRegex(PublicationError, "record mismatch"):
            with self.store.shared():
                self.store.view()
        pointer.unlink()
        os.mkfifo(pointer)
        with self.assertRaisesRegex(PublicationError, "plain file"):
            with self.store.shared():
                self.store.view()


if __name__ == "__main__":
    unittest.main()
