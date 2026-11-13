"""Snapshot lifecycle, immutable ownership and old/new search equivalence."""
from concurrent.futures import ThreadPoolExecutor
import ast
import asyncio
from dataclasses import FrozenInstanceError, replace
import importlib
import json
import os
from pathlib import Path
import sys
from threading import Barrier, Event
from types import ModuleType
from types import SimpleNamespace

from fuzzywuzzy import fuzz
import pytest
from sakura_taiko_core.chart import identity
from taiko_application.query import SongQueryContext, query_music
from taiko_application.query.song_index import build_song_index


@pytest.fixture
def host(tmp_path, monkeypatch):
    import taiko_bot
    name = '_song_snapshot_host'
    package = ModuleType(name)
    package.__path__ = [str(Path(taiko_bot.__file__).parent/'runtime/public')]
    config = ModuleType(name+'.config')
    config.root = lambda: tmp_path
    config.profile = lambda: 'center'
    monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, config.__name__, config)
    catalog = importlib.import_module(name+'.catalog')
    provider = importlib.import_module(name+'.provider')
    songs = tmp_path/'songs'
    songs.mkdir()
    def publish(rows=None, aliases=None):
        if rows is not None:
            atomic(songs/'song_data.json', rows)
        if aliases is not None:
            atomic(songs/'song_alias.json', aliases)
    publish([dict(id=1, song_name_jp='Old', type='分类', bpm='100')],
            [dict(id=1, aliases=['oldalias'])])
    yield catalog, provider, config, publish, songs
    for key in tuple(sys.modules):
        if key.startswith(name+'.'):
            sys.modules.pop(key, None)


def atomic(path, data):
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def test_revision_changes_on_alias_and_song_updates(host):
    catalog, provider, _, publish, _ = host
    first = catalog.get_snapshot()
    assert provider.query_with_mode('oldalias') == ([[1, 'Old']], 'exact_alias')
    assert catalog.get_snapshot() is first
    publish(aliases=[dict(id=1, aliases=['newalias'])])
    second = catalog.get_snapshot()
    assert second.revision != first.revision
    assert provider.query_with_mode('newalias') == ([[1, 'Old']], 'exact_alias')
    publish(rows=[dict(id=1, song_name_jp='Old'), dict(id=2, song_name_jp='New')])
    third = catalog.get_snapshot()
    assert third.revision != second.revision
    assert provider.query_with_mode('id2') == ([[2, 'New']], 'exact_id')
    assert first.index.literal_aliases['oldalias'] == ((1, 'Old'),)


def test_same_size_preserved_mtime_eventually_invalidates_even_on_coarse_ctime(host, monkeypatch):
    catalog, provider, _, _, songs = host
    clock = [0.0]
    monkeypatch.setattr(catalog, 'monotonic', lambda: clock[0])
    old = catalog.get_snapshot()
    path = songs/'song_alias.json'
    stat = path.stat()
    data = path.read_text().replace('oldalias', 'newalias')
    path.write_text(data)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    clock[0] = 31.0
    assert provider.query_with_mode('newalias')[1] == 'exact_alias'
    assert catalog.get_snapshot().revision != old.revision


def test_same_stamp_replacement_invalidates_immediately_by_inode(host):
    catalog, provider, _, _, songs = host
    old = catalog.get_snapshot()
    path = songs/'song_alias.json'
    stat = path.stat()
    temporary = path.with_suffix('.next')
    temporary.write_text(path.read_text().replace('oldalias', 'newalias'))
    os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    temporary.replace(path)
    assert provider.query_with_mode('newalias')[1] == 'exact_alias'
    assert catalog.get_snapshot().revision != old.revision


def test_periodic_identical_content_check_reuses_index_without_rebuild(host, monkeypatch):
    catalog, _, _, _, _ = host
    old = catalog.get_snapshot()
    monkeypatch.setattr(catalog, 'monotonic', lambda: catalog._store._verify_after + 1)
    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged content rebuilt')
    monkeypatch.setattr(catalog, 'build_song_index', forbidden)
    assert catalog.get_snapshot() is old


@pytest.mark.parametrize('payload', ['{broken', '{}', '[null]', '[{"id":1,"aliases":{}}]'])
def test_corruption_retains_old_and_recovers(host, payload):
    catalog, provider, _, publish, songs = host
    old = catalog.get_snapshot()
    (songs/'song_alias.json').write_text(payload)
    assert catalog.get_snapshot() is old
    failures = catalog._store.failures
    assert provider.query_with_mode('oldalias')[1] == 'exact_alias'
    assert catalog._store.failures == failures  # No repeated JSON load for a known broken revision.
    publish(aliases=[dict(id=1, aliases=['recovered'])])
    assert provider.query_with_mode('recovered')[1] == 'exact_alias'
    assert catalog.get_snapshot().revision != old.revision


