#!/usr/bin/env python3
from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

try:
    from .grade_dojo_extract import normalize_text, parse_metric_token
except ImportError:
    from grade_dojo_extract import normalize_text, parse_metric_token


BASE = Path(str(_runtime_root()))
OUTPUT_PATH = BASE / "songs" / "grade_dojo_nijiiro_history_simple.json"
CACHE_DIR = BASE / "output" / "grade_dojo_page_cache"
CURRENT_SONG_DATA_PATH = BASE / "songs" / "song_data.json"
SONG_DATA_PATHS = [
    BASE / "songs" / "song_data_raw.json",
    BASE / "songs" / "song_data_back.json",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

YEARS = ["2020", "2021", "2022", "2023", "2024"]
YEAR_REGIONS = {
    "2020": "default",
    "2021": "default",
    "2022": "default",
    "2023": "cn",
    "2024": "default",
}
SLUGS = [
    "五級",
    "四級",
    "三級",
    "二級",
    "一級",
    "初段",
    "二段",
    "三段",
    "四段",
    "五段",
    "六段",
    "七段",
    "八段",
    "九段",
    "十段",
    "玄人",
    "名人",
    "超人",
    "達人",
]

LABEL_PASS = "合格条件"
LABEL_GOLD = "金合格条件"
LABELS = {LABEL_PASS, LABEL_GOLD}

REGION_COMMON = "common"
REGION_CN = "cn"
REGION_JP = "jp"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", ""))
    except Exception:
        return default


def fetch_html(url: str, *, retries: int = 4, sleep_seconds: float = 1.0) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_name = quote(url, safe="").replace("%", "_") + ".html"
    cache_path = CACHE_DIR / cache_name
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            text = response.text
            cache_path.write_text(text, encoding="utf-8")
            return text
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(max(sleep_seconds * attempt, 10.0 if "429" in str(exc) else 0.0))
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def _is_available_song(song: Dict[str, Any]) -> bool:
    return safe_int(song.get("shelf_status"), 0) == 0


def build_song_index(paths: List[Path], *, available_only: bool = False) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    seen_keys: set[Tuple[int, str]] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for song in payload:
            if not isinstance(song, dict):
                continue
            song_id = safe_int(song.get("id"), -1)
            title_jp = clean_text(song.get("song_name_jp") or "")
            if song_id <= 0 or not title_jp:
                continue
            if available_only and not _is_available_song(song):
                continue
            dedupe_key = (song_id, title_jp)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            for norm in normalized_title_candidates(title_jp):
                index.setdefault(norm, song)
    return index


def expand_table_rows(section: Any) -> List[List[str]]:
    rows: List[List[str]] = []
    carried: Dict[int, Dict[str, Any]] = {}
    table_rows = section.select("tr") if hasattr(section, "select") else []
    for tr in table_rows:
        row: List[str] = []
        col_idx = 0

        def fill_carried() -> None:
            nonlocal col_idx
            while col_idx in carried:
                slot = carried[col_idx]
                row.append(slot["text"])
                slot["remain"] -= 1
                if slot["remain"] <= 0:
                    carried.pop(col_idx, None)
                col_idx += 1

        fill_carried()
        for cell in tr.find_all(["td", "th"], recursive=False):
            fill_carried()
            text = clean_text(cell.get_text(" ", strip=True))
            rowspan = safe_int(cell.get("rowspan"), 1)
            colspan = safe_int(cell.get("colspan"), 1)
            for _ in range(max(1, colspan)):
                row.append(text)
                if rowspan > 1:
                    carried[col_idx] = {"text": text, "remain": rowspan - 1}
                col_idx += 1
            fill_carried()
        fill_carried()
        if row:
            rows.append(row)

    if not rows:
        return rows

    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def classify_region(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return REGION_COMMON
    if "中国版" in cleaned:
        return REGION_CN
    if "共通" in cleaned:
        return REGION_COMMON
    if "日本版" in cleaned or "アジア版" in cleaned:
        return REGION_JP
    return REGION_COMMON


def has_region_marker(text: str) -> bool:
    cleaned = clean_text(text)
    return any(marker in cleaned for marker in ("中国版", "共通", "日本版", "アジア版"))


def normalized_title_candidates(title: str) -> List[str]:
    cleaned_title = re.sub(r"\s*\*\d+\s*$", "", str(title or ""))
    base = clean_text(normalize_text(cleaned_title))
    candidates = {
        base,
        base.replace(" ： ", "："),
        base.replace("：", ":"),
        base.replace(" : ", ":"),
        base.replace(": ", ":").replace(" :", ":"),
        base.replace(" × ", "×"),
        base.replace(" x ", "×"),
    }
    expanded = set(candidates)
    for item in list(candidates):
        expanded.add(item.replace(" ： ", ":"))
        expanded.add(item.replace("：", " : "))
        expanded.add(item.replace("・", "･"))
        expanded.add(item.replace("･", "・"))
    return [clean_text(item) for item in expanded if clean_text(item)]


def select_rows_for_region(rows: List[List[str]], region: str) -> List[List[str]]:
    if not rows:
        return rows

    selected: List[List[str]] = []
    for row in rows:
        kind = classify_region(row[-1] if row else "")
        if region == REGION_CN:
            if kind in {REGION_COMMON, REGION_CN}:
                selected.append(row)
        else:
            if kind in {REGION_COMMON, REGION_JP}:
                selected.append(row)
    return selected or rows


def difficulty_to_level(title: str, difficulty_text: str) -> str:
    raw_title = str(title or "")
    raw_diff = str(difficulty_text or "")
    if "かんたん" in raw_diff:
        return "level1"
    if "ふつう" in raw_diff:
        return "level2"
    if "むずかしい" in raw_diff:
        return "level3"
    if "おに" in raw_diff:
        if any(token in raw_title for token in ("(裏", "（裏", "裏譜面")):
            return "level5"
        return "level4"
    return "level4"


def parse_song_table_rows(table: Any, region: str) -> List[Dict[str, Any]]:
    body_rows = expand_table_rows(table.find("tbody") or table)
    grouped: Dict[int, List[List[str]]] = defaultdict(list)
    for row in body_rows:
        if len(row) < 4:
            continue
        order_match = re.search(r"(\d+)曲目", row[0])
        if not order_match:
            continue
        grouped[int(order_match.group(1))].append(row)

    chosen_rows: List[List[str]] = []
    for order in sorted(grouped):
        rows = grouped[order]
        preferred = None
        for row in rows:
            kind = classify_region(row[-1] if row else "")
            if region == REGION_CN and kind == REGION_CN:
                preferred = row
                break
            if region != REGION_CN and kind == REGION_JP:
                preferred = row
                break
        if preferred is None:
            preferred = rows[0]
        chosen_rows.append(preferred)

    songs: List[Dict[str, Any]] = []
    for order, row in enumerate(chosen_rows, start=1):
        songs.append(
            {
                "order": order,
                "title": clean_text(row[1]),
                "difficulty": clean_text(row[2]),
                "noteCount": safe_int(re.sub(r"[^\d]", "", row[3]), 0),
            }
        )
    return songs


def parse_condition_rows(table: Any, region: str) -> Dict[str, List[Dict[str, Any]]]:
    body_rows = expand_table_rows(table.find("tbody") or table)
    selected_rows = select_rows_for_region(body_rows, region)
    groups: Dict[str, List[Dict[str, Any]]] = {LABEL_PASS: [], LABEL_GOLD: []}

    for row in selected_rows:
        if len(row) < 2:
            continue
        label = clean_text(row[0])
        if label not in LABELS:
            continue
        tokens = [clean_text(cell) for cell in row[1:]]
        if tokens and has_region_marker(tokens[-1]):
            tokens = tokens[:-1]
        metrics: Dict[str, Any] = {}
        for token in tokens:
            if not token:
                continue
            parsed = parse_metric_token(token)
            metrics.update(
                {
                    key: value
                    for key, value in parsed.items()
                    if key in {
                        "gauge_min_percent",
                        "good_min",
                        "ok_max",
                        "miss_max",
                        "hit_count_min",
                        "drumroll_min",
                    }
                }
            )
        if metrics:
            groups[label].append(metrics)
    return groups


def compress_metric(rows: List[Dict[str, Any]], key: str) -> Any:
    values = [row[key] for row in rows if key in row]
    if not values:
        return None
    if all(value == values[0] for value in values):
        return values[0]
    return values


def build_condition_payload(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    mapping = {
        "gauge_min_percent": "soulGaugePercent",
        "good_min": "goodCountAtLeast",
        "ok_max": "okCountLessThan",
        "miss_max": "badCountLessThan",
        "hit_count_min": "hitCountAtLeast",
        "drumroll_min": "drumrollCountAtLeast",
    }
    for source_key, target_key in mapping.items():
        value = compress_metric(rows, source_key)
        if value is not None:
            out[target_key] = value
    return out


def extract_grade_title(soup: BeautifulSoup) -> str:
    title_text = clean_text(
        (soup.select_one("#title .title") or soup.select_one("h1") or soup.title).get_text(
            " ", strip=True
        )
    )
    for slug in SLUGS:
        if title_text.endswith(slug):
            return slug
    return title_text.split()[-1]


def find_detail_tables(soup: BeautifulSoup) -> Dict[str, Any]:
    content = soup.select_one("#content")
    if content is None:
        raise RuntimeError("missing #content")

    detail_heading = next(
        (
            child
            for child in content.find_all(recursive=False)
            if child.name == "h3" and clean_text(child.get_text(" ", strip=True)) == "詳細"
        ),
        None,
    )
    if detail_heading is None:
        raise RuntimeError("missing 詳細 section")

    tables: Dict[str, Any] = {}
    for sibling in detail_heading.find_next_siblings():
        if sibling.name == "h3":
            break
        if not hasattr(sibling, "find_all"):
            continue
        for table in sibling.find_all("table"):
            table_text = clean_text(table.get_text(" ", strip=True))
            if (
                "songs" not in tables
                and "曲名" in table_text
                and ("最大コンボ数" in table_text or "最大 コンボ数" in table_text)
            ):
                tables["songs"] = table
                continue
            if (
                "conditions" not in tables
                and "条件1" in table_text
                and ("合格条件" in table_text or "金合格条件" in table_text)
            ):
                tables["conditions"] = table
                continue
    return tables


def match_song(song_index: Dict[str, Dict[str, Any]], title: str) -> Optional[Dict[str, Any]]:
    for normalized in normalized_title_candidates(title):
        matched = song_index.get(normalized)
        if matched is not None:
            return matched
    return None


def build_song_entry(
    available_song_index: Dict[str, Dict[str, Any]],
    reference_song_index: Dict[str, Dict[str, Any]],
    row: Dict[str, Any],
) -> Dict[str, Any]:
    matched_song = match_song(available_song_index, row["title"])
    reference_song = matched_song or match_song(reference_song_index, row["title"])
    entry = {
        "title": row["title"],
        "difficulty": difficulty_to_level(row["title"], row["difficulty"]),
        "noteCount": safe_int(row["noteCount"], 0),
    }
    if matched_song is not None:
        entry["id"] = safe_int(matched_song.get("id"), -1)
    else:
        entry["id"] = -1
    if reference_song is not None and matched_song is None:
        entry["unavailable"] = True
    return entry


def accuracy_formula_for_conditions(pass_cond: Dict[str, Any]) -> str:
    if pass_cond.get("goodCountAtLeast") is not None:
        return "good_over_total"
    return "total_minus_ok_minus_1_over_total"


def parse_grade_page(
    available_song_index: Dict[str, Dict[str, Any]],
    reference_song_index: Dict[str, Dict[str, Any]],
    year: str,
    slug: str,
    region: str,
) -> Dict[str, Any]:
    url = "https://wikiwiki.jp/taiko-fumen/" + quote(f"段位道場/ニジイロ{year}/{slug}", safe="/")
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    tables = find_detail_tables(soup)

    song_rows = parse_song_table_rows(tables["songs"], region)
    condition_rows = parse_condition_rows(tables["conditions"], region)
    pass_cond = build_condition_payload(condition_rows[LABEL_PASS])
    gold_cond = build_condition_payload(condition_rows[LABEL_GOLD])
    formula = accuracy_formula_for_conditions(pass_cond)

    songs = []
    for row in song_rows:
        entry = build_song_entry(available_song_index, reference_song_index, row)
        entry["accuracyFormula"] = formula
        songs.append(entry)

    return {
        "grade": extract_grade_title(soup),
        "songs": songs,
        "conditions": {
            "pass": pass_cond,
            "gold": gold_cond,
        },
        "sourceUrl": url,
    }


def build_payload() -> Dict[str, Any]:
    available_song_index = build_song_index([CURRENT_SONG_DATA_PATH], available_only=True)
    reference_song_index = build_song_index([CURRENT_SONG_DATA_PATH, *SONG_DATA_PATHS])
    existing_payload: Dict[str, Any] = {}
    if OUTPUT_PATH.exists():
        try:
            existing_payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing_payload = {}

    versions: Dict[str, Dict[str, Any]] = dict(existing_payload.get("versions") or {})
    missing_songs: List[Dict[str, Any]] = [
        item for item in (existing_payload.get("missingSongs") or []) if isinstance(item, dict)
    ]
    selected_years_raw = os.environ.get("NIJIIRO_HISTORY_YEARS", "")
    selected_years = [item.strip() for item in selected_years_raw.split(",") if item.strip()]
    years = selected_years or YEARS

    for year in years:
        region = YEAR_REGIONS[year]
        grades = [parse_grade_page(available_song_index, reference_song_index, year, slug, region) for slug in SLUGS]
        missing_songs = [item for item in missing_songs if item.get("year") != year]
        for grade in grades:
            for song in grade["songs"]:
                if safe_int(song.get("id"), -1) <= 0:
                    missing_songs.append(
                        {
                            "year": year,
                            "grade": grade["grade"],
                            "title": song["title"],
                            "difficulty": song["difficulty"],
                        }
                    )
        versions[year] = {
            "year": year,
            "region": region,
            "grades": grades,
        }
        time.sleep(2.0)

    return {
        "versions": {year: versions[year] for year in sorted(versions)},
        "missingSongs": missing_songs,
    }


def main() -> None:
    payload = build_payload()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH}")
    print(f"missing={len(payload['missingSongs'])}")


if __name__ == "__main__":
    main()
