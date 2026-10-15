"""Trend ownership checks moved from the legacy daily consumer tests."""
from datetime import datetime
from types import SimpleNamespace
import pytest
from taiko_store import PublicationStore, PublicationError
from taiko_bot.runtime.player.center import trend_history, b30_history


def test_history_and_measurement_share_source_lease(tmp_path, monkeypatch):
    store = PublicationStore(tmp_path, '123')
    with store.exclusive():
        store.commit({'current': b'{}'})
    def inputs(view):
        with pytest.raises(PublicationError):
            with PublicationStore(tmp_path, '123', lock_timeout=.02).exclusive():
                pytest.fail('history captured outside Source SH')
        return [(datetime(2025,1,1,20), {'_meta': {'full': True}, 'songs': [{}]})]
    monkeypatch.setattr(trend_history, '_history_snapshot_inputs', inputs)
    monkeypatch.setattr(b30_history,'load_rating_config', lambda _: {'const_table': {'const_to_score': {}}})
    monkeypatch.setattr(b30_history,'build_const_table', lambda _: [])
    monkeypatch.setattr(b30_history,'_compute_results_from_userdata_records',lambda *a,**k: [object()])
    monkeypatch.setattr(b30_history,'compute_dim_topN_means',lambda *a: {'精度力': 10})
    monkeypatch.setattr(b30_history,'aggregate_topN_value',lambda *a: 10)
    provider=SimpleNamespace(verify_initial=lambda: None)
    with store.shared():
        trend_history.capture(provider,store.reader(),store,(False,'v1',{'N':20,'max_days':30},''))
    first=provider.trend_points
    assert first[0]=='ok' and first[1][0][2]==10
    def no_recompute(*a,**k):pytest.fail('Historical measurement recomputed')
    monkeypatch.setattr(b30_history,'_compute_results_from_userdata_records',no_recompute)
    for retained in (True,False):
        if not retained:monkeypatch.setattr(trend_history,'_history_snapshot_inputs',lambda _: [])
        with store.shared():
            trend_history.capture(provider,store.reader(),store,(False,'v1',{'N':20,'max_days':30},''))
        assert provider.trend_points==first
    with store.exclusive():pass
