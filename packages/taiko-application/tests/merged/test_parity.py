"""Frozen 38826aa oracle, synthetic payloads only; installed-wheel compatible."""
import builtins
import copy
import hashlib
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
from taiko_application import merged_bind as new

STAMP = datetime(2025, 1, 2, 3, 4, 5)
COMBOS = {(7, 4): 100}

@pytest.fixture
def old(monkeypatch):
    name = 'frozen_u0'
    package = types.ModuleType(name)
    package.__path__ = []
    snapshot = types.ModuleType(name + '.snapshot_history')
    snapshot.list_snapshot_files = snapshot.parse_snapshot_time = lambda *a: pytest.fail('oracle performed IO')
    module = types.ModuleType(name + '.merged_bind')
    module.__package__ = name
    module.__file__ = str(Path(__file__).resolve())
    for item in (package, snapshot, module):
        monkeypatch.setitem(sys.modules, item.__name__, item)
    text = Path(__file__).with_name('frozen_merged_bind.py.txt').read_text()
    assert hashlib.sha256(text.encode()).hexdigest() == '4e9948d7eb697335688d81ed6c663f684ba42bbb47f8e04d5c33470f6115e4df'
    exec(compile(text, '<frozen-38826aa>', 'exec'), module.__dict__)
    class Clock(datetime):
        @classmethod
        def now(cls):
            return STAMP
    module.datetime = Clock
    module._SONG_COMBO_MAP_CACHE = COMBOS
    return module


def row(**kw):
    return {'song_no': 7, 'level': 4, 'stage_cnt': 2, 'good_cnt': 90,
            'ok_cnt': 10, 'high_score': 800000, 'best_score_rank': 7,
            'update_datetime': '2025-01-01 00:00:00', **kw}


CASES = [[], [row()], [row(), row()], [None, {}, row(song_no='bad')],
         [row(), row(dondaful_combo_cnt=1)], [row(), row(good_cnt=99)],
         [row(), row(full_combo_cnt=1)], [row(), row(high_score=999999)],
         [row(), row(best_score_rank=8)], [row(), row(update_datetime='2025-02-01 00:00:00')],
         [row(extra='first'), row(extra='second')], [row(stage_cnt='3'), row(stage_cnt=-2)],
         [row(song_no=9), row(song_no='7'), row(level=1)],
         [row(good_cnt='bad', ng_cnt=None)], [row(dondaful_combo_cnt=1, full_combo_cnt=0)]]

@pytest.mark.parametrize('rows', CASES)
@pytest.mark.parametrize('reverse', [False, True])
def test_payload(old, rows, reverse, monkeypatch):
    payloads = [{'profile': {'name': 'A', 'nested': [1]}, 'dojo': {'dan': 4}, 'songs': rows},
                {'profile': {'name': 'B'}, 'songs': [row(extra='B')]}]
    if reverse:
        payloads.reverse()
    saved = copy.deepcopy(payloads)
    expected = old._merge_payloads(payloads, profile_source=payloads[1], merge_topology=['222', '111', '222'])
    # Actual kernel execution must perform no file IO, including swallowed IO.
    attempts = []
    def forbidden(*a, **k):
        attempts.append(True)
        raise AssertionError('kernel IO')
    with monkeypatch.context() as m:
        m.setattr(builtins, 'open', forbidden)
        m.setattr(Path, 'open', forbidden)
        actual = new._merge_payloads(payloads, profile_source=payloads[1],
            merge_topology=['222', '111', '222'], combo_map=COMBOS, clock=lambda: STAMP)
    assert not attempts
    assert actual == expected
    assert payloads == saved
    actual['profile']['changed'] = True
    assert payloads == saved

@pytest.mark.parametrize('histories', [{}, {'111': []},
    {'111': [(STAMP, {'songs': [row()], 'profile': {'name': 'A'}})]},
    {'111': [(STAMP, {'songs': [row()]})], '222': [(STAMP, {'songs': [row(extra='B')], 'profile': {'name': 'B'}})]}])
@pytest.mark.parametrize('ids', [['111','222'], ['222','111']])
@pytest.mark.parametrize('profile', ['111','222'])
def test_history(old, histories, ids, profile):
    fallback = {'profile': {'name': 'fallback'}, 'songs': [row(update_datetime='invalid')]}
    args = dict(profile_source_id=profile, fallback_profile=fallback)
    assert new._merge_snapshot_histories(ids, histories, **args, combo_map=COMBOS, clock=lambda: STAMP) == old._merge_snapshot_histories(ids, histories, **args)

@pytest.mark.parametrize('identity', ['onebot_v11:123', 'qq_official:'+'a'*128, '', None, '../bad', 'qq_official:'])
def test_identity(old, identity):
    try:
        expected = old.build_virtual_user_id(identity)
    except old.MergedBindError as exc:
        with pytest.raises(new.MergedBindError) as actual:
            new.build_virtual_user_id(identity)
        assert str(actual.value) == str(exc)
    else:
        assert new.build_virtual_user_id(identity) == expected

@pytest.mark.parametrize('missing', [[], [(1,'111')], [(2,'222'),(1,'111')]])
def test_missing(old, missing):
    before = old.MergedBindMissingUserdataError(old.MissingBindUserdata(*x) for x in missing)
    after = new.MergedBindMissingUserdataError(new.MissingBindUserdata(*x) for x in missing)
    assert str(before) == str(after)
    assert [(x.slot,x.taiko_id) for x in before.missing] == [(x.slot,x.taiko_id) for x in after.missing]

@pytest.mark.parametrize('bad', [None, 1, {'songs': 1}, {'songs': [row(stage_cnt={})]}])
def test_errors(old, bad):
    def outcome(fn):
        try:
            return ('ok', fn())
        except Exception as e:
            return (type(e).__name__, str(e))
    assert outcome(lambda: old._merge_payloads([bad], profile_source=bad)) == outcome(lambda: new._merge_payloads([bad], profile_source=bad, combo_map=COMBOS, clock=lambda: STAMP))
