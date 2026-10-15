from __future__ import annotations


import base64

import hashlib

import os

from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from taiko_bot.sqlite_db import ensure_schema, get_taiko_db_connection

def _fernet() -> Fernet:
    pepper = os.getenv("HIROBA_CRED_KEY", "taiko-bot-hiroba-key")
    digest = hashlib.sha256(pepper.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)

def ensure_hiroba_credentials_table() -> None:
    ensure_schema()

def decrypt_password(password_enc: str) -> str:
    try:
        return _fernet().decrypt(password_enc.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt Hiroba password") from exc

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
