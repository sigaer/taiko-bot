"""Migration preserves legacy evidence and enables canonical u0 reads."""
import hashlib
import json
import os

import pytest

from taiko_bot.cli.adopt_publications import migrate
from taiko_store import merge_reference, merged_materialization
from taiko_store.publication import PublicationError, PublicationStore


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_reference, '_SONG_COMBO_MAP_CACHE', {})
    for identity in ('1001', '1002', 'u0_synthetic'):
        (tmp_path / identity).mkdir()
        payload = {'profile': {'mydon_name': 'Synthetic'}, 'achievement': {}, 'dojo': {},
                   'songs': [{'song_no': 1, 'level': 4, 'high_score': 500000}],
                   '_meta': {'full': True, 'ts': '20261018_010000'}}
        if identity == 'u0_synthetic':
            payload['_meta']['merge_topology'] = ['1001', '1002']
        raw = json.dumps(payload).encode()
        (tmp_path / (identity + 'data.json')).write_bytes(raw)
        (tmp_path / identity / 'data_20261018_010000.json').write_bytes(raw)
        # Even malformed historical evidence must survive, not be repaired.
        (tmp_path / identity / 'data_legacy.json').write_bytes(b'invalid original evidence')
        (tmp_path / identity / 'daily_rating.json').write_bytes(b'frozen daily bytes')
    return tmp_path


def fingerprint(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                     p.stat().st_mtime_ns, p.stat().st_ctime_ns)
            for p in root.glob('**/*') if p.is_file() and '.taiko-publications' not in p.parts}


def test_inspection_is_physically_read_only_and_apply_requires_writer_fence(legacy):
    before = fingerprint(legacy)
    result = migrate(legacy, ['1001', '1002', 'u0_synthetic'])
    assert result['legacy'] == 3 and result['adopted'] == 0
    assert not (legacy / '.taiko-publications').exists()
    with pytest.raises(PublicationError, match='Fence legacy'):
        migrate(legacy, ['1001'], apply=True)
    assert fingerprint(legacy) == before


def test_exact_bytes_times_daily_and_receipts_survive_repeat_migration(legacy):
    original = legacy / '1001' / 'data_legacy.json'
    os.utime(original, (1600000000, 1600000000))
    before = fingerprint(legacy)
    ids = ['1001', '1002', 'u0_synthetic']
    result = migrate(legacy, ids, apply=True, writers_coordinated=True)
    assert result['adopted'] == 3
    store = PublicationStore(legacy, '1001')
    with store.shared():
        first = store.view()['commitId']
        assert store.reader().raw('history/data_legacy.json') == b'invalid original evidence'
        assert store.reader().file_times('history/data_legacy.json')['mtime'] == 1600000000
    assert fingerprint(legacy) == before
    assert migrate(legacy, ids, apply=True, writers_coordinated=True)['adopted'] == 0
    with store.shared():
        assert store.view()['commitId'] == first


def test_legacy_u0_fails_before_migration_then_retains_history_during_incremental_refresh(legacy, monkeypatch):
    args = (legacy, 'onebot_v11:123', ['1001', '1002'], '1002', 'u0_synthetic')
    with pytest.raises(PublicationError, match='no publication'):
        merged_materialization.materialize(*args)
    migrate(legacy, ['1001', '1002'], apply=True, writers_coordinated=True)
    with pytest.raises(PublicationError, match='must be adopted'):
        merged_materialization.materialize(*args)
    migrate(legacy, ['u0_synthetic'], apply=True, writers_coordinated=True)
    def no_rebuild(*args, **kwargs):
        pytest.fail('Existing u0 history was rebuilt')
    monkeypatch.setattr(merged_materialization, 'derive_merged_read', no_rebuild)
    merged_materialization.materialize(*args)
    store = PublicationStore(legacy, 'u0_synthetic')
    with store.shared():
        assert store.reader().raw('history/data_legacy.json') == b'invalid original evidence'
        assert store.view()['dependencyHash']


def test_missing_current_is_reported_without_creating_empty_publication(legacy):
    (legacy / '1001data.json').unlink()
    result = migrate(legacy, ['1001'], apply=True, writers_coordinated=True)
    assert result['missing_current'] == 1 and result['adopted'] == 0
    assert not (legacy / '.taiko-publications').exists()


def test_all_inputs_preflight_before_mutation_and_symlinks_fail_closed(legacy):
    (legacy / '1002' / 'data_link.json').symlink_to(legacy / '1001data.json')
    with pytest.raises(PublicationError):
        migrate(legacy, ['1001', '1002'], apply=True, writers_coordinated=True)
    assert not (legacy / '.taiko-publications').exists()


def test_interrupted_adoption_is_retryable_without_rewriting_legacy(legacy, monkeypatch):
    before = fingerprint(legacy)
    original = PublicationStore._put_stream
    calls = 0
    def fail(store, source):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('synthetic disk failure')
        return original(store, source)
    monkeypatch.setattr(PublicationStore, '_put_stream', fail)
    with pytest.raises(OSError):
        migrate(legacy, ['1001'], apply=True, writers_coordinated=True)
    assert not (legacy / '.taiko-publications/1001/committed.json').exists()
    monkeypatch.setattr(PublicationStore, '_put_stream', original)
    assert migrate(legacy, ['1001'], apply=True, writers_coordinated=True)['adopted'] == 1
    assert fingerprint(legacy) == before


def test_managed_corruption_never_readopts_compatible_projection(legacy):
    migrate(legacy, ['1001'], apply=True, writers_coordinated=True)
    store = PublicationStore(legacy, '1001')
    with store.exclusive():
        head = store.view()
        (store.objects / head['files']['current']['sha256']).unlink()
    with pytest.raises(OSError):
        migrate(legacy, ['1001'], apply=True, writers_coordinated=True)
    with store.shared():
        assert store.view()['commitId'] == head['commitId']
