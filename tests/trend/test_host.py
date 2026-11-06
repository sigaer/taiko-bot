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


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('has_current', [False, True])
def test_history_registers_and_persists_without_changing_scores(tmp_path, monkeypatch, existing, has_current):
    import json
    from taiko_bot.runtime.player.center.b30_daily import store_measurement
    from taiko_bot.runtime.player.center.source_registration import ensure_registered
    identity = '123'
    folder = tmp_path / identity
    folder.mkdir()
    payload = {'_meta': {'full': True}, 'songs': [{}]}
    history = folder / 'data_20250102_200000_000000.json'
    history.write_text(json.dumps(payload))
    current = tmp_path / '123data.json'
    if has_current:
        current.write_text(json.dumps(payload))
    daily = folder / 'daily-ability-v1-top20.json'
    days = {}
    if existing:
        store_measurement(days, datetime(2025, 1, 1, 20), {'精度力': 7}, 7, 1)
        daily.write_text(json.dumps({'version': 1, 'namespace': 'v1-top20', 'days': days}))
    original_history = history.read_text()
    monkeypatch.setattr(b30_history, 'load_rating_config', lambda _: {'const_table': {'const_to_score': {}}})
    monkeypatch.setattr(b30_history, 'build_const_table', lambda _: [])
    monkeypatch.setattr(b30_history, '_compute_results_from_userdata_records', lambda *a, **k: [object()])
    monkeypatch.setattr(b30_history, 'compute_dim_topN_means', lambda *a: {'精度力': 10})
    monkeypatch.setattr(b30_history, 'aggregate_topN_value', lambda *a: 10)
    store = PublicationStore(tmp_path, identity)
    checks = []
    def verify():
        checks.append(True)
        with pytest.raises(PublicationError):
            with PublicationStore(tmp_path, identity, lock_timeout=.01).exclusive():
                pytest.fail('registration did not hold EX')
    ensure_registered(store, verify)
    provider = SimpleNamespace(verify_initial=lambda: None)
    with store.shared():
        first = store.view()['commitId']
        trend_history.capture(provider, store.reader(), store,
                              (False, 'v1', {'N': 20, 'max_days': 30}, ''))
    ensure_registered(store, verify)
    assert checks == [True]
    with store.shared():
        assert store.view()['commitId'] == first
    assert provider.trend_points[0] == 'ok'
    assert [row[2] for row in provider.trend_points[1]] == ([7, 10] if existing else [10])
    saved = json.loads(daily.read_text())['days']
    assert saved['2025-01-02']['rating'] == 10
    if existing:
        assert saved['2025-01-01'] == days['2025-01-01']
    assert history.read_text() == original_history
    if has_current:
        assert current.read_text() == original_history


@pytest.mark.parametrize('state', ['empty', 'deleted', 'corrupt', 'revoked'])
def test_registration_respects_absence_deletion_corruption_and_authorization(tmp_path, state):
    from taiko_bot.runtime.player.center.source_registration import ensure_registered
    from taiko_bot.runtime.player.authority import TinfoDenied
    store = PublicationStore(tmp_path, '123')
    if state in ('deleted', 'corrupt'):
        with store.exclusive():
            store.commit({})
        # Stale compatibility files must not resurrect deleted data.
        (tmp_path / '123data.json').write_text('{}')
        if state == 'corrupt':
            (store.base / 'committed.json').write_text('{}')
    elif state == 'revoked':
        (tmp_path / '123data.json').write_text('{}')
    def verify():
        if state == 'revoked':
            raise TinfoDenied()
    if state in ('corrupt', 'revoked'):
        with pytest.raises(PublicationError if state == 'corrupt' else TinfoDenied):
            ensure_registered(store, verify)
    else:
        ensure_registered(store, verify)
        with store.shared():
            assert store.view() is None if state == 'empty' else store.view()['files'] == {}
    if state in ('empty', 'revoked'):
        assert not (store.base / 'committed.json').exists()


