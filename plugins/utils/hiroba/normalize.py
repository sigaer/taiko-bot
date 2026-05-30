from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .parser import BADGE_NAME_TO_RANK, HirobaProfile, HirobaScoreDetail


def build_profile_stub(profile: HirobaProfile) -> Dict[str, Any]:
    return {
        "mydon_name": profile.nickname or profile.taiko_no,
        "userid": profile.taiko_no,
        "gameCostume": {
            "mydon_name": profile.nickname or profile.taiko_no,
            "title": profile.title or "",
            "titleplate_id": 0,
        },
        "_source": "hiroba",
    }


def score_detail_to_userdata_record(detail: HirobaScoreDetail) -> Dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    badge_rank = BADGE_NAME_TO_RANK.get(detail.badge or "", 0)
    return {
        "song_no": int(detail.song_no),
        "level": int(detail.level),
        "high_score": int(detail.score),
        "best_score_rank": int(badge_rank),
        "good_cnt": int(detail.good),
        "ok_cnt": int(detail.ok),
        "ng_cnt": int(detail.bad),
        "pound_cnt": int(detail.roll),
        "combo_cnt": int(detail.max_combo),
        "option_flg": [1, 0, 0, "00"],
        "stage_cnt": int(detail.stage_cnt),
        "clear_cnt": int(detail.clear_cnt),
        "full_combo_cnt": int(detail.full_combo_cnt),
        "dondaful_combo_cnt": int(detail.dondaful_combo_cnt),
        "highscore_datetime": now,
        "highscore_mode": 0,
        "update_datetime": now,
        "_hiroba_crown": detail.crown,
        "_hiroba_badge": detail.badge,
    }


def _sanitize_achievement(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = raw or {}
    ary_rank = list(payload.get("ary_score_rank_count") or [])
    ary_crown = list(payload.get("ary_crown_count") or [])
    if len(ary_rank) < 7:
        ary_rank.extend([0] * (7 - len(ary_rank)))
    if len(ary_crown) < 3:
        ary_crown.extend([0] * (3 - len(ary_crown)))
    return {
        "count_level": int(payload.get("count_level", 1) or 1),
        "ary_crown_count": [int(v or 0) for v in ary_crown[:3]],
        "ary_score_rank_count": [int(v or 0) for v in ary_rank[:7]],
    }


def _compute_achievement_from_details(details: List[HirobaScoreDetail]) -> Dict[str, Any]:
    rank_counts = [0] * 7
    crown_counts = [0] * 3
    for detail in details:
        if detail is None:
            continue

        rank_value = BADGE_NAME_TO_RANK.get(detail.badge or "", 0)
        if 2 <= rank_value <= 8:
            rank_counts[rank_value - 2] += 1

        crown = str(detail.crown or "").strip().lower()
        if crown in {"silver"} or int(detail.clear_cnt or 0) > 0:
            crown_counts[0] += 1
        if crown in {"gold", "dondaful", "donderfull"} or int(detail.full_combo_cnt or 0) > 0:
            crown_counts[1] += 1
        if crown in {"dondaful", "donderfull"} or int(detail.dondaful_combo_cnt or 0) > 0:
            crown_counts[2] += 1

    if rank_counts[6] > 0:
        count_level = 5
    elif rank_counts[5] > 0:
        count_level = 4
    elif rank_counts[4] > 0:
        count_level = 3
    elif rank_counts[3] > 0:
        count_level = 2
    else:
        count_level = 1
    return {
        "count_level": count_level,
        "ary_crown_count": crown_counts,
        "ary_score_rank_count": rank_counts,
    }


def build_userdata(
    profile: HirobaProfile,
    details: List[HirobaScoreDetail],
    achievement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    songs = [score_detail_to_userdata_record(d) for d in details if d is not None]
    songs.sort(key=lambda item: (item["song_no"], item["level"]))
    achievement_payload = (
        _sanitize_achievement(achievement)
        if achievement
        else _compute_achievement_from_details(details)
    )
    return {
        "profile": build_profile_stub(profile),
        "songs": songs,
        "achievement": achievement_payload,
        "dojo": {},
    }
