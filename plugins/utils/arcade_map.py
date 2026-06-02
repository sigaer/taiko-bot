from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from taiko_bot.settings import get_settings
from taiko_bot.viewer_client import fetch_arcade_snapshot

BASE_PATH = get_settings().root_dir
CITY_DATA_PATH = BASE_PATH / "city.json"
MAP_DISK_CACHE_DIR = get_settings().runtime_data_dir / "arcade_map_cache"
TAK_MAP_CACHE_PATH = get_settings().runtime_data_dir / "arcade_map_taklist_cache.json"

MAP_CITY_CACHE_TTL_SECONDS = 300
MAP_DISK_CACHE_TTL_SECONDS = 72 * 3600
MAP_DISK_CACHE_SCHEMA_VERSION = 3
TAK_MAP_CACHE_SCHEMA_VERSION = 1
CITY_SUFFIXES = (
    "特别行政区",
    "自治州",
    "自治县",
    "自治旗",
    "地区",
    "郊县",
    "城区",
    "盟",
    "市",
    "县",
)

_CITY_QUERY_CACHE: Dict[str, tuple[float, "CityShopQueryResult"]] = {}
_LAST_SYNC_STATE: Optional[tuple[float, Dict[str, Any]]] = None


@dataclass(frozen=True)
class CityEntry:
    city_code: str
    name: str
    province_code: str
    name_pinyin: str = ""


@dataclass(frozen=True)
class CityShopEntry:
    shop_id: int
    name: str
    address: str
    transport: str
    longitude: str
    latitude: str
    quantity: int
    coin: int
    version: str
    open_hours: str
    machine_comment: str
    shop_comment: str


@dataclass(frozen=True)
class CityShopQueryResult:
    city: CityEntry
    total_arcade_records: int
    returned_arcade_records: int
    shops: tuple[CityShopEntry, ...]
    pagination_broken: bool


def _collapse_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _trim_text(value: Any, limit: int) -> str:
    text = _collapse_text(value)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _normalize_city_query(value: str) -> str:
    return re.sub(r"[\s·•．.·()（）]+", "", str(value or "").strip())


def _city_alias_candidates(name: str) -> set[str]:
    text = _normalize_city_query(name)
    aliases = {text}
    working = text
    for suffix in CITY_SUFFIXES:
        if working.endswith(suffix):
            working = working[: -len(suffix)]
            if working:
                aliases.add(working)
    if "自治" in text:
        prefix = text.split("自治", 1)[0]
        prefix = re.sub(r"(?:[\u4e00-\u9fa5]{1,4}族)+$", "", prefix)
        if prefix:
            aliases.add(prefix)
    return {alias for alias in aliases if alias}


