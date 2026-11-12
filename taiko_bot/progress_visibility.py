"""Shared song eligibility for progress lists and their score summaries."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Wahlap still reports these retired CN songs as shelf_status=0. Keep the
# progress policy consistent with the client's public visibility exclusions.
RETIRED_CN_SONG_IDS = frozenset({231, 678, 987, 1167, 1200})


def is_progress_song_available(song: Mapping[str, Any]) -> bool:
    if int(song["id"]) in RETIRED_CN_SONG_IDS:
        return False
    if song.get("shelf_status") not in (None, 0, "0", "未下架"):
        return False
    return not any(
        "双打" in str(song.get(field) or "")
        for field in ("song_name", "song_name_jp")
    )
