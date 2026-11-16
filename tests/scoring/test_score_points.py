"""Score lookup shares chart identity and revision handling with score lines."""
import asyncio
from functools import partial
import json
import os
import re
import sys

import pytest
from fuzzywuzzy import fuzz
from taiko_application.query import SongQueryContext, query_music
from taiko_application.query.song_index import build_song_index
from taiko_bot.runtime.player.center import duplicate_versions, score_data
from taiko_bot.runtime.player.center.recommendation_support import score_line


def publish(path, rows):
    previous = path.stat().st_mtime_ns if path.exists() else 0
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    revision = max(path.stat().st_mtime_ns, previous + 1)
    os.utime(path, ns=(revision, revision))


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    songs = [dict(id=sid, song_name_jp='ボクハシンセ', song_name='我是合成器',
                  max_combo=[150, 200, 300, 612, 800]) for sid in (191, 1266)]
    aliases = [dict(id=sid, song_name_jp='ボクハシンセ', aliases=['合成器'])
               for sid in (191, 1266)]
    paths = [('SCORE_PATH', 'song_score.json'), ('SONG_DATA_PATH', 'song_data.json'),
             ('ALL_LEVELS_STREAM_PATH', 'stream.json'), ('UNIFIED_PATH', 'unified.json')]
    for attr, name in paths:
        path = tmp_path/name
        publish(path, songs if attr == 'SONG_DATA_PATH' else [])
        monkeypatch.setattr(score_line, attr, path)
    monkeypatch.setattr(score_data, 'group_ids_for_query', partial(
        duplicate_versions.group_ids_for_query, song_data_path=score_line.SONG_DATA_PATH))
    monkeypatch.setattr(score_data, 'default_song_id_for_query', partial(
        duplicate_versions.default_song_id_for_query, song_data_path=score_line.SONG_DATA_PATH))
    publish(score_line.UNIFIED_PATH, [dict(id=1266, level=4, initial_points=1630),
                                    dict(id=1266, level=5, initial_points=1250),
                                    dict(id=1303, level=4, initial_points=2000)])
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()
    index = build_song_index(songs, aliases, collapse_versions=True)

    def query(text):
        return query_music(SongQueryContext(songs=(), aliases=(), groups_by_id={},
            groups_by_title={}, similarity=fuzz.ratio, query=text, index=index))[0]

    yield query
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()


def test_alias_resolves_to_other_id_with_existing_points(catalog):
    assert catalog('合成器') == [[191, 'ボクハシンセ']]
    assert score_data.get_scoreline_entry(191, 4)['id'] == 1266
    assert score_data.compute_score(191, 377, 221, 117) == 805220
    assert score_data.compute_score(1266, 377, 221, 117) == 805220


@pytest.mark.parametrize('song_id,level,expected', [
    (191, 4, 805220), (1266, 4, 805220), (191, 5, 619970),
    (1266, 5, 619970), (1303, 4, 986700),
])
def test_chart_difficulty_and_unrelated_song(catalog, song_id, level, expected):
    assert score_data.compute_score(song_id, 377, 221, 117, level=level) == expected


def test_existing_exact_id_points_take_precedence(catalog):
    rows = json.loads(score_line.UNIFIED_PATH.read_text())
    rows.append(dict(id=191, level=4, initial_points=1650))
    publish(score_line.UNIFIED_PATH, rows)
    assert score_data.get_scoreline_entry(1266, 4)['id'] == 191
    assert score_data.compute_score(1266, 1, 1, 1) == 2540
    assert score_data.compute_score(191, 1, 1, 1) == 2570


def test_distinct_songs_sharing_translation_keep_their_points(catalog):
    publish(score_line.SONG_DATA_PATH, [
        dict(id=523, song_name='Synchronicity', song_name_jp='Synchronicity'),
        dict(id=766, song_name='Synchronicity', song_name_jp='シンクロニシティ'),
    ])
    publish(score_line.UNIFIED_PATH, [
        dict(id=523, level=4, initial_points=2240),
        dict(id=766, level=4, initial_points=2420),
    ])
    assert score_data.compute_score(523, 1, 0) == 2240
    assert score_data.compute_score(766, 1, 0) == 2420


def test_updates_refresh_warm_score_lookup(catalog):
    assert score_data.compute_score(191, 1, 0) == 1630
    rows = json.loads(score_line.UNIFIED_PATH.read_text())
    rows[0]['initial_points'] = 1730
    publish(score_line.UNIFIED_PATH, rows)
    assert score_data.compute_score(191, 1, 0) == 1730
    publish(score_line.SCORE_PATH, [dict(id=1266, title='ボクハシンセ',
                                       level=4, initial_points=1830, max_combo=612)])
    revision = max(score_line.SCORE_PATH.stat().st_mtime_ns,
                   score_line.UNIFIED_PATH.stat().st_mtime_ns + 1)
    os.utime(score_line.SCORE_PATH, ns=(revision, revision))
    assert score_data.compute_score(191, 1, 0) == 1830


def test_missing_source_matches_scoreline_after_warm_lookup(catalog):
    assert score_data.compute_score(191, 1, 0) == 1630
    score_line.SCORE_PATH.unlink()
    with pytest.raises(FileNotFoundError):
        score_data.compute_score(191, 1, 0)


@pytest.mark.parametrize('song_id,level', [(99999, 4), (191, 3), (1303, 5)])
def test_missing_chart_does_not_borrow_unrelated_data(catalog, song_id, level):
    with pytest.raises(KeyError, match='分值记录'):
        score_data.compute_score(song_id, 1, 1, level=level)


def test_missing_points_still_reports_configuration_error(catalog):
    publish(score_line.UNIFIED_PATH, [dict(id=1266, level=4)])
    with pytest.raises(KeyError, match='initial_points'):
        score_data.compute_score(191, 1, 1)


@pytest.mark.parametrize('command,expected', [
    ('查分 合成器 377 221 117', '805220'),
    ('查分 表合成器 377 221 117', '805220'),
    ('/查分 里合成器 377 221 117', '619970'),
    ('查分 id1266 377 221 117', '805220'),
    ('查分 合成器 377 221', '793520'),
])
def test_loaded_command_handler(catalog, monkeypatch, command, expected):
    scoring = sys.modules.get('taiko_bot.runtime.player.scoring')
    if scoring is None:
        pytest.skip('Run with command_checks.py --load-player to verify registered commands')
    from nonebot.rule import RegexRule
    regex = next(dep.call.regex for dep in scoring.score_cmd.rule.checkers
                 if isinstance(dep.call, RegexRule))
    groups = re.search(regex, command).groups()
    monkeypatch.setattr(scoring.host, 'queryMusic', catalog)

    class Finished(Exception):
        pass

    class Capture:
        async def finish(self, text):
            raise Finished(text)

    with pytest.raises(Finished) as reply:
        asyncio.run(scoring.host.handle_score(Capture(), None, groups))
    assert '总分：' + expected in str(reply.value)
    assert '分值配置异常' not in str(reply.value)
