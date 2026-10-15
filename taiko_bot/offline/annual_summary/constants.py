from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

from pathlib import Path


BASE = Path(str(_runtime_root()))
USERDATA_DIR = BASE / "userdata"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
RATING_DATA_PATH = BASE / "songs" / "rating_structured_with_ids.json"
SCHEMA_PATH = BASE / "schemas" / "annual-summary-v4.schema.json"

SCHEMA_VERSION = 4
ALGORITHM_VERSION = "annual-observation-v4.5.3"
DEFAULT_VERSION_KEY = "annual_2026"
DEFAULT_VERSION = {
    "key": DEFAULT_VERSION_KEY,
    "name": "2026 太鼓年度回顾",
    "timezone": "Asia/Shanghai",
}

FULL_SNAPSHOT_MIN_SONGS = 500
TIME_COVERAGE_THRESHOLD = 0.8
MIN_TIMED_EVENT_RECORDS = 5
MIN_TIMED_ACTIVE_DAYS = 2
MIN_SPEED_RECORDS = 11
MIN_CHALLENGE_PLAYS = 10
KEYWORD_CHART_LIMIT = 20

TRUSTED_PLAY_TIME_SOURCES = frozenset({"wahlap"})
ARCHIVE_ONLY_SOURCES = frozenset({"merged-bind"})
MANUAL_SOURCES = frozenset({"web-account", "manual-score", "web-score-import", "manual-score-delete"})
KNOWN_LOW_TRUST_SOURCES = frozenset(
    {"hiroba", "legacy", "unknown", "sakura-bot-sync"}
)

COUNTER_FIELDS = (
    "stage_cnt",
    "high_score",
    "clear_cnt",
    "full_combo_cnt",
    "dondaful_combo_cnt",
)

VALID_SPEEDS = frozenset(
    {1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.5, 3.0, 3.5, 4.0}
)

DIMENSION_CONFIG = (
    ("big_song", "大歌力", "big_song"),
    ("stamina", "体力", "stamina"),
    ("speed", "高速处理", "speed"),
    ("accuracy", "精度力", "accuracy_power"),
    ("rhythm", "节奏处理", "rhythm"),
    ("complex", "复合处理", "complex_proc"),
)

KEYWORD_TITLE_KEYS = {
    "big_song": "wall_breaker",
    "stamina": "endless_drummer",
    "speed": "speed_runner",
    "accuracy": "precision_tuner",
    "rhythm": "rhythm_resonator",
    "complex": "complex_hunter",
}
