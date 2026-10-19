import json
from pathlib import Path

import pytest

from taiko_bot.offline import song_positions as updater
from taiko_bot.offline.song_position_matching import SongTable, normalize_title
from taiko_bot.song_positions import (
    GENRES, PositionIndexUnavailable, find_position, format_national_position, load_index,
)


def song(sid, title, genre='游戏音乐', subtitle=''):
    return {'id': sid, 'song_name': title, 'song_name_jp': title, 'type': genre, 'subtitle': subtitle}


def pages(game=(), namco=()):
    result = {slug: [] for slug in GENRES}
    for slug, values in [('game', game), ('namco', namco)]:
        result[slug] = [{'title': value, 'subtitle': ''} if isinstance(value, str) else value for value in values]
    return result


def build(rows=None, official=None):
    rows = rows if rows is not None else [song(1207, 'AtoZ,I leave toZ'), song(1311, '雨中的回旋曲'), song(1310, 'Genesis Ray'), song(1404, 'みんなのうた'), song(1418, 'Sync Your World')]
    official = official if official is not None else pages([row['song_name_jp'] for row in rows])
    return updater.build_index(rows, official, updated_at='2026-10-19T12:00:00+08:00')


def test_national_roster_filters_overseas_and_keeps_all_national_categories():
    rows = [song(1, 'One'), song(1, 'One', '南梦宫原创音乐'), song(2, 'Only CN')]
    payload = build(rows, pages(['Only Overseas', 'One'], ['One', 'Only CN']))
    check = payload['categories']
    assert check['游戏音乐'] == {'ordered': [1], 'pending': [2]}
    assert check['南梦宫原创音乐'] == {'ordered': [1], 'pending': []}
    assert len(json.dumps(payload).encode()) < 1024
    assert set(payload) == {'version', 'updated_at', 'categories'}


def test_supplied_cabinet_tail_and_pending_position_are_honest():
    payload = build()
    payload['categories']['游戏音乐']['pending'] = [1500, 1501]
    message = format_national_position(find_position(payload, 1207, 'AtoZ,I leave toZ'))
    assert '倒数第 5' in message and '另有 2 首位置待确认' in message
    assert '参考第 1 / 5' in message and 'sort' not in message
    assert '位置待确认' in format_national_position(find_position(payload, 1500, 'LUMINΔ'))
    assert '当前国行曲表未收录' in format_national_position(find_position(payload, 99999, 'Overseas'))


def test_originals_and_focus_on_covers_are_not_collapsed():
    rows = [song(433, 'エンジェル ドリーム', '南梦宫原创音乐'),
            song(1265, 'エンジェル ドリーム', '南梦宫原创音乐', 'Furen / FOCUS ON (NIJISANJI) × 太鼓之达人')]
    official = pages(namco=[{'title': 'エンジェル ドリーム', 'subtitle': 'フレン・E・ルスタリオ / FOCUS ON (にじさんじ) × 太鼓の達人'}, 'エンジェル ドリーム'])
    assert build(rows, official)['categories']['南梦宫原创音乐']['ordered'] == [1265, 433]
    rows = [song(433, 'エンジェル ドリーム', '南梦宫原创音乐')]
    assert build(rows, official)['categories']['南梦宫原创音乐']['ordered'] == [433]
    assert normalize_title('ダーク・エクス・マキナ♡') != normalize_title('ダーク・エクス・マキナ！')


def test_unresolved_same_title_is_pending_not_arbitrarily_selected():
    payload = build([song(1, 'Same'), song(2, 'Same')], pages(['Same']))
    assert payload['categories']['游戏音乐'] == {'ordered': [], 'pending': [1, 2]}


def test_html_parser_ignores_badges_and_movie_column():
    parser = SongTable()
    parser.feed('<tr><th>AtoZ,I leave toZ <span>NEW!</span><span>MEDAL</span><p>Artist</p></th>'
                '<td></td><td>3</td><td>4</td><td>6</td><td>9</td><td>-</td><td>movie</td></tr>')
    assert parser.rows == [{'title': 'AtoZ,I leave toZ', 'subtitle': 'Artist'}]


