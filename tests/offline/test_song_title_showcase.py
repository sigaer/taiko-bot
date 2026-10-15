from __future__ import annotations

import importlib


def _load_showcase_module():
    return importlib.import_module("taiko_bot.runtime.player.center.song_title_showcase")


def test_load_api_song_title_relations_parses_visible_api_titles(monkeypatch):
    showcase = _load_showcase_module()
    showcase._load_api_song_title_relations.cache_clear()

    monkeypatch.setattr(
        showcase,
        "load_title_catalog_items",
        lambda: (
            {
                "name": "正義をかたる者",
                "subtitle": "在《Hater》的“魔王”难度下达成全连吧",
                "rarity": 2,
                "sort_no": 607,
            },
            {
                "name": "よき旅を",
                "subtitle": "用任意难度通关《GO ON ～朝向未来～》吧",
                "rarity": 0,
                "sort_no": 264,
            },
            {
                "name": "わさびの達人",
                "subtitle": "？？？",
                "rarity": 2,
                "sort_no": 283,
            },
        ),
    )

    relations = showcase._load_api_song_title_relations()

    assert relations == (
        showcase.SongTitleRelation(
            title_name="正義をかたる者",
            song_names=("Hater",),
            requirement_type="full_combo",
            difficulty_scope="oni",
            condition_text="在《Hater》的“魔王”难度下达成全连吧",
            source_row_index=607,
        ),
        showcase.SongTitleRelation(
            title_name="よき旅を",
            song_names=("GO ON ～朝向未来～",),
            requirement_type="clear",
            difficulty_scope="unspecified",
            condition_text="用任意难度通关《GO ON ～朝向未来～》吧",
            source_row_index=264,
        ),
    )


