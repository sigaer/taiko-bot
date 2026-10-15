"""Dan achievement events: grade progression + completion-mark progression.

Two event kinds, one unified value model:

``danGradeProgression``
    ``danBefore -> danAfter`` from the shipped breakthrough detector
    (``breakthrough.type == "dan"``).  Authoritative in-window source; the
    ``highscore_datetime`` field is **never** used to date an achievement -- the
    first import of an account pollutes those timestamps.

``danMarkProgression``
    same ``dan_id``, ``level_mark`` increased between the earliest and the latest
    *dojo-bearing* snapshot inside the annual window.  Both states must exist and
    carry dojo detail; a missing state is ignored and never treated as mark 0.

The union is the ``danAchievementEvent`` set; when a user has several candidates
the highest-severity event wins (deterministic, no random, no date preference).

Mark-progression coverage is low and biased (only a minority of snapshots carry
``dojo``), therefore it is **additive only**: detecting an event adds evidence,
failing to detect one proves nothing and must never remove or downgrade anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .dan_state import (
    COMPLETION_FULL_COMBO,
    COMPLETION_FULL_GOOD,
    COMPLETION_PASS,
    PASS_CLASS_GOLD,
    PASS_CLASS_RED,
    read_dan_state,
)
from .helpers import safe_int

#: completion quality table (frozen by Copy-3A Final Preflight)
QUALITY: Dict[Tuple[str, str], float] = {
    (PASS_CLASS_RED, COMPLETION_PASS): 0.55,
    (PASS_CLASS_RED, COMPLETION_FULL_COMBO): 0.68,
    (PASS_CLASS_RED, COMPLETION_FULL_GOOD): 0.80,
    (PASS_CLASS_GOLD, COMPLETION_PASS): 0.84,
    (PASS_CLASS_GOLD, COMPLETION_FULL_COMBO): 0.92,
    (PASS_CLASS_GOLD, COMPLETION_FULL_GOOD): 1.00,
}

#: strong-dan business predicate thresholds (see :func:`is_strong_dan_achievement`)
STRONG_DAN_SEVERITY = 0.55
MAJOR_PROGRESS_MIN_LEVELS = 6
MAJOR_PROGRESS_MIN_DAN = 13

EVENT_GRADE = "grade"
EVENT_MARK = "mark"


def completion_quality(mark: Optional[int]) -> float:
    """Quality modulation of a completion mark; mark 0 (未合格) is **not** an achievement."""
    if mark is None or int(mark) <= 0:
        return 0.0
    from .dan_state import classify

    pass_class, completion, _ = classify(int(mark))
    return QUALITY.get((pass_class, completion), 0.0)


@dataclass(frozen=True)
class DanEvent:
    kind: str
    dan: int
    mark: Optional[int]
    severity: float
    advance_levels: int = 0
    dan_before: int = 0
    dan_after: int = 0
    mark_before: Optional[int] = None
    mark_after: Optional[int] = None

    @property
    def is_mark_progression(self) -> bool:
        return self.kind == EVENT_MARK

    def sort_key(self) -> Tuple[float, int, int]:
        # deterministic: severity, then grade events before mark events, then higher dan
        return (self.severity, 1 if self.kind == EVENT_GRADE else 0, self.dan)


def event_severity(reference: Any, dan: int, mark: Optional[int]) -> float:
    """``danLevelPercentile(dan) x quality(passClass, completionClass)``."""
    if not dan or dan <= 0 or mark is None or int(mark) <= 0:
        return 0.0
    return float(reference.dan_level_rank(dan)) * completion_quality(mark)


def grade_event(breakthrough: Optional[Dict[str, Any]], reference: Any) -> Optional[DanEvent]:
    """Build the grade-progression event from the shipped breakthrough payload."""
    if not isinstance(breakthrough, dict) or breakthrough.get("type") != "dan":
        return None
    before = safe_int(breakthrough.get("danBefore"), 0) or 0
    after = safe_int(breakthrough.get("danAfter"), 0) or 0
    if after <= before:
        return None
    return DanEvent(
        kind=EVENT_GRADE,
        dan=after,
        mark=None,
        severity=0.0,  # filled in by the caller once the completion mark is known
        advance_levels=after - before,
        dan_before=before,
        dan_after=after,
    )


def mark_events(
    states: Iterable[Tuple[datetime, Dict[str, Any]]],
    *,
    start_at: datetime,
    end_at: datetime,
    reference: Any,
) -> List[DanEvent]:
    """Same-dan completion-mark increases inside the window (additive evidence only)."""
    observed: List[Tuple[datetime, Dict[int, int]]] = []
    for observed_at, payload in states:
        if observed_at is None or observed_at < start_at or observed_at >= end_at:
            continue
        state = read_dan_state(payload)
        if not state.has_dojo_detail:
            continue
        observed.append((observed_at, dict(state.marks)))
    if len(observed) < 2:
        return []
    observed.sort(key=lambda item: item[0])
    before_marks = observed[0][1]
    after_marks = observed[-1][1]

    events: List[DanEvent] = []
    for dan_id, mark_after in sorted(after_marks.items()):
        mark_before = before_marks.get(dan_id)
        if mark_before is None or mark_after <= mark_before:
            continue
        events.append(
            DanEvent(
                kind=EVENT_MARK,
                dan=dan_id,
                mark=mark_after,
                severity=event_severity(reference, dan_id, mark_after),
                advance_levels=0,
                dan_before=0,
                dan_after=0,
                mark_before=mark_before,
                mark_after=mark_after,
            )
        )
    return events


def select_dan_event(events: Sequence[DanEvent]) -> Optional[DanEvent]:
    """Highest-value event for one user (deterministic).

    A strong event always outranks a non-strong one, so a major grade climb is never
    hidden behind a same-dan mark improvement that happens to score higher; within the
    same strength the higher severity wins (grade events first on a tie).
    """
    if not events:
        return None
    return max(
        events,
        key=lambda event: (is_strong_dan_achievement(event), event.severity, event.sort_key()),
    )


def is_strong_dan_achievement(event: Optional[DanEvent]) -> bool:
    """Strong-dan business predicate.

    "A reliable dan result this year that is worth being highlighted": either the
    completion value is high enough (``severity >= 0.55``), which currently maps
    exactly to *九段以上 + 全连/全良* or *八段以上 + 金合格以上*, or the player climbed
    at least six dan levels and landed at 八段 or above.

    ``0.55`` is the frozen implementation threshold, not the product semantics.
    """
    if event is None:
        return False
    if event.severity >= STRONG_DAN_SEVERITY:
        return True
    return (
        event.kind == EVENT_GRADE
        and event.advance_levels >= MAJOR_PROGRESS_MIN_LEVELS
        and event.dan_after >= MAJOR_PROGRESS_MIN_DAN
    )


def dan_achievement_event(
    *,
    breakthrough: Optional[Dict[str, Any]],
    completion_mark: Optional[int],
    snapshots: Iterable[Tuple[datetime, Dict[str, Any]]],
    start_at: datetime,
    end_at: datetime,
    reference: Any,
) -> Optional[DanEvent]:
    """Unified ``danGradeProgression | danMarkProgression`` selection."""
    events: List[DanEvent] = []
    grade = grade_event(breakthrough, reference)
    if grade is not None:
        events.append(
            DanEvent(
                kind=grade.kind,
                dan=grade.dan,
                mark=completion_mark,
                severity=event_severity(reference, grade.dan_after, completion_mark),
                advance_levels=grade.advance_levels,
                dan_before=grade.dan_before,
                dan_after=grade.dan_after,
            )
        )
    events.extend(mark_events(snapshots, start_at=start_at, end_at=end_at, reference=reference))
    return select_dan_event(events)
