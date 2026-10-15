"""FinalTitle integration: one call that turns a built summary + window into a title.

Public output is exactly ``{titleKey, evidenceKey, evidenceValue}``; every other
value stays internal (see :class:`finaltitle_model.FinalTitleDecision`).

Deferred by decision (do NOT wire these here):

* ``danEffort`` (three-course shared practice / sync ratio) -- research only,
  the snapshot coverage is ~13% and G1 == G2 in simulation.
* ``monthly.visibleNarrative``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

from .dan_events import dan_achievement_event
from .dan_state import DanState, read_dan_state
from .finaltitle_features import summary_features
from .finaltitle_model import FinalTitleDecision, build_final_title
from .finaltitle_reference import FinalTitleReference, load_reference
from .helpers import safe_int


def _song_names(summary: Dict[str, Any]) -> Dict[str, Optional[str]]:
    sections = summary.get("sections") or {}

    def name_of(key: str) -> Optional[str]:
        data = (sections.get(key) or {}).get("data") or {}
        value = data.get("name") or data.get("songName")
        return str(value) if value else None

    return {"favorite": name_of("favoriteSong"), "obsession": name_of("obsessionSong")}


def compute_final_title(
    summary: Dict[str, Any],
    *,
    dan_state: DanState,
    snapshots: Iterable[Tuple[datetime, Dict[str, Any]]],
    start_at: datetime,
    end_at: datetime,
    reference: Optional[FinalTitleReference] = None,
    features: Optional[Dict[str, Any]] = None,
) -> FinalTitleDecision:
    """Deterministic FinalTitle decision for one annual summary."""
    ref = reference or load_reference()
    row = features if features is not None else summary_features(summary)

    breakthrough = ((summary.get("sections") or {}).get("breakthrough") or {}).get("data") or {}
    dan_after = safe_int(breakthrough.get("danAfter"), 0) or 0
    completion_mark = dan_state.mark_of(dan_after) if dan_after else None

    event = dan_achievement_event(
        breakthrough=breakthrough,
        completion_mark=completion_mark,
        snapshots=snapshots,
        start_at=start_at,
        end_at=end_at,
        reference=ref,
    )
    return build_final_title(
        summary=summary,
        features=row,
        dan_state=dan_state,
        dan_event=event,
        reference=ref,
        songs=_song_names(summary),
    )


def read_state_from_payload(payload: Any) -> DanState:
    return read_dan_state(payload)
