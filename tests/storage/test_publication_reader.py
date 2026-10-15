"""Real Python CLIs, owned score roots, and a frozen pre-reader adapter oracle."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from taiko_store import PublicationStore, PublicationError
from taiko_store.reader import read_current_json

SOURCE = Path(__file__).resolve().parents[2]
FROZEN = "f3146cf"
IDENTITY = "114514"
COMMANDS = [
    ["plugins.utils.recommendation_intelligence", "rating", IDENTITY],
    ["plugins.utils.recommendation_intelligence", "ordinary", IDENTITY, "--basis", "rating", "--limit", "3"],
    ["plugins.utils.recommendation_intelligence", "ordinary", IDENTITY, "--basis", "stamina", "--limit", "3"],
    ["plugins.utils.recommendation_intelligence", "target", IDENTITY, "--target", "full_combo", "--limit", "3"],
    ["plugins.utils.recommendation_intelligence", "target", IDENTITY, "--target", "goku", "--limit", "3"],
    ["growth_compute", "growth", "--user", IDENTITY, "--limit", "3"],
]

GUARD = '''import os,sys
from pathlib import Path
allowed=Path(os.environ["OWNED_COMPUTE_QA_ROOT"]).resolve()
def guard(event,args):
 if event=="socket.connect": raise PermissionError("Offline compute QA forbids network")
 if event in ("open","os.mkdir","os.remove","os.rmdir","os.rename"):
  for value in args[:2] if event=="os.rename" else args[:1]:
   if not isinstance(value,(str,bytes)): continue
   path=Path(os.fsdecode(value)).resolve()
   if any(path==Path(root) or Path(root) in path.parents for root in ("/home/sigaer/taiko/userdata","/home/sigaer/taiko-bot/userdata")):
    raise PermissionError("Offline compute QA forbids production score access")
   mutation=event!="open" or (len(args)>2 and isinstance(args[2],int) and args[2]&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
   if mutation and path!=Path("/dev/null") and path!=allowed and allowed not in path.parents:
    raise PermissionError("Offline compute QA forbids writes outside its owned root")
sys.addaudithook(guard)
'''


class CanonicalComputeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="canonical-compute-", dir="/var/tmp")
        self.root = Path(self.temporary.name)
        self.data = self.root / "userdata"
        self.data.mkdir()
        self.payload = {"profile": {"userid": IDENTITY, "mydon_name": "Synthetic 鼓众"}, "songs": []}

    def tearDown(self):
        self.temporary.cleanup()

    def publish(self):
        store = PublicationStore(self.data, IDENTITY)
        with store.exclusive():
            store.commit({"current": json.dumps(self.payload, ensure_ascii=False).encode()})
        return store

    def test_managed_current_ignores_missing_or_changed_projection(self):
        self.publish()
        projection = self.data / (IDENTITY + "data.json")
        projection.unlink()
        self.assertEqual(read_current_json(self.data, IDENTITY), self.payload)
        projection.write_text('{"songs": [], "private": "wrong source"}')
        self.assertEqual(read_current_json(self.data, IDENTITY), self.payload)

    def test_corrupt_canonical_current_does_not_read_valid_projection(self):
        store = self.publish()
        with store.shared():
            reference = store.view()["files"]["current"]
        (store.objects / reference["sha256"]).write_bytes(b"corrupt")
        with self.assertRaises(PublicationError):
            read_current_json(self.data, IDENTITY)

    def test_tombstone_does_not_resurrect_an_old_projection(self):
        store = self.publish()
        with store.exclusive():
            store.commit({"current": None})
        (self.data / (IDENTITY + "data.json")).write_text(json.dumps(self.payload))
        with self.assertRaises(FileNotFoundError):
            read_current_json(self.data, IDENTITY)

    def test_legacy_value_shape_is_preserved_and_has_no_publication_claim(self):
        for payload in (self.payload, [{"song_no": 1}], None):
            (self.data / (IDENTITY + "data.json")).write_text(json.dumps(payload))
            self.assertEqual(read_current_json(self.data, IDENTITY), payload)
        with PublicationStore(self.data, IDENTITY).shared() as store:
            self.assertIsNone(store.reader().publication)

    def test_legacy_symlink_and_invalid_identity_are_rejected(self):
        other = self.root / "other.json"
        other.write_text(json.dumps(self.payload))
        (self.data / (IDENTITY + "data.json")).symlink_to(other)
        with self.assertRaises(OSError):
            read_current_json(self.data, IDENTITY)
        with self.assertRaises(PublicationError):
            read_current_json(self.data, "../114514")

    def test_missing_managed_object_and_invalid_managed_json_fail_as_publication_errors(self):
        store = self.publish()
        with store.shared():
            reference = store.view()["files"]["current"]
        (store.objects / reference["sha256"]).unlink()
        with self.assertRaises(PublicationError):
            read_current_json(self.data, IDENTITY)
        # Infrastructure accepts raw score bytes; the JSON reader owns decoding.
        with store.exclusive():
            store.commit({"current": b"not-json"})
        with self.assertRaises(PublicationError):
            read_current_json(self.data, IDENTITY)


if __name__ == "__main__":
    unittest.main()
