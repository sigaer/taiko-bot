from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import argparse
from difflib import SequenceMatcher
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata

import ujson as json

try:
    from taiko_bot.offline.branch_audio_manifest import (
        BRANCH_AUDIO_MANIFEST_PATH,
        build_branch_audio_manifest,
        write_branch_audio_manifest,
    )
    from taiko_bot.offline.merge_index import (
        build_candidate_indexes,
        build_candidate_summary,
        select_candidate as select_metadata_candidate,
    )
except Exception:
    from branch_audio_manifest import (
        BRANCH_AUDIO_MANIFEST_PATH,
        build_branch_audio_manifest,
        write_branch_audio_manifest,
    )
    from merge_index import (
        build_candidate_indexes,
        build_candidate_summary,
        select_candidate as select_metadata_candidate,
    )

SONG_DATA_PATH = Path(str(_runtime_root() / 'songs/song_data.json'))
ESE_SYNC_REPO_PATH = Path("/home/sigaer/git/ESE_autosync")
TJA2AUDIO_ROOT = Path("/home/sigaer/git/tja2audio")
TJA2AUDIO_MAIN = TJA2AUDIO_ROOT / "main.py"
OSS_MIX_AUDIO_PREFIX = "oss://sigaer/mix"
OSS_DRUM_AUDIO_PREFIX = "oss://sigaer/drum"
OSS_PURE_AUDIO_PREFIX = "oss://sigaer/pure"
ESE_AUDIO_SYNC_REPORT_PATH = Path(str(_runtime_root() / 'logs/ese_audio_sync_report.json'))

ESE_REPO_URL = "https://ese.tjadataba.se/ESE/ESE"
ESE_REPO_URL_ALIASES = (
    ESE_REPO_URL,
    f"{ESE_REPO_URL}.git",
)
ESE_BRANCH = "master"
ESE_CATEGORY_DIRS = (
    "01 Pop",
    "02 Anime",
    "03 Vocaloid",
    "04 Children and Folk",
    "05 Variety",
    "06 Classical",
    "07 Game Music",
    "09 Namco Original",
)
try:
    COMMAND_TIMEOUT_SECONDS = int(os.getenv("ESE_AUDIO_SYNC_COMMAND_TIMEOUT", "900"))
except Exception:
    COMMAND_TIMEOUT_SECONDS = 900
if COMMAND_TIMEOUT_SECONDS <= 0:
    COMMAND_TIMEOUT_SECONDS = None

