#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    from rapidfuzz import fuzz
except Exception as e:
    raise SystemExit(
        "缺少依赖 rapidfuzz。请先安装：\n"
        "  pip install -U rapidfuzz\n"
        f"原始错误: {e}"
    )

# 你的目录结构：assets/fumens/{Oni,Muzukashii,Futsuu,Kantan}/*.png
DIFFICULTIES = ["Oni", "Muzukashii", "Futsuu", "Kantan"]

# 需要去掉的“前缀标签”，以【...】形式出现，可能多个叠加：【双打】【限定】xxx
LEADING_TAG_RE = re.compile(r"^(?:【[^】]+】)+")
# 常见“裏谱面/裏譜面/裏”后缀，可能在()或（）里
URA_SUFFIX_RE = re.compile(
    r"[（(]\s*(?:裏譜面|裏谱面|裏|里谱面|里譜面)\s*[)）]\s*$", re.IGNORECASE
)
# 判定“里谱面/裏譜面”的提示（用于分流到 InnerOni）
INNER_HINT_RE = re.compile(r"(?:裏譜面|裏谱面|里譜面|里谱面|裏|里)", re.IGNORECASE)
# 更稳健：只在括号中出现时认为是里谱面（避免曲名本身包含“里/裏”字导致误判）
INNER_HINT_PAREN_RE = re.compile(
    r"[（(]\s*(?:裏譜面|裏谱面|里譜面|里谱面|裏|里)\s*[)）]\s*$", re.IGNORECASE
)

# 你可以按需扩展：一些文件名里可能还有额外括号说明，谨慎起见默认不全删，只删“裏谱面”相关
# 若你确实想把所有末尾括号都删掉，可启用下行（会增加误匹配风险）：
# TRAILING_PAREN_RE = re.compile(r"[（(].*?[)）]\s*$")


def normalize_name(s: str) -> str:
    """
    将曲名/文件名统一为更可匹配的形式：
    - 去掉开头【...】标签（含多个）
    - 去掉末尾(裏譜面)/(裏谱面)/(裏) 等
    - 统一全角括号到半角、去掉多余空白
    - 统一大小写（对日文影响不大）
    """
    if s is None:
        return ""

    s = s.strip()

    # 去扩展名（如果传进来的是文件名）
    if s.lower().endswith(".png"):
        s = s[:-4]

    # 全角括号统一（这里只替换括号本身；不替换其它全角符号，避免破坏日文）
    s = s.replace("（", "(").replace("）", ")")

    # 去掉前缀【...】标签（多段）
    s = LEADING_TAG_RE.sub("", s).strip()

    # 去掉“裏谱面”类后缀
    s = URA_SUFFIX_RE.sub("", s).strip()

    # 如果你确认要更激进，可开启：删除末尾任意括号内容
    # s = TRAILING_PAREN_RE.sub("", s).strip()

    # 压缩空白
    s = re.sub(r"\s+", " ", s)

    return s


