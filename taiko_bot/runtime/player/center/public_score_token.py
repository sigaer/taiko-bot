from __future__ import annotations
from taiko_bot.runtime.public.config import root as _runtime_root



from dataclasses import dataclass

from typing import Any, Dict, Optional, Tuple

@dataclass
class PublicScoreTokenError(Exception):
    status_code: int
    error: str
    message: str

    def __str__(self) -> str:
        return self.message

def issue_public_score_token_for_taiko_id(
    taiko_id: str, *, identity_key: Optional[str] = None, require_bot_binding: bool = True
) -> Dict[str, Any]:
    # An ownerless gateway call is never an authorization capability. The old
    # option remains a rejected argument for explicit rollback diagnostics.
    if not require_bot_binding:
        raise PublicScoreTokenError(403, "token_owner_required", "请使用自己的当前实账号管理成绩 token。")
    from .score_token_authority import manage_bot_score_token
    return manage_bot_score_token(taiko_id, identity_key, "issue")


import hashlib

import os

import secrets

from datetime import datetime

from pathlib import Path

from .taiko_db import get_taiko_db_connection

USERDATA_DIR = Path(str(_runtime_root() / 'userdata'))

TOKEN_BYTES = 24

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

def _userdata_root() -> Path:
    return Path(os.getenv("TAIKO_USERDATA_DIR") or USERDATA_DIR)
