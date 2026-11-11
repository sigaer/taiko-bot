"""Regression cases for mixed-width titles and misspelled name fragments."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

from fuzzywuzzy import fuzz
import pytest
from sakura_taiko_core.chart import identity
from taiko_application.query import SongQueryContext, query_music
from taiko_application.query.song_matching import normalize_song_query, song_similarity


SONGS = [
    {"id": 1459, "song_name": "给我听Waruloo大人的歌！", "song_name_jp": "ワルルーさまの歌を聴けぇ！"},
    {"id": 1031, "song_name_jp": "Hello, Worldooon!!"},
    {"id": 649, "song_name_jp": "毒LOＣＡＮdy♡"},
    {"id": 935, "song_name_jp": "MagiCatz"},
    {"id": 354, "song_name_jp": "さいたま2000"},
]
ALIASES = [{"id": 649, "aliases": ["毒糖", "Poison Candy"]}]


def context(query, *, songs=SONGS, aliases=ALIASES, **options):
    _, by_id, by_title = identity.build_group_maps(songs)
    return SongQueryContext(songs, aliases, by_id, by_title, fuzz.ratio, query=query, **options)


@pytest.mark.parametrize("query,song_id,mode", [
    ("waruloo", 1459, "partial_name"),
    ("warulooo", 1459, "fuzzy"),
    ("waruioo", 1459, "fuzzy"),
    ("ＷＡＲＵＬＯＯＯ", 1459, "fuzzy"),
    ("毒loca", 649, "partial_name"),
    ("毒ＬＯＣＡ", 649, "partial_name"),
    ("毒locandy♡", 649, "exact_name"),
    ("さいたま２０００", 354, "exact_name"),
    ("ｉｄ６４９", 649, "exact_id"),
    ("ｐｏｉｓｏｎ　ｃａｎｄｙ", 649, "exact_alias"),
])
def test_title_and_alias_queries(query, song_id, mode):
    rows, actual_mode = query_music(context(query))
    assert actual_mode == mode
    assert len(rows) == 1
    assert rows[0][0] == song_id
    if mode == "fuzzy":
        assert rows[0][2] >= 85


@pytest.mark.parametrize("query", ["", "  ", None])
def test_empty_queries(query):
    assert query_music(context(query)) == ([], None)


def test_normalization_keeps_symbols_and_version_numbers():
    assert normalize_song_query(" 毒LOＣＡＮdy♡ ") == "毒locandy♡"
    assert normalize_song_query("Ａ　Ｂ ２０００！") == "ab2000!"
    assert normalize_song_query("Song 2 +") != normalize_song_query("Song 3 +")
    assert normalize_song_query("Song +") != normalize_song_query("Song -")


def test_literal_name_wins_over_normalized_collision():
    songs = [{"id": 1, "song_name_jp": "AB"}, {"id": 2, "song_name_jp": "A B"}]
    assert query_music(context("A B", songs=songs, aliases=[])) == ([[2, "A B"]], "exact_name")
    rows, mode = query_music(context("ＡＢ", songs=songs, aliases=[]))
    assert mode == "exact_name"
    assert {row[0] for row in rows} == {1}  # Same-title group collapses its versions.


def test_literal_alias_wins_over_normalized_name():
    songs = [{"id": 1, "song_name_jp": "ＳＨＯＲＴ"}, {"id": 2, "song_name_jp": "Other"}]
    aliases = [{"id": 2, "aliases": ["short"]}]
    assert query_music(context("short", songs=songs, aliases=aliases)) == ([[2, "Other"]], "exact_alias")


def test_disabling_fuzzy_and_partial_matching():
    assert query_music(context("warulooo", allow_fuzzy=False)) == ([], None)
    assert query_music(context("waruloo", allow_partial=False, allow_fuzzy=False)) == ([], None)
    assert query_music(context("毒loca", allow_partial=False, allow_fuzzy=False)) == ([], None)
    query, candidate = "warulooo", normalize_song_query(SONGS[0]["song_name"])
    assert song_similarity(query, candidate, fuzz.ratio, allow_partial=False) == fuzz.ratio(query, candidate)


@pytest.mark.parametrize("query,candidate", [
    ("waru", "xxwaruxx"),
    ("12345", "xx1234xx"),
    ("warulooo", "waru"),
    ("warulooo", "completelyunrelated"),
])
def test_weak_fragments_are_not_promoted(query, candidate):
    assert song_similarity(query, candidate, fuzz.ratio, allow_partial=True) == fuzz.ratio(query, candidate)


def test_long_alias_can_recover_a_misspelled_fragment():
    aliases = [{"id": 1459, "aliases": ["please listen to waruloo singing"]}]
    rows, mode = query_music(context("warulooo", songs=[{"id": 1459, "song_name_jp": "Target"}], aliases=aliases))
    assert mode == "fuzzy"
    assert rows[0][0] == 1459
    assert 85 <= rows[0][2] < 100


@pytest.fixture
def client_provider(tmp_path, monkeypatch):
    # Load the actual adapter without registering NoneBot plugins or reading config.
    import taiko_bot
    public_dir = Path(taiko_bot.__file__).parent / "runtime" / "public"
    package_name = "_song_search_test_public"
    package = ModuleType(package_name)
    package.__path__ = [str(public_dir)]
    config = ModuleType(package_name + ".config")
    config.root = lambda: tmp_path
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setitem(sys.modules, config.__name__, config)
    spec = importlib.util.spec_from_file_location(package_name + ".client_provider", public_dir / "client_provider.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    songs_dir = tmp_path / "songs"
    songs_dir.mkdir()
    (songs_dir / "song_data.json").write_text(json.dumps(SONGS), encoding="utf-8")
    (songs_dir / "song_alias.json").write_text(json.dumps(ALIASES), encoding="utf-8")
    yield module, songs_dir
    for suffix in ("provider", "client_provider", "resolve"):
        sys.modules.pop(package_name + "." + suffix, None)


@pytest.mark.parametrize("query", ["waruloo", "warulooo", "毒loca", "さいたま２０００", "ｐｏｉｓｏｎ　ｃａｎｄｙ"])
def test_client_uses_same_matching(query, client_provider):
    client, _ = client_provider
    assert client._query_music_with_mode(query) == query_music(context(query))


@pytest.mark.parametrize("query", ["hiddenname", "hiddennam", "hiddennamee"])
def test_client_excludes_hidden_aliases_from_every_stage(query, client_provider):
    client, songs_dir = client_provider
    songs = SONGS + [{"id": 1429, "song_name_jp": "Hidden"}]
    (songs_dir / "song_data.json").write_text(json.dumps(songs), encoding="utf-8")
    (songs_dir / "song_alias.json").write_text(json.dumps([{"id": 1429, "aliases": ["hiddenname"]}]), encoding="utf-8")
    rows, _ = client._query_music_with_mode(query)
    assert all(row[0] != 1429 for row in rows)


def test_client_keeps_duplicate_version_ids(client_provider):
    client, songs_dir = client_provider
    songs = [{"id": 10, "song_name_jp": "Song"}, {"id": 11, "song_name_jp": "Song"}]
    (songs_dir / "song_data.json").write_text(json.dumps(songs), encoding="utf-8")
    rows, mode = client._query_music_with_mode("Song")
    assert mode == "exact_name"
    assert [row[0] for row in rows] == [10, 11]


def test_client_normalizes_alias_ids(client_provider):
    client, songs_dir = client_provider
    (songs_dir / "song_alias.json").write_text(json.dumps([
        {"id": "0649", "aliases": ["candy"]},
        {"aliases": ["missingid"]},
    ]), encoding="utf-8")
    assert client._query_music_with_mode("candy") == ([[649, "毒LOＣＡＮdy♡"]], "exact_alias")


@pytest.mark.parametrize("profile", ["center", "client"])
@pytest.mark.parametrize("query,song_id", [("waruloo", 1459), ("warulooo", 1459), ("毒loca", 649)])
def test_what_song_command_uses_fixed_matching(profile, query, song_id, client_provider, monkeypatch):
    import importlib
    from taiko_application.commands import CommandContext, SongPorts, execute_song

    config = sys.modules["_song_search_test_public.config"]
    monkeypatch.setattr(config, "profile", lambda: profile, raising=False)
    provider = importlib.import_module("_song_search_test_public.provider")
    result = execute_song(
        CommandContext(profile=profile, text=f"里{query}是什么歌"),
        SongPorts(
            _extract_what_song_query=lambda text: text.removesuffix("是什么歌"),
            _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
            _resolve_what_song_query=provider.resolve,
        ),
    )
    if profile == "client" and query == "warulooo":
        assert result.kind == "fuzzy_fumen"
        assert result.difficulty == "InnerOni"
        assert result.payload[0][0] == song_id
    else:
        assert result.kind == "fumen"
        assert result.payload == ("InnerOni", str(song_id))
