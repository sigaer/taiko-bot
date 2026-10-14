from __future__ import annotations


from sakura_taiko_core.score import dojo as domain_dojo

import json

from functools import lru_cache

from pathlib import Path

from typing import Dict, List, Optional

BASE = __import__("taiko_bot.runtime.player.center.recommendation_support.paths", fromlist=["ROOT"]).ROOT

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

@lru_cache(maxsize=1)
def load_grade_id_map() -> Dict[str, int]:
    return {
        grade_name: dan_id for dan_id, grade_name in load_grade_name_map().items()
    }

def get_dan_id_by_grade_name(grade_name: str) -> Optional[int]:
    return load_grade_id_map().get(str(grade_name).strip())

def normalize_dojo_scores(payload):
    normalized = isinstance(payload, dict) and isinstance(payload.get("scores"), list)
    return domain_dojo.normalize_dojo_scores(payload, grade_names={} if normalized else load_grade_name_map())

def build_dojo_score_map(payload):
    normalized = isinstance(payload, dict) and isinstance(payload.get("scores"), list)
    return domain_dojo.build_dojo_score_map(payload, grade_names={} if normalized else load_grade_name_map())
