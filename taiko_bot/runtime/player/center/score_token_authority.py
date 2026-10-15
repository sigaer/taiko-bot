from __future__ import annotations


import re

from .messages import format_identity_for_display

from taiko_store import PublicationStore

from .bot_binding_authority import BotBindingDenied, normalize_bot_principal, read_bot_current_binding, require_bot_binding

from . import public_score_token as tokens

def _denied():
    return tokens.PublicScoreTokenError(403, "token_owner_required", "请使用自己的当前实账号管理成绩 token。")

def _unavailable():
    return tokens.PublicScoreTokenError(503, "token_unavailable", "成绩 token 服务暂时不可用，请稍后重试。")

def _external(binding, requested):
    if binding.taiko_id != requested:
        raise BotBindingDenied()
    if binding.source not in {"wahlap", "hiroba"} or re.fullmatch(r"98[0-9]{16}", requested):
        raise tokens.PublicScoreTokenError(400, "token_source_unsupported", "手动账号不支持网页成绩 token。")

def _status(cursor, identity):
    cursor.execute("SELECT id,token_hash,token_mask,last_used_at,created_at,updated_at FROM public_score_tokens WHERE taiko_id=%s LIMIT 1 FOR UPDATE", (identity,))
    row = cursor.fetchone()
    status = {"taiko_id": identity, "exists": row is not None, "token_mask": str(row[2] or "").strip() if row else None,
              "last_used_at": tokens._serialize_token_datetime(row[3]) if row else None,
              "created_at": tokens._serialize_token_datetime(row[4]) if row else None,
              "updated_at": tokens._serialize_token_datetime(row[5]) if row else None}
    return status, tuple(row) if row is not None else None

def _close(connection, cursor=None):
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass

def _rollback(connection):
    if connection is not None:
        try:
            connection.rollback()
        except Exception:
            # A failed rollback cannot leave an owner/token lock in circulation.
            _close(connection)

def _prove_uncertain_commit(factory, store, principal, expected, outcome):
    connection = cursor = None
    try:
        store._require_lock(write=True)
        connection = factory()
        cursor = connection.cursor()
        connection.begin()
        require_bot_binding(cursor, principal, expected)
        _, row = _status(cursor, expected.taiko_id)
        if row != outcome:
            raise _unavailable()
        store._require_lock(write=True)
        connection.commit()
        store._require_lock(write=True)
    except Exception:
        _rollback(connection)
        raise _unavailable() from None
    finally:
        _close(connection, cursor)

def manage_bot_score_token(taiko_id, principal, action):
    if not isinstance(taiko_id, str) or not re.fullmatch(r"[0-9]{1,25}", taiko_id.strip()):
        raise tokens.PublicScoreTokenError(400, "invalid_taiko_id", "鼓众 ID 无效。")
    identity = taiko_id.strip()
    try:
        principal = normalize_bot_principal(principal)
    except BotBindingDenied:
        raise _denied() from None
    if action not in {"issue", "revoke", "status"}:
        raise tokens.PublicScoreTokenError(400, "invalid_action", "不支持的 token 管理操作。")
    # Capture the factory and its actual connection before waiting for Source.
    # The initial read transaction ends before EX; SQL locks never precede it.
    factory = tokens.get_taiko_db_connection
    connection = cursor = None
    try:
        tokens.ensure_public_score_token_table()
        connection = factory()
        cursor = connection.cursor()
        expected = read_bot_current_binding(cursor, principal)
        _external(expected, identity)
        connection.commit()
        store = PublicationStore(tokens._userdata_root(), identity)
        with store.exclusive():
            prepared = None
            attempted = False
            try:
                connection.begin()
                require_bot_binding(cursor, principal, expected)
                _external(expected, identity)
                store._require_lock(write=True)
                if action == "issue":
                    token = tokens.generate_public_score_token()
                    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{48}", token):
                        raise _unavailable()
                    cursor.execute("""INSERT INTO public_score_tokens (taiko_id,token_hash,token_mask) VALUES (%s,%s,%s)
                        ON DUPLICATE KEY UPDATE token_hash=VALUES(token_hash),token_mask=VALUES(token_mask),last_used_at=NULL""",
                        (identity, tokens._hash_token(token), tokens.mask_public_score_token(token)))
                    result = {"taiko_id": identity, "owner_identity": principal, "owner_display": format_identity_for_display(principal),
                              "token": token, "token_mask": tokens.mask_public_score_token(token)}
                elif action == "revoke":
                    cursor.execute("DELETE FROM public_score_tokens WHERE taiko_id=%s", (identity,))
                    result = {"taiko_id": identity, "revoked": cursor.rowcount > 0}
                status, outcome = _status(cursor, identity)
                if action == "status":
                    result = status
                elif action == "issue" and (outcome is None or outcome[1] != tokens._hash_token(token) or outcome[2] != result["token_mask"] or outcome[3] is not None):
                    raise _unavailable()
                elif action == "revoke" and outcome is not None:
                    raise _unavailable()
                require_bot_binding(cursor, principal, expected)
                store._require_lock(write=True)
                prepared = result
                attempted = True
                connection.commit()
                store._require_lock(write=True)
                return result
            except Exception:
                _rollback(connection)
                if attempted and prepared is not None:
                    _prove_uncertain_commit(factory, store, principal, expected, outcome)
                    return prepared
                raise
    except BotBindingDenied:
        _rollback(connection)
        raise _denied() from None
    except tokens.PublicScoreTokenError:
        _rollback(connection)
        raise
    except Exception:
        _rollback(connection)
        raise _unavailable() from None
    finally:
        _close(connection, cursor)
