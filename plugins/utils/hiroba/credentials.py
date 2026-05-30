from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from taiko_bot.settings import get_settings

from ..taiko_db import ensure_schema, get_taiko_db_connection

HIROBA_TOKEN_DIR = get_settings().hiroba_token_dir


def _fernet() -> Fernet:
    pepper = os.getenv("HIROBA_CRED_KEY", "taiko-bot-hiroba-key")
    digest = hashlib.sha256(pepper.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def ensure_hiroba_credentials_table() -> None:
    ensure_schema()


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(password_enc: str) -> str:
    try:
        return _fernet().decrypt(password_enc.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt Hiroba password") from exc


def save_hiroba_credentials(
    taiko_no: str,
    email: str,
    password: str,
    *,
    configured_by_qq: Optional[str] = None,
) -> None:
    ensure_hiroba_credentials_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO web_hiroba_credentials (taiko_no, email, password_enc, configured_by_qq, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(taiko_no)
            DO UPDATE SET
                email=excluded.email,
                password_enc=excluded.password_enc,
                configured_by_qq=excluded.configured_by_qq,
                updated_at=CURRENT_TIMESTAMP
            """,
            (str(taiko_no), email.strip(), encrypt_password(password), configured_by_qq),
        )
        db.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


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


def delete_hiroba_credentials(taiko_no: str) -> None:
    ensure_hiroba_credentials_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            "DELETE FROM web_hiroba_credentials WHERE taiko_no=%s",
            (str(taiko_no),),
        )
        db.commit()
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
