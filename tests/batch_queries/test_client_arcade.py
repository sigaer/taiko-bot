"""Client snapshot persistence: synthetic API, real isolated cache files."""
import asyncio
import json
import pytest
from taiko_bot.runtime.player.client import arcade_map as arcade


def test_snapshot_cold_hot_and_offline_fallback(tmp_path, monkeypatch):
    city = arcade.CityEntry('2103', '鞍山市', '21')
    result = arcade.CityShopQueryResult(city, 1, 1, (
        arcade.CityShopEntry(1, '测试店', '测试地址', '', '123', '41', 1, 2,
                             '虹', '10:00', '', ''),), False)
    calls = []
    clock = [1000000]
    monkeypatch.setattr(arcade, 'MAP_DISK_CACHE_DIR', tmp_path / 'cities')
    monkeypatch.setattr(arcade, 'TAK_MAP_CACHE_PATH', tmp_path / 'tak.json')
    monkeypatch.setattr(arcade, '_CITY_QUERY_CACHE', {})
    monkeypatch.setattr(arcade, '_LAST_SYNC_STATE', None)
    monkeypatch.setattr(arcade, 'resolve_city_entry', lambda _: city)
    monkeypatch.setattr(arcade.time, 'time', lambda: clock[0])
    monkeypatch.setattr(arcade.time, 'monotonic', lambda: clock[0])
    def fetch():
        calls.append('fetch')
        return {'citySnapshots': [{'schema_version': 3, 'cached_at_epoch': clock[0],
                'result': arcade._serialize_city_shop_query_result(result)}],
                'taklistSnapshot': {'schema_version': 1, 'shops': []}}
    monkeypatch.setattr(arcade, 'fetch_arcade_snapshot', fetch)
    assert asyncio.run(arcade.query_taiko_shops_by_city('鞍山')) == result
    cache = tmp_path / 'cities/2103.json'
    first = cache.stat().st_mtime_ns
    assert json.loads(cache.read_text())['schema_version'] == 3
    assert asyncio.run(arcade.query_taiko_shops_by_city('鞍山市')) == result
    arcade._CITY_QUERY_CACHE.clear()
    assert asyncio.run(arcade.query_taiko_shops_by_city('鞍山')) == result
    assert calls == ['fetch'] and cache.stat().st_mtime_ns == first
    clock[0] += arcade.MAP_DISK_CACHE_TTL_SECONDS + 1
    def offline():
        calls.append('offline')
        raise OSError('isolated API unavailable')
    monkeypatch.setattr(arcade, 'fetch_arcade_snapshot', offline)
    assert asyncio.run(arcade.query_taiko_shops_by_city('鞍山')) == result
    assert calls == ['fetch', 'offline'] and cache.stat().st_mtime_ns == first
    arcade._CITY_QUERY_CACHE.clear()
    cache.unlink()
    with pytest.raises(RuntimeError, match='同步本机地图缓存失败'):
        asyncio.run(arcade.query_taiko_shops_by_city('鞍山'))
