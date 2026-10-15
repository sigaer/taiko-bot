from __future__ import annotations

import asyncio
import json

import pytest

from taiko_bot.runtime.player.center import arcade_map as am


@pytest.fixture
def sample_city_catalog(tmp_path, monkeypatch):
    payload = [
        {
            "name": "北京市",
            "name_pinyin": "bei-jing-shi",
            "province_code": "110000000000",
            "city_code": "110100000000",
        },
        {
            "name": "鞍山市",
            "name_pinyin": "an-shan-shi",
            "province_code": "210000000000",
            "city_code": "210300000000",
        },
        {
            "name": "马鞍山市",
            "name_pinyin": "ma-an-shan-shi",
            "province_code": "340000000000",
            "city_code": "340500000000",
        },
        {
            "name": "延边朝鲜族自治州",
            "name_pinyin": "yan-bian",
            "province_code": "220000000000",
            "city_code": "222400000000",
        },
        {
            "name": "重庆城区",
            "name_pinyin": "chong-qing-cheng-qu",
            "province_code": "500000000000",
            "city_code": "500100000000",
        },
        {
            "name": "重庆郊县",
            "name_pinyin": "chong-qing-jiao-xian",
            "province_code": "500000000000",
            "city_code": "500200000000",
        },
    ]
    path = tmp_path / "city.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(am, "CITY_DATA_PATH", path)
    am._load_city_entries.cache_clear()
    am._build_city_alias_index.cache_clear()
    am._build_address_city_matchers.cache_clear()
    yield path
    am._load_city_entries.cache_clear()
    am._build_city_alias_index.cache_clear()
    am._build_address_city_matchers.cache_clear()


@pytest.fixture
def sample_cache_dir(tmp_path, monkeypatch):
    cache_dir = tmp_path / "arcade_map_cache"
    monkeypatch.setattr(am, "MAP_DISK_CACHE_DIR", cache_dir)
    monkeypatch.setattr(am, "TAK_MAP_CACHE_PATH", tmp_path / "arcade_map_taklist_cache.json")
    am._CITY_QUERY_CACHE.clear()
    am._clear_tak_map_snapshot_cache()
    yield cache_dir
    am._CITY_QUERY_CACHE.clear()
    am._clear_tak_map_snapshot_cache()


def _build_sample_query_result(
    *,
    city_name: str = "鞍山市",
    total_arcade_records: int = 1,
    returned_arcade_records: int = 1,
    pagination_broken: bool = False,
    shop_name: str = "MELAND（鞍山万象汇店）",
) -> am.CityShopQueryResult:
    return am.CityShopQueryResult(
        city=am.CityEntry(
            city_code="210300000000",
            name=city_name,
            province_code="210000000000",
        ),
        total_arcade_records=total_arcade_records,
        returned_arcade_records=returned_arcade_records,
        pagination_broken=pagination_broken,
        shops=(
            am.CityShopEntry(
                shop_id=5651,
                name=shop_name,
                address="辽宁省鞍山市铁东区站前街道华润万象汇三楼反斗乐园",
                transport="鞍山火车站旁边",
                longitude="122.994768",
                latitude="41.108647",
                quantity=1,
                coin=9,
                version="国服",
                open_hours="09:00-20:00",
                machine_comment="机况良好，机台声音略小。",
                shop_comment="",
            ),
        ),
    )


def test_resolve_city_without_suffix(sample_city_catalog):
    result = am.resolve_city_entry("鞍山")
    assert result.city_code == "210300000000"
    assert result.name == "鞍山市"


def test_resolve_city_by_full_name(sample_city_catalog):
    result = am.resolve_city_entry("北京市")
    assert result.city_code == "110100000000"


def test_resolve_city_by_partial_unique_name(sample_city_catalog):
    result = am.resolve_city_entry("延边")
    assert result.city_code == "222400000000"
    assert result.name == "延边朝鲜族自治州"


def test_resolve_city_ambiguous(sample_city_catalog):
    with pytest.raises(ValueError) as exc_info:
        am.resolve_city_entry("重庆")
    assert "重庆城区" in str(exc_info.value)
    assert "重庆郊县" in str(exc_info.value)


