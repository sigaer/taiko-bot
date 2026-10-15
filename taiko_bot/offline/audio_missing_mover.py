from taiko_bot.offline.paths import root as _runtime_root
from datetime import datetime
from pathlib import Path
import re
import shutil

import ujson as json

AUDIO_MISSING_REPORT_PATH = Path(str(_runtime_root() / 'logs/audio_missing_report.json'))
AUDIO_MISSING_TITLE_LIST_PATH = Path(str(_runtime_root() / 'logs/audio_missing_titles.json'))
AUDIO_MOVE_REPORT_PATH = Path(str(_runtime_root() / 'logs/audio_move_report.json'))
ASSETS_SOURCE_DIR = Path(str(_runtime_root() / 'assets/source'))
ASSETS_INPUT_DIR = Path(str(_runtime_root() / 'assets/input'))


def _load_missing_title_id_map(report_path: Path):
    report = json.load(open(report_path, "r", encoding="utf-8"))
    missing = report.get("missing", [])

    title_to_ids = {}
    for item in missing:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        try:
            sid = int(item.get("id"))
        except Exception:
            continue
        title_to_ids.setdefault(title, set()).add(sid)

    title_to_id = {}
    multi_id_titles = {}
    for title, ids in title_to_ids.items():
        if len(ids) == 1:
            title_to_id[title] = next(iter(ids))
        else:
            chosen = min(ids)
            title_to_id[title] = chosen
            multi_id_titles[title] = sorted(ids)

    return title_to_id, multi_id_titles


def build_missing_title_list_from_report(
    report_path: Path = AUDIO_MISSING_REPORT_PATH,
    output_path: Path = AUDIO_MISSING_TITLE_LIST_PATH,
):
    if not report_path.exists():
        raise FileNotFoundError(f"缺失报告不存在: {report_path}")

    title_to_id, multi_id_titles = _load_missing_title_id_map(report_path)
    titles = sorted(title_to_id.keys())
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "title_count": len(titles),
        "titles": titles,
        "title_id_map": title_to_id,
        "multi_id_titles": multi_id_titles,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[AUDIO][TITLE] 已生成缺失歌曲名称名单: {output_path}, count={len(titles)}")
    return titles


def _read_text_with_fallback(path: Path):
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis", "gbk"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_titleja(path: Path):
    content = _read_text_with_fallback(path)
    for line in content.splitlines():
        m = re.match(r"^\s*TITLEJA\s*:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _move_file_to_input(src_path: Path, input_dir: Path, target_name: str):
    input_dir.mkdir(parents=True, exist_ok=True)
    dst_path = input_dir / target_name
    if dst_path.exists():
        stem = dst_path.stem
        suffix = dst_path.suffix
        idx = 1
        while True:
            candidate = input_dir / f"{stem}_{idx}{suffix}"
            if not candidate.exists():
                dst_path = candidate
                break
            idx += 1
    shutil.move(str(src_path), str(dst_path))
    return dst_path


def move_missing_titles_tja_and_ogg(
    source_dir: Path = ASSETS_SOURCE_DIR,
    input_dir: Path = ASSETS_INPUT_DIR,
    report_path: Path = AUDIO_MISSING_REPORT_PATH,
    title_output_path: Path = AUDIO_MISSING_TITLE_LIST_PATH,
    move_report_path: Path = AUDIO_MOVE_REPORT_PATH,
):
    build_missing_title_list_from_report(
        report_path=report_path,
        output_path=title_output_path,
    )
    title_to_id, multi_id_titles = _load_missing_title_id_map(report_path)
    missing_titles = set(title_to_id.keys())
    if not source_dir.exists():
        raise FileNotFoundError(f"源目录不存在: {source_dir}")

    tja_files = list(source_dir.rglob("*.tja"))
    matched_items = []
    moved_tja = 0
    moved_ogg = 0
    missing_ogg = 0

    for tja_path in tja_files:
        titleja = _extract_titleja(tja_path)
        if not titleja or titleja not in missing_titles:
            continue

        song_id = title_to_id.get(titleja)
        if song_id is None:
            continue

        moved_tja_path = _move_file_to_input(tja_path, input_dir, f"{song_id}.png")
        moved_tja += 1
        ogg_candidates = [tja_path.with_suffix(".ogg"), tja_path.with_suffix(".OGG")]
        moved_ogg_path = None
        for ogg_path in ogg_candidates:
            if ogg_path.exists():
                moved_ogg_path = _move_file_to_input(ogg_path, input_dir, f"{song_id}.ogg")
                moved_ogg += 1
                break
        if moved_ogg_path is None:
            missing_ogg += 1

        matched_items.append(
            {
                "id": song_id,
                "titleja": titleja,
                "tja": str(moved_tja_path),
                "ogg": str(moved_ogg_path) if moved_ogg_path else None,
            }
        )
        print(
            "[AUDIO][MOVE] "
            f"title={titleja} tja={moved_tja_path} ogg={moved_ogg_path}"
        )

    move_report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_dir": str(source_dir),
        "input_dir": str(input_dir),
        "scanned_tja_count": len(tja_files),
        "matched_title_count": len(matched_items),
        "moved_tja_count": moved_tja,
        "moved_ogg_count": moved_ogg,
        "missing_ogg_count": missing_ogg,
        "multi_id_titles": multi_id_titles,
        "items": matched_items,
    }
    move_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(move_report_path, "w", encoding="utf-8") as f:
        json.dump(move_report, f, ensure_ascii=False, indent=2)

    print(
        "[AUDIO][MOVE] 完成: "
        f"scanned_tja={len(tja_files)}, matched={len(matched_items)}, "
        f"moved_tja={moved_tja}, moved_ogg={moved_ogg}, missing_ogg={missing_ogg}"
    )
    print(f"[AUDIO][MOVE] 报告已写入: {move_report_path}")
    return move_report
