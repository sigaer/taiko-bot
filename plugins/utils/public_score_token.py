from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import ensure_userdata_available, get_cached_userdata
from taiko_runtime.platform_adapter import ONEBOT_V11_PLATFORM, format_identity_for_display

from .taiko_db import ensure_schema, get_taiko_db_connection

USERDATA_DIR = get_settings().userdata_dir
TOKEN_BYTES = 24


@dataclass
class PublicScoreTokenError(Exception):
    status_code: int
    error: str
    message: str

    def __str__(self) -> str:
        return self.message


def ensure_public_score_token_table() -> None:
    ensure_schema()


def generate_public_score_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def mask_public_score_token(token: str) -> str:
    token = str(token or "").strip()
    if len(token) <= 14:
        return f"{token[:4]}****{token[-4:]}"
    return f"{token[:8]}...{token[-8:]}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).strip().encode("utf-8")).hexdigest()


def issue_public_score_token_for_taiko_id(taiko_id: str) -> Dict[str, Any]:
    ensure_public_score_token_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        normalized_taiko_id = str(taiko_id or "").strip()
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
        if row is None:
            raise PublicScoreTokenError(
                404,
                "binding_not_found",
                "当前鼓众ID没有 bot 侧绑定记录。",
            )

        owner_identity = str(row[0] or "").strip()
        resolved_taiko_id = str(row[1] or "").strip()
        token = generate_public_score_token()
        cursor.execute(
            """
            INSERT INTO public_score_tokens (taiko_id, token_hash, token_mask, last_used_at, updated_at)
            VALUES (%s, %s, %s, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(taiko_id)
            DO UPDATE SET
                token_hash=excluded.token_hash,
                token_mask=excluded.token_mask,
                last_used_at=NULL,
                updated_at=CURRENT_TIMESTAMP
            """,
            (resolved_taiko_id, _hash_token(token), mask_public_score_token(token)),
        )
        db.commit()
        return {
            "taiko_id": resolved_taiko_id,
            "owner_identity": owner_identity,
            "owner_display": format_identity_for_display(owner_identity),
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
            "UPDATE public_score_tokens SET last_used_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
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
    cached = get_cached_userdata(str(taiko_id))
    if isinstance(cached, dict):
        return cached
    path = USERDATA_DIR / f"{taiko_id}data.json"
    if not path.exists():
        raise PublicScoreTokenError(404, "userdata_missing", "本地成绩文件不存在。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise PublicScoreTokenError(500, "userdata_invalid", f"本地成绩文件损坏：{error}") from error


def fetch_latest_userdata_by_token(token: str) -> Dict[str, Any]:
    resolved = _resolve_token_binding(token)
    taiko_id = resolved["taiko_id"]
    local_payload: Optional[Dict[str, Any]] = None
    try:
        local_payload = _load_local_userdata(taiko_id)
    except PublicScoreTokenError:
        local_payload = None

    try:
        ensure_userdata_available(taiko_id, force_refresh=True)
    except Exception as error:
        if local_payload is None:
            raise PublicScoreTokenError(
                502, "update_failed", f"拉取中心成绩失败：{error}"
            ) from error

    return {
        "ok": True,
        "taikoId": taiko_id,
        "fetchedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "data": _load_local_userdata(taiko_id),
    }
