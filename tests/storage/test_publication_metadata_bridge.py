"""Actual readonly metadata RPC against owned canonical objects."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from taiko_store import PublicationStore


@pytest.fixture
def managed(tmp_path):
    root = tmp_path / "userdata"
    directory = root / "synthetic"
    directory.mkdir(parents=True)
    for name, stamp in [("data_a.json", 1737000000.125), ("data_b.json", 1737100000.375)]:
        path = directory / name
        path.write_text('{}')
        os.utime(path, (stamp, stamp))
    store = PublicationStore(root, "synthetic")
    with store.exclusive():
        store._adopt()
        manifest = store.view()
    return root, store, manifest


def rpc(root, messages, mode="read"):
    command = [sys.executable, "-m", "taiko_store.bridge", "--root", str(root), "--identity", "synthetic", "--mode", mode]
    result = subprocess.run(command, input=''.join(json.dumps(message)+'\n' for message in messages), text=True, capture_output=True, timeout=8)
    assert len(result.stdout) < 16384 and len(result.stderr) < 8192
    return result, [json.loads(line) for line in result.stdout.splitlines()]


def test_real_metadata_rpc_keeps_distinct_captured_times_after_projection_loss(managed):
    root, store, manifest = managed
    assert manifest["files"]["history/data_a.json"] == manifest["files"]["history/data_b.json"]
    for path in (root / "synthetic").glob("data_*.json"):
        path.unlink()
    result, lines = rpc(root, [{"method": "file-times", "key": "history/data_a.json"}, {"method": "file-times", "key": "history/data_b.json"}, {"method": "finish"}])
    assert result.returncode == 0
    assert [line["times"]["mtime"] for line in lines[1:3]] == [1737000000.125, 1737100000.375]
    assert lines[1]["times"]["ctime"] == manifest["fileCtimes"]["history/data_a.json"]
    assert lines[-1] == {"finished": True}


@pytest.mark.parametrize("key", ["history/../secret.json", "history/data_absent.json", "invalid", None])
def test_real_metadata_rpc_rejects_invalid_keys_and_releases_lease(managed, key):
    root, store, manifest = managed
    result, lines = rpc(root, [{"method": "file-times", "key": key}])
    assert result.returncode != 0 and "times" not in lines[-1]
    with store.exclusive():
        assert store.view()["commitId"] == manifest["commitId"]


def test_metadata_verifies_canonical_bytes_and_cannot_describe_unpublished_staging(managed):
    root, store, manifest = managed
    result, lines = rpc(root, [{"method": "put", "key": "current", "body": '{}'}, {"method": "file-times", "key": "current"}], mode="write")
    assert result.returncode != 0 and "times" not in lines[-1]
    (store.objects / manifest["files"]["history/data_a.json"]["sha256"]).write_text('corrupt')
    result, lines = rpc(root, [{"method": "file-times", "key": "history/data_a.json"}])
    assert result.returncode != 0 and "times" not in lines[-1]
