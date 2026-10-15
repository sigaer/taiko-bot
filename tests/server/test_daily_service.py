"""Daily capture through the migrated adapter, actual publication/file commits."""
from datetime import datetime
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch
from taiko_store import PublicationStore
from taiko_bot.runtime.player.center import daily_ability as daily


def test_daily_capture_v1_v2_same_observation_and_historical_freeze(tmp_path, monkeypatch):
    from taiko_bot.runtime.player.center import score_calculator as score, taikob_v2 as v2
    monkeypatch.setattr(score, "load_rating_config", lambda _: {"const_table":{"const_to_score":{}}})
    monkeypatch.setattr(score, "build_const_table", lambda _: {})
    monkeypatch.setattr(score, "_compute_results_from_userdata_records", lambda *a, **kw: [SimpleNamespace()])
    monkeypatch.setattr(score, "compute_dim_topN_means", lambda *a: {"精度力":1})
    monkeypatch.setattr(score, "aggregate_topN_value", lambda *a: 1)
    monkeypatch.setattr(v2, "compute_all_v2_from_userdata_records", lambda *a: [SimpleNamespace()])
    monkeypatch.setattr(v2, "compute_dim_topN_means_v2", lambda *a: {"精度力":2})
    monkeypatch.setattr(v2, "aggregate_topN_value_v2", lambda *a: 2)
    store=PublicationStore(tmp_path,"123")
    with store.exclusive():
        store.commit({"current":b'{"songs":[]}'})
        daily.capture_snapshot("123",[],datetime(2025,1,1,12),userdata_dir=tmp_path,publication_store=store)
        paths=[daily.archive_path("123",ns,userdata_dir=tmp_path) for ns in ("v1-top20","v2-top20")]
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        daily.capture_snapshot("123",[],datetime(2025,1,1,13),userdata_dir=tmp_path,publication_store=store)
        assert before==[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        for ns,rating in [("v1-top20",1),("v2-top20",2)]:
            with daily.archive("123",ns,userdata_dir=tmp_path,publication_store=store,writable=False) as days:
                assert days["2025-01-01"]["rating"]==rating
                assert days["2025-01-01"]["capturedAt"]=="2025-01-01T12:00:00+08:00"
