from __future__ import annotations


import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, Optional

from taiko_application.dani import DaniAssets, DaniInputs, DaniProgressService, DaniProgressRenderer

from taiko_application.dani.rating import build_rating_context

from taiko_application.dani.common import CURRENT_DANI_VERSION, DOJO_DATA_VERSION

from .dojo_score import build_dojo_score_map, get_dan_id_by_grade_name, normalize_dojo_scores

BASE = __import__("taiko_bot.runtime.player.center.recommendation_support.paths", fromlist=["ROOT"]).ROOT

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

def _load_history_dojo_payload_for_dan(history_snapshots, dan_id):
    if dan_id <= 0:
        return None
    for item in sorted(history_snapshots, key=lambda row: row['fileName'], reverse=True):
        payload = item['payload']
        if not isinstance(payload, dict) or 'dojo' not in payload:
            continue
        dojo_payload = normalize_dojo_scores(payload.get('dojo') or {})
        if dan_id in build_dojo_score_map(dojo_payload):
            return dojo_payload
    return None


def _load_dojo_progress_payload(
    userdata: Dict[str, Any], history_snapshots, dan_id: Optional[int], version: str
) -> Dict[str, Any]:
    if version != DOJO_DATA_VERSION:
        return normalize_dojo_scores({})

    dojo_payload = normalize_dojo_scores(userdata.get("dojo") or {})
    if dan_id and dan_id not in build_dojo_score_map(dojo_payload):
        history_payload = _load_history_dojo_payload_for_dan(history_snapshots, dan_id)
        if history_payload:
            return history_payload
    return dojo_payload

class _GradePayloads(dict):
    def __missing__(self, version):
        return _load_grade_payload(version)

def _parser_service():
    return DaniProgressService(DaniInputs(_GradePayloads(), [], [], {}))

def parse_dani_progress_request(text):
    return _parser_service().parse_dani_progress_request(text)

def _assets():
    return DaniAssets(
        UP_TEMPLATE_PATH, DOWN_TEMPLATE_PATH, DIFF_DIR, DANI_DIR, FONT_PATH, DDFONT_PATH
    )

def _load_inputs(grade, userdata):
    # The existing catalog acquisition and any upstream cache refresh stay in Sakura.
    song_catalog = json.loads(
        (BASE / "songs" / "song_data.json").read_text(encoding="utf-8")
    )
    roll_catalog = []
    if _parser_service().requires_roll_catalog(grade):
        from ..recommendation_support.score_line import load_scoreline_data

        roll_catalog = load_scoreline_data()
    rating_context = {}
    if _parser_service()._can_use_dynamic_rate_allocation(
        grade, userdata.get("songs", [])
    ):
        from ..recommendation_support.taiko_domain_adapter import identity_inputs
        from ..recommendation_support.duplicate_versions import build_duplicate_song_groups

        cfg = json.loads(
            (BASE / "songs" / "rating_structured_with_ids.json").read_text(
                encoding="utf-8"
            )
        )
        default_ids, _ = identity_inputs()
        rating_context = build_rating_context(
            cfg, default_ids=default_ids, duplicate_groups=build_duplicate_song_groups()
        )
    return DaniInputs(_GradePayloads(), song_catalog, roll_catalog, rating_context)

def render_dani_progress_image_bytes(
    user_id: int,
    grade_name: str,
    *,
    version: str = CURRENT_DANI_VERSION,
    explicit_version: bool = False,
    userdata=None,
    history_snapshots=(),
) -> bytes:
    version = str(version or CURRENT_DANI_VERSION)
    parser = _parser_service()
    try:
        grade = parser._load_grade_index(version).get(str(grade_name).strip())
    except KeyError:
        grade = None
    inputs = parser.inputs
    dojo_payload = {}
    dan_id = None
    if grade:
        # Preserve the accepted pre-Native reader behavior. No adoption of Phase 6 WIP.
        if userdata is not None:
            inputs = _load_inputs(grade, userdata)
            if version in {CURRENT_DANI_VERSION, DOJO_DATA_VERSION}:
                dan_id = get_dan_id_by_grade_name(str(grade["grade"]))
                dojo_payload = _load_dojo_progress_payload(
                    userdata, history_snapshots, dan_id, version
                )
    progress = DaniProgressService(inputs).prepare(
        user_id,
        grade_name,
        userdata=userdata,
        dojo_payload=dojo_payload,
        dan_id=dan_id,
        version=version,
        explicit_version=explicit_version,
    )
    return DaniProgressRenderer(_assets()).render(progress)
