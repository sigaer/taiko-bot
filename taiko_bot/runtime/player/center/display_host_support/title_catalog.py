from __future__ import annotations


from sakura_taiko_core.parser.title_catalog import normalize_title_display, _serialize_title_catalog, _deserialize_title_catalog, build_title_rarity_lookup

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, Iterable, List, Tuple

import requests

ROOT_DIR = __import__("taiko_bot.runtime.public.config",fromlist=["root"]).root()

TITLE_API_CONFIG_PATH = ROOT_DIR / "config.json"

TITLE_API_CACHE_PATH = ROOT_DIR / "data" / "title_catalog_cache.json"

TITLE_API_URL = "https://wl-taiko.wahlap.net/api/user/all/title"

TITLE_API_PAGE_SIZE = 1000

def normalize_title_authorization(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"

def fetch_title_catalog_items(
    *,
    config_path: Path = TITLE_API_CONFIG_PATH,
) -> List[Dict[str, Any]]:
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    authorization = normalize_title_authorization((config or {}).get("cookie") or "")
    if not authorization:
        return []

    try:
        response = requests.post(
            TITLE_API_URL,
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
            },
            json={"page": 1, "pageSize": TITLE_API_PAGE_SIZE, "unlock": 0},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return _deserialize_title_catalog({"titles": items})

def write_title_catalog_cache(
    items: Iterable[Dict[str, Any]],
    *,
    cache_path: Path = TITLE_API_CACHE_PATH,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(_serialize_title_catalog(items), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def refresh_title_catalog_cache(
    *,
    config_path: Path = TITLE_API_CONFIG_PATH,
    cache_path: Path = TITLE_API_CACHE_PATH,
) -> List[Dict[str, Any]]:
    items = fetch_title_catalog_items(config_path=config_path)
    if items:
        write_title_catalog_cache(items, cache_path=cache_path)
        load_title_catalog_items.cache_clear()
    return items

def load_title_catalog_cache(
    *,
    cache_path: Path = TITLE_API_CACHE_PATH,
) -> List[Dict[str, Any]]:
    if not cache_path.exists():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    return _deserialize_title_catalog(payload)

@lru_cache(maxsize=1)
def load_title_catalog_items() -> Tuple[Dict[str, Any], ...]:
    cached_items = load_title_catalog_cache()
    if cached_items:
        return tuple(cached_items)
    live_items = refresh_title_catalog_cache()
    return tuple(live_items)
