from __future__ import annotations


from sakura_taiko_core.score import single as domain_single

from pathlib import Path

from typing import Any, Dict, Iterable, List, Tuple

from .score_calculator import build_const_table, load_rating_config
from .duplicate_versions import build_duplicate_song_groups

ROOT_DIR = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

ASSETS_DIR = ROOT_DIR / "assets"

FONT_TITLE_PATH = ASSETS_DIR / "fonts" / "FZPW_GBK.ttf"

FONT_TITLE_FALLBACK_PATHS = [
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/SourceHanSansCN-Bold.otf"),
    Path("/usr/share/fonts/SourceHanSansCN-Medium.otf"),
    FONT_TITLE_PATH,
]

from taiko_bot.public_catalog_cache import rating_resources as _load_rating_resources

def _compute_rating_for_entry(entry, rating_index, const_table):
    return domain_single._compute_rating_for_entry(
        entry, rating_index, const_table, duplicate_groups=build_duplicate_song_groups()
    )

def build_song_index(song_db: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    index: Dict[int, Dict[str, Any]] = {}
    for song in song_db:
        try:
            song_id = int(song.get("id", 0))
        except Exception:
            continue
        index[song_id] = song
    return index
