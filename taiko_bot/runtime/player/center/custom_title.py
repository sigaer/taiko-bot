from __future__ import annotations
from taiko_bot.runtime.public.config import root as _runtime_root




import html

import json

import logging

import threading

import unicodedata

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .admin_audit import ensure_admin_action_log_table

from .taiko_db import get_taiko_db_connection

from .title_catalog import load_title_catalog_items

ROOT_DIR = _runtime_root()

SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

CUSTOM_PLATE_DIR = ROOT_DIR / "assets" / "name_plate_custom"

CUSTOM_PLATE_PATHS = {
    "silver": CUSTOM_PLATE_DIR / "name_plate_custom_sliver.png",
    "gold": CUSTOM_PLATE_DIR / "name_plate_custom_gold.png",
    "rainbow": CUSTOM_PLATE_DIR / "name_plate_custom_rainbow.png",
}

CUSTOM_TITLE_LEVEL_LABELS = {1: "梅", 2: "竹", 3: "松", 4: "表", 5: "里"}

CUSTOM_TITLE_ACHIEVEMENTS = {
    "过关": "clear",
    "全连": "full_combo",
    "全良": "all_perfect",
}

CUSTOM_TITLE_ACHIEVEMENT_LABELS = {
    "clear": "过关",
    "full_combo": "全连",
    "all_perfect": "全良",
}

CUSTOM_TITLE_ACHIEVEMENT_STYLES = {
    "clear": "silver",
    "full_combo": "gold",
    "all_perfect": "rainbow",
}

CUSTOM_TITLE_SCOPES = {
    1: "easy",
    2: "normal",
    3: "hard",
    4: "oni",
    5: "inner_oni",
}

_schema_ready = False

_schema_lock = threading.Lock()

class CustomTitleError(RuntimeError):
    pass

class CustomTitleValidationError(CustomTitleError):
    pass

@dataclass(frozen=True)
class CustomTitleRecord:
    id: int
    title_name: str
    title_key: str
    song_id: int
    difficulty_level: int
    creator_type: str
    creator_id: str
    creator_name: str
    source: str
    group_id: Optional[str]
    group_name: Optional[str]
    created_at: str
    updated_at: str
    achievement_type: str = "full_combo"

