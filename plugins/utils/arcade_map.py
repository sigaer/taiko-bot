from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx
from taiko_bot.settings import get_settings

BASE_PATH = get_settings().root_dir
CITY_DATA_PATH = BASE_PATH / "city.json"
CONFIG_PATH = BASE_PATH / "config.json"
BEMANICN_LOGIN_PATH = BASE_PATH / "capture" / "login"
MAP_DISK_CACHE_DIR = BASE_PATH / "data" / "arcade_map_cache"
TAK_MAP_CACHE_PATH = BASE_PATH / "data" / "arcade_map_taklist_cache.json"

MAP_GAME_ID = 31
MAP_AUTHORIZE_URL = (
    "https://bemanicn.com/oauth/authorize"
    "?client_id=94efc137-0b63-4e1b-ae7e-0cd43dc86961"
    "&redirect_uri=https%3A%2F%2Fmap.bemanicn.com%2Foauth%2Fcallback"
    "&response_type=code&scope=&state=taiko_map_query"
)
MAP_CITY_CACHE_TTL_SECONDS = 300
MAP_DISK_CACHE_TTL_SECONDS = 72 * 3600
MAP_DISK_CACHE_SCHEMA_VERSION = 3
TAK_MAP_CACHE_SCHEMA_VERSION = 1
MAX_DETAIL_CONCURRENCY = 5
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
    "Gecko/20100101 Firefox/150.0"
)
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
_TAK_MAP_SNAPSHOT_CACHE: Optional[
    tuple[int, tuple[dict[str, Any], ...], str]
] = None


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


@dataclass(frozen=True)
class CityShopLocation:
    shop: CityShopEntry
    latitude: float
    longitude: float


def _city_disk_cache_path(city_code: str) -> Path:
    return MAP_DISK_CACHE_DIR / f"{city_code}.json"


def _clear_tak_map_snapshot_cache() -> None:
    global _TAK_MAP_SNAPSHOT_CACHE
    _TAK_MAP_SNAPSHOT_CACHE = None


def _collapse_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _trim_text(value: Any, limit: int) -> str:
    text = _collapse_text(value)
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def _split_lnglat_text(value: Any) -> tuple[str, str]:
    text = _collapse_text(value)
    if not text:
        return "", ""
    parts = [part.strip() for part in text.split(",", 1)]
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


def _resolve_coordinates(
    *,
    longitude: Any = "",
    latitude: Any = "",
    temp_lnglat: Any = "",
) -> tuple[str, str]:
    lon = _collapse_text(longitude)
    lat = _collapse_text(latitude)
    if lon and lat:
        return lon, lat
    return _split_lnglat_text(temp_lnglat)


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


@lru_cache(maxsize=1)
def _build_address_city_matchers() -> tuple[tuple[str, CityEntry], ...]:
    matchers: list[tuple[str, CityEntry]] = []
    for entry in _load_city_entries():
        tokens = set(_city_alias_candidates(entry.name))
        tokens.add(_normalize_city_query(entry.name))
        for token in tokens:
            if token:
                matchers.append((token, entry))
    matchers.sort(key=lambda item: (len(item[0]), len(item[1].name)), reverse=True)
    return tuple(matchers)


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
        if not normalized:
            continue
        if entry_name.startswith(normalized[:1]) or normalized[:1] in entry_name:
            suggestions.append(entry.name)
        if len(suggestions) >= 4:
            break
    suggestion_text = f" 你可以试试：{'、'.join(suggestions)}。" if suggestions else ""
    raise ValueError(f"没识别出“{query}”是哪个地级市。{suggestion_text}".strip())


def _get_cookie_value(
    client: httpx.AsyncClient,
    name: str,
    *,
    domain: Optional[str] = None,
) -> str:
    for cookie in client.cookies.jar:
        if cookie.name != name:
            continue
        if domain and cookie.domain != domain:
            continue
        return cookie.value
    return ""


