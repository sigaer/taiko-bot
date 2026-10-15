from taiko_bot.offline.paths import root as _runtime_root
from io import BytesIO

import json

import math

import os

from pathlib import Path

from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from taiko_bot.runtime.player.center.duplicate_versions import (
    choose_best_record_in_group,
    group_ids_for_query,
)

from .score_calculator import (
    build_const_table,
    calc_accuracy,
    calc_y,
    compute_AD_AE_AF_AG,
    compute_AI,
    compute_P,
    compute_Q,
    compute_six_dims,
    lookup_const_score,
)

from taiko_bot.runtime.player.center.taikob_v2 import _calculate_v2_from_chart

from taiko_bot.runtime.player.center.taikob_v2_data import V2DataSourceError, load_v2_snapshot

WHITE = (255, 255, 255)

BLACK = (0, 0, 0)

BLUE = (0x26, 0x85, 0xDE)

SIZE_TITLE = 27

SIZE_SCORE = 48

SIZE_STATS = 24

STROKE_TITLE = 2

STROKE_SCORE = 3

STROKE_STATS = 2

ART_POS = (95, 88)

ART_SIZE = (400, 400)

INFO_X = 755

POS_TITLE_EN = (INFO_X, 140)

POS_TITLE_JP = (INFO_X, 230)

POS_TYPE = (INFO_X, 323)

LEVEL_STEP_X = 62

POS_ID_BPM = (INFO_X - 90, 412)

ROW_Y = [585, 715, 845, 975, 1105]

OPTION_ICON_SIZE = (30, 30)

OPTION_ICON_MARGIN = 8

LEVEL_X = 165

LEVEL_Y_OFFSET = 30

SCORE_X = 190

SCORE_Y_OFFSET = -int(SIZE_SCORE / 2)

RANK_ICON_SIZE = (85, 85)

CROWN_ICON_SIZE = (85, 85)

AFTER_SCORE_GAP = 12

AFTER_RANK_GAP = 12

RANK_X_FIXED = 425

CROWN_X_FIXED = 535

STAT_COL_X_CENTER = 733

POUND_COL_X_CENTER = 955

STAT_Y_OFFSET = -35

STAT_LINE_H = 40

USERDATA_DIR = str(_runtime_root() / 'userdata')

RATING_DB_PATH = str(_runtime_root() / 'songs/rating_structured_with_ids.json')

FONT_FILE_NAME = "DDFont.ttf"

RAW_DIM_KEYS = ["复合处理", "平均密度", "瞬间密度", "节奏处理", "BPM变化", "HS变化"]

RAW_DIM_VALUE_ALIASES = {
    "复合处理": ("复合处理",),
    "平均密度": ("平均密度",),
    "瞬间密度": ("瞬间密度",),
    "节奏处理": ("节奏处理", "叩き分け"),
    "BPM变化": ("BPM变化",),
    "HS变化": ("HS变化", "hs变化"),
}

PLAYER_DIM_KEYS = ["复合处理", "节奏处理", "精度力", "高速处理", "体力", "大歌力"]

RADAR_CARD_W = 420

RADAR_CARD_H = 1140

RADAR_CARD_GAP = 24

SIDE_PADDING = 24

RADAR_TOP_Y = 132

RADAR_RADIUS = 118

RADAR_GRID_STEPS = 5

DETAIL_PANEL_W = 500

DETAIL_PANEL_H = 550

DETAIL_PANEL_GAP = 22

DETAIL_SECTION_TOP_GAP = 28

DETAIL_PLAYER_LABEL_X = 268

DETAIL_PLAYER_VALUE_RIGHT_X = DETAIL_PANEL_W - 18

DETAIL_METRIC_MIN_GAP = 8

DETAIL_METRIC_FONT_SIZE = 20

DETAIL_METRIC_MIN_FONT_SIZE = 14

DETAIL_CONSTANT_COLUMN_CENTERS = (158, 292, 426)

TYPE_MAP = {
    "南梦宫原创音乐": "original",
    "流行音乐": "pop",
    "动漫音乐": "anime",
    "游戏音乐": "gamemusic",
    "博歌乐音乐": "vocaloid",
    "儿童音乐": "kid",
    "古典音乐": "classic",
    "综合音乐": "variety",
}

