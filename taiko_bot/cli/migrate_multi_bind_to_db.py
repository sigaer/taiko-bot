#!/usr/bin/env python3
"""Migrate legacy taiko_multi_bind.json into normalized bind slot rows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pymysql

from taiko_bot.offline.paths import root
ROOT = root()
LEGACY_PATH = ROOT / "data" / "taiko_multi_bind.json"
BACKUP_ROOT = ROOT / "data" / "bind_migration_backups"


def connect():
    return pymysql.connect(
        host=os.getenv("TAIKO_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("TAIKO_DB_PORT", "3306")),
        user=os.environ["TAIKO_DB_USER"],
        password=os.environ["TAIKO_DB_PASSWORD"],
        database=os.getenv("TAIKO_DB_NAME", "taiko"),
        charset="utf8mb4",
        autocommit=False,
    )


def clean_ids(value: Any) -> List[str]:
    output: List[str] = []
    for raw in value if isinstance(value, list) else []:
        taiko_id = str(raw or "").strip()
        if taiko_id and taiko_id not in output:
            output.append(taiko_id)
    return output


def infer_source(taiko_id: str, sources: Dict[str, Any]) -> str:
    explicit = str(sources.get(taiko_id) or "").strip().lower()
    if explicit in {"wahlap", "hiroba"}:
        return explicit
    return "hiroba" if len(taiko_id) == 12 else "wahlap"


def load_plan(cursor) -> Dict[str, Dict[str, Any]]:
    cursor.execute(
        "SELECT qq,id,COALESCE(visible,0),COALESCE(source,'wahlap') FROM bind ORDER BY qq,row_id"
    )
    existing: Dict[str, List[Dict[str, Any]]] = {}
    for identity, taiko_id, visible, source in cursor.fetchall():
        existing.setdefault(str(identity), []).append(
            {
                "id": str(taiko_id),
                "visible": int(visible or 0),
                "source": str(source or "wahlap"),
            }
        )
    legacy = json.loads(LEGACY_PATH.read_text("utf-8")) if LEGACY_PATH.exists() else {}
    plan: Dict[str, Dict[str, Any]] = {}
    for identity, rows in existing.items():
        fallback = rows[0]
        plan[identity] = {
            "ids": [fallback["id"]],
            "current_index": 0,
            "current_virtual": False,
            "visible": fallback["visible"],
            "sources": {fallback["id"]: fallback["source"]},
        }
    for raw_identity, payload in legacy.items():
        if not isinstance(payload, dict):
            continue
        identity = str(raw_identity or "").strip()
        ids = clean_ids(payload.get("ids"))
        if not identity or not ids:
            continue
        fallback = existing.get(identity, [{"visible": 0, "id": ids[0]}])[0]
        try:
            current_index = max(0, min(int(payload.get("current_index", 0)), len(ids) - 1))
        except (TypeError, ValueError):
            current_index = 0
        plan[identity] = {
            "ids": ids,
            "current_index": current_index,
            "current_virtual": int(payload.get("current_slot", current_index + 1) or 0) == 0,
            "visible": int(fallback.get("visible", 0)),
            "sources": {
                taiko_id: infer_source(
                    taiko_id,
                    payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
                )
                for taiko_id in ids
            },
        }
    return plan


def ensure_schema(cursor) -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS taiko_bind_identity_state (
             identity_key VARCHAR(191) NOT NULL PRIMARY KEY,
             current_virtual TINYINT(1) NOT NULL DEFAULT 0,
             updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
               ON UPDATE CURRENT_TIMESTAMP
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply migration; default is dry-run")
    args = parser.parse_args()
    db = connect()
    try:
        with db.cursor() as cursor:
            ensure_schema(cursor)
            plan = load_plan(cursor)
            slots = sum(len(item["ids"]) for item in plan.values())
            multi = sum(1 for item in plan.values() if len(item["ids"]) > 1)
            virtual = sum(1 for item in plan.values() if item["current_virtual"])
            print(
                json.dumps(
                    {
                        "mode": "apply" if args.apply else "dry-run",
                        "identities": len(plan),
                        "slots": slots,
                        "multiIdentities": multi,
                        "currentVirtual": virtual,
                    },
                    ensure_ascii=False,
                )
            )
            if not args.apply:
                db.rollback()
                return 0

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_dir = BACKUP_ROOT / stamp
            backup_dir.mkdir(parents=True, exist_ok=False)
            if LEGACY_PATH.exists():
                shutil.copy2(LEGACY_PATH, backup_dir / LEGACY_PATH.name)
            cursor.execute(
                """SELECT row_id,qq,id,visible,slot_index,is_current,source
                     FROM bind ORDER BY qq,slot_index,row_id"""
            )
            columns = ["row_id", "qq", "id", "visible", "slot_index", "is_current", "source"]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            (backup_dir / "bind_rows.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, default=str), "utf-8"
            )
            (backup_dir / "migration_plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), "utf-8"
            )

            cursor.execute("DELETE FROM taiko_bind_identity_state")
            cursor.execute("DELETE FROM bind")
            for identity, item in plan.items():
                for index, taiko_id in enumerate(item["ids"]):
                    cursor.execute(
                        """INSERT INTO bind
                             (qq,id,visible,slot_index,is_current,source)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
                        (
                            identity,
                            taiko_id,
                            item["visible"],
                            index + 1,
                            1 if index == item["current_index"] else 0,
                            item["sources"][taiko_id],
                        ),
                    )
                cursor.execute(
                    """INSERT INTO taiko_bind_identity_state(identity_key,current_virtual)
                       VALUES(%s,%s)""",
                    (identity, 1 if item["current_virtual"] else 0),
                )
            db.commit()
            print(json.dumps({"ok": True, "backup": str(backup_dir)}, ensure_ascii=False))
            return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
