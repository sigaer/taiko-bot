#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

LABEL_PASS = "合格条件"
LABEL_GOLD = "金合格条件"
LABELS = {LABEL_PASS, LABEL_GOLD}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("\u3000", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("（裏譜面）", "").replace("(裏譜面)", "")
    text = text.replace("（裏）", "").replace("(裏)", "")
    text = re.sub(r"\s*[‐‑–—-]\s*", "-", text)
    text = text.replace("’", "'")
    return text


def display_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_text(value: str) -> str:
    return " ".join(normalize_text(value).split())


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_song_rows(block_html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(block_html, "html.parser")
    rows: List[Dict[str, Any]] = []
    for tr in soup.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        rows.append(
            {
                "order_label": display_text(tds[0].get_text(" ", strip=True)),
                "title": display_text(tds[1].get_text(" ", strip=True)),
                "difficulty": display_text(tds[2].get_text(" ", strip=True)),
                "max_combo": display_text(tds[3].get_text(" ", strip=True)),
                "bpm": display_text(tds[4].get_text(" ", strip=True)),
            }
        )
    return rows


def parse_metric_token(token: str) -> Dict[str, Any]:
    text = clean_text(token)
    compact = text.replace(" ", "")
    out: Dict[str, Any] = {}

    match = re.fullmatch(r"魂ゲージ(\d+)%?(?:以上)?", compact)
    if match:
        out["gauge_min_percent"] = int(match.group(1))
        return out

    match = re.fullmatch(r"良(\d+)(?:以上|未満)?", compact)
    if match:
        out["good_min"] = int(match.group(1))
        return out

    match = re.fullmatch(r"可(\d+)(?:以上|未満)?", compact)
    if match:
        out["ok_max"] = int(match.group(1))
        return out

    match = re.fullmatch(r"不可(\d+)(?:以上|未満)?", compact)
    if match:
        out["miss_max"] = int(match.group(1))
        return out

    match = re.fullmatch(r"たたけた数(\d+)以上", compact)
    if match:
        out["hit_count_min"] = int(match.group(1))
        return out

    match = re.fullmatch(r"連打数(\d+)打(?:以上)?", compact)
    if match:
        out["drumroll_min"] = int(match.group(1))
        return out

    if compact:
        out["raw"] = text
    return out


def merge_metric(target: Dict[str, Any], metric: Dict[str, Any]) -> None:
    for key, value in metric.items():
        if key == "raw":
            target.setdefault("raw_tokens", []).append(value)
            continue
        target[key] = value


def parse_condition_groups(block_html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(block_html, "html.parser")
    table = soup.select_one("table")
    if table is None:
        return []

    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        texts = [clean_text(td.get_text(" ", strip=True)) for td in tds]
        rowspans = [int(td.get("rowspan", 1) or 1) for td in tds]
        row = {"texts": texts, "rowspans": rowspans}
        if texts[0] in LABELS:
            current = {"label": texts[0], "rows": []}
            groups.append(current)
        if current is None:
            continue
        current["rows"].append(row)
    return groups


def row_tokens(row: Dict[str, Any]) -> List[str]:
    texts = row["texts"]
    if texts and texts[0] in LABELS:
        return texts[1:]
    return texts


def parse_condition_group(rows: List[Dict[str, Any]]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    first_row = rows[0]
    first_rowspans = first_row["rowspans"]
    first_metrics: Dict[str, Any] = {}
    for token in row_tokens(first_row):
        merge_metric(first_metrics, parse_metric_token(token))

    global_conditions: Dict[str, Any] = {}
    per_song_conditions: List[Dict[str, Any]] = []

    if len(rows) == 1:
        for key in (
            "gauge_min_percent",
            "good_min",
            "ok_max",
            "miss_max",
            "hit_count_min",
            "drumroll_min",
        ):
            if key in first_metrics:
                global_conditions[key] = first_metrics[key]
        return global_conditions, per_song_conditions

    # 列语义固定：label | gauge | performance | miss | roll
    if len(first_rowspans) >= 5:
        if first_rowspans[1] > 1 and "gauge_min_percent" in first_metrics:
            global_conditions["gauge_min_percent"] = first_metrics["gauge_min_percent"]
        if first_rowspans[2] > 1:
            if "good_min" in first_metrics:
                global_conditions["good_min"] = first_metrics["good_min"]
            if "ok_max" in first_metrics:
                global_conditions["ok_max"] = first_metrics["ok_max"]
        if first_rowspans[3] > 1 and "miss_max" in first_metrics:
            global_conditions["miss_max"] = first_metrics["miss_max"]

    if "hit_count_min" in first_metrics:
        global_conditions["hit_count_min"] = first_metrics["hit_count_min"]

    for index, row in enumerate(rows, start=1):
        row_metrics: Dict[str, Any] = {}
        for token in row_tokens(row):
            merge_metric(row_metrics, parse_metric_token(token))

        song_condition: Dict[str, Any] = {"song_index": index}
        if len(first_rowspans) >= 3 and first_rowspans[2] == 1:
            if "good_min" in row_metrics:
                song_condition["good_min"] = row_metrics["good_min"]
            if "ok_max" in row_metrics:
                song_condition["ok_max"] = row_metrics["ok_max"]
        if len(first_rowspans) >= 4 and first_rowspans[1] == 1 and "gauge_min_percent" in row_metrics:
            song_condition["gauge_min_percent"] = row_metrics["gauge_min_percent"]
        if len(first_rowspans) >= 4 and first_rowspans[3] == 1 and "miss_max" in row_metrics:
            song_condition["miss_max"] = row_metrics["miss_max"]
        if "drumroll_min" in row_metrics:
            song_condition["drumroll_min"] = row_metrics["drumroll_min"]
        per_song_conditions.append(song_condition)

    return global_conditions, per_song_conditions


def parse_formula_groups(block_html: str) -> Dict[str, Dict[str, Any]]:
    soup = BeautifulSoup(block_html, "html.parser")
    out: Dict[str, Dict[str, Any]] = {}
    current_label: Optional[str] = None

    for tr in soup.select("tbody tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if not cells:
            continue

        if cells[0] in LABELS:
            current_label = cells[0]
            text = " ".join(cells[1:])
        else:
            text = " ".join(cells)

        if current_label is None:
            continue

        bucket = out.setdefault(current_label, {})
        match = re.search(
            r"たたけた数(\d+)以上\s*(?:＝|=)\s*連打数(\d+)打以上[＋+]不可の数だけ追加の連打",
            text,
        )
        if match:
            bucket["total_hit_min"] = int(match.group(1))
            bucket["base_drumroll_min"] = int(match.group(2))

        match = re.search(r"必要な(?:黄色)?連打速度[:：]([\d.]+)打/秒", text)
        if match:
            bucket["required_drumroll_speed_dps"] = float(match.group(1))

    return out


def build_song_index(song_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for song in song_data:
        title_jp = song.get("song_name_jp")
        if not title_jp:
            continue
        normalized = normalize_text(title_jp)
        index.setdefault(normalized, song)
    return index


def build_song_entry(song: Optional[Dict[str, Any]], song_order: int) -> Dict[str, Any]:
    if song is None:
        return {
            "song_id": None,
            "song_name_jp": None,
            "song_name_cn": None,
            "match_index": song_order,
        }
    return {
        "song_id": song.get("id"),
        "song_name_jp": song.get("song_name_jp"),
        "song_name_cn": song.get("song_name") or song.get("song_name_jp"),
        "match_index": song_order,
    }


def attach_song_conditions(
    songs: List[Dict[str, Any]],
    pass_rows: List[Dict[str, Any]],
    gold_rows: List[Dict[str, Any]],
) -> None:
    pass_map = {row["song_index"]: {k: v for k, v in row.items() if k != "song_index"} for row in pass_rows}
    gold_map = {row["song_index"]: {k: v for k, v in row.items() if k != "song_index"} for row in gold_rows}
    for song in songs:
        order = int(song["order"])
        if order in pass_map or order in gold_map:
            song["conditions"] = {
                "pass": pass_map.get(order, {}),
                "gold": gold_map.get(order, {}),
            }


def build_group_payload(
    group: Optional[Dict[str, Any]],
    formula_groups: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    if not group:
        return {"raw": [], "scope": None, "global": {}}

    raw_lines: List[str] = []
    for row in group["rows"]:
        for text in row["texts"]:
            if text and text not in LABELS:
                raw_lines.append(text)

    global_conditions, per_song_rows = parse_condition_group(group["rows"])
    payload: Dict[str, Any] = {"raw": raw_lines, "global": global_conditions}

    if per_song_rows:
        payload["scope"] = "per_song"
        payload["rows"] = per_song_rows
        return payload

    if any("たたけた数" in text for text in raw_lines):
        payload["scope"] = "formula"
        formula = formula_groups.get(group["label"])
        if formula:
            payload["formula"] = {
                **formula,
                "extra_drumroll_per_miss": 1,
            }
        return payload

    if any("連打数" in text for text in raw_lines):
        payload["scope"] = "total"
        return payload

    payload["scope"] = "global"
    return payload


def extract_grade_dojo(source_path: Path, song_data_path: Path) -> Dict[str, Any]:
    source_payload = load_json(source_path)
    song_data = load_json(song_data_path)

    if not isinstance(source_payload, dict):
        raise ValueError("grade dojo source payload must be dict")
    if not isinstance(song_data, list):
        raise ValueError("song_data payload must be list")

    song_index = build_song_index(song_data)
    grades_out: List[Dict[str, Any]] = []
    missing_songs: List[Dict[str, Any]] = []
    duplicate_resolutions: List[Dict[str, Any]] = []
    duplicate_seen = set()

    for grade in source_payload.get("grades", []):
        details = next(
            (section for section in grade.get("sections", []) if section.get("title") == "詳細"),
            None,
        )
        if details is None:
            continue

        song_block_html = None
        condition_block_html = None
        formula_block_html = None
        for block in details.get("blocks", []):
            html = block.get("html", "")
            if "楽曲情報" in html and song_block_html is None:
                song_block_html = html
            elif "合格条件" in html and "条件1" in html and condition_block_html is None:
                condition_block_html = html
            elif "補足" in html and formula_block_html is None:
                formula_block_html = html

        song_rows = parse_song_rows(song_block_html or "")
        songs_out: List[Dict[str, Any]] = []
        for order, row in enumerate(song_rows, start=1):
            normalized_title = normalize_text(row["title"])
            matched_song = song_index.get(normalized_title)
            if matched_song is None:
                missing_songs.append({"grade": grade.get("slug"), "title": row["title"]})
            else:
                duplicate_ids = [
                    song.get("id")
                    for song in song_data
                    if normalize_text(song.get("song_name_jp", "")) == normalized_title
                ]
                if len(duplicate_ids) > 1:
                    dedupe_key = (grade.get("slug"), row["title"])
                    if dedupe_key not in duplicate_seen:
                        duplicate_seen.add(dedupe_key)
                        duplicate_resolutions.append(
                            {
                                "grade": grade.get("slug"),
                                "title": row["title"],
                                "resolved_id": matched_song.get("id"),
                                "candidate_ids": duplicate_ids,
                            }
                        )

            songs_out.append(
                {
                    "order": order,
                    "order_label": row["order_label"],
                    "title": row["title"],
                    "difficulty": row["difficulty"],
                    "max_combo": row["max_combo"],
                    "bpm": row["bpm"],
                    **build_song_entry(matched_song, order),
                }
            )

        condition_groups = parse_condition_groups(condition_block_html or "")
        formula_groups = parse_formula_groups(formula_block_html or "")

        pass_group = next((group for group in condition_groups if group["label"] == LABEL_PASS), None)
        gold_group = next((group for group in condition_groups if group["label"] == LABEL_GOLD), None)
        pass_payload = build_group_payload(pass_group, formula_groups)
        gold_payload = build_group_payload(gold_group, formula_groups)

        attach_song_conditions(
            songs_out,
            pass_payload.get("rows", []),
            gold_payload.get("rows", []),
        )

        grades_out.append(
            {
                "slug": grade.get("slug"),
                "title": grade.get("title"),
                "displayTitle": grade.get("displayTitle"),
                "sourceUrl": grade.get("sourceUrl"),
                "pass_conditions": pass_payload["raw"],
                "gold_conditions": gold_payload["raw"],
                "conditions": {
                    "pass": pass_payload,
                    "gold": gold_payload,
                },
                "songs": songs_out,
            }
        )

    return {
        "year": source_payload.get("year"),
        "title": source_payload.get("title"),
        "sourceBaseUrl": source_payload.get("sourceBaseUrl"),
        "matching_rule": (
            "Normalize song_name_jp, strip ura suffix, unify punctuation and hyphen spacing, "
            "then keep the first song_data match."
        ),
        "grade_count": len(grades_out),
        "song_count": sum(len(grade["songs"]) for grade in grades_out),
        "grades": grades_out,
        "missing_songs": missing_songs,
        "duplicate_resolutions": duplicate_resolutions,
    }


def parse_args() -> argparse.Namespace:
    from taiko_bot.offline.paths import root
    repo_root = root()
    parser = argparse.ArgumentParser(description="Extract structured grade dojo data")
    parser.add_argument(
        "--source",
        default=str(
            repo_root
            / "taiko-forum"
            / "taiko_frontend_back"
            / "assets"
            / "data"
            / "grade_dojo_nijiiro_2025.json"
        ),
        help="Path to raw grade dojo JSON",
    )
    parser.add_argument(
        "--song-data",
        default=str(repo_root / "songs" / "song_data.json"),
        help="Path to song_data.json",
    )
    parser.add_argument(
        "--output",
        default=str(repo_root / "output" / "grade_dojo_nijiiro_2025_extracted.json"),
        help="Path to extracted output JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = extract_grade_dojo(Path(args.source), Path(args.song_data))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path}")
    print(
        "grades="
        f"{payload['grade_count']} songs={payload['song_count']} "
        f"missing={len(payload['missing_songs'])} duplicates={len(payload['duplicate_resolutions'])}"
    )


if __name__ == "__main__":
    main()
