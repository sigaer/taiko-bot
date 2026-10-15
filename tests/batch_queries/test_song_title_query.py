from __future__ import annotations

from io import BytesIO

from PIL import Image

from taiko_bot.runtime.player.center.display_host_support import custom_title
from taiko_bot.runtime.player.center import song_title_query
from taiko_bot.runtime.player.center.display_host_support import song_title_showcase as showcase


def _showcase_title(
    title_name: str,
    *,
    source: str = "official",
    requirement_type: str = "full_combo",
    difficulty_scope: str = "oni",
) -> showcase.ShowcaseTitle:
    return showcase.ShowcaseTitle(
        title_name=title_name,
        plate_id=42 if source == "official" else -1,
        requirement_type=requirement_type,
        difficulty_scope=difficulty_scope,
        condition_text="测试条件",
        song_names=("测试歌曲",),
        song_ids=(100,),
        const_value=10.0,
        priority_const_value=10.0,
        is_multi_song=False,
        source=source,
        custom_title_id=1 if source == "custom" else None,
        difficulty_level=4 if source == "custom" else None,
        plate_style="gold" if source == "custom" else None,
    )


def test_parse_song_title_query_accepts_spaced_and_compact_forms():
    assert song_title_query.parse_song_title_query("查称号 刻龙") == "刻龙"
    assert song_title_query.parse_song_title_query("查称号刻龙") == "刻龙"
    assert song_title_query.SONG_TITLE_QUERY_PATTERN.match("查称号")
    assert song_title_query.parse_song_title_query("查称号") is None


def test_list_official_titles_for_song_matches_relation_song_id(monkeypatch):
    relations = (
        showcase.SongTitleRelation("相关称号", ("测试歌曲",), "full_combo", "oni", "条件", 1),
        showcase.SongTitleRelation("无关称号", ("其他歌曲",), "clear", "oni", "条件", 2),
    )
    monkeypatch.setattr(showcase, "load_song_title_relations", lambda: relations)
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: ({"测试歌曲": (100,), "其他歌曲": (200,)}, {}, {}, {}),
    )
    monkeypatch.setattr(showcase, "_song_lookup_keys", lambda value: (value,))
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args: 42)
    monkeypatch.setattr(showcase, "_relation_showcase_bg_plate_id", lambda _name, plate_id: plate_id)

    result = showcase.list_official_titles_for_song(100)

    assert [item.title_name for item in result] == ["相关称号"]
    assert result[0].song_ids == (100,)


def test_list_custom_titles_for_song_does_not_require_achievement(monkeypatch):
    record = custom_title.CustomTitleRecord(
        id=1,
        title_name="自定义测试",
        title_key="自定义测试",
        song_id=100,
        difficulty_level=5,
        creator_type="bot-user",
        creator_id="1",
        creator_name="测试者",
        source="bot-custom-title",
        group_id=None,
        group_name=None,
        created_at="2026-07-21 00:00:00",
        updated_at="2026-07-21 00:00:00",
        achievement_type="all_perfect",
    )
    monkeypatch.setattr(custom_title, "_official_title_keys", lambda: set())
    monkeypatch.setattr(custom_title, "_load_song_title_map", lambda: {100: "测试歌曲"})
    monkeypatch.setattr(showcase, "_load_song_lookup", lambda: ({}, {}, {}, {}))

    result = custom_title.list_custom_titles_for_song(100, records=[record])

    assert len(result) == 1
    assert result[0].title_name == "自定义测试"
    assert result[0].requirement_type == "all_perfect"
    assert result[0].plate_style == "rainbow"


def test_find_songs_by_title_supports_official_and_custom_titles(monkeypatch):
    relations = (
        showcase.SongTitleRelation(
            "官方称号", ("官方歌曲",), "full_combo", "oni", "条件", 1
        ),
    )
    custom_record = custom_title.CustomTitleRecord(
        id=1,
        title_name="自定义称号",
        title_key="自定义称号",
        song_id=200,
        difficulty_level=4,
        creator_type="bot-user",
        creator_id="1",
        creator_name="测试者",
        source="bot-custom-title",
        group_id=None,
        group_name=None,
        created_at="2026-07-21 00:00:00",
        updated_at="2026-07-21 00:00:00",
    )
    monkeypatch.setattr(song_title_query, "load_song_title_relations", lambda: relations)
    monkeypatch.setattr(song_title_query, "list_custom_titles", lambda: [custom_record])
    monkeypatch.setattr(
        song_title_query,
        "_load_song_lookup",
        lambda: ({"官方歌曲": (100,)}, {}, {}, {}),
    )
    monkeypatch.setattr(song_title_query, "_song_lookup_keys", lambda value: (value,))
    monkeypatch.setattr(
        song_title_query,
        "_load_song_id_title_map",
        lambda: {100: "官方歌曲", 200: "自定义歌曲"},
    )

    official = song_title_query.find_songs_by_title("官方称号")
    custom = song_title_query.find_songs_by_title("自定义称号")

    assert [(item.song_id, item.song_title, item.source) for item in official] == [
        (100, "官方歌曲", "official")
    ]
    assert [(item.song_id, item.song_title, item.source) for item in custom] == [
        (200, "自定义歌曲", "custom")
    ]


