from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
import html

def normalize_title_display(value: str) -> str:
    return ' '.join(html.unescape(str(value or '')).split()).strip()

def _normalize_title_catalog_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = normalize_title_display(item.get('name') or '')
    if not name:
        return None
    try:
        rarity = int(item.get('rarity'))
    except Exception:
        return None
    try:
        uid = int(item.get('uid'))
    except Exception:
        uid = -1
    try:
        sort_no = int(item.get('sort_no'))
    except Exception:
        sort_no = -1
    return {'uid': uid, 'sort_no': sort_no, 'name': name, 'subtitle': str(item.get('subtitle') or '').strip(), 'subtitle_got': str(item.get('subtitle_got') or '').strip(), 'rarity': rarity, 'unlock': bool(item.get('unlock'))}

def _serialize_title_catalog(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_items: List[Dict[str, Any]] = []
    for item in items:
        normalized = _normalize_title_catalog_item(item)
        if normalized is not None:
            normalized_items.append(normalized)
    return {'titles': normalized_items}

def _deserialize_title_catalog(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    titles = payload.get('titles') or []
    if not isinstance(titles, list):
        return []
    normalized_items: List[Dict[str, Any]] = []
    for item in titles:
        normalized = _normalize_title_catalog_item(item)
        if normalized is not None:
            normalized_items.append(normalized)
    return normalized_items

def build_title_rarity_lookup(items: Iterable[Dict[str, Any]]) -> Dict[str, Tuple[int, ...]]:
    by_title: Dict[str, set[int]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        title_name = normalize_title_display(item.get('name') or '')
        if not title_name:
            continue
        try:
            rarity = int(item.get('rarity'))
        except Exception:
            continue
        by_title.setdefault(title_name, set()).add(rarity)
    return {title_name: tuple(sorted(rarities)) for title_name, rarities in by_title.items() if rarities}
