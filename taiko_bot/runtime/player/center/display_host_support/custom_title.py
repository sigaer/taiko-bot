from __future__ import annotations
import re
import threading
from ..admin_audit import ensure_admin_action_log_table
from ..taiko_db import get_taiko_db_connection


import html

import json

import logging

import unicodedata

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .title_catalog import load_title_catalog_items

ROOT_DIR = __import__("taiko_bot.runtime.public.config",fromlist=["root"]).root()

SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

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

def list_custom_titles(*, connection_factory=None) -> List[CustomTitleRecord]:
    if connection_factory is None:
        ensure_custom_title_table()
        connection_factory = get_taiko_db_connection
    db = connection_factory()
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
    records: Iterable[CustomTitleRecord],
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


CUSTOM_PLATE_DIR = ROOT_DIR / "assets" / "name_plate_custom"

CUSTOM_TITLE_MAX_LENGTH = 30

CUSTOM_TITLE_COOLDOWN_SECONDS = 30

CUSTOM_PLATE_PATHS = {
    "silver": CUSTOM_PLATE_DIR / "name_plate_custom_sliver.png",
    "gold": CUSTOM_PLATE_DIR / "name_plate_custom_gold.png",
    "rainbow": CUSTOM_PLATE_DIR / "name_plate_custom_rainbow.png",
}

CUSTOM_TITLE_COMMAND_NAMES = (
    "添加称号",
    "追加称号",
    "自定义称号",
    "加称号",
    "ttitle",
)

CUSTOM_TITLE_COMMAND_PATTERN = re.compile(
    rf"^/?(?:{'|'.join(re.escape(name) for name in CUSTOM_TITLE_COMMAND_NAMES)})"
    r"\s*(?P<title>.+?)\s*to\s+(?P<target>.+?)\s*$",
    re.IGNORECASE,
)

CUSTOM_TITLE_USAGE = (
    "格式：加称号 称号名 to [里/表/松/竹/梅] 歌曲名 "
    "[过关/全连/全良]（不写难度默认表谱，不写成就默认全连）"
)

CUSTOM_TITLE_LEVELS = {"梅": 1, "竹": 2, "松": 3, "表": 4, "里": 5}

_schema_ready = False

_schema_lock = threading.Lock()

class CustomTitleConflictError(CustomTitleError):
    pass

class CustomTitleCooldownError(CustomTitleError):
    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = max(1, int(remaining_seconds))
        super().__init__(f"操作太快啦，请在 {self.remaining_seconds} 秒后再添加称号。")

@dataclass(frozen=True)
class ParsedCustomTitleCommand:
    title_name: str
    song_query: str
    difficulty_level: int = 4
    achievement_type: str = "full_combo"

def validate_custom_title_name(value: object) -> Tuple[str, str]:
    title_name = normalize_custom_title_display(value)
    if not title_name:
        raise CustomTitleValidationError("称号名不能为空。")
    if any(unicodedata.category(char).startswith("C") for char in title_name):
        raise CustomTitleValidationError("称号名不能包含控制字符。")
    if len(title_name) > CUSTOM_TITLE_MAX_LENGTH:
        raise CustomTitleValidationError(
            f"称号名最多 {CUSTOM_TITLE_MAX_LENGTH} 个字符。"
        )
    return title_name, normalize_custom_title_key(title_name)

def parse_custom_title_command(text: object) -> Optional[ParsedCustomTitleCommand]:
    match = CUSTOM_TITLE_COMMAND_PATTERN.match(str(text or "").strip())
    if not match:
        return None
    title_name = normalize_custom_title_display(match.group("title"))
    target = str(match.group("target") or "").strip()
    if not title_name or not target:
        return None

    achievement_type = "full_combo"
    achievement_match = re.match(
        r"^(?P<song>.+?)\s+(?P<achievement>过关|全连|全良)$",
        target,
    )
    if achievement_match:
        achievement_type = CUSTOM_TITLE_ACHIEVEMENTS[
            achievement_match.group("achievement")
        ]
        target = str(achievement_match.group("song") or "").strip()

    difficulty_level = 4
    difficulty_match = re.match(r"^(?P<difficulty>[里表松竹梅])\s*(?P<song>.+)$", target)
    if difficulty_match:
        difficulty_level = CUSTOM_TITLE_LEVELS[difficulty_match.group("difficulty")]
        target = str(difficulty_match.group("song") or "").strip()
    if not target:
        return None
    return ParsedCustomTitleCommand(
        title_name,
        target,
        difficulty_level,
        achievement_type,
    )

def _validate_level(value: object) -> int:
    try:
        level = int(value)
    except Exception as exc:
        raise CustomTitleValidationError("难度必须是 level 1–5。") from exc
    if level not in CUSTOM_TITLE_LEVEL_LABELS:
        raise CustomTitleValidationError("难度必须是 level 1–5。")
    return level

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

def is_official_title_name(value: object) -> bool:
    key = normalize_custom_title_key(value)
    return bool(key) and key in _official_title_keys()