def test_title_fuzzy_match_and_acceptance_threshold(monkeypatch):
    monkeypatch.setattr(song_title_query, "load_song_title_relations", lambda: ())
    monkeypatch.setattr(
        song_title_query,
        "list_custom_titles",
        lambda: [
            custom_title.CustomTitleRecord(
                id=1,
                title_name="星空の冒険者",
                title_key="星空の冒険者",
                song_id=300,
                difficulty_level=4,
                creator_type="bot-user",
                creator_id="1",
                creator_name="测试者",
                source="bot-custom-title",
                group_id=None,
                group_name=None,
                created_at="2026-07-21 00:00:00",
                updated_at="2026-07-21 00:00:00",
            )
        ],
    )
    monkeypatch.setattr(song_title_query, "_load_song_lookup", lambda: ({}, {}, {}, {}))
    monkeypatch.setattr(
        song_title_query,
        "_load_song_id_title_map",
        lambda: {300: "测试歌曲"},
    )

    result = song_title_query.find_songs_by_title("星空の冒险者")

    assert result[0].match_mode == "fuzzy"
    assert result[0].song_id == 300
    assert song_title_query.is_accepted_similarity(75)
    assert song_title_query.is_accepted_similarity(0.75)
    assert not song_title_query.is_accepted_similarity(74)


def test_song_and_title_matches_are_accepted_independently_at_threshold():
    title_match = song_title_query.TitleSongMatch(
        title_name="近似称号",
        song_id=200,
        song_title="称号对应歌曲",
        source="official",
        match_mode="fuzzy",
        similarity=0.75,
    )

    accepted = song_title_query.collect_accepted_song_matches(
        [[100, "精确歌名"]],
        [title_match],
    )

    assert accepted == {100: "精确歌名", 200: "称号对应歌曲"}


def test_fuzzy_matches_below_threshold_only_produce_suggestions():
    title_match = song_title_query.TitleSongMatch(
        title_name="低相似称号",
        song_id=200,
        song_title="称号对应歌曲",
        source="custom",
        match_mode="fuzzy",
        similarity=0.74,
    )
    song_results = [[100, "低相似歌曲", 74]]

    assert not song_title_query.collect_accepted_song_matches(
        song_results,
        [title_match],
    )
    assert song_title_query.build_rejected_match_suggestions(
        song_results,
        [title_match],
    ) == [
        "歌曲：低相似歌曲（匹配度 0.74）",
        "称号：低相似称号（匹配度 0.74）",
    ]


def test_render_song_title_query_uses_nickname_layout_for_both_sections(monkeypatch):
    calls = []

    def fake_render(nickname, title_name, plate_id, **kwargs):
        calls.append((nickname, title_name, plate_id, kwargs.get("plate_path_override")))
        return Image.new("RGBA", (350, 70), (255, 255, 255, 255))

    monkeypatch.setattr(song_title_query, "render_nickname_title_row", fake_render)
    output = song_title_query.render_song_title_query(
        "测试歌曲",
        100,
        "测试昵称",
        [_showcase_title("原有称号")],
        [_showcase_title("自定义称号", source="custom")],
    )

    assert isinstance(output, BytesIO)
    with Image.open(output) as image:
        assert image.width < song_title_query.CANVAS_WIDTH
        assert image.height > 300
    assert [(nickname, title_name) for nickname, title_name, *_ in calls] == [
        ("测试昵称", "原有称号"),
        ("测试昵称", "自定义称号"),
    ]
    assert calls[0][3] is None
    assert calls[1][3] == custom_title.CUSTOM_PLATE_PATHS["gold"]


def test_render_song_title_query_expands_to_two_columns(monkeypatch):
    monkeypatch.setattr(
        song_title_query,
        "render_nickname_title_row",
        lambda *_args, **_kwargs: Image.new("RGBA", (350, 70)),
    )

    output = song_title_query.render_song_title_query(
        "测试歌曲",
        100,
        "玩家昵称",
        [_showcase_title("称号一"), _showcase_title("称号二")],
        [],
    )

    with Image.open(output) as image:
        assert image.width == song_title_query.CANVAS_WIDTH


def test_player_nickname_comes_from_captured_userdata():
    assert song_title_query.extract_player_nickname({"profile":{"mydon_name":"资料昵称","gameCostume":{"mydon_name":"玩家昵称"}}}) == "玩家昵称"
    assert song_title_query.extract_player_nickname({}) == "鼓手"
