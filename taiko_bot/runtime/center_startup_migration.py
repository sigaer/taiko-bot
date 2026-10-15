from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Tuple


from taiko_bot.runtime.center_platform_adapter import (
    ONEBOT_V11_PLATFORM,
    build_group_key,
    build_identity_key,
    parse_identity_key,
)
DEFAULT_MULTI_BIND_PATH = Path("/home/sigaer/taiko/data/taiko_multi_bind.json")
DEFAULT_FEATURE_SWITCH_DB_PATH = Path(
    "/usr/lib/python3.11/site-packages/feature_handler/data/switch.db"
)


def normalize_legacy_identity_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if ":" in normalized:
        return normalized
    return build_identity_key(ONEBOT_V11_PLATFORM, normalized)


def normalize_legacy_group_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if ":" in normalized:
        return normalized
    if not normalized.isdigit():
        return normalized
    return build_group_key(ONEBOT_V11_PLATFORM, normalized)


def _normalize_multi_bind_entry(payload: Any) -> Dict[str, Any]:
    ids = []
    if isinstance(payload, dict):
        raw_ids = payload.get("ids") or []
        current_index = int(payload.get("current_index") or 0)
        current_slot = int(payload.get("current_slot") or current_index + 1)
    else:
        raw_ids = []
        current_index = 0
        current_slot = 1
    seen = set()
    for raw_id in raw_ids:
        taiko_id = str(raw_id or "").strip()
        if not taiko_id or taiko_id in seen:
            continue
        seen.add(taiko_id)
        ids.append(taiko_id)
    if ids:
        current_index = min(max(current_index, 0), len(ids) - 1)
    else:
        current_index = 0
    if len(ids) < 2:
        current_slot = 1
    else:
        current_slot = min(max(current_slot, 0), len(ids))
    sources = payload.get("sources") if isinstance(payload, dict) else {}
    if not isinstance(sources, dict):
        sources = {}
    cleaned_sources = {
        str(taiko_id): str(source)
        for taiko_id, source in sources.items()
        if str(taiko_id) in ids and str(source).strip()
    }
    return {
        "ids": ids,
        "current_index": current_index,
        "current_slot": current_slot,
        "sources": cleaned_sources,
    }


def _merge_multi_bind_entries(
    primary: Dict[str, Any], secondary: Dict[str, Any]
) -> Dict[str, Any]:
    primary_entry = _normalize_multi_bind_entry(primary)
    secondary_entry = _normalize_multi_bind_entry(secondary)
    ids = list(primary_entry["ids"])
    for taiko_id in secondary_entry["ids"]:
        if taiko_id not in ids:
            ids.append(taiko_id)
    current_index = min(primary_entry["current_index"], max(len(ids) - 1, 0))
    current_slot = primary_entry.get("current_slot", current_index + 1)
    if len(ids) < 2:
        current_slot = 1
    else:
        current_slot = min(max(int(current_slot or 0), 0), len(ids))
    sources = dict(primary_entry.get("sources") or {})
    for taiko_id, source in (secondary_entry.get("sources") or {}).items():
        if taiko_id in ids and taiko_id not in sources:
            sources[taiko_id] = source
    return {
        "ids": ids,
        "current_index": current_index,
        "current_slot": current_slot,
        "sources": sources,
    }


def migrate_multi_bind_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    migrated: Dict[str, Any] = {}
    stats = {"migrated": 0, "merged": 0}
    ordered_items = sorted(
        payload.items(),
        key=lambda item: 0 if str(item[0] or "").strip().count(":") else 1,
    )
    for raw_key, raw_entry in ordered_items:
        source_key = str(raw_key or "").strip()
        if not source_key:
            continue
        target_key = normalize_legacy_identity_key(source_key)
        normalized_entry = _normalize_multi_bind_entry(raw_entry)
        if target_key != source_key:
            stats["migrated"] += 1
        if target_key in migrated:
            migrated[target_key] = _merge_multi_bind_entries(
                migrated[target_key], normalized_entry
            )
            stats["merged"] += 1
            continue
        migrated[target_key] = normalized_entry
    return migrated, stats


def migrate_feature_switch_db(path: Path = DEFAULT_FEATURE_SWITCH_DB_PATH) -> Dict[str, int]:
    if not path.exists():
        return {"migrated": 0, "merged": 0}

    conn = sqlite3.connect(path)
    stats = {"migrated": 0, "merged": 0}
    try:
        rows = conn.execute(
            "SELECT group_id, feature, enabled, updated_at FROM feature_switch"
        ).fetchall()
        for group_id, feature, enabled, updated_at in rows:
            source_key = str(group_id or "").strip()
            target_key = normalize_legacy_group_key(source_key)
            if not source_key or target_key == source_key:
                continue

            existing = conn.execute(
                "SELECT enabled, updated_at FROM feature_switch WHERE group_id=? AND feature=?",
                (target_key, feature),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "UPDATE feature_switch SET group_id=? WHERE group_id=? AND feature=?",
                    (target_key, source_key, feature),
                )
                stats["migrated"] += 1
                continue

            next_enabled = int(existing[0])
            next_updated_at = max(int(existing[1] or 0), int(updated_at or 0))
            conn.execute(
                "UPDATE feature_switch SET enabled=?, updated_at=? WHERE group_id=? AND feature=?",
                (next_enabled, next_updated_at, target_key, feature),
            )
            conn.execute(
                "DELETE FROM feature_switch WHERE group_id=? AND feature=?",
                (source_key, feature),
            )
            stats["merged"] += 1
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
