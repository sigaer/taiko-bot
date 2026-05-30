from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from taiko_bot.settings import get_settings

BASE = get_settings().root_dir
SCORE_PATH = BASE / "songs" / "song_score.json"
ROLL_PATH = BASE / "songs" / "song_data_with_roll.json"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
UNIFIED_PATH = BASE / "songs" / "taiko_goku_onis.json"

RATING_CONFIG: Dict[str, Dict[str, Any]] = {
    "goku": {"display": "极", "aliases": ["极", "極"], "ratio": 1.0},
    "ziya": {"display": "紫雅", "aliases": ["紫雅", "紫"], "ratio": 0.95},
    "fenya": {"display": "粉雅", "aliases": ["粉雅", "粉"], "ratio": 0.90},
    "jinya": {"display": "金雅", "aliases": ["金雅", "金"], "ratio": 0.80},
    "yincui": {"display": "银粹", "aliases": ["银粹", "銀粹", "银", "銀"], "ratio": 0.70},
    "tongcui": {"display": "铜粹", "aliases": ["铜粹", "銅粹", "铜", "銅"], "ratio": 0.60},
    "baicui": {"display": "白粹", "aliases": ["白粹", "白"], "ratio": 0.50},
}

_RATING_ALIAS_TO_KEY: Dict[str, str] = {}
for _key, _config in RATING_CONFIG.items():
    for _alias in _config["aliases"]:
        _RATING_ALIAS_TO_KEY[_alias] = _key

_SORTED_RATING_ALIASES = sorted(_RATING_ALIAS_TO_KEY.keys(), key=len, reverse=True)

_DIFF_PREFIXES = [
    ("里谱", 5, "里谱"),
    ("里", 5, "里谱"),
    ("鬼", 4, "表谱"),
    ("魔王", 4, "表谱"),
    ("表谱", 4, "表谱"),
    ("表", 4, "表谱"),
    ("松", 3, "松谱"),
    ("困难", 3, "松谱"),
]


@dataclass(frozen=True)
class ScoreLineRequest:
    rating_key: str
    rating_display: str
    song_query: str
    speed_ips: float
    level: int
    level_label: str


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _round_up_to_10(score: float) -> int:
    return int(math.ceil(score / 10.0) * 10)


def _normalize_title(text: str) -> str:
    normalized = str(text or "").strip()
    normalized = normalized.replace("〜", "～")
    normalized = normalized.replace("~", "～")
    for src in ("‐", "‑", "‒", "–", "—", "―", "－", "ｰ"):
        normalized = normalized.replace(src, "-")
    normalized = normalized.replace("【限定】", "")
    normalized = normalized.replace("(裏)", "")
    normalized = normalized.replace("(裏譜面)", "")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.lower()


def _score_target_map(goku_score: int) -> Dict[str, int]:
    targets: Dict[str, int] = {}
    for key, config in RATING_CONFIG.items():
        targets[key] = _round_up_to_10(goku_score * float(config["ratio"]))
    return targets


def _extract_roll_times(roll_row: Optional[Dict[str, Any]], level: int) -> List[float]:
    if not roll_row:
        return []
    all_rolls = roll_row.get("roll_times")
    if not isinstance(all_rolls, list) or not (1 <= level <= len(all_rolls)):
        return []
    raw = all_rolls[level - 1]
    if not isinstance(raw, list):
        return []
    return [_safe_float(item) for item in raw if _safe_float(item, -1.0) >= 0]


def _extract_balloons(roll_row: Optional[Dict[str, Any]], level: int) -> List[int]:
    if not roll_row:
        return []
    all_balloons = roll_row.get("balloons")
    if not isinstance(all_balloons, list) or not (1 <= level <= len(all_balloons)):
        return []
    raw = all_balloons[level - 1]
    if not isinstance(raw, list):
        return []
    return [_safe_int(item, -1) for item in raw if _safe_int(item, -1) >= 0]


