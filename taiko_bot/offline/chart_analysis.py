# -*- coding: utf-8 -*-

from __future__ import annotations

from sakura_taiko_core.parser.chart_analysis import (
    COURSE_NAME_MAP,
    COMBO_PATTERNS,
    Bar,
    ChartSection,
    TjaFileData,
    parse_tja_multi,
    sample_bar_by_basegrid,
    build_stream_dynamic_strict,
    extract_runs,
    count_runs_by_length,
    count_all_runs,
    count_combo_patterns,
    compute_tags,
    parse_bpm_number,
    bpm_to_index_value,
    collect_record_bpms,
    index_record_bpms,
    estimate_section_note_count,
    analyze_section,
    sanitize_filename,
    build_inverted_index_from_records,
    _ids_by_bpm_range,
    _clean_subtitle,
    normalize_course_name,
)


import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

DEFAULT_SONG_DIR = "/home/sigaer/git"
from taiko_bot.offline.paths import root
DEFAULT_OUTPUT_DIR = str(root() / "songs/analyze_result_raw")


def read_text_with_fallback(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "shift_jis", "cp932", "euc-jp"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception:
            continue
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def load_tja_file(path: str) -> TjaFileData:
    text = read_text_with_fallback(path)
    meta, sections = parse_tja_multi(text)
    return TjaFileData(path=path, meta=meta, sections=sections)


def analyze_tja_file(tja_path: str) -> List[Dict]:
    tja_data = load_tja_file(tja_path)
    results: List[Dict] = []
    for section in tja_data.sections:
        result = analyze_section(tja_data.meta, section)
        result["source_path"] = tja_path
        results.append(result)
    return results


def process_single_tja(tja_path: str, output_dir: str) -> List[str]:
    records = analyze_tja_file(tja_path)
    if not records:
        return []
    os.makedirs(output_dir, exist_ok=True)
    title = records[0].get("title") or Path(tja_path).stem
    title_safe = sanitize_filename(str(title))
    written: List[str] = []
    for record in records:
        course_safe = sanitize_filename(record.get("course") or "UnknownCourse")
        out_path = os.path.join(output_dir, f"{title_safe}_{course_safe}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        written.append(out_path)
    return written


def find_tja_files(song_dir: str) -> List[str]:
    tjas: List[str] = []
    for root, _, files in os.walk(song_dir):
        for fn in files:
            if fn.lower().endswith(".tja"):
                tjas.append(os.path.join(root, fn))
    return sorted(tjas)


def batch_analyze(song_dir: str, output_dir: str) -> List[str]:
    tja_files = find_tja_files(song_dir)
    if not tja_files:
        print(f"未在 {song_dir!r} 下找到任何 .tja 文件。")
        return []
    print(f"发现 {len(tja_files)} 个 .tja，开始处理……")
    all_outputs: List[str] = []
    for path in tja_files:
        try:
            outputs = process_single_tja(path, output_dir)
            all_outputs.extend(outputs)
            for output in outputs:
                print(f"[OK] {output}")
        except Exception as exc:
            print(f"[ERR] 处理失败：{path} -> {exc}")
    print(f"完成。共生成 {len(all_outputs)} 个 JSON。输出目录：{output_dir}")
    return all_outputs


def build_inverted_index(output_dir: str) -> Dict:
    records: List[Dict] = []
    for fn in os.listdir(output_dir):
        if not fn.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(output_dir, fn), "r", encoding="utf-8") as f:
                records.append(json.load(f))
        except Exception:
            continue

    index = build_inverted_index_from_records(records)
    with open(os.path.join(output_dir, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return index


def load_index(output_dir: str) -> Dict:
    path = os.path.join(output_dir, "_index.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return build_inverted_index(output_dir)


def fast_query(
    output_dir: str,
    bpm: Optional[int] = None,
    bpm_range: Optional[Tuple[int, int]] = None,
    level: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> List[Dict]:
    idx = load_index(output_dir)
    sets: List[Set[str]] = []

    if bpm is not None:
        sets.append(set(idx["by_bpm"].get(str(bpm), [])))

    if bpm_range is not None:
        lo, hi = bpm_range
        sets.append(_ids_by_bpm_range(idx, int(lo), int(hi)))

    if level is not None:
        sets.append(set(idx["by_level"].get(str(level), [])))

    if tags:
        for tag in tags:
            sets.append(set(idx["by_tag"].get(tag, [])))

    if not sets:
        ids = set(idx["catalog"].keys())
    else:
        sets.sort(key=len)
        ids = set(sets[0])
        for item_set in sets[1:]:
            if not ids:
                break
            ids &= item_set

    catalog = idx["catalog"]
    return [catalog[item_id] for item_id in ids]


def main() -> None:
    parser = argparse.ArgumentParser(description="批量分析 TJA 并生成倒排索引")
    parser.add_argument("--song-dir", default=DEFAULT_SONG_DIR, help="TJA 根目录")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="逐谱面 JSON 输出目录",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="仅导出逐谱面 JSON，不生成 _index.json",
    )
    args = parser.parse_args()

    batch_analyze(args.song_dir, args.output_dir)
    if not args.skip_index:
        build_inverted_index(args.output_dir)


if __name__ == "__main__":
    main()