COURSE_TO_LEVEL = {
    "EASY": 1,
    "NORMAL": 2,
    "HARD": 3,
    "ONI": 4,
    "EDIT": 5,
}
BRANCH_LABELS = {
    "N": "普通",
    "E": "玄人",
    "M": "达人",
}
ENCODINGS = ("utf-8-sig", "utf-8", "cp932", "shift_jis", "gbk")
TITLE_NORMALIZE_RE = re.compile(r"[\s\-‐‑‒–—ー~〜～·・:：!！?？\[\]\(\)（）\"“”'‘’`]+")
TITLE_VARIANT_TRANSLATION = str.maketrans(
    {
        "晩": "晚",
    }
)
SONG_MATCH_TITLE_FIELDS = ("song_name_jp", "song_name")
TJA_PREFERRED_TITLE_KEYS = ("TITLEJA", "TITLEZH", "TITLE")
TJA_PREFERRED_SUBTITLE_KEYS = ("SUBTITLEJA", "SUBTITLEZH", "SUBTITLE")
FUZZY_MATCH_MIN_SCORE = 0.97
FUZZY_MATCH_MIN_GAP = 0.03
MATCH_STRATEGY_PRIORITY = {
    "fuzzy": 1,
    "normalized": 2,
    "exact": 3,
    "metadata": 4,
}
COVER_SOURCE_HINTS = (
    "cover audio",
    "cover ver",
    "(cover)",
    "taiko team cover",
)
PREFERRED_SOURCE_HINTS = (
    "new audio chart",
    "new audio",
    "(ac16)",
    " ac16 ",
)
LOW_PRIORITY_SOURCE_HINTS = (
    "old chart",
    "old audio chart",
    "old audio",
    "(old)",
)
GIT_LOCK_RETRY_LIMIT = 1


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_subprocess_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run(cmd, cwd=None, check=True, timeout=COMMAND_TIMEOUT_SECONDS):
    cmd_text = " ".join(str(part) for part in cmd)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _normalize_subprocess_output(exc.stdout).strip()
        stderr = _normalize_subprocess_output(exc.stderr).strip()
        raise RuntimeError(
            f"command timed out after {exc.timeout}s: {cmd_text}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        ) from exc
    if check and result.returncode != 0:
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"command failed: {cmd_text}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return result


def _write_report(report):
    ESE_AUDIO_SYNC_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ESE_AUDIO_SYNC_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def _tail_text(text, limit=2000):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _normalize_repo_url(url):
    normalized = str(url or "").strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized

def _repo_contains_path(repo_path: Path, other_path: Path):
    try:
        other_path.resolve().relative_to(repo_path.resolve())
        return True
    except Exception:
        return False


def _find_repo_git_lock_paths(repo_path: Path):
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return []
    return sorted(
        path
        for path in git_dir.rglob("*.lock")
        if path.is_file()
    )


def _read_process_cmdline(proc_dir: Path):
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except Exception:
        return []
    if not raw:
        return []
    return [
        chunk.decode("utf-8", errors="replace")
        for chunk in raw.split(b"\0")
        if chunk
    ]


def _find_git_processes_for_repo(repo_path: Path):
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []

    repo_path = repo_path.resolve()
    current_pid = os.getpid()
    matches = []
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        pid = int(proc_dir.name)
        if pid == current_pid:
            continue

        cmdline = _read_process_cmdline(proc_dir)
        if not cmdline:
            continue
        executable = os.path.basename(cmdline[0]).lower()
        if executable != "git" and executable != "git-remote-http":
            continue

        cwd = None
        try:
            cwd = Path(os.readlink(proc_dir / "cwd")).resolve()
        except Exception:
            cwd = None

        cmd_text = " ".join(cmdline)
        if cwd is None and str(repo_path) not in cmd_text:
            continue
        if cwd is not None and not _repo_contains_path(repo_path, cwd) and str(repo_path) not in cmd_text:
            continue

        matches.append(
            {
                "pid": pid,
                "cwd": str(cwd) if cwd is not None else None,
                "cmd": cmd_text,
            }
        )
    return matches


def _format_repo_git_processes(processes):
    return "; ".join(
        f"pid={item['pid']} cwd={item['cwd'] or '-'} cmd={item['cmd']}"
        for item in processes
    )


def _cleanup_stale_repo_lock_files(repo_path: Path, reason: str):
    lock_paths = _find_repo_git_lock_paths(repo_path)
    if not lock_paths:
        return None

    processes = _find_git_processes_for_repo(repo_path)
    if processes:
        raise RuntimeError(
            "ESE 自动镜像仓库存在活动中的 git 进程，跳过 lock 清理:\n"
            f"locks={', '.join(str(path) for path in lock_paths)}\n"
            f"{_format_repo_git_processes(processes)}"
        )

    removed_locks = []
    now_ts = datetime.now().timestamp()
    for lock_path in lock_paths:
        try:
            age_seconds = max(0, int(now_ts - lock_path.stat().st_mtime))
        except Exception:
            age_seconds = None
        lock_path.unlink()
        removed_locks.append(
            {
                "path": str(lock_path),
                "age_seconds": age_seconds,
            }
        )

    return {
        "reason": reason,
        "locks": removed_locks,
    }


def _format_lock_cleanup_note(cleanup_result):
    if not cleanup_result:
        return None
    parts = []
    for item in cleanup_result.get("locks", []):
        age_seconds = item.get("age_seconds")
        age_text = f"{age_seconds}s" if isinstance(age_seconds, int) else "unknown"
        parts.append(f"{item['path']} age={age_text}")
    return (
        "自动清理 ESE 镜像残留 lock 并重试: "
        f"locks=[{'; '.join(parts)}] "
        f"reason={cleanup_result['reason']}"
    )


def _should_retry_git_with_lock_cleanup(exc: Exception, repo_path: Path):
    lock_paths = _find_repo_git_lock_paths(repo_path)
    if not lock_paths:
        return False
    message = str(exc)
    return (
        ".lock" in message
        or "Another git process seems to be running" in message
        or "command timed out" in message
    )


def _run_repo_git(cmd, repo_path: Path, check=True, timeout=COMMAND_TIMEOUT_SECONDS):
    last_exc = None
    for attempt in range(GIT_LOCK_RETRY_LIMIT + 1):
        try:
            return _run(cmd, cwd=repo_path, check=check, timeout=timeout)
        except RuntimeError as exc:
            last_exc = exc
            if attempt >= GIT_LOCK_RETRY_LIMIT:
                raise
            if not _should_retry_git_with_lock_cleanup(exc, repo_path):
                raise
            cleanup_result = _cleanup_stale_repo_lock_files(
                repo_path,
                reason="retry_after_git_failure",
            )
            if cleanup_result is None:
                raise
            print(f"[ESE][GIT] {_format_lock_cleanup_note(cleanup_result)}")
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unexpected git retry state")


def _inspect_git_repo(repo_path: Path):
    if not (repo_path / ".git").exists():
        raise FileNotFoundError(f"ESE 仓库目录不是 git 仓库: {repo_path}")
    remote_url = _run_repo_git(
        ["git", "config", "--get", "remote.origin.url"],
        repo_path,
    ).stdout.strip()
    normalized_remote_url = _normalize_repo_url(remote_url)
    normalized_expected_urls = {
        _normalize_repo_url(candidate)
        for candidate in ESE_REPO_URL_ALIASES
    }
    if normalized_remote_url not in normalized_expected_urls:
        raise RuntimeError(f"ESE 仓库远端不匹配: {remote_url}")
    status = _run_repo_git(["git", "status", "--short"], repo_path).stdout.strip()
    return {
        "remote_url": remote_url,
        "status": status,
    }


def _backup_repo_path(repo_path: Path, reason: str):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_reason = str(reason or "backup").strip().replace(" ", "_")
    safe_reason = "".join(ch for ch in safe_reason if ch.isalnum() or ch in {"_", "-"})
    if not safe_reason:
        safe_reason = "backup"
    backup_path = repo_path.parent / f"{repo_path.name}_{safe_reason}_{timestamp}"
    shutil.move(str(repo_path), str(backup_path))
    return backup_path


def _repair_managed_repo(repo_path: Path, dirty_status: str):
    _run_repo_git(
        ["git", "restore", "--source=HEAD", "--staged", "--worktree", "."],
        repo_path,
    )
    _run_repo_git(["git", "clean", "-fd"], repo_path)
    repaired = _inspect_git_repo(repo_path)
    if repaired["status"]:
        raise RuntimeError(
            "自动镜像自修复后仍存在未提交修改:\n"
            f"before:\n{dirty_status}\n\nafter:\n{repaired['status']}"
        )
    return (
        "自动镜像存在未提交修改，已自动恢复并继续同步:\n"
        f"{dirty_status}"
    )


def _ensure_sparse_checkout(repo_path: Path):
    desired_dirs = tuple(ESE_CATEGORY_DIRS)
    enabled_result = _run_repo_git(
        ["git", "config", "--bool", "core.sparseCheckout"],
        repo_path,
        check=False,
    )
    sparse_enabled = (
        enabled_result.returncode == 0
        and (enabled_result.stdout or "").strip().lower() == "true"
    )
    current_dirs = None
    if sparse_enabled:
        list_result = _run_repo_git(
            ["git", "sparse-checkout", "list"],
            repo_path,
            check=False,
        )
        if list_result.returncode == 0:
            current_dirs = tuple(
                line.strip()
                for line in (list_result.stdout or "").splitlines()
                if line.strip()
            )

    if sparse_enabled and current_dirs == desired_dirs:
        return False

    if not sparse_enabled:
        _run_repo_git(["git", "sparse-checkout", "init", "--cone"], repo_path)
    _run_repo_git(["git", "sparse-checkout", "set", *desired_dirs], repo_path)
    return True


def _clone_ese_repo(repo_path: Path):
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        ESE_BRANCH,
        "--filter=blob:none",
        "--sparse",
        ESE_REPO_URL,
        str(repo_path),
    ]
    _run(clone_cmd)
    _ensure_sparse_checkout(repo_path)
    return {
        "clone_source": ESE_REPO_URL,
        "seeded_from_local_repo": False,
    }


