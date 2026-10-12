from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from sakura_taiko_core.chart.progress_catalog import is_song_on_shelf
from .context import ConstantQueryContext, PaginationContext

LEVEL_LABELS = {1: "简单", 2: "一般", 3: "困难", 4: "鬼", 5: "里"}
LEVEL_STAR_FIELD = {
    1: "level_1",
    2: "level_2",
    3: "level_3",
    4: "level_4",
    5: "level_5",
}
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class ConstChartRow:
    song_id: int
    level: int
    const_value: float
    title_cn: str
    title_jp: str
    diff_label: str
    star: str
    bpm: str
    combo: int
    density: str
    stamina: str
    rhythm: str
    complex_proc: str
    average: str
    song_type: str
    shelf_status: int


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any, digits: int = 1) -> str:
    num = _to_float(value)
    if num is None:
        return "-"
    if digits <= 0:
        return str(int(round(num)))
    return f"{num:.{digits}f}"


def _pick_title(
    song: Optional[Dict[str, Any]], chart: Dict[str, Any]
) -> Tuple[str, str]:
    cn = (
        (chart.get("song_name_cn") or "").strip()
        or (song or {}).get("song_name", "")
        or (song or {}).get("song_name_jp", "")
        or chart.get("曲名", "")
        or f"ID{chart.get('id')}"
    )
    jp = (song or {}).get("song_name_jp", "") or chart.get("曲名", "") or cn
    return (str(cn), str(jp))


def query_charts_by_const(context: ConstantQueryContext):
    const_value = context.value
    include_shelf_status = context.include_shelf_status
    song_index = context.song_index
    rows: List[ConstChartRow] = []
    for chart in context.rating_entries:
        score = _to_float(chart.get("score"))
        if score is None or abs(score - const_value) >= 1e-06:
            continue
        try:
            song_id = int(chart.get("id"))
            level = int(chart.get("level"))
        except (TypeError, ValueError):
            continue
        song = song_index.get(song_id)
        if not include_shelf_status and (
            not is_song_on_shelf((song or {}).get("shelf_status"))
        ):
            continue
        title_cn, title_jp = _pick_title(song, chart)
        star_field = LEVEL_STAR_FIELD.get(level, "level_4")
        star_raw = (song or {}).get(star_field, "-")
        star = "-" if star_raw in (None, "", "-") else str(star_raw)
        rows.append(
            ConstChartRow(
                song_id=song_id,
                level=level,
                const_value=const_value,
                title_cn=title_cn,
                title_jp=title_jp,
                diff_label=LEVEL_LABELS.get(level, f"L{level}"),
                star=star,
                bpm=str(chart.get("bpm") or "-"),
                combo=int(chart.get("combo") or 0),
                density=_fmt_num(chart.get("平均密度")),
                stamina=_fmt_num(chart.get("体力")),
                rhythm=_fmt_num(chart.get("节奏处理")),
                complex_proc=_fmt_num(chart.get("复合处理")),
                average=_fmt_num(chart.get("平均")),
                song_type=str((song or {}).get("type") or "-"),
                shelf_status=int((song or {}).get("shelf_status", 0) or 0),
            )
        )
    rows.sort(key=lambda r: (r.song_id, r.level))
    return rows


def paginate_rows(context: PaginationContext):
    rows, page, page_size = context.rows, context.page, context.page_size
    total = len(rows)
    if total == 0:
        return ([], 1, 1)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return (rows[start:end], page, total_pages)
