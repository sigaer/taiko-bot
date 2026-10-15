"""Public grade configuration and drawing helpers still consumed by dani_overview."""

from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from taiko_application.dani import (
    DaniAssets,
    DaniInputs,
    DaniProgressService,
    DaniProgressRenderer,
)
from taiko_application.dani.common import (
    CURRENT_DANI_VERSION,
    DOJO_DATA_VERSION,
    SUPPORTED_DANI_VERSIONS,
    BLACK,
    CARD_STROKE,
    TEXT_MAIN,
    TEXT_SUB,
    WHITE,
    _difficulty_level,
    _safe_int,
    _safe_float,
    _safe_optional_int,
    _normalize_song_title,
)

BASE = Path(str(_runtime_root()))
HISTORY_CONFIG_PATH = BASE / "songs" / "grade_dojo_nijiiro_history_simple.json"
VERSION_CONFIG_PATHS = {
    v: BASE / "songs" / f"grade_dojo_nijiiro_{v}_simple.json" for v in ("2025", "2026")
}
UP_TEMPLATE_PATH = BASE / "assets" / "templates" / "dani_up.png"
DOWN_TEMPLATE_PATH = BASE / "assets" / "templates" / "dani_down.png"
DIFF_DIR = BASE / "assets" / "icons" / "diff"
DANI_DIR = BASE / "assets" / "icons" / "dani"
FONT_PATH = BASE / "assets" / "fonts" / "FZPW_GBK.ttf"
DDFONT_PATH = BASE / "assets" / "fonts" / "DDFont.ttf"


@lru_cache(maxsize=8)
def _load_grade_payload(version: str) -> Dict[str, Any]:
    version = str(version or CURRENT_DANI_VERSION)
    version_config_path = VERSION_CONFIG_PATHS.get(version)
    if version_config_path:
        payload = json.loads(version_config_path.read_text(encoding="utf-8"))
        return {
            "year": str(payload.get("year") or version),
            "grades": payload.get("grades") or [],
        }

    history_payload = json.loads(HISTORY_CONFIG_PATH.read_text(encoding="utf-8"))
    versions = history_payload.get("versions") or {}
    version_payload = versions.get(version)
    if not isinstance(version_payload, dict):
        raise KeyError(version)
    return version_payload


class _GradePayloads(dict):
    def __missing__(self, version):
        return _load_grade_payload(version)


def _parser_service():
    return DaniProgressService(DaniInputs(_GradePayloads(), [], [], {}))


def _resolved_gold_conditions(grade):
    return _parser_service()._resolved_gold_conditions(grade)


def _assets():
    return DaniAssets(
        UP_TEMPLATE_PATH, DOWN_TEMPLATE_PATH, DIFF_DIR, DANI_DIR, FONT_PATH, DDFONT_PATH
    )


# Existing dani_overview imports drawing helpers. Delegate to the same implementation;
# this is an adapter compatibility surface, not a second renderer.
_overview_renderer = DaniProgressRenderer(_assets())
_load_font = _overview_renderer._load_font
_load_ddfont = _overview_renderer._load_ddfont
_load_rgba = _overview_renderer._load_rgba
_diff_icon_path = _overview_renderer._diff_icon_path
_draw_text_with_stroke = _overview_renderer._draw_text_with_stroke
_paste_fit = _overview_renderer._paste_fit
_truncate_text = _overview_renderer._truncate_text
