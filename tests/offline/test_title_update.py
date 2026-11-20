import json
from pathlib import Path
import subprocess
from unittest import mock

import pytest

from taiko_bot.offline.title_update import refresh_title_relations


def cached_root(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/title_catalog_cache.json").write_text(json.dumps({"titles": [{"uid": 1}]}))
    return tmp_path


def test_failed_official_refresh_prevents_generation_and_publication(tmp_path):
    with mock.patch("taiko_bot.services.title_catalog.refresh_title_catalog_cache", return_value=[]), \
         mock.patch("taiko_bot.offline.title_update.subprocess.run") as run:
        with pytest.raises(ValueError, match="refresh failed"):
            refresh_title_relations(runtime_root=tmp_path)
    run.assert_not_called()


def test_generation_failure_prevents_all_api_publication(tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command)
    with mock.patch("taiko_bot.offline.title_update.subprocess.run", side_effect=run):
        with pytest.raises(subprocess.CalledProcessError):
            refresh_title_relations(runtime_root=cached_root(tmp_path), cached=True)
    assert len(calls) == 1
    assert "extract_title_song_relations.py" in calls[0][1]


def test_preview_never_applies_and_sync_failure_propagates(tmp_path):
    runtime = cached_root(tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1].endswith("sync_title_song_relations.py"):
            raise subprocess.CalledProcessError(1, command)
    with mock.patch("taiko_bot.offline.title_update.subprocess.run", side_effect=run):
        with pytest.raises(subprocess.CalledProcessError):
            refresh_title_relations(runtime_root=runtime, cached=True, apply=False)
    assert len(calls) == 2
    assert "--apply" not in calls[1][0]
    assert all(kwargs["timeout"] <= 330 for _, kwargs in calls)


def test_daily_publication_uses_explicit_song_catalog_and_private_config(tmp_path):
    runtime = cached_root(tmp_path)
    with mock.patch("taiko_bot.offline.title_update.subprocess.run") as run:
        refresh_title_relations(runtime_root=runtime, cached=True)
    generate, publish = [call.args[0] for call in run.call_args_list]
    assert generate[generate.index("--songs") + 1] == str(runtime / "songs/song_data.json")
    assert publish[publish.index("--config") + 1] == str(runtime / "data/title_sync.json")
    assert publish[-1] == "--apply"
