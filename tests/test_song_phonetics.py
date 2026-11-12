"""Homophone recovery and difficulty-prefix alias ownership."""

import importlib.util
from pathlib import Path
import sys

import pytest
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity
from sakura_taiko_core.score import scoreline
from taiko_application.query import SongQueryContext, query_music
from taiko_application.query.song_phonetics import same_pronunciation
from taiko_bot.runtime.player.scoreline_query import resolve_scoreline_query


SONGS = [
    {'id': 94, 'song_name_jp': '弩蚊怒夏'},
    {'id': 993, 'song_name_jp': '彁'},
    {'id': 1, 'song_name_jp': '幽玄'},
]
ALIASES = [{'id': 993, 'aliases': ['表哥']}]

# The production center pins Core 0.1.1; the client's parser is owned by 0.1.2.
_client_path = Path(__file__).resolve().parents[1] / 'packages/sakura-taiko-core/core/score/client_scoreline.py'
_client_spec = importlib.util.spec_from_file_location('sakura_taiko_core.score._client_parser_test', _client_path)
client_scoreline = importlib.util.module_from_spec(_client_spec)
sys.modules[_client_spec.name] = client_scoreline
_client_spec.loader.exec_module(client_scoreline)


def query(text, *, songs=SONGS, aliases=ALIASES, **kwargs):
    _, by_id, by_title = identity.build_group_maps(songs)
    return query_music(SongQueryContext(songs, aliases, by_id, by_title, fuzz.ratio,
                                       query=text, **kwargs))


@pytest.mark.parametrize('text,sid', [('哥', 993), ('歌', 993), ('幽宣', 1)])
def test_full_homophone_outweighs_unrelated_text_similarity(text, sid):
    rows, mode = query(text)
    assert mode == 'fuzzy'
    assert [row[0] for row in rows] == [sid]


def test_exact_names_aliases_and_ids_still_win():
    assert query('表哥') == ([[993, '彁']], 'exact_alias')
    assert query('彁') == ([[993, '彁']], 'exact_name')
    assert query('id993') == ([[993, '彁']], 'exact_id')
    songs = SONGS + [{'id': 2, 'song_name_jp': '哥'}]
    assert query('哥', songs=songs) == ([[2, '哥']], 'exact_name')


def test_full_pronunciation_outranks_a_fragment_of_a_long_title():
    songs = SONGS + [{'id': 2, 'song_name_jp': '晚餐歌'}]
    assert query('歌', songs=songs)[0] == [[993, '彁', 90]]
    assert query('歌', songs=songs, allow_fuzzy=False) == ([[2, '晚餐歌']], 'partial_name')


def test_homophone_aliases_are_searchable_and_ambiguous_songs_are_preserved():
    assert query('表歌')[0][0][0] == 993
    songs = SONGS + [{'id': 2, 'song_name_jp': '戈'}]
    rows, mode = query('哥', songs=songs)
    assert mode == 'fuzzy'
    assert {row[0] for row in rows} == {2, 993}
    assert query('哥', songs=list(reversed(songs)))[0] == list(reversed(rows))


def test_fuzzy_opt_out_and_non_chinese_characters():
    assert query('哥', allow_fuzzy=False) == ([], None)
    assert not same_pronunciation('ge', '彁')
    assert not same_pronunciation('哥', '表哥')
    assert not same_pronunciation('哥2', '彁3')
    assert not same_pronunciation('哥+', '彁-')
    assert same_pronunciation('哥2', '彁2')
    assert not same_pronunciation('西安', '先')


@pytest.mark.parametrize('text,expected_level', [
    ('分数线 表哥 12', 4),
    ('分数线 表 表哥 12', 4),
    ('分数线 里表哥 12', 5),
    ('分数线 哥 12', 4),
    ('分数线 极表哥 30', 4),
    ('分数线 表哥 极 30', 4),
    ('分数线 极 表哥', 4),
    ('分数线 极 里表哥 30', 5),
    ('分数线 表 哥 12', 4),
])
def test_center_scoreline_preserves_whole_alias_and_recovers_homophones(text, expected_level):
    request, rows = resolve_scoreline_query(text, scoreline.parse_scoreline_request,
                                          query, scoreline._DIFF_PREFIXES)
    assert len(rows) == 1 and rows[0][0] == 993
    assert request.level == expected_level
    if text == '分数线 表哥 12':
        assert request.song_query == '表哥'
        assert request.target_rating == 12


@pytest.mark.parametrize('text,expected_level', [
    ('分数线 极 表哥 30', 4), ('分数线 极 里表哥 30', 5),
    ('分数线 极 哥 30', 4),
])
def test_client_scoreline_uses_same_alias_resolution(text, expected_level):
    request, rows = resolve_scoreline_query(text, client_scoreline.parse_scoreline_request,
                                          query, client_scoreline._DIFF_PREFIXES)
    assert len(rows) == 1 and rows[0][0] == 993
    assert request.level == expected_level
    assert request.speed_ips == 30


@pytest.mark.parametrize('text', ['分数线', '分数线 表哥 0', '分数线 极 表哥 61'])
def test_scoreline_validation_still_rejects_invalid_arguments(text):
    with pytest.raises(ValueError):
        resolve_scoreline_query(text, scoreline.parse_scoreline_request,
                               query, scoreline._DIFF_PREFIXES)
