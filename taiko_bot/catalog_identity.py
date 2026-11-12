"""Canonical song identity, owned by song_data.json's legacy_ids metadata.

Historical score bytes remain immutable. Consumers resolve their old song IDs
through the same catalog used by the importer and current chart lookups.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path


def identity_map(songs, *, allow_pending=False):
    current = {int(song["id"]) for song in songs}
    aliases = {}
    for song in songs:
        sid = int(song["id"])
        for old in song.get("legacy_ids", []):
            old = int(old)
            if old == sid:
                continue
            if old in aliases and aliases[old] != sid:
                raise ValueError("Ambiguous legacy song identity")
            if old in current and not allow_pending:
                raise ValueError("Legacy song ID is still a catalog entry")
            aliases[old] = sid
    for old in aliases:
        seen, target = {old}, aliases[old]
        while target in aliases:
            if target in seen:
                raise ValueError("Cyclic legacy song identity")
            seen.add(target)
            target = aliases[target]
        aliases[old] = target
    return aliases


@lru_cache(maxsize=1)
def _load_revision(path, revision):
    return identity_map(json.loads(Path(path).read_text(encoding="utf-8")))


def load_identity_map(catalog_path):
    path = Path(catalog_path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    import hashlib, time
    digest = hashlib.sha256(path.read_bytes()).digest() if time.time_ns()-stat.st_ctime_ns < 1_000_000_000 else None
    return _load_revision(str(path.resolve()), (stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns, digest))


def canonical_song_id(value, aliases):
    try:
        sid = int(value)
    except (TypeError, ValueError):
        return value
    return aliases.get(sid, sid)


def _score_key(row):
    # Keep the best actual attempt; do not synthesize scores or sum play counts.
    def number(key):
        try:
            return float(row.get(key) or 0)
        except (ValueError, TypeError):
            return 0
    return (number("high_score"), number("dondaful_combo_cnt"), number("full_combo_cnt"),
            number("clear_cnt"), number("good_cnt"), -number("bad_cnt"), number("play_cnt"))


def normalize_score_payload(payload, aliases):
    if not aliases or not isinstance(payload, dict):
        return payload
    rows = payload.get("songs")
    normalized = payload
    if isinstance(rows, list) and any(isinstance(row, dict) and row.get("song_no") is not None and
                                    canonical_song_id(row["song_no"], aliases) != canonical_song_id(row["song_no"], {})
                                    for row in rows):
        result, indices = [], {}
        for row in rows:
            if not isinstance(row, dict) or row.get("song_no") is None:
                result.append(row)
                continue
            sid = canonical_song_id(row["song_no"], aliases)
            updated = {**row, "song_no": sid} if sid != canonical_song_id(row["song_no"], {}) else row
            key = (sid, str(row.get("level")))
            if key in indices:
                index = indices[key]
                if _score_key(updated) > _score_key(result[index]):
                    result[index] = updated
            else:
                indices[key] = len(result)
                result.append(updated)
        normalized = {**payload, "songs": result}
    removed = payload.get("songs_removed")
    if isinstance(removed, list):
        converted = []
        for key in removed:
            if isinstance(key, (list, tuple)) and len(key) == 2:
                key = [canonical_song_id(key[0], aliases), key[1]]
            elif isinstance(key, dict) and "song_no" in key:
                key = {**key, "song_no": canonical_song_id(key["song_no"], aliases)}
            elif isinstance(key, str) and ":" in key:
                sid, level = key.split(":", 1)
                key = f"{canonical_song_id(sid, aliases)}:{level}"
            converted.append(key)
        if converted != removed:
            normalized = {**normalized, "songs_removed": converted}
    return normalized
