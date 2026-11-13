from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple

from fuzzywuzzy import fuzz
from sakura_taiko_core.chart.visibility import is_song_publicly_visible

from .config import root
from .catalog import get_snapshot

SONG_DATA_PATH = root() / "songs/song_data.json"


def load_song_data(*, include_hidden: bool = False):
    with SONG_DATA_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if include_hidden or not isinstance(payload, list):
        return payload
    return [item for item in payload if isinstance(item, dict) and is_song_publicly_visible(item)]


def _query_music_with_mode(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> Tuple[List[List[Any]], Optional[str]]:
    # Clients retain separate version IDs and only expose their visible catalog.
    return get_snapshot(profile='client').query(name, fuzz.ratio,
        allow_partial=allow_partial, allow_fuzzy=allow_fuzzy)


def is_song_id_publicly_visible(song_id):
    from sakura_taiko_core.chart.visibility import is_song_id_publicly_visible as visible

    rows = load_song_data(include_hidden=True)
    index = {
        int(row["id"]): row
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).isdigit()
    }
    return visible(song_id, song_index=index)
