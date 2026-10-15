import json

import pytest

from taiko_bot.runtime.player.center.score_rating_target import (
    compute_song_rating_target,
)
from taiko_bot.runtime.player.center.score_data import parse_scoreline_request


def _rating_config(tmp_path):
    path = tmp_path / "rating.json"
    path.write_text(
        json.dumps(
            {
                "songs": {},
                "const_table": {"const_to_score": {"10.0": 12.0}},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_parse_scoreline_target_rating_with_inner_difficulty():
    request = parse_scoreline_request("分数线 里夏祭り 13.2")
    assert request.song_query == "夏祭り"
    assert request.level == 5
    assert request.mode == "rating"
    assert request.target_rating == pytest.approx(13.2)


def test_parse_scoreline_evaluation_treats_number_as_roll_speed():
    request = parse_scoreline_request("分数线 极 里夏祭り 25")
    assert request.song_query == "夏祭り"
    assert request.level == 5
    assert request.mode == "evaluation"
    assert request.rating_display == "极"
    assert request.speed_ips == 25
    assert request.target_rating is None


@pytest.mark.parametrize(
    "command",
    ["分数线 极 里夏祭り", "分数线 里夏祭り 极"],
)
def test_parse_scoreline_evaluation_defaults_roll_speed_to_30(command):
    request = parse_scoreline_request(command)
    assert request.song_query == "夏祭り"
    assert request.level == 5
    assert request.mode == "evaluation"
    assert request.rating_display == "极"
    assert request.speed_ips == 30
    assert request.target_rating is None


@pytest.mark.parametrize(
    "prefix,level,label",
    [
        ("梅", 1, "梅谱"),
        ("简单", 1, "梅谱"),
        ("竹", 2, "竹谱"),
        ("普通", 2, "竹谱"),
        ("松", 3, "松谱"),
        ("困难", 3, "松谱"),
    ],
)
def test_parse_scoreline_supports_low_difficulties(prefix, level, label):
    request = parse_scoreline_request(f"分数线 极 {prefix}夏祭り 25")

    assert request.song_query == "夏祭り"
    assert request.level == level
    assert request.level_label == label
    assert request.speed_ips == 25


def test_compute_song_rating_target_returns_discrete_good_and_ok(tmp_path):
    path = _rating_config(tmp_path)
    song = {"combo": 1000, "score": 10.0}
    result = compute_song_rating_target(song, 11.5, rating_path=path)
    assert result.reachable
    assert result.good_count + result.ok_count == 1000
    assert result.achieved_rating >= 11.5

    if result.ok_count < result.note_count:
        harder_result = compute_song_rating_target(
            song, result.achieved_rating + 1e-6, rating_path=path
        )
        assert harder_result.ok_count <= result.ok_count


def test_compute_song_rating_target_reports_unreachable(tmp_path):
    result = compute_song_rating_target(
        {"combo": 500, "score": 10.0}, 20.0, rating_path=_rating_config(tmp_path)
    )
    assert not result.reachable
    assert result.good_count == 500
    assert result.ok_count == 0