def _load_bemanicn_credentials() -> tuple[str, str]:
    email = str(os.getenv("BEMANICN_EMAIL") or "").strip()
    password = str(os.getenv("BEMANICN_PASSWORD") or "").strip()
    if email and password:
        return email, password

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        config = {}
    login_config = config.get("bemanicn")
    if isinstance(login_config, dict):
        email = str(login_config.get("email") or "").strip()
        password = str(login_config.get("password") or "").strip()
        if email and password:
            return email, password
    email = str(config.get("bemanicn_email") or "").strip()
    password = str(config.get("bemanicn_password") or "").strip()
    if email and password:
        return email, password

    try:
        with BEMANICN_LOGIN_PATH.open("r", encoding="utf-8") as f:
            login_payload = json.load(f)
    except Exception:
        login_payload = {}
    email = str(login_payload.get("email") or "").strip()
    password = str(login_payload.get("password") or "").strip()
    if email and password:
        return email, password

    raise RuntimeError("未配置 BEMANICN 登录信息，暂时无法查询太鼓地图。")


async def _ensure_map_session(client: httpx.AsyncClient) -> None:
    email, password = _load_bemanicn_credentials()
    await client.get(
        "https://bemanicn.com/login",
        headers={"Accept": "text/html, application/xhtml+xml"},
    )
    xsrf_token = urllib.parse.unquote(
        _get_cookie_value(client, "XSRF-TOKEN", domain="bemanicn.com")
    )
    if not xsrf_token:
        raise RuntimeError("初始化 BEMANICN 登录会话失败。")

    login_resp = await client.post(
        "https://bemanicn.com/login",
        json={"email": email, "password": password, "remember": ""},
        headers={
            "Accept": "text/html, application/xhtml+xml",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Inertia": "true",
            "X-XSRF-TOKEN": xsrf_token,
            "Origin": "https://bemanicn.com",
            "Referer": "https://bemanicn.com/login",
        },
    )
    if login_resp.status_code >= 500:
        raise RuntimeError("BEMANICN 登录失败，请检查登录凭据是否失效。")

    await client.get(
        MAP_AUTHORIZE_URL,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        },
    )
    if not _get_cookie_value(client, "arcademap_session", domain="map.bemanicn.com"):
        raise RuntimeError("地图 OAuth 登录失败，未拿到地图站点会话。")


def _extract_inertia_page_payload(page_html: str) -> dict[str, Any]:
    match = re.search(r'data-page="([^"]+)"', page_html)
    if not match:
        raise RuntimeError("地图页面结构异常，未找到 data-page。")
    try:
        return json.loads(html.unescape(match.group(1)))
    except Exception as exc:
        raise RuntimeError("地图页面返回内容无法解析。") from exc


def _normalize_tak_map_row(payload: dict[str, Any]) -> dict[str, Any]:
    shop = payload.get("shop") or {}
    if not isinstance(shop, dict):
        shop = {}
    return {
        "shop_id": int(payload.get("shop_id") or 0),
        "tak_id": int(payload.get("tak_id") or 0),
        "address": _collapse_text(payload.get("address")),
        "store_name": _collapse_text(payload.get("store_name")),
        "temp_lnglat": _collapse_text(
            payload.get("tempLnglat") or payload.get("temp_lnglat")
        ),
        "longitude": _collapse_text(payload.get("longitude") or shop.get("longitude")),
        "latitude": _collapse_text(payload.get("latitude") or shop.get("latitude")),
        "shop": {
            "id": int(shop.get("id") or 0),
            "name": _collapse_text(shop.get("name")),
            "address": _collapse_text(shop.get("address")),
            "longitude": _collapse_text(shop.get("longitude")),
            "latitude": _collapse_text(shop.get("latitude")),
        },
    }