def _ensure_ese_repo():
    repo_notes = []
    backup_path = None

    if ESE_SYNC_REPO_PATH.exists():
        cleanup_result = _cleanup_stale_repo_lock_files(
            ESE_SYNC_REPO_PATH,
            reason="preflight",
        )
        cleanup_note = _format_lock_cleanup_note(cleanup_result)
        if cleanup_note:
            repo_notes.append(cleanup_note)
        rebuild_reason = ""
        try:
            repo_state = _inspect_git_repo(ESE_SYNC_REPO_PATH)
            if _normalize_repo_url(repo_state["remote_url"]) != _normalize_repo_url(ESE_REPO_URL):
                _run_repo_git(
                    ["git", "remote", "set-url", "origin", ESE_REPO_URL],
                    ESE_SYNC_REPO_PATH,
                )
                repo_notes.append(f"自动镜像远端已迁移到: {ESE_REPO_URL}")
                repo_state = _inspect_git_repo(ESE_SYNC_REPO_PATH)
            dirty_status = repo_state["status"]
            if dirty_status:
                try:
                    repo_notes.append(_repair_managed_repo(ESE_SYNC_REPO_PATH, dirty_status))
                except Exception as exc:
                    rebuild_reason = "dirty"
                    repo_notes.append(f"自动镜像自修复失败，已重建镜像并继续同步: {exc}")
        except Exception as exc:
            rebuild_reason = "invalid"
            repo_notes.append(f"自动镜像无效，已重建镜像并继续同步: {exc}")
        if rebuild_reason:
            backup_path = _backup_repo_path(ESE_SYNC_REPO_PATH, rebuild_reason)

    if not ESE_SYNC_REPO_PATH.exists():
        _clone_ese_repo(ESE_SYNC_REPO_PATH)

    sparse_updated = _ensure_sparse_checkout(ESE_SYNC_REPO_PATH)
    if sparse_updated:
        repo_notes.append("已刷新 ESE 自动镜像 sparse-checkout 目录配置")
    _run_repo_git(["git", "pull", "--ff-only", "origin", ESE_BRANCH], ESE_SYNC_REPO_PATH)
    if _ensure_sparse_checkout(ESE_SYNC_REPO_PATH):
        repo_notes.append("拉取后已重新应用 ESE 自动镜像 sparse-checkout 目录配置")

    revision = _run_repo_git(["git", "rev-parse", "HEAD"], ESE_SYNC_REPO_PATH).stdout.strip()
    repo_info = {
        "repo_path": str(ESE_SYNC_REPO_PATH),
        "repo_url": ESE_REPO_URL,
        "branch": ESE_BRANCH,
        "revision": revision,
        "categories": list(ESE_CATEGORY_DIRS),
        "managed_mirror": True,
    }
    if backup_path is not None:
        repo_info["backup_repo_path"] = str(backup_path)
    if repo_notes:
        repo_info["notes"] = repo_notes
    return repo_info


def _read_text_with_fallback(path: Path):
    data = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_tja_metadata(path: Path):
    title_fields = {}
    subtitle_fields = {}
    wave = None
    content = _read_text_with_fallback(path)
    for line in content.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        upper = key.strip().upper()
        value = value.strip()
        if not value:
            continue
        if upper == "WAVE":
            wave = value
            continue
        if upper.startswith("TITLE"):
            title_fields.setdefault(upper, value)
            continue
        if upper.startswith("SUBTITLE"):
            subtitle_fields.setdefault(upper, value.lstrip("-").strip())
    return {
        "titleja": title_fields.get("TITLEJA"),
        "titles": title_fields,
        "subtitles": subtitle_fields,
        "wave": wave.strip() if isinstance(wave, str) else None,
    }


def _normalize_course(course_value):
    course_value = str(course_value or "").strip().upper()
    if course_value.isdigit():
        return {
            "0": "EASY",
            "1": "NORMAL",
            "2": "HARD",
            "3": "ONI",
            "4": "EDIT",
        }.get(course_value, course_value)
    return course_value


def _split_branch_lines(lines):
    branch_lines = {"N": [], "E": [], "M": []}
    branched_courses = set()
    has_branch = False
    in_branch = False
    active_branch = None
    current_course = None
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        token = upper.split()[0] if upper else ""
        if upper.startswith("COURSE:"):
            raw = stripped.split(":", 1)[1] if ":" in stripped else ""
            current_course = _normalize_course(raw)
        if upper.startswith("#END"):
            current_course = None
        if upper.startswith("#BRANCHSTART"):
            has_branch = True
            in_branch = True
            active_branch = None
            if current_course:
                branched_courses.add(current_course)
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
        for key in branch_lines:
            branch_lines[key].append(line)
    return branch_lines, has_branch, branched_courses


def _collect_courses_with_notes(lines):
    current_course = None
    start = False
    courses = set()
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        upper = line.upper()
        if upper.startswith("COURSE:"):
            current_course = _normalize_course(line.split(":", 1)[1])
            continue
        if "#START" in upper:
            start = True
            continue
        if "#END" in upper:
            start = False
            continue
        if not start or current_course not in COURSE_TO_LEVEL:
            continue
        compact = line.split("//")[0].strip().replace(" ", "").replace("\t", "")
        payload = compact.replace(",", "")
        if payload.isdigit() and any(ch in "12345678" for ch in payload):
            courses.add(current_course)
    return courses


def _song_level_required(song, diff_name):
    level = COURSE_TO_LEVEL.get(diff_name)
    if level is None:
        return False
    value = song.get(f"level_{level}")
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "-":
        return False
    return True


