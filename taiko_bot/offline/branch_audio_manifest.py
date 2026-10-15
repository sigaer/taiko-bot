from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

from datetime import datetime
import hashlib
import math
import os
from pathlib import Path
import re
from typing import Iterable

import ujson as json


BRANCH_AUDIO_MANIFEST_PATH = Path(
    str(_runtime_root() / 'songs/branch_audio_manifest.json')
)
BRANCH_KEYS = ("N", "E", "M")
BRANCH_LABELS = {
    "N": "普通",
    "E": "玄人",
    "M": "达人",
}
COURSE_TO_TRACK = {
    "EASY": "EASY",
    "NORMAL": "NORMAL",
    "HARD": "HARD",
    "ONI": "ONI",
    "EDIT": "EDIT",
}
BRANCH_START_RE = re.compile(
    r"^#BRANCHSTART\s+([A-Z]),\s*(-?(?:\d+(?:\.\d*)?|\.\d+)),\s*(-?(?:\d+(?:\.\d*)?|\.\d+))",
    flags=re.IGNORECASE,
)


def _normalize_course(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized.isdigit():
        return {
            "0": "EASY",
            "1": "NORMAL",
            "2": "HARD",
            "3": "ONI",
            "4": "EDIT",
        }.get(normalized, normalized)
    return normalized


def _reachable_branch_keys(metric: str, first: float, second: float) -> set[str]:
    metric = str(metric or "").strip().lower()
    if metric == "p":
        domain_min, domain_max = 0.0, 100.0
    elif metric == "r":
        domain_min, domain_max = 0.0, math.inf
    else:
        return set(BRANCH_KEYS)

    reachable = set()
    if domain_min < first:
        reachable.add("N")

    expert_low = max(domain_min, first)
    if first < second and expert_low <= domain_max and expert_low < second:
        reachable.add("E")

    if domain_max >= max(first, second):
        reachable.add("M")
    return reachable


def _parse_branch_start(line: str) -> set[str]:
    match = BRANCH_START_RE.match(line)
    if not match:
        return set(BRANCH_KEYS)
    try:
        return _reachable_branch_keys(
            match.group(1),
            float(match.group(2)),
            float(match.group(3)),
        )
    except (TypeError, ValueError):
        return set(BRANCH_KEYS)


def _split_branch_lines(lines: list[str]):
    branch_lines = {key: [] for key in BRANCH_KEYS}
    branched_courses: set[str] = set()
    reachable_by_course: dict[str, set[str]] = {}
    in_branch = False
    active_branch = None
    current_course = None

    for line in lines:
        stripped = line.strip().lstrip("\ufeff")
        upper = stripped.upper()
        token = upper.split()[0] if upper else ""

        if upper.startswith("COURSE:"):
            raw = stripped.split(":", 1)[1] if ":" in stripped else ""
            current_course = _normalize_course(raw)

        if upper.startswith("#BRANCHSTART"):
            in_branch = True
            active_branch = None
            if current_course:
                branched_courses.add(current_course)
                reachable_by_course.setdefault(current_course, set()).update(
                    _parse_branch_start(upper)
                )
            continue

        if in_branch:
            if token == "#N":
                active_branch = "N"
                continue
            if token == "#E":
                active_branch = "E"
                continue
            if token == "#M":
                active_branch = "M"
                continue
            if upper.startswith("#BRANCHEND"):
                in_branch = False
                active_branch = None
                continue
            if active_branch in branch_lines:
                branch_lines[active_branch].append(line)
            continue

        for key in BRANCH_KEYS:
            branch_lines[key].append(line)

    return branch_lines, branched_courses, reachable_by_course


def _normalize_chart_line(line: str) -> str:
    content = line.lstrip("\ufeff").split("//", 1)[0].strip()
    if not content:
        return ""
    return re.sub(r"\s+", "", content).upper()


def _course_chart_signature(lines: Iterable[str], target_course: str) -> str:
    current_course = None
    chart_lines = []

    for line in lines:
        normalized = _normalize_chart_line(line)
        if not normalized:
            continue
        if normalized.startswith("COURSE:"):
            current_course = _normalize_course(normalized.split(":", 1)[1])
        if current_course == target_course:
            chart_lines.append(normalized)
    if not chart_lines:
        return ""
    payload = "\n".join(chart_lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def analyze_tja_branch_variants(tja_path: Path) -> dict[str, list[dict]]:
    lines = tja_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines(
        keepends=True
    )
    branch_lines, branched_courses, reachable_by_course = _split_branch_lines(lines)
    tracks: dict[str, list[dict]] = {}

    for course in sorted(branched_courses):
        track = COURSE_TO_TRACK.get(course)
        if not track:
            continue
        reachable = reachable_by_course.get(course) or set(BRANCH_KEYS)
        signatures: dict[str, list[str]] = {}
        for key in BRANCH_KEYS:
            if key not in reachable:
                continue
            signature = _course_chart_signature(branch_lines[key], course)
            if not signature:
                continue
            signatures.setdefault(signature, []).append(BRANCH_LABELS[key])

        variants = []
        for signature, labels in signatures.items():
            variants.append(
                {
                    "labels": labels,
                    "signature": signature,
                }
            )
        if variants:
            tracks[track] = variants

    return tracks


def _available_variant_label(
    song_id: int,
    track: str,
    labels: list[str],
    drum_objects: set[str],
    mix_objects: set[str],
) -> str | None:
    for label in labels:
        filename = f"{song_id}_{track}_{label}.mp3"
        if filename in drum_objects and filename in mix_objects:
            return label
    return None


def build_branch_audio_manifest(
    candidates: Iterable[dict],
    drum_objects: set[str],
    mix_objects: set[str],
    source_revision: str = "",
) -> dict:
    songs: dict[str, dict[str, list[dict]]] = {}
    missing_asset_groups = []
    analyzed_song_count = 0
    branch_track_count = 0
    variant_count = 0
    available_variant_count = 0
    merged_label_count = 0

    for candidate in candidates:
        song = candidate.get("song") or {}
        try:
            song_id = int(song["id"])
        except (KeyError, TypeError, ValueError):
            continue
        tja_path = Path(candidate["tja_path"])
        analyzed_song_count += 1
        tracks = analyze_tja_branch_variants(tja_path)
        manifest_tracks = {}

        for track, groups in tracks.items():
            variants = []
            for group in groups:
                labels = list(group["labels"])
                selected_label = _available_variant_label(
                    song_id,
                    track,
                    labels,
                    drum_objects,
                    mix_objects,
                )
                is_available = selected_label is not None
                if not is_available:
                    missing_asset_groups.append(
                        {
                            "songId": song_id,
                            "track": track,
                            "labels": labels,
                        }
                    )
                    selected_label = labels[0]
                else:
                    available_variant_count += 1
                aliases = [label for label in labels if label != selected_label]
                variants.append(
                    {
                        "label": selected_label,
                        "aliases": aliases,
                        "signature": group["signature"],
                        "available": is_available,
                    }
                )
                variant_count += 1
                merged_label_count += len(aliases)

            if variants:
                manifest_tracks[track] = variants
                branch_track_count += 1

        if manifest_tracks:
            songs[str(song_id)] = manifest_tracks

    return {
        "version": 1,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourceRevision": str(source_revision or ""),
        "songs": songs,
        "stats": {
            "analyzedSongCount": analyzed_song_count,
            "branchSongCount": len(songs),
            "branchTrackCount": branch_track_count,
            "variantCount": variant_count,
            "availableVariantCount": available_variant_count,
            "missingVariantCount": variant_count - available_variant_count,
            "mergedLabelCount": merged_label_count,
            "missingAssetGroupCount": len(missing_asset_groups),
        },
        "missingAssetGroups": missing_asset_groups,
    }


def write_branch_audio_manifest(
    manifest: dict,
    path: Path = BRANCH_AUDIO_MANIFEST_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
