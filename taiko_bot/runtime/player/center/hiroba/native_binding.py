from __future__ import annotations


from dataclasses import dataclass

import re

from uuid import uuid4

from ..bot_binding_authority import normalize_bot_principal

from ..bot_binding_mutation import _read, _apply, principal_lock_name

from ..source_mutation import AuthorizedPublicationStore

from .private_credentials import run_private_credentials

from .credentials import decrypt_password

class NativeHirobaUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Hiroba 服务暂不可用，请稍后重试。")

class NativeHirobaDenied(ValueError):
    def __init__(self):
        super().__init__("请使用自己的 Hiroba 实账号绑定和更新。")

class NativeHirobaCredentialUnavailable(NativeHirobaUnavailable):
    def __init__(self):
        RuntimeError.__init__(self, "Hiroba 凭据无法读取，请重新绑定该账号后再更新。")

@dataclass(frozen=True)
class NativeHirobaBinding:
    taiko_ids: tuple[str, ...]
    entry: dict

def _principal(value):
    if not isinstance(value, str) or value != value.strip():
        raise NativeHirobaDenied()
    try:
        return normalize_bot_principal(value)
    except Exception:
        raise NativeHirobaDenied() from None

def _gate(cursor, principal):
    cursor.execute("SELECT GET_LOCK(%s,5)", (principal_lock_name(principal),))
    if cursor.fetchone() != (1,):
        raise NativeHirobaUnavailable()

def _close(connection, cursor, principal):
    if cursor is not None:
        try: cursor.execute("SELECT RELEASE_LOCK(%s)", (principal_lock_name(principal),))
        except Exception: pass
        try: cursor.close()
        except Exception: pass
    if connection is not None:
        try: connection.close()
        except Exception: pass

def _credentials(cursor, identity, *, locked):
    cursor.execute("""SELECT email,password_enc,configured_by_qq FROM web_hiroba_credentials
        WHERE taiko_no=%s LIMIT 1""" + (" FOR UPDATE" if locked else ""), (identity,))
    row = cursor.fetchone()
    if row is not None and (len(row) != 3 or not isinstance(row[0], str) or not 0 < len(row[0].encode()) <= 255
            or not isinstance(row[1], str) or not 0 < len(row[1].encode()) <= 8192
            or (row[2] is not None and (not isinstance(row[2], str) or len(row[2]) > 191))):
        raise NativeHirobaUnavailable()
    return row

def bind_native_hiroba(principal, email, password, *, target="", connection_factory, discovery=None):
    principal = _principal(principal)
    connection = cursor = None
    try:
        found = run_private_credentials(dict(operationId=uuid4().hex, mode="discover", email=email,
            password=password, target=target, principal=principal), discovery=discovery)
        identities = tuple(found["taikoIds"])
        if not identities:
            raise NativeHirobaDenied()
        connection = connection_factory(); cursor = connection.cursor(); _gate(cursor, principal)
        connection.begin(); rows, virtual = _read(cursor, principal)
        if len(set(row.identity for row in rows) | set(identities)) > 128:
            raise NativeHirobaDenied()
        # Match the center credential lock order; card/display order remains
        # unchanged for slot allocation and preferred selection below.
        for identity in sorted(identities):
            _credentials(cursor, identity, locked=True)
        for identity in sorted(identities):
            cursor.execute("""INSERT INTO web_hiroba_credentials(taiko_no,email,password_enc,configured_by_qq)
                VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE email=VALUES(email),password_enc=VALUES(password_enc),
                configured_by_qq=VALUES(configured_by_qq),updated_at=CURRENT_TIMESTAMP""",
                (identity, email, found["passwordEnc"], principal))
        for identity in identities:
            _apply(cursor, principal, rows, virtual, "upsert", identity, "hiroba", False)
            rows, virtual = _read(cursor, principal)
        preferred = identities[0]
        result = _apply(cursor, principal, rows, virtual, "switch",
            next(index+1 for index, row in enumerate(rows) if row.identity == preferred), None, False)
        for identity in identities:
            if _credentials(cursor, identity, locked=True) != (email, found["passwordEnc"], principal):
                raise NativeHirobaUnavailable()
        connection.commit()
        return NativeHirobaBinding(identities, result.entry)
    except Exception as error:
        if connection is not None:
            try: connection.rollback()
            except Exception: pass
        if isinstance(error, NativeHirobaDenied):
            raise
        # Unknown COMMIT is never automatically replayed or falsely reported
        # as a rollback; caller can query its current binding before retrying.
        raise NativeHirobaUnavailable() from None
    finally:
        _close(connection, cursor, principal)

def sync_native_hiroba(principal, identity, *, connection_factory, userdata_root,
        current_only=True, include_image=False, show_all=False, progress=None, sync=None, render=None):
    principal = _principal(principal)
    if (not isinstance(identity, str) or not re.fullmatch(r"[0-9]{1,25}", identity)
            or re.fullmatch(r"98[0-9]{16}", identity)):
        raise NativeHirobaDenied()
    connection = cursor = None
    try:
        connection = connection_factory(); cursor = connection.cursor()
        rows, virtual = _read(cursor, principal, locked=False)
        expected = next((row for row in rows if row.identity == identity and row.source == "hiroba"), None)
        selected = next((row for row in rows if row.current), rows[0] if rows else None)
        if expected is None or (current_only and (virtual or selected != expected)):
            raise NativeHirobaDenied()
        credentials = _credentials(cursor, identity, locked=False)
        connection.commit()
        store = AuthorizedPublicationStore(userdata_root, identity)
        with store.exclusive():
            _gate(cursor, principal); connection.begin()
            def prove():
                store._require_lock(write=True)
                actual, active_virtual = _read(cursor, principal)
                target = next((row for row in actual if row.identity == identity), None)
                selected = next((row for row in actual if row.current), actual[0] if actual else None)
                if (target != expected or (current_only and (active_virtual or selected != target))
                        or _credentials(cursor, identity, locked=True) != credentials):
                    raise NativeHirobaDenied()
            store.authorize = prove; prove()
            # A public/profile binding is not authority to borrow another
            # principal's global login. Preserve public synchronization there.
            email, password = None, None
            if credentials and credentials[2] == principal:
                try:
                    password = decrypt_password(credentials[1])
                except Exception:
                    raise NativeHirobaCredentialUnavailable() from None
                email = credentials[0]
            if sync is None:
                from .sync import sync_bound_hiroba_userdata
                sync = sync_bound_hiroba_userdata
            if sync(identity, email=email, password=password, progress=progress, publication_store=store) != identity:
                raise NativeHirobaUnavailable()
            prove(); image = None
            if include_image:
                try:
                    if render is None:
                        from ..draw_dress import render_update_changes_image
                        render = render_update_changes_image
                    image = render(int(identity), show_all=show_all, score_view=store.reader())
                    if not isinstance(image, bytes) or not 0 < len(image) <= 16*1024**2:
                        image = None
                except Exception:
                    image = None  # Existing product permits text-only success.
            prove(); connection.commit(); store._require_lock(write=True)
            return {"ok": True, "message": "Hiroba 更新成功！", "image": image}
    except Exception as error:
        if connection is not None:
            try: connection.rollback()
            except Exception: pass
        if isinstance(error, (NativeHirobaDenied, NativeHirobaCredentialUnavailable)):
            raise
        raise NativeHirobaUnavailable() from None
    finally:
        _close(connection, cursor, principal)