def _load_tak_map_snapshot_disk() -> Optional[tuple[int, tuple[dict[str, Any], ...], str]]:
    if not TAK_MAP_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(TAK_MAP_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("schema_version") != TAK_MAP_CACHE_SCHEMA_VERSION:
        return None
    fetched_at_epoch = int(payload.get("fetched_at_epoch") or 0)
    latest = _collapse_text(payload.get("latest"))
    taklist = payload.get("taklist") or []
    if not isinstance(taklist, list):
        return None
    try:
        normalized = tuple(
            _normalize_tak_map_row(item) for item in taklist if isinstance(item, dict)
        )
    except Exception:
        return None
    return fetched_at_epoch, normalized, latest


def _write_tak_map_snapshot_disk(
    taklist: tuple[dict[str, Any], ...],
    latest: str,
    *,
    fetched_at_epoch: Optional[int] = None,
) -> None:
    TAK_MAP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TAK_MAP_CACHE_SCHEMA_VERSION,
        "fetched_at_epoch": int(
            fetched_at_epoch if fetched_at_epoch is not None else time.time()
        ),
        "latest": latest,
        "taklist": list(taklist),
    }
    temp_path = TAK_MAP_CACHE_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(TAK_MAP_CACHE_PATH)


async def _fetch_tak_map_snapshot_remote(
    client: httpx.AsyncClient,
) -> tuple[int, tuple[dict[str, Any], ...], str]:
    resp = await client.get(
        "https://map.bemanicn.com/taiko",
        headers={"Accept": "text/html, application/xhtml+xml"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"全国太鼓地图请求失败，HTTP {resp.status_code}")
    payload = _extract_inertia_page_payload(resp.text)
    if payload.get("component") != "Map/TakMap":
        raise RuntimeError("全国太鼓地图返回异常，可能是登录已失效或站点结构已变更。")
    props = payload.get("props", {})
    taklist = props.get("taklist") or []
    if not isinstance(taklist, list):
        raise RuntimeError("全国太鼓地图数据结构异常。")
    normalized = tuple(
        _normalize_tak_map_row(item) for item in taklist if isinstance(item, dict)
    )
    latest = _collapse_text(props.get("latest"))
    fetched_at_epoch = int(time.time())
    _write_tak_map_snapshot_disk(
        normalized, latest, fetched_at_epoch=fetched_at_epoch
    )
    global _TAK_MAP_SNAPSHOT_CACHE
    _TAK_MAP_SNAPSHOT_CACHE = (fetched_at_epoch, normalized, latest)
    return _TAK_MAP_SNAPSHOT_CACHE


async def _get_tak_map_snapshot(
    client: httpx.AsyncClient,
) -> tuple[int, tuple[dict[str, Any], ...], str]:
    global _TAK_MAP_SNAPSHOT_CACHE
    current_epoch = int(time.time())
    if _TAK_MAP_SNAPSHOT_CACHE is not None:
        cached_epoch, taklist, latest = _TAK_MAP_SNAPSHOT_CACHE
        if _is_disk_cache_fresh(cached_epoch, now_epoch=current_epoch):
            return cached_epoch, taklist, latest
    disk_cached = _load_tak_map_snapshot_disk()
    if disk_cached is not None:
        cached_epoch, taklist, latest = disk_cached
        if _is_disk_cache_fresh(cached_epoch, now_epoch=current_epoch):
            _TAK_MAP_SNAPSHOT_CACHE = disk_cached
            return disk_cached
    return await _fetch_tak_map_snapshot_remote(client)


def _city_match_tokens(city: CityEntry) -> tuple[str, ...]:
    tokens = set(_city_alias_candidates(city.name))
    tokens.add(_normalize_city_query(city.name))
    return tuple(sorted((token for token in tokens if token), key=len, reverse=True))


def _resolve_city_from_text(text: str) -> Optional[CityEntry]:
    haystack = _normalize_city_query(text)
    if not haystack:
        return None

    best_token_length = 0
    best_matches: list[CityEntry] = []
    seen_city_codes: set[str] = set()
    for token, entry in _build_address_city_matchers():
        token_length = len(token)
        if token_length < best_token_length:
            break
        if token not in haystack:
            continue
        if token_length > best_token_length:
            best_token_length = token_length
            best_matches = []
            seen_city_codes.clear()
        if entry.city_code in seen_city_codes:
            continue
        best_matches.append(entry)
        seen_city_codes.add(entry.city_code)

    if len(best_matches) == 1:
        return best_matches[0]
    return None


def _tak_map_row_matches_city(row: dict[str, Any], city: CityEntry) -> bool:
    shop = row.get("shop") or {}
    resolved = _resolve_city_from_text(
        " ".join(
            part
            for part in (
                row.get("address"),
                row.get("store_name"),
                shop.get("name"),
                shop.get("address"),
            )
            if part
        )
    )
    if resolved is not None:
        return resolved.city_code == city.city_code
    haystack = _normalize_city_query(
        " ".join(
            part
            for part in (
                row.get("address"),
                row.get("store_name"),
                shop.get("name"),
                shop.get("address"),
            )
            if part
        )
    )
    return any(token in haystack for token in _city_match_tokens(city))


def _tak_map_row_key(row: dict[str, Any]) -> str:
    shop_id = int(row.get("shop_id") or 0)
    if shop_id > 0:
        return f"shop:{shop_id}"
    tak_id = int(row.get("tak_id") or 0)
    if tak_id > 0:
        return f"tak:{tak_id}"
    return f"{_collapse_text(row.get('store_name'))}|{_collapse_text(row.get('address'))}"


def _select_taiko_arcade_from_shop_detail(
    shop_detail: dict[str, Any],
) -> Optional[dict[str, Any]]:
    arcades = shop_detail.get("arcades") or []
    if not isinstance(arcades, list):
        return None
    for arcade in arcades:
        if not isinstance(arcade, dict):
            continue
        if int(arcade.get("title_id") or 0) != MAP_GAME_ID:
            continue
        enriched = dict(arcade)
        enriched["shop"] = {
            "id": int(shop_detail.get("id") or 0),
            "name": _collapse_text(shop_detail.get("name")),
            "province_code": _collapse_text(shop_detail.get("province_code")),
            "city_code": _collapse_text(shop_detail.get("city_code")),
        }
        return enriched
    return None


def _coords_text(row: dict[str, Any]) -> str:
    longitude, latitude = _resolve_coordinates(
        longitude=row.get("longitude"),
        latitude=row.get("latitude"),
        temp_lnglat=row.get("temp_lnglat"),
    )
    return f"{longitude}, {latitude}" if longitude and latitude else ""


def _build_base_shop_entry_from_tak_map_row(row: dict[str, Any]) -> CityShopEntry:
    shop = row.get("shop") or {}
    shop_id = int(row.get("shop_id") or 0)
    longitude, latitude = _resolve_coordinates(
        longitude=row.get("longitude") or shop.get("longitude"),
        latitude=row.get("latitude") or shop.get("latitude"),
        temp_lnglat=row.get("temp_lnglat"),
    )
    transport = ""
    if shop_id <= 0:
        if longitude and latitude:
            transport = f"坐标 {longitude}, {latitude}"
    return CityShopEntry(
        shop_id=shop_id,
        name=_collapse_text(shop.get("name")) or _collapse_text(row.get("store_name")),
        address=_collapse_text(row.get("address")) or _collapse_text(shop.get("address")),
        transport=transport,
        longitude=longitude,
        latitude=latitude,
        quantity=0,
        coin=0,
        version="",
        open_hours="",
        machine_comment="",
        shop_comment="",
    )


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


def _map_inertia_headers() -> dict[str, str]:
    return {
        "Accept": "text/html, application/xhtml+xml",
        "X-Requested-With": "XMLHttpRequest",
        "X-Inertia": "true",
    }


async def _fetch_city_page(
    client: httpx.AsyncClient,
    city_code: str,
) -> dict[str, Any]:
    resp = await client.get(
        f"https://map.bemanicn.com/games/{MAP_GAME_ID}?city={city_code}",
        headers=_map_inertia_headers(),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"地图城市页请求失败，HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError("地图城市页返回内容无法解析。") from exc
    if payload.get("component") != "Games/Show":
        raise RuntimeError("地图城市页返回异常，可能是登录已失效或站点结构已变更。")
    return payload


async def _fetch_shop_detail(
    client: httpx.AsyncClient,
    shop_id: int,
) -> dict[str, Any]:
    resp = await client.get(
        f"https://map.bemanicn.com/s/{shop_id}",
        headers=_map_inertia_headers(),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"店铺详情请求失败，HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except Exception as exc:
        raise RuntimeError("店铺详情返回内容无法解析。") from exc
    shop = payload.get("props", {}).get("shop")
    if not isinstance(shop, dict):
        raise RuntimeError("店铺详情结构异常。")
    return shop


def _format_open_hours(shop_detail: dict[str, Any]) -> str:
    start_time = shop_detail.get("start_time")
    end_time = shop_detail.get("end_time")
    if start_time is None or end_time is None:
        return ""
    try:
        start_value = int(start_time)
        end_value = int(end_time)
    except Exception:
        return ""
    return f"{start_value:02d}:00-{end_value:02d}:00"


def _build_shop_entry(
    arcade_row: dict[str, Any],
    shop_detail: Optional[dict[str, Any]],
    *,
    fallback_row: Optional[dict[str, Any]] = None,
) -> CityShopEntry:
    shop = arcade_row.get("shop") or {}
    detail = shop_detail or {}
    fallback = fallback_row or {}
    longitude, latitude = _resolve_coordinates(
        longitude=(
            detail.get("longitude")
            or arcade_row.get("longitude")
            or shop.get("longitude")
            or fallback.get("longitude")
        ),
        latitude=(
            detail.get("latitude")
            or arcade_row.get("latitude")
            or shop.get("latitude")
            or fallback.get("latitude")
        ),
        temp_lnglat=detail.get("temp_lnglat") or arcade_row.get("temp_lnglat") or fallback.get("temp_lnglat"),
    )
    quantity = int(arcade_row.get("quantity") or 0)
    coin = int(arcade_row.get("coin") or 0)
    version = _collapse_text(arcade_row.get("version"))
    machine_comment = _trim_text(arcade_row.get("comment"), 80)
    shop_comment = _trim_text(detail.get("comment"), 80)
    return CityShopEntry(
        shop_id=int(shop.get("id") or arcade_row.get("shop_id") or 0),
        name=_collapse_text(shop.get("name")),
        address=_collapse_text(detail.get("address")),
        transport=_collapse_text(detail.get("transport")),
        longitude=longitude,
        latitude=latitude,
        quantity=quantity,
        coin=coin,
        version=version,
        open_hours=_format_open_hours(detail),
        machine_comment=machine_comment,
        shop_comment=shop_comment,
    )


async def _gather_shop_details(
    client: httpx.AsyncClient,
    arcade_rows: Iterable[dict[str, Any]],
) -> tuple[CityShopEntry, ...]:
    semaphore = asyncio.Semaphore(MAX_DETAIL_CONCURRENCY)

    async def build_entry(row: dict[str, Any]) -> CityShopEntry:
        shop_id = int(row.get("shop_id") or 0)
        detail: Optional[dict[str, Any]] = None
        if shop_id > 0:
            try:
                async with semaphore:
                    detail = await _fetch_shop_detail(client, shop_id)
            except Exception:
                detail = None
        return _build_shop_entry(row, detail)

    entries = await asyncio.gather(*(build_entry(row) for row in arcade_rows))
    return tuple(entry for entry in entries if entry.shop_id > 0 and entry.name)


async def _fetch_city_page_query_result(city: CityEntry) -> CityShopQueryResult:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
        http2=True,
    ) as client:
        await _ensure_map_session(client)
        city_page = await _fetch_city_page(client, city.city_code)
        arcades = city_page.get("props", {}).get("arcades") or {}
        rows = arcades.get("data") or []
        if not isinstance(rows, list):
            rows = []

        unique_rows: list[dict[str, Any]] = []
        seen_shop_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            shop_id = int(row.get("shop_id") or 0)
            if shop_id <= 0 or shop_id in seen_shop_ids:
                continue
            seen_shop_ids.add(shop_id)
            unique_rows.append(row)

        shops = await _gather_shop_details(client, unique_rows)
        total_arcade_records = int(arcades.get("total") or len(rows))
        returned_arcade_records = len(rows)
        result = CityShopQueryResult(
            city=city,
            total_arcade_records=total_arcade_records,
            returned_arcade_records=returned_arcade_records,
            shops=shops,
            pagination_broken=total_arcade_records > returned_arcade_records,
        )
        return result


async def _fetch_remote_city_query_result(city: CityEntry) -> CityShopQueryResult:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=HTTP_TIMEOUT_SECONDS,
        http2=True,
    ) as client:
        await _ensure_map_session(client)
        _fetched_at_epoch, taklist, _latest = await _get_tak_map_snapshot(client)
        matched_rows = [row for row in taklist if _tak_map_row_matches_city(row, city)]
        if not matched_rows:
            return await _fetch_city_page_query_result(city)

        unique_rows: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in matched_rows:
            key = _tak_map_row_key(row)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_rows.append(row)

        semaphore = asyncio.Semaphore(MAX_DETAIL_CONCURRENCY)

        async def build_entry(row: dict[str, Any]) -> CityShopEntry:
            shop_id = int(row.get("shop_id") or 0)
            if shop_id > 0:
                try:
                    async with semaphore:
                        shop_detail = await _fetch_shop_detail(client, shop_id)
                    arcade_row = _select_taiko_arcade_from_shop_detail(shop_detail)
                    if arcade_row is not None:
                        return _build_shop_entry(arcade_row, shop_detail, fallback_row=row)
                except Exception:
                    pass
            return _build_base_shop_entry_from_tak_map_row(row)

        shops = tuple(
            shop
            for shop in await asyncio.gather(*(build_entry(row) for row in unique_rows))
            if shop.name
        )
        result = CityShopQueryResult(
            city=city,
            total_arcade_records=len(matched_rows),
            returned_arcade_records=len(unique_rows),
            shops=shops,
            pagination_broken=False,
        )
        if not result.shops:
            return await _fetch_city_page_query_result(city)
        return result


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

    result = await _fetch_remote_city_query_result(city)
    _CITY_QUERY_CACHE[cache_key] = (now_monotonic, result)
    _write_city_disk_cache(cache_key, result)
    return result


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
            f"该站翻页当前会跳回列表页，先展示首页能稳定拿到的 {len(result.shops)} 家店铺。"
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
            f"该站翻页当前会跳回列表页，先展示首页能稳定拿到的 {len(result.shops)} 家店铺。"
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


def _parse_float_coordinate(
    value: str,
    *,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    text = _collapse_text(value)
    if not text:
        return None
    try:
        parsed = float(text)
    except Exception:
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def collect_city_shop_locations(
    result: CityShopQueryResult,
) -> tuple[CityShopLocation, ...]:
    locations: list[CityShopLocation] = []
    for shop in result.shops:
        longitude = _parse_float_coordinate(shop.longitude, minimum=-180.0, maximum=180.0)
        latitude = _parse_float_coordinate(shop.latitude, minimum=-90.0, maximum=90.0)
        if longitude is None or latitude is None:
            continue
        locations.append(
            CityShopLocation(
                shop=shop,
                latitude=latitude,
                longitude=longitude,
            )
        )
    return tuple(locations)
