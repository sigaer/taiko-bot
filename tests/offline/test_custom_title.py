from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from taiko_bot.runtime.player.center import custom_title
from taiko_bot.runtime.player.center import draw_dress
from taiko_bot.runtime.player.center import song_title_showcase as showcase












def _record(
    title_id: int = 1,
    title_name: str = "自定义测试",
    achievement_type: str = "full_combo",
):
    return custom_title.CustomTitleRecord(
        id=title_id,
        title_name=title_name,
        title_key=custom_title.normalize_custom_title_key(title_name),
        song_id=100,
        difficulty_level=4,
        creator_type="bot-user",
        creator_id="onebot:1",
        creator_name="测试用户",
        source="bot-custom-title",
        group_id="1",
        group_name="测试群",
        created_at="2026-07-20 00:00:00",
        updated_at="2026-07-20 00:00:00",
        achievement_type=achievement_type,
    )


@pytest.mark.parametrize(
    "achievement_type,song_record,requirement,style",
    [
        ("clear", {"clear_cnt": 1}, "clear", "silver"),
        ("clear", {"dondaful_combo_cnt": 1}, "clear", "silver"),
        ("full_combo", {"full_combo_cnt": 1}, "full_combo", "gold"),
        ("full_combo", {"dondaful_combo_cnt": 1}, "full_combo", "gold"),
        ("all_perfect", {"dondaful_combo_cnt": 1}, "all_perfect", "rainbow"),
    ],
)
def test_custom_title_candidate_uses_fixed_achievement_style(
    monkeypatch, achievement_type, song_record, requirement, style
):
    monkeypatch.setattr(custom_title, "_official_title_keys", lambda: set())
    monkeypatch.setattr(custom_title, "_load_song_title_map", lambda: {100: "测试歌曲"})
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: ({}, {(100, 4): 9.7}, {}, {(100, 4): 10.0}),
    )
    songs = [{"song_no": 100, "level": 4, **song_record}]

    result = custom_title.list_custom_title_showcase_candidates(
        songs,
        records=[_record(achievement_type=achievement_type)],
    )

    assert len(result) == 1
    assert result[0].requirement_type == requirement
    assert result[0].plate_style == style
    assert result[0].source == "custom"
    assert result[0].custom_title_id == 1
    assert result[0].difficulty_level == 4
    assert result[0].const_value == 9.7


def test_custom_title_candidate_requires_clear(monkeypatch):
    monkeypatch.setattr(custom_title, "_official_title_keys", lambda: set())
    monkeypatch.setattr(custom_title, "_load_song_title_map", lambda: {100: "测试歌曲"})
    monkeypatch.setattr(showcase, "_load_song_lookup", lambda: ({}, {}, {}, {}))
    result = custom_title.list_custom_title_showcase_candidates(
        [{"song_no": 100, "level": 4, "clear_cnt": 0}], records=[_record()]
    )
    assert result == []


def test_custom_title_candidate_requires_configured_achievement(monkeypatch):
    monkeypatch.setattr(custom_title, "_official_title_keys", lambda: set())
    monkeypatch.setattr(custom_title, "_load_song_title_map", lambda: {100: "测试歌曲"})
    monkeypatch.setattr(showcase, "_load_song_lookup", lambda: ({}, {}, {}, {}))
    result = custom_title.list_custom_title_showcase_candidates(
        [{"song_no": 100, "level": 4, "clear_cnt": 1, "full_combo_cnt": 1}],
        records=[_record(achievement_type="all_perfect")],
    )
    assert result == []


def test_custom_title_candidate_hides_future_official_collision(monkeypatch):
    monkeypatch.setattr(custom_title, "_official_title_keys", lambda: {"自定义测试"})
    monkeypatch.setattr(showcase, "_load_song_lookup", lambda: ({}, {}, {}, {}))
    result = custom_title.list_custom_title_showcase_candidates(
        [{"song_no": 100, "level": 4, "clear_cnt": 1}], records=[_record()]
    )
    assert result == []


