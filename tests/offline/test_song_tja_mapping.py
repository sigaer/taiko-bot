from __future__ import annotations

import json

import pytest

from taiko_bot.offline import song_tja_mapping


def test_normalize_song_tja_mapping_converts_windows_paths() -> None:
    mapping = song_tja_mapping.normalize_song_tja_mapping(
        {"1": r"09 Namco Original\Tenjiku 2000\Tenjiku 2000.tja", "2": ""}
    )

    assert mapping == {
        1: "09 Namco Original/Tenjiku 2000/Tenjiku 2000.tja",
        2: "",
    }


@pytest.mark.parametrize("path", ["../outside.tja", "/tmp/outside.tja", "song.ogg"])
def test_normalize_song_tja_mapping_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError):
        song_tja_mapping.normalize_song_tja_mapping({"1": path})


def test_refresh_song_tja_mapping_writes_validated_cache(tmp_path, monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"7": r"01 Pop\Example\Example.tja"}

    monkeypatch.setattr(
        song_tja_mapping.requests, "get", lambda *_args, **_kwargs: Response()
    )
    cache = tmp_path / "song_id2tjapath.json"

    result = song_tja_mapping.refresh_song_tja_mapping(
        path=cache, minimum_entries=1
    )

    assert result == {7: "01 Pop/Example/Example.tja"}
    assert json.loads(cache.read_text(encoding="utf-8")) == {
        "7": "01 Pop/Example/Example.tja"
    }


def test_refresh_does_not_replace_cache_with_truncated_mapping(
    tmp_path, monkeypatch
) -> None:
    cache = tmp_path / "song_id2tjapath.json"
    cache.write_text('{"1": "old.tja"}\n', encoding="utf-8")

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"7": "new.tja"}

    monkeypatch.setattr(
        song_tja_mapping.requests, "get", lambda *_args, **_kwargs: Response()
    )

    with pytest.raises(ValueError, match="expected at least 2"):
        song_tja_mapping.refresh_song_tja_mapping(
            path=cache, minimum_entries=2
        )

    assert json.loads(cache.read_text(encoding="utf-8")) == {"1": "old.tja"}
