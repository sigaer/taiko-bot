"""Lossless read adapter for legacy score records; writes use a separate Writer."""
from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any
from .types import Score

MAX_SAFE_INTEGER = 9007199254740991
SECRET_KEYS = frozenset({'cookie', 'password', 'token', 'authorization', 'secret', 'credentials', 'accesskeysecret'})


def _assert_value(value: Any, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError('score extension nesting exceeds contract limit')
    if isinstance(value, dict):
        if len(value) > 128:
            raise ValueError('score extension field count exceeds contract limit')
        for key, item in value.items():
            if not isinstance(key, str) or key.lower() in SECRET_KEYS:
                raise ValueError('score extension contains a credential field')
            _assert_value(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 128:
            raise ValueError('score extension array exceeds contract limit')
        for item in value:
            _assert_value(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > 4096:
            raise ValueError('score extension string exceeds contract limit')
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError('score extension number is not JSON interoperable')
    elif value is not None and not isinstance(value, bool):
        raise ValueError('score extension is not a JSON value')


def _count(value: Any, field: str) -> int | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('invalid score field: ' + field)
    if isinstance(value, str) and not re.fullmatch(r'[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value.strip()):
        raise ValueError('invalid score field: ' + field)
    try:
        number = float(value)
    except ValueError:
        raise ValueError('invalid score field: ' + field) from None
    if not math.isfinite(number) or number < 0 or number > MAX_SAFE_INTEGER or not number.is_integer():
        raise ValueError('invalid score field: ' + field)
    return int(number)


def from_legacy_score(record: dict[str, Any], *, source: str, captured_at: str | None,
                      chart_level: float | None = None, chart_type: str = 'unknown',
                      catalog_revision: str | None = None) -> Score:
    if not isinstance(record, dict):
        raise ValueError('score record must be an object')
    _assert_value(record)
    song_id = _count(record.get('song_no'), 'song_no')
    difficulty = _count(record.get('level'), 'level')
    if not song_id or difficulty not in range(1, 6):
        raise ValueError('score record requires a valid song and difficulty')
    if not isinstance(source, str) or not source.strip():
        raise ValueError('score source is required')
    if captured_at is not None and (not isinstance(captured_at, str) or not captured_at):
        raise ValueError('capturedAt must be an explicit instant or null')
    if chart_type not in {'single', 'double', 'unknown'}:
        raise ValueError('invalid chart type')
    if chart_level is not None and (isinstance(chart_level, bool) or not isinstance(chart_level, (int, float)) or not math.isfinite(chart_level) or chart_level < 0):
        raise ValueError('invalid chart star level')
    if catalog_revision is not None and (not isinstance(catalog_revision, str) or not catalog_revision):
        raise ValueError('invalid catalog revision')
    counts = {key: _count(record.get(field), field) for key, field in (
        ('clear', 'clear_cnt'), ('fullCombo', 'full_combo_cnt'),
        ('dondafulCombo', 'dondaful_combo_cnt'), ('stage', 'stage_cnt'), ('roll', 'pound_cnt'))}
    flag = lambda name: None if counts[name] is None else counts[name] > 0
    identity = record['song_no'] if isinstance(record['song_no'], str) else str(song_id)
    for field in ('highscore_datetime', 'update_datetime'):
        if record.get(field) is not None and not isinstance(record[field], str):
            raise ValueError('invalid score timestamp: ' + field)
    timestamp = lambda field: None if record.get(field) in (None, '') else str(record[field])
    return {
        'song': {'songId': identity, 'title': None, 'catalogRevision': catalog_revision},
        'chart': {'songId': identity, 'chartId': f'{identity}:{difficulty}:{chart_type}',
                  'difficulty': difficulty, 'level': chart_level, 'type': chart_type,
                  'variant': None, 'catalogRevision': catalog_revision},
        'score': _count(record.get('high_score'), 'high_score'),
        'good': _count(record.get('good_cnt'), 'good_cnt'),
        'ok': _count(record.get('ok_cnt'), 'ok_cnt'),
        'ng': _count(record.get('ng_cnt'), 'ng_cnt'),
        'combo': _count(record.get('combo_cnt'), 'combo_cnt'),
        'clear': flag('clear'), 'fullCombo': flag('fullCombo'), 'dondafulCombo': flag('dondafulCombo'),
        'rank': _count(record.get('best_score_rank'), 'best_score_rank'),
        'capturedAt': captured_at, 'source': source, 'counts': counts,
        'highscoreAt': timestamp('highscore_datetime'), 'updatedAt': timestamp('update_datetime'),
        'legacy': deepcopy(record),
    }


def to_legacy_score(score: Score) -> dict[str, Any]:
    """Return unchanged evidence only; never silently discard canonical edits."""
    if 'legacy' not in score:
        raise ValueError('legacy evidence is required for a lossless read roundtrip')
    projected = from_legacy_score(score['legacy'], source=score['source'], captured_at=score['capturedAt'],
                                  chart_level=score['chart']['level'], chart_type=score['chart']['type'],
                                  catalog_revision=score['chart']['catalogRevision'])
    if projected != score:
        raise ValueError('read contract cannot publish edited score evidence')
    return deepcopy(score['legacy'])
