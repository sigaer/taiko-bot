from __future__ import annotations
from taiko_bot.runtime.public.config import root as _runtime_root




import os

import hashlib

import uuid

from datetime import datetime

from typing import Any, Dict, Optional, Set, Tuple

import pymysql

from taiko_store import PublicationStore, PublicationError

import ujson as json

TAIKO_SONG_DIR = str(_runtime_root() / 'userdata/')

def _load_locked_song_keys(user_id: str) -> Set[Tuple[int, int]]:
    host = os.getenv("TAIKO_DB_HOST", "127.0.0.1")
    port = int(os.getenv("TAIKO_DB_PORT", "3306"))
    db_user = os.getenv("TAIKO_DB_USER", "")
    password = os.getenv("TAIKO_DB_PASSWORD")
    database = os.getenv("TAIKO_DB_NAME", "taiko")
    if not db_user or not password:
        raise PublicationError("Score write-lock database is not configured")
    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=db_user,
            password=password,
            database=database,
            charset="utf8mb4",
        )
    except Exception as error:
        raise PublicationError("Score write-lock database is unavailable") from error

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
    except Exception as error:
        raise PublicationError("Score write-lock query failed") from error
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
    publication_store: Optional[PublicationStore] = None,
) -> None:
    user_id = str(user_id).strip()
    if not user_id:
        raise ValueError("user_id is required")

    if publication_store is not None:
        # A synchronous authenticated acquisition may already own Source EX.
        # Reuse that exact lease; never open another EX or upgrade a SH lease.
        publication_store._require_lock(write=True)
        if publication_store.identity != user_id:
            raise PublicationError("Acquisition source does not match its lease")
        publication_store.collect()
        _save_userdata_locked(publication_store, user_id, userdata, source=source)
        return

    store = PublicationStore(os.getenv("TAIKO_USERDATA_DIR") or TAIKO_SONG_DIR, user_id)
    with store.exclusive():
        # Collect before the mutation; maintenance failure cannot misreport an
        # already committed score sync as an unsuccessful acquisition.
        store.collect()
        _save_userdata_locked(store, user_id, userdata, source=source)

def _save_userdata_locked(store, user_id, userdata, *, source=None):
    reader = store.reader()

    now = datetime.now()
    incoming_meta = userdata.get("_meta") if isinstance(userdata.get("_meta"), dict) else {}
    normalized_source = str(
        source
        or incoming_meta.get("source")
        or ((userdata.get("profile") or {}).get("_source") if isinstance(userdata.get("profile"), dict) else "")
        or "unknown"
    ).strip().lower().replace("_", "-")
    source_account = str(
        incoming_meta.get("source_account")
        or incoming_meta.get("sourceAccount")
        or user_id
    ).strip()
    merge_topology = (
        incoming_meta.get("merge_topology")
        or incoming_meta.get("mergeTopology")
        or incoming_meta.get("member_ids")
        or []
    )
    if not isinstance(merge_topology, list):
        merge_topology = []

    ts = now.strftime("%Y%m%d_%H%M%S_%f")
    # Keep the existing event/observation timestamp, add a storage identity only.
    sequence = 1 if reader.manifest is None else reader.manifest["sequence"] + 1
    history_name = f"data_{ts}_{sequence:020d}_{uuid.uuid4().hex}.json"

    prev_data = None
    try:
        prev_data = json.loads(reader.current_raw())
    except FileNotFoundError:
        pass
    except ValueError:
        if reader.manifest is not None:
            raise PublicationError("Committed current score JSON is invalid")
        # Preserve the legacy full-baseline rule; adoption retains these bytes.

    panel_data = userdata.get("profile", {})
    count_data = userdata.get("achievement", {})
    dojo_data = userdata.get("dojo", {})
    song_list = userdata.get("songs", [])

    song_list = merge_locked_songs(user_id, prev_data, song_list)
    userdata = {
        **userdata,
        "_meta": {
            **incoming_meta,
            "full": True,
            "ts": ts,
            "source": normalized_source,
            "source_account": source_account,
            "merge_topology": merge_topology,
            "schema_version": 2,
            "synced_at": now.isoformat(timespec="seconds"),
        },
        "profile": panel_data,
        "songs": song_list,
        "achievement": count_data,
        "dojo": dojo_data,
    }
    def _content_hash(value: Dict[str, Any]) -> str:
        normalized = dict(value)
        meta = dict(normalized.get("_meta") or {})
        meta.pop("content_sha256", None)
        normalized["_meta"] = meta
        canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    userdata["_meta"]["content_sha256"] = _content_hash(userdata)
    payload = json.dumps(userdata, ensure_ascii=False, indent=4)

    def _song_key(song):
        return (song.get("song_no"), song.get("level"))

    def _build_song_map(songs):
        song_map = {}
        for s in songs or []:
            song_map[_song_key(s)] = s
        return song_map

    def _has_full_snapshot() -> bool:
        for name in reader.history_names():
            try:
                snap = json.loads(reader.history_raw(name))
            except (ValueError, FileNotFoundError):
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

    snapshot_meta = {
        "full": False,
        "ts": ts,
        "source": normalized_source,
        "source_account": source_account,
        "merge_topology": merge_topology,
        "schema_version": 2,
        "synced_at": now.isoformat(timespec="seconds"),
    }
    delta_snapshot: Dict[str, Any] = {"_meta": snapshot_meta}
    if prev_data and isinstance(prev_data, dict):
        if not _has_full_snapshot():
            delta_snapshot = {
                "_meta": {**snapshot_meta, "full": True},
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
            "_meta": {**snapshot_meta, "full": True},
            "profile": panel_data,
            "achievement": count_data,
            "songs": song_list,
            "dojo": dojo_data,
        }

    delta_snapshot["_meta"]["content_sha256"] = _content_hash(delta_snapshot)
    store.commit({
        "current": payload.encode("utf-8"),
        "history/" + history_name: json.dumps(delta_snapshot, ensure_ascii=False, indent=4).encode("utf-8"),
    })

    # Persist the daily value at snapshot creation, before future model changes.
    # A chart failure must not turn a successfully saved score sync into a retry.
    try:
        from .daily_ability import capture_snapshot
        capture_snapshot(user_id, song_list, now, userdata_dir=store.root, publication_store=store)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Daily ability capture failed")