def load_song_data(song_json_path: Path) -> List[Dict]:
    data = json.loads(song_json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("song_data.json 不是列表结构")
    # 仅保留需要字段
    songs = []
    for x in data:
        if not isinstance(x, dict):
            continue
        sid = x.get("id")
        name = x.get("song_name_jp")
        if sid is None or not name:
            continue
        songs.append({"id": str(sid), "song_name_jp": str(name)})
    return songs


def index_fumen_files(fumen_root: Path) -> Dict[str, List[Tuple[Path, str, bool]]]:
    """
    为每个难度建立索引：[(path, normalized_stem, is_inner_oni), ...]
    """
    index: Dict[str, List[Tuple[Path, str, bool]]] = {}
    for d in DIFFICULTIES:
        folder = fumen_root / d
        items: List[Tuple[Path, str, bool]] = []
        if folder.exists():
            for p in folder.glob("*.png"):
                # 是否“里谱面”：用原始文件名判断，不要用 normalize 后的名字
                is_inner = bool(
                    INNER_HINT_PAREN_RE.search(
                        p.stem.replace("（", "(").replace("）", ")")
                    )
                )
                norm = normalize_name(p.stem)
                items.append((p, norm, is_inner))
        index[d] = items
    return index


def best_match(
    target_norm: str,
    candidates: List[Tuple[Path, str, bool]],
    used_paths: set,
) -> Tuple[Optional[Path], float, bool]:
    """
    返回 (path or None, score, is_inner)
    """
    best_p = None
    best_score = -1.0
    best_inner = False
    for p, cand_norm, is_inner in candidates:
        if p in used_paths:
            continue
        score = fuzz.ratio(target_norm, cand_norm) / 100.0
        if score > best_score:
            best_score = score
            best_p = p
            best_inner = is_inner
    return best_p, best_score, best_inner


def best_match_filtered(
    target_norm: str,
    candidates: list[tuple[Path, str, bool]],
    used_paths: set[Path],
    want_inner: bool,
) -> tuple[Optional[Path], float]:
    """
    在 candidates 中仅匹配 is_inner == want_inner 的候选，返回 (path, score)
    """
    best_p = None
    best_score = -1.0
    for p, cand_norm, is_inner in candidates:
        if is_inner != want_inner:
            continue
        if p in used_paths:
            continue
        score = fuzz.ratio(target_norm, cand_norm) / 100.0
        if score > best_score:
            best_score = score
            best_p = p
    return best_p, best_score


def ensure_unique_target(path: Path) -> Path:
    """
    若目标文件已存在，为避免覆盖，自动追加 _2, _3...
    """
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def main():
    ap = argparse.ArgumentParser(
        description="将太鼓谱面文件按 song_data.json 的 id 复制重命名到新目录（模糊匹配>=阈值）"
    )
    ap.add_argument(
        "--base-dir",
        type=str,
        default=".",
        help="项目根目录（包含 song_data.json 与 assets/）",
    )
    ap.add_argument(
        "--song-json",
        type=str,
        default="songs/song_data.json",
        help="歌曲 json 文件名或路径",
    )
    ap.add_argument(
        "--fumens-dir",
        type=str,
        default="assets/fumens",
        help="谱面目录（包含4个难度子目录）",
    )
    ap.add_argument(
        "--out-dir",
        type=str,
        default="assets/fumens_rebuilt",
        help="输出目录（不会修改原文件）",
    )
    ap.add_argument(
        "--threshold", type=float, default=0.85, help="相似度阈值（0~1），默认0.90"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="只打印计划与日志，不复制文件"
    )
    ap.add_argument(
        "--allow-reuse",
        action="store_true",
        help="允许同一个原始png被多个song匹配（不推荐）",
    )
    args = ap.parse_args()

    base_dir = Path(args.base_dir).resolve()
    song_json_path = (
        (base_dir / args.song_json).resolve()
        if not Path(args.song_json).is_absolute()
        else Path(args.song_json)
    )
    fumen_root = (base_dir / args.fumens_dir).resolve()
    out_root = (base_dir / args.out_dir).resolve()

    if not song_json_path.exists():
        raise SystemExit(f"找不到 song json: {song_json_path}")
    if not fumen_root.exists():
        raise SystemExit(f"找不到 fumens 目录: {fumen_root}")

    songs = load_song_data(song_json_path)
    fumen_index = index_fumen_files(fumen_root)

    # 记录哪些源文件已经被使用（每个难度单独 tracking 更合理）
    used_by_diff = {d: set() for d in DIFFICULTIES}
    used_by_diff_inneroni = set()  # Oni 里谱面（InnerOni）的“已使用源文件”
    used_by_diff_outeroni = set()  # Oni 表谱面（Oni）的“已使用源文件”

    # 日志
    log_lines: List[str] = []
    log_lines.append(
        "difficulty\tsong_id\tsong_name_jp\tmatched_file\tmatch_score\toutput_file"
    )

    copied = 0
    matched = 0
    skipped = 0

    for s in songs:
        sid = s["id"]
        name = s["song_name_jp"]
        target_norm = normalize_name(name)

        for d in DIFFICULTIES:

            candidates = fumen_index.get(d, [])
            if not candidates:
                continue
            if d != "Oni":
                used_paths = used_by_diff[d] if not args.allow_reuse else set()

                p, score, is_inner = best_match(target_norm, candidates, used_paths)

                if p is None or score < args.threshold:
                    continue

                out_dir = out_root / d
                out_path = out_dir / f"{sid}.png"
                out_path = ensure_unique_target(out_path)
                log_lines.append(
                    f"{d}\t{sid}\t{name}\t{p.name}\t{score:.3f}\t{out_path.relative_to(base_dir) if out_path.is_relative_to(base_dir) else out_path}"
                )
                matched += 1
                if not args.dry_run:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, out_path)
                    copied += 1

                if not args.allow_reuse:
                    used_by_diff[d].add(p)
                continue
            # ---- 新逻辑：Oni 难度分别匹配表谱面与里谱面 ----
            # 1) 表谱面（is_inner == False）输出到 Oni/
            p_outer, score_outer = best_match_filtered(
                target_norm,
                candidates,
                used_by_diff_outeroni if not args.allow_reuse else set(),
                want_inner=False,
            )
            if p_outer is not None and score_outer >= args.threshold:
                out_dir = out_root / "Oni"
                out_path = ensure_unique_target(out_dir / f"{sid}.png")
                log_lines.append(
                    f"Oni\t{sid}\t{name}\t{p_outer.name}\t{score_outer:.3f}\t{out_path}"
                )
                matched += 1
                if name == "DEBSTEP！":
                    print(out_path)
                if not args.dry_run:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p_outer, out_path)
                    copied += 1
                if not args.allow_reuse:
                    used_by_diff_outeroni.add(p_outer)

            # 2) 里谱面（is_inner == True）输出到 InnerOni/
            p_inner, score_inner = best_match_filtered(
                target_norm,
                candidates,
                used_by_diff_inneroni if not args.allow_reuse else set(),
                want_inner=True,
            )
            if p_inner is not None and score_inner >= args.threshold:
                out_dir = out_root / "InnerOni"
                out_path = ensure_unique_target(out_dir / f"{sid}.png")
                log_lines.append(
                    f"InnerOni\t{sid}\t{name}\t{p_inner.name}\t{score_inner:.3f}\t{out_path}"
                )
                matched += 1
                if not args.dry_run:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p_inner, out_path)
                    copied += 1
                if not args.allow_reuse:
                    used_by_diff_inneroni.add(p_inner)
    # 未匹配统计（粗略：无法逐一列出每首歌每个难度的缺失，避免日志过大）
    # 你如需更细粒度，可扩展为对每首歌每难度都写一条 "NOT_FOUND"
    # 这里给出总体汇总。
    summary = [
        "",
        "===== Summary =====",
        f"Base dir: {base_dir}",
        f"Song json: {song_json_path}",
        f"Fumens dir: {fumen_root}",
        f"Out dir: {out_root}",
        f"Threshold: {args.threshold}",
        f"Songs: {len(songs)}",
        f"Matched (song-difficulty pairs): {matched}",
        f"Copied: {copied} (dry-run={args.dry_run})",
        "===================",
        "",
    ]

    # 写日志文件
    log_path = out_root / "rename_log.tsv"
    if args.dry_run:
        # dry-run 也写到当前目录，避免“out_dir不存在”导致写失败
        log_path = base_dir / "rename_log.tsv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines + summary), encoding="utf-8")

    print("\n".join(summary))
    print(f"Log written to: {log_path}")


if __name__ == "__main__":
    main()
