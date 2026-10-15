from __future__ import annotations

def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""

def _load_multi_bind_store() -> Dict[str, Dict[str, Any]]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """select b.qq, b.id, coalesce(b.slot_index, 1),
                      coalesce(b.is_current, 0), coalesce(b.source, 'wahlap'),
                      coalesce(s.current_virtual, 0)
                 from bind b
                 left join taiko_bind_identity_state s
                   on cast(s.identity_key as binary)=cast(b.qq as binary)
                order by b.qq, b.slot_index, b.row_id"""
        )
        cleaned: Dict[str, Dict[str, Any]] = {}
        for qq, taiko_id, slot_index, is_current, source, current_virtual in cursor.fetchall():
            key = _normalize_identity_key(str(qq or "").strip())
            taiko_id = str(taiko_id or "").strip()
            if not key or not taiko_id:
                continue
            entry = cleaned.setdefault(
                key,
                {"ids": [], "current_index": 0, "current_slot": 1, "sources": {}},
            )
            entry["ids"].append(taiko_id)
            entry["sources"][taiko_id] = str(source or "wahlap")
            if int(is_current or 0):
                entry["current_index"] = len(entry["ids"]) - 1
            if int(current_virtual or 0):
                entry["current_slot"] = 0
        for entry in cleaned.values():
            if entry.get("current_slot") != 0:
                entry["current_slot"] = int(entry.get("current_index", 0)) + 1
        return cleaned
    finally:
        cursor.close()
        db.close()
