"""Explicit revision differences; the frozen exact-equivalence test stays unchanged."""
import hashlib
import json
from datetime import datetime

from test_frozen import old


def test_revision_changes_only_declared_identity_and_preserves_old_objects(old, tmp_path, monkeypatch):
    import test_version_summary as fixture
    from taiko_bot.offline.annual_summary import service, cache

    userdata = tmp_path / 'userdata'
    fixture._write_json(tmp_path / 'songs.json', fixture._song_data())
    fixture._write_json(tmp_path / 'rating.json', fixture._rating_data())
    for day, stage in ((1, 1), (3, 4)):
        fixture._snapshot(userdata, 'synthetic', f'2026010{day}_000000_000000', fixture._payload('wahlap', [fixture._song(i, stage=stage, updated_at=f'2026-01-0{day} 00:00:00') for i in range(1, 13)]))
    args = dict(userdata_dir=userdata, song_data_path=tmp_path / 'songs.json', rating_path=tmp_path / 'rating.json', generated_at=datetime(2026, 1, 31))
    monkeypatch.setenv('TAIKO_ANNUAL_CACHE_DIR', str(tmp_path / 'cache'))
    frozen = old('annual_summary.service')
    expected = frozen.build_annual_result('synthetic', fixture.TEST_VERSION, **args)
    saved = tmp_path / (expected['summary']['summaryId'] + '.json')
    saved.write_text(json.dumps(expected, sort_keys=True))
    originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.rglob('*.json')}
    old_objects = set((tmp_path / 'cache' / 'normalized').glob('*/*.json'))
    assert old_objects

    def differences(a, b, path=()):
        if isinstance(a, dict) and isinstance(b, dict):
            assert a.keys() == b.keys()
            return set().union(*(differences(a[k], b[k], path + (k,)) for k in a))
        if isinstance(a, list) and isinstance(b, list):
            assert len(a) == len(b)
            return set().union(*(differences(x, y, path + (str(i),)) for i, (x, y) in enumerate(zip(a, b))))
        return {path} if a != b else set()

    for _ in range(2):
        actual = service.build_annual_result('synthetic', fixture.TEST_VERSION, **args)
        assert differences(expected, actual) == {
            ('summary', 'summaryId'), ('summary', 'poster', 'summaryId'),
            ('summary', 'provenance', 'algorithmVersion'),
            ('summary', 'provenance', 'inputFingerprint'),
        }
        assert actual['summary']['provenance']['algorithmVersion'] == 'annual-observation-v4.5.4'
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in originals.items())
    new_objects = set((tmp_path / 'cache' / 'normalized').glob('*/*.json')) - old_objects
    assert new_objects
    assert all(json.loads(path.read_text())['cacheVersion'] == cache.NORMALIZED_CACHE_VERSION for path in new_objects)
