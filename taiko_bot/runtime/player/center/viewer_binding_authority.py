"""Current Viewer binding SQL proof for a trusted local application caller."""
import re
from dataclasses import dataclass


class ViewerBindingDenied(Exception):
    pass


@dataclass(frozen=True)
class ViewerBindingIdentity:
    id: str
    taiko_id: str
    source: str
    manual_account_id: object = None


def capture_viewer_binding(value):
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not re.fullmatch(r"[1-9][0-9]{0,19}", value["id"]):
        raise ViewerBindingDenied()
    identity = value.get("taiko_id")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9]{1,25}", identity):
        raise ViewerBindingDenied()
    if not isinstance(value.get("source"), str) or value["source"] not in {"wahlap", "hiroba", "manual"}:
        raise ViewerBindingDenied()
    manual = value.get("manual_account_id") or None
    if manual is not None and not isinstance(manual, str):
        raise ViewerBindingDenied()
    return ViewerBindingIdentity(value["id"], identity, value["source"], manual)


def require_viewer_current_binding(cursor, user_id, expected, *, lock=True):
    if type(user_id) is not int or not 0 < user_id <= 2**53 - 1:
        raise ViewerBindingDenied()
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute("SELECT id FROM web_user_accounts WHERE id=%s" + suffix, (user_id,))
    row = cursor.fetchone()
    if row is None or row[0] != user_id:
        raise ViewerBindingDenied()
    # Lock owner before all bindings, exactly matching Viewer authority order.
    cursor.execute("SELECT CAST(id AS CHAR),taiko_id,source,manual_account_id,is_current "
                   "FROM web_taiko_bindings WHERE user_id=%s ORDER BY id LIMIT 129" + suffix, (user_id,))
    rows = cursor.fetchall()
    if not rows or len(rows) > 128:
        raise ViewerBindingDenied()
    selected = next((row for row in rows if row[4]), rows[0])
    actual = capture_viewer_binding(dict(zip(("id", "taiko_id", "source", "manual_account_id"), selected[:4])))
    if actual != expected:
        raise ViewerBindingDenied()
    return actual