def test_publication_is_atomic_and_reader_sees_new_generation(tmp_path, monkeypatch):
    path = tmp_path / 'index.json'
    before = build()
    updater.publish_index(path, before)
    after = build([song(1418, 'Sync Your World')])
    updater.publish_index(path, after)
    assert load_index(path) == after
    assert load_index(path.with_suffix('.json.previous')) == before
    original = updater.os.replace

    def fail(source, target):
        if Path(target) == path:
            raise OSError('synthetic publication failure')
        return original(source, target)

    monkeypatch.setattr(updater.os, 'replace', fail)
    with pytest.raises(OSError, match='publication failure'):
        updater.publish_index(path, before)
    assert load_index(path) == after
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize('failure', ['empty', 'truncated', 'duplicate', 'wrong-version'])
def test_invalid_generation_never_overwrites_good_index(tmp_path, failure):
    path = tmp_path / 'index.json'
    payload = build()
    updater.publish_index(path, payload)
    if failure == 'empty':
        with pytest.raises(ValueError, match='incomplete'):
            updater.refresh_positions([], output_path=path)
    elif failure == 'truncated':
        with pytest.raises(ValueError, match='Missing'):
            updater.build_index([song(1, 'One')], {})
    else:
        broken = build()
        if failure == 'duplicate':
            broken['categories']['游戏音乐']['pending'].append(1207)
        else:
            broken['version'] = 2
        with pytest.raises(ValueError):
            updater.publish_index(path, broken)
    assert load_index(path) == payload


def test_safe_daily_refresh_retains_file_on_network_or_parse_failure(tmp_path, monkeypatch):
    path = tmp_path / 'index.json'
    updater.publish_index(path, build())
    before = path.read_bytes()
    monkeypatch.setattr(updater, 'refresh_positions', lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('synthetic')))
    assert updater.refresh_positions_safely([], output_path=path) is None
    assert path.read_bytes() == before
    path.write_text('invalid')
    with pytest.raises(PositionIndexUnavailable):
        load_index(path)


def test_center_provider_and_all_position_entry_formats_use_compact_index(tmp_path, monkeypatch):
    import importlib
    import sys
    import types
    import taiko_bot
    package = types.ModuleType('position_test_public')
    package.__path__ = [str(Path(taiko_bot.__file__).parent / 'runtime/public')]
    monkeypatch.setitem(sys.modules, 'position_test_public', package)
    provider = importlib.import_module('position_test_public.provider')
    public_queries = importlib.import_module('position_test_public.public_queries')
    directory = tmp_path / 'songs'
    directory.mkdir()
    (directory / 'song_data.json').write_text(json.dumps([song(1207, 'AtoZ,I leave toZ')]))
    updater.publish_index(directory / 'cn_song_positions.json', build())
    monkeypatch.setattr(provider, 'profile', lambda: 'center')
    monkeypatch.setattr(provider, 'root', lambda: tmp_path)
    assert '倒数第 5' in public_queries.format_position_reply(provider.position(1207))
    assert provider.position(99999) is None


def test_daily_hook_uses_live_occurrences_before_deduplication(tmp_path, monkeypatch):
    from taiko_bot.offline import song_update_task as task
    live = [song(1, 'One'), song(1, 'One', '南梦宫原创音乐')]
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'data': {'list': live}}
    config = tmp_path / 'config.json'
    config.write_text('{"cookie":"synthetic"}')
    old = tmp_path / 'old.json'
    old.write_text('[]')
    monkeypatch.setattr(task, 'CONFIG_PATH', config)
    monkeypatch.setattr(task, 'SONG_DATA_PATH', old)
    monkeypatch.setattr(task, 'ROOT_DIR', tmp_path)
    monkeypatch.setattr(task.requests, 'post', lambda *a, **kw: Response())
    monkeypatch.setattr(task, 'refresh_positions_safely', lambda rows, **kw: calls.append((rows, kw)))
    monkeypatch.setattr(task, '_load_db_bpm_map', lambda: (_ for _ in ()).throw(RuntimeError('stop-before-other-pipeline')))
    with pytest.raises(RuntimeError, match='stop-before-other-pipeline'):
        task.update_taiko_music(interactive=False)
    assert calls == [(live, {'output_path': tmp_path / 'songs/cn_song_positions.json'})]
    trigger = task.scheduler.get_job(task.SCHEDULE_JOB_TAG).trigger
    assert str(trigger.timezone) == 'Asia/Shanghai'
