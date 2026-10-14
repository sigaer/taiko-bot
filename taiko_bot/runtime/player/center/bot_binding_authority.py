"""SQL proof of an adapter-authenticated Bot caller's current real binding.

The caller supplies its own platform identity, never a mentioned/visible user.
Mutations acquire Source EX before these SQL locks. Bind rows precede virtual
selection state, matching the existing Bot selection and attachment lock order.
"""
from dataclasses import dataclass
import re


class BotBindingDenied(Exception):
    pass


def normalize_bot_principal(value):
    if not isinstance(value, str):
        raise BotBindingDenied()
    value = value.strip()
    if not re.fullmatch(r"(?:onebot_v11:[0-9]{1,128}|qq_official:[A-Za-z0-9_-]{1,128})", value):
        raise BotBindingDenied()
    return value


@dataclass(frozen=True)
class BotBindingIdentity:
    row_id: int
    principal: str
    taiko_id: str
    source: str
    slot_index: int
    is_current: int
    visible: int


def read_bot_current_binding(cursor, principal, *, lock=False):
    principal = normalize_bot_principal(principal)
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute(
        "SELECT row_id,qq,id,COALESCE(source,'wahlap'),slot_index,is_current,visible "
        "FROM bind WHERE qq=%s ORDER BY slot_index,row_id LIMIT 129" + suffix,
        (principal,),
    )
    rows = cursor.fetchall()
    if not rows or len(rows) > 128:
        raise BotBindingDenied()
    bindings = []
    for row in rows:
        # VARCHAR identities stay strings. Never silently coerce SQL numeric,
        # case-colliding principals, a foreign row or unsafe storage identity.
        row_id, key, taiko_id, source, slot, current, visible = row
        if key != principal or not isinstance(taiko_id, str) or not re.fullmatch(r"[0-9]{1,25}", taiko_id):
            raise BotBindingDenied()
        if type(row_id) is not int or row_id <= 0 or type(slot) is not int or not 0 < slot < 1_000_000:
            raise BotBindingDenied()
        if source not in {"wahlap", "hiroba", "manual"} or current not in (0, 1) or visible not in (0, 1):
            raise BotBindingDenied()
        bindings.append(BotBindingIdentity(row_id, key, taiko_id, source, slot, current, visible))
    if lock:
        # An absent-state SELECT may not take a gap lock at READ COMMITTED.
        # Materialize neutral legacy u1 before locking; never reset an existing
        # u0/current selection. This row rolls back with a denied grant.
        cursor.execute("""INSERT INTO taiko_bind_identity_state(identity_key,current_virtual) VALUES (%s,0)
            ON DUPLICATE KEY UPDATE identity_key=identity_key""", (principal,))
    cursor.execute("SELECT identity_key,current_virtual FROM taiko_bind_identity_state WHERE identity_key=%s" + suffix, (principal,))
    state = cursor.fetchone()
    if state is not None and (state[0] != principal or state[1] != 0):
        raise BotBindingDenied()
    selected = [binding for binding in bindings if binding.is_current]
    if len(selected) > 1:
        raise BotBindingDenied()
    return selected[0] if selected else bindings[0]


def require_bot_binding(cursor, principal, expected):
    actual = read_bot_current_binding(cursor, principal, lock=True)
    if actual != expected:
        raise BotBindingDenied()
    return actual
