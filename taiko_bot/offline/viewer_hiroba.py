"""Viewer's existing center credential/sync contracts, without bot registration."""
from taiko_bot.runtime.player.center.hiroba.credentials import (
    load_hiroba_credentials, has_hiroba_credentials,
)
from taiko_bot.runtime.player.center.hiroba.sync import (
    sync_hiroba_userdata, discover_hiroba_playable_cards,
)


def save_hiroba_credentials(taiko_no, email, password, *, configured_by_qq=None):
    """Persist a credential selected by the authenticated Viewer binding flow."""
    from taiko_bot.runtime.player.center.hiroba.credentials import ensure_hiroba_credentials_table, encrypt_password
    from taiko_bot.runtime.player.center.taiko_db import get_taiko_db_connection
    ensure_hiroba_credentials_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("""INSERT INTO web_hiroba_credentials (taiko_no, email, password_enc, configured_by_qq)
            VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE
            email=VALUES(email), password_enc=VALUES(password_enc),
            configured_by_qq=VALUES(configured_by_qq), updated_at=CURRENT_TIMESTAMP""",
            (str(taiko_no), email.strip(), encrypt_password(password), configured_by_qq))
        db.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()
