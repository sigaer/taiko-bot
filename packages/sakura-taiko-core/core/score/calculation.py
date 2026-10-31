from __future__ import annotations
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, Iterable, Literal, Sequence
from ..models.calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef
from ..rating.v1 import *
from ..rating.v1 import _calc_accuracy_for_record
from ..dimension.v1 import *
from ..chart.catalog import _build_song_index_by_id_level, _build_song_index_by_identity, _find_song_info_for_recommend_record
def _compute_results_from_userdata_records(
    userdata_records: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    const_table: List[tuple],
    *,
    collapse_duplicate_versions: bool = False,
    duplicate_groups: Sequence[Sequence[int]] = (),
    default_ids: Mapping[int, int] | None = None,
    visible_song_ids: set[int] | None = None,
    identity_namespace: str = 'title',
) -> List[RatingResult]:
    PAIR_ID_MAP = {sid: index for index, group in enumerate(duplicate_groups) for sid in group}
    songs = cfg["songs"]
    idx = _build_song_index_by_id_level(songs)
    idx_by_identity = _build_song_index_by_identity(songs, default_ids, visible_song_ids=visible_song_ids, identity_namespace=identity_namespace)
    best_pair_keys: Dict[int, Tuple[int, int]] = {}
    best_pair_acc: Dict[int, float] = {}
    if collapse_duplicate_versions:
        for rec in userdata_records:
            try:
                song_no = int(rec.get("song_no"))
                level = int(rec.get("level"))
            except Exception:
                continue
            if visible_song_ids is not None and song_no not in visible_song_ids:
                continue
            pair_id = PAIR_ID_MAP.get(song_no)
            if pair_id is None:
                continue
            found = _find_song_info_for_recommend_record(
                song_no, level, idx, idx_by_identity, default_ids, identity_namespace=identity_namespace
            )
            if not found:
                continue
            _, song_info = found
            total_notes = int(song_info.get("combo", 0) or 0)
            good_cnt = int(rec.get("good_cnt", 0) or 0)
            ok_cnt = int(rec.get("ok_cnt", 0) or 0)
            dondaful_cnt = int(rec.get("dondaful_combo_cnt", 0) or 0)
            accuracy = _calc_accuracy_for_record(
                total_notes=total_notes,
                great_cnt=good_cnt,
                good_cnt=ok_cnt,
                dondaful_combo_cnt=dondaful_cnt,
                algorithm="comprehensive",
            )
            if accuracy > best_pair_acc.get(pair_id, -1.0):
                best_pair_acc[pair_id] = accuracy
                best_pair_keys[pair_id] = (song_no, level)
    results: List[RatingResult] = []
    for user_record in userdata_records:
        song_no = user_record["song_no"]
        level = user_record["level"]
        if level < 4:
            continue
        if visible_song_ids is not None and song_no not in visible_song_ids:
            continue
        if collapse_duplicate_versions:
            pair_id = PAIR_ID_MAP.get(song_no)
            if pair_id is not None and best_pair_keys.get(pair_id) != (song_no, level):
                continue
        good_cnt = int(user_record.get("good_cnt", 0) or 0)  # 良
        ok_cnt = int(user_record.get("ok_cnt", 0) or 0)  # 可

        # 查找对应的歌曲
        found = _find_song_info_for_recommend_record(song_no, level, idx, idx_by_identity, default_ids, identity_namespace=identity_namespace)
        song_name = None
        if found:
            song_key, song_info = found
            song_name = songs[song_key]["song_name_cn"]
            if level == 5:
                song_name += "(里谱)"

        if not song_name:
            continue

        # 获取歌曲的定数（score）
        const_value = song_info["score"]

        # 根据 good_cnt 计算良率
        total_notes = int(song_info.get("combo", 0) or 0)
        dondaful_cnt = int(user_record.get("dondaful_combo_cnt", 0) or 0)
        accuracy = _calc_accuracy_for_record(
            total_notes=total_notes,
            great_cnt=good_cnt,
            good_cnt=ok_cnt,
            dondaful_combo_cnt=dondaful_cnt,
            algorithm="comprehensive",
        )
        if accuracy == 0.0:
            continue  # comprehensive 阈值未达（<0.75），前端行为是直接丢弃

        # 由 H~L 计算 AD/AE/AF/AG
        metrics = compute_AD_AE_AF_AG(song_info)

        # 定数得点 M
        M = lookup_const_score(const_value, const_table)

        # 精度得点 N
        N = calc_y(
            accuracy=accuracy,
            normalization_factor=15.5,
            algorithm="comprehensive",
        )
        # P、Q
        P = compute_P(M, N)
        Q = compute_Q(M, N)

        # 综合 AI
        AI = compute_AI(M, N, P, Q)

        # 六维属性
        six = compute_six_dims(AI, M, N, metrics)

        results.append(
            RatingResult(
                song_id=song_no,
                level=level,
                song_name=song_name,
                high_score=int(user_record.get("high_score", 0) or 0),
                const_value=const_value,
                accuracy=accuracy,
                M_const_score=M,
                N_acc_score=N,
                raw_complex_proc=metrics.complex_proc,
                raw_stamina=metrics.stamina,
                raw_speed=metrics.speed,
                raw_rhythm=metrics.rhythm,
                P_param=P,
                Q_weight=Q,
                AI_rating=AI,
                big_song=six["大歌力"],
                stamina=six["体力"],
                speed=six["高速处理"],
                accuracy_power=six["精度力"],
                rhythm=six["节奏处理"],
                complex_proc=six["复合处理"],
            )
        )

    return results
