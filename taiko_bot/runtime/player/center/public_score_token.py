from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from taiko_store import PublicationError, PublicationStore
from taiko_store.reader import score_read_view

from .hiroba.client import HirobaError
from .hiroba.cooldown import peek_hiroba_sync_cooldown
from .hiroba.credentials import load_hiroba_credentials
from .hiroba.sync import sync_bound_hiroba_userdata
from .taiko_db import get_taiko_db_connection
from .update_user import getUserData

from taiko_bot.runtime.paths import root as _runtime_root
USERDATA_DIR = _runtime_root() / "userdata"
TOKEN_BYTES = 24


@dataclass
class PublicScoreTokenError(Exception):
    status_code: int
    error: str
    message: str

    def __str__(self) -> str:
        return self.message


def ensure_public_score_token_table() -> None:
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS public_score_tokens (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                taiko_id VARCHAR(25) NOT NULL,
                token_hash CHAR(64) NOT NULL,
                token_mask VARCHAR(32) NOT NULL,
                last_used_at DATETIME DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_public_score_tokens_taiko_id (taiko_id),
                UNIQUE KEY uniq_public_score_tokens_token_hash (token_hash),
                KEY idx_public_score_tokens_last_used_at (last_used_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        db.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def generate_public_score_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def mask_public_score_token(token: str) -> str:
    token = str(token or "").strip()
    if len(token) <= 14:
        return f"{token[:4]}****{token[-4:]}"
    return f"{token[:8]}...{token[-8:]}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).strip().encode("utf-8")).hexdigest()


def _serialize_token_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def get_public_score_token_status(taiko_id: str, *, identity_key: Optional[str] = None) -> Dict[str, Any]:
    from .score_token_authority import manage_bot_score_token
    return manage_bot_score_token(taiko_id, identity_key, "status")


def revoke_public_score_token_for_taiko_id(taiko_id: str, *, identity_key: Optional[str] = None) -> Dict[str, Any]:
    from .score_token_authority import manage_bot_score_token
    return manage_bot_score_token(taiko_id, identity_key, "revoke")


def issue_public_score_token_for_taiko_id(
    taiko_id: str, *, identity_key: Optional[str] = None, require_bot_binding: bool = True
) -> Dict[str, Any]:
    # An ownerless gateway call is never an authorization capability. The old
    # option remains a rejected argument for explicit rollback diagnostics.
    if not require_bot_binding:
        raise PublicScoreTokenError(403, "token_owner_required", "请使用自己的当前实账号管理成绩 token。")
    from .score_token_authority import manage_bot_score_token
    return manage_bot_score_token(taiko_id, identity_key, "issue")


def _normalize_bearer_token(token: str) -> str:
    normalized = token.strip() if isinstance(token, str) else ""
    if not normalized:
        raise PublicScoreTokenError(400, "invalid_token", "缺少 token。")
    if not re.fullmatch(r"[a-f0-9]{48}", normalized):
        raise PublicScoreTokenError(401, "invalid_token", "成绩查询 token 无效。")
    return normalized


def _resolve_token_binding(cursor, token_hash: str, *, lock: bool = False) -> Dict[str, Any]:
    cursor.execute(
        "SELECT id, taiko_id FROM public_score_tokens WHERE token_hash=%s LIMIT 1" + (" FOR UPDATE" if lock else ""),
        (token_hash,),
    )
    row = cursor.fetchone()
    if row is None:
        raise PublicScoreTokenError(401, "invalid_token", "成绩查询 token 无效。")
    taiko_id = row[1]
    if not isinstance(taiko_id, str) or not re.fullmatch(r"[0-9]{1,25}", taiko_id) or re.fullmatch(r"98[0-9]{16}", taiko_id):
        raise PublicScoreTokenError(401, "invalid_token", "成绩查询 token 无效。")
    return {"token_row_id": int(row[0]), "taiko_id": taiko_id}


def _require_token_binding(cursor, token_hash, expected):
    if _resolve_token_binding(cursor, token_hash, lock=True) != expected:
        raise PublicScoreTokenError(401, "invalid_token", "成绩查询 token 无效。")


def _userdata_root() -> Path:
    return Path(os.getenv("TAIKO_USERDATA_DIR") or USERDATA_DIR)


def _load_local_userdata(taiko_id: str, *, publication_store=None) -> Dict[str, Any]:
    def load(view):
        try:
            return json.loads(view.current_raw().decode("utf-8"))
        except FileNotFoundError:
            if view.manifest is not None and "current" in view.manifest["files"]:
                raise PublicationError("Canonical token score is unavailable") from None
            raise PublicScoreTokenError(404, "userdata_missing", "本地成绩文件不存在。") from None
        except (ValueError, UnicodeError, OSError):
            if view.manifest is not None:
                raise PublicationError("Canonical token score is unavailable") from None
            raise PublicScoreTokenError(500, "userdata_invalid", "本地成绩文件损坏。") from None
    try:
        if publication_store is not None:
            publication_store._require_lock(write=True)
            if publication_store.identity != taiko_id:
                raise PublicationError("Token score does not match its lease")
            return load(publication_store.reader())
        with score_read_view(_userdata_root(), taiko_id) as view:
            return load(view)
    except PublicationError:
        raise PublicScoreTokenError(503, "score_unavailable", "成绩服务暂时不可用，请稍后重试。") from None


def _resolve_local_userdata_source(payload: Dict[str, Any]) -> str:
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return ""
    source = str(meta.get("source") or "").strip().lower()
    return source if source in {"hiroba", "wahlap"} else ""


def _infer_public_token_source(
    taiko_id: str, local_payload: Optional[Dict[str, Any]]
) -> Tuple[str, Optional[Tuple[str, str]]]:
    if local_payload is not None:
        local_source = _resolve_local_userdata_source(local_payload)
        if local_source == "wahlap":
            return "wahlap", None

    creds = load_hiroba_credentials(taiko_id)
    if creds is not None:
        return "hiroba", creds

    if local_payload is not None:
        local_source = _resolve_local_userdata_source(local_payload)
        if local_source == "hiroba":
            return "hiroba", None

    return "wahlap", None


def _refresh_public_token_userdata(
    taiko_id: str,
    source: str,
    hiroba_creds: Optional[Tuple[str, str]],
    *,
    has_local_payload: bool,
    publication_store=None,
) -> None:
    if source == "hiroba":
        cooldown_msg = peek_hiroba_sync_cooldown(taiko_id)
        if cooldown_msg:
            return
        try:
            sync_bound_hiroba_userdata(
                taiko_id,
                email=hiroba_creds[0] if hiroba_creds else None,
                password=hiroba_creds[1] if hiroba_creds else None,
                publication_store=publication_store,
            )
        except PublicationError:
            raise
        except HirobaError as error:
            if has_local_payload:
                return
            raise PublicScoreTokenError(
                502, "update_failed", "拉取 Hiroba 成绩失败，请稍后重试。"
            ) from None
        except Exception as error:
            if has_local_payload:
                return
            raise PublicScoreTokenError(
                502, "update_failed", "拉取 Hiroba 成绩失败，请稍后重试。"
            ) from None
        return

    result = getUserData(taiko_id, publication_store=publication_store)
    if result == 404:
        raise PublicScoreTokenError(
            404, "user_not_found", "鼓众广场未找到该绑定 ID 的玩家成绩。"
        )
    if result != 0:
        raise PublicScoreTokenError(502, "update_failed", "拉取鼓众成绩失败，请稍后重试。")


def fetch_latest_userdata_by_token(token: str) -> Dict[str, Any]:
    normalized = _normalize_bearer_token(token)
    token_hash = _hash_token(normalized)
    db = None
    try:
        ensure_public_score_token_table()
        # Keep one captured SQL connection. The optimistic lookup has no private
        # file access; finish its snapshot before waiting for Source EX.
        db = get_taiko_db_connection()
        cursor = db.cursor()
    except Exception:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        raise PublicScoreTokenError(503, "score_unavailable", "成绩服务暂时不可用，请稍后重试。") from None
    try:
        resolved = _resolve_token_binding(cursor, token_hash)
        db.commit()
        taiko_id = resolved["taiko_id"]
        store = PublicationStore(_userdata_root(), taiko_id)
        with store.exclusive():
            db.begin()
            # The token row itself is the explicit Source grant. Pin that exact
            # id/hash/Source under EX, so revocation/rotation cannot finish in
            # the middle of an authenticated refresh or private DTO read.
            _require_token_binding(cursor, token_hash, resolved)
            local_payload: Optional[Dict[str, Any]] = None
            try:
                local_payload = _load_local_userdata(taiko_id, publication_store=store)
            except PublicScoreTokenError as error:
                if error.status_code not in (404, 500):
                    raise
            source, hiroba_creds = _infer_public_token_source(taiko_id, local_payload)
            _refresh_public_token_userdata(taiko_id, source, hiroba_creds,
                has_local_payload=local_payload is not None, publication_store=store)
            result = {"ok": True, "taikoId": taiko_id,
                "fetchedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "data": _load_local_userdata(taiko_id, publication_store=store)}
            _require_token_binding(cursor, token_hash, resolved)
            store._require_lock(write=True)
            cursor.execute("UPDATE public_score_tokens SET last_used_at=NOW() WHERE id=%s AND token_hash=%s AND taiko_id=%s",
                (resolved["token_row_id"], token_hash, taiko_id))
            db.commit()
            store._require_lock(write=True)
            return result
    except Exception as error:
        try:
            db.rollback()
        except Exception:
            try:
                db.close()
            except Exception:
                pass
        if isinstance(error, PublicScoreTokenError):
            raise
        raise PublicScoreTokenError(503, "score_unavailable", "成绩服务暂时不可用，请稍后重试。") from None
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