@lru_cache(maxsize=1)
def _load_city_entries() -> tuple[CityEntry, ...]:
    with CITY_DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    entries: list[CityEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        city_code = _collapse_text(item.get("city_code"))
        name = _collapse_text(item.get("name"))
        province_code = _collapse_text(item.get("province_code"))
        if not city_code or not name:
            continue
        entries.append(
            CityEntry(
                city_code=city_code,
                name=name,
                province_code=province_code,
                name_pinyin=_collapse_text(item.get("name_pinyin")),
            )
        )
    return tuple(entries)


@lru_cache(maxsize=1)
def _build_city_alias_index() -> dict[str, tuple[CityEntry, ...]]:
    alias_index: dict[str, list[CityEntry]] = {}
    for entry in _load_city_entries():
        for alias in _city_alias_candidates(entry.name):
            alias_index.setdefault(alias, []).append(entry)
    return {key: tuple(value) for key, value in alias_index.items()}


def resolve_city_entry(query: str) -> CityEntry:
    normalized = _normalize_city_query(query)
    if not normalized:
        raise ValueError("城市名不能为空，请直接发送“鞍山哪有鼓”这类指令。")

    alias_index = _build_city_alias_index()
    exact_matches = alias_index.get(normalized)
    if exact_matches:
        if len(exact_matches) == 1:
            return exact_matches[0]
        names = "、".join(entry.name for entry in exact_matches)
        raise ValueError(f"“{query}”可能指：{names}，请说得更完整一些。")

    partial_matches: list[CityEntry] = []
    for entry in _load_city_entries():
        entry_name = _normalize_city_query(entry.name)
        if normalized in entry_name or entry_name in normalized:
            partial_matches.append(entry)
    unique_partial = {entry.city_code: entry for entry in partial_matches}
    if len(unique_partial) == 1:
        return next(iter(unique_partial.values()))
    if len(unique_partial) > 1:
        names = "、".join(entry.name for entry in unique_partial.values())
        raise ValueError(f"“{query}”可能指：{names}，请说得更完整一些。")

    suggestions: list[str] = []
    for entry in _load_city_entries():
        entry_name = _normalize_city_query(entry.name)
        if entry_name.startswith(normalized[:1]) or normalized[:1] in entry_name:
            suggestions.append(entry.name)
        if len(suggestions) >= 4:
            break
    suggestion_text = f" 你可以试试：{'、'.join(suggestions)}。" if suggestions else ""
    raise ValueError(f"没识别出“{query}”是哪个地级市。{suggestion_text}".strip())


def _city_disk_cache_path(city_code: str) -> Path:
    return MAP_DISK_CACHE_DIR / f"{city_code}.json"


def _serialize_city_entry(entry: CityEntry) -> dict[str, Any]:
    return {
        "city_code": entry.city_code,
        "name": entry.name,
        "province_code": entry.province_code,
        "name_pinyin": entry.name_pinyin,
    }


def _deserialize_city_entry(payload: dict[str, Any]) -> CityEntry:
    return CityEntry(
        city_code=_collapse_text(payload.get("city_code")),
        name=_collapse_text(payload.get("name")),
        province_code=_collapse_text(payload.get("province_code")),
        name_pinyin=_collapse_text(payload.get("name_pinyin")),
    )


def _serialize_city_shop_entry(entry: CityShopEntry) -> dict[str, Any]:
    return {
        "shop_id": entry.shop_id,
        "name": entry.name,
        "address": entry.address,
        "transport": entry.transport,
        "longitude": entry.longitude,
        "latitude": entry.latitude,
        "quantity": entry.quantity,
        "coin": entry.coin,
        "version": entry.version,
        "open_hours": entry.open_hours,
        "machine_comment": entry.machine_comment,
        "shop_comment": entry.shop_comment,
    }


def _deserialize_city_shop_entry(payload: dict[str, Any]) -> CityShopEntry:
    return CityShopEntry(
        shop_id=int(payload.get("shop_id") or 0),
        name=_collapse_text(payload.get("name")),
        address=_collapse_text(payload.get("address")),
        transport=_collapse_text(payload.get("transport")),
        longitude=_collapse_text(payload.get("longitude")),
        latitude=_collapse_text(payload.get("latitude")),
        quantity=int(payload.get("quantity") or 0),
        coin=int(payload.get("coin") or 0),
        version=_collapse_text(payload.get("version")),
        open_hours=_collapse_text(payload.get("open_hours")),
        machine_comment=_collapse_text(payload.get("machine_comment")),
        shop_comment=_collapse_text(payload.get("shop_comment")),
    )


def _serialize_city_shop_query_result(result: CityShopQueryResult) -> dict[str, Any]:
    return {
        "city": _serialize_city_entry(result.city),
        "total_arcade_records": result.total_arcade_records,
        "returned_arcade_records": result.returned_arcade_records,
        "shops": [_serialize_city_shop_entry(shop) for shop in result.shops],
        "pagination_broken": result.pagination_broken,
    }


def _deserialize_city_shop_query_result(payload: dict[str, Any]) -> CityShopQueryResult:
    city = payload.get("city") or {}
    shops = payload.get("shops") or []
    return CityShopQueryResult(
        city=_deserialize_city_entry(city),
        total_arcade_records=int(payload.get("total_arcade_records") or 0),
        returned_arcade_records=int(payload.get("returned_arcade_records") or 0),
        shops=tuple(
            _deserialize_city_shop_entry(shop)
            for shop in shops
            if isinstance(shop, dict)
        ),
        pagination_broken=bool(payload.get("pagination_broken")),
    )


def _load_city_disk_cache(city_code: str) -> Optional[tuple[int, CityShopQueryResult]]:
    cache_path = _city_disk_cache_path(city_code)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("schema_version") != MAP_DISK_CACHE_SCHEMA_VERSION:
        return None
    cached_at_epoch = int(payload.get("cached_at_epoch") or 0)
    result_payload = payload.get("result")
    if not isinstance(result_payload, dict):
        return None
    try:
        result = _deserialize_city_shop_query_result(result_payload)
    except Exception:
        return None
    if result.city.city_code != city_code:
        return None
    return cached_at_epoch, result


def _write_city_disk_cache(
    city_code: str,
    result: CityShopQueryResult,
    *,
    cached_at_epoch: Optional[int] = None,
) -> None:
    cache_path = _city_disk_cache_path(city_code)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": MAP_DISK_CACHE_SCHEMA_VERSION,
        "cached_at_epoch": int(cached_at_epoch if cached_at_epoch is not None else time.time()),
        "result": _serialize_city_shop_query_result(result),
    }
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(cache_path)


