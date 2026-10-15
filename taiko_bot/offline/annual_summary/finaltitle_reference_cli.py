"""CLI helper: rebuild the frozen FinalTitle population reference from a built corpus.

The reference is a *frozen model parameter* (percentile / residual tables over the
annual population).  Regenerate it when the population definition changes:

    python3 -m taiko_bot.offline.annual_summary finaltitle-reference \\
        --summaries-dir <dir of built summary json> \\
        --userdata-dir <userdata dir> \\
        --output plugins/utils/annual_summary/data/finaltitle_reference_v1.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import USERDATA_DIR
from .dan_state import read_dan_state
from .finaltitle_features import summary_features
from .finaltitle_reference import build_reference


def build_finaltitle_reference(
    summaries_dir: str | Path,
    userdata_dir: str | Path = USERDATA_DIR,
    *,
    generated_at: Optional[str] = None,
    source: str = "",
) -> Dict[str, Any]:
    rows: list[Dict[str, Any]] = []
    attained: Dict[str, int] = {}
    for path in sorted(Path(summaries_dir).glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        summary = payload.get("summary") if isinstance(payload, dict) and "summary" in payload else payload
        if not isinstance(summary, dict) or "sections" not in summary:
            continue
        user_id = path.stem
        row = summary_features(summary)
        row["id"] = user_id
        rows.append(row)

        payload_path = Path(userdata_dir) / f"{user_id}data.json"
        attained[user_id] = 0
        if payload_path.exists():
            try:
                attained[user_id] = read_dan_state(json.loads(payload_path.read_text(encoding="utf-8"))).attained_dan
            except (OSError, ValueError):
                attained[user_id] = 0

    reference = build_reference(
        rows,
        attained_dan_by_id=attained,
        source=source or f"{Path(summaries_dir).name} ({len(rows)} built summaries)",
        generated_at=generated_at,
    )
    reference["population"]["summariesDir"] = str(summaries_dir)
    return reference