@pytest.mark.parametrize("style", ["silver", "gold", "rainbow"])
def test_custom_title_plate_assets_render_in_full_layout(style, tmp_path, monkeypatch):
    from PIL import Image
    plate = tmp_path / (style + ".png")
    Image.new("RGBA", (394, 80), (120, 100, 80, 255)).save(plate)
    monkeypatch.setitem(custom_title.CUSTOM_PLATE_PATHS, style, plate)
    preview = draw_dress._build_title_plate_showcase_preview(
        -1,
        394,
        plate_path_override=custom_title.CUSTOM_PLATE_PATHS[style],
    )
    assert preview is not None
    image, title_box = preview
    assert image.width == 394
    assert image.height > 0
    assert title_box == (0, 0, image.width, image.height)


def test_combined_showcase_uses_common_sort_and_limit(monkeypatch):
    official = showcase.ShowcaseTitle(
        title_name="官方全连",
        plate_id=2,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="official",
        song_names=("A",),
        song_ids=(1,),
        const_value=10.0,
        priority_const_value=10.0,
        is_multi_song=False,
    )
    custom = replace(
        official,
        title_name="自定义全良",
        source="custom",
        custom_title_id=8,
        requirement_type="all_perfect",
        plate_style="rainbow",
    )
    monkeypatch.setattr(showcase, "_collect_song_title_showcase_candidates", lambda _songs: [official])
    monkeypatch.setattr(custom_title, "list_custom_title_showcase_candidates", lambda _songs: [custom])

    result = showcase.list_song_title_showcase_candidates([], limit=1)

    assert result == [custom]


def test_default_showcase_suppresses_custom_title_for_same_song(monkeypatch):
    official = showcase.ShowcaseTitle(
        title_name="原有称号",
        plate_id=2,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="official",
        song_names=("测试歌曲",),
        song_ids=(100,),
        const_value=9.5,
        priority_const_value=9.5,
        is_multi_song=False,
    )
    custom = replace(
        official,
        title_name="自定义称号",
        song_ids=(101,),
        source="custom",
        custom_title_id=8,
        plate_style="gold",
    )
    custom_calls = []
    monkeypatch.setattr(
        showcase,
        "default_song_id_for_query",
        lambda song_id: 100 if int(song_id) in {100, 101} else int(song_id),
    )
    monkeypatch.setattr(
        showcase,
        "_collect_song_title_showcase_candidates",
        lambda _songs: [official],
    )
    monkeypatch.setattr(
        custom_title,
        "list_custom_title_showcase_candidates",
        lambda _songs: custom_calls.append(True) or [custom],
    )

    result = showcase.infer_song_title_showcase([], limit=5)

    assert result == [official]
    assert custom_calls == [True]


def test_default_showcase_keeps_custom_title_for_other_song(monkeypatch):
    official = showcase.ShowcaseTitle(
        title_name="原有称号",
        plate_id=2,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="official",
        song_names=("已有原称号歌曲",),
        song_ids=(100,),
        const_value=9.5,
        priority_const_value=9.5,
        is_multi_song=False,
    )
    custom = replace(
        official,
        title_name="仅有自定义称号",
        song_names=("只有自定义称号歌曲",),
        song_ids=(200,),
        source="custom",
        custom_title_id=8,
        plate_style="gold",
    )
    monkeypatch.setattr(
        showcase,
        "_collect_song_title_showcase_candidates",
        lambda _songs: [official],
    )
    monkeypatch.setattr(
        custom_title,
        "list_custom_title_showcase_candidates",
        lambda _songs: [custom],
    )

    result = showcase.infer_song_title_showcase([], limit=5)

    assert result == sorted([official, custom], key=showcase._showcase_sort_key)


def test_default_showcase_keeps_only_earliest_eligible_custom_title(monkeypatch):
    official = showcase.ShowcaseTitle(
        title_name="原有称号",
        plate_id=2,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="official",
        song_names=("已有原称号歌曲",),
        song_ids=(100,),
        const_value=9.5,
        priority_const_value=9.5,
        is_multi_song=False,
    )
    suppressed_earliest = replace(
        official,
        title_name="同歌自定义称号",
        source="custom",
        custom_title_id=1,
        plate_style="gold",
    )
    earliest_eligible = replace(
        official,
        title_name="最早的可展示自定义称号",
        song_names=("第一首只有自定义称号的歌曲",),
        song_ids=(200,),
        const_value=8.0,
        priority_const_value=8.0,
        source="custom",
        custom_title_id=3,
        plate_style="gold",
    )
    newer_eligible = replace(
        official,
        title_name="更新且优先级更高的自定义称号",
        song_names=("第二首只有自定义称号的歌曲",),
        song_ids=(300,),
        requirement_type="all_perfect",
        const_value=10.5,
        priority_const_value=10.5,
        source="custom",
        custom_title_id=8,
        plate_style="rainbow",
    )
    monkeypatch.setattr(
        showcase,
        "_collect_song_title_showcase_candidates",
        lambda _songs: [official],
    )
    monkeypatch.setattr(
        custom_title,
        "list_custom_title_showcase_candidates",
        lambda _songs: [newer_eligible, suppressed_earliest, earliest_eligible],
    )

    result = showcase.infer_song_title_showcase([], limit=5)

    assert result == sorted(
        [official, earliest_eligible],
        key=showcase._showcase_sort_key,
    )