def normalize_custom_title_display(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip()

def normalize_custom_title_key(value: object) -> str:
    return normalize_custom_title_display(value).lower()

def _validate_achievement_type(value: object) -> str:
    normalized = str(value or "full_combo").strip()
    achievement_type = CUSTOM_TITLE_ACHIEVEMENTS.get(normalized, normalized)
    if achievement_type not in CUSTOM_TITLE_ACHIEVEMENT_LABELS:
        raise CustomTitleValidationError("成就必须是过关、全连或全良。")
    return achievement_type

def ensure_custom_title_table() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        ensure_admin_action_log_table()
        db = get_taiko_db_connection()
        cursor = db.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS taiko_custom_titles (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    title_name VARCHAR(255) NOT NULL,
                    title_key VARCHAR(255) NOT NULL,
                    song_id INT NOT NULL,
                    difficulty_level TINYINT UNSIGNED NOT NULL,
                    achievement_type VARCHAR(32) NOT NULL DEFAULT 'full_combo',
                    creator_type VARCHAR(32) NOT NULL,
                    creator_id VARCHAR(255) NOT NULL,
                    creator_name VARCHAR(255) NOT NULL,
                    source VARCHAR(32) NOT NULL,
                    group_id VARCHAR(255) DEFAULT NULL,
                    group_name VARCHAR(255) DEFAULT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uniq_taiko_custom_titles_title_key (title_key),
                    KEY idx_taiko_custom_titles_song_level (song_id, difficulty_level),
                    KEY idx_taiko_custom_titles_creator (creator_id, created_at),
                    CONSTRAINT chk_taiko_custom_titles_level CHECK (difficulty_level BETWEEN 1 AND 5)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                "SHOW COLUMNS FROM taiko_custom_titles LIKE 'achievement_type'"
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    ALTER TABLE taiko_custom_titles
                    ADD COLUMN achievement_type VARCHAR(32) NOT NULL
                    DEFAULT 'full_combo' AFTER difficulty_level
                    """
                )
            db.commit()
            _schema_ready = True
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            db.close()

def _official_title_keys() -> set[str]:
    return {
        normalize_custom_title_key(item.get("name"))
        for item in load_title_catalog_items()
        if isinstance(item, dict) and normalize_custom_title_display(item.get("name"))
    }

def _row_to_record(row: Sequence[Any]) -> CustomTitleRecord:
    return CustomTitleRecord(
        id=int(row[0]),
        title_name=str(row[1] or ""),
        title_key=str(row[2] or ""),
        song_id=int(row[3]),
        difficulty_level=int(row[4]),
        creator_type=str(row[5] or ""),
        creator_id=str(row[6] or ""),
        creator_name=str(row[7] or ""),
        source=str(row[8] or ""),
        group_id=str(row[9]) if row[9] is not None else None,
        group_name=str(row[10]) if row[10] is not None else None,
        created_at=str(row[11] or ""),
        updated_at=str(row[12] or ""),
        achievement_type=_validate_achievement_type(row[13]),
    )

_CUSTOM_TITLE_SELECT = """
SELECT id, title_name, title_key, song_id, difficulty_level,
       creator_type, creator_id, creator_name, source, group_id, group_name,
       created_at, updated_at, achievement_type
FROM taiko_custom_titles
"""

def list_custom_titles() -> List[CustomTitleRecord]:
    ensure_custom_title_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(f"{_CUSTOM_TITLE_SELECT} ORDER BY id ASC")
        return [_row_to_record(row) for row in cursor.fetchall()]
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()

def _load_song_title_map() -> Dict[int, str]:
    try:
        payload = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: Dict[int, str] = {}
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id"))
        except Exception:
            continue
        result[song_id] = str(
            item.get("song_name_jp") or item.get("song_name") or f"ID{song_id}"
        )
    return result

def _achievement_for_record(
    record: Optional[Dict[str, Any]],
    achievement_type: str,
) -> Optional[Tuple[str, str]]:
    if not isinstance(record, dict):
        return None
    achievement_type = _validate_achievement_type(achievement_type)
    clear_count = int(record.get("clear_cnt", 0) or 0)
    full_combo_count = int(record.get("full_combo_cnt", 0) or 0)
    all_perfect_count = int(record.get("dondaful_combo_cnt", 0) or 0)
    satisfied = {
        "clear": clear_count > 0 or full_combo_count > 0 or all_perfect_count > 0,
        "full_combo": full_combo_count > 0 or all_perfect_count > 0,
        "all_perfect": all_perfect_count > 0,
    }
    if not satisfied[achievement_type]:
        return None
    return (
        achievement_type,
        CUSTOM_TITLE_ACHIEVEMENT_STYLES[achievement_type],
    )

def _build_custom_title_showcase(
    custom_title: CustomTitleRecord,
    *,
    song_name: str,
    const_value: float,
) -> Any:
    from .song_title_showcase import ShowcaseTitle

    requirement_type = _validate_achievement_type(custom_title.achievement_type)
    level_label = CUSTOM_TITLE_LEVEL_LABELS[custom_title.difficulty_level]
    achievement_label = CUSTOM_TITLE_ACHIEVEMENT_LABELS[requirement_type]
    return ShowcaseTitle(
        title_name=custom_title.title_name,
        plate_id=-1,
        requirement_type=requirement_type,
        difficulty_scope=CUSTOM_TITLE_SCOPES[custom_title.difficulty_level],
        condition_text=(
            f"自定义称号：{achievement_label}《{song_name}》{level_label}谱"
        ),
        song_names=(song_name,),
        song_ids=(custom_title.song_id,),
        const_value=const_value,
        priority_const_value=const_value,
        is_multi_song=False,
        source="custom",
        custom_title_id=custom_title.id,
        difficulty_level=custom_title.difficulty_level,
        plate_style=CUSTOM_TITLE_ACHIEVEMENT_STYLES[requirement_type],
    )

def list_custom_title_showcase_candidates(
    songs: Iterable[Dict[str, Any]],
    *,
    records: Optional[Iterable[CustomTitleRecord]] = None,
) -> List[Any]:
    from .song_title_showcase import _load_song_lookup, _showcase_sort_key

    song_records: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for song in songs:
        if not isinstance(song, dict):
            continue
        try:
            song_records[(int(song.get("song_no")), int(song.get("level")))] = song
        except Exception:
            continue

    if records is None:
        try:
            resolved_records = list_custom_titles()
        except Exception:
            logging.exception("failed_to_load_custom_titles_for_showcase")
            return []
    else:
        resolved_records = list(records)

    official_keys = _official_title_keys()
    song_titles = _load_song_title_map()
    _, const_by_song_level, _, level_by_song_level = _load_song_lookup()
    result: List[Any] = []
    for custom_title in resolved_records:
        if custom_title.title_key in official_keys:
            continue
        if _achievement_for_record(
            song_records.get((custom_title.song_id, custom_title.difficulty_level)),
            custom_title.achievement_type,
        ) is None:
            continue
        song_name = song_titles.get(custom_title.song_id, f"ID{custom_title.song_id}")
        const_value = float(
            const_by_song_level.get(
                (custom_title.song_id, custom_title.difficulty_level),
                level_by_song_level.get(
                    (custom_title.song_id, custom_title.difficulty_level), 0.0
                ),
            )
            or 0.0
        )
        result.append(
            _build_custom_title_showcase(
                custom_title,
                song_name=song_name,
                const_value=const_value,
            )
        )
    return sorted(result, key=_showcase_sort_key)
