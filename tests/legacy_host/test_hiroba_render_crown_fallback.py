from __future__ import annotations

from pathlib import Path

from taiko_application.score.b30_single import B30SingleRenderer

def pick_b30_crown_path(assets,entry):
    return B30SingleRenderer._pick_crown_path(None,assets,entry)
from taiko_application.score.drawinfo import ScoreInfoRenderer

def pick_tinfo_crown_path(assets, entry):
    return ScoreInfoRenderer._pick_crown_path(None, assets, entry)


def test_drawinfo_pick_crown_path_falls_back_to_hiroba_crown() -> None:
    entry = {"_hiroba_crown": "silver", "clear_cnt": 0, "full_combo_cnt": 0, "dondaful_combo_cnt": 0}
    path = pick_tinfo_crown_path("/tmp/assets", entry)
    assert path is not None
    assert path.endswith("/icons/crown/clear.png")


def test_b30_pick_crown_path_falls_back_to_hiroba_crown() -> None:
    entry = {"_hiroba_crown": "gold", "clear_cnt": 0, "full_combo_cnt": 0, "dondaful_combo_cnt": 0}
    path = pick_b30_crown_path(Path("/tmp/assets"), entry)
    assert path is not None
    assert path.as_posix().endswith("/icons/crown/full.png")