def test_default_showcase_falls_back_to_custom_without_official_titles(monkeypatch):
    custom = showcase.ShowcaseTitle(
        title_name="自定义称号",
        plate_id=-1,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="custom",
        song_names=("测试歌曲",),
        song_ids=(100,),
        const_value=9.5,
        priority_const_value=9.5,
        is_multi_song=False,
        source="custom",
        custom_title_id=8,
        plate_style="gold",
    )
    monkeypatch.setattr(
        showcase,
        "_collect_song_title_showcase_candidates",
        lambda _songs: [],
    )
    monkeypatch.setattr(
        custom_title,
        "list_custom_title_showcase_candidates",
        lambda _songs: [custom],
    )

    assert showcase.infer_song_title_showcase([], limit=5) == [custom]


def test_explicit_showcase_selection_still_allows_custom_titles(monkeypatch):
    official = showcase.ShowcaseTitle(
        title_name="原有称号",
        plate_id=2,
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="official",
        song_names=("测试歌曲",),
        song_ids=(100,),
        const_value=9.5,
        priority_const_value=9.5,
        is_multi_song=False,
    )
    custom = replace(
        official,
        title_name="网页指定自定义称号一",
        source="custom",
        custom_title_id=8,
        plate_style="gold",
    )
    other_custom = replace(
        custom,
        title_name="网页指定自定义称号二",
        custom_title_id=9,
    )
    monkeypatch.setattr(
        showcase,
        "list_song_title_showcase_candidates",
        lambda _songs: [official, custom, other_custom],
    )

    result = showcase.resolve_song_title_showcase_selection(
        [],
        ["网页指定自定义称号一", "网页指定自定义称号二"],
    )

    assert result == [custom, other_custom]


@pytest.mark.parametrize(
    "layout,style,requirement",
    [
        ("nickname", "silver", "clear"),
        ("full", "gold", "full_combo"),
        ("full_gold", "rainbow", "all_perfect"),
    ],
)
def test_custom_title_renders_in_all_my_don_layouts(
    monkeypatch, layout, style, requirement
):
    item = showcase.ShowcaseTitle(
        title_name="很长但仍在限制以内的自定义称号用于验证文字截断",
        plate_id=-1,
        requirement_type=requirement,
        difficulty_scope="oni",
        condition_text="custom",
        song_names=("测试歌曲",),
        song_ids=(100,),
        const_value=10.0,
        priority_const_value=10.0,
        is_multi_song=False,
        source="custom",
        custom_title_id=1,
        difficulty_level=4,
        plate_style=style,
    )
    monkeypatch.setattr(draw_dress, "infer_song_title_showcase", lambda *_args, **_kwargs: [item])
    userdata = {
        "songs": [],
        "profile": {
            "mydon_name": "TEST",
            "gameCostume": {
                "mydon_name": "TEST",
                "title": "原称号",
                "titleplate_id": 0,
                "is_disp_dan_on": False,
            },
        },
    }
    font_path = draw_dress.FONT_PATH
    if not font_path.exists():
        font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not font_path.exists():
        pytest.skip("CJK font unavailable")

    panel = draw_dress._render_my_don_title_showcase_panel(
        userdata,
        font_path=font_path,
        showcase_layout=layout,
    )

    assert panel.width == draw_dress.MY_DON_CARD_WIDTH
    assert panel.height > 100
    if layout == "full_gold":
        assert draw_dress._resolve_my_don_showcase_plate_id(item, layout) == -1