def test_format_taiko_city_shop_reply_with_page_issue():
    result = am.CityShopQueryResult(
        city=am.CityEntry(
            city_code="210300000000",
            name="鞍山市",
            province_code="210000000000",
        ),
        total_arcade_records=56,
        returned_arcade_records=20,
        pagination_broken=True,
        shops=(
            _build_sample_query_result().shops[0],
            am.CityShopEntry(
                shop_id=9999,
                name="示例店铺",
                address="示例地址",
                transport="",
                longitude="",
                latitude="",
                quantity=2,
                coin=6,
                version="2026春",
                open_hours="10:00-22:00",
                machine_comment="",
                shop_comment="店铺备注",
            ),
        ),
    )

    text = am.format_taiko_city_shop_reply(result)
    assert "鞍山市哪有鼓" in text
    assert "翻页当前会跳回列表页" in text
    assert "MELAND（鞍山万象汇店）｜1台｜国服｜9币/PC｜09:00-20:00" in text
    assert "备注：机况良好，机台声音略小。" in text
    assert "示例店铺｜2台｜2026春｜6币/PC｜10:00-22:00" in text


def test_tak_map_row_matches_city_with_alias(sample_city_catalog):
    city = am.resolve_city_entry("北京")
    row = {
        "shop_id": 0,
        "tak_id": 1,
        "address": "北京丰台区万丰路68号院和谐广场三层301室卡通尼乐园",
        "store_name": "卡通尼北京和谐广场店",
        "shop": {},
    }
    assert am._tak_map_row_matches_city(row, city) is True


def test_resolve_city_from_text_prefers_longer_match(sample_city_catalog):
    resolved = am._resolve_city_from_text("安徽省马鞍山市雨山区安民街道太白大道3200号")
    assert resolved is not None
    assert resolved.name == "马鞍山市"


def test_build_base_shop_entry_from_tak_map_row(sample_city_catalog):
    row = {
        "shop_id": 0,
        "tak_id": 849,
        "address": "新疆伊犁哈萨克自治州伊宁市解放路79号万力时尚三楼",
        "store_name": "好好玩岛伊犁伊宁万力时尚店",
        "temp_lnglat": "81.319776,43.921642",
        "shop": {},
    }
    entry = am._build_base_shop_entry_from_tak_map_row(row)
    assert entry.shop_id == 0
    assert entry.name == "好好玩岛伊犁伊宁万力时尚店"
    assert "坐标 81.319776, 43.921642" == entry.transport
    assert entry.longitude == "81.319776"
    assert entry.latitude == "43.921642"


def test_collect_city_shop_locations_uses_explicit_coordinates():
    result = _build_sample_query_result()
    locations = am.collect_city_shop_locations(result)

    assert len(locations) == 1
    assert locations[0].shop.name == "MELAND（鞍山万象汇店）"
    assert locations[0].longitude == pytest.approx(122.994768)
    assert locations[0].latitude == pytest.approx(41.108647)


def test_build_tencent_map_location_json_matches_template():
    shop = _build_sample_query_result().shops[0]
    payload_text = am.build_tencent_map_location_json(shop)
    assert payload_text is not None

    payload = json.loads(payload_text)
    assert payload["app"] == "com.tencent.map"
    assert payload["view"] == "LocationShare"
    location = payload["meta"]["Location.Search"]
    assert location["name"] == shop.name
    assert location["address"] == shop.address
    assert location["lat"] == shop.latitude
    assert location["lng"] == shop.longitude
    assert location["from"] == "plusPanel"
    assert payload["config"] == {"forward": 1, "autosize": 1, "type": "card"}


def test_build_tencent_map_location_json_rejects_invalid_coordinates():
    shop = am.CityShopEntry(
        shop_id=1,
        name="无效坐标店铺",
        address="示例地址",
        transport="",
        longitude="181.0",
        latitude="91.0",
        quantity=1,
        coin=8,
        version="国服",
        open_hours="10:00-22:00",
        machine_comment="",
        shop_comment="",
    )
    assert am.build_tencent_map_location_json(shop) is None


def test_format_taiko_city_shop_summary_without_shop_details():
    result = _build_sample_query_result()
    summary = am.format_taiko_city_shop_summary(result)
    assert "鞍山市哪有鼓" in summary
    assert "共 1 家店铺。" in summary
    assert "以下为分店铺地图卡片。" in summary
    assert result.shops[0].address not in summary


