from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from taiko_bot.runtime.player.center import draw_dress, font_fallback


@pytest.mark.parametrize("layout", ["nickname", "full", "full_gold"])
def test_normalize_my_don_showcase_layout_accepts_supported_values(layout):
    assert draw_dress.normalize_my_don_showcase_layout(layout) == layout


def test_normalize_my_don_showcase_layout_defaults_and_rejects_unknown():
    assert draw_dress.normalize_my_don_showcase_layout(None) == "nickname"
    with pytest.raises(ValueError):
        draw_dress.normalize_my_don_showcase_layout("legacy")


def test_full_gold_only_maps_plate_two_to_gold():
    rarity_two = SimpleNamespace(plate_id=42, showcase_bg_plate_id=2)
    regular = SimpleNamespace(plate_id=1, showcase_bg_plate_id=1)

    assert draw_dress._resolve_my_don_showcase_plate_id(rarity_two, "nickname") == 2
    assert draw_dress._resolve_my_don_showcase_plate_id(rarity_two, "full") == 2
    assert draw_dress._resolve_my_don_showcase_plate_id(rarity_two, "full_gold") == 42
    assert draw_dress._resolve_my_don_showcase_plate_id(regular, "full_gold") == 1


def test_nickname_row_uses_user_nickname_and_forces_no_dan(monkeypatch):
    captured = {}

    def _fake_draw_player_info(**kwargs):
        captured.update(kwargs)
        return (10, 10, 110, 70)

    monkeypatch.setattr(draw_dress, "draw_player_info", _fake_draw_player_info)
    userdata = {
        "profile": {
            "mydon_name": "用户昵称",
            "gameCostume": {
                "mydon_name": "用户昵称",
                "title": "原称号",
                "titleplate_id": 0,
                "is_disp_dan_on": True,
            },
        }
    }

    draw_dress._render_my_don_nickname_title_row(
        userdata, "展示称号", 42, draw_dress.FONT_PATH
    )

    costume = captured["userdata"]["profile"]["gameCostume"]
    assert costume["title"] == "展示称号"
    assert costume["titleplate_id"] == 42
    assert costume["mydon_name"] == "用户昵称"
    assert captured["force_no_dan"] is True
    assert userdata["profile"]["gameCostume"]["title"] == "原称号"


def test_showcase_rows_keep_equal_gap_with_mixed_heights():
    heights = [60, 60, 84, 116]
    positions = draw_dress._build_my_don_showcase_row_positions(heights, 100, 8)
    gaps = [
        positions[index + 1] - positions[index] - heights[index]
        for index in range(len(heights) - 1)
    ]
    assert gaps == [8, 8, 8]


@pytest.mark.parametrize("plate_id", [0, 1, 2, 42])
def test_nickname_rows_from_mixed_source_heights_have_same_canvas_width(plate_id):
    userdata = {
        "profile": {
            "mydon_name": "NAME",
            "gameCostume": {
                "mydon_name": "NAME",
                "title": "TITLE",
                "titleplate_id": plate_id,
                "is_disp_dan_on": True,
                "dan_name": {"grade": "08", "level": "01"},
            },
        }
    }
    row = draw_dress._render_my_don_nickname_title_row(
        userdata, "TITLE", plate_id, draw_dress.FONT_PATH
    )
    assert row.width == draw_dress.PLAYER_PLATE_SIZE[0] + 4


def test_title_font_falls_back_for_magicatz_custom_title():
    primary_path = (
        draw_dress.FONT_PATH
        if draw_dress.FONT_PATH.exists()
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )
    if not primary_path.exists():
        pytest.skip("primary test font unavailable")
    font = draw_dress._get_font_by_path(primary_path, 18)
    title = "꜀(^. .^꜀ )꜆੭"

    runs = font_fallback.font_runs(title, font)

    assert "".join(text for text, _ in runs) == title
    assert any(run_font is not font for _, run_font in runs)
    assert all(
        font_fallback.font_supports_char(run_font, char)
        for text, run_font in runs
        for char in text
    )

    image = Image.new("RGBA", (400, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_dress._draw_text_center(
        draw,
        (0, 0, image.width, image.height),
        title,
        font,
        (255, 255, 255),
        (0, 0, 0),
        2,
    )
    assert image.getbbox() is not None
