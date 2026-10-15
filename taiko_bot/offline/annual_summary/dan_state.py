"""Canonical dan (段位道場) state reader.

Semantics are fixed by the Copy-3A Final Preflight audit and must not drift:

* ``dojo.levelList[dan_id - 1]`` is the authoritative per-dan completion mark.
  ``dan_id`` runs 1..19 (五级..达人); slot index 19 (dan_id 20) is an unused ``-1``
  sentinel.  Verified against every ``dojo.scores[]`` row in the corpus:
  ``scores[].level_mark == levelList[dan_id - 1]`` with zero mismatches.
* Slot values: ``None`` = no data, ``-1`` = not attempted, ``0`` = attempted but
  NOT passed, ``1..6`` = the completion mark.  ``None`` / ``-1`` must never be
  read as ``0`` -- "no record" and "record exists with mark 0" are different
  states and are kept apart in :class:`DanState`.
* When the slot has no data the verified fallback order is
  ``dojo.scores[dan_id].highscore_dan_result`` and then the profile
  (``gameCostume.dan_name.level``) for the *attained* dan only.  The profile
  fallback may describe an **existing/historical** result; it must never be used
  to claim an in-window achievement.
* ``profile.gameCostume.got_dan_max`` (1..19) is the highest dan actually passed.

Completion-class business semantics (locked):

===== ========================== ===========
mark  meaning                    isKanzui
===== ========================== ===========
0     未合格                      false
1     赤合格                      false
2     赤合格 + 全连               **true**
3     赤合格 + 全良               false
4     金合格（含不可）            false
5     金合格 + 全连               **true**
6     金合格 + 全良               false
===== ========================== ===========

``isKanzui(mark)`` is ``mark in (2, 5)`` -- mark 2 is a 金粹 too.  Any code that
writes ``kanzui = mark == 5`` is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .helpers import safe_int

LEVEL_COUNT = 19

MARK_SOURCE_LEVEL_LIST = "dojo_level_list"
MARK_SOURCE_SCORE = "dojo_score"
MARK_SOURCE_PROFILE = "profile_fallback"
MARK_SOURCE_NONE = "none"

PASS_CLASS_NONE = "none"
PASS_CLASS_RED = "red"
PASS_CLASS_GOLD = "gold"

COMPLETION_NONE = "none"
COMPLETION_PASS = "pass"
COMPLETION_FULL_COMBO = "full_combo"
COMPLETION_FULL_GOOD = "full_good"

#: mark -> (passClass, completionClass)
_COMPLETION_TABLE: Dict[int, Tuple[str, str]] = {
    0: (PASS_CLASS_NONE, COMPLETION_NONE),
    1: (PASS_CLASS_RED, COMPLETION_PASS),
    2: (PASS_CLASS_RED, COMPLETION_FULL_COMBO),
    3: (PASS_CLASS_RED, COMPLETION_FULL_GOOD),
    4: (PASS_CLASS_GOLD, COMPLETION_PASS),
    5: (PASS_CLASS_GOLD, COMPLETION_FULL_COMBO),
    6: (PASS_CLASS_GOLD, COMPLETION_FULL_GOOD),
}


def classify(mark: Optional[int]) -> Tuple[str, str, bool]:
    """Return ``(passClass, completionClass, isKanzui)`` for an authoritative mark."""
    if mark is None:
        return PASS_CLASS_NONE, COMPLETION_NONE, False
    pass_class, completion = _COMPLETION_TABLE.get(int(mark), (PASS_CLASS_NONE, COMPLETION_NONE))
    return pass_class, completion, is_kanzui(mark)


def is_kanzui(mark: Optional[int]) -> bool:
    """金粹 = 全连档: mark 2 (赤合格+全连) **and** mark 5 (金合格+全连)."""
    return mark in (2, 5)


@dataclass(frozen=True)
class DanState:
    """Canonical standing/history dan state for one payload."""

    marks: Dict[int, int] = field(default_factory=dict)
    mark_sources: Dict[int, str] = field(default_factory=dict)
    has_dojo_detail: bool = False
    got_dan_max: int = 0
    attained_dan: int = 0
    attained_mark: Optional[int] = None
    attained_mark_source: str = MARK_SOURCE_NONE
    best_mark: Optional[int] = None
    best_mark_dan: Optional[int] = None
    profile_dan_max: int = 0
    profile_dan_level: Optional[int] = None

    # ---------------------------------------------------------------- states
    @property
    def record_exists(self) -> bool:
        """True when the account carries *any* dan information at all."""
        return self.has_dojo_detail or self.got_dan_max > 0 or self.profile_dan_max > 0

    @property
    def no_dojo_record(self) -> bool:
        """No dan information whatsoever -- **not** the same as 未合格."""
        return not self.record_exists

    @property
    def never_passed(self) -> bool:
        """A dojo record exists but no dan was ever passed (the real mark-0 state)."""
        return self.record_exists and self.attained_dan == 0

    @property
    def class_known(self) -> bool:
        return self.attained_mark is not None

    @property
    def standing_pass_class(self) -> str:
        return classify(self.attained_mark)[0]

    @property
    def standing_completion_class(self) -> str:
        return classify(self.attained_mark)[1]

    @property
    def standing_is_kanzui(self) -> bool:
        return is_kanzui(self.attained_mark)

    def mark_of(self, dan_id: int) -> Optional[int]:
        return self.marks.get(int(dan_id))

    def snapshot(self) -> Dict[str, Any]:
        """Serialisable view used by the FinalTitle model / contract tests."""
        return {
            "attainedDan": self.attained_dan,
            "attainedMark": self.attained_mark,
            "attainedMarkSource": self.attained_mark_source,
            "bestMark": self.best_mark,
            "bestMarkDan": self.best_mark_dan,
            "hasDojoDetail": self.has_dojo_detail,
            "recordExists": self.record_exists,
            "noDojoRecord": self.no_dojo_record,
            "neverPassed": self.never_passed,
        }


def _latest_score_record(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    return max(records, key=lambda item: str(item.get("highscore_datetime") or item.get("update_datetime") or ""))


def read_dan_state(payload: Any) -> DanState:
    """Read the canonical dan state from a raw/normalised userdata payload."""
    payload = payload if isinstance(payload, dict) else {}
    dojo = payload.get("dojo") if isinstance(payload.get("dojo"), dict) else {}
    level_list = list(dojo.get("levelList") or [])
    scores = [row for row in (dojo.get("scores") or []) if isinstance(row, dict)]

    costume = ((payload.get("profile") or {}).get("gameCostume") or {}) if isinstance(payload.get("profile"), dict) else {}
    got_dan_max = safe_int(costume.get("got_dan_max"), 0) or 0
    dan_name = costume.get("dan_name") if isinstance(costume.get("dan_name"), dict) else {}
    profile_dan_max = safe_int(dan_name.get("grade"), 0) or 0
    profile_dan_level = safe_int(dan_name.get("level"), -1)
    if profile_dan_level is not None and profile_dan_level < 0:
        profile_dan_level = None
    if not profile_dan_max:
        profile_dan_max = got_dan_max

    by_dan: Dict[int, List[Dict[str, Any]]] = {}
    for row in scores:
        dan_id = safe_int(row.get("dan_id"), 0)
        if dan_id:
            by_dan.setdefault(dan_id, []).append(row)

    marks: Dict[int, int] = {}
    sources: Dict[int, str] = {}
    for dan_id in range(1, LEVEL_COUNT + 1):
        raw = level_list[dan_id - 1] if dan_id - 1 < len(level_list) else None
        raw_value = safe_int(raw, -1)
        if raw is not None and raw_value >= 0:
            marks[dan_id] = raw_value
            sources[dan_id] = MARK_SOURCE_LEVEL_LIST
            continue
        records = by_dan.get(dan_id)
        if records:
            mark = safe_int(_latest_score_record(records).get("highscore_dan_result"), -1)
            if mark >= 0:
                marks[dan_id] = mark
                sources[dan_id] = MARK_SOURCE_SCORE
                continue
        # profile fallback: only for the attained dan, and only for standing/history.
        if profile_dan_level is not None and dan_id == profile_dan_max:
            marks[dan_id] = profile_dan_level
            sources[dan_id] = MARK_SOURCE_PROFILE

    passed = [dan_id for dan_id, mark in marks.items() if mark >= 1]
    attained_dan = max(passed) if passed else (got_dan_max or profile_dan_max)
    attained_mark = marks.get(attained_dan) if attained_dan else None
    best: Optional[Tuple[int, int]] = None
    for dan_id, mark in marks.items():
        if mark >= 1 and (best is None or mark > best[0]):
            best = (mark, dan_id)

    return DanState(
        marks=dict(sorted(marks.items())),
        mark_sources=dict(sorted(sources.items())),
        has_dojo_detail=bool(level_list) or bool(scores),
        got_dan_max=got_dan_max,
        attained_dan=attained_dan,
        attained_mark=attained_mark,
        attained_mark_source=sources.get(attained_dan, MARK_SOURCE_NONE) if attained_dan else MARK_SOURCE_NONE,
        best_mark=best[0] if best else None,
        best_mark_dan=best[1] if best else None,
        profile_dan_max=profile_dan_max,
        profile_dan_level=profile_dan_level,
    )


def dan_label(dan_id: Optional[int]) -> Optional[str]:
    """Chinese dan label used by the *generator-side* debug output only.

    Locale rendering happens in the viewer (``formatDanGrade``); the summary
    carries numeric dan ids so both languages stay correct.
    """
    from .helpers import DAN_GRADE_NAMES

    if not dan_id:
        return None
    return DAN_GRADE_NAMES.get(int(dan_id))