def _record_payload(record: CustomTitleRecord, song_title: str = "") -> Dict[str, Any]:
    return {
        "id": record.id,
        "title_name": record.title_name,
        "song_id": record.song_id,
        "song_title": str(song_title or ""),
        "difficulty_level": record.difficulty_level,
        "difficulty": CUSTOM_TITLE_LEVEL_LABELS.get(record.difficulty_level, ""),
        "achievement_type": record.achievement_type,
        "achievement": CUSTOM_TITLE_ACHIEVEMENT_LABELS[record.achievement_type],
        "plate_style": CUSTOM_TITLE_ACHIEVEMENT_STYLES[record.achievement_type],
        "creator_type": record.creator_type,
        "creator_id": record.creator_id,
        "creator_name": record.creator_name,
        "source": record.source,
        "group_id": record.group_id,
        "group_name": record.group_name,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }

def create_custom_title(
    *,
    title_name: object,
    song_id: object,
    difficulty_level: object,
    achievement_type: object = "full_combo",
    song_title: str,
    creator_type: str,
    creator_id: str,
    creator_name: str,
    source: str = "bot-custom-title",
    group_id: Optional[str] = None,
    group_name: Optional[str] = None,
    enforce_cooldown: bool = True,
) -> CustomTitleRecord:
    normalized_name, title_key = validate_custom_title_name(title_name)
    level = _validate_level(difficulty_level)
    resolved_achievement_type = _validate_achievement_type(achievement_type)
    try:
        resolved_song_id = int(song_id)
    except Exception as exc:
        raise CustomTitleValidationError("歌曲 ID 无效。") from exc
    if resolved_song_id <= 0:
        raise CustomTitleValidationError("歌曲 ID 无效。")
    if is_official_title_name(normalized_name):
        raise CustomTitleConflictError("该称号名已存在于既有称号中，请换一个名字。")

    ensure_custom_title_table()
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        db.begin()
        if enforce_cooldown:
            cursor.execute(
                """
                SELECT TIMESTAMPDIFF(SECOND, created_at, NOW())
                FROM web_admin_action_logs
                WHERE source = 'bot-custom-title'
                  AND action = 'create'
                  AND actor_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (str(creator_id),),
            )
            cooldown_row = cursor.fetchone()
            if cooldown_row is not None:
                elapsed = int(cooldown_row[0] or 0)
                if elapsed < CUSTOM_TITLE_COOLDOWN_SECONDS:
                    raise CustomTitleCooldownError(
                        CUSTOM_TITLE_COOLDOWN_SECONDS - elapsed
                    )

        cursor.execute(
            "SELECT id FROM taiko_custom_titles WHERE title_key = %s LIMIT 1 FOR UPDATE",
            (title_key,),
        )
        if cursor.fetchone() is not None:
            raise CustomTitleConflictError("该自定义称号已存在，无需重复添加。")

        cursor.execute(
            """
            INSERT INTO taiko_custom_titles (
                title_name, title_key, song_id, difficulty_level,
                achievement_type, creator_type, creator_id, creator_name,
                source, group_id, group_name
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                normalized_name,
                title_key,
                resolved_song_id,
                level,
                resolved_achievement_type,
                str(creator_type or "bot-user"),
                str(creator_id or "unknown"),
                str(creator_name or creator_id or "unknown"),
                str(source or "bot-custom-title"),
                str(group_id) if group_id is not None else None,
                str(group_name) if group_name is not None else None,
            ),
        )
        record_id = int(cursor.lastrowid)
        cursor.execute(f"{_CUSTOM_TITLE_SELECT} WHERE id = %s", (record_id,))
        record = _row_to_record(cursor.fetchone())
        after = _record_payload(record, song_title)
        cursor.execute(
            """
            INSERT INTO web_admin_action_logs (
                actor_type, actor_id, actor_name, source, target_type,
                target_key, action, before_json, after_json, extra_json
            ) VALUES (%s, %s, %s, %s, 'custom-title', %s, 'create', NULL, %s, %s)
            """,
            (
                record.creator_type,
                record.creator_id,
                record.creator_name,
                record.source,
                str(record.id),
                json.dumps(after, ensure_ascii=False),
                json.dumps(
                    {"group_id": record.group_id, "group_name": record.group_name},
                    ensure_ascii=False,
                ),
            ),
        )
        db.commit()
        return record
    except CustomTitleError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        error_code = getattr(exc, "args", (None,))[0]
        if error_code == 1062 or str(error_code) == "1062":
            raise CustomTitleConflictError("该自定义称号已存在，无需重复添加。") from exc
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()

def list_custom_titles_for_song(
    song_id: int,
    *,
    records: Optional[Iterable[CustomTitleRecord]] = None,
) -> List[Any]:
    from .song_title_showcase import _load_song_lookup, _showcase_sort_key

    resolved_song_id = int(song_id)
    resolved_records = list(records) if records is not None else list_custom_titles()
    official_keys = _official_title_keys()
    song_titles = _load_song_title_map()
    _, const_by_song_level, _, level_by_song_level = _load_song_lookup()
    result: List[Any] = []

    for custom_title in resolved_records:
        if custom_title.song_id != resolved_song_id:
            continue
        if custom_title.title_key in official_keys:
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

def custom_title_catalog_fingerprint() -> str:
    import hashlib

    try:
        rows = list_custom_titles()
    except Exception:
        return "unavailable"
    payload = [
        [
            row.id,
            row.title_name,
            row.song_id,
            row.difficulty_level,
            row.achievement_type,
            row.updated_at,
        ]
        for row in rows
    ]
    return hashlib.sha1(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