def _is_disk_cache_fresh(
    cached_at_epoch: int,
    *,
    now_epoch: Optional[int] = None,
) -> bool:
    if cached_at_epoch <= 0:
        return False
    current_epoch = int(now_epoch if now_epoch is not None else time.time())
    if current_epoch <= cached_at_epoch:
        return True
    return current_epoch - cached_at_epoch < MAP_DISK_CACHE_TTL_SECONDS


def sync_taiko_arcade_snapshot(
    *, force: bool = False
) -> Dict[str, Any]:
    global _LAST_SYNC_STATE
    now_monotonic = time.monotonic()
    if (
        not force
        and _LAST_SYNC_STATE is not None
        and now_monotonic - _LAST_SYNC_STATE[0] < MAP_CITY_CACHE_TTL_SECONDS
    ):
        return dict(_LAST_SYNC_STATE[1])

    snapshot = fetch_arcade_snapshot()
    city_snapshots = snapshot.get("citySnapshots") or []
    taklist_snapshot = snapshot.get("taklistSnapshot")
    if not isinstance(city_snapshots, list):
        raise RuntimeError("中心地图快照格式异常：citySnapshots 不是列表。")

    written_cities = 0
    for item in city_snapshots:
        if not isinstance(item, dict):
            continue
        if int(item.get("schema_version") or 0) != MAP_DISK_CACHE_SCHEMA_VERSION:
            continue
        result_payload = item.get("result")
        if not isinstance(result_payload, dict):
            continue
        try:
            result = _deserialize_city_shop_query_result(result_payload)
        except Exception:
            continue
        if not result.city.city_code:
            continue
        _write_city_disk_cache(
            result.city.city_code,
            result,
            cached_at_epoch=int(item.get("cached_at_epoch") or time.time()),
        )
        _CITY_QUERY_CACHE.pop(result.city.city_code, None)
        written_cities += 1

    if isinstance(taklist_snapshot, dict) and taklist_snapshot:
        TAK_MAP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = TAK_MAP_CACHE_PATH.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(taklist_snapshot, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(TAK_MAP_CACHE_PATH)

    summary = {
        "ok": True,
        "writtenCities": written_cities,
        "hasTaklistSnapshot": isinstance(taklist_snapshot, dict) and bool(taklist_snapshot),
        "generatedAt": snapshot.get("generatedAt") or "",
    }
    _LAST_SYNC_STATE = (now_monotonic, summary)
    return dict(summary)


async def query_taiko_shops_by_city(city_name: str) -> CityShopQueryResult:
    city = resolve_city_entry(city_name)
    cache_key = city.city_code
    now_monotonic = time.monotonic()
    cached = _CITY_QUERY_CACHE.get(cache_key)
    if cached and now_monotonic - cached[0] < MAP_CITY_CACHE_TTL_SECONDS:
        return cached[1]

    disk_cached = _load_city_disk_cache(cache_key)
    if disk_cached is not None:
        cached_at_epoch, cached_result = disk_cached
        if _is_disk_cache_fresh(cached_at_epoch):
            _CITY_QUERY_CACHE[cache_key] = (now_monotonic, cached_result)
            return cached_result

    sync_error: Optional[Exception] = None
    try:
        sync_taiko_arcade_snapshot(force=True)
    except Exception as exc:
        sync_error = exc

    disk_cached = _load_city_disk_cache(cache_key)
    if disk_cached is not None:
        _cached_at_epoch, cached_result = disk_cached
        _CITY_QUERY_CACHE[cache_key] = (now_monotonic, cached_result)
        return cached_result

    if sync_error is not None:
        raise RuntimeError(f"同步本机地图缓存失败：{sync_error}") from sync_error
    raise RuntimeError(f"{city.name} 暂时没有查到太鼓店铺信息。")


def _build_shop_info_bits(shop: CityShopEntry) -> list[str]:
    info_bits: list[str] = []
    if shop.quantity > 0:
        info_bits.append(f"{shop.quantity}台")
    if shop.version:
        info_bits.append(shop.version)
    if shop.coin > 0:
        info_bits.append(f"{shop.coin}币/PC")
    if shop.open_hours:
        info_bits.append(shop.open_hours)
    return info_bits


def format_taiko_city_shop_summary(result: CityShopQueryResult) -> str:
    lines = [f"{result.city.name}哪有鼓"]
    if result.pagination_broken:
        lines.append(
            f"地图登记 {result.total_arcade_records} 条机台记录；"
            f"该站快照当前不完整，先展示本机缓存中稳定拿到的 {len(result.shops)} 家店铺。"
        )
    elif result.total_arcade_records != len(result.shops):
        lines.append(
            f"地图登记 {result.total_arcade_records} 条机台记录，整理后共 {len(result.shops)} 家店铺。"
        )
    else:
        lines.append(f"共 {len(result.shops)} 家店铺。")
    lines.append("以下为分店铺地图卡片。")
    return "\n".join(lines)


def format_city_shop_forward_nickname(index: int, shop: CityShopEntry) -> str:
    info_bits = _build_shop_info_bits(shop)
    title = shop.name or "店铺信息"
    if info_bits:
        return f"{index}. {title}｜{'｜'.join(info_bits)}"
    return f"{index}. {title}"


def format_taiko_city_shop_entry(index: int, shop: CityShopEntry) -> str:
    info_bits = _build_shop_info_bits(shop)
    lines = [
        f"{index}. {shop.name}" + (f"｜{'｜'.join(info_bits)}" if info_bits else "")
    ]
    if shop.address:
        lines.append(shop.address)
    if shop.transport:
        lines.append(f"交通：{shop.transport}")
    elif shop.longitude and shop.latitude:
        lines.append(f"坐标：{shop.longitude}, {shop.latitude}")
    for comment in (shop.machine_comment, shop.shop_comment):
        if comment:
            lines.append(f"备注：{comment}")
    return "\n".join(lines)


def _parse_float_coordinate(
    value: str,
    *,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def build_tencent_map_location_json(shop: CityShopEntry) -> Optional[str]:
    latitude_text = _collapse_text(shop.latitude)
    longitude_text = _collapse_text(shop.longitude)
    if (
        _parse_float_coordinate(latitude_text, minimum=-90.0, maximum=90.0) is None
        or _parse_float_coordinate(longitude_text, minimum=-180.0, maximum=180.0)
        is None
    ):
        return None

    name = _collapse_text(shop.name) or "店铺位置"
    address = _collapse_text(shop.address) or name
    payload = {
        "app": "com.tencent.map",
        "desc": "地图",
        "view": "LocationShare",
        "ver": "0.0.0.1",
        "prompt": "[应用]地图",
        "from": 1,
        "meta": {
            "Location.Search": {
                "id": "",
                "name": name,
                "address": address,
                "lat": latitude_text,
                "lng": longitude_text,
                "from": "plusPanel",
            }
        },
        "config": {"forward": 1, "autosize": 1, "type": "card"},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def format_taiko_city_shop_reply(result: CityShopQueryResult) -> str:
    if not result.shops:
        return f"{result.city.name} 暂时没有查到太鼓店铺信息。"

    header_lines = [f"{result.city.name}哪有鼓"]
    if result.pagination_broken:
        header_lines.append(
            f"地图登记 {result.total_arcade_records} 条机台记录；"
            f"该站快照当前不完整，先展示本机缓存中稳定拿到的 {len(result.shops)} 家店铺。"
        )
    elif result.total_arcade_records != len(result.shops):
        header_lines.append(
            f"地图登记 {result.total_arcade_records} 条机台记录，整理后共 {len(result.shops)} 家店铺。"
        )
    else:
        header_lines.append(f"共 {len(result.shops)} 家店铺。")

    body_lines: list[str] = []
    for index, shop in enumerate(result.shops, start=1):
        info_bits = _build_shop_info_bits(shop)
        address_line = shop.address or "地址待补充"
        if shop.transport:
            address_line = f"{address_line}（{_trim_text(shop.transport, 30)}）"
        body_lines.append(
            f"{index}. {shop.name}"
            + (f"｜{'｜'.join(info_bits)}" if info_bits else "")
        )
        body_lines.append(address_line)
        comment = shop.machine_comment or shop.shop_comment
        if comment:
            body_lines.append(f"备注：{comment}")

    return "\n".join(header_lines + [""] + body_lines)