def test_format_taiko_city_shop_entry_includes_shop_details():
    shop = _build_sample_query_result().shops[0]
    entry = am.format_taiko_city_shop_entry(1, shop)
    assert "MELAND（鞍山万象汇店）" in entry
    assert "1台" in entry
    assert shop.address in entry
    assert "备注：机况良好，机台声音略小。" in entry


def test_format_city_shop_forward_nickname():
    shop = _build_sample_query_result().shops[0]
    nickname = am.format_city_shop_forward_nickname(1, shop)
    assert nickname == "1. MELAND（鞍山万象汇店）｜1台｜国服｜9币/PC｜09:00-20:00"


def test_collect_city_shop_locations_skips_invalid_coordinates():
    result = am.CityShopQueryResult(
        city=am.CityEntry(
            city_code="210300000000",
            name="鞍山市",
            province_code="210000000000",
        ),
        total_arcade_records=1,
        returned_arcade_records=1,
        pagination_broken=False,
        shops=(
            am.CityShopEntry(
                shop_id=1,
                name="无效坐标店铺",
                address="示例地址",
                transport="",
                longitude="181.0",
                latitude="91.0",
                quantity=1,
                coin=8,
                version="国服",
                open_hours="10:00-22:00",
                machine_comment="",
                shop_comment="",
            ),
        ),
    )

    assert am.collect_city_shop_locations(result) == ()


def test_tak_map_snapshot_disk_round_trip(sample_cache_dir):
    rows = (
        {
            "shop_id": 0,
            "tak_id": 1,
            "address": "北京市朝阳区示例地址",
            "store_name": "示例店",
            "temp_lnglat": "116.1,39.9",
            "longitude": "",
            "latitude": "",
            "shop": {
                "id": 0,
                "name": "",
                "address": "",
                "longitude": "",
                "latitude": "",
            },
        },
    )
    am._write_tak_map_snapshot_disk(rows, "2026-05-25T03:41:54.000000Z", fetched_at_epoch=1234)
    cached = am._load_tak_map_snapshot_disk()
    assert cached is not None
    fetched_at_epoch, loaded_rows, latest = cached
    assert fetched_at_epoch == 1234
    assert loaded_rows == rows
    assert latest == "2026-05-25T03:41:54.000000Z"


def test_disk_cache_round_trip(sample_cache_dir):
    result = _build_sample_query_result()
    am._write_city_disk_cache("210300000000", result, cached_at_epoch=1234567890)
    cached = am._load_city_disk_cache("210300000000")
    assert cached is not None
    cached_at_epoch, loaded_result = cached
    assert cached_at_epoch == 1234567890
    assert loaded_result == result


def test_query_uses_fresh_disk_cache(
    sample_city_catalog, sample_cache_dir, monkeypatch
):
    result = _build_sample_query_result(shop_name="缓存店铺")
    am._write_city_disk_cache("210300000000", result, cached_at_epoch=1_000_000)
    monkeypatch.setattr(am.time, "time", lambda: 1_000_060)

    calls = {"count": 0}

    async def fake_remote(_city):
        calls["count"] += 1
        return _build_sample_query_result(shop_name="远端店铺")

    monkeypatch.setattr(am, "_fetch_remote_city_query_result", fake_remote)
    queried = asyncio.run(am.query_taiko_shops_by_city("鞍山"))
    assert queried == result
    assert calls["count"] == 0


def test_query_refreshes_stale_disk_cache(
    sample_city_catalog, sample_cache_dir, monkeypatch
):
    stale_result = _build_sample_query_result(shop_name="旧缓存店铺")
    fresh_result = _build_sample_query_result(shop_name="最新店铺")
    stale_epoch = 1_000_000
    fresh_epoch = stale_epoch + am.MAP_DISK_CACHE_TTL_SECONDS + 1
    am._write_city_disk_cache("210300000000", stale_result, cached_at_epoch=stale_epoch)
    monkeypatch.setattr(am.time, "time", lambda: fresh_epoch)

    calls = {"count": 0}

    async def fake_remote(_city):
        calls["count"] += 1
        return fresh_result

    monkeypatch.setattr(am, "_fetch_remote_city_query_result", fake_remote)
    queried = asyncio.run(am.query_taiko_shops_by_city("鞍山"))
    assert queried == fresh_result
    assert calls["count"] == 1

    cached = am._load_city_disk_cache("210300000000")
    assert cached is not None
    cached_at_epoch, loaded_result = cached
    assert cached_at_epoch == fresh_epoch
    assert loaded_result == fresh_result
