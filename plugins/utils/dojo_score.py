from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.score import dojo as _dojo

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from taiko_bot.settings import get_settings

BASE = get_settings().root_dir
GRADE_CONFIG_PATH = BASE / "songs" / "grade_dojo_nijiiro_2025_simple.json"

LEVEL_MARK_TO_ICON = _dojo.LEVEL_MARK_TO_ICON


_safe_int = _dojo._safe_int


_safe_optional_int = _dojo._safe_optional_int


@lru_cache(maxsize=1)
def load_grade_order() -> List[str]:
    payload = json.loads(GRADE_CONFIG_PATH.read_text(encoding="utf-8"))
    return [str(grade.get("grade") or "").strip() for grade in payload.get("grades") or []]


@lru_cache(maxsize=1)
def load_grade_name_map() -> Dict[int, str]:
    return {
        idx + 1: grade_name
        for idx, grade_name in enumerate(load_grade_order())
        if grade_name
    }


@lru_cache(maxsize=1)
def load_grade_id_map() -> Dict[str, int]:
    return {
        grade_name: dan_id for dan_id, grade_name in load_grade_name_map().items()
    }


def get_grade_name_by_dan_id(dan_id: int) -> str:
    return load_grade_name_map().get(int(dan_id), f"段位{dan_id}")


def get_dan_id_by_grade_name(grade_name: str) -> Optional[int]:
    return load_grade_id_map().get(str(grade_name).strip())


level_mark_to_icon = _dojo.level_mark_to_icon


_normalize_song_metrics = _dojo._normalize_song_metrics


class _GradeNames:
    def get(self, dan_id, default=None):
        return load_grade_name_map().get(dan_id, default)


def normalize_dojo_scores(payload):
    return _dojo.normalize_dojo_scores(payload, grade_names=_GradeNames())


def build_dojo_score_map(payload):
    return _dojo.build_dojo_score_map(payload, grade_names=_GradeNames())
