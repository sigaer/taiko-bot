"""Retained history does not disable a bounded incremental u0 current update."""
import json

import pytest
from taiko_store import merged_materialization as merged
from taiko_store import merged_read, merge_reference
from taiko_store.publication import PublicationStore, PublicationError


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(merged, 'MAX_BYTES', 8192)
    monkeypatch.setattr(merged_read, 'MAX_BYTES', 8192)
    monkeypatch.setattr(merge_reference, '_SONG_COMBO_MAP_CACHE', {})
    for identity in ['1001', '1002']:
        store = PublicationStore(tmp_path, identity)
        with store.exclusive():
            payload = json.dumps({'profile': {'mydon_name': 'Synthetic'}, 'achievement': {}, 'dojo': {},
                'songs': [{'song_no': int(identity), 'level': 4, 'high_score': 500000}],
                '_meta': {'full': True, 'ts': '20261018_010000'}}).encode()
            ref = store.stage(payload)
            store.publish({'current': ref, 'history/data_20261018_010000.json': ref})
    return tmp_path


def add_history(root, *, changed=False):
    store = PublicationStore(root, '1001')
    with store.exclusive():
        payload = json.loads(store.reader().current_raw())
        changes = {}
        for index in range(45):
            snapshot = {**payload, 'syntheticPadding': 'x' * 128, 'observation': index}
            changes[f'history/data_20261018_02{index:02d}00.json'] = store.stage(json.dumps(snapshot).encode())
        if changed:
            payload['songs'][0]['high_score'] = 777777
            changes['current'] = store.stage(json.dumps(payload).encode())
        store.publish(changes)
        assert sum(x['bytes'] for key, x in store.view()['files'].items() if key.startswith('history/')) > merged.MAX_BYTES


@pytest.mark.parametrize('changed', [False, True])
def test_incremental_and_hot_u0_survive_retained_history_exceeding_current_limit(sources, monkeypatch, changed):
    merged.materialize(sources, 'onebot_v11:123', ['1001', '1002'], '1002', 'u0_synthetic')
    add_history(sources, changed=changed)
    def no_cold_rebuild(*args, **kwargs):
        pytest.fail('Incremental materialization re-read retained history')
    monkeypatch.setattr(merged, 'derive_merged_read', no_cold_rebuild)
    result = merged.materialize(sources, 'onebot_v11:123', ['1001', '1002'], '1002', 'u0_synthetic')
    store = PublicationStore(sources, result.virtual_user_id)
    with store.shared():
        current = json.loads(store.reader().current_raw())
        assert len(current['songs']) == 2
        score = next(s for s in current['songs'] if s['song_no'] == 1001)['high_score']
        assert score == (777777 if changed else 500000)


def test_cold_history_rebuild_keeps_the_existing_aggregate_limit(sources):
    add_history(sources)
    with pytest.raises(PublicationError, match='Merged input limit exceeded'):
        merged.materialize(sources, 'onebot_v11:123', ['1001', '1002'], '1002', 'u0_cold')
    store = PublicationStore(sources, 'u0_cold')
    with store.shared():
        assert store.view() is None
