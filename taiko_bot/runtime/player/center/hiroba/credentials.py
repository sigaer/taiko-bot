from __future__ import annotations
from taiko_bot.runtime.public.config import root as _runtime_root



import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from ..taiko_db import get_taiko_db_connection

HIROBA_TOKEN_DIR = Path(os.getenv("TAIKO_HIROBA_TOKEN_DIR") or str(_runtime_root() / 'secrets/hiroba_tokens'))


def _credential_pepper() -> str:
    return os.getenv("HIROBA_CRED_KEY", os.getenv("TAIKO_DB_PASSWORD", "taiko-hiroba-default-key"))


def _fernet() -> Fernet:
    pepper = _credential_pepper()
    digest = hashlib.sha256(pepper.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def ensure_hiroba_credentials_table() -> None:
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS web_hiroba_credentials (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                taiko_no VARCHAR(25) NOT NULL,
                email VARCHAR(255) NOT NULL,
                password_enc TEXT NOT NULL,
                configured_by_qq VARCHAR(191) DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_web_hiroba_credentials_taiko_no (taiko_no),
                KEY idx_web_hiroba_credentials_configured_by_qq (configured_by_qq)
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


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(password_enc: str) -> str:
    try:
        return _fernet().decrypt(password_enc.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt Hiroba password") from exc


def credential_request_fingerprint(email: str, password: str, target: str, principal: str) -> str:
    """Stable private retry proof. Never store a guessable plain password hash."""
    key = hashlib.sha256((_credential_pepper() + ":hiroba-intent-v1").encode("utf-8")).digest()
    value = json.dumps([email, password, target, principal], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def load_hiroba_credentials(taiko_no: str) -> Optional[Tuple[str, str]]:
    ensure_hiroba_credentials_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT email, password_enc
            FROM web_hiroba_credentials
            WHERE taiko_no=%s
            LIMIT 1
            """,
            (str(taiko_no),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return str(row[0]), decrypt_password(str(row[1]))
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def load_hiroba_credential_owner(taiko_no: str) -> Optional[str]:
    ensure_hiroba_credentials_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT configured_by_qq
            FROM web_hiroba_credentials
            WHERE taiko_no=%s
            LIMIT 1
            """,
            (str(taiko_no),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        owner = str(row[0] or "").strip()
        return owner or None
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def has_hiroba_credentials(taiko_no: str) -> bool:
    return load_hiroba_credentials(taiko_no) is not None


def save_hiroba_token(taiko_no: str, token: str) -> None:
    HIROBA_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    path = HIROBA_TOKEN_DIR / f"{taiko_no}.token"
    path.write_text(token.strip(), encoding="utf-8")


def load_hiroba_token(taiko_no: str) -> Optional[str]:
    path = HIROBA_TOKEN_DIR / f"{taiko_no}.token"
    if not path.exists():
        return None
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def delete_hiroba_token(taiko_no: str) -> None:
    path = HIROBA_TOKEN_DIR / f"{str(taiko_no).strip()}.token"
    try:
        path.unlink()
    except FileNotFoundError:
        pass
