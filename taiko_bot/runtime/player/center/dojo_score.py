from __future__ import annotations
from taiko_bot.runtime.paths import root as _runtime_root




from sakura_taiko_core.score import dojo as domain_dojo

from sakura_taiko_core.score.dojo import LEVEL_MARK_TO_ICON, _safe_int, _safe_optional_int, level_mark_to_icon, _normalize_song_metrics

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, List, Optional

BASE = Path(str(_runtime_root()))

GRADE_CONFIG_PATH = BASE / "songs" / "grade_dojo_nijiiro_2025_simple.json"

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

def normalize_dojo_scores(payload):
    normalized = isinstance(payload, dict) and isinstance(payload.get("scores"), list)
    return domain_dojo.normalize_dojo_scores(payload, grade_names={} if normalized else load_grade_name_map())

def build_dojo_score_map(payload):
    normalized = isinstance(payload, dict) and isinstance(payload.get("scores"), list)
    return domain_dojo.build_dojo_score_map(payload, grade_names={} if normalized else load_grade_name_map())


@lru_cache(maxsize=1)
def load_grade_id_map() -> Dict[str, int]:
    return {
        grade_name: dan_id for dan_id, grade_name in load_grade_name_map().items()
    }



def get_grade_name_by_dan_id(dan_id: int) -> str:
    return load_grade_name_map().get(int(dan_id), f"段位{dan_id}")



def get_dan_id_by_grade_name(grade_name: str) -> Optional[int]:
    return load_grade_id_map().get(str(grade_name).strip())
