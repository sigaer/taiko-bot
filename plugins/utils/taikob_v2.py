from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata

from .duplicate_versions import duplicate_identity_key
from .score_calculator import calc_y

ROOT_DIR = get_settings().root_dir
V2_CONSTANTS_CSV = ROOT_DIR / "songs" / "constants_id_v2.csv"

DIFFICULTY_MAP = {
    "oni": 4,
    "edit": 5,
}

V2_DIM_COLUMNS = ["体力", "手速", "爆发", "精度", "节奏", "复合"]
V2_TAIKOB_DIM_ALIASES = {
    "体力": "体力",
    "stamina": "体力",
    "手速": "手速",
    "高速": "手速",
    "高速处理": "手速",
    "handspeed": "手速",
    "speed": "手速",
    "爆发": "爆发",
    "爆发力": "爆发",
    "burst": "爆发",
    "精度": "精度",
    "精度力": "精度",
    "accuracy": "精度",
    "accuracy_power": "精度",
    "节奏": "节奏",
    "节奏处理": "节奏",
    "rhythm": "节奏",
    "复合": "复合",
    "复合处理": "复合",
    "complex": "复合",
    "综合": "综合Rating",
    "综合rating": "综合Rating",
    "rating": "综合Rating",
}
V2_COL_TO_ATTR = {
    "综合Rating": "AI_rating",
    "体力": "stamina_rt",
    "手速": "handspeed_rt",
    "爆发": "burst_rt",
    "精度": "accuracy_rt",
    "节奏": "rhythm_rt",
    "复合": "complex_rt",
}


@dataclass(frozen=True)
class V2SongData:
    song_id: int
    level: int
    title: str
    total_notes: int
    sub_constant_1: float
    main_constant: float
    sub_constant_2: float
    stamina: float
    handspeed: float
    burst: float
    complex: float
    rhythm: float


@dataclass
class V2RatingResult:
    song_id: int
    level: int
    song_name: str
    high_score: int
    accuracy: float
    bad_rate: float
    AI_rating: float
    stamina_rt: float
    handspeed_rt: float
    burst_rt: float
    complex_rt: float
    rhythm_rt: float
    accuracy_rt: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@lru_cache(maxsize=1)
def _load_v2_song_map() -> Dict[Tuple[int, int], V2SongData]:
    song_map: Dict[Tuple[int, int], V2SongData] = {}
    with V2_CONSTANTS_CSV.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            difficulty = DIFFICULTY_MAP.get(str(row.get("difficulty") or "").strip().lower())
            if difficulty is None:
                continue
            song = V2SongData(
                song_id=_safe_int(row.get("id")),
                level=difficulty,
                title=str(row.get("title") or "").strip(),
                total_notes=_safe_int(row.get("totalNotes")),
                sub_constant_1=_safe_float(row.get("sub_constant_1")),
                main_constant=_safe_float(row.get("main_constant")),
                sub_constant_2=_safe_float(row.get("sub_constant_2")),
                stamina=_safe_float(row.get("stamina")),
                handspeed=_safe_float(row.get("handspeed")),
                burst=_safe_float(row.get("burst")),
                complex=_safe_float(row.get("complex")),
                rhythm=_safe_float(row.get("rhythm")),
            )
            if song.song_id <= 0 or song.total_notes <= 0:
                continue
            song_map[(song.song_id, song.level)] = song
    return song_map


def _calc_p(x: float, y: float, p1: float = 150.0) -> float:
    term = p1**2 - ((x - y) ** 2) / 2.0
    if term < 0:
        return p1
    return p1 - math.sqrt(term)


def _calc_w(x: float, y: float) -> float:
    term = 25 - ((x - 15.5) ** 2) / 25.0 - ((y - 23.0) ** 2) / 69.0
    if term < 0:
        return 0.5
    return max(math.sqrt(term) - 4.0, 0.5)


def _calc_single_rating(x: float, y: float) -> float:
    p_value = _calc_p(x, y)
    w_value = _calc_w(x, y)
    if abs(p_value) < 1e-9:
        x = max(x, 1e-9)
        y = max(y, 1e-9)
        return math.exp(w_value * math.log(x) + (1.0 - w_value) * math.log(y))
    value = w_value * (x**p_value) + (1.0 - w_value) * (y**p_value)
    value = max(value, 0.0)
    return value ** (1.0 / p_value)