def _build_output_mapping(tja_path: Path, song):
    lines = _read_text_with_fallback(tja_path).splitlines(keepends=True)
    branch_lines, has_branch, branched_courses = _split_branch_lines(lines)
    mapping = {}
    tja_name = tja_path.name

    if not has_branch:
        for course in sorted(_collect_courses_with_notes(lines)):
            if not _song_level_required(song, course):
                continue
            mapping[f"{song['id']}_{course}.mp3"] = f"{tja_name}_{course}.mp3"
        return mapping

    for branch_key in ("N", "E", "M"):
        courses = _collect_courses_with_notes(branch_lines[branch_key])
        for course in sorted(courses):
            if not _song_level_required(song, course):
                continue
            if course in branched_courses:
                label = BRANCH_LABELS[branch_key]
                mapping[f"{song['id']}_{course}_{label}.mp3"] = (
                    f"{tja_name}_{course}（{label}）.mp3"
                )
            elif branch_key == "N":
                mapping[f"{song['id']}_{course}.mp3"] = f"{tja_name}_{course}.mp3"
    return mapping


def _normalize_title(text):
    normalized = unicodedata.normalize("NFKC", str(text or "").strip()).lower()
    normalized = normalized.translate(TITLE_VARIANT_TRANSLATION)
    normalized = TITLE_NORMALIZE_RE.sub("", normalized)
    normalized = normalized.replace("&", "and")
    return normalized


def _find_music_path(tja_dir: Path, wave_field: str | None):
    if wave_field:
        candidate = (tja_dir / wave_field).resolve()
        if candidate.is_file():
            return candidate
    for pattern in ("*.ogg", "*.OGG", "*.mp3", "*.MP3", "*.wav", "*.WAV", "*.flac", "*.m4a"):
        matches = sorted(tja_dir.glob(pattern))
        if matches:
            return matches[0].resolve()
    return None


def _symlink_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        return
    try:
        os.symlink(src, dst)
    except Exception:
        shutil.copy2(src, dst)


def _stage_song_inputs(tja_path: Path, wave_field: str | None, music_path: Path | None, stage_dir: Path):
    stage_tja = stage_dir / tja_path.name
    _symlink_or_copy(tja_path, stage_tja)
    if music_path is None:
        return stage_tja
    _symlink_or_copy(music_path, stage_dir / music_path.name)
    if wave_field:
        _symlink_or_copy(music_path, stage_dir / wave_field)
    return stage_tja


def _collect_existing_objects(prefix, object_kind="chart"):
    result = _run(["ossutil", "ls", prefix, "-s"])
    existing = set()
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if not line.startswith("oss://") or not line.endswith(".mp3"):
            continue
        name = Path(line).name
        stem = name[:-4]
        if object_kind == "pure":
            if stem.isdigit():
                existing.add(name)
            continue
        if "_" not in stem:
            continue
        sid, rest = stem.split("_", 1)
        if not sid.isdigit():
            continue
        if rest.startswith("EASY") or rest.startswith("NORMAL") or rest.startswith("HARD") or rest.startswith("ONI") or rest.startswith("EDIT"):
            existing.add(name)
    return existing


def _ordered_unique_values(values):
    unique_values = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        unique_values.append(text)
        seen.add(text)
    return unique_values


def _iter_song_match_titles(song):
    return _ordered_unique_values(
        song.get(field)
        for field in SONG_MATCH_TITLE_FIELDS
    )


def _build_unique_song_title_map(
    song_data,
    title_transform=None,
    on_shelf_only=True,
):
    title_to_rows = {}
    for song in song_data:
        if not isinstance(song, dict):
            continue
        if on_shelf_only and song.get("shelf_status") not in (0, "未下架"):
            continue
        for title in _iter_song_match_titles(song):
            key = title_transform(title) if title_transform else title
            if not key:
                continue
            title_to_rows.setdefault(key, []).append(song)

    unique_map = {}
    collisions = {}
    for title, rows in title_to_rows.items():
        if len(rows) == 1:
            unique_map[title] = rows[0]
        else:
            collisions[title] = sorted(int(row["id"]) for row in rows if row.get("id") is not None)
    return unique_map, collisions


def _iter_on_shelf_songs(song_data, include_other=False):
    for song in song_data:
        if not isinstance(song, dict):
            continue
        status = song.get("shelf_status")
        if status in (0, "未下架"):
            yield song
        elif include_other and status == 2:
            yield song


def _build_song_match_indexes(song_data, on_shelf_only=True, include_other=False):
    songs = (
        list(_iter_on_shelf_songs(song_data, include_other=include_other))
        if on_shelf_only
        else [song for song in song_data if isinstance(song, dict)]
    )
    song_by_id = {}
    for song in songs:
        try:
            song_by_id[int(song["id"])] = song
        except Exception:
            continue
    title_map, title_collisions = _build_unique_song_title_map(
        songs,
        on_shelf_only=False,
    )
    normalized_map, normalized_collisions = _build_unique_song_title_map(
        songs,
        title_transform=_normalize_title,
        on_shelf_only=False,
    )
    return {
        "songs": songs,
        "song_by_id": song_by_id,
        "title_map": title_map,
        "title_collisions": title_collisions,
        "normalized_map": normalized_map,
        "normalized_collisions": normalized_collisions,
    }


def _build_tja_record(tja_path: Path):
    metadata = _extract_tja_metadata(tja_path)
    titles = []
    for key in TJA_PREFERRED_TITLE_KEYS:
        value = metadata["titles"].get(key)
        if value:
            titles.append(value)
    for key, value in sorted(metadata["titles"].items()):
        if key not in TJA_PREFERRED_TITLE_KEYS and value:
            titles.append(value)
    titles = _ordered_unique_values(titles)
    if not titles:
        return None
    subtitles = []
    for key in TJA_PREFERRED_SUBTITLE_KEYS:
        value = metadata["subtitles"].get(key)
        if value:
            subtitles.append(value)
    for key, value in sorted(metadata["subtitles"].items()):
        if key not in TJA_PREFERRED_SUBTITLE_KEYS and value:
            subtitles.append(value)
    subtitles = _ordered_unique_values(subtitles)
    titleja = metadata["titleja"] or titles[0]
    return {
        "titleja": titleja,
        "primary_title": titles[0],
        "titles": titles,
        "subtitles": subtitles,
        "normalized_titles": _ordered_unique_values(_normalize_title(title) for title in titles),
        "tja_path": tja_path,
        "wave_field": metadata["wave"],
        "music_path": _find_music_path(tja_path.parent, metadata["wave"]),
    }


