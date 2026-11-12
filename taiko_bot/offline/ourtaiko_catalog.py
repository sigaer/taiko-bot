"""Merge the complete OurTaiko catalog into the shared song catalog.

Wahlap owns mainland availability; Nijiiro IDs own arcade identity.  Other
platform IDs are allocated once in the existing 100000+ namespace.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import json
import logging
from pathlib import Path
import unicodedata

import requests

from .song_tja_mapping import write_song_tja_mapping

API_URL = "https://database.ourtaiko.org/api/v1/charts"
FULL_API_URL = "https://database.ourtaiko.org/api/v1/game/catalog"
logger = logging.getLogger(__name__)
OTHER_ID_START = 100000
COURSES = {"easy": 1, "normal": 2, "hard": 3, "oni": 4, "edit": 5, "ura": 5}
CATEGORIES = {
    "pop": "流行音乐", "anime": "动漫音乐", "vocaloid": "博歌乐音乐",
    "children": "儿童音乐", "kids": "儿童音乐", "folk": "儿童音乐",
    "variety": "综合音乐", "classical": "古典音乐", "classics": "古典音乐", "game": "游戏音乐",
    "namco": "南梦宫原创音乐",
}


def atomic_json(path: Path, payload) -> None:
    # Use the same atomic/fsync writer as other catalog publication jobs.
    from .merge_index import _write_json_atomic
    _write_json_atomic(path, payload)


def fetch_paginated_charts(url=API_URL, *, workers=4, max_pages=250, filters=None, allow_empty=False):
    def page(number):
        for attempt in range(3):
            try:
                response = requests.get(url, params={**(filters or {}), "page": number}, timeout=30)
                response.raise_for_status()
                payload = response.json()
                if payload.get("page") != number or not isinstance(payload.get("items"), list):
                    raise ValueError("Invalid OurTaiko page")
                return payload
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise

    first = page(1)
    total, size = int(first["total"]), int(first["pageSize"])
    if total < 0 or (not allow_empty and total == 0) or size < 1:
        raise ValueError("Empty OurTaiko catalog")
    count = (total + size - 1) // size
    if count > max_pages:
        raise ValueError("OurTaiko pagination limit exceeded")
    items = list(first["items"])
    with ThreadPoolExecutor(max_workers=min(4, max(1, workers))) as pool:
        for payload in pool.map(page, range(2, count + 1)):
            if payload["total"] != total or payload["pageSize"] != size:
                raise ValueError("OurTaiko catalog changed during pagination; retry")
            items.extend(payload["items"])
    if len(items) != total or len({item["id"] for item in items}) != total:
        raise ValueError("Incomplete or duplicate OurTaiko pagination; previous snapshot retained")
    return items


def fetch_charts(url=API_URL, *, workers=4, max_pages=250):
    """Use one full snapshot plus registered songs without files.

    The game's endpoint excludes fileless and uncategorized songs. Check its
    union against the unfiltered count and fall back to complete pagination
    when it cannot cover that snapshot. Never publish a partial response.
    """
    if url != API_URL:
        return fetch_paginated_charts(url, workers=workers, max_pages=max_pages)
    try:
        response = requests.get(FULL_API_URL, timeout=45)
        response.raise_for_status()
        payload = response.json()
        charts = payload.get("charts")
        if not isinstance(charts, list) or not charts or payload.get("chartCount") != len(charts):
            raise ValueError("Invalid OurTaiko full catalog")
        fileless = fetch_paginated_charts(filters={"files": "no"}, allow_empty=True,
                                         workers=workers, max_pages=max_pages)
        response = requests.get(url, params={"page": 1}, timeout=30)
        response.raise_for_status()
        total = response.json()["total"]
        combined = [*charts, *fileless]
        if len(combined) != total or len({row["id"] for row in combined}) != total:
            raise ValueError("OurTaiko full catalog coverage mismatch")
        return combined
    except (requests.RequestException, ValueError, TypeError, KeyError):
        logger.warning("OurTaiko 全量接口未完整覆盖，改用分页全量读取", exc_info=True)
        return fetch_paginated_charts(url, workers=workers, max_pages=max_pages)


def positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number > 0 and float(value) == number else None
    except (ValueError, TypeError):
        return None


def title_key(value):
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def chart_levels(chart):
    result = {}
    for difficulty in chart.get("difficulties") or []:
        # P1/P2 have independent note counts. Never advertise them as singles.
        if difficulty.get("side", "single").lower() != "single":
            continue
        index = COURSES.get(str(difficulty.get("course", "")).lower())
        level = positive_id(difficulty.get("level"))
        if index and level:
            result[index] = level
    return result


def chart_titles(chart):
    return {title_key(value) for value in [chart.get("title"), *(chart.get("titleTranslations") or {}).values()] if value}


def new_song(chart, sid, status):
    translations = chart.get("titleTranslations") or {}
    title = chart.get("title") or ""
    return {
        "id": sid, "sort": sid, "song_name": translations.get("zh") or translations.get("ja") or title,
        "song_name_jp": translations.get("ja") or title,
        "subtitle": (chart.get("subtitleTranslations") or {}).get("zh") or chart.get("subtitle") or "",
        "type": next((CATEGORIES[c] for c in chart.get("categoryIds", []) if c in CATEGORIES), ""),
        "bpm": str(chart.get("bpm") or ""), "shelf_status": status,
        "catalog_source": "ourtaiko",
        "open_day": "", "tag": "", "version": [], "artists": [], "isPlayed": False,
        **{f"level_{i}": "-" for i in range(1, 6)},
        "max_combo": ["-"] * 5,
    }


def merge_catalog(songs, charts, *, mainland_ids=None):
    merged = [dict(song) for song in songs]
    by_id = {int(song["id"]): song for song in merged}
    if len(by_id) != len(merged):
        raise ValueError("Duplicate local song IDs")
    by_source = {source: song for song in merged for source in song.get("ourtaiko_ids", [])}
    other_titles = defaultdict(list)
    for song in merged:
        if int(song["id"]) >= OTHER_ID_START:
            for title in {title_key(song.get("song_name")), title_key(song.get("song_name_jp"))} - {""}:
                other_titles[title].append(song)
    next_id = max([OTHER_ID_START - 1, *(sid for sid in by_id if sid >= OTHER_ID_START)])
    report = {"upstreamCharts": len(charts), "added": 0, "matched": 0, "issues": []}
    assignments = {}
    for chart in sorted(charts, key=lambda row: (int(row.get("numberId") or 0), row["id"])):
        rainbow = positive_id(chart.get("nijiiroId"))
        if rainbow is not None and rainbow >= OTHER_ID_START:
            report["issues"].append({"source": chart["id"], "reason": "invalid_nijiiro_id"})
            continue
        song = by_id.get(rainbow) if rainbow else by_source.get(chart["id"])
        if rainbow is None and song is not None and int(song["id"]) < OTHER_ID_START:
            song = None
        if song is None and rainbow is None:
            levels = chart_levels(chart)
            candidates = {int(s["id"]): s for title in chart_titles(chart) for s in other_titles.get(title, [])
                          if levels and all(s.get(f"level_{i}") in (None, "", "-", level) for i, level in levels.items())}
            if len(candidates) == 1:
                song = next(iter(candidates.values()))
        is_new = song is None
        if is_new:
            if rainbow:
                sid = rainbow
            else:
                next_id += 1
                sid = next_id
            song = new_song(chart, sid, 1 if rainbow else 2)
            by_id[sid] = song
            merged.append(song)
            report["added"] += 1
        else:
            report["matched"] += 1
        sid = int(song["id"])
        # Preserve maintained values; populate fields absent from older schemas.
        for key, value in new_song(chart, sid, 1 if rainbow else 2).items():
            if key not in {"id", "sort", "shelf_status", "catalog_source"} and song.get(key) in (None, "", "-", []):
                song[key] = value
        assignments[chart["id"]] = sid
        by_source[chart["id"]] = song
        song["ourtaiko_ids"] = sorted(set(song.get("ourtaiko_ids", [])) | {chart["id"]})
        official = str(chart.get("officialId") or "").strip()
        if official:
            if song.get("official_id") and song["official_id"] != official:
                report["issues"].append({"source": chart["id"], "reason": "official_id_conflict", "id": sid})
            else:
                song["official_id"] = official
        else:
            song.setdefault("official_id", "")
        if is_new and rainbow and mainland_ids is not None:
            song["shelf_status"] = 0 if rainbow in mainland_ids else 1
        elif is_new and rainbow is None:
            song["shelf_status"] = 2
        # A known mainland chart's difficulty availability is owned by Wahlap.
        if is_new:
            for index, level in chart_levels(chart).items():
                if song.get(f"level_{index}") in (None, "", "-", 0):
                    song[f"level_{index}"] = level
    report["songs"] = len(merged)
    return merged, assignments, report


def refresh_catalog(songs, *, root: Path, fetch=True, persist=True):
    cache = root / "songs/ourtaiko_charts.json"
    if fetch:
        try:
            charts = fetch_charts()
            atomic_json(cache, charts)
        except Exception:
            logger.warning("OurTaiko 刷新失败，保留最近完整快照", exc_info=True)
            if not cache.is_file():
                raise
            charts = json.loads(cache.read_text(encoding="utf-8"))
    else:
        charts = json.loads(cache.read_text(encoding="utf-8"))
    # Current song_data statuses reflect the latest successful Wahlap update.
    mainland_ids = {int(s["id"]) for s in songs if s.get("shelf_status", 0) == 0 and int(s["id"]) < OTHER_ID_START}
    merged, assignments, report = merge_catalog(songs, charts, mainland_ids=mainland_ids)
    from .catalog_resources import enrich_resources
    mapping_path = root / "songs/song_id2tjapath.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.is_file() else {}
    report["resources"] = enrich_resources(merged, charts, assignments, Path("/home/sigaer/git/ESE_autosync"), mapping)
    from .catalog_reconcile import reconcile_catalog, load_legacy_provenance
    merged, report["reconciliation"] = reconcile_catalog(
        merged, charts, assignments, mapping=mapping,
        provenance=load_legacy_provenance(root), mainland_ids=mainland_ids,
    )
    active_ids = {int(song["id"]) for song in merged}
    mapping = {int(k): v for k, v in mapping.items() if int(k) in active_ids}
    report["songs"] = len(merged)
    from .catalog_references import migrate_references
    report["references"] = migrate_references(root, merged, persist=persist)
    if persist:
        write_song_tja_mapping(mapping_path, {int(k): v for k, v in mapping.items()})
    atomic_json(root / "logs/ourtaiko_catalog_report.json", report)
    return merged
