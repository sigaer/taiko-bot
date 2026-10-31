from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from ..chart.roll import compute_rating_roll_breakdown

RATING_CONFIG: Dict[str, Dict[str, Any]] = {'goku': {'display': '极', 'aliases': ['极', '極'], 'ratio': 1.0}, 'ziya': {'display': '紫雅', 'aliases': ['紫雅', '紫'], 'ratio': 0.95}, 'fenya': {'display': '粉雅', 'aliases': ['粉雅', '粉'], 'ratio': 0.9}, 'jinya': {'display': '金雅', 'aliases': ['金雅', '金'], 'ratio': 0.8}, 'yincui': {'display': '银粹', 'aliases': ['银粹', '銀粹', '银', '銀'], 'ratio': 0.7}, 'tongcui': {'display': '铜粹', 'aliases': ['铜粹', '銅粹', '铜', '銅'], 'ratio': 0.6}, 'baicui': {'display': '白粹', 'aliases': ['白粹', '白'], 'ratio': 0.5}}
_RATING_ALIAS_TO_KEY: Dict[str, str] = {}
for _key, _config in RATING_CONFIG.items():
    for _alias in _config['aliases']:
        _RATING_ALIAS_TO_KEY[_alias] = _key
_SORTED_RATING_ALIASES = sorted(_RATING_ALIAS_TO_KEY.keys(), key=len, reverse=True)
_DIFF_PREFIXES = [('里谱', 5, '里谱'), ('里', 5, '里谱'), ('鬼', 4, '表谱'), ('魔王', 4, '表谱'), ('表谱', 4, '表谱'), ('表', 4, '表谱'), ('松谱', 3, '松谱'), ('松', 3, '松谱'), ('困难谱', 3, '松谱'), ('困难', 3, '松谱'), ('竹谱', 2, '竹谱'), ('竹', 2, '竹谱'), ('普通谱', 2, '竹谱'), ('普通', 2, '竹谱'), ('一般', 2, '竹谱'), ('梅谱', 1, '梅谱'), ('梅', 1, '梅谱'), ('简单谱', 1, '梅谱'), ('简单', 1, '梅谱')]
DIFFICULTY_LEVEL_LABELS = {1: '梅谱', 2: '竹谱', 3: '松谱', 4: '表谱', 5: '里谱'}

@dataclass(frozen=True)
class ScoreLineRequest:
    mode: str
    rating_key: Optional[str]
    rating_display: Optional[str]
    song_query: str
    speed_ips: float
    level: int
    level_label: str
    target_rating: Optional[float] = None

