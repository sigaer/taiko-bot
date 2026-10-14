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
