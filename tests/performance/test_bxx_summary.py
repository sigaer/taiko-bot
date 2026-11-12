"""Synthetic update/read integration, with all history access forbidden."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from taiko_bot.runtime.player import bxx_summary as summary
from taiko_bot.runtime.player.center import daily_ability as daily
from taiko_bot.runtime.player.center import b30_history, taikob_v2, score_calculator
from taiko_store import PublicationStore
from taiko_store.reader import ScoreReadView


@pytest.fixture(autouse=True)
def no_upstream_refresh(monkeypatch):
    from taiko_bot.runtime.player.center import taikob_v2_data
    monkeypatch.setattr(taikob_v2_data, '_start_background_refresh_locked', lambda now: None)


def legacy_row(stamp, value):
    return {'capturedAt': stamp, 'rating': value,
            'dimensions': {name: value for name in summary.DIMENSIONS}, 'sampleCount': 1}


def numeric_model(value, song=1):
    return {'columns': {column: [value] for column in summary.COLUMNS},
            'top20': {column: value for column in summary.COLUMNS}, 'top': [[song, 4, value]]}


def test_existing_v2_daily_values_are_used_without_new_models():
    days = {'2026-11-01': legacy_row('2026-11-01T12:00:00+08:00', 9)}
    prepared = summary.comparison(days, records=[], version='v2', count=20,
                                  captured='2026-11-12T13:00:00+08:00')
    assert prepared['baseline']['rating'] == 9 and prepared['previous'] is None
    assert summary.growth({'体力': 10}, 11, prepared) == {'体力': 1, '综合Rating': 2}
    assert summary.comparison(days, records=[], version='v1', count=20,
                              captured='2026-11-12T13:00:00+08:00')['baseline'] is None
    assert summary.comparison(days, records=[], version='v2', count=30,
                              captured='2026-11-12T13:00:00+08:00')['baseline'] is None


def test_same_day_previous_and_first_are_retained_separately():
    days = {}
    for hour, value, song in [(10, 9, 1), (11, 10, 2), (12, 11, 3)]:
        captured = summary.timestamp(f'2026-11-12T{hour}:00:00+08:00')
        previous = summary.latest(days, captured)
        first = days.get('2026-11-12', {}).get('bxx', {}).get('first')
        row = legacy_row(captured.isoformat(), value)
        days['2026-11-12'] = row
        summary.attach(days, row, previous=previous, first=first,
                       records=[song], model=numeric_model(value, song))
    prepared = summary.comparison(days, records=[3], version='v2', count=20,
                                  captured='2026-11-12T13:00:00+08:00')
    assert prepared['baseline']['rating'] == 9
    assert prepared['previous']['rating'] == 10
    assert prepared['previous']['top'] == [[2, 4, 10]]
    assert 'previous' not in days['2026-11-12']['bxx']['previous']


def test_detail_retention_preserves_long_term_daily_numbers():
    days = {}
    for offset in range(100):
        captured = summary.timestamp(datetime(2026, 1, 1) + timedelta(days=offset))
        previous = summary.latest(days, captured)
        row = legacy_row(captured.isoformat(), 10)
        days[captured.date().isoformat()] = row
        summary.attach(days, row, previous=previous, first=None, records=[], model=numeric_model(10))
    assert len(days) == 100
    assert sum('bxx' in row for row in days.values()) == 30
    assert days['2026-01-01']['rating'] == 10
    assert len(json.dumps(days).encode()) < summary.MAX_BYTES


def test_context_and_current_score_digest_prevent_stale_previous():
    row = legacy_row('2026-11-12T12:00:00+08:00', 10)
    old = legacy_row('2026-11-12T11:00:00+08:00', 9)
    days = {'2026-11-12': row}
    summary.attach(days, row, previous=old, first=None, records=[1], model=numeric_model(10), context='members-a')
    wrong = summary.comparison(days, records=[1], version='v2', count=20,
                               captured='2026-11-12T13:00:00+08:00', context='members-b')
    assert wrong == {'previous': None, 'baseline': None}
    stale = summary.comparison(days, records=[2], version='v2', count=20,
                               captured='2026-11-12T13:00:00+08:00', context='members-a')
    assert stale['previous'] is None
    wrong_source = summary.comparison(days, records=[1], version='v2', count=20,
        captured='2026-11-12T13:00:00+08:00', context='members-a', source_ref='another-publication')
    assert wrong_source['previous'] is None


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_all_supported_n_match_full_calculation(version):
    from taiko_bot.runtime.player.center.bxx_capture import model
    records = json.loads(Path('fixtures/U08.json').read_text())['current']['songs']
    if version == 'v1':
        from taiko_bot.runtime.player.center.b30_support import score_calculator as score
        results = score.compute_all_from_userdata_records(records, collapse_duplicate_versions=True)
        aggregate, dimensions = score.aggregate_topN_value, score.compute_dim_topN_means
        unmerged = score.compute_all_from_userdata_records(records, collapse_duplicate_versions=False)
    else:
        results = taikob_v2.compute_all_v2_from_userdata_records(records)
        aggregate, dimensions = taikob_v2.aggregate_topN_value_v2, taikob_v2.compute_dim_topN_means_v2
    compact = model(records, results, version)
    assert compact['top']
    for count in range(1, 51):
        actual = summary.statistics(compact, count)
        assert actual['rating'] == aggregate(results, 'AI_rating', count)
        assert actual['dimensions'] == dimensions(results, count)
    if version == 'v1':
        raw_compact = model(records, unmerged, version)['unmerged']
        for count in range(1, 51):
            assert summary.statistics(raw_compact, count)['rating'] == aggregate(unmerged, 'AI_rating', count)


def test_daily_capture_reuses_v2_results_and_preserves_same_day_previous(tmp_path, monkeypatch):
    records = json.loads(Path('fixtures/U05.json').read_text())['current']['songs']
    calls = []
    calculate = taikob_v2.compute_all_v2_from_userdata_records
    def counted(rows):
        calls.append(1)
        return calculate(rows)
    monkeypatch.setattr(taikob_v2, 'compute_all_v2_from_userdata_records', counted)
    store = PublicationStore(tmp_path / 'userdata', '111')
    now = datetime.now(daily.SHANGHAI)
    with store.exclusive():
        store.commit({'current': json.dumps({'songs': records}).encode()})
        daily.capture_snapshot('111', records, now, userdata_dir=store.root, publication_store=store)
        daily.capture_snapshot('111', records, now + timedelta(seconds=1), userdata_dir=store.root,
                               publication_store=store, repeated=True)
        assert len(calls) == 1
        daily.capture_snapshot('111', records, now + timedelta(seconds=2), userdata_dir=store.root,
                               publication_store=store)
        assert len(calls) == 2
        with daily.archive('111', 'v2-top20', userdata_dir=store.root, publication_store=store, writable=False) as days:
            row = days[now.date().isoformat()]
            assert row['bxx']['previous']['capturedAt'] == now.isoformat()
            assert row['bxx']['first']['capturedAt'] == now.isoformat()
            assert row['bxx']['model']['top20']['AI_rating'] == row['rating']


def test_bxx_capture_never_reads_or_reconstructs_history(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('BXX attempted historical reconstruction')
    for name in ('history_names', 'history_raw'):
        monkeypatch.setattr(ScoreReadView, name, forbidden)
    monkeypatch.setattr(b30_history, '_reconstruct_user_snapshots', forbidden)
    original = ScoreReadView.decoded
    def decoded(view, key='current'):
        assert key == 'current'
        return original(view, key)
    monkeypatch.setattr(ScoreReadView, 'decoded', decoded)
    store = PublicationStore(tmp_path / 'userdata', '111')
    payload = {'songs': []}
    now = datetime.now(daily.SHANGHAI)
    with store.exclusive():
        store.commit({'current': json.dumps(payload).encode(), 'history/data_old.json': b'invalid historical JSON'})
        with daily.archive('111', 'v2-top20', userdata_dir=store.root, publication_store=store) as days:
            days[(now.date() - timedelta(days=1)).isoformat()] = legacy_row((now - timedelta(days=1)).isoformat(), 8)
    provider = SimpleNamespace()
    with store.shared():
        history = b30_history.capture(provider, store.reader(), store, (20, [], True, False, None), payload)
    assert history == ()
    assert provider.b30_inputs['comparison']['baseline']['rating'] == 8
    assert 'history_snapshots' not in provider.b30_inputs and 'daily_points' not in provider.b30_inputs


def test_merged_bxx_first_materialization_does_not_rebuild_member_history(tmp_path, monkeypatch):
    from taiko_store import merged_materialization as merged
    def forbidden(*args, **kwargs):
        raise AssertionError('BXX attempted merged history reconstruction')
    monkeypatch.setattr(merged, 'derive_merged_read', forbidden)
    monkeypatch.setattr(merged, '_load_song_combo_map', lambda: {})
    for identity in ('111', '222'):
        store = PublicationStore(tmp_path, identity)
        with store.exclusive():
            store.commit({'current': b'{"songs":[],"profile":{},"achievement":{}}',
                          'history/data_old.json': b'invalid historical JSON'})
    calls = []
    merged.materialize(tmp_path, 'onebot_v11:7', ['111', '222'], '111', 'u0-test',
                       current_only=True, on_current=lambda *args: calls.append(1))
    assert calls == [1]

    merged.materialize(tmp_path, 'onebot_v11:7', ['111', '222'], '111', 'u0-test',
                       current_only=True, on_current=lambda *args: calls.append(1))
    assert calls == [1]


@pytest.mark.parametrize('version', ['v1', 'v2'])
@pytest.mark.parametrize('fixture_id', ['U05', 'U09'])
def test_real_image_uses_saved_diff_and_growth(version, fixture_id, monkeypatch):
    from taiko_bot.runtime.player.center.bxx_capture import model
    from taiko_bot.runtime.player.center.b30_support import b30_render, taikob_v2 as render_v2
    from taiko_application.score import B30Renderer
    from taiko_bot.runtime.player.center.taikob_v2_data import load_v2_snapshot
    current = json.loads(Path('fixtures', fixture_id + '.json').read_text())['current']
    records = current['songs']
    results = taikob_v2.compute_all_v2_from_userdata_records(records) if version == 'v2' else []
    saved = summary.statistics(model(records, results, version), 20)
    previous = deepcopy(saved)
    previous['rating'] -= 0.1
    previous['top'][0][2] -= 0.25
    previous['top'].pop()
    previous['dimensions'] = {key: value - 0.1 for key, value in saved['dimensions'].items()}
    prepared = {'previous': previous, 'baseline': previous}
    contexts = []
    original = B30Renderer.render
    def render(renderer, *args, **kwargs):
        contexts.append(renderer.context)
        return original(renderer, *args, **kwargs)
    monkeypatch.setattr(B30Renderer, 'render', render)
    if version == 'v2':
        image = render_v2.render_b20_v2_image('111', userdata=current, snapshot=load_v2_snapshot(),
            comparison=prepared, observed_at='2026-11-12T12:00:00', as_png_bytes=False)
    else:
        image = b30_render.render_b30_image('111', N=20, userdata=current,
            collapse_duplicate_versions=True, comparison=prepared,
            observed_at='2026-11-12T12:00:00', as_png_bytes=False)
    try:
        assert image.width == 1080 and image.height > 1000
        new, improved, dimensions, total = contexts[0].update_diff
        assert [[int(entry['song_no']), int(entry['level']), rating]
                for rating, entry in contexts[0].top_entries] == saved['top']
        assert new == {(saved['top'][-1][0], saved['top'][-1][1])}
        assert list(improved.values()) == pytest.approx([0.25])
        assert total == pytest.approx(0.1)
        assert all(value == pytest.approx(0.1) for value in dimensions.values())
        assert all(row['delta'] == pytest.approx(0.1) for row in contexts[0].trend_rows)
    finally:
        image.close()


def test_viewer_b30_adapter_reads_measurements_without_history(tmp_path, monkeypatch):
    from taiko_bot.offline import viewer
    from taiko_bot.runtime.player.center.b30_support import b30_render
    store = PublicationStore(tmp_path, '111')
    with store.exclusive():
        store.commit({'current': b'{"songs":[]}'})
    monkeypatch.setattr(viewer, '_userdata_root', lambda: tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Viewer B30 opened history')
    monkeypatch.setattr(ScoreReadView, 'history_names', forbidden)
    monkeypatch.setattr(ScoreReadView, 'history_raw', forbidden)
    calls = []
    monkeypatch.setattr(b30_render, 'render_b30_image', lambda *args, **kwargs: calls.append(kwargs) or b'PNG')
    assert viewer.render_b30_image(111) == b'PNG'
    assert 'comparison' in calls[0] and 'history_snapshots' not in calls[0]


def test_non_python_publication_writer_uses_existing_daily_capture(tmp_path, monkeypatch):
    from taiko_store.bridge import capture_current_measurement
    store = PublicationStore(tmp_path, '111')
    records = [{'song_no': 1, 'level': 4}]
    with store.exclusive():
        store.commit({'current': json.dumps({'songs': records}).encode()})
        calls = []
        monkeypatch.setattr(daily, 'capture_snapshot', lambda *args, **kwargs: calls.append((args, kwargs)))
        capture_current_measurement(store)
    assert calls[0][0][:2] == ('111', records)
    assert calls[0][1]['publication_store'] is store


def test_bridge_publish_measures_once_and_skips_nonce_retry_and_deletion(tmp_path, monkeypatch):
    from taiko_store import bridge
    from io import BytesIO
    import signal
    import sys
    messages = [
        {'method': 'put', 'key': 'current', 'body': '{"songs":[]}'},
        {'method': 'publish', 'transactionId': 'a' * 32},
        {'method': 'put', 'key': 'current', 'body': '{"songs":[]}'},
        {'method': 'publish', 'transactionId': 'a' * 32},
        {'method': 'remove', 'key': 'current'},
        {'method': 'publish', 'transactionId': 'b' * 32},
        {'method': 'finish'},
    ]
    monkeypatch.setattr(sys, 'argv', ['bridge', '--root', str(tmp_path), '--identity', '111', '--mode', 'write'])
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=BytesIO(
        b''.join(json.dumps(row).encode() + b'\n' for row in messages))))
    replies, calls = [], []
    monkeypatch.setattr(bridge, 'send', replies.append)
    monkeypatch.setattr(bridge, 'capture_current_measurement', lambda store: calls.append(store.identity))
    handler = signal.getsignal(signal.SIGALRM)
    try:
        assert bridge.main() == 0
    finally:
        signal.signal(signal.SIGALRM, handler)
    assert calls == ['111']
    assert all('error' not in row for row in replies)