def _add_candidate(matched_candidates, song, tja_record, match_strategy, match_score):
    try:
        song_id = int(song["id"])
    except Exception:
        return
    candidate = {
        "song": song,
        "titleja": tja_record["titleja"],
        "primary_title": tja_record["primary_title"],
        "titles": tja_record["titles"],
        "subtitles": tja_record["subtitles"],
        "normalized_titles": tja_record["normalized_titles"],
        "tja_path": tja_record["tja_path"],
        "wave_field": tja_record["wave_field"],
        "music_path": tja_record["music_path"],
        "match_strategy": match_strategy,
        "match_score": match_score,
    }
    candidate_key = str(tja_record["tja_path"])
    song_candidates = matched_candidates.setdefault(song_id, {})
    existing = song_candidates.get(candidate_key)
    existing_priority = (
        MATCH_STRATEGY_PRIORITY.get(existing.get("match_strategy"), 0),
        float(existing.get("match_score") or 0.0),
    ) if existing else None
    candidate_priority = (
        MATCH_STRATEGY_PRIORITY.get(match_strategy, 0),
        float(match_score or 0.0),
    )
    if existing is None or candidate_priority > existing_priority:
        song_candidates[candidate_key] = candidate


def _get_title_best_scores(song_titles, tja_records):
    normalized_song_titles = _ordered_unique_values(
        _normalize_title(song_title)
        for song_title in song_titles
    )
    if not normalized_song_titles:
        return None, 0.0, 0.0

    best_record = None
    best_score = 0.0
    second_score = 0.0
    for record in tja_records:
        record_best_score = 0.0
        for normalized_song_title in normalized_song_titles:
            for normalized_title in record["normalized_titles"]:
                if not normalized_title:
                    continue
                score = SequenceMatcher(None, normalized_song_title, normalized_title).ratio()
                if score > record_best_score:
                    record_best_score = score
        if record_best_score > best_score:
            second_score = best_score
            best_score = record_best_score
            best_record = record
        elif record_best_score > second_score:
            second_score = record_best_score
    return best_record, best_score, second_score


def _match_tja_records(song_indexes, tja_records):
    matched_candidates = {}
    skipped_unmatched = []

    for tja_record in tja_records:
        for title in tja_record["titles"]:
            if title in song_indexes["title_collisions"]:
                continue
            song = song_indexes["title_map"].get(title)
            if song is not None:
                _add_candidate(
                    matched_candidates,
                    song,
                    tja_record,
                    "exact",
                    1.0,
                )

        for normalized_title in tja_record["normalized_titles"]:
            if (
                not normalized_title
                or normalized_title in song_indexes["normalized_collisions"]
            ):
                continue
            song = song_indexes["normalized_map"].get(normalized_title)
            if song is not None:
                _add_candidate(
                    matched_candidates,
                    song,
                    tja_record,
                    "normalized",
                    1.0,
                )

    matched_song_ids = set(matched_candidates)
    for song in song_indexes["songs"]:
        try:
            song_id = int(song["id"])
        except Exception:
            continue
        if song_id in matched_song_ids:
            continue

        song_titles = _iter_song_match_titles(song)
        if not song_titles:
            skipped_unmatched.append(
                {
                    "song_id": song_id,
                    "titleja": "",
                    "reason": "missing_song_title",
                }
            )
            continue

        best_record, best_score, second_score = _get_title_best_scores(
            song_titles,
            tja_records,
        )
        if (
            best_record
            and best_score >= FUZZY_MATCH_MIN_SCORE
            and (best_score - second_score) >= FUZZY_MATCH_MIN_GAP
        ):
            _add_candidate(
                matched_candidates,
                song,
                best_record,
                "fuzzy",
                best_score,
            )
            continue

        skipped_unmatched.append(
            {
                "song_id": song_id,
                "titleja": song_titles[0],
                "reason": "no_confident_match",
                "best_titleja": (
                    best_record["primary_title"] if best_record else None
                ),
                "best_score": round(best_score, 6),
                "second_best_score": round(second_score, 6),
            }
        )

    return matched_candidates, skipped_unmatched


def _build_metadata_matcher(repo_path, tja_records):
    candidate_summaries = []
    record_by_path = {}
    skipped = []

    for record in tja_records:
        tja_path = Path(record["tja_path"]).resolve()
        try:
            summary = build_candidate_summary(str(tja_path), repo_path)
        except Exception as exc:
            skipped.append(
                {
                    "tja_path": str(tja_path),
                    "reason": "metadata_analysis_failed",
                    "error": str(exc),
                }
            )
            continue
        candidate_summaries.append(summary)
        record_by_path[str(tja_path)] = record

    return {
        "candidates": candidate_summaries,
        "indexes": build_candidate_indexes(candidate_summaries),
        "record_by_path": record_by_path,
        "skipped": skipped,
    }


def _match_songs_with_metadata(
    song_data,
    repo_path,
    matcher,
    on_shelf_only=True,
    include_other=False,
):
    matched_candidates = {}
    skipped_unmatched = []
    songs = (
        list(_iter_on_shelf_songs(song_data, include_other=include_other))
        if on_shelf_only
        else [song for song in song_data if isinstance(song, dict)]
    )

    for song in songs:
        try:
            song_id = int(song["id"])
        except Exception:
            continue
        summary, decision = select_metadata_candidate(
            song,
            matcher["candidates"],
            *matcher["indexes"],
            repo_path,
        )
        if summary is None:
            skipped_unmatched.append(
                {
                    "song_id": song_id,
                    "titleja": next(iter(_iter_song_match_titles(song)), ""),
                    **decision,
                }
            )
            continue

        tja_record = matcher["record_by_path"].get(
            str(Path(summary.path).resolve())
        )
        if tja_record is None:
            skipped_unmatched.append(
                {
                    "song_id": song_id,
                    "titleja": next(iter(_iter_song_match_titles(song)), ""),
                    "reason": "selected_record_missing",
                    "tja_path": summary.path,
                }
            )
            continue

        _add_candidate(
            matched_candidates,
            song,
            tja_record,
            "metadata",
            float(decision.get("score") or 1.0),
        )

    return matched_candidates, skipped_unmatched


