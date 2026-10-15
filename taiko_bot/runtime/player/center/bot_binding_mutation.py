from dataclasses import dataclass
import re
class BotBindingMutationUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("绑定服务暂不可用，请稍后重试。")


@dataclass(frozen=True)
class _Row:
    row_id: int
    principal: str
    identity: str
    slot: int
    current: int
    source: str
    visible: int


def _read(cursor, principal, *, locked=True):
    # Retain the indexed collation match and reject a case-colliding foreign
    # row explicitly. An empty binary-only read could then overwrite its state
    # through an older case-insensitive UNIQUE key.
    cursor.execute("""SELECT row_id,qq,id,slot_index,is_current,COALESCE(source,'wahlap'),visible
        FROM bind WHERE qq=%s ORDER BY slot_index,row_id LIMIT 129""" + (" FOR UPDATE" if locked else ""), (principal,))
    records = cursor.fetchall()
    if len(records) > 128:
        raise BotBindingMutationUnavailable()
    rows, identities, slots = [], set(), set()
    for record in records:
        if len(record) != 7:
            raise BotBindingMutationUnavailable()
        row = _Row(*record)
        if (row.principal != principal or type(row.row_id) is not int or row.row_id <= 0
                or not isinstance(row.identity, str) or not re.fullmatch(r"[0-9]{1,25}", row.identity)
                or type(row.slot) is not int or not 0 < row.slot < 1_000_000
                or row.current not in (0, 1) or row.visible not in (0, 1)
                or row.source not in {"wahlap", "hiroba", "manual"}
                or (row.source == "manual") != bool(re.fullmatch(r"98[0-9]{16}", row.identity))
                or row.identity in identities or row.slot in slots):
            raise BotBindingMutationUnavailable()
        identities.add(row.identity)
        slots.add(row.slot)
        rows.append(row)
    if sum(row.current for row in rows) > 1:
        raise BotBindingMutationUnavailable()
    cursor.execute("""SELECT identity_key,current_virtual FROM taiko_bind_identity_state
        WHERE identity_key=%s LIMIT 1""" + (" FOR UPDATE" if locked else ""), (principal,))
    state = cursor.fetchone()
    if state is not None and (state[0] != principal or state[1] not in (0, 1)):
        raise BotBindingMutationUnavailable()
    return rows, bool(state and state[1])


def _entry(rows, virtual):
    if not rows:
        return None
    index = next((i for i, row in enumerate(rows) if row.current), 0)
    return {"ids": [row.identity for row in rows], "current_index": index,
            "current_slot": 0 if virtual and len(rows) >= 2 else index + 1,
            "sources": {row.identity: row.source for row in rows}}


import hashlib

import json

from .bot_binding_authority import BotBindingDenied, normalize_bot_principal

class BotBindingMutationRejected(ValueError):
    def __init__(self, reason, message=""):
        self.reason = reason
        super().__init__(message)

@dataclass(frozen=True)
class BotBindingMutationResult:
    entry: dict | None
    target_id: str = ""
    first_binding: bool = False
    added: bool = False
    matched: int = 0

def principal_lock_name(principal):
    # Exactly sha256(JSON.stringify(principal)), also used by the Node adapter.
    value = json.dumps(principal, ensure_ascii=False, separators=(",", ":"))
    return "taiko-bind-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:52]

def _state(cursor, principal, virtual):
    cursor.execute("""INSERT INTO taiko_bind_identity_state(identity_key,current_virtual)
        VALUES (%s,%s) ON DUPLICATE KEY UPDATE current_virtual=VALUES(current_virtual)""", (principal, int(virtual)))

def resolve_remove_target(entry, target):
    ids = list((entry or {}).get("ids") or [])
    if not ids:
        raise ValueError("当前没有可删除的鼓众广场ID。")
    index = max(0, min(int(entry.get("current_index", 0) or 0), len(ids)-1))
    target = str(target or "").strip()
    if not target:
        return index, ids[index]
    slot = re.fullmatch(r"[uU]([1-9]\d*)", target)
    if slot:
        index = int(slot.group(1))-1
        if index >= len(ids):
            raise ValueError(f"当前仅已绑定 u1~u{len(ids)}。")
        return index, ids[index]
    if target in ids:
        return ids.index(target), target
    if target.isdigit():
        raise ValueError("当前未绑定该鼓众广场ID。")
    raise ValueError("参数错误，请使用 删除绑定 / 删除绑定 u2 / 删除绑定 123456 这类形式。")

