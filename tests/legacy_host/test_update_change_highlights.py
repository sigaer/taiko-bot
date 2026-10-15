from __future__ import annotations

from pathlib import Path

import taiko_bot.runtime.player.center.draw_dress as draw_dress


def _song(song_no: int, *, full_combo: int = 0, dondaful: int = 0) -> dict:
    return {
        "song_no": song_no,
        "level": 4,
        "clear_cnt": int(full_combo > 0 or dondaful > 0),
        "full_combo_cnt": full_combo,
        "dondaful_combo_cnt": dondaful,
    }


def test_full_combo_and_all_perfect_sections_are_highlighted(monkeypatch):
    monkeypatch.setattr(
        draw_dress,
        "_load_song_display_map",
        lambda: {
            1: {"title": "全良曲", "levels": {4: 10}},
            2: {"title": "全连曲", "levels": {4: 9}},
        },
    )
    previous = {(1, 4): _song(1), (2, 4): _song(2)}
    current = {
        (1, 4): _song(1, full_combo=1, dondaful=1),
        (2, 4): _song(2, full_combo=1),
    }

    achievement_sections, _ = draw_dress._collect_change_sections(previous, current)

    assert {
        section["label"]: section.get("emphasis")
        for section in achievement_sections
    } == {
        "全良(0->1)": "all_perfect",
        "全连(0->1)": "full_combo",
    }


def test_dojo_sections_keep_the_dojo_highlight():
    previous = {
        "scores": [
            {
                "dan_id": 1,
                "grade": "五级",
                "level_mark": 0,
                "songs": [],
            }
        ]
    }
    current = {
        "scores": [
            {
                "dan_id": 1,
                "grade": "五级",
                "level_mark": 5,
                "songs": [],
            }
        ]
    }

    achievement_sections, _ = draw_dress._collect_dojo_change_sections(
        previous, current
    )

    assert achievement_sections[0]["label"] == "取得全连金合格"
    assert achievement_sections[0]["emphasis"] == "dojo"


def test_highlight_cards_use_distinct_visual_treatments():
    sections = [
        {
            "label": "全良(0->1)",
            "emphasis": "all_perfect",
            "items": [{"title": "全良曲", "level": 4}],
        },
        {
            "label": "全连(0->1)",
            "emphasis": "full_combo",
            "items": [{"title": "全连曲", "level": 4}],
        },
        {
            "label": "取得全连金合格",
            "emphasis": "dojo",
            "items": [{"title": "十段", "emphasis": "dojo"}],
        },
    ]

    image = draw_dress._render_change_column(
        "本次更新变化 - 成就",
        sections,
        "无变化",
        font_path=Path("/usr/share/fonts/SourceHanSansCN-Medium.otf"),
    )

    card_x = 30
    first_card_y = 70
    second_card_y = first_card_y + 94 + 8
    third_card_y = second_card_y + 94 + 8
    assert image.getpixel((card_x, first_card_y)) == (255, 248, 218, 255)
    assert image.getpixel((card_x, second_card_y)) == (255, 239, 241, 255)
    assert image.getpixel((card_x, third_card_y)) == (244, 239, 255, 255)
    assert all(
        "badge" not in style
        for style in draw_dress.CHANGE_HIGHLIGHT_STYLES.values()
    )
