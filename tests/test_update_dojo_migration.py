import json

from taiko_bot.runtime.player.center import draw_dress
from taiko_bot.runtime.player.center.dojo_version import normalize_versioned_dojo_scores


def _dojo(version, *, mark=1, score=800000):
    return {
        "version": version,
        "scores": [{
            "dan_id": 7, "grade": "二段", "level_mark": mark,
            "songs": [{"reached": True, "highscore": {"score": score}}] * 3,
        }],
        "levelList": [],
    }


def _items(sections, label):
    return next(section["items"] for section in sections if section["label"] == label)


def test_update_uses_2026_songs_and_resets_previous_version_achievements():
    previous = _dojo("2025", mark=6, score=1000000)
    current = _dojo("2026")
    left, right = draw_dress._collect_dojo_change_sections(previous, current, include_score_refresh=True)
    assert _items(left, "取得赤合格")[0]["title"] == "虹2026二段"
    reached = _items(left, "到达新曲")
    assert {item["title"] for item in reached} == {
        "虹2026二段 第1曲·メズマライザー",
        "虹2026二段 第2曲·only my railgun",
        "虹2026二段 第3曲·カルメン 組曲一番終曲",
    }
    assert all(item["line_icon_path"].name == "4.png" for item in reached)
    assert len(_items(right, "段位内刷新最高分")) == 3


def test_same_version_keeps_existing_achievement_and_score_comparison():
    left, right = draw_dress._collect_dojo_change_sections(
        _dojo("2026"), _dojo("2026"), include_score_refresh=True,
    )
    assert left == right == []
    left, right = draw_dress._collect_dojo_change_sections(
        _dojo("2026"), _dojo("2026", score=900000), include_score_refresh=True,
    )
    assert left == []
    assert len(_items(right, "段位内刷新最高分")) == 3


def test_previous_version_uses_its_own_song_catalog():
    left, _ = draw_dress._collect_dojo_change_sections({}, _dojo("2025"))
    songs = draw_dress._load_dojo_grade_display_map("2025")[7]["songs"]
    assert {item["title"] for item in _items(left, "到达新曲")} == {
        f"虹2025二段 第{idx}曲·{song['title']}"
        for idx, song in enumerate(songs, 1)
    }


def test_version_reset_without_scores_does_not_report_old_achievements():
    assert draw_dress._collect_dojo_change_sections(
        _dojo("2025", mark=6), {"version": "2026", "scores": [], "levelList": []},
    ) == ([], [])


def test_snapshot_history_preserves_explicit_version_through_song_only_delta(tmp_path, monkeypatch):
    history = tmp_path / "123"
    history.mkdir()
    for stamp, payload in [
        ("20261014_090000", {"_meta": {"full": True}, "dojo": _dojo("2026")}),
        ("20261014_100000", {"songs": []}),
        ("20261014_110000", {"dojo": _dojo("2026", score=900000)}),
    ]:
        (history / f"data_{stamp}.json").write_text(json.dumps(payload))
    monkeypatch.setattr(draw_dress, "USERDATA_DIR", tmp_path)
    previous = draw_dress._load_previous_dojo_state(123)
    assert previous["version"] == "2026"
    left, right = draw_dress._collect_dojo_change_sections(
        previous, normalize_versioned_dojo_scores(_dojo("2026", score=900000)),
        include_score_refresh=True,
    )
    assert left == []
    assert len(_items(right, "段位内刷新最高分")) == 3


def test_normalization_does_not_lose_explicit_version_or_trust_unknown_version():
    assert normalize_versioned_dojo_scores(_dojo("2026"))["version"] == "2026"
    unknown = normalize_versioned_dojo_scores({"version": "unknown", "scores": []})
    assert unknown["version"] is None
    assert draw_dress._collect_dojo_change_sections({}, unknown) == ([], [])


import pytest

@pytest.fixture(autouse=True)
def grade_catalogs(tmp_path, monkeypatch):
    songs = tmp_path / "songs"
    songs.mkdir()
    for version, titles in [("2026", ["メズマライザー", "only my railgun", "カルメン 組曲一番終曲"]), ("2025", ["Old A", "Old B", "Old C"])]:
        grades = [{}] * 6 + [{"grade": "二段", "songs": [{"title": title, "difficulty": "level4"} for title in titles]}]
        (songs / f"grade_dojo_nijiiro_{version}_simple.json").write_text(json.dumps({"grades": grades}))
    monkeypatch.setattr(draw_dress, "ROOT_DIR", tmp_path)
    from taiko_bot.runtime.player.center import dojo_score
    monkeypatch.setattr(dojo_score, "GRADE_CONFIG_PATH", songs / "grade_dojo_nijiiro_2025_simple.json")
    dojo_score.load_grade_name_map.cache_clear()
    dojo_score.load_grade_order.cache_clear()
    draw_dress._load_dojo_grade_display_map.cache_clear()
    yield
    draw_dress._load_dojo_grade_display_map.cache_clear()
