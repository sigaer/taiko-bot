from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .taiko_db import get_taiko_db_connection


def ensure_admin_action_log_table() -> None:
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS web_admin_action_logs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                actor_type VARCHAR(32) NOT NULL,
                actor_id VARCHAR(255) DEFAULT NULL,
                actor_name VARCHAR(255) DEFAULT NULL,
                source VARCHAR(32) NOT NULL,
                target_type VARCHAR(64) NOT NULL,
                target_key VARCHAR(255) NOT NULL,
                action VARCHAR(16) NOT NULL,
                before_json LONGTEXT DEFAULT NULL,
                after_json LONGTEXT DEFAULT NULL,
                extra_json LONGTEXT DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                KEY idx_web_admin_action_logs_created_at (created_at),
                KEY idx_web_admin_action_logs_target (target_type, target_key, created_at),
                KEY idx_web_admin_action_logs_source_action (source, action, created_at)
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


def _to_json_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, indent=2)


def write_admin_action_log(
    *,
    actor_type: str,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    source: str,
    target_type: str,
    target_key: str,
    action: str,
    before: Any = None,
    after: Any = None,
    extra: Any = None,
) -> None:
    ensure_admin_action_log_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO web_admin_action_logs (
                actor_type,
                actor_id,
                actor_name,
                source,
                target_type,
                target_key,
                action,
                before_json,
                after_json,
                extra_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(actor_type or "").strip() or "system",
                str(actor_id or "").strip() or None,
                str(actor_name or "").strip() or None,
                str(source or "").strip() or "system",
                str(target_type or "").strip() or "unknown",
                str(target_key or "").strip() or "unknown",
                str(action or "").strip() or "read",
                _to_json_text(before),
                _to_json_text(after),
                _to_json_text(extra),
            ),
        )
        db.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def write_system_backup_log(label: str, extra: Optional[Dict[str, Any]] = None) -> None:
    write_admin_action_log(
        actor_type="system",
        actor_id="system-backup",
        actor_name="system-backup",
        source="system-backup",
        target_type="backup",
        target_key=str(label or "backup"),
        action="create",
        extra=extra or {},
    )