def _calc_ln_rating(rating: float, dimension_value: float, accuracy: float) -> float:
    base = min(rating, dimension_value)
    upper = max(rating, dimension_value)
    if dimension_value <= rating:
        if dimension_value <= 0:
            return base
        return base + min(accuracy / dimension_value, 1.0) * math.log(upper - base + 1.0)

    rt1 = base + min(accuracy / max(dimension_value, 1e-9), 1.0) * math.log(
        upper - base + 1.0
    )
    rt2 = math.sqrt(base * upper)
    if accuracy <= rating:
        weight_one, weight_two = 1.0, 0.0
    elif accuracy >= dimension_value:
        weight_one, weight_two = 0.0, 1.0
    else:
        denominator = max(dimension_value - rating, 1e-9)
        weight_one = (accuracy - rating) / denominator
        weight_two = (dimension_value - accuracy) / denominator
    return rt1 * weight_one + rt2 * weight_two


def _calculate_v2_from_chart(
    chart: V2SongData,
    *,
    accuracy_per: float,
    bad_per: float,
) -> V2RatingResult:
    accuracy_per = _clamp01(accuracy_per)
    bad_per = _clamp01(bad_per)
    accuracy = calc_y(accuracy_per, normalization_factor=15.5, algorithm="comprehensive")

    rt_90 = _calc_single_rating(chart.sub_constant_1, calc_y(0.9, 15.5, "comprehensive"))
    rt_95_ref = _calc_single_rating(chart.sub_constant_1, calc_y(0.95, 15.5, "comprehensive"))
    rt_95 = _calc_single_rating(chart.main_constant, calc_y(0.95, 15.5, "comprehensive"))
    rt_100_ref = _calc_single_rating(chart.main_constant, calc_y(1.0, 15.5, "comprehensive"))
    rt_100 = _calc_single_rating(chart.sub_constant_2, calc_y(1.0, 15.5, "comprehensive"))

    x_ini = chart.sub_constant_1 if accuracy_per <= 0.95 else chart.main_constant
    rt_ini = _calc_single_rating(x_ini, accuracy)

    if accuracy_per <= 0.9:
        rating = rt_ini
    elif accuracy_per <= 0.95:
        denominator = rt_95_ref - rt_90
        rating = rt_95 if abs(denominator) < 1e-9 else rt_90 + (rt_95 - rt_90) * (rt_ini - rt_90) / denominator
    else:
        denominator = rt_100_ref - rt_95
        rating = rt_100 if abs(denominator) < 1e-9 else rt_95 + (rt_100 - rt_95) * (rt_ini - rt_95) / denominator

    accuracy_rt = _calc_ln_rating(rating, accuracy, accuracy)
    stamina_rt = _calc_single_rating(chart.stamina, accuracy)
    handspeed_rt = _calc_single_rating(chart.handspeed, accuracy)

    burst_rt_base = _calc_single_rating(chart.burst, accuracy)
    burst_hs_factor = min(accuracy / chart.handspeed, 1.0) if chart.handspeed > 0 else 1.0
    burst_candidate = burst_rt_base * burst_hs_factor
    if burst_candidate > handspeed_rt:
        denominator = chart.burst - chart.handspeed
        if abs(denominator) < 1e-9:
            blend = 1.0 if accuracy > chart.handspeed else 0.0
        else:
            blend = min(max(accuracy - chart.handspeed, 0.0) / denominator, 1.0)
        burst_rt = handspeed_rt + blend * (burst_candidate - handspeed_rt)
    else:
        burst_rt = burst_candidate

    complex_rt_base = _calc_single_rating(chart.complex, accuracy)
    complex_penalty = (5000.0 / 9.0) * (max(0.03 - bad_per, 0.0) ** 2) + 0.5
    complex_rt = complex_rt_base * complex_penalty

    rhythm_rt_base = _calc_single_rating(chart.rhythm, accuracy)
    rhythm_rt = rhythm_rt_base * burst_hs_factor

    return V2RatingResult(
        song_id=chart.song_id,
        level=chart.level,
        song_name=chart.title,
        high_score=0,
        accuracy=accuracy_per,
        bad_rate=bad_per,
        AI_rating=rating,
        stamina_rt=stamina_rt,
        handspeed_rt=handspeed_rt,
        burst_rt=burst_rt,
        complex_rt=complex_rt,
        rhythm_rt=rhythm_rt,
        accuracy_rt=accuracy_rt,
    )