def test_load_song_title_relations_prefers_api_relations(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()

    api_relation = showcase.SongTitleRelation(
        title_name="正義をかたる者",
        song_names=("Hater",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api",
        source_row_index=607,
    )
    legacy_relation = showcase.SongTitleRelation(
        title_name="正義をかたる者",
        song_names=("ヘイラ",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="legacy",
        source_row_index=408,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: (api_relation,))
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: ())
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: (legacy_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())

    relations = showcase.load_song_title_relations()

    assert relations == (api_relation,)


def test_load_song_title_relations_keeps_different_difficulty_scopes(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()

    api_relation = showcase.SongTitleRelation(
        title_name="桂月",
        song_names=("桂月",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api oni",
        source_row_index=916,
    )
    legacy_relation = showcase.SongTitleRelation(
        title_name="桂月",
        song_names=("桂月(裏)",),
        requirement_type="full_combo",
        difficulty_scope="inner_oni",
        condition_text="legacy inner",
        source_row_index=920,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: (api_relation,))
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: ())
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: (legacy_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())

    relations = showcase.load_song_title_relations()

    assert relations == (api_relation, legacy_relation)


def test_levels_for_scope_supports_oni_and_inner_oni():
    showcase = _load_showcase_module()
    assert showcase._levels_for_scope("oni_or_inner_oni") == (4, 5)


def test_load_song_title_relations_prefers_manual_hidden_relations(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()

    manual_relation = showcase.SongTitleRelation(
        title_name="紫薔薇の融合",
        song_names=("Purple Rose Fusion",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="manual",
        source_row_index=2666,
    )
    legacy_relation = showcase.SongTitleRelation(
        title_name="紫薔薇の融合",
        song_names=("Red Rose Evangel", "Blue Rose Ruin"),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="legacy",
        source_row_index=2666,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: ())
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: (manual_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: (legacy_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())

    relations = showcase.load_song_title_relations()

    assert relations == (manual_relation,)


def test_load_song_title_relations_manual_override_replaces_same_scope_api(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()

    api_relation = showcase.SongTitleRelation(
        title_name="紫薔薇の融合",
        song_names=("Red Rose Evangel", "Blue Rose Ruin"),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api",
        source_row_index=98,
    )
    manual_relation = showcase.SongTitleRelation(
        title_name="紫薔薇の融合",
        song_names=("Purple Rose Fusion",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="manual",
        source_row_index=2666,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: (api_relation,))
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: (manual_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: ())
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())

    relations = showcase.load_song_title_relations()

    assert relations == (manual_relation,)


def test_load_song_title_relations_manual_override_replaces_wrong_api_scope(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()

    api_relation = showcase.SongTitleRelation(
        title_name="出会った仲間と共に乗り越えて行ける",
        song_names=("4+1的各自的未来",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api oni",
        source_row_index=731,
    )
    legacy_relation = showcase.SongTitleRelation(
        title_name="出会った仲間と共に乗り越えて行ける",
        song_names=("4+1のそれぞれの未来(裏)",),
        requirement_type="full_combo",
        difficulty_scope="inner_oni",
        condition_text="legacy inner",
        source_row_index=523,
    )
    manual_relation = showcase.SongTitleRelation(
        title_name="出会った仲間と共に乗り越えて行ける",
        song_names=("4+1のそれぞれの未来(裏)",),
        requirement_type="full_combo",
        difficulty_scope="inner_oni",
        condition_text="manual inner",
        source_row_index=523,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: (api_relation,))
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: (manual_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: (legacy_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())

    relations = showcase.load_song_title_relations()

    assert relations == (manual_relation,)


def test_load_api_song_title_relations_excludes_configured_titles(monkeypatch):
    showcase = _load_showcase_module()
    showcase._load_api_song_title_relations.cache_clear()

    monkeypatch.setattr(
        showcase,
        "load_title_catalog_items",
        lambda: (
            {
                "name": "Seafood Seeker",
                "subtitle": "在1次游玩中，在《The Carnivorous Carnival》《Evidence of evil》《Turquoise Tachometer》的“魔王”难度下达成全连吧",
                "rarity": 2,
                "sort_no": 349,
            },
            {
                "name": "正義をかたる者",
                "subtitle": "在《Hater》的“魔王”难度下达成全连吧",
                "rarity": 2,
                "sort_no": 607,
            },
            {
                "name": "セッションマスター",
                "subtitle": "在《GO GET'EM!》与《GO GET'EM!(裏)》的“魔王”或“魔王（隐藏）”难度下达成全连吧",
                "rarity": 2,
                "sort_no": 574,
            },
        ),
    )

    relations = showcase._load_api_song_title_relations()

    assert relations == (
        showcase.SongTitleRelation(
            title_name="正義をかたる者",
            song_names=("Hater",),
            requirement_type="full_combo",
            difficulty_scope="oni",
            condition_text="在《Hater》的“魔王”难度下达成全连吧",
            source_row_index=607,
        ),
    )


def test_detect_difficulty_scope_supports_japanese_oni_text():
    showcase = _load_showcase_module()
    assert showcase._detect_difficulty_scope("天狗囃子を難易度おにでフルコンボ") == "oni"


def test_detect_difficulty_scope_keeps_inner_oni_song_name_out_of_dual_scope():
    showcase = _load_showcase_module()
    assert (
        showcase._detect_difficulty_scope("RAGING FIRE(裏)を難易度おにでクリア")
        == "inner_oni"
    )
    assert (
        showcase._detect_difficulty_scope(
            "在《KOKODOKO? 或许是DOKKA岛呢!》的“魔王（隐藏）”难度下达成全连吧"
        )
        == "inner_oni"
    )


def test_relation_plate_id_prefers_available_oni_plate(monkeypatch):
    showcase = _load_showcase_module()
    monkeypatch.setattr(
        showcase,
        "_load_title_rarity_lookup",
        lambda: {"RAGING FIRE": (41, 42, 43)},
    )

    assert showcase._relation_plate_id("RAGING FIRE", "clear", "oni_or_inner_oni") == 41
    assert showcase._relation_plate_id("RAGING FIRE", "clear", "inner_oni") == 41
    assert showcase._relation_plate_id("RAGING FIRE", "full_combo", "oni_or_inner_oni") == 42
    assert showcase._relation_plate_id("RAGING FIRE", "full_combo", "inner_oni") == 42
    assert showcase._relation_plate_id("RAGING FIRE", "all_perfect", "oni_or_inner_oni") == 43
    assert showcase._relation_plate_id("RAGING FIRE", "all_perfect", "inner_oni") == 43


def test_relation_plate_id_prefers_available_inner_oni_plate(monkeypatch):
    showcase = _load_showcase_module()
    monkeypatch.setattr(
        showcase,
        "_load_title_rarity_lookup",
        lambda: {"刻竜 ～Kokuryu～": (59, 60, 61)},
    )

    assert showcase._relation_plate_id("刻竜 ～Kokuryu～", "clear", "oni") == 59
    assert showcase._relation_plate_id("刻竜 ～Kokuryu～", "full_combo", "oni") == 60
    assert showcase._relation_plate_id("刻竜 ～Kokuryu～", "all_perfect", "oni") == 61


def test_relation_showcase_bg_plate_id_keeps_rarity_2_bg_for_elevated_fc(monkeypatch):
    showcase = _load_showcase_module()
    monkeypatch.setattr(
        showcase,
        "_load_title_rarity_lookup",
        lambda: {"测试称号": (2,)},
    )

    assert showcase._relation_plate_id("测试称号", "full_combo", "oni") == 42
    assert showcase._relation_showcase_bg_plate_id("测试称号", 42) == 2


def test_load_song_title_relations_filters_titles_missing_from_catalog(monkeypatch):
    showcase = _load_showcase_module()
    showcase.load_song_title_relations.cache_clear()
    showcase._load_available_title_names.cache_clear()

    available_relation = showcase.SongTitleRelation(
        title_name="赤薔薇の福音",
        song_names=("Red Rose Evangel",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="available",
        source_row_index=96,
    )
    unavailable_relation = showcase.SongTitleRelation(
        title_name="SORA-VIII ネビュラトレイル",
        song_names=("SORA-VIII ネビュラトレイル",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="legacy only",
        source_row_index=689,
    )

    monkeypatch.setattr(showcase, "_load_api_song_title_relations", lambda: (available_relation,))
    monkeypatch.setattr(showcase, "_load_manual_hidden_relations", lambda: ())
    monkeypatch.setattr(showcase, "_load_legacy_base_song_title_relations", lambda: (unavailable_relation,))
    monkeypatch.setattr(showcase, "_load_legacy_all_perfect_relations", lambda: ())
    monkeypatch.setattr(
        showcase,
        "load_title_catalog_items",
        lambda: ({"name": "赤薔薇の福音", "subtitle": "", "rarity": 2, "sort_no": 96},),
    )

    relations = showcase.load_song_title_relations()

    assert relations == (available_relation,)


def test_battle_no_1_priority_const_only_affects_sort_order(monkeypatch):
    showcase = _load_showcase_module()
    battle_relation = showcase.SongTitleRelation(
        title_name="俺たちのBATTLEはこれからだ！",
        song_names=("BATTLE NO.1",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="battle",
        source_row_index=1,
    )
    normal_relation = showcase.SongTitleRelation(
        title_name="Lightning Boys",
        song_names=("Lightning Boys",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="normal",
        source_row_index=2,
    )

    monkeypatch.setattr(showcase, "load_song_title_relations", lambda: (battle_relation, normal_relation))
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: (
            {"battle no.1": (1037,), "lightning boys": (1411,)},
            {(1037, 4): 10.7, (1411, 4): 10.2},
            {("battle no.1", 4): 10.7, ("lightning boys", 4): 10.2},
            {},
        ),
    )
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args, **_kwargs: 2)

    result = showcase.infer_song_title_showcase(
        [
            {"song_no": 1037, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 1411, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
        ],
        limit=5,
    )

    assert [item.title_name for item in result[:2]] == ["Lightning Boys", "俺たちのBATTLEはこれからだ！"]
    assert result[1].const_value == 10.7
    assert result[1].priority_const_value == 8.5


def test_infer_song_title_showcase_falls_back_to_title_level_const(monkeypatch):
    showcase = _load_showcase_module()
    relation = showcase.SongTitleRelation(
        title_name="正義をかたる者",
        song_names=("Hater",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api",
        source_row_index=607,
    )

    monkeypatch.setattr(showcase, "load_song_title_relations", lambda: (relation,))
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: (
            {"hater": (1146, 1264)},
            {(1264, 4): 9.5},
            {("hater", 4): 9.5},
            {},
        ),
    )
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args, **_kwargs: 2)

    result = showcase.infer_song_title_showcase(
        [
            {
                "song_no": 1146,
                "level": 4,
                "full_combo_cnt": 1,
                "dondaful_combo_cnt": 0,
                "clear_cnt": 1,
            }
        ],
        limit=5,
    )

    assert len(result) == 1
    assert result[0].title_name == "正義をかたる者"
    assert result[0].const_value == 9.5


def test_infer_song_title_showcase_demotes_professor_title(monkeypatch):
    showcase = _load_showcase_module()
    professor_relation = showcase.SongTitleRelation(
        title_name="教授のきもち",
        song_names=("僕らの世界にダンスを", "Pico Pico MAPPY", "Pico Pico Ruin"),
        requirement_type="full_combo",
        difficulty_scope="unspecified",
        condition_text="api professor",
        source_row_index=5544,
    )
    normal_relation = showcase.SongTitleRelation(
        title_name="正義をかたる者",
        song_names=("Hater",),
        requirement_type="full_combo",
        difficulty_scope="oni",
        condition_text="api normal",
        source_row_index=607,
    )

    monkeypatch.setattr(
        showcase,
        "load_song_title_relations",
        lambda: (professor_relation, normal_relation),
    )
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: (
            {
                "僕らの世界にダンスを".casefold(): (1,),
                "pico pico mappy": (2,),
                "pico pico ruin": (3,),
                "hater": (4,),
            },
            {(1, 4): 10.0, (2, 4): 10.0, (3, 4): 10.0, (4, 4): 9.5},
            {},
            {},
        ),
    )
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args, **_kwargs: 2)

    result = showcase.infer_song_title_showcase(
        [
            {"song_no": 1, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 2, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 3, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 4, "level": 4, "full_combo_cnt": 1, "dondaful_combo_cnt": 0, "clear_cnt": 1},
        ],
        limit=5,
    )

    assert [item.title_name for item in result] == ["正義をかたる者", "教授のきもち"]


def test_infer_song_title_showcase_demotes_lovesick_clear_title(monkeypatch):
    showcase = _load_showcase_module()
    lovesick_relation = showcase.SongTitleRelation(
        title_name="恋の病治療中",
        song_names=("恋的処方箋",),
        requirement_type="clear",
        difficulty_scope="unspecified",
        condition_text="api lovesick",
        source_row_index=215,
    )
    normal_relation = showcase.SongTitleRelation(
        title_name="よき旅を",
        song_names=("GO ON ～朝向未来～",),
        requirement_type="clear",
        difficulty_scope="unspecified",
        condition_text="api normal",
        source_row_index=264,
    )

    monkeypatch.setattr(
        showcase,
        "load_song_title_relations",
        lambda: (lovesick_relation, normal_relation),
    )
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: (
            {
                "恋的処方箋".casefold(): (1,),
                "go on ~朝向未来~": (2,),
            },
            {(1, 4): 10.0, (2, 1): 1.0},
            {},
            {},
        ),
    )
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args, **_kwargs: 0)

    result = showcase.infer_song_title_showcase(
        [
            {"song_no": 1, "level": 4, "full_combo_cnt": 0, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 2, "level": 1, "full_combo_cnt": 0, "dondaful_combo_cnt": 0, "clear_cnt": 1},
        ],
        limit=5,
    )

    assert [item.title_name for item in result] == ["よき旅を", "恋の病治療中"]


def test_infer_song_title_showcase_demotes_taiko_master_clear_title(monkeypatch):
    showcase = _load_showcase_module()
    taiko_master_relation = showcase.SongTitleRelation(
        title_name="たいこのたしゅじん",
        song_names=("Xa",),
        requirement_type="clear",
        difficulty_scope="unspecified",
        condition_text="api taiko master",
        source_row_index=262,
    )
    normal_relation = showcase.SongTitleRelation(
        title_name="よき旅を",
        song_names=("GO ON ～朝向未来～",),
        requirement_type="clear",
        difficulty_scope="unspecified",
        condition_text="api normal",
        source_row_index=264,
    )

    monkeypatch.setattr(
        showcase,
        "load_song_title_relations",
        lambda: (taiko_master_relation, normal_relation),
    )
    monkeypatch.setattr(
        showcase,
        "_load_song_lookup",
        lambda: (
            {
                "xa": (1,),
                "go on ~朝向未来~": (2,),
            },
            {(1, 4): 10.9, (2, 1): 1.0},
            {},
            {},
        ),
    )
    monkeypatch.setattr(showcase, "_relation_plate_id", lambda *_args, **_kwargs: 0)

    result = showcase.infer_song_title_showcase(
        [
            {"song_no": 1, "level": 4, "full_combo_cnt": 0, "dondaful_combo_cnt": 0, "clear_cnt": 1},
            {"song_no": 2, "level": 1, "full_combo_cnt": 0, "dondaful_combo_cnt": 0, "clear_cnt": 1},
        ],
        limit=5,
    )

    assert [item.title_name for item in result] == ["よき旅を", "たいこのたしゅじん"]


def test_song_lookup_keys_support_manual_aliases():
    showcase = _load_showcase_module()
    keys = showcase._song_lookup_keys("Nijustat on Amatias")
    assert "nijustat on amatias" in keys
    assert "nesin amatias" in keys
    assert "【限定】 nesin amatias".casefold() in keys
