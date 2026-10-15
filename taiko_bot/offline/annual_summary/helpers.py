from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

DAN_GRADE_NAMES = {
    1: "五级",
    2: "四级",
    3: "三级",
    4: "二级",
    5: "一级",
    6: "初段",
    7: "二段",
    8: "三段",
    9: "四段",
    10: "五段",
    11: "六段",
    12: "七段",
    13: "八段",
    14: "九段",
    15: "十段",
    16: "玄人",
    17: "名人",
    18: "超人",
    19: "达人",
}


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def format_dan_grade(value: Any) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    numeric = safe_int(raw, -1)
    return DAN_GRADE_NAMES.get(numeric, raw)


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def content_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def iso_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    localized = value.replace(tzinfo=SHANGHAI_TZ) if value.tzinfo is None else value.astimezone(SHANGHAI_TZ)
    return localized.isoformat(timespec="seconds")


def iso_date(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def parse_datetime(raw_value: Any) -> Optional[datetime]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d_%H%M%S_%f",
        "%Y-%m-%d_%H_%M_%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def parse_date(raw_value: Any) -> date:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("version date is required")
    return date.fromisoformat(value)


def song_key(song: Dict[str, Any]) -> Tuple[int, int]:
    return safe_int(song.get("song_no"), -1), safe_int(song.get("level"), -1)


# The game writes a wall-clock moment on every chart it has a record for. Those
# moments reach back far beyond the annual observation window, but they are the
# chart's own business history: a player whose archive is first observed today
# can still carry a highscore_datetime from years ago. They are therefore *not*
# evidence of when this system started recording the account, and the period
# anchor must never be derived from them.


def build_song_map(state: Dict[str, Any]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    result: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for raw_song in state.get("songs") or []:
        if not isinstance(raw_song, dict):
            continue
        key = song_key(raw_song)
        if key[0] > 0 and key[1] > 0:
            result[key] = raw_song
    return result


def metric(status: str, data: Any = None, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status, "data": data}
    if reason:
        payload["reason"] = reason
    return payload


def public_source_name(source: str) -> str:
    return source if source in {"wahlap", "hiroba", "merged-bind", "web-account"} else "unknown"