def rebuild_scoreline_dataset(output_path: Path = UNIFIED_PATH) -> Tuple[int, int]:
    score_rows = json.loads(SCORE_PATH.read_text(encoding="utf-8"))
    roll_rows = json.loads(ROLL_PATH.read_text(encoding="utf-8"))
    song_rows = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))

    roll_by_id: Dict[int, Dict[str, Any]] = {}
    roll_by_title: Dict[str, Dict[str, Any]] = {}
    for row in roll_rows:
        song_id = _safe_int(row.get("id"), -1)
        if song_id >= 0:
            roll_by_id[song_id] = row
        for key in (row.get("song_name_jp"), row.get("song_name")):
            normalized = _normalize_title(str(key or ""))
            if normalized and normalized not in roll_by_title:
                roll_by_title[normalized] = row

    song_by_id: Dict[int, Dict[str, Any]] = {}
    song_by_title: Dict[str, Dict[str, Any]] = {}
    for row in song_rows:
        song_id = _safe_int(row.get("id"), -1)
        if song_id >= 0:
            song_by_id[song_id] = row
        for key in (row.get("song_name_jp"), row.get("song_name")):
            normalized = _normalize_title(str(key or ""))
            if normalized and normalized not in song_by_title:
                song_by_title[normalized] = row

    merged: List[Dict[str, Any]] = []
    matched_count = 0
    for row in score_rows:
        level = _safe_int(row.get("level"), 4)
        base_title = str(row.get("title") or "").strip()
        normalized_title = _normalize_title(base_title)

        resolved_id = row.get("id")
        roll_row: Optional[Dict[str, Any]] = None
        song_row: Optional[Dict[str, Any]] = None
        match_source = "none"

        if resolved_id is not None and str(resolved_id).isdigit():
            resolved_id = int(resolved_id)
            roll_row = roll_by_id.get(resolved_id)
            song_row = song_by_id.get(resolved_id)
            if roll_row or song_row:
                match_source = "id"
        else:
            resolved_id = None

        if roll_row is None:
            roll_row = roll_by_title.get(normalized_title)
            if roll_row is not None:
                match_source = "title"
        if song_row is None:
            song_row = song_by_title.get(normalized_title)
            if song_row is not None and match_source == "none":
                match_source = "title"

        if resolved_id is None:
            if roll_row is not None:
                resolved_id = _safe_int(roll_row.get("id"), None)  # type: ignore[arg-type]
            elif song_row is not None:
                resolved_id = _safe_int(song_row.get("id"), None)  # type: ignore[arg-type]

        if match_source != "none":
            matched_count += 1

        max_combo = _safe_int(row.get("max_combo"), 0)
        if max_combo <= 0 and roll_row is not None:
            combos = roll_row.get("max_combo")
            if isinstance(combos, list) and 1 <= level <= len(combos):
                max_combo = _safe_int(combos[level - 1], 0)

        title_jp = str(
            (song_row or {}).get("song_name_jp")
            or (roll_row or {}).get("song_name_jp")
            or base_title
        ).strip()
        title_cn = str(
            (song_row or {}).get("song_name")
            or (roll_row or {}).get("song_name")
            or title_jp
        ).strip()
        initial_points = _safe_int(row.get("initial_points"), 0)
        ok_points = (initial_points // 2) // 10 * 10
        goku_score = _safe_int(row.get("goku_score"), 0)
        roll_times = _extract_roll_times(roll_row, level)
        balloons = _extract_balloons(roll_row, level)
        merged.append(
            {
                "id": resolved_id,
                "title": base_title,
                "title_jp": title_jp,
                "title_cn": title_cn,
                "level": level,
                "difficulty_label": "里谱" if level == 5 else "表谱",
                "tenjo_score": _safe_int(row.get("tenjo_score"), 0),
                "goku_score": goku_score,
                "rating_scores": _score_target_map(goku_score),
                "roll_required": _safe_int(row.get("roll_required"), 0),
                "roll_speed_ips": row.get("roll_speed_ips"),
                "max_combo": max_combo,
                "initial_points": initial_points,
                "ok_points": ok_points,
                "selected_version": row.get("selected_version"),
                "roll_times": roll_times,
                "roll_total_seconds": round(sum(roll_times), 6),
                "balloons": balloons,
                "balloon_hits": sum(balloons),
                "match_source": match_source,
            }
        )

    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _load_scoreline_data.cache_clear()
    return len(merged), matched_count


@lru_cache(maxsize=1)
def _load_scoreline_data() -> List[Dict[str, Any]]:
    source_mtime = max(
        SCORE_PATH.stat().st_mtime,
        ROLL_PATH.stat().st_mtime,
        SONG_DATA_PATH.stat().st_mtime,
    )
    if not UNIFIED_PATH.exists() or UNIFIED_PATH.stat().st_mtime < source_mtime:
        rebuild_scoreline_dataset()
    return json.loads(UNIFIED_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _build_chart_index() -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[Tuple[str, int], List[Dict[str, Any]]]]:
    by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in _load_scoreline_data():
        song_id = row.get("id")
        level = _safe_int(row.get("level"), 4)
        if song_id is not None:
            try:
                by_id[(int(song_id), level)] = row
            except Exception:
                pass
        for key in (row.get("title"), row.get("title_jp"), row.get("title_cn")):
            normalized = _normalize_title(str(key or ""))
            if not normalized:
                continue
            by_title.setdefault((normalized, level), []).append(row)
    return by_id, by_title


def get_scoreline_entry(
    song_id: Optional[int],
    level: int,
    fallback_title: str = "",
) -> Optional[Dict[str, Any]]:
    by_id, by_title = _build_chart_index()
    if song_id is not None:
        row = by_id.get((song_id, level))
        if row is not None:
            return row
    normalized = _normalize_title(fallback_title)
    if not normalized:
        return None
    rows = by_title.get((normalized, level), [])
    if len(rows) == 1:
        return rows[0]
    return None


def available_levels_for_song(song_id: Optional[int], fallback_title: str = "") -> List[int]:
    by_id, by_title = _build_chart_index()
    levels = set()
    if song_id is not None:
        for key in by_id:
            if key[0] == song_id:
                levels.add(key[1])
    normalized = _normalize_title(fallback_title)
    if normalized:
        for key in by_title:
            if key[0] == normalized:
                levels.add(key[1])
    return sorted(levels)


def compute_roll_hits(roll_times: List[float], speed_ips: float, balloon_hits: int = 0) -> int:
    total_seconds = sum(_safe_float(duration) for duration in roll_times)
    return max(0, int(round(total_seconds * speed_ips))) + max(0, _safe_int(balloon_hits))


def compute_scoreline_result(
    entry: Dict[str, Any],
    rating_key: str,
    speed_ips: float,
) -> Dict[str, Any]:
    note_count = _safe_int(entry.get("max_combo"), 0)
    good_points = _safe_int(entry.get("initial_points"), 0)
    ok_points = _safe_int(entry.get("ok_points"), 0)
    delta = good_points - ok_points
    target_score = _safe_int((entry.get("rating_scores") or {}).get(rating_key), 0)
    roll_times = entry.get("roll_times") or []
    balloon_hits = _safe_int(entry.get("balloon_hits"), 0)
    roll_hits = compute_roll_hits(
        roll_times if isinstance(roll_times, list) else [],
        speed_ips,
        balloon_hits,
    )
    roll_score = roll_hits * 100
    max_score = note_count * good_points + roll_score
    min_score = note_count * ok_points + roll_score

    if note_count <= 0 or good_points <= 0 or delta <= 0 or target_score <= 0:
        raise ValueError("谱面分值数据不完整。")

    if max_score < target_score:
        return {
            "reachable": False,
            "target_score": target_score,
            "roll_hits": roll_hits,
            "balloon_hits": balloon_hits,
            "roll_score": roll_score,
            "max_ok": -1,
            "good_points": good_points,
            "ok_points": ok_points,
            "max_score": max_score,
            "min_score": min_score,
        }

    if min_score >= target_score:
        max_ok = note_count
    else:
        max_ok = max(0, min(note_count, (max_score - target_score) // delta))

    return {
        "reachable": True,
        "target_score": target_score,
        "roll_hits": roll_hits,
        "balloon_hits": balloon_hits,
        "roll_score": roll_score,
        "max_ok": int(max_ok),
        "good_points": good_points,
        "ok_points": ok_points,
        "max_score": max_score,
        "min_score": min_score,
    }


def parse_scoreline_request(text: str) -> ScoreLineRequest:
    compact = str(text or "").strip()
    match = re.match(r"^分数线\s+(.+?)\s+(-?[0-9]+)\s*$", compact)
    if not match:
        raise ValueError("用法：分数线 [评价名] [里/表/松]歌曲别名 [连打秒速整数]")

    spec = re.sub(r"\s+", " ", match.group(1).strip())
    speed_ips = float(match.group(2))
    if speed_ips < 0 or speed_ips > 60:
        raise ValueError("？")

    rating_key: Optional[str] = None
    for alias in _SORTED_RATING_ALIASES:
        if spec.startswith(alias):
            rating_key = _RATING_ALIAS_TO_KEY[alias]
            spec = spec[len(alias) :].strip()
            break
    if rating_key is None:
        for alias in _SORTED_RATING_ALIASES:
            if spec.endswith(alias):
                rating_key = _RATING_ALIAS_TO_KEY[alias]
                spec = spec[: -len(alias)].strip()
                break
    if rating_key is None:
        raise ValueError("评价名仅支持：极、紫雅、粉雅、金雅、银粹、铜粹、白粹。")
    if not spec:
        raise ValueError("请在评价名后提供歌曲别名或id。")

    level = 4
    level_label = "表谱"
    for prefix, diff_level, diff_label in _DIFF_PREFIXES:
        if spec.startswith(prefix):
            level = diff_level
            level_label = diff_label
            spec = spec[len(prefix) :].strip()
            break

    if not spec:
        raise ValueError("请在难度前缀后提供歌曲别名或id。")

    return ScoreLineRequest(
        rating_key=rating_key,
        rating_display=str(RATING_CONFIG[rating_key]["display"]),
        song_query=spec,
        speed_ips=speed_ips,
        level=level,
        level_label=level_label,
    )


def format_scoreline_message(
    entry: Dict[str, Any],
    result: Dict[str, Any],
    request: ScoreLineRequest,
) -> str:
    title = str(entry.get("title_jp") or entry.get("title_cn") or entry.get("title") or "未知歌曲")
    target_score = int(result["target_score"])
    roll_hits = int(result["roll_hits"])
    balloon_hits = int(result.get("balloon_hits", 0))
    roll_score = int(result["roll_score"])
    speed_text = str(int(request.speed_ips))
    roll_times = entry.get("roll_times") or []
    if not roll_times and balloon_hits <= 0:
        roll_note = "无连打，秒速不影响结果"
    elif balloon_hits > 0:
        roll_note = f"预计连打得分：{roll_score}（{roll_hits} 打，含气球 {balloon_hits} 打）"
    else:
        roll_note = f"预计连打得分：{roll_score}（{roll_hits} 打）"

    if not result["reachable"]:
        return (
            f"歌曲：{title}（{request.level_label}）\n"
            f"评价：{request.rating_display}\n"
            f"目标分：{target_score}\n"
            f"连打秒速：{speed_text}\n"
            f"{roll_note}\n"
            f"该秒速下即使全良也无法达成，最高分约为 {int(result['max_score'])}。"
        )

    return (
        f"歌曲：{title}（{request.level_label}）\n"
        f"评价：{request.rating_display}\n"
        f"目标分：{target_score}\n"
        f"连打秒速：{speed_text}\n"
        f"{roll_note}\n"
        f"最多可数：{int(result['max_ok'])}"
    )


if __name__ == "__main__":
    total, matched = rebuild_scoreline_dataset()
    print(f"rebuilt {UNIFIED_PATH} rows={total} matched={matched}")