_RATING_INDEX_CACHE = {"mtime": None, "index": {}, "const_table": []}

from taiko_bot.offline.paths import root as _runtime_root
ROOT_DIR = _runtime_root()

from taiko_application.score import (
    ScorePresentationContext,
    B30SingleRenderer,
    B30Renderer,
    ScoreInfoRenderer,
    RecommendationRenderer,
)


def _load_note_count_map() -> Dict[Tuple[int, int], int]:
    cache = getattr(_load_note_count_map, "_cache", None)
    mapping: Dict[Tuple[int, int], int] = {}
    rating_path = Path(RATING_DB_PATH)
    if not rating_path.exists():
        return mapping
    mtime_ns = rating_path.stat().st_mtime_ns
    if cache and cache.get("mtime_ns") == mtime_ns:
        return cache["mapping"]

    with rating_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    songs = payload.get("songs", {})
    items = songs.values() if isinstance(songs, dict) else songs
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id"))
            level = int(item.get("level"))
            combo = int(float(item.get("combo") or 0))
        except Exception:
            continue
        if combo <= 0:
            continue
        key = (song_id, level)
        if combo > mapping.get(key, 0):
            mapping[key] = combo

    song_data_path = ROOT_DIR / "songs" / "song_data.json"
    if song_data_path.exists():
        try:
            song_rows = json.loads(song_data_path.read_text(encoding="utf-8"))
        except Exception:
            song_rows = []
        for song in song_rows:
            if not isinstance(song, dict):
                continue
            try:
                song_id = int(song.get("id"))
            except Exception:
                continue
            combos = song.get("max_combo") or []
            if not isinstance(combos, list):
                continue
            for level, value in enumerate(combos, start=1):
                if value in (None, "", "-"):
                    continue
                try:
                    combo = int(value)
                except Exception:
                    continue
                if combo <= 0:
                    continue
                key = (song_id, level)
                if combo > mapping.get(key, 0):
                    mapping[key] = combo

    _load_note_count_map._cache = {"mtime_ns": mtime_ns, "mapping": mapping}
    return mapping


def _collect_entries_for_song(
    data: list,
    song_no: int,
    *,
    title: str = "",
    prefer_best_in_group: bool = False,
) -> dict:
    """将同一 song_no 的记录按 level 聚合：dict[level] = entry（level: 1..5）"""
    out = {}
    if prefer_best_in_group:
        note_count_map = _load_note_count_map()
        group_ids = set(group_ids_for_query(song_id=song_no, title=title))
        records_by_level: Dict[int, list] = {}
        for e in data:
            try:
                record_song_no = int(e.get("song_no"))
                lvl = int(e.get("level", 0))
            except Exception:
                continue
            if group_ids and record_song_no not in group_ids:
                continue
            records_by_level.setdefault(lvl, []).append(e)
        for lvl, records in records_by_level.items():
            best = choose_best_record_in_group(
                records,
                song_id=song_no,
                title=title,
                level=lvl,
                note_count_by_key=note_count_map,
            )
            if best is not None:
                out[lvl] = best
        return out

    for e in data:
        if e.get("song_no") == song_no:
            try:
                lvl = int(e.get("level", 0))
            except Exception:
                continue
            out[lvl] = e
    return out


