import datetime
import pytest
from taiko_bot.runtime.player.center import taikob_v2

@pytest.fixture(autouse=True)
def isolated_daily_ability_archive(monkeypatch, tmp_path):
    from taiko_bot.runtime.player.center import daily_ability
    monkeypatch.setattr(daily_ability, "ROOT", tmp_path)
    monkeypatch.setenv("TAIKO_USERDATA_DIR", str(tmp_path))
    from taiko_store import PublicationStore
    for identity in ["123", "999001", "999002", "999003", "999004", "999005", "999006", "u0_qq_official_TEST_OPENID"]:
        with PublicationStore(tmp_path, identity).exclusive() as store:
            store.commit({"current": b"{}"})

SAMPLE_SONGS = [
    {"song_no": 1001, "level": 4, "stage_cnt": 3},
    {"song_no": 1002, "level": 5, "stage_cnt": 5},
    {"song_no": 1003, "level": 5, "stage_cnt": 2},
]

def _mock_rating_pipeline(monkeypatch):
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.score_calculator._compute_results_from_userdata_records",
        lambda records, cfg, const_table, **kwargs: [object()] if records else [],
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.score_calculator.compute_dim_topN_means",
        lambda results, n: {
            "大歌力": 10.0,
            "体力": 9.0,
            "高速处理": 8.0,
            "精度力": 7.0,
            "节奏处理": 6.0,
            "复合处理": 5.0,
        },
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.score_calculator.aggregate_topN_value",
        lambda results, col, n: 11.0,
    )

def test_snapshot_writer_freezes_both_default_model_families(monkeypatch):
    from taiko_bot.runtime.player.center import daily_ability, score_calculator
    _mock_rating_pipeline(monkeypatch)
    monkeypatch.setattr(score_calculator, 'load_rating_config', lambda *_: {'const_table': {'const_to_score': {}}})
    monkeypatch.setattr(score_calculator, 'build_const_table', lambda *_: [])
    monkeypatch.setattr(taikob_v2, 'compute_all_v2_from_userdata_records', lambda *_: [object()])
    monkeypatch.setattr(taikob_v2, 'compute_dim_topN_means_v2', lambda *_: {'精度': 12.0})
    monkeypatch.setattr(taikob_v2, 'aggregate_topN_value_v2', lambda *_: 12.5)
    captured = datetime.datetime(2026, 1, 1, 20)
    daily_ability.capture_snapshot('123', SAMPLE_SONGS, captured)
    monkeypatch.setattr(score_calculator, 'aggregate_topN_value', lambda *_: 99)
    monkeypatch.setattr(taikob_v2, 'aggregate_topN_value_v2', lambda *_: 99)
    daily_ability.capture_snapshot('123', SAMPLE_SONGS, captured)
    with daily_ability.archive('123') as days:
        assert days['2026-01-01']['rating'] == 11.0
    with daily_ability.archive('123', 'v2-top20') as days:
        assert days['2026-01-01']['rating'] == 12.5