def _apply(cursor, principal, rows, virtual, action, value, source, force_last):
    predicate = "qq=%s AND CAST(qq AS BINARY)=CAST(%s AS BINARY)"
    params = (principal, principal)
    target_id, first, added, matched = "", False, False, 0
    if action == "upsert":
        existing = next((row for row in rows if row.identity == value), None)
        if existing and existing.source == "manual":
            raise BotBindingMutationRejected("manual", "手动账号必须通过创建或认领接口绑定。")
        first, added, target_id = not rows, existing is None, value
        if existing is None:
            if len(rows) >= 128:
                raise BotBindingMutationRejected("capacity", "绑定数量已达上限。")
            used = {row.slot for row in rows}
            slot = next(slot for slot in range(1, 130) if slot not in used)
            cursor.execute("""INSERT INTO bind(qq,id,visible,slot_index,is_current,source)
                VALUES (%s,%s,0,%s,0,%s)""", (principal, value, slot, source))
        else:
            cursor.execute("UPDATE bind SET source=%s WHERE row_id=%s", (source, existing.row_id))
        cursor.execute("UPDATE bind SET is_current=0 WHERE " + predicate, params)
        cursor.execute("UPDATE bind SET is_current=1 WHERE " + predicate + " AND id=%s", params+(value,))
        _state(cursor, principal, False)
    elif action == "switch":
        if not rows:
            raise BotBindingMutationRejected("empty")
        # Source's frozen native profile permits a manual member in u0. This
        # is deliberately distinct from the client's external-only profile.
        if value == 0:
            if len(rows) < 2:
                raise BotBindingMutationRejected("virtual", "当前至少需要绑定 2 个账号后才能切换到 u0。")
        else:
            if not 1 <= value <= len(rows):
                start = 0 if len(rows) >= 2 else 1
                raise BotBindingMutationRejected("slot", f"当前仅已绑定 u{start}~u{len(rows)}。")
            row = rows[value-1]
            target_id = row.identity
            cursor.execute("UPDATE bind SET is_current=0 WHERE " + predicate, params)
            cursor.execute("UPDATE bind SET is_current=1 WHERE row_id=%s", (row.row_id,))
        _state(cursor, principal, value == 0)
    elif action == "remove":
        if not rows:
            raise BotBindingMutationRejected("empty")
        try:
            index, target_id = resolve_remove_target(_entry(rows, virtual), value)
        except ValueError as error:
            raise BotBindingMutationRejected("target", str(error)) from None
        if len(rows) == 1 and not force_last:
            raise BotBindingMutationRejected("confirm", target_id)
        removed = rows[index]
        if removed.source == "manual":
            raise BotBindingMutationRejected("manual", "手动账号请使用“解绑空白账号”或“永久删除空白账号”。")
        if removed.source == "hiroba":
            # Same transaction; a foreign/legacy owner is preserved. Never
            # delete somebody else's global Source credential by public ID.
            cursor.execute("""DELETE FROM web_hiroba_credentials WHERE taiko_no=%s
                AND configured_by_qq=%s AND CAST(configured_by_qq AS BINARY)=CAST(%s AS BINARY)""",
                (target_id, principal, principal))
        cursor.execute("DELETE FROM bind WHERE row_id=%s", (removed.row_id,))
        remaining = [row for row in rows if row.row_id != removed.row_id]
        if remaining:
            # A fixed +1000 offset may collide with existing/gapped slots.
            # Move above the proven maximum, then preserve the frozen order.
            offset = max(row.slot for row in remaining)+len(remaining)+1
            cursor.execute("UPDATE bind SET slot_index=slot_index+%s WHERE " + predicate, (offset,)+params)
            selected = next((row for row in remaining if row.current), remaining[0])
            for slot, row in enumerate(remaining, 1):
                cursor.execute("UPDATE bind SET slot_index=%s,is_current=%s WHERE row_id=%s",
                               (slot, int(row.row_id == selected.row_id), row.row_id))
            _state(cursor, principal, virtual and len(remaining) >= 2)
        else:
            cursor.execute("DELETE FROM taiko_bind_identity_state WHERE identity_key=%s AND CAST(identity_key AS BINARY)=CAST(%s AS BINARY)", params)
    else:
        matched = len(rows)
        if rows:
            cursor.execute("UPDATE bind SET visible=%s WHERE " + predicate, (value,)+params)
    final, final_virtual = _read(cursor, principal)
    return BotBindingMutationResult(_entry(final, final_virtual), target_id, first, added, matched)

def mutate_bot_binding(principal, action, *, value=None, source=None, force_last=False, connection_factory):
    try:
        if not isinstance(principal, str) or principal != principal.strip():
            raise BotBindingDenied()
        principal = normalize_bot_principal(principal)
    except BotBindingDenied:
        raise BotBindingMutationUnavailable() from None
    if action not in {"upsert", "switch", "remove", "visibility"}:
        raise BotBindingMutationUnavailable()
    if action == "upsert" and (not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,25}", value)
                               or re.fullmatch(r"98[0-9]{16}", value) or source not in {"wahlap", "hiroba"}):
        raise BotBindingMutationRejected("input", "绑定账号或来源无效。")
    if action == "switch" and (type(value) is not int or not 0 <= value < 1_000_000):
        raise BotBindingMutationRejected("input", "槽位无效。")
    if action == "visibility" and (type(value) is not int or value not in (0, 1)):
        raise BotBindingMutationRejected("input", "可见性无效。")
    if action == "remove" and (not isinstance(value, str) or len(value) > 128 or type(force_last) is not bool
                               or (force_last and not re.fullmatch(r"[0-9]{1,25}", value))):
        raise BotBindingMutationRejected("input", "删除参数无效。")
    connection = cursor = None
    name = principal_lock_name(principal)
    acquired = False
    try:
        connection = connection_factory()
        cursor = connection.cursor()
        cursor.execute("SELECT GET_LOCK(%s,5)", (name,))
        if cursor.fetchone() != (1,):
            raise BotBindingMutationUnavailable()
        acquired = True
        connection.begin()
        rows, virtual = _read(cursor, principal)
        result = _apply(cursor, principal, rows, virtual, action, value, source, force_last)
        connection.commit()
        return result
    except Exception as error:
        if connection is not None:
            try: connection.rollback()
            except Exception: pass  # Always close: this connection is never pooled.
        if isinstance(error, BotBindingMutationRejected):
            raise
        # An uncertain COMMIT is not reported as success or automatically
        # retried (especially positional deletion). No private SQL diagnostics.
        raise BotBindingMutationUnavailable() from None
    finally:
        if acquired and cursor is not None:
            try: cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
            except Exception: pass
        if cursor is not None:
            try: cursor.close()
            except Exception: pass
        if connection is not None:
            try: connection.close()
            except Exception: pass
