from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from ..models.calculation import SongMetrics, RatingResult, SongStats, ClientSongStats
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table, _calc_accuracy_for_record, aggregate_topN_value
from ..dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims
from ..chart.catalog import _build_song_index_by_id_level, _build_song_index_by_identity, _get_recommend_identity_key, _find_song_info_for_recommend_record, _get_title_like_existing

def _median(values: List[float]) -> float:
    vs = sorted([float(v) for v in values if v is not None])
    n = len(vs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return vs[mid]
    return (vs[mid - 1] + vs[mid]) / 2.0

def _get_song_indicator_value(song_info: dict, dimension: str, const_table: List[tuple]) -> float:
    """
    对齐你要求：
    - rating/daigouryoku/accuracy_power：来自 cfg["const_table"]["const_to_score"]（即 lookup_const_score）
    - stamina/speed/rhythm/complex：来自 AD/AE/AF/AG 原始值（compute_AD_AE_AF_AG）
    """
    const_value = float(song_info.get('score', 0.0) or 0.0)
    if dimension in ('rating', 'daigouryoku', 'accuracy_power'):
        return float(lookup_const_score(const_value, const_table))
    metrics = compute_AD_AE_AF_AG(song_info)
    if dimension == 'stamina':
        return float(metrics.stamina)
    if dimension == 'speed':
        return float(metrics.speed)
    if dimension == 'rhythm':
        return float(metrics.rhythm)
    if dimension == 'complex':
        return float(metrics.complex_proc)
    return 0.0

def build_all_stats_from_records(userdata: List[Dict[str, Any]], cfg: dict, *, collapse_duplicate_versions: bool=True, default_ids: Mapping[int, int] | None=None, visible_song_ids: set[int] | None=None, profile: str='recommend-center-20261010', identity_namespace='title') -> tuple[List[SongStats] | List[ClientSongStats], dict, List[tuple]]:
    if profile not in {'recommend-center-20261010', 'recommend-client-20261010'}:
        raise ValueError('unknown recommendation profile')
    center = profile == 'recommend-center-20261010'

    def stat(**values):
        if center:
            return SongStats(**values)
        values.pop('accuracy')
        return ClientSongStats(**values)
    songs = cfg['songs']
    const_map = cfg['const_table']['const_to_score']
    const_table = build_const_table(const_map)
    idx = _build_song_index_by_id_level(songs)
    idx_by_identity = _build_song_index_by_identity(songs, default_ids=default_ids, visible_song_ids=visible_song_ids, identity_namespace=identity_namespace)
    best_identity_keys: Dict[Tuple[str, int, int], Tuple[int, int]] = {}
    best_identity_acc: Dict[Tuple[str, int, int], float] = {}
    for rec in userdata if collapse_duplicate_versions else []:
        try:
            song_no = int(rec.get('song_no'))
            level = int(rec.get('level'))
        except Exception:
            continue
        if visible_song_ids is not None and song_no not in visible_song_ids:
            continue
        identity_key = _get_recommend_identity_key(song_no, level, default_ids=default_ids, identity_namespace=identity_namespace)
        found = _find_song_info_for_recommend_record(song_no, level, idx, idx_by_identity, default_ids=default_ids, identity_namespace=identity_namespace)
        if not found:
            continue
        _, song_info = found
        total_notes = int(song_info.get('combo', 0) or 0)
        great = int(rec.get('good_cnt', 0) or 0)
        good = int(rec.get('ok_cnt', 0) or 0)
        dondaful_cnt = int(rec.get('dondaful_combo_cnt', 0) or 0)
        accuracy = _calc_accuracy_for_record(total_notes=total_notes, great_cnt=great, good_cnt=good, dondaful_combo_cnt=dondaful_cnt, algorithm='comprehensive')
        if accuracy > best_identity_acc.get(identity_key, -1.0):
            best_identity_acc[identity_key] = accuracy
            best_identity_keys[identity_key] = (song_no, level)
    all_stats: List[SongStats] = []
    for rec in userdata:
        try:
            song_no = int(rec.get('song_no'))
            level = int(rec.get('level'))
        except Exception:
            continue
        if visible_song_ids is not None and song_no not in visible_song_ids:
            continue
        identity_key = _get_recommend_identity_key(song_no, level, default_ids=default_ids, identity_namespace=identity_namespace)
        if collapse_duplicate_versions and best_identity_keys.get(identity_key) != (song_no, level):
            continue
        found = _find_song_info_for_recommend_record(song_no, level, idx, idx_by_identity, default_ids=default_ids, identity_namespace=identity_namespace)
        if not found:
            continue
        song_key, song_info = found
        title = _get_title_like_existing(song_info, level)
        great = int(rec.get('good_cnt', 0) or 0)
        good = int(rec.get('ok_cnt', 0) or 0)
        bad = int(rec.get('ng_cnt', 0) or 0)
        const_value = float(song_info.get('score', 0.0) or 0.0)
        total_notes = int(song_info.get('combo', 0) or 0)
        dondaful_cnt = int(rec.get('dondaful_combo_cnt', 0) or 0)
        accuracy = _calc_accuracy_for_record(total_notes=total_notes, great_cnt=great, good_cnt=good, dondaful_combo_cnt=dondaful_cnt, algorithm='comprehensive')
        M = lookup_const_score(const_value, const_table)
        if accuracy == 0.0:
            all_stats.append(stat(title=title, song_id=song_no, level=level, rating=0.0, daigouryoku=0.0, stamina=0.0, speed=0.0, accuracy_power=0.0, rhythm=0.0, complex=0.0, great=great, good=good, bad=bad, accuracy=accuracy))
            continue
        N = calc_y(accuracy=accuracy, normalization_factor=15.5, algorithm='comprehensive')
        P = compute_P(M, N)
        Q = compute_Q(M, N)
        AI = compute_AI(M, N, P, Q)
        metrics = compute_AD_AE_AF_AG(song_info)
        six = compute_six_dims(AI, M, N, metrics)
        all_stats.append(stat(title=title, song_id=song_no, level=level, rating=float(AI), daigouryoku=float(six['大歌力']), stamina=float(six['体力']), speed=float(six['高速处理']), accuracy_power=float(six['精度力']), rhythm=float(six['节奏处理']), complex=float(six['复合处理']), great=great, good=good, bad=bad, accuracy=accuracy))
    return (all_stats, songs, const_table)

def collapse_stats_for_recommendation(stats: List[SongStats], *, default_ids: Mapping[int, int] | None=None, identity_namespace='title') -> List[SongStats]:
    best: Dict[Tuple[str, int, int], Tuple[int, float]] = {}
    for index, item in enumerate(stats):
        identity = _get_recommend_identity_key(item.song_id, item.level, default_ids=default_ids, identity_namespace=identity_namespace)
        if identity not in best or item.accuracy > best[identity][1]:
            best[identity] = (index, item.accuracy)
    selected = {index for index, _ in best.values()}
    return [item for index, item in enumerate(stats) if index in selected]

def recommend_songs(all_stats: List[SongStats], songs_cfg: dict, const_table: List[tuple], best_key: str='rating', limit: int=20, *, default_ids: Mapping[int, int] | None=None, cn_available_chart_keys: set[tuple[int, int]] | None=None, on_shelf_song_ids: set[int] | None=None, visible_song_ids: set[int] | None=None, identity_namespace='title') -> List[dict]:
    """
    主推荐函数：复刻 recommend.ts 的总体行为（按你要求改 indicator 来源）
    best_key 支持：rating / daigouryoku / stamina / speed / accuracy_power / rhythm / complex
    返回 list[dict]，便于你直接转文字/转图片。
    """
    if not songs_cfg:
        return []
    if not all_stats:
        return []
    song_info_by_identity = _build_song_index_by_identity(songs_cfg, default_ids=default_ids, visible_song_ids=visible_song_ids, identity_namespace=identity_namespace)
    best20 = sorted(all_stats, key=lambda s: float(getattr(s, best_key)), reverse=True)[:20]
    best20_keys = {_get_recommend_identity_key(s.song_id, s.level, default_ids=default_ids, identity_namespace=identity_namespace) for s in best20}
    best20_indicator_vals: List[float] = []
    for s in best20:
        found = song_info_by_identity.get(_get_recommend_identity_key(s.song_id, s.level, default_ids=default_ids, identity_namespace=identity_namespace))
        if not found:
            continue
        _, song_info = found
        v = _get_song_indicator_value(song_info, best_key, const_table)
        if v > 0:
            best20_indicator_vals.append(v)
    best20_indicator_median = _median(best20_indicator_vals)
    if best20_indicator_median <= 0:
        return []
    best20_rating_vals: List[float] = []
    for s in best20:
        found = song_info_by_identity.get(_get_recommend_identity_key(s.song_id, s.level, default_ids=default_ids, identity_namespace=identity_namespace))
        if not found:
            continue
        _, song_info = found
        best20_rating_vals.append(_get_song_indicator_value(song_info, 'rating', const_table))
    best20_rating_median = _median(best20_rating_vals)
    played_map = {_get_recommend_identity_key(s.song_id, s.level, default_ids=default_ids, identity_namespace=identity_namespace): s for s in all_stats}
    seen_candidate_keys = set()
    candidates: List[dict] = []
    for k in songs_cfg:
        song_info = songs_cfg[k]
        try:
            song_id = int(song_info.get('id'))
        except Exception:
            song_id = None
        if song_id is None:
            continue
        lvl = int(song_info.get('level', 0) or 0)
        if cn_available_chart_keys:
            if (song_id, lvl) not in cn_available_chart_keys:
                continue
        elif on_shelf_song_ids and song_id not in on_shelf_song_ids:
            continue
        title = _get_title_like_existing(song_info, lvl)
        identity_key = _get_recommend_identity_key(song_id, lvl, default_ids=default_ids, identity_namespace=identity_namespace)
        if identity_key in best20_keys:
            continue
        if identity_key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(identity_key)
        song_rating_indicator = _get_song_indicator_value(song_info, 'rating', const_table)
        if song_rating_indicator > best20_rating_median + 0.2:
            continue
        st = played_map.get(identity_key)
        is_unplayed = st is None
        if is_unplayed:
            st = SongStats(title=title, song_id=song_id, level=lvl, rating=0.0, daigouryoku=0.0, stamina=0.0, speed=0.0, accuracy_power=0.0, rhythm=0.0, complex=0.0, great=0, good=0, bad=0)
        display_title = title
        display_song_id = song_id
        display_level = lvl
        if not is_unplayed:
            display_title = str(st.title)
            display_song_id = int(st.song_id)
            display_level = int(st.level)
        song_indicator = _get_song_indicator_value(song_info, best_key, const_table)
        if song_indicator <= 0:
            continue
        user_score_value = float(getattr(st, best_key))
        total_notes = float(song_info.get('combo', 0) or 0)
        if is_unplayed:
            user_acc = 0.0
            accuracy_factor = 0.5
        else:
            user_acc = 0.0
            if total_notes > 0:
                user_acc = (st.great + 0.5 * st.good) / total_notes
            if user_acc >= 0.5:
                accuracy_factor = 1.0 - user_acc
            else:
                accuracy_factor = 1.0
        indicator_dev_signed = (song_indicator - best20_indicator_median) / best20_indicator_median
        indicator_dev_abs = abs(indicator_dev_signed)
        score_dev = abs(user_score_value - best20_indicator_median) / best20_indicator_median
        balance_score = indicator_dev_abs * 1.0 - score_dev * 2.0 - accuracy_factor * 1.5
        is_in_strict_range = song_indicator <= best20_indicator_median * 1.05 and song_indicator >= best20_indicator_median * 0.9
        candidates.append({'title': display_title, 'song_id': display_song_id, 'level': display_level, 'is_unplayed': is_unplayed, 'recommend_score': balance_score, 'indicator_deviation_percent': indicator_dev_signed, 'indicator_deviation_abs': indicator_dev_abs, 'score_deviation_percent': score_dev, 'user_indicator': user_score_value, 'reference_indicator': best20_indicator_median, 'accuracy': user_acc, 'accuracy_factor': accuracy_factor, 'is_in_strict_range': is_in_strict_range, 'song_indicator': song_indicator, 'rating_indicator': song_rating_indicator})
    UNPLAYED_INDICATOR_DEVIATION_THRESHOLD = 0.1
    unplayed = [c for c in candidates if c['is_unplayed'] and c['indicator_deviation_abs'] <= UNPLAYED_INDICATOR_DEVIATION_THRESHOLD]
    played = [c for c in candidates if not c['is_unplayed']]
    strict_unplayed = [c for c in unplayed if c['is_in_strict_range']]
    strict_played = [c for c in played if c['is_in_strict_range']]
    loose_unplayed = [c for c in unplayed if not c['is_in_strict_range']]
    loose_played = [c for c in played if not c['is_in_strict_range']]
    strict_unplayed.sort(key=lambda c: c['recommend_score'])
    strict_played.sort(key=lambda c: c['recommend_score'])
    loose_unplayed.sort(key=lambda c: c['indicator_deviation_abs'])
    loose_played.sort(key=lambda c: c['indicator_deviation_abs'])
    half = int(limit) // 2
    out: List[dict] = []

    def take(src: List[dict], k: int):
        nonlocal out
        if k <= 0 or not src:
            return
        out.extend(src[:k])
        del src[:k]
    take(strict_unplayed, min(half, len(strict_unplayed)))
    take(strict_played, min(limit - len(out), len(strict_played)))
    if len(out) < limit:
        need_unplayed = max(0, half - len([x for x in out if x['is_unplayed']]))
        take(loose_unplayed, min(need_unplayed, len(loose_unplayed)))
    if len(out) < limit:
        take(loose_played, min(limit - len(out), len(loose_played)))
    if len(out) < limit:
        take(loose_unplayed, min(limit - len(out), len(loose_unplayed)))
    if len(out) < limit:
        take(strict_unplayed, min(limit - len(out), len(strict_unplayed)))
    if len(out) < limit:
        take(strict_played, min(limit - len(out), len(strict_played)))
    return out[:limit]
