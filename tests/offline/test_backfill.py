import json
import pytest
from taiko_store import PublicationStore, PublicationError
from taiko_bot.runtime.player.center import daily_ability as daily
IDENTITY="123"

@pytest.fixture

def source(tmp_path):
    store = PublicationStore(tmp_path, IDENTITY)
    with store.exclusive():
        store.commit({"current": b"{}"})
    return store

def test_backfill_uses_canonical_history_after_projection_loss(source, monkeypatch):
    backfill = load_backfill()
    with source.exclusive():
        source.commit({"history/data_20250101_200000_000000.json": json.dumps({"_meta": {"full": True},
            "songs": [{"song_no": 1, "level": 4, "value": 7}]}).encode()})
    directory = source.root / IDENTITY
    next(directory.glob("data_*.json")).unlink()
    monkeypatch.setattr(backfill.score, "load_rating_config", lambda *_: {"const_table": {"const_to_score": {}}})
    monkeypatch.setattr(backfill.score, "build_const_table", lambda *_: [])
    monkeypatch.setattr(backfill.score, "_compute_results_from_userdata_records", lambda rows, *a, **k: rows)
    monkeypatch.setattr(backfill.score, "compute_dim_topN_means", lambda rows, n: {"精度力": rows[0]["value"]})
    monkeypatch.setattr(backfill.score, "aggregate_topN_value", lambda rows, *a: rows[0]["value"])
    result = backfill.backfill(IDENTITY, userdata_dir=source.root)
    assert result == {"daysBefore": 0, "daysAfter": 1, "filesRead": 1}
    assert json.loads(daily.archive_path(IDENTITY, userdata_dir=source.root).read_bytes())["days"]["2025-01-01"]["rating"] == 7

def test_backfill_seed_cap_and_unmanaged_source_fail_closed(tmp_path, monkeypatch):
    backfill = load_backfill()
    seed = tmp_path / "seed.json"
    seed.write_text("[{}]")
    monkeypatch.setattr(backfill, "MAX_SEED_BYTES", 2)
    with pytest.raises(ValueError):
        backfill.read_seed(seed)
    with pytest.raises(PublicationError):
        backfill.backfill(IDENTITY, userdata_dir=tmp_path)

def load_backfill():
    from taiko_bot.cli import backfill_daily_ability
    return backfill_daily_ability


def test_legacy_merge_adapter_uses_owned_writer_and_keeps_errors(tmp_path,monkeypatch):
    from taiko_bot.offline import merged_bind
    from taiko_store import merged_materialization
    calls=[]
    def materialize(*args):calls.append(args);return 'synthetic-publication'
    monkeypatch.setattr(merged_materialization,'materialize',materialize)
    entry={'ids':['111','222'],'current_index':1}
    assert merged_bind.materialize_merged_bind_userdata('onebot_v11:7',entry,userdata_dir=tmp_path)=='synthetic-publication'
    assert calls[0][0:4]==(tmp_path,'onebot_v11:7',['111','222'],'222')
    with pytest.raises(merged_bind.MergedBindError):
        merged_bind.materialize_merged_bind_userdata('onebot_v11:7',{'ids':['111','111']},userdata_dir=tmp_path)
    assert len(calls)==1

@pytest.mark.parametrize('name',['growth_compute','recommendation_intelligence'])
def test_installed_console_preserves_publication_unavailable_exit(name,monkeypatch,capsys):
    import importlib
    module=importlib.import_module('taiko_bot.offline.'+name)
    def unavailable():raise PublicationError('synthetic')
    monkeypatch.setattr(module,'main',unavailable)
    assert module.entrypoint()==75
    assert capsys.readouterr().err=='Score publication is unavailable\n'