def _candidate_source_penalty(candidate):
    haystack = " ".join(
        _ordered_unique_values(
            [
                str(candidate["tja_path"]),
                candidate.get("primary_title"),
                candidate.get("titleja"),
                *candidate.get("titles", []),
                *candidate.get("subtitles", []),
            ]
        )
    ).lower()
    penalty = 0
    for token in COVER_SOURCE_HINTS:
        if token in haystack:
            penalty += 20
    for token in LOW_PRIORITY_SOURCE_HINTS:
        if token in haystack:
            penalty += 5
    return penalty


def _candidate_source_bonus(candidate):
    haystack = " ".join(
        _ordered_unique_values(
            [
                str(candidate["tja_path"]),
                candidate.get("primary_title"),
                candidate.get("titleja"),
                *candidate.get("titles", []),
                *candidate.get("subtitles", []),
            ]
        )
    ).lower()
    bonus = 0
    for token in PREFERRED_SOURCE_HINTS:
        if token in haystack:
            bonus += 5
    return bonus


def _candidate_priority(candidate):
    return (
        MATCH_STRATEGY_PRIORITY.get(candidate.get("match_strategy"), 0),
        float(candidate.get("match_score") or 0.0),
        1 if candidate.get("music_path") else 0,
        _candidate_source_bonus(candidate),
        -_candidate_source_penalty(candidate),
    )


def _select_candidate(candidates):
    grouped = {}
    for candidate in candidates:
        grouped.setdefault(_candidate_priority(candidate), []).append(candidate)
    best_priority = max(grouped)
    best_group = grouped[best_priority]
    if len(best_group) != 1:
        return None, [], False
    best_candidate = best_group[0]
    alternatives = [
        candidate
        for candidate in candidates
        if str(candidate["tja_path"]) != str(best_candidate["tja_path"])
    ]
    return best_candidate, alternatives, True


def _resolve_matched_candidates(matched_candidates):
    selected = []
    resolved_duplicates = []
    skipped_duplicates = []

    for song_id, candidate_map in sorted(matched_candidates.items()):
        candidates = list(candidate_map.values())
        if len(candidates) > 1:
            candidate, alternatives, resolved = _select_candidate(candidates)
            if not resolved or candidate is None:
                skipped_duplicates.append(
                    {
                        "song_id": song_id,
                        "titleja": candidates[0]["titleja"],
                        "match_strategies": sorted(
                            {
                                item.get("match_strategy")
                                for item in candidates
                            }
                        ),
                        "tja_paths": [
                            str(item["tja_path"]) for item in candidates
                        ],
                    }
                )
                continue
            resolved_duplicates.append(
                {
                    "song_id": song_id,
                    "titleja": candidate["titleja"],
                    "selected_tja_path": str(candidate["tja_path"]),
                    "alternative_tja_paths": [
                        str(item["tja_path"]) for item in alternatives
                    ],
                }
            )
        else:
            candidate = candidates[0]
        selected.append(candidate)

    return selected, resolved_duplicates, skipped_duplicates


def _transcode_audio_to_mp3(source_path: Path, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(target_path),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed\n"
            f"stdout:\n{_tail_text(result.stdout)}\n"
            f"stderr:\n{_tail_text(result.stderr)}"
        )
    if not target_path.exists():
        raise RuntimeError(f"ffmpeg 未生成目标文件: {target_path}")


def _iter_tja_files(repo_path: Path):
    for category in ESE_CATEGORY_DIRS:
        category_dir = repo_path / category
        if not category_dir.exists():
            continue
        for tja_path in sorted(category_dir.rglob("*.tja")):
            yield tja_path


def _run_tja2audio(input_dir: Path, output_dir: Path, mix_music: bool):
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(TJA2AUDIO_MAIN),
        "-i",
        str(input_dir),
        "-o",
        str(output_dir),
        "-f",
        "mp3",
        "-w",
        "1",
        "--overwrite",
    ]
    if mix_music:
        cmd.append("--mix-music")
    else:
        cmd.append("--no-mix-music")
    result = _run(cmd, cwd=TJA2AUDIO_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "tja2audio failed\n"
            f"stdout:\n{_tail_text(result.stdout)}\n"
            f"stderr:\n{_tail_text(result.stderr)}"
        )


def _standardize_outputs(raw_output_dir: Path, target_names, output_mapping):
    standardized = {}
    missing_generated = []
    for target_name in sorted(target_names):
        source_name = output_mapping[target_name]
        source_path = raw_output_dir / source_name
        if not source_path.exists():
            missing_generated.append({"target": target_name, "expected_source": source_name})
            continue
        target_path = raw_output_dir / target_name
        if source_path != target_path:
            if target_path.exists():
                target_path.unlink()
            source_path.rename(target_path)
        standardized[target_name] = target_path
    return standardized, missing_generated


def _upload_outputs(side_prefix, local_files, dry_run):
    uploaded = []
    failed = []
    for target_name, local_path in sorted(local_files.items()):
        oss_target = f"{side_prefix}/{target_name}"
        if dry_run:
            uploaded.append({"target": target_name, "oss_target": oss_target, "dry_run": True})
            continue
        result = _run(
            ["ossutil", "cp", "-u", str(local_path), oss_target],
            check=False,
        )
        if result.returncode == 0:
            uploaded.append({"target": target_name, "oss_target": oss_target})
        else:
            failed.append(
                {
                    "target": target_name,
                    "oss_target": oss_target,
                    "stdout": _tail_text(result.stdout),
                    "stderr": _tail_text(result.stderr),
                }
            )
    return uploaded, failed