def test_missing_file_retains_old_then_recovers(host):
    catalog, _, _, publish, songs = host
    old = catalog.get_snapshot()
    (songs/'song_data.json').unlink()
    assert catalog.get_snapshot() is old
    publish(rows=[dict(id=2, song_name_jp='Restored')])
    assert catalog.get_snapshot().index.id_to_title[2] == 'Restored'


@pytest.mark.parametrize('payload', ['null', '[null]', '[{"id":Infinity}]', '[{"id":1,"song_name":{}}]'])
def test_corrupt_song_structure_retains_snapshot(host, payload):
    catalog, _, _, _, songs = host
    old = catalog.get_snapshot()
    (songs/'song_data.json').write_text(payload)
    assert catalog.get_snapshot() is old


def test_preparation_failure_retains_snapshot_then_recovers(host, monkeypatch):
    catalog, provider, _, publish, _ = host
    old = catalog.get_snapshot()
    original = catalog.build_song_index
    publish(aliases=[dict(id=1, aliases=['newalias'])])
    def failing(*args, **kwargs):
        raise RuntimeError('preparation unavailable')
    monkeypatch.setattr(catalog, 'build_song_index', failing)
    assert catalog.get_snapshot() is old
    monkeypatch.setattr(catalog, 'build_song_index', original)
    publish(aliases=[dict(id=1, aliases=['recovered'])])
    assert provider.query_with_mode('recovered')[1] == 'exact_alias'


def test_initial_corruption_fails_and_does_not_install_snapshot(host):
    catalog, _, _, publish, songs = host
    (songs/'song_data.json').write_text('{')
    with pytest.raises(ValueError):
        catalog.get_snapshot()
    assert catalog._store._snapshot is None
    publish(rows=[dict(id=2, song_name_jp='Restored')])
    assert catalog.get_snapshot().index.id_to_title[2] == 'Restored'


def test_request_pins_prefix_retries_and_brief(host, monkeypatch):
    catalog, provider, _, publish, _ = host
    original = provider.query_with_mode
    revisions = []
    def updating(query, **kwargs):
        result = original(query, **kwargs)
        revisions.append(catalog.get_snapshot().revision)
        publish(rows=[dict(id=1, song_name_jp='Replacement')])
        return result
    monkeypatch.setattr(provider, 'query_with_mode', updating)
    with provider.catalog_request():
        assert provider.resolve('里Old', 'Old') == [[1, 'Old']]
        assert provider.brief(1) == '【Old】\n分类：分类\nBPM：100'
    assert len(revisions) == 2 and len(set(revisions)) == 1
    assert provider.brief(1) == '【Replacement】'


def test_context_resets_on_exception(host):
    catalog, _, _, publish, _ = host
    with pytest.raises(RuntimeError), catalog.catalog_request():
        catalog.get_snapshot()
        raise RuntimeError('cancel request')
    publish(rows=[dict(id=2, song_name_jp='New')])
    assert 2 in catalog.get_snapshot().index.id_to_title


def test_real_async_handler_pins_snapshot_through_delivery_await(host):
    catalog, provider, config, publish, _ = host
    from taiko_application import commands
    source = Path(provider.__file__).with_name('__init__.py')
    handler = next(node for node in ast.parse(source.read_text()).body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == 'handle')
    handler.decorator_list = []
    seen = []
    async def delivery(matcher, event, result):
        assert result.payload == ('Oni', '1')
        if event == 'old':
            publish(rows=[dict(id=1, song_name_jp='New')])
            ready.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        seen.append((event, provider.brief(1)))
    namespace = dict(commands=commands, provider=provider, profile=config.profile,
                     Matcher=object, Event=object, deliver=delivery,
                     transport=lambda: SimpleNamespace(is_qq_official_event=lambda event: True,
                         extract_plain_text=lambda event: 'id1是什么歌'),
                     extract=lambda text, official=False: text.removesuffix('是什么歌'))
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
    async def interleave():
        nonlocal ready, release
        ready, release = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(namespace['handle'](object(), 'old'))
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
            await namespace['handle'](object(), 'new')
        finally:
            release.set()
            await first
    ready = release = None
    asyncio.run(interleave())
    assert seen == [('new', '【New】'), ('old', '【Old】\n分类：分类\nBPM：100')]
    assert catalog.get_snapshot().index.id_to_title[1] == 'New'


