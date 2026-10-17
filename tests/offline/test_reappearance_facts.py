"""G1 fact correction: source snapshots are observations, not play receipts."""
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from taiko_bot.offline.annual_summary.constants import ALGORITHM_VERSION
from taiko_bot.offline.annual_summary.events import build_observation_events
from taiko_bot.offline.annual_summary.snapshots import load_snapshot_history, select_window


def payload(stage, *, source='wahlap', full=True, removed=False, account='one', topology=(), chart=1):
    value = {'profile': {}, 'achievement': {}, 'dojo': {},
             'songs': [] if stage is None else [{'song_no': chart, 'level': 4, 'stage_cnt': stage,
                 'high_score': 1000000, 'update_datetime': '2026-01-04 12:00:00',
                 'highscore_datetime': '2026-01-04 12:00:00'}],
             '_meta': {'full': full, 'source': source, 'source_account': account,
                       'merge_topology': list(topology)}}
    if removed:
        value['songs_removed'] = [[chart, 4]]
    return value


def replay(root, sequence, *, start=date(2026, 1, 1), reverse_creation=False, same_day=False):
    folder = root / 'fixture'
    folder.mkdir(exist_ok=True)
    pairs = list(enumerate(sequence, 1))
    if reverse_creation:
        pairs.reverse()
    for index, item in pairs:
        day, hour = (1, index) if same_day else (index, 12)
        # Trusted timestamps fall inside the observation interval.
        for song in item['songs']:
            song['update_datetime'] = f'2026-01-{day:02d} {hour:02d}:00:00'
            song['highscore_datetime'] = song['update_datetime']
        (folder / f'data_202601{day:02d}_{hour:02d}0000_000000.json').write_text(json.dumps(item))
    history = load_snapshot_history('fixture', userdata_dir=root)
    selection = select_window(history.snapshots, start_date=start,
        generated_at=datetime(2026, 1, 31), end_date=date(2026, 1, 31))
    return build_observation_events(selection, start_date=start, effective_end_date=date(2026, 1, 31))[0]


def plays(events):
    return [item for item in events if item['type'] == 'play_delta']


@pytest.mark.parametrize('sequence', [
    [payload(10), payload(None, source='hiroba'), payload(30, source='hiroba')],
    [payload(10), payload(None), payload(30)],
    [payload(10), payload(None, full=False, removed=True), payload(30)],
    [payload(10), payload(20, source='hiroba'), payload(None), payload(30)],
    [payload(10), payload(None, account='two'), payload(30, account='two')],
    [payload(10, topology=('1','2')), payload(None, topology=('1','3')), payload(30, topology=('1','3'))],
    [payload(10, source='merged-bind'), payload(None, source='merged-bind'), payload(30, source='merged-bind')],
    [payload(10, source='manual-score'), payload(None, source='manual-score'), payload(30, source='manual-score')],
], ids=['source-and-deletion','full-absence','explicit-removal','historical-fail',
        'account-boundary','topology-boundary','merged-archive','manual'])
def test_reappearance_is_a_baseline_not_play(tmp_path, sequence):
    assert plays(replay(tmp_path, sequence)) == []


def test_pre_window_tombstone_survives_empty_selected_baseline(tmp_path):
    assert plays(replay(tmp_path, [payload(10), payload(None), payload(30)], start=date(2026,1,3))) == []


def test_delta_omission_is_not_deletion_and_keeps_counter_baseline(tmp_path):
    events = plays(replay(tmp_path, [payload(10), payload(None, full=False), payload(12)]))
    assert [event['delta']['playCount'] for event in events] == [2]


def test_reappearance_then_comparable_change_counts_only_later_delta(tmp_path):
    events = plays(replay(tmp_path, [payload(10), payload(None), payload(30), payload(32)]))
    assert [event['delta']['playCount'] for event in events] == [2]
    assert events[0]['before']['stage_cnt'] == 30


def test_true_first_seen_keeps_existing_minimum_evidence_policy(tmp_path):
    events = plays(replay(tmp_path, [payload(None), payload(30), payload(32)]))
    assert [event['delta']['playCount'] for event in events] == [1, 2]
    assert 'first_seen_chart' in events[0]['warnings']
    assert events[0]['timePrecision'] == 'batch_last_play_proxy'


def test_direct_switch_stays_zero(tmp_path):
    assert plays(replay(tmp_path, [payload(10), payload(20, source='hiroba'), payload(30)])) == []


def test_same_day_reappearance_does_not_add_a_play(tmp_path):
    events = plays(replay(tmp_path, [payload(10), payload(None), payload(30), payload(32)], same_day=True))
    assert [event['delta']['playCount'] for event in events] == [2]


def test_import_reappearance_never_becomes_play(tmp_path):
    assert plays(replay(tmp_path, [payload(10, source='web-score-import'),
        payload(None, source='web-score-import'), payload(30, source='web-score-import')])) == []


@pytest.mark.parametrize('boundary', [{'source':'hiroba'}, {'account':'two'}, {'topology':('2','3')}])
@pytest.mark.parametrize('first_stage', [10, 30])
@pytest.mark.parametrize('start', [date(2026,1,1), date(2026,1,3)])
def test_delta_identity_cannot_adopt_an_inherited_chart_baseline(tmp_path, boundary, first_stage, start):
    baseline = payload(10)
    baseline['songs'].extend(payload(10, chart=2)['songs'])
    sequence = [baseline, payload(20, full=False, **boundary),
        payload(first_stage, chart=2, full=False, **boundary),
        payload(first_stage+2, chart=2, full=False, **boundary)]
    events = plays(replay(tmp_path, sequence, start=start))
    assert [event['delta']['playCount'] for event in events] == [2]
    assert events[0]['songNo'] == 2


def test_replay_order_duplicate_and_interrupted_attempt_are_stable(tmp_path):
    sequence = [payload(10), payload(None), payload(30), payload(32), payload(32)]
    original = replay(tmp_path, sequence, reverse_creation=True)
    folder = tmp_path/'fixture'
    files = list(folder.glob('*.json'))
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    # A failed caller attempt does not mutate input evidence or persistent facts.
    with pytest.raises(RuntimeError):
        replay(tmp_path, sequence)
        raise RuntimeError('synthetic consumer interruption')
    again = replay(tmp_path, sequence)
    assert original == again
    assert [event['delta']['playCount'] for event in plays(again)] == [2]
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    assert ALGORITHM_VERSION == 'annual-observation-v4.5.4'