def _build_result_from_entry(entry: Dict[str, Any]) -> Optional[V2RatingResult]:
    song_id = _safe_int(entry.get("song_no"), 0)
    level = _safe_int(entry.get("level"), 0)
    chart = _load_v2_song_map().get((song_id, level))
    if chart is None:
        return None

    great = _safe_int(entry.get("good_cnt"))
    good = _safe_int(entry.get("ok_cnt"))
    bad = _safe_int(entry.get("ng_cnt"))
    if _safe_int(entry.get("dondaful_combo_cnt"), 0) > 0:
        accuracy_per = 1.0
        bad_per = 0.0
    else:
        total_notes = max(chart.total_notes, 1)
        accuracy_per = (great + good * 0.5) / total_notes
        bad_per = bad / total_notes

    result = _calculate_v2_from_chart(chart, accuracy_per=accuracy_per, bad_per=bad_per)
    result.high_score = _safe_int(entry.get("high_score"))
    return result


def _load_userdata_payload(user_id: int | str) -> Any:
    cached = get_cached_userdata(str(user_id))
    if isinstance(cached, dict):
        return cached
    userdata_path = get_settings().userdata_dir / f"{str(user_id)}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")
    with userdata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_userdata_records(payload: Any) -> List[Dict[str, Any]]:
    records = payload.get("songs", []) if isinstance(payload, dict) else payload
    return records if isinstance(records, list) else []


def compute_all_v2_from_userdata_records(
    userdata_records: List[Dict[str, Any]],
) -> List[V2RatingResult]:
    deduped: Dict[Tuple[str, int, int], V2RatingResult] = {}
    for entry in userdata_records:
        result = _build_result_from_entry(entry)
        if result is None or result.level < 4 or result.AI_rating <= 0:
            continue
        identity = duplicate_identity_key(int(result.song_id), int(result.level))
        current = deduped.get(identity)
        if current is None or (
            float(result.AI_rating),
            int(result.high_score),
        ) > (
            float(current.AI_rating),
            int(current.high_score),
        ):
            deduped[identity] = result
    return list(deduped.values())


def compute_all_v2_from_userdata(user_id: int | str) -> List[V2RatingResult]:
    payload = _load_userdata_payload(user_id)
    return compute_all_v2_from_userdata_records(_extract_userdata_records(payload))


def _build_dimension_rows(
    results: List[V2RatingResult],
    *,
    attr: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for result in results:
        dim_score = getattr(result, attr, None)
        if dim_score is None:
            continue
        rows.append(
            {
                "song_id": int(result.song_id),
                "level": int(result.level),
                "title": str(result.song_name or ""),
                "score": int(result.high_score or 0),
                "accuracy_rate": float(result.accuracy or 0.0) * 100.0,
                "dim_score": float(dim_score),
            }
        )
    rows.sort(key=lambda row: (-row["dim_score"], -row["score"], row["title"]))
    return rows


def render_b20_v2_image(user_id: int | str) -> bytes:
    payload = _load_userdata_payload(user_id)
    userdata = payload if isinstance(payload, dict) else {"songs": payload}
    results = compute_all_v2_from_userdata_records(_extract_userdata_records(payload))
    rows = _build_dimension_rows(results, attr="AI_rating")[:20]

    from . import _render_dimension_table_image, _render_simple_notice

    if not rows:
        return _render_simple_notice(
            "taikob20 v2 暂无可展示的数据。",
            1060,
            24,
            "assets/fonts/DDFont.ttf",
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    return _render_dimension_table_image(
        user_id=int(user_id),
        userdata=userdata,
        title_text=f"综合Rating best{len(rows)} (v2)",
        rows=rows,
        assets_base=ROOT_DIR / "assets",
        font_path="assets/fonts/DDFont.ttf",
        dim_label="综合Rating",
    )


def render_b20_v2_dim_image(
    user_id: int | str,
    dim: str,
    N: int = 20,
    font_path: str | None = "assets/fonts/DDFont.ttf",
) -> bytes:
    attr = V2_COL_TO_ATTR.get(dim)
    from . import _render_dimension_table_image, _render_simple_notice

    if not attr:
        return _render_simple_notice(
            f"不支持的维度：{dim}",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    payload = _load_userdata_payload(user_id)
    userdata = payload if isinstance(payload, dict) else {"songs": payload}
    results = compute_all_v2_from_userdata_records(_extract_userdata_records(payload))
    rows = _build_dimension_rows(results, attr=attr)[: max(1, int(N))]
    if not rows:
        return _render_simple_notice(
            f"{dim}暂无可展示的数据。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    return _render_dimension_table_image(
        user_id=int(user_id),
        userdata=userdata,
        title_text=f"{dim} best{len(rows)} (v2)",
        rows=rows,
        assets_base=ROOT_DIR / "assets",
        font_path=font_path,
        dim_label=dim,
    )