def test_cold_load_error_keeps_command_error_result(host):
    catalog, provider, _, _, songs = host
    from taiko_application.commands import CommandContext, SongPorts, execute_song
    (songs/'song_data.json').write_text('{')
    with provider.catalog_request():
        result = execute_song(CommandContext(text='Old是什么歌'), SongPorts(
            _extract_what_song_query=lambda text: 'Old',
            _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
            _resolve_what_song_query=provider.resolve))
    assert result.kind == 'text' and result.payload.startswith('queryMusic 调用失败：')
    assert catalog._store._snapshot is None


def test_snapshot_is_deeply_immutable_and_results_are_owned(host):
    catalog, provider, _, _, _ = host
    snapshot = catalog.get_snapshot()
    with pytest.raises(FrozenInstanceError):
        snapshot.revision = 'changed'
    with pytest.raises(TypeError):
        snapshot.index.id_to_title[1] = 'changed'
    with pytest.raises(TypeError):
        snapshot.index.literal_names['old'][0][1] = 'changed'
    with pytest.raises(FrozenInstanceError):
        snapshot.index.groups_by_id[1].default_id = 99
    rows, _ = provider.query_with_mode('Old')
    rows[0][1] = 'changed'
    rows.clear()
    assert provider.query_with_mode('Old') == ([[1, 'Old']], 'exact_name')


def test_brief_preserves_last_duplicate_id_and_untitled_display(host):
    _, provider, _, publish, _ = host
    publish(rows=[dict(id=8, song_name_jp='Earlier'), dict(id='008', song_name_jp='', bpm=123)])
    assert provider.brief('008') == '【ID008】\nBPM：123'
    assert provider.brief(8) == '【ID8】\nBPM：123'
    assert provider.brief(999) == ''


def test_concurrent_cold_readers_build_once(host):
    catalog, _, _, _, _ = host
    barrier = Barrier(8)
    def read(_):
        barrier.wait(timeout=10)
        return catalog.get_snapshot()
    with ThreadPoolExecutor(max_workers=8) as pool:
        snapshots = list(pool.map(read, range(8)))
    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert catalog._store.loads == 1


def test_concurrent_requests_keep_own_revision_during_update(host):
    catalog, provider, _, publish, _ = host
    barrier = Barrier(5)
    release = Event()
    def reader():
        with provider.catalog_request():
            result = provider.query_with_mode('id1')
            barrier.wait(timeout=10)
            assert release.wait(timeout=10)
            return result, provider.brief(1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(reader) for _ in range(4)]
        try:
            barrier.wait(timeout=10)
            publish(rows=[dict(id=1, song_name_jp='New')])
            assert provider.query_with_mode('id1') == ([[1, 'New']], 'exact_id')
        finally:
            release.set()
        for future in futures:
            result, brief = future.result(timeout=10)
            assert result == ([[1, 'Old']], 'exact_id')
            assert brief.startswith('【Old】')