@pytest.mark.parametrize('revoked', [False, True])
def test_storage_failure_gets_safe_reply_after_authorization_check(monkeypatch, revoked):
    import ast
    import asyncio
    from pathlib import Path
    from taiko_bot.runtime.player.authority import TinfoDenied, TinfoUnavailable
    # Execute the actual handler with its host ports replaced; no platform sends.
    source = Path(b30_history.__file__).resolve().parents[1] / 'trend.py'
    tree = ast.parse(source.read_text())
    handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'handle')
    replies, checks = [], []
    def prepare_trend(*args):
        raise PublicationError('private/path must not appear in reply')
    def verify():
        checks.append(True)
        if revoked:
            raise TinfoDenied()
    async def reply(matcher, event, message):
        replies.append(message)
    provider = SimpleNamespace(prepare_trend=prepare_trend, verify_initial=verify)
    helpers = SimpleNamespace(extract_plain_text=lambda e: 'taikotrend',
        _normalize_identity_key=lambda x: x, get_identity_key=lambda **k: 'actor',
        _resolve_requested_identity_key=lambda e: ('actor', None), _finish_text_reply=reply)
    entry = SimpleNamespace(helpers=helpers, create_provider=lambda: provider,
        TinfoDenied=TinfoDenied, TinfoUnavailable=TinfoUnavailable,
        MergedBindError=type('MergedBindError', (Exception,), {}),
        AuthorizedDelivery=lambda m, p, v: m)
    scope = {'__package__': 'taiko_bot.runtime.player', 'entry': entry,
             'PROFILE': 'center', 'PublicationError': PublicationError, 'prepare': lambda *a: ()}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), scope)
    asyncio.run(scope['handle'](object(), object(), False))
    assert checks == [True]
    assert replies == ['查不到呢，可能不给看哦~' if revoked else '历史成绩暂时无法读取，请稍后重试。']


def test_provider_registers_real_account_before_trend_capture(tmp_path, monkeypatch):
    from taiko_bot.runtime.player.center.tinfo_provider import TinfoHostProvider
    entry = {'current_slot': 1, 'current_index': 0, 'ids': ['123'], 'sources': {'123': 'wahlap'}}
    provider = TinfoHostProvider(connection_factory=lambda: pytest.fail('unexpected SQL'), userdata_root=tmp_path)
    monkeypatch.setattr(provider, '_snapshot', lambda *args: ([], entry, 'binding-observation'))
    (tmp_path / '123data.json').write_text('{"songs": []}')
    def capture(p, view, store, command):
        assert view.publication is not None
        p.trend_points = ('no_snapshot', [])
        return ()
    monkeypatch.setattr(trend_history, 'capture', capture)
    private = provider.prepare_trend('onebot_v11:1', 'onebot_v11:1', (False, 'v1', {'N': 20, 'max_days': 30}, ''))
    assert private.authorized_target.user_id == '123'
    assert (tmp_path / '.taiko-publications/123/committed.json').exists()


def test_provider_registers_all_merged_members_and_existing_output(tmp_path, monkeypatch):
    from taiko_bot.runtime.player.center import tinfo_provider
    from taiko_bot.runtime.player.center.materialization import build_virtual_user_id
    principal = 'onebot_v11:1'
    virtual = build_virtual_user_id(principal)
    entry = {'current_slot': 0, 'current_index': 0, 'ids': ['123', '456'],
             'sources': {'123': 'wahlap', '456': 'wahlap'}}
    provider = tinfo_provider.TinfoHostProvider(connection_factory=lambda: pytest.fail('unexpected SQL'), userdata_root=tmp_path)
    monkeypatch.setattr(provider, '_snapshot', lambda *args: ([], entry, 'binding-observation'))
    for identity in ['123', '456', virtual]:
        (tmp_path / (identity + 'data.json')).write_text('{"songs": []}')
    class ReachedMaterialization(Exception):
        pass
    def materialize(*args, **kwargs):
        for identity in ['123', '456', virtual]:
            assert (tmp_path / '.taiko-publications' / identity / 'committed.json').exists()
        raise ReachedMaterialization()
    monkeypatch.setattr(tinfo_provider, 'materialize_merged_bind_userdata', materialize)
    with pytest.raises(ReachedMaterialization):
        provider.prepare_trend(principal, principal, (False, 'v1', {'N': 20, 'max_days': 30}, ''))


def test_registration_keeps_writer_commit_between_probe_and_exclusive(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from taiko_bot.runtime.player.center.source_registration import ensure_registered
    store = PublicationStore(tmp_path, '123')
    (tmp_path / '123data.json').write_text('{"old": true}')
    original = store.exclusive
    @contextmanager
    def writer_wins():
        with original():
            store.commit({'current': b'{"new": true}'})
            yield store
    monkeypatch.setattr(store, 'exclusive', writer_wins)
    ensure_registered(store, lambda: None)
    with store.shared():
        assert store.reader().current_raw() == b'{"new": true}'
