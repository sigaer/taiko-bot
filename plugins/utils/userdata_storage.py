from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import ujson as json

from taiko_bot.settings import get_settings

from .taiko_db import get_taiko_db_connection

TAIKO_SONG_DIR = str(get_settings().userdata_dir)


def _load_locked_song_keys(user_id: str) -> Set[Tuple[int, int]]:
    try:
        connection = get_taiko_db_connection()
    except Exception:
        return set()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT song_no, level
                FROM web_song_locks
                WHERE taiko_id=%s AND is_locked=1
                """,
                (str(user_id),),
            )
            return {
                (int(song_no), int(level))
                for song_no, level in cursor.fetchall()
            }
    except Exception:
        return set()
    finally:
        connection.close()


def merge_locked_songs(user_id: str, previous_payload: Any, latest_songs: list) -> list:
    if not isinstance(previous_payload, dict):
        return latest_songs

    locked_keys = _load_locked_song_keys(user_id)
    if not locked_keys:
        return latest_songs

    prev_songs = previous_payload.get("songs", [])
    prev_map = {
        (int(song.get("song_no", 0)), int(song.get("level", 0))): song
        for song in prev_songs
    }
    merged = []
    seen = set()
    for song in latest_songs:
        key = (int(song.get("song_no", 0)), int(song.get("level", 0)))
        if key in locked_keys and key in prev_map:
            merged.append(prev_map[key])
        else:
            merged.append(song)
        seen.add(key)

    for key in locked_keys:
        if key not in seen and key in prev_map:
            merged.append(prev_map[key])

    return merged


def save_userdata(
    user_id: str,
    userdata: Dict[str, Any],
    *,
    source: Optional[str] = None,
) -> None:
    user_id = str(user_id).strip()
    if not user_id:
        raise ValueError("user_id is required")

    if source:
        meta = userdata.setdefault("_meta", {})
        if isinstance(meta, dict):
            meta["source"] = source
            meta["synced_at"] = datetime.now().isoformat(timespec="seconds")

    base_dir = Path(TAIKO_SONG_DIR)
    base_dir.mkdir(parents=True, exist_ok=True)
    save_path = base_dir / f"{user_id}data.json"
    user_history_dir = base_dir / user_id
    user_history_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    history_path = user_history_dir / f"data_{ts}.json"

    prev_data = None
    if save_path.exists():
        try:
            with open(save_path, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
        except Exception:
            prev_data = None

    panel_data = userdata.get("profile", {})
    count_data = userdata.get("achievement", {})
    dojo_data = userdata.get("dojo", {})
    song_list = userdata.get("songs", [])

    song_list = merge_locked_songs(user_id, prev_data, song_list)
    userdata = {
        **userdata,
        "profile": panel_data,
        "songs": song_list,
        "achievement": count_data,
        "dojo": dojo_data,
    }
    payload = json.dumps(userdata, ensure_ascii=False, indent=4)

    def _song_key(song):
        return (song.get("song_no"), song.get("level"))

    def _build_song_map(songs):
        song_map = {}
        for s in songs or []:
            song_map[_song_key(s)] = s
        return song_map

    def _has_full_snapshot() -> bool:
        for p in user_history_dir.glob("data_*.json"):
            try:
                snap = json.load(open(p, "r", encoding="utf-8"))
            except Exception:
                continue
            meta = snap.get("_meta", {}) if isinstance(snap, dict) else {}
            if meta.get("full"):
                return True
            if (
                isinstance(snap, dict)
                and "songs" in snap
                and "profile" in snap
                and "achievement" in snap
                and not meta
            ):
                return True
        return False

    delta_snapshot: Dict[str, Any] = {"_meta": {"full": False, "ts": ts}}
    if prev_data and isinstance(prev_data, dict):
        if not _has_full_snapshot():
            delta_snapshot = {
                "_meta": {"full": True, "ts": ts, "source": source or "unknown"},
                "profile": panel_data,
                "achievement": count_data,
                "songs": song_list,
                "dojo": dojo_data,
            }
        else:
            prev_songs = prev_data.get("songs", [])
            prev_map = _build_song_map(prev_songs)
            new_map = _build_song_map(song_list)
            changed_songs = []
            for key, new_song in new_map.items():
                old_song = prev_map.get(key)
                if old_song != new_song:
                    changed_songs.append(new_song)
            removed = [key for key in prev_map.keys() if key not in new_map]

            if prev_data.get("profile") != panel_data:
                delta_snapshot["profile"] = panel_data
            if prev_data.get("achievement") != count_data:
                delta_snapshot["achievement"] = count_data
            if prev_data.get("dojo") != dojo_data:
                delta_snapshot["dojo"] = dojo_data
            delta_snapshot["songs"] = changed_songs
            if removed:
                delta_snapshot["songs_removed"] = removed
    else:
        delta_snapshot = {
            "_meta": {"full": True, "ts": ts, "source": source or "unknown"},
            "profile": panel_data,
            "achievement": count_data,
            "songs": song_list,
            "dojo": dojo_data,
        }

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(payload)
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(delta_snapshot, ensure_ascii=False, indent=4))
