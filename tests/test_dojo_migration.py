from datetime import datetime
from taiko_bot.runtime.player.center.dojo_version import dojo_payload_version, normalize_wahlap_dojo_scores
from taiko_bot.runtime.player.center.progress_support import dani_progress as dani


def test_fresh_empty_dojo_keeps_2026_reset_version():
    assert normalize_wahlap_dojo_scores({'scores': []}, fetched_at=datetime(2026, 10, 17))['version'] == '2026'
    assert dojo_payload_version({'scores': [], 'version': '2026'}) == '2026'
    assert dojo_payload_version({'scores': []}) == '2025'


def test_progress_never_reuses_other_version_and_finds_matching_history(monkeypatch):
    monkeypatch.setattr(dani, 'build_dojo_score_map', lambda value: {x['dan_id']: x for x in value.get('scores', [])})
    current = {'dojo': {'version': '2026', 'scores': [{'dan_id': 1, 'marker': 'new'}]}}
    history = [{'fileName': 'data_20261001.json', 'payload': {'dojo': {'version': '2025', 'scores': [{'dan_id': 1, 'marker': 'old'}]}}},
               {'fileName': 'data_20261017.json', 'payload': current}]
    assert dani._load_dojo_progress_payload(current, history, 1, '2025')['scores'][0]['marker'] == 'old'
    assert dani._load_dojo_progress_payload(current, history, 1, '2026')['scores'][0]['marker'] == 'new'
