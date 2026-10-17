"""Synthetic independent backup and portable source/daily recovery tests."""
import errno
import fcntl
import hashlib
import json
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taiko_store import PublicationError, PublicationStore
from taiko_store.backup import export_source_backup, restore_source_backup, verify_source_backup, purge_backup_archives


IDENTITY = "synthetic"
BACKUP_KEY = "b" * 32
RESTORE_KEY = "c" * 32
CURRENT = b'{ "meta":{"nickname":"synthetic","source":"manual"}, "count": 0 }\n'
HISTORY = b'invalid legacy history, preserved verbatim\n'
ARCHIVES = {
    "daily-ability-v1-top20.json": b'{"days":{"2026-10-10":{"rating":123.0}},"revision":1}\n',
    "daily-ability-v2-recent.json": b'{"days":{"2026-10-10":{"ability":45.0}},"revision":1}\n',
}


def crash_backup(root, key, point):
    def fault(name):
        if name == point:
            os._exit(73)
    store = PublicationStore(root, IDENTITY, fault=fault)
    with store.exclusive():
        export_source_backup(store, key)


def crash_restore(root, point):
    def fault(name):
        if name == point:
            os._exit(73)
    store = PublicationStore(root, IDENTITY, fault=fault)
    with store.exclusive():
        restore_source_backup(store, BACKUP_KEY, transaction_id=RESTORE_KEY)


def crash_purge(root):
    def fault(name):
        if name == "delete.archive-removed":
            os._exit(73)
    store = PublicationStore(root, IDENTITY, fault=fault)
    with store.exclusive():
        purge_backup_archives(store, BACKUP_KEY)


class SourceBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="source-backup-", dir="/var/tmp")
        self.workspace = Path(self.temporary.name)
        self.root = self.workspace / "source"
        self.root.mkdir()
        (self.root / IDENTITY).mkdir()
        (self.root / (IDENTITY + "data.json")).write_bytes(CURRENT)
        (self.root / IDENTITY / "data_bad.json").write_bytes(HISTORY)
        for name, raw in ARCHIVES.items():
            (self.root / IDENTITY / name).write_bytes(raw)
        self.store = PublicationStore(self.root, IDENTITY)

    def tearDown(self):
        self.temporary.cleanup()

    def backup_path(self, root=None, key=BACKUP_KEY):
        return (root or self.root) / ".manual_deleted" / (IDENTITY + "-" + key)

    def export(self, key=BACKUP_KEY):
        with self.store.exclusive():
            return export_source_backup(self.store, key)

    def portable_target(self, name="restore"):
        destination = self.workspace / name
        shutil.copytree(self.backup_path(), self.backup_path(destination))
        return PublicationStore(destination, IDENTITY)

    def assert_restored(self, store):
        expected = {"current": CURRENT, "history/data_bad.json": HISTORY}
        with store.shared():
            view = store.view()
            self.assertEqual(set(view["files"]), set(expected))
            for key, raw in expected.items():
                self.assertEqual(view["files"][key]["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertTrue(store.read_object(view["files"][key]) == raw, "Restored source bytes differ")
                self.assertTrue(store._projection_path(key).read_bytes() == raw, "Restored projection bytes differ")
        for name, raw in ARCHIVES.items():
            self.assertTrue((store.root / IDENTITY / name).read_bytes() == raw, "Restored daily bytes differ")

    def test_legacy_bytes_invalid_history_and_daily_are_independent_verified_copies(self):
        metadata = self.export()
        self.assertEqual(metadata["source"]["sequence"], 0)
        with self.store.shared():
            self.assertEqual(verify_source_backup(self.store, BACKUP_KEY), metadata)
        for key, reference in metadata["source"]["files"].items():
            copied = self.backup_path() / (IDENTITY + "data.json") if key == "current" else self.backup_path() / IDENTITY / "data_bad.json"
            self.assertNotEqual(copied.stat().st_ino, (self.store.objects / reference["sha256"]).stat().st_ino)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.backup_path().stat().st_mode), 0o700)
        # Old writers can corrupt hard-linked projections; the backup survives.
        with self.store.exclusive():
            self.store.restore_projections()
        (self.root / (IDENTITY + "data.json")).write_bytes(b'corrupted by synthetic old writer')
        with self.store.shared():
            self.assertEqual(verify_source_backup(self.store, BACKUP_KEY), metadata)

    def test_backup_uses_canonical_objects_when_legacy_projections_are_missing(self):
        with self.store.exclusive():
            self.store.commit({"current": CURRENT})
        (self.root / (IDENTITY + "data.json")).unlink()
        (self.root / IDENTITY / "data_bad.json").unlink()
        self.export()
        self.assertTrue((self.backup_path() / (IDENTITY + "data.json")).read_bytes() == CURRENT, "Canonical C lost")
        self.assertTrue((self.backup_path() / IDENTITY / "data_bad.json").read_bytes() == HISTORY, "Canonical H lost")

    def test_same_backup_key_is_immutable_and_new_key_captures_new_generation(self):
        first = self.export()
        with self.store.exclusive():
            updated = self.store.commit({"current": b'{"count":1}'})
            self.assertEqual(export_source_backup(self.store, BACKUP_KEY), first)
            following = export_source_backup(self.store, "d" * 32)
        self.assertEqual(following["source"]["commitId"], updated["commitId"])
        self.assertNotEqual(first["source"]["commitId"], updated["commitId"])

    def test_portable_restore_needs_no_old_objects_and_retry_preserves_exact_files(self):
        self.export()
        target = self.portable_target()
        shutil.rmtree(self.root)
        with target.exclusive():
            first = restore_source_backup(target, BACKUP_KEY, transaction_id=RESTORE_KEY)
            second = restore_source_backup(target, BACKUP_KEY, transaction_id=RESTORE_KEY)
        self.assertEqual(first["source"]["commitId"], second["source"]["commitId"])
        self.assert_restored(target)

    def test_partial_copy_failure_cleans_only_owned_stage_and_keeps_source(self):
        original = __import__("taiko_store.backup", fromlist=["_copy_verified"])._copy_verified
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(errno.ENOSPC, "Synthetic backup interruption")
            return original(*args, **kwargs)
        with self.store.exclusive(), patch("taiko_store.backup._copy_verified", side_effect=fail_second):
            with self.assertRaises(OSError):
                export_source_backup(self.store, BACKUP_KEY)
            self.assertEqual(self.store.view()["sequence"], 0)
        self.assertFalse(self.backup_path().exists())
        self.assertEqual(list((self.root / ".manual_deleted").iterdir()), [])
        self.assertTrue((self.root / (IDENTITY + "data.json")).read_bytes() == CURRENT, "Source changed on failed backup")
        self.export()

    def test_disk_headroom_rejection_precedes_copy_and_completed_receipt(self):
        with patch("taiko_store.backup.shutil.disk_usage", return_value=shutil._ntuple_diskusage(100, 99, 1)):
            with self.assertRaisesRegex(PublicationError, "headroom"):
                self.export()
        self.assertFalse(self.backup_path().exists())

    def run_owned_crash(self, target, args):
        child = multiprocessing.get_context("spawn").Process(target=target, args=args)
        try:
            child.start()
            child.join(10)
            self.assertEqual(child.exitcode, 73, "Owned crash checkpoint was not reached")
        finally:
            if child.is_alive():
                child.terminate()
                child.join(5)

    def test_real_process_death_at_all_backup_boundaries_is_retryable(self):
        points = ("backup.created", "backup.source-complete", "backup.archives-complete", "backup.metadata-commit", "backup.promoted")
        for index, point in enumerate(points):
            with self.subTest(point=point):
                key = format(index + 1, "032x")
                self.run_owned_crash(crash_backup, (str(self.root), key, point))
                self.assertEqual(self.backup_path(key=key).exists(), point == "backup.promoted")
                result = self.export(key)
                with self.store.shared():
                    self.assertEqual(verify_source_backup(self.store, key), result)
                self.assertFalse((self.root / ".manual_deleted" / (".stage-" + IDENTITY + "-" + key)).exists())

    def test_portable_restore_recovers_process_death_before_and_after_source_commit(self):
        self.export()
        for index, point in enumerate(("intent-durable", "restore.source-committed", "restore.archive-installed")):
            with self.subTest(point=point):
                target = self.portable_target("restore-" + str(index))
                self.run_owned_crash(crash_restore, (str(target.root), point))
                with target.exclusive():
                    restore_source_backup(target, BACKUP_KEY, transaction_id=RESTORE_KEY)
                self.assert_restored(target)

    def test_daily_namespace_lock_has_deadline_and_releases_source_fence(self):
        path = self.root / IDENTITY / next(iter(ARCHIVES))
        fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            limited = PublicationStore(self.root, IDENTITY, lock_timeout=0.05)
            with limited.exclusive(), self.assertRaisesRegex(PublicationError, "deadline"):
                export_source_backup(limited, BACKUP_KEY)
        finally:
            os.close(fd)
        self.assertFalse(self.backup_path().exists())
        self.export()

    def test_verification_of_missing_backup_does_not_create_directories(self):
        with self.store.shared(), self.assertRaises(FileNotFoundError):
            verify_source_backup(self.store, BACKUP_KEY)
        self.assertFalse((self.root / ".manual_deleted").exists())
        (self.root / ".manual_deleted").mkdir()
        with self.store.shared(), self.assertRaises(FileNotFoundError):
            verify_source_backup(self.store, BACKUP_KEY)
        self.assertFalse(self.backup_path().exists())

    def test_symlink_parent_and_backup_history_are_rejected_without_outside_writes(self):
        outside = self.workspace / "outside"
        outside.mkdir()
        (self.root / ".manual_deleted").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(PublicationError):
            self.export()
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / ".manual_deleted").unlink()
        self.export()
        shutil.rmtree(self.backup_path() / IDENTITY)
        (self.backup_path() / IDENTITY).symlink_to(self.root / IDENTITY, target_is_directory=True)
        with self.store.shared(), self.assertRaises(PublicationError):
            verify_source_backup(self.store, BACKUP_KEY)

    def test_daily_fifo_symlink_and_oversize_fail_closed_before_completed_receipt(self):
        path = self.root / IDENTITY / next(iter(ARCHIVES))
        for kind in ("fifo", "symlink", "oversize"):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == "fifo":
                    os.mkfifo(path)
                elif kind == "symlink":
                    path.symlink_to(self.root / (IDENTITY + "data.json"))
                else:
                    with path.open("wb") as output:
                        output.truncate(8 * 1024**2 + 1)
                with self.assertRaises((OSError, PublicationError)):
                    self.export()
                self.assertFalse(self.backup_path().exists())

    def test_corrupt_backup_metadata_or_object_blocks_restore_before_source_publish(self):
        self.export()
        for kind in ("metadata", "object"):
            with self.subTest(kind=kind):
                target = self.portable_target("corrupt-" + kind)
                path = self.backup_path(target.root) / ("backup.json" if kind == "metadata" else IDENTITY + "data.json")
                path.write_bytes(b'{}' if kind == "metadata" else b'corrupt')
                with target.exclusive(), self.assertRaises(PublicationError):
                    restore_source_backup(target, BACKUP_KEY, transaction_id=RESTORE_KEY)
                with target.shared():
                    self.assertIsNone(target.view())
                self.assertFalse((target.root / (IDENTITY + "data.json")).exists())

    def test_restore_rejects_different_active_scores_legacy_files_and_daily_measurements(self):
        self.export()
        for kind in ("managed", "legacy", "daily", "namespace"):
            with self.subTest(kind=kind):
                target = self.portable_target("occupied-" + kind)
                (target.root / IDENTITY).mkdir()
                if kind == "managed":
                    with target.exclusive():
                        original = target.commit({"current": b'other source'})
                elif kind == "legacy":
                    (target.root / (IDENTITY + "data.json")).write_bytes(b'other legacy')
                else:
                    name = next(iter(ARCHIVES)) if kind == "daily" else "daily-ability-other.json"
                    (target.root / IDENTITY / name).write_bytes(b'other archive')
                with target.exclusive(), self.assertRaises(PublicationError):
                    restore_source_backup(target, BACKUP_KEY, transaction_id=RESTORE_KEY)
                with target.shared():
                    if kind == "managed":
                        self.assertEqual(target.view()["commitId"], original["commitId"])
                    else:
                        self.assertIsNone(target.view())

    def test_operations_require_correct_source_lock_and_safe_backup_key(self):
        with self.assertRaises(PublicationError):
            export_source_backup(self.store, BACKUP_KEY)
        with self.store.shared(), self.assertRaises(PublicationError):
            export_source_backup(self.store, BACKUP_KEY)
        with self.store.exclusive():
            for key in ("../escape", "", "a" * 33, "X" * 32):
                with self.assertRaises(PublicationError):
                    export_source_backup(self.store, key)

    def test_actual_bridge_reports_backup_generation_without_exposing_paths(self):
        command = [sys.executable, "-m", "taiko_store.bridge", "--root", str(self.root),
                   "--identity", IDENTITY, "--mode", "write", "--lifetime", "5"]
        result = subprocess.run(command, input=json.dumps({"method": "backup", "backupKey": BACKUP_KEY}) + '\n{"method":"finish"}\n',
                                capture_output=True, text=True, timeout=7)
        self.assertEqual(result.returncode, 0, "Backup bridge failed")
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertIsNone(responses[0]["view"])
        backup = responses[1]
        self.assertTrue(backup["backedUp"])
        self.assertEqual(backup["source"]["commitId"], backup["view"]["commitId"])
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        self.assertFalse(result.stderr)

    def test_archive_cleanup_is_verified_idempotent_and_recovers_real_process_death(self):
        metadata = self.export()
        self.run_owned_crash(crash_purge, (str(self.root),))
        with self.store.exclusive():
            purge_backup_archives(self.store, BACKUP_KEY)
            self.assertEqual(purge_backup_archives(self.store, BACKUP_KEY), {"removed": 0})
            self.assertEqual(verify_source_backup(self.store, BACKUP_KEY), metadata)
            self.assertEqual(self.store.view()["files"], metadata["source"]["files"])
        self.assertTrue(all(not (self.root / IDENTITY / name).exists() for name in ARCHIVES))

    def test_changed_source_or_daily_archive_stops_cleanup_before_first_unlink(self):
        self.export()
        for kind in ("source", "daily", "namespace"):
            with self.subTest(kind=kind):
                if kind == "source":
                    with self.store.exclusive():
                        self.store.commit({"current": b'updated source'})
                elif kind == "daily":
                    (self.root / IDENTITY / next(iter(ARCHIVES))).write_bytes(b'updated daily')
                else:
                    (self.root / IDENTITY / "daily-ability-other.json").write_bytes(b'new namespace')
                with self.store.exclusive(), self.assertRaises(PublicationError):
                    purge_backup_archives(self.store, BACKUP_KEY)
                self.assertTrue(all((self.root / IDENTITY / name).exists() for name in ARCHIVES))
                # Restore the original committed head for each isolated case.
                if kind == "source":
                    old = json.loads((self.backup_path() / "backup.json").read_text())["source"]
                    (self.store.base / "committed.json").write_text(json.dumps(old))
                elif kind == "daily":
                    name = next(iter(ARCHIVES))
                    (self.root / IDENTITY / name).write_bytes(ARCHIVES[name])

    def test_new_backup_reclaims_only_this_identity_unpromoted_crash_stages(self):
        self.run_owned_crash(crash_backup, (str(self.root), BACKUP_KEY, "backup.source-complete"))
        parent = self.root / ".manual_deleted"
        other = parent / (".stage-other-" + "a" * 32)
        other.mkdir()
        (other / "owned-by-another-source").write_bytes(b'keep')
        self.export("d" * 32)
        self.assertFalse((parent / (".stage-" + IDENTITY + "-" + BACKUP_KEY)).exists())
        self.assertTrue((other / "owned-by-another-source").read_bytes() == b'keep', "Other backup stage changed")


if __name__ == "__main__":
    unittest.main()