def test_update_during_build_retries_without_publishing_torn_snapshot(host, monkeypatch):
    catalog, _, _, publish, _ = host
    original = catalog.build_song_index
    calls = 0
    def build(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            publish(rows=[dict(id=1, song_name_jp='New')], aliases=[dict(id=1, aliases=['newalias'])])
        return result
    monkeypatch.setattr(catalog, 'build_song_index', build)
    snapshot = catalog.get_snapshot()
    assert calls == 2
    assert snapshot.query('newalias', fuzz.ratio) == ([[1, 'New']], 'exact_alias')
    assert catalog._store.loads == 1


def test_changing_root_does_not_serve_another_roots_last_good(host, tmp_path):
    catalog, _, _, _, _ = host
    catalog.get_snapshot()
    with pytest.raises(OSError):
        catalog._store.get(tmp_path/'missing/song_data.json', tmp_path/'missing/song_alias.json', 'center')


def test_writer_stops_after_retry_budget_then_recovers_without_another_write(host, monkeypatch):
    catalog, _, _, publish, _ = host
    old = catalog.get_snapshot()
    publish(rows=[dict(id=1, song_name_jp='Start')])
    original = catalog.build_song_index
    calls = 0
    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        publish(rows=[dict(id=1, song_name_jp=f'Generation{calls}')])
        return result
    monkeypatch.setattr(catalog, 'build_song_index', changing)
    assert catalog.get_snapshot() is old
    monkeypatch.setattr(catalog, 'build_song_index', original)
    assert catalog.get_snapshot().index.id_to_title[1] == 'Generation2'


@pytest.mark.parametrize('profile', ['center', 'client'])
def test_order_collisions_duplicates_and_fuzzy_ties(profile):
    songs = [dict(id=3, song_name_jp='A B'), dict(id=2, song_name_jp='AB'),
             dict(id=3, song_name_jp='Duplicate ID'), dict(id=4, song_name_jp='哥'),
             dict(id=5, song_name_jp='戈'), dict(id=6, song_name_jp='哥2'),
             dict(id='007', song_name_jp='String ID'), dict(id=8, song_name_jp='')]
    aliases = [dict(id='0002', aliases=['ＡＢ', '表哥', '  ', 'tie']),
               dict(id=5, aliases=['tie', '哥']), dict(id=8, aliases=['fallback'])]
    compare_queries(songs, aliases, profile, ['AB', 'A B', 'ＡＢ', 'id3', 'id7', 'fallback',
                    'String ID', 'Duplicate ID', 'tie', '表歌', '歌', '歌2', 'zz', '  ', None])


def compare_queries(songs, aliases, profile, queries):
    if profile == 'client':
        from sakura_taiko_core.chart.visibility import is_song_publicly_visible, normalize_song_id
        songs = [row for row in songs if is_song_publicly_visible(row)]
        ids = {normalize_song_id(row.get('id')) for row in songs} - {None}
        aliases = [row for row in aliases if normalize_song_id(row.get('id')) in ids]
    _, by_id, by_title = identity.build_group_maps(songs) if profile == 'center' else ({}, {}, {})
    index = build_song_index(songs, aliases, collapse_versions=profile == 'center')
    for query in queries:
        for partial, fuzzy in ((True, True), (True, False), (False, True), (False, False)):
            legacy = SongQueryContext(songs, aliases, by_id, by_title, fuzz.ratio,
                                      query=query, allow_partial=partial, allow_fuzzy=fuzzy)
            expected = query_music(legacy)
            actual = query_music(replace(legacy, index=index))
            assert actual == expected, f'query parity: {profile} {query!r} partial={partial} fuzzy={fuzzy}'


@pytest.mark.parametrize('profile', ['center', 'client'])
def test_real_catalog_differential(profile):
    directory = os.environ.get('TAIKO_SONG_TEST_CATALOG')
    if not directory:
        pytest.skip('Set TAIKO_SONG_TEST_CATALOG to the frozen public corpus')
    songs = json.loads((Path(directory)/'song_data.json').read_text())
    aliases = json.loads((Path(directory)/'song_alias.json').read_text())
    # Every real literal title, ID and alias, with extra normalized/partial/typo/
    # homophone/low-score cases. Exhaustive literals use exact-only to keep the
    # corpus replay bounded; the stage matrix exercises every matching flag.
    queries = []
    for row in songs:
        queries.extend(str(row[key]) for key in ('song_name_jp', 'song_name') if row.get(key))
        queries.extend((str(row['id']), 'id'+str(row['id'])))
    queries.extend(alias for row in aliases for alias in row.get('aliases') or [] if isinstance(alias, str))
    if profile == 'client':
        from sakura_taiko_core.chart.visibility import is_song_publicly_visible, normalize_song_id
        songs = [row for row in songs if is_song_publicly_visible(row)]
        ids = {normalize_song_id(row.get('id')) for row in songs} - {None}
        aliases = [row for row in aliases if normalize_song_id(row.get('id')) in ids]
    _, by_id, by_title = identity.build_group_maps(songs) if profile == 'center' else ({}, {}, {})
    index = build_song_index(songs, aliases, collapse_versions=profile == 'center')
    for query in dict.fromkeys(queries):
        legacy = SongQueryContext(songs, aliases, by_id, by_title, fuzz.ratio,
                                  query=query, allow_partial=False, allow_fuzzy=False)
        assert query_music(legacy) == query_music(replace(legacy, index=index)), f'real literal parity: {profile} {query!r}'
    compare_queries(songs, aliases, profile, ['waruloo', 'warulooo', 'waruioo', '毒loca', '毒ＬＯＣＡ',
                    'さいたま２０００', 'ｉｄ６４９', 'ｐｏｉｓｏｎ　ｃａｎｄｙ', '哥', '歌', '幽宣',
                    'night of knigts', 'zxqvjkzz', '里彁', '鬼千本桜'])
