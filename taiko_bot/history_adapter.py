"""Decode the versioned private history transport with frozen host profiles.

No personal files or authority cache. File metadata is ordering provenance,
never evidence of a play or a verified measurement.
"""
import copy
import datetime
import math
import re
from pathlib import Path

from .viewer_client import ViewerClientError


def _invalid():
    return ViewerClientError("中心历史响应无效，请稍后重试。", status_code=503)


def snapshot_name_time(name):
    stem = Path(name).stem
    for expression, format_text in ((r"data_(\d{8}_\d{6}_\d{6})(?:_.+)?", "%Y%m%d_%H%M%S_%f"),
                                    (r"data_(\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2})(?:_.+)?", "%Y-%m-%d_%H_%M_%S")):
        match = re.fullmatch(expression, stem)
        if match:
            try:
                return datetime.datetime.strptime(match[1], format_text)
            except ValueError:
                pass
    return None


def validate_raw_snapshot(item):
    name = item.get("fileName")
    if not isinstance(name, str) or not re.fullmatch(r"data_[^/\\\x00]{1,255}\.json", name) or not isinstance(item.get("payload"), dict):
        raise _invalid()
    result = {"capturedAt": str(item.get("capturedAt") or ""), "payload": item["payload"], "fileName": name, "historyFormat": "raw-v1"}
    for field in ("fileMtime", "fileCtime"):
        if field in item:
            value = item[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise _invalid()
            result[field] = value
    if snapshot_name_time(name) is None and "fileMtime" not in result:
        raise _invalid()
    return result


def ordered_raw_history(items, *, filename_order=False):
    rows = []
    for item in items:
        if not isinstance(item, dict) or item.get("historyFormat") != "raw-v1":
            raise _invalid()
        value = validate_raw_snapshot(item)
        try:
            stamp = snapshot_name_time(value["fileName"])
            if stamp is None:
                if "fileMtime" not in value:
                    raise _invalid()
                stamp = datetime.datetime.fromtimestamp(value["fileMtime"])
        except (OverflowError, ValueError, OSError):
            raise _invalid() from None
        rows.append((stamp, value["fileName"], value["payload"]))
    return sorted(rows, key=(lambda row: row[1]) if filename_order else (lambda row: (row[0], row[1])))


def iter_trend_history(items):
    """The old client filesystem trend profile; explicit legacy DTOs stay separate."""
    profile, achievement, songs, base = {}, {}, {}, False
    for stamp, name, payload in ordered_raw_history(items):
        meta = payload.get("_meta", {})
        full = bool(meta.get("full")) or ("songs" in payload and "profile" in payload and "achievement" in payload and not meta)
        if full:
            profile = payload.get("profile", {})
            achievement = payload.get("achievement", {})
            songs = {(song.get("song_no"), song.get("level")): song for song in payload.get("songs", [])}
            base = True
        elif not base:
            continue
        else:
            if "profile" in payload:
                profile = payload.get("profile") or {}
            if "achievement" in payload:
                achievement = payload.get("achievement") or {}
            for song in payload.get("songs", []) or []:
                songs[(song.get("song_no"), song.get("level"))] = song
            for removed in payload.get("songs_removed", []) or []:
                songs.pop(tuple(removed), None)
        yield stamp, {"profile": profile, "achievement": achievement, "songs": list(songs.values())}


def previous_song_map(items, *, is_full, build_map, key_for, removed_key):
    previous, current = None, None
    for stamp, name, payload in ordered_raw_history(items):
        if is_full(payload) or current is None:
            values = [dict(song) for song in payload.get("songs") or [] if isinstance(song, dict)]
            updated = build_map(values)
        else:
            updated = dict(current)
            for song in payload.get("songs") or []:
                if isinstance(song, dict) and (key := key_for(song)) is not None:
                    updated[key] = dict(song)
            for removed in payload.get("songs_removed") or []:
                if (key := removed_key(removed)) is not None:
                    updated.pop(key, None)
        previous, current = current, updated
    return previous


def previous_dojo_state(items, *, normalize):
    previous, current = None, None
    for stamp, name, payload in ordered_raw_history(items):
        if "dojo" in payload:
            updated = normalize(payload.get("dojo") or {})
        else:
            updated = current
        if updated is not None:
            previous, current = current, updated
    return copy.deepcopy(previous)