def _process_candidate(candidate, dry_run=False):
    item = {
        "song_id": candidate["song"]["id"],
        "titleja": candidate["titleja"],
        "match_strategy": candidate.get("match_strategy"),
        "match_score": candidate.get("match_score"),
        "tja_path": str(candidate["tja_path"]),
        "source_audio": str(candidate["music_path"]) if candidate["music_path"] else None,
        "pure_source_audio": str(candidate["music_path"]) if candidate["music_path"] else None,
        "required_objects": sorted(candidate["output_mapping"]),
        "missing_mix": sorted(candidate["missing_mix"]),
        "missing_drum": sorted(candidate["missing_drum"]),
        "missing_pure": sorted(candidate["missing_pure"]),
        "uploaded_mix": [],
        "uploaded_drum": [],
        "uploaded_pure": [],
        "failed": [],
    }

    with tempfile.TemporaryDirectory(prefix=f"ese_audio_{candidate['song']['id']}_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        stage_dir = tmpdir_path / "input"
        _stage_song_inputs(
            candidate["tja_path"],
            candidate["wave_field"],
            candidate["music_path"],
            stage_dir,
        )

        if candidate["missing_mix"]:
            if candidate["music_path"] is None:
                item["failed"].append(
                    {
                        "stage": "mix_precheck",
                        "reason": "missing_source_audio",
                    }
                )
            else:
                raw_mix_dir = tmpdir_path / "mix"
                try:
                    _run_tja2audio(stage_dir, raw_mix_dir, mix_music=True)
                    standardized_mix, missing_generated = _standardize_outputs(
                        raw_mix_dir,
                        candidate["missing_mix"],
                        candidate["output_mapping"],
                    )
                    if missing_generated:
                        item["failed"].append(
                            {
                                "stage": "mix_standardize",
                                "missing_generated": missing_generated,
                            }
                        )
                    uploaded_mix, failed_mix = _upload_outputs(
                        OSS_MIX_AUDIO_PREFIX,
                        standardized_mix,
                        dry_run=dry_run,
                    )
                    item["uploaded_mix"].extend(uploaded_mix)
                    if failed_mix:
                        item["failed"].append(
                            {
                                "stage": "mix_upload",
                                "errors": failed_mix,
                            }
                        )
                except Exception as exc:
                    item["failed"].append(
                        {
                            "stage": "mix_generate",
                            "reason": str(exc),
                        }
                    )

        if candidate["missing_drum"]:
            raw_drum_dir = tmpdir_path / "drum"
            try:
                _run_tja2audio(stage_dir, raw_drum_dir, mix_music=False)
                standardized_drum, missing_generated = _standardize_outputs(
                    raw_drum_dir,
                    candidate["missing_drum"],
                    candidate["output_mapping"],
                )
                if missing_generated:
                    item["failed"].append(
                        {
                            "stage": "drum_standardize",
                            "missing_generated": missing_generated,
                        }
                    )
                uploaded_drum, failed_drum = _upload_outputs(
                    OSS_DRUM_AUDIO_PREFIX,
                    standardized_drum,
                    dry_run=dry_run,
                )
                item["uploaded_drum"].extend(uploaded_drum)
                if failed_drum:
                    item["failed"].append(
                        {
                            "stage": "drum_upload",
                            "errors": failed_drum,
                        }
                    )
            except Exception as exc:
                    item["failed"].append(
                        {
                            "stage": "drum_generate",
                            "reason": str(exc),
                        }
                    )

        if candidate["missing_pure"]:
            if candidate["music_path"] is None:
                item["failed"].append(
                    {
                        "stage": "pure_precheck",
                        "reason": "missing_source_audio",
                    }
                )
            else:
                raw_pure_dir = tmpdir_path / "pure"
                raw_pure_dir.mkdir(parents=True, exist_ok=True)
                target_name = sorted(candidate["missing_pure"])[0]
                target_path = raw_pure_dir / target_name
                try:
                    _transcode_audio_to_mp3(candidate["music_path"], target_path)
                    uploaded_pure, failed_pure = _upload_outputs(
                        OSS_PURE_AUDIO_PREFIX,
                        {target_name: target_path},
                        dry_run=dry_run,
                    )
                    item["uploaded_pure"].extend(uploaded_pure)
                    if failed_pure:
                        item["failed"].append(
                            {
                                "stage": "pure_upload",
                                "errors": failed_pure,
                            }
                        )
                except Exception as exc:
                    item["failed"].append(
                        {
                            "stage": "pure_generate",
                            "reason": str(exc),
                        }
                    )

    item["success"] = not item["failed"]
    return item


def sync_audio_from_ese(song_data, mode="incremental", workers=2, dry_run=False, include_other=False):
    report = {
        "generated_at": _now_text(),
        "mode": mode,
        "dry_run": dry_run,
        "success": False,
        "repo": {},
        "stats": {},
        "title_collisions": {},
        "normalized_title_collisions": {},
        "skipped_no_title": [],
        "metadata_analysis_skipped": [],
        "skipped_unmatched": [],
        "resolved_duplicate_sources": [],
        "skipped_duplicate_sources": [],
        "skipped_no_outputs": [],
        "songs": [],
    }

    try:
        if mode not in {"full", "incremental"}:
            raise ValueError(f"unsupported mode: {mode}")
        if not TJA2AUDIO_MAIN.exists():
            raise FileNotFoundError(f"tja2audio 不存在: {TJA2AUDIO_MAIN}")

        report["repo"] = _ensure_ese_repo()
        repo_path = Path(report["repo"]["repo_path"])
        mix_existing = _collect_existing_objects(OSS_MIX_AUDIO_PREFIX, object_kind="chart")
        drum_existing = _collect_existing_objects(OSS_DRUM_AUDIO_PREFIX, object_kind="chart")
        pure_existing = _collect_existing_objects(OSS_PURE_AUDIO_PREFIX, object_kind="pure")
        song_indexes = _build_song_match_indexes(song_data, include_other=include_other)
        report["title_collisions"] = song_indexes["title_collisions"]
        report["normalized_title_collisions"] = song_indexes["normalized_collisions"]

        scanned_tja_count = 0
        tja_records = []

        for tja_path in _iter_tja_files(repo_path):
            scanned_tja_count += 1
            tja_record = _build_tja_record(tja_path)
            if tja_record is None:
                report["skipped_no_title"].append({"tja_path": str(tja_path)})
                continue
            tja_records.append(tja_record)

        metadata_matcher = _build_metadata_matcher(repo_path, tja_records)
        report["metadata_analysis_skipped"] = metadata_matcher["skipped"]
        matched_candidates, report["skipped_unmatched"] = (
            _match_songs_with_metadata(
                song_data,
                repo_path,
                metadata_matcher,
                on_shelf_only=True,
                include_other=include_other,
            )
        )
        (
            selected_candidates,
            report["resolved_duplicate_sources"],
            report["skipped_duplicate_sources"],
        ) = _resolve_matched_candidates(matched_candidates)

        manifest_matched_candidates, manifest_skipped_unmatched = (
            _match_songs_with_metadata(
                song_data,
                repo_path,
                metadata_matcher,
                on_shelf_only=False,
            )
        )
        (
            manifest_candidates,
            manifest_resolved_duplicates,
            manifest_skipped_duplicates,
        ) = _resolve_matched_candidates(manifest_matched_candidates)

        final_candidates = []
        for candidate in selected_candidates:
            output_mapping = _build_output_mapping(candidate["tja_path"], candidate["song"])
            if not output_mapping:
                report["skipped_no_outputs"].append(
                    {
                        "song_id": candidate["song"]["id"],
                        "titleja": candidate["titleja"],
                        "tja_path": str(candidate["tja_path"]),
                        "match_strategy": candidate.get("match_strategy"),
                    }
                )
                continue

            missing_mix = {name for name in output_mapping if name not in mix_existing}
            missing_drum = {name for name in output_mapping if name not in drum_existing}
            pure_name = f"{candidate['song']['id']}.mp3"
            missing_pure = {pure_name} if pure_name not in pure_existing else set()
            if mode == "incremental" and not missing_mix and not missing_drum and not missing_pure:
                continue

            candidate["output_mapping"] = output_mapping
            candidate["missing_mix"] = missing_mix
            candidate["missing_drum"] = missing_drum
            candidate["missing_pure"] = missing_pure
            final_candidates.append(candidate)

        workers = int(workers or 1)
        if workers <= 0:
            workers = os.cpu_count() or 1
        workers = max(1, workers)

        if workers == 1:
            for candidate in final_candidates:
                report["songs"].append(_process_candidate(candidate, dry_run=dry_run))
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_process_candidate, candidate, dry_run): candidate
                    for candidate in final_candidates
                }
                for future in as_completed(future_map):
                    report["songs"].append(future.result())

        report["songs"].sort(key=lambda item: int(item["song_id"]))
        uploaded_mix_count = sum(len(item["uploaded_mix"]) for item in report["songs"])
        uploaded_drum_count = sum(len(item["uploaded_drum"]) for item in report["songs"])
        uploaded_pure_count = sum(len(item["uploaded_pure"]) for item in report["songs"])
        failed_song_count = sum(1 for item in report["songs"] if item["failed"])

        if not dry_run:
            for item in report["songs"]:
                mix_existing.update(
                    upload["target"] for upload in item["uploaded_mix"]
                )
                drum_existing.update(
                    upload["target"] for upload in item["uploaded_drum"]
                )

        branch_manifest = build_branch_audio_manifest(
            manifest_candidates,
            drum_existing,
            mix_existing,
            source_revision=report["repo"].get("revision", ""),
        )
        if not dry_run:
            write_branch_audio_manifest(branch_manifest)
        report["branch_audio_manifest"] = {
            "path": str(BRANCH_AUDIO_MANIFEST_PATH),
            "written": not dry_run,
            "stats": branch_manifest["stats"],
            "unmatched_song_count": len(manifest_skipped_unmatched),
            "unmatched_songs": manifest_skipped_unmatched,
            "resolved_duplicate_source_song_count": len(
                manifest_resolved_duplicates
            ),
            "duplicate_source_song_count": len(manifest_skipped_duplicates),
        }

        report["stats"] = {
            "scanned_tja_count": scanned_tja_count,
            "metadata_analysis_skipped_count": len(
                report["metadata_analysis_skipped"]
            ),
            "title_collision_count": len(song_indexes["title_collisions"]),
            "normalized_title_collision_count": len(song_indexes["normalized_collisions"]),
            "matched_song_count": len(final_candidates),
            "resolved_duplicate_source_song_count": len(report["resolved_duplicate_sources"]),
            "duplicate_source_song_count": len(report["skipped_duplicate_sources"]),
            "skipped_no_title_count": len(report["skipped_no_title"]),
            "skipped_unmatched_count": len(report["skipped_unmatched"]),
            "skipped_no_outputs_count": len(report["skipped_no_outputs"]),
            "uploaded_mix_count": uploaded_mix_count,
            "uploaded_drum_count": uploaded_drum_count,
            "uploaded_pure_count": uploaded_pure_count,
            "failed_song_count": failed_song_count,
            "branch_song_count": branch_manifest["stats"]["branchSongCount"],
            "branch_track_count": branch_manifest["stats"]["branchTrackCount"],
            "branch_variant_count": branch_manifest["stats"]["variantCount"],
        }
        report["success"] = True
    except Exception as exc:
        report["error"] = str(exc)
        report["success"] = False

    _write_report(report)
    return report


def _load_song_data():
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "incremental"), default="incremental")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    report = sync_audio_from_ese(
        _load_song_data(),
        mode=args.mode,
        workers=args.workers,
        dry_run=args.dry_run,
    )
    stats = report.get("stats", {})
    print(
        "[ESE][AUDIO] "
        f"success={report.get('success')} "
        f"matched={stats.get('matched_song_count', 0)} "
        f"uploaded_mix={stats.get('uploaded_mix_count', 0)} "
        f"uploaded_drum={stats.get('uploaded_drum_count', 0)} "
        f"uploaded_pure={stats.get('uploaded_pure_count', 0)} "
        f"failed_songs={stats.get('failed_song_count', 0)} "
        f"report={ESE_AUDIO_SYNC_REPORT_PATH}"
    )
    if args.mode == "full":
        if (not report.get("success")) or stats.get("failed_song_count", 0) > 0:
            raise SystemExit(1)
    elif not report.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