def _load_rating_song_index(path: str = RATING_DB_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = None
    cached = _RATING_INDEX_CACHE
    if cached.get("mtime") == mtime and cached.get("index"):
        return cached["index"]

    payload = json.load(open(path, "r", encoding="utf-8"))
    songs = payload.get("songs", {})
    const_map = (payload.get("const_table") or {}).get("const_to_score") or {}
    index = {}
    items = songs.values() if isinstance(songs, dict) else songs
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            sid = int(item.get("id"))
            lvl = int(item.get("level"))
        except Exception:
            continue
        index[(sid, lvl)] = item

    _RATING_INDEX_CACHE["mtime"] = mtime
    _RATING_INDEX_CACHE["index"] = index
    try:
        _RATING_INDEX_CACHE["const_table"] = build_const_table(const_map)
    except Exception:
        _RATING_INDEX_CACHE["const_table"] = []
    return index


def _load_rating_const_table(path: str = RATING_DB_PATH) -> list[tuple]:
    _load_rating_song_index(path)
    return _RATING_INDEX_CACHE.get("const_table", [])


def _build_player_metrics(
    chart_info: Optional[dict],
    entry: Optional[dict],
    const_table: list[tuple],
):
    if not chart_info or not entry or not const_table:
        return None
    try:
        total_notes = int(_to_float(chart_info.get("combo")) or 0)
        const_value = _to_float(chart_info.get("score"))
        if total_notes <= 0 or const_value is None:
            return None

        M = lookup_const_score(const_value, const_table)

        max_accuracy = 1.0
        N_max = calc_y(
            accuracy=max_accuracy,
            normalization_factor=15.5,
            algorithm="comprehensive",
        )
        P_max = compute_P(M, N_max)
        Q_max = compute_Q(M, N_max)
        AI_max = compute_AI(M, N_max, P_max, Q_max)
        metrics = compute_AD_AE_AF_AG(chart_info)
        six_max = compute_six_dims(AI_max, M, N_max, metrics)

        great_cnt = int(entry.get("good_cnt", 0) or 0)
        good_cnt = int(entry.get("ok_cnt", 0) or 0)
        dondaful_cnt = int(entry.get("dondaful_combo_cnt", 0) or 0)
        if dondaful_cnt > 0:
            accuracy = 1.0
        else:
            accuracy = calc_accuracy(
                total_notes=total_notes,
                great_cnt=great_cnt,
                good_cnt=good_cnt,
                algorithm="comprehensive",
            )

        if accuracy == 0.0:
            AI_cur = 0.0
            cur_dims = [0.0] * 6
        else:
            N_cur = calc_y(
                accuracy=accuracy,
                normalization_factor=15.5,
                algorithm="comprehensive",
            )
            P_cur = compute_P(M, N_cur)
            Q_cur = compute_Q(M, N_cur)
            AI_cur = compute_AI(M, N_cur, P_cur, Q_cur)
            six_cur = compute_six_dims(AI_cur, M, N_cur, metrics)
            cur_dims = [
                round(float(six_cur["复合处理"]), 2),
                round(float(six_cur["节奏处理"]), 2),
                round(float(six_cur["精度力"]), 2),
                round(float(six_cur["高速处理"]), 2),
                round(float(six_cur["体力"]), 2),
                round(float(six_cur["大歌力"]), 2),
            ]

        max_dims = [
            round(float(six_max["复合处理"]), 2),
            round(float(six_max["节奏处理"]), 2),
            round(float(six_max["精度力"]), 2),
            round(float(six_max["高速处理"]), 2),
            round(float(six_max["体力"]), 2),
            round(float(six_max["大歌力"]), 2),
        ]
        return {
            "current_dims": cur_dims,
            "max_dims": max_dims,
            "current_rating": round(float(AI_cur), 2),
            "max_rating": round(float(AI_max), 2),
        }
    except Exception:
        return None


def _build_v2_player_values(chart, entry):
    if not chart or not entry:
        return None
    try:
        accuracy = calc_accuracy(
            total_notes=int(chart.total_notes),
            great_cnt=int(entry.get("good_cnt", 0) or 0),
            good_cnt=int(entry.get("ok_cnt", 0) or 0),
            algorithm="comprehensive",
        )
        result = _calculate_v2_from_chart(
            chart,
            accuracy_per=accuracy,
            bad_per=int(entry.get("ng_cnt", 0) or 0) / max(int(chart.total_notes), 1),
        )
        maximum = _calculate_v2_from_chart(chart, accuracy_per=1.0, bad_per=0.0)
        return (
            [
                result.stamina_rt,
                result.handspeed_rt,
                result.burst_rt,
                result.accuracy_rt,
                result.rhythm_rt,
                result.complex_rt,
            ],
            result.AI_rating,
            [
                maximum.stamina_rt,
                maximum.handspeed_rt,
                maximum.burst_rt,
                maximum.accuracy_rt,
                maximum.rhythm_rt,
                maximum.complex_rt,
            ],
            maximum.AI_rating,
        )
    except Exception:
        return None








def _to_float(value):
    return ScoreInfoRenderer(ScorePresentationContext(Path(".")))._to_float(value)


def _available_chart_levels(song_data):
    return ScoreInfoRenderer(
        ScorePresentationContext(Path("."))
    )._available_chart_levels(song_data)
