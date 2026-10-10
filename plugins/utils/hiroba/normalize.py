from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.parser import hiroba_score as _score

from datetime import datetime
from typing import Any, Dict, List, Optional

from .parser import BADGE_NAME_TO_RANK, HirobaProfile, HirobaScoreDetail


build_profile_stub = _score.build_profile_stub


def score_detail_to_userdata_record(detail):
    return _score.score_detail_to_userdata_record(detail,
        captured_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


_sanitize_achievement = _score._sanitize_achievement


_compute_achievement_from_details = _score._compute_achievement_from_details


def build_userdata(profile, details, achievement=None):
    return _score.build_userdata(profile, details, achievement,
        captured_at=[datetime.now().strftime("%Y-%m-%d %H:%M:%S") for detail in details if detail is not None])
