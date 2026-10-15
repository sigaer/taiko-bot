"""FinalTitle model (production port of the frozen Copy-3A/Copy-3B model).

Pipeline (unchanged from the approved audit):

    raw features -> dimension scores (population percentiles + volume/rating residuals)
                 -> dan achievement adjustment (severity merge into growth)
                 -> L1/L2/L3 routing
                 -> primary -> optional secondary
                 -> resolveFinalTitleKey() (45-key whitelist)
                 -> evidenceKey / evidenceValue

Everything is deterministic.  No thresholds are re-tuned here; every constant is a
verbatim copy of the frozen audit definition (see ``PARAMETER_MANIFEST``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .dan_events import (
    MAJOR_PROGRESS_MIN_DAN,
    MAJOR_PROGRESS_MIN_LEVELS,
    STRONG_DAN_SEVERITY,
    DanEvent,
    is_strong_dan_achievement,
)
from .dan_state import DanState
from .finaltitle_reference import FinalTitleReference

DIMENSIONS: Sequence[str] = ("growth", "precision", "speed", "endurance", "exploration", "devotion", "nocturnal")

# ---------------------------------------------------------------- frozen params
BREAKTHROUGH_TIER: Dict[str, float] = {
    "dan": 1.0,
    "ten_star_full_combo": 0.95,
    "dondaful": 0.92,
    "extreme": 0.90,
    "rating_gain": 0.85,
    "ten_star_clear": 0.65,
    "full_combo": 0.60,
    "clear": 0.40,
}
BREAKTHROUGH_TIER_DEFAULT = 0.5
STRONG_BREAKTHROUGH_TYPES = frozenset({"dan", "ten_star_full_combo", "dondaful", "extreme", "rating_gain"})
FORCED_BREAKTHROUGH_QUALITY = 0.90
FORCED_BREAKTHROUGH_MIN_GROWTH = 0.5

PRIMARY_COVERAGE_GATE = 0.5
SECONDARY_COVERAGE_GATE = 0.4
SECONDARY_SCORE_THRESHOLD = 0.5
LOW_MARGIN_GATE = 0.06

DAN_GROWTH_MERGE_BASE_WEIGHT = 0.4
DAN_GROWTH_MERGE_EVENT_WEIGHT = 0.6

L1_MAX_PLAY_COUNT = 20
L2_MAX_TYPED_PAGES = 1
ARCHIVE_REGULAR_MIN_CLEARS = 300
ARCHIVE_EXPLORER_MIN_BREADTH = 0.40
ARCHIVE_EXPLORER_MIN_SONGS = 50
ARCHIVE_COLLECTOR_MIN_CLEARS = 20
ARCHIVE_DAN_MIN_BEST_MARK = 4

CURATED_PAIRS: frozenset[Tuple[str, str]] = frozenset({
    ("devotion", "endurance"), ("devotion", "growth"), ("devotion", "precision"), ("devotion", "speed"),
    ("endurance", "devotion"), ("endurance", "exploration"), ("endurance", "growth"), ("endurance", "nocturnal"),
    ("endurance", "precision"), ("endurance", "speed"),
    ("exploration", "endurance"), ("exploration", "growth"),
    ("growth", "devotion"), ("growth", "endurance"), ("growth", "exploration"), ("growth", "precision"), ("growth", "speed"),
    ("nocturnal", "devotion"), ("nocturnal", "endurance"), ("nocturnal", "exploration"), ("nocturnal", "growth"),
    ("nocturnal", "precision"), ("nocturnal", "speed"),
    ("precision", "devotion"), ("precision", "endurance"), ("precision", "growth"), ("precision", "speed"),
    ("speed", "devotion"), ("speed", "endurance"), ("speed", "exploration"), ("speed", "growth"), ("speed", "precision"),
})

FINAL_TITLE_KEYS: frozenset[str] = frozenset({
    "final_archive_collector", "final_archive_dan", "final_archive_explorer", "final_archive_regular",
    "final_devotion", "final_devotion_endurance", "final_devotion_growth", "final_devotion_precision",
    "final_devotion_speed", "final_early", "final_endurance", "final_endurance_devotion",
    "final_endurance_exploration", "final_endurance_growth", "final_endurance_nocturnal",
    "final_endurance_precision", "final_endurance_speed", "final_exploration",
    "final_exploration_endurance", "final_exploration_growth", "final_growth", "final_growth_devotion",
    "final_growth_endurance", "final_growth_exploration", "final_growth_precision", "final_growth_speed",
    "final_keeper", "final_nocturnal", "final_nocturnal_devotion", "final_nocturnal_endurance",
    "final_nocturnal_exploration", "final_nocturnal_growth", "final_nocturnal_precision",
    "final_nocturnal_speed", "final_precision", "final_precision_devotion", "final_precision_endurance",
    "final_precision_growth", "final_precision_speed", "final_speed", "final_speed_devotion",
    "final_speed_endurance", "final_speed_exploration", "final_speed_growth", "final_speed_precision",
})

# ---------------------------------------------------------------- evidence keys
EVIDENCE_DAN_STRONG: Dict[int, str] = {
    2: "dan_kanzui_red",
    5: "dan_kanzui_gold",
    3: "dan_fullgood_red",
    6: "dan_fullgood_gold",
    4: "dan_gold_pass",
}
EVIDENCE_DAN_MAJOR_PROGRESS = "dan_major_progress"
EVIDENCE_DAN_MARK_PROGRESS = "dan_mark_progress"
EVIDENCE_DAN_STANDING: Dict[int, str] = {
    2: "dan_standing_kanzui_red",
    5: "dan_standing_kanzui_gold",
    3: "dan_standing_fullgood_red",
    6: "dan_standing_fullgood_gold",
    4: "dan_standing_gold_pass",
}
EVIDENCE_DIMENSION: Dict[str, str] = {
    "growth": "growth_breakthrough",
    "precision": "precision_full_combo",
    "speed": "speed_high",
    "endurance": "endurance_volume",
    "exploration": "exploration_breadth",
    "devotion": "devotion_song",
    "nocturnal": "nocturnal_days",
}
EVIDENCE_SPARSE = "sparse_basic"
DAN_EVIDENCE_KEYS: frozenset[str] = frozenset(
    set(EVIDENCE_DAN_STRONG.values())
    | set(EVIDENCE_DAN_STANDING.values())
    | {EVIDENCE_DAN_MAJOR_PROGRESS, EVIDENCE_DAN_MARK_PROGRESS}
)
#: evidence keys that unlock the Dan-specific title presentation (strong dan only)
STRONG_DAN_PRESENTATION_EVIDENCE: frozenset[str] = frozenset(
    set(EVIDENCE_DAN_STRONG.values()) | {EVIDENCE_DAN_MAJOR_PROGRESS}
)

SINGER_LEVELS = ("L1", "L2", "L3")


# ---------------------------------------------------------------- helpers
def _mean_available(pairs: Sequence[Tuple[Optional[float], float]]) -> Tuple[Optional[float], float]:
    available = [(value, weight) for value, weight in pairs if value is not None]
    if not available:
        return None, 0.0
    total_weight = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total_weight, total_weight / sum(
        weight for _, weight in pairs
    )


def _ratio(part: Any, whole: Any) -> Optional[float]:
    try:
        part_value = float(part)
        whole_value = float(whole)
    except (TypeError, ValueError):
        return None
    if not whole_value:
        return None
    return part_value / whole_value


@dataclass
class FinalTitleDecision:
    title_key: str
    evidence_key: str
    evidence_value: Any
    level: str
    primary: str
    secondary: Optional[str]
    reason: Optional[str]
    scores: Dict[str, Optional[float]]
    coverage: Dict[str, float]
    severity: float
    strong_dan: bool
    dan_event_kind: Optional[str] = None

    def public(self) -> Dict[str, Any]:
        """Exactly the three keys the v4 schema exposes (no schema change)."""
        return {"titleKey": self.title_key, "evidenceKey": self.evidence_key, "evidenceValue": self.evidence_value}

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "primary": self.primary,
            "secondary": self.secondary,
            "reason": self.reason,
            "scores": self.scores,
            "coverage": self.coverage,
            "severity": round(self.severity, 4),
            "strongDan": self.strong_dan,
            "danEventKind": self.dan_event_kind,
        }


def dimension_scores(features: Dict[str, Any], reference: FinalTitleReference) -> Tuple[Dict[str, Optional[float]], Dict[str, float]]:
    """Port of the audit ``scores_for`` (population percentiles in the reference)."""
    play_count = features.get("play_count") or 0
    active_days = features.get("active_days")
    rating = features.get("rating")

    # falsy active_days (0 / missing) means "no calendar data": the audit fills the
    # population median for the percentile column but drops the term from endurance.
    days_present = active_days if active_days else None
    volume = None
    play_pct = reference.percentile("play", play_count)
    days_value = days_present if days_present is not None else reference.median("days")
    days_pct = reference.percentile("days", days_value)
    if play_pct is not None and days_pct is not None:
        volume = (play_pct + days_pct) / 2

    charts_per_play = _ratio(features.get("unique_charts"), play_count)
    months_per_active = _ratio(features.get("monthly_count"), active_days)
    obsession_share = _ratio(features.get("obsession_days"), active_days)
    favorite_share = _ratio(features.get("favorite_plays"), play_count)
    challenge_share = _ratio(features.get("challenge_plays"), play_count)
    late_share = _ratio(features.get("late_days"), active_days)

    # rating-controlled residuals bucket by the *percentile* of the median-filled rating
    # (the reference stores bucket edges in percentile space, matching the audit control)
    rating_control = reference.percentile("rating", rating if rating is not None else reference.median("rating"))
    milestones_value = features.get("milestone_count") if features.get("mode") == "version_observed" else None
    hardship_value = features.get("hardship_max")
    pound_speed_value = features.get("pound_speed")

    R = {
        "charts_per_play": reference.residual_percentile("charts_per_play", volume, charts_per_play),
        "months_per_active": reference.residual_percentile("months_per_active", volume, months_per_active),
        "obsession_share": reference.residual_percentile("obsession_share", volume, obsession_share),
        "favorite_share": reference.residual_percentile("favorite_share", volume, favorite_share),
        "challenge_share": reference.residual_percentile("challenge_share", volume, challenge_share),
        "late_share": reference.residual_percentile("late_share", volume, late_share),
        "dondaful_share": reference.residual_percentile("dondaful_share", volume, features.get("dondaful_share")),
        "full_combo_share": reference.residual_percentile("full_combo_share", volume, features.get("full_combo_share")),
        "near_ok": reference.residual_percentile("near_ok", volume, features.get("near_ok")),
        "milestones": reference.residual_percentile("milestones", volume, milestones_value),
        "pound_speed": reference.residual_skill_percentile("pound_speed", rating_control, pound_speed_value),
        "hardship": reference.residual_skill_percentile("hardship", rating_control, hardship_value),
    }
    P = {
        "speed_pref": reference.percentile("speed_pref", features.get("speed")),
        "kiwami": reference.percentile("kiwami", features.get("kiwami_charts")),
    }

    growth_event = None
    if features.get("breakthrough"):
        tier = BREAKTHROUGH_TIER.get(str(features.get("old_breakthrough_type")), BREAKTHROUGH_TIER_DEFAULT)
        quality = R["hardship"]
        growth_event = tier * (0.75 + 0.25 * quality) if quality is not None else tier

    streak_pct = reference.percentile("streak", features.get("longest_streak")) if days_present else None

    scores: Dict[str, Optional[float]] = {}
    coverage: Dict[str, float] = {}
    scores["growth"], coverage["growth"] = _mean_available(
        [(growth_event, 0.60), (R["milestones"], 0.25), (P["kiwami"], 0.15)]
    )
    scores["precision"], coverage["precision"] = _mean_available(
        [(R["dondaful_share"], 0.40), (R["full_combo_share"], 0.35), (R["near_ok"], 0.25)]
    )
    scores["speed"], coverage["speed"] = _mean_available([(P["speed_pref"], 1.0)])
    scores["endurance"], coverage["endurance"] = _mean_available(
        [(play_pct, 0.55), (days_pct if days_present is not None else None, 0.30), (streak_pct, 0.15)]
    )
    scores["exploration"], coverage["exploration"] = _mean_available(
        [(R["charts_per_play"], 0.65), (R["months_per_active"], 0.35)]
    )
    scores["devotion"], coverage["devotion"] = _mean_available(
        [(R["obsession_share"], 0.40), (R["favorite_share"], 0.35), (R["challenge_share"], 0.25)]
    )
    scores["nocturnal"], coverage["nocturnal"] = _mean_available([(R["late_share"], 1.0)])

    return (
        {key: (round(value, 4) if value is not None else None) for key, value in scores.items()},
        {key: round(value, 3) for key, value in coverage.items()},
    )


def _min_evidence(features: Dict[str, Any], dimension: str) -> bool:
    if dimension == "growth":
        return bool(features.get("breakthrough")) or (features.get("milestone_count") or 0) > 0
    if dimension == "precision":
        return features.get("full_combo_share") is not None and (features.get("clear_charts") or 0) >= 10
    if dimension == "speed":
        return features.get("speed") is not None
    if dimension == "endurance":
        days = features.get("active_days")
        return (features.get("play_count") or 0) >= 300 and ((days or 0) >= 20 or days == 0)
    if dimension == "exploration":
        return (features.get("unique_charts") or 0) >= 40 and (features.get("monthly_count") or 0) >= 2
    if dimension == "devotion":
        return (features.get("obsession_days") or 0) >= 3 or (features.get("favorite_plays") or 0) >= 15
    if dimension == "nocturnal":
        return (features.get("late_days") or 0) >= 4
    return False


def forced_breakthrough(features: Dict[str, Any], reference: FinalTitleReference) -> bool:
    if not features.get("breakthrough") or str(features.get("old_breakthrough_type")) not in STRONG_BREAKTHROUGH_TYPES:
        return False
    rating = features.get("rating")
    rating_control = reference.percentile("rating", rating if rating is not None else reference.median("rating"))
    quality = reference.residual_skill_percentile("hardship", rating_control, features.get("hardship_max"))
    return quality is not None and quality >= FORCED_BREAKTHROUGH_QUALITY


def _ranking(scores: Dict[str, Optional[float]]) -> List[Tuple[str, float]]:
    scored = [(key, scores[key] if scores.get(key) is not None else -1.0) for key in DIMENSIONS]
    scored.sort(key=lambda item: (-item[1], DIMENSIONS.index(item[0])))
    return scored


def _model_b(
    features: Dict[str, Any],
    scores: Dict[str, Optional[float]],
    coverage: Dict[str, float],
    *,
    strong_dan: bool,
    strong_breakthrough: bool,
) -> Tuple[str, Optional[str], Optional[str]]:
    eligible = [
        (key, value)
        for key, value in _ranking(scores)
        if _min_evidence(features, key) and coverage.get(key, 0) >= PRIMARY_COVERAGE_GATE and value >= 0
    ]
    if not eligible:
        return "keeper", None, "no_evidence"
    if strong_dan:
        return "growth", None, "strong_dan_override"
    if strong_breakthrough and (scores.get("growth") or 0) >= FORCED_BREAKTHROUGH_MIN_GROWTH:
        return "growth", None, "strong_breakthrough_override"
    primary, top = eligible[0]
    runner_up = eligible[1][1] if len(eligible) > 1 else -1.0
    secondary = None
    for key, value in eligible:
        if key != primary and coverage.get(key, 0) >= SECONDARY_COVERAGE_GATE and value >= SECONDARY_SCORE_THRESHOLD:
            secondary = key
            break
    return primary, secondary, ("low_margin" if top - runner_up < LOW_MARGIN_GATE else None)


def l2_family(features: Dict[str, Any], state: DanState) -> str:
    best = state.best_mark
    if best is not None and best >= ARCHIVE_DAN_MIN_BEST_MARK:
        return "archive_dan"
    if (features.get("clear_charts") or 0) >= ARCHIVE_REGULAR_MIN_CLEARS:
        return "archive_regular"
    breadth = _ratio(features.get("unique_charts"), features.get("play_count")) or 0
    if breadth >= ARCHIVE_EXPLORER_MIN_BREADTH and (features.get("unique_songs") or 0) >= ARCHIVE_EXPLORER_MIN_SONGS:
        return "archive_explorer"
    if (features.get("clear_charts") or 0) >= ARCHIVE_COLLECTOR_MIN_CLEARS:
        return "archive_collector"
    return "keeper"


def resolve_final_title_key(primary: str, secondary: Optional[str]) -> str:
    """Whitelisted projection of the internal (primary, secondary) decision."""
    if secondary and (primary, secondary) in CURATED_PAIRS:
        key = f"final_{primary}_{secondary}"
    else:
        key = f"final_{primary}"
    if key not in FINAL_TITLE_KEYS:  # pragma: no cover - guard rail
        raise ValueError(f"unresolved final title key: {key!r}")
    return key


def _dan_evidence(event: Optional[DanEvent], *, strong: bool, state: DanState, is_l2_dan: bool) -> Tuple[str, Any]:
    if strong and event is not None:
        key = EVIDENCE_DAN_STRONG.get(int(event.mark or 0))
        if key is None:
            key = EVIDENCE_DAN_MAJOR_PROGRESS
        value: Dict[str, Any] = {"kind": event.kind, "dan": event.dan, "mark": event.mark}
        if event.kind == "grade":
            value["danBefore"] = event.dan_before
        if event.mark_before is not None:
            value["markBefore"] = event.mark_before
        if event.mark_after is not None:
            value["markAfter"] = event.mark_after
        return key, value
    if event is not None and event.is_mark_progression:
        return EVIDENCE_DAN_MARK_PROGRESS, {
            "kind": "mark",
            "dan": event.dan,
            "markBefore": event.mark_before,
            "markAfter": event.mark_after,
            "mark": event.mark_after,
        }
    if is_l2_dan:
        key = EVIDENCE_DAN_STANDING.get(int(state.best_mark or 0), EVIDENCE_DAN_STANDING[4])
        value = {
            "dan": state.best_mark_dan,
            "mark": state.best_mark,
            "source": "dojo" if state.has_dojo_detail else "profile",
        }
        return key, value
    return "", None


def _dimension_evidence(
    primary: str, features: Dict[str, Any], songs: Dict[str, Optional[str]]
) -> Tuple[str, Any]:
    plays = features.get("play_count") or 0
    days = features.get("active_days")
    if primary == "growth":
        milestones = features.get("milestone_count") or 0
        if milestones <= 0:
            # no milestone payload: fall back to the shipped breakthrough evidence line
            return "breakthrough", features.get("old_breakthrough_type")
        return EVIDENCE_DIMENSION["growth"], {
            "breakthrough": features.get("old_breakthrough_type"),
            "milestones": milestones,
        }
    if primary == "precision":
        return EVIDENCE_DIMENSION["precision"], {
            "fullCombo": features.get("full_combo_charts") or 0,
            "dondaful": features.get("dondaful_charts") or 0,
            "clears": features.get("clear_charts") or 0,
        }
    if primary == "speed":
        return EVIDENCE_DIMENSION["speed"], {"speed": features.get("speed"), "charts": features.get("speed_charts") or 0}
    if primary == "endurance":
        return EVIDENCE_DIMENSION["endurance"], {"plays": plays, "days": days}
    if primary == "exploration":
        return EVIDENCE_DIMENSION["exploration"], {
            "songs": features.get("unique_songs") or 0,
            "charts": features.get("unique_charts") or 0,
        }
    if primary == "devotion":
        song = songs.get("obsession") or songs.get("favorite")
        if not song:
            # without a resolvable song name the devotion line would render empty
            return EVIDENCE_DIMENSION["endurance"], {"plays": plays, "days": days}
        return EVIDENCE_DIMENSION["devotion"], {"song": song, "plays": features.get("obsession_plays") or 0}
    if primary == "nocturnal":
        return EVIDENCE_DIMENSION["nocturnal"], {"lateDays": features.get("late_days") or 0}
    return EVIDENCE_SPARSE, {"plays": plays, "days": days}


def build_final_title(
    *,
    summary: Dict[str, Any],
    features: Dict[str, Any],
    dan_state: DanState,
    dan_event: Optional[DanEvent],
    reference: FinalTitleReference,
    songs: Optional[Dict[str, Optional[str]]] = None,
) -> FinalTitleDecision:
    """Full FinalTitle decision for one user (deterministic)."""
    songs = songs or {}
    scores, coverage = dimension_scores(features, reference)

    severity = float(dan_event.severity) if dan_event is not None else 0.0
    strong_dan = is_strong_dan_achievement(dan_event)
    if severity > 0:
        base = scores.get("growth") or 0.0
        scores["growth"] = round(
            DAN_GROWTH_MERGE_BASE_WEIGHT * base + DAN_GROWTH_MERGE_EVENT_WEIGHT * max(base, severity), 4
        )

    play_count = features.get("play_count") or 0
    page_count = features.get("page_count") or 0
    if play_count < L1_MAX_PLAY_COUNT:
        level, primary, secondary, reason = "L1", "early", None, "sparse_L1"
    elif page_count <= L2_MAX_TYPED_PAGES:
        level, primary, secondary, reason = "L2", l2_family(features, dan_state), None, "sparse_L2"
    else:
        level = "L3"
        primary, secondary, reason = _model_b(
            features,
            scores,
            coverage,
            strong_dan=strong_dan,
            strong_breakthrough=forced_breakthrough(features, reference),
        )

    title_key = resolve_final_title_key(primary, secondary)

    evidence_key, evidence_value = _dan_evidence(
        dan_event, strong=strong_dan, state=dan_state, is_l2_dan=(level == "L2" and primary == "archive_dan")
    )
    if not evidence_key:
        if level == "L1" or primary == "keeper":
            evidence_key, evidence_value = EVIDENCE_SPARSE, {"plays": play_count, "days": features.get("active_days")}
        elif level == "L2" and primary != "archive_dan":
            evidence_key, evidence_value = EVIDENCE_DIMENSION["exploration"], {
                "songs": features.get("unique_songs") or 0,
                "charts": features.get("unique_charts") or 0,
            }
        else:
            evidence_key, evidence_value = _dimension_evidence(primary, features, songs)

    return FinalTitleDecision(
        title_key=title_key,
        evidence_key=evidence_key,
        evidence_value=evidence_value,
        level=level,
        primary=primary,
        secondary=secondary,
        reason=reason,
        scores=scores,
        coverage=coverage,
        severity=severity,
        strong_dan=strong_dan,
        dan_event_kind=dan_event.kind if dan_event else None,
    )


#: Audit value -> production value, asserted by the contract test.
PARAMETER_MANIFEST: Dict[str, Any] = {
    "dimensions": list(DIMENSIONS),
    "breakthroughTier.dan": BREAKTHROUGH_TIER["dan"],
    "breakthroughTier.default": BREAKTHROUGH_TIER_DEFAULT,
    "strongBreakthroughTypes": sorted(STRONG_BREAKTHROUGH_TYPES),
    "forcedBreakthroughQuality": FORCED_BREAKTHROUGH_QUALITY,
    "growthEventWeights": {"event": 0.60, "milestones": 0.25, "kiwami": 0.15},
    "precisionWeights": {"dondaful": 0.40, "fullCombo": 0.35, "nearOk": 0.25},
    "enduranceWeights": {"plays": 0.55, "days": 0.30, "streak": 0.15},
    "explorationWeights": {"chartsPerPlay": 0.65, "monthsPerActive": 0.35},
    "devotionWeights": {"obsession": 0.40, "favorite": 0.35, "challenge": 0.25},
    "primaryCoverageGate": PRIMARY_COVERAGE_GATE,
    "secondaryCoverageGate": SECONDARY_COVERAGE_GATE,
    "secondaryScoreThreshold": SECONDARY_SCORE_THRESHOLD,
    "lowMarginGate": LOW_MARGIN_GATE,
    "l1MaxPlayCount": L1_MAX_PLAY_COUNT,
    "l2MaxTypedPages": L2_MAX_TYPED_PAGES,
    "archiveDanMinBestMark": ARCHIVE_DAN_MIN_BEST_MARK,
    "archiveRegularMinClears": ARCHIVE_REGULAR_MIN_CLEARS,
    "archiveExplorer": {"minBreadth": ARCHIVE_EXPLORER_MIN_BREADTH, "minSongs": ARCHIVE_EXPLORER_MIN_SONGS},
    "archiveCollectorMinClears": ARCHIVE_COLLECTOR_MIN_CLEARS,
    "strongDanSeverity": STRONG_DAN_SEVERITY,
    "majorProgress": {"minLevels": MAJOR_PROGRESS_MIN_LEVELS, "minDan": MAJOR_PROGRESS_MIN_DAN},
    "danGrowthMerge": {"base": DAN_GROWTH_MERGE_BASE_WEIGHT, "event": DAN_GROWTH_MERGE_EVENT_WEIGHT},
    "curatedPairs": len(CURATED_PAIRS),
    "finalTitleKeys": len(FINAL_TITLE_KEYS),
    "danPresentationEvidence": sorted(STRONG_DAN_PRESENTATION_EVIDENCE),
}