def _safe_int(value: Any, default: int=0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _safe_float(value: Any, default: float=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def _round_up_to_10(score: float) -> int:
    return int(math.ceil(score / 10.0) * 10)

def _normalize_title(text: str) -> str:
    normalized = str(text or '').strip()
    normalized = normalized.replace('〜', '～')
    normalized = normalized.replace('~', '～')
    normalized = normalized.replace('（', '(')
    normalized = normalized.replace('）', ')')
    normalized = normalized.replace('＆', '&')
    normalized = normalized.replace('＠', '@')
    normalized = normalized.replace('！', '!')
    normalized = normalized.replace('？', '?')
    for src in ('‐', '‑', '‒', '–', '—', '―', '－', 'ｰ'):
        normalized = normalized.replace(src, '-')
    normalized = normalized.replace('【限定】', '')
    normalized = normalized.replace('(裏)', '')
    normalized = normalized.replace('(裏譜面)', '')
    normalized = re.sub('\\s+', '', normalized)
    return normalized.lower()

def _normalize_title_aggressive(text: str) -> str:
    normalized = _normalize_title(text)
    normalized = re.sub('\\([^)]*\\)', '', normalized)
    return normalized

def _score_target_map(goku_score: int) -> Dict[str, int]:
    targets: Dict[str, int] = {}
    for key, config in RATING_CONFIG.items():
        targets[key] = _round_up_to_10(goku_score * float(config['ratio']))
    return targets

def _extract_roll_times(roll_row: Optional[Dict[str, Any]], level: int) -> List[float]:
    if not roll_row:
        return []
    all_rolls = roll_row.get('roll_times')
    if not isinstance(all_rolls, list) or not 1 <= level <= len(all_rolls):
        return []
    raw = all_rolls[level - 1]
    if not isinstance(raw, list):
        return []
    return [_safe_float(item) for item in raw if _safe_float(item, -1.0) >= 0]

def _extract_balloons(roll_row: Optional[Dict[str, Any]], level: int) -> List[int]:
    if not roll_row:
        return []
    all_balloons = roll_row.get('balloons')
    if not isinstance(all_balloons, list) or not 1 <= level <= len(all_balloons):
        return []
    raw = all_balloons[level - 1]
    if not isinstance(raw, list):
        return []
    return [_safe_int(item, -1) for item in raw if _safe_int(item, -1) >= 0]

def _append_title_index(index: Dict[str, List[Dict[str, Any]]], title: Any, row: Dict[str, Any], *, aggressive: bool=False) -> None:
    normalized = _normalize_title_aggressive(title) if aggressive else _normalize_title(title)
    if not normalized:
        return
    index.setdefault(normalized, []).append(row)

def _pick_unique_candidate(index: Dict[str, List[Dict[str, Any]]], normalized_title: str) -> Optional[Dict[str, Any]]:
    candidates = index.get(normalized_title, [])
    if not candidates:
        return None
    unique: List[Dict[str, Any]] = []
    seen_keys = set()
    for row in candidates:
        row_id = _safe_int(row.get('id'), -1)
        row_key = row_id if row_id >= 0 else id(row)
        if row_key in seen_keys:
            continue
        seen_keys.add(row_key)
        unique.append(row)
    if len(unique) == 1:
        return unique[0]
    return None

def _scoreline_row_quality(row: Dict[str, Any]) -> Tuple[int, int, int, int, int]:
    return (1 if _safe_int(row.get('initial_points'), 0) > 0 else 0, 1 if row.get('selected_version') else 0, 1 if _safe_int(row.get('max_combo'), 0) > 0 else 0, 1 if _safe_int(row.get('goku_score'), 0) > 0 else 0, 1 if _safe_int(row.get('tenjo_score'), 0) > 0 else 0)

def _prefer_scoreline_row(current: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> Dict[str, Any]:
    if current is None or _scoreline_row_quality(candidate) > _scoreline_row_quality(current):
        return candidate
    return current

def deduplicate_scoreline_rows(rows: List[Dict[str, Any]], song_rows: Optional[List[Dict[str, Any]]]=None) -> List[Dict[str, Any]]:
    """Collapse duplicate charts by song id and difficulty without losing score metadata."""
    canonical_titles: Dict[int, set[str]] = {}
    title_ids: Dict[str, set[int]] = {}
    aggressive_title_ids: Dict[str, set[int]] = {}
    for song in song_rows or []:
        song_id = _safe_int(song.get('id'), -1)
        if song_id < 0:
            continue
        titles = canonical_titles.setdefault(song_id, set())
        for title in (song.get('song_name_jp'), song.get('song_name')):
            normalized = _normalize_title(str(title or ''))
            if normalized:
                titles.add(normalized)
                title_ids.setdefault(normalized, set()).add(song_id)
            aggressive = _normalize_title_aggressive(str(title or ''))
            if aggressive:
                aggressive_title_ids.setdefault(aggressive, set()).add(song_id)
    grouped: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    ordered_keys: List[Tuple[str, Any]] = []
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        song_id = _safe_int(row.get('id'), -1)
        level = _safe_int(row.get('level'), 4)
        if song_id < 0:
            normalized = _normalize_title(str(row.get('title') or ''))
            candidates = title_ids.get(normalized, set())
            if len(candidates) != 1:
                aggressive = _normalize_title_aggressive(str(row.get('title') or ''))
                candidates = aggressive_title_ids.get(aggressive, set())
            if len(candidates) == 1:
                song_id = next(iter(candidates))
                row['id'] = song_id
        if song_id < 0:
            ordered_keys.append(('row', (index, row)))
            continue
        key = (song_id, level)
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(('group', key))
        grouped[key].append(row)
    result: List[Dict[str, Any]] = []
    for kind, value in ordered_keys:
        if kind == 'row':
            result.append(value[1])
            continue
        candidates = grouped[value]
        song_id, _ = value
        known_titles = canonical_titles.get(song_id, set())
        canonical_candidates = [row for row in candidates if _normalize_title(str(row.get('title') or '')) in known_titles]
        pool = canonical_candidates or candidates
        picked = max(pool, key=_scoreline_row_quality).copy()
        metadata_source = max(candidates, key=_scoreline_row_quality)
        if _safe_int(picked.get('initial_points'), 0) <= 0:
            picked['initial_points'] = metadata_source.get('initial_points')
        if not picked.get('selected_version'):
            picked['selected_version'] = metadata_source.get('selected_version')
        if _safe_int(picked.get('max_combo'), 0) <= 0:
            picked['max_combo'] = metadata_source.get('max_combo')
        result.append(picked)
    return result

def compute_roll_hits(roll_times: List[float], speed_ips: float, balloon_hits: int=0) -> int:
    total_seconds = sum((_safe_float(duration) for duration in roll_times))
    return max(0, int(round(total_seconds * speed_ips))) + max(0, _safe_int(balloon_hits))

def compute_scoreline_result(entry: Dict[str, Any], rating_key: str, speed_ips: float) -> Dict[str, Any]:
    note_count = _safe_int(entry.get('max_combo'), 0)
    good_points = _safe_int(entry.get('initial_points'), 0)
    ok_points = _safe_int(entry.get('ok_points'), 0)
    delta = good_points - ok_points
    target_score = _safe_int((entry.get('rating_scores') or {}).get(rating_key), 0)
    roll_breakdown = compute_rating_roll_breakdown(entry, speed_ips)
    roll_hits = roll_breakdown.effective_roll_hits
    balloon_hits = roll_breakdown.raw_balloon_hits
    roll_score = roll_hits * 100
    max_score = note_count * good_points + roll_score
    min_score = note_count * ok_points + roll_score
    if note_count <= 0 or good_points <= 0 or delta <= 0 or (target_score <= 0):
        raise ValueError('谱面分值数据不完整。')
    if max_score < target_score:
        return {'reachable': False, 'target_score': target_score, 'roll_hits': roll_hits, 'balloon_hits': balloon_hits, 'roll_adjusted': roll_breakdown.adjusted, 'preserved_balloon_hits': roll_breakdown.preserved_balloon_hits, 'replaced_balloon_hits': roll_breakdown.replaced_balloon_hits, 'special_balloon_seconds': roll_breakdown.special_balloon_seconds, 'roll_score': roll_score, 'max_ok': -1, 'good_points': good_points, 'ok_points': ok_points, 'max_score': max_score, 'min_score': min_score}
    if min_score >= target_score:
        max_ok = note_count
    else:
        max_ok = max(0, min(note_count, (max_score - target_score) // delta))
    return {'reachable': True, 'target_score': target_score, 'roll_hits': roll_hits, 'balloon_hits': balloon_hits, 'roll_adjusted': roll_breakdown.adjusted, 'preserved_balloon_hits': roll_breakdown.preserved_balloon_hits, 'replaced_balloon_hits': roll_breakdown.replaced_balloon_hits, 'special_balloon_seconds': roll_breakdown.special_balloon_seconds, 'roll_score': roll_score, 'max_ok': int(max_ok), 'good_points': good_points, 'ok_points': ok_points, 'max_score': max_score, 'min_score': min_score}

def parse_scoreline_request(text: str) -> ScoreLineRequest:
    compact = str(text or '').strip()
    match = re.match('^分数线\\s+(.+?)(?:\\s+(-?[0-9]+(?:\\.[0-9]+)?))?\\s*$', compact)
    if not match:
        raise ValueError('用法：分数线 [里/表/松/竹/梅]歌曲别名 目标rating；或分数线 [评价名] [里/表/松/竹/梅]歌曲别名 [连打秒速]')
    spec = re.sub('\\s+', ' ', match.group(1).strip())
    numeric_value = float(match.group(2)) if match.group(2) is not None else None
    rating_key: Optional[str] = None
    for alias in _SORTED_RATING_ALIASES:
        if spec.startswith(alias):
            rating_key = _RATING_ALIAS_TO_KEY[alias]
            spec = spec[len(alias):].strip()
            break
    if rating_key is None:
        for alias in _SORTED_RATING_ALIASES:
            if spec.endswith(alias):
                rating_key = _RATING_ALIAS_TO_KEY[alias]
                spec = spec[:-len(alias)].strip()
                break
    mode = 'evaluation' if rating_key is not None else 'rating'
    if numeric_value is None:
        if mode == 'rating':
            raise ValueError('用法：分数线 [里/表/松/竹/梅]歌曲别名 目标rating；或分数线 [评价名] [里/表/松/竹/梅]歌曲别名 [连打秒速]')
        numeric_value = 30.0
    if mode == 'evaluation' and (numeric_value < 0 or numeric_value > 60):
        raise ValueError('连打秒速需在 0 到 60 之间。')
    if mode == 'rating' and (numeric_value <= 0 or numeric_value > 30):
        raise ValueError('目标 rating 需大于 0 且不超过 30。')
    if not spec:
        raise ValueError('请提供歌曲别名或id。')
    level = 4
    level_label = '表谱'
    for prefix, diff_level, diff_label in _DIFF_PREFIXES:
        if spec.startswith(prefix):
            level = diff_level
            level_label = diff_label
            spec = spec[len(prefix):].strip()
            break
    if not spec:
        raise ValueError('请在难度前缀后提供歌曲别名或id。')
    return ScoreLineRequest(mode=mode, rating_key=rating_key, rating_display=str(RATING_CONFIG[rating_key]['display']) if rating_key is not None else None, song_query=spec, speed_ips=numeric_value if mode == 'evaluation' else 0.0, level=level, level_label=level_label, target_rating=numeric_value if mode == 'rating' else None)
