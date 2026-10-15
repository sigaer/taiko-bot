from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from taiko_runtime.platform_adapter import ONEBOT_V11_PLATFORM, format_identity_for_display

from .hiroba.client import HirobaError
from .hiroba.cooldown import peek_hiroba_sync_cooldown
from .hiroba.credentials import load_hiroba_credentials
from .hiroba.sync import sync_bound_hiroba_userdata
from .taiko_db import get_taiko_db_connection
from .update_user import getUserData

USERDATA_DIR = Path("/home/sigaer/taiko/userdata")
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


def get_public_score_token_status(taiko_id: str) -> Dict[str, Any]:
    ensure_public_score_token_table()
    normalized_taiko_id = str(taiko_id or "").strip()
    if not normalized_taiko_id:
        raise PublicScoreTokenError(400, "invalid_taiko_id", "缺少鼓众 ID。")

    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT token_mask, last_used_at, created_at, updated_at
            FROM public_score_tokens
            WHERE taiko_id = %s
            LIMIT 1
            """,
            (normalized_taiko_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return {
                "taiko_id": normalized_taiko_id,
                "exists": False,
                "token_mask": None,
                "last_used_at": None,
                "created_at": None,
                "updated_at": None,
            }
        return {
            "taiko_id": normalized_taiko_id,
            "exists": True,
            "token_mask": str(row[0] or "").strip(),
            "last_used_at": _serialize_token_datetime(row[1]),
            "created_at": _serialize_token_datetime(row[2]),
            "updated_at": _serialize_token_datetime(row[3]),
        }
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def revoke_public_score_token_for_taiko_id(taiko_id: str) -> Dict[str, Any]:
    ensure_public_score_token_table()
    normalized_taiko_id = str(taiko_id or "").strip()
    if not normalized_taiko_id:
        raise PublicScoreTokenError(400, "invalid_taiko_id", "缺少鼓众 ID。")

    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "DELETE FROM public_score_tokens WHERE taiko_id = %s",
            (normalized_taiko_id,),
        )
        revoked = cursor.rowcount > 0
        db.commit()
        return {"taiko_id": normalized_taiko_id, "revoked": revoked}
    except Exception as error:
        try:
            db.rollback()
        except Exception:
            pass
        raise PublicScoreTokenError(500, "token_revoke_failed", f"撤销 token 失败：{error}") from error
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def issue_public_score_token_for_taiko_id(
    taiko_id: str, *, require_bot_binding: bool = True
) -> Dict[str, Any]:
    ensure_public_score_token_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        normalized_taiko_id = str(taiko_id or "").strip()
        row = None
        if require_bot_binding:
            cursor.execute(
                """
                SELECT qq, id
                FROM bind
                WHERE id = %s
                ORDER BY CASE WHEN qq LIKE %s THEN 0 ELSE 1 END, qq
                LIMIT 1
                """,
                (normalized_taiko_id, f"{ONEBOT_V11_PLATFORM}:%"),
            )
            row = cursor.fetchone()
        if require_bot_binding and row is None:
            raise PublicScoreTokenError(
                404,
                "binding_not_found",
                "当前鼓众ID没有 bot 侧绑定记录。",
            )

        owner_identity = str(row[0] or "").strip() if row else "viewer"
        resolved_taiko_id = str(row[1] or "").strip() if row else normalized_taiko_id
        token = generate_public_score_token()
        cursor.execute(
            """
            INSERT INTO public_score_tokens (taiko_id, token_hash, token_mask)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                token_hash = VALUES(token_hash),
                token_mask = VALUES(token_mask),
                last_used_at = NULL
            """,
            (resolved_taiko_id, _hash_token(token), mask_public_score_token(token)),
        )
        db.commit()
        return {
            "taiko_id": resolved_taiko_id,
            "owner_identity": owner_identity,
            "owner_display": (
                format_identity_for_display(owner_identity) if row else "Viewer 当前绑定"
            ),
            "token": token,
            "token_mask": mask_public_score_token(token),
        }
    except PublicScoreTokenError:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    except Exception as error:
        try:
            db.rollback()
        except Exception:
            pass
        raise PublicScoreTokenError(500, "token_issue_failed", f"生成 token 失败：{error}") from error
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _resolve_token_binding(token: str) -> Dict[str, Any]:
    ensure_public_score_token_table()
    normalized = str(token or "").strip()
    if not normalized:
        raise PublicScoreTokenError(400, "invalid_token", "缺少 token。")

    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT id, taiko_id
            FROM public_score_tokens
            WHERE token_hash = %s
            LIMIT 1
            """,
            (_hash_token(normalized),),
        )
        token_row = cursor.fetchone()
        if token_row is None:
            raise PublicScoreTokenError(401, "invalid_token", "成绩查询 token 无效。")

        token_row_id = int(token_row[0])
        taiko_id = str(token_row[1] or "").strip()

        cursor.execute(
            "UPDATE public_score_tokens SET last_used_at = NOW() WHERE id = %s",
            (token_row_id,),
        )
        db.commit()
        return {
            "token_row_id": token_row_id,
            "taiko_id": taiko_id,
        }
    except PublicScoreTokenError:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _load_local_userdata(taiko_id: str) -> Dict[str, Any]:
    path = USERDATA_DIR / f"{taiko_id}data.json"
    if not path.exists():
        raise PublicScoreTokenError(404, "userdata_missing", "本地成绩文件不存在。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise PublicScoreTokenError(500, "userdata_invalid", f"本地成绩文件损坏：{error}") from error


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
            )
        except HirobaError as error:
            if has_local_payload:
                return
            raise PublicScoreTokenError(
                502, "update_failed", f"拉取 Hiroba 成绩失败：{error}"
            ) from error
        except Exception as error:
            if has_local_payload:
                return
            raise PublicScoreTokenError(
                502, "update_failed", f"拉取 Hiroba 成绩失败：{error}"
            ) from error
        return

    result = getUserData(taiko_id)
    if result == 404:
        raise PublicScoreTokenError(
            404, "user_not_found", "鼓众广场未找到该绑定 ID 的玩家成绩。"
        )
    if result != 0:
        raise PublicScoreTokenError(502, "update_failed", "拉取鼓众成绩失败，请稍后重试。")


def fetch_latest_userdata_by_token(token: str) -> Dict[str, Any]:
    resolved = _resolve_token_binding(token)
    taiko_id = resolved["taiko_id"]
    local_payload: Optional[Dict[str, Any]] = None
    try:
        local_payload = _load_local_userdata(taiko_id)
    except PublicScoreTokenError:
        local_payload = None

    source, hiroba_creds = _infer_public_token_source(taiko_id, local_payload)
    _refresh_public_token_userdata(
        taiko_id,
        source,
        hiroba_creds,
        has_local_payload=local_payload is not None,
    )

    return {
        "ok": True,
        "taikoId": taiko_id,
        "fetchedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "data": _load_local_userdata(taiko_id),
    }
