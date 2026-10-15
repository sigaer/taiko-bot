from taiko_bot.offline.paths import root as _runtime_root
import argparse
from datetime import datetime
import hashlib
from html import unescape
import logging
import os
from pathlib import Path
import subprocess
import re
import sys
import time
from urllib.parse import quote, urljoin

from taiko_bot.offline.paths import root
ROOT_DIR = root()

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
import ujson as json
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
try:
    from taiko_bot.offline.audio_missing_mover import (
        build_missing_title_list_from_report,
        move_missing_titles_tja_and_ogg,
    )
except Exception:
    from audio_missing_mover import (
        build_missing_title_list_from_report,
        move_missing_titles_tja_and_ogg,
    )
try:
    from taiko_bot.offline.ese_audio_sync import sync_audio_from_ese
except Exception:
    from ese_audio_sync import sync_audio_from_ese
try:
    from taiko_bot.offline.branch_audio_manifest import BRANCH_AUDIO_MANIFEST_PATH
except Exception:
    from branch_audio_manifest import BRANCH_AUDIO_MANIFEST_PATH
try:
    from taiko_bot.offline.score_line import (
        deduplicate_scoreline_rows,
        rebuild_scoreline_dataset,
    )
except Exception:
    from score_line import deduplicate_scoreline_rows, rebuild_scoreline_dataset
try:
    from taiko_bot.offline.chart_roll_metadata import apply_chart_roll_metadata_overrides
except Exception:
    from chart_roll_metadata import apply_chart_roll_metadata_overrides
try:
    from taiko_bot.offline.tja_roll_sync import audit_song_data, write_audit_report
except Exception:
    from tja_roll_sync import audit_song_data, write_audit_report
try:
    from taiko_bot.offline.song_tja_mapping import (
        DEFAULT_MAPPING_PATH as SONG_TJA_MAPPING_PATH,
        DEFAULT_MAPPING_URL as SONG_TJA_MAPPING_URL,
        load_song_tja_mapping,
        refresh_song_tja_mapping,
    )
except Exception:
    from song_tja_mapping import (
        DEFAULT_MAPPING_PATH as SONG_TJA_MAPPING_PATH,
        DEFAULT_MAPPING_URL as SONG_TJA_MAPPING_URL,
        load_song_tja_mapping,
        refresh_song_tja_mapping,
    )
try:
    from taiko_bot.runtime.player.center.title_catalog import refresh_title_catalog_cache
except Exception:
    from title_catalog import refresh_title_catalog_cache
try:
    from taiko_bot.runtime.player.center.song_title_showcase import clear_song_title_showcase_caches
except Exception:
    from song_title_showcase import clear_song_title_showcase_caches

SONG_DATA_PATH = Path(str(_runtime_root() / 'songs/song_data.json'))
SONG_DATA_RAW_PATH = Path(str(_runtime_root() / 'songs/song_data_raw.json'))
TAIKO_SONG_DATABASE_PATH = Path(str(_runtime_root() / 'songs/taiko_song_database.json'))
RATING_STRUCTURED_WITH_IDS_PATH = Path(
    str(_runtime_root() / 'songs/rating_structured_with_ids.json')
)
FUMENS_BASE_DIR = Path(str(_runtime_root() / 'assets/fumens'))
CONFIG_PATH = Path(str(_runtime_root() / 'config.json'))
TAIKO_WIKI_SONG_URL = "https://taiko.wiki/api/song"
TAIKO_WIKI_BASE_URL = "https://taiko.wiki"
FUMEN_DB_SONG_URL_TMPL = "https://fumen-database.com/song/{song_id}-{diff_level}/"
WIKIWIKI_BASE_URL = "https://wikiwiki.jp/taiko-fumen/"
WIKIWIKI_SOURCE_URL_TMPL = WIKIWIKI_BASE_URL + "?cmd=source&page={page}"
WIKIWIKI_SCORE_CACHE_DIR = Path(str(_runtime_root() / 'output/wiki_score_page_cache'))
OSS_SONG_DATA_PATH = "oss://sigaer/json/song_data.json"
OSS_RATING_STRUCTURED_WITH_IDS_PATH = "oss://sigaer/json/rating_structured_with_ids.json"
OSS_BRANCH_AUDIO_MANIFEST_PATH = "oss://sigaer/json/branch_audio_manifest.json"
OSS_FUMEN_BASE_PATH = "oss://sigaer/fumen"
OSS_DRUM_AUDIO_PREFIX = "oss://sigaer/drum"
OSS_MIX_AUDIO_PREFIX = "oss://sigaer/mix"
OSS_PURE_AUDIO_PREFIX = "oss://sigaer/pure"
AUDIO_MISSING_REPORT_PATH = Path(str(_runtime_root() / 'logs/audio_missing_report.json'))
SCORE_PATH = Path(str(_runtime_root() / 'songs/song_score.json'))
SCORELINE_DATA_PATH = Path(str(_runtime_root() / 'songs/taiko_goku_onis.json'))
TITLE_CATALOG_CACHE_PATH = Path(str(_runtime_root() / 'data/title_catalog_cache.json'))
TITLE_RELATIONS_INPUT_PATH = Path(
    str(_runtime_root() / 'taiko-forum/taiko_viewer/assets/data/title_wikitable.json')
)
TITLE_RELATIONS_OUTPUT_PATH = Path(
    str(_runtime_root() / 'taiko-forum/taiko_viewer/assets/data/title_song_relations.json')
)
TITLE_RELATIONS_SCRIPT_PATH = Path(
    str(_runtime_root() / 'taiko-forum/taiko_viewer/scripts/extract_title_song_relations.py')
)

SHELF_STATUS_UP = 0
SHELF_STATUS_DOWN = 1
SHELF_STATUS_OTHER = 2
OTHER_SONG_ID_START = 100000
DAILY_UPDATE_HOUR = 9
DAILY_UPDATE_MINUTE = 42
SCHEDULE_JOB_TAG = "taiko_song_daily_update"

# 配置日志（可选）
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

DIFF_FOLDER_MAP = {
    "easy": "Kantan",
    "normal": "Futsuu",
    "hard": "Muzukashii",
    "oni": "Oni",
    "ura": "InnerOni",
}

LEVEL_TO_DIFF_TOKEN = {
    1: "EASY",
    2: "NORMAL",
    3: "HARD",
    4: "ONI",
    5: "EDIT",
}

DIFF_KEYS = ("easy", "normal", "hard", "oni", "ura")
DIFF_KEY_BY_LEVEL = {1: "easy", 2: "normal", 3: "hard", 4: "oni", 5: "ura"}
ROLL_METADATA_FIELDS = ("roll_times", "roll_time", "balloons", "balloon_num")

RATING_REFRESH_LEVELS = (4, 5)
WIKIWIKI_SCORE_PAGE_SLUGS = (
    "ポップス",
    "キッズ",
    "アニメ",
    "ボーカロイド™曲",
    "ゲームミュージック",
    "バラエティ",
    "クラシック",
    "ナムコオリジナル",
)

GENRE_TYPE_MAP = {
    "namco": "南梦宫原创音乐",
    "vocaloid": "博歌乐音乐",
    "variety": "综合音乐",
    "kids": "儿童音乐",
    "game": "游戏音乐",
    "pops": "流行音乐",
    "classic": "古典音乐",
    "anime": "动漫音乐",
}


class RatingPageNotFoundError(Exception):
    pass


def _audio_sync_failure_message(audio_sync_report):
    if not isinstance(audio_sync_report, dict):
        return "音源同步报告无效"

    stats = audio_sync_report.get("stats") or {}
    failed_song_count = stats.get("failed_song_count", 0) or 0
    if not audio_sync_report.get("success"):
        detail = audio_sync_report.get("error") or "未知错误"
        return f"{detail} report={AUDIO_MISSING_REPORT_PATH.parent / 'ese_audio_sync_report.json'}"
    if failed_song_count > 0:
        matched_song_count = stats.get("matched_song_count", 0) or 0
        return (
            "存在歌曲音源未成功补齐: "
            f"matched={matched_song_count} failed_song_count={failed_song_count} "
            f"report={AUDIO_MISSING_REPORT_PATH.parent / 'ese_audio_sync_report.json'}"
        )
    return None


def _course_value(courses, diff_key, field):
    if not isinstance(courses, dict):
        return "-"
    course = courses.get(diff_key)
    if not isinstance(course, dict):
        return "-"
    value = course.get(field)
    if value is None:
        return "-"
    return value


def _extract_levels_and_max_combo(db_song):
    courses = db_song.get("courses", {})
    levels = [_course_value(courses, key, "level") for key in DIFF_KEYS]
    max_combo = [_course_value(courses, key, "maxCombo") for key in DIFF_KEYS]
    return levels, max_combo


def _apply_levels_and_max_combo(song_record, levels, max_combo):
    for idx, value in enumerate(levels, start=1):
        song_record[f"level_{idx}"] = value
    song_record["max_combo"] = max_combo
    return song_record


def _normalize_level_availability(value):
    if value is None:
        return "-"
    if isinstance(value, str):
        text = value.strip()
        return text if text else "-"
    try:
        return int(value)
    except Exception:
        return "-"


def _normalize_confirmed_rating_levels(levels):
    confirmed = set()
    if not levels:
        return confirmed
    for level in levels:
        try:
            parsed_level = int(level)
        except Exception:
            continue
        if parsed_level in RATING_REFRESH_LEVELS:
            confirmed.add(parsed_level)
    return confirmed


def _restrict_levels_by_raw_snapshot(song_record, raw_song, preserve_levels=None):
    if not isinstance(song_record, dict) or not isinstance(raw_song, dict):
        return song_record
    preserved = _normalize_confirmed_rating_levels(preserve_levels)
    max_combo = song_record.get("max_combo")
    max_combo_list = list(max_combo) if isinstance(max_combo, list) else None
    for idx in range(1, 6):
        raw_level = _normalize_level_availability(raw_song.get(f"level_{idx}"))
        if raw_level == "-" and idx not in preserved:
            song_record[f"level_{idx}"] = "-"
            if max_combo_list is not None and len(max_combo_list) >= idx:
                max_combo_list[idx - 1] = "-"
    if max_combo_list is not None:
        song_record["max_combo"] = max_combo_list
    return song_record


def _build_bpm_text(db_song):
    bpm = db_song.get("bpm")
    if not isinstance(bpm, dict):
        return "-"
    bpm_min = bpm.get("min")
    bpm_max = bpm.get("max")
    if bpm_min in (None, "") and bpm_max in (None, ""):
        return "-"
    if bpm_min in (None, ""):
        return str(bpm_max)
    if bpm_max in (None, ""):
        return str(bpm_min)
    if bpm_min == bpm_max:
        return str(bpm_min)
    return f"{bpm_min}-{bpm_max}"


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _merge_wahlap_song_without_roll_metadata(new_song, old_song=None):
    """Keep local parser results while refreshing the remaining Wahlap fields."""
    merged = dict(new_song)
    if isinstance(old_song, dict):
        merged["bpm"] = old_song.get("bpm", merged.get("bpm"))
        for field in ROLL_METADATA_FIELDS:
            if field in old_song:
                merged[field] = old_song[field]
            else:
                merged.pop(field, None)
    else:
        for field in ROLL_METADATA_FIELDS:
            merged.pop(field, None)
    return merged


def _build_open_day(db_song):
    added_ms = db_song.get("addedDate")
    if not isinstance(added_ms, (int, float)):
        return "-"
    if added_ms <= 0:
        return "-"
    try:
        return datetime.fromtimestamp(added_ms / 1000).strftime("%m/%d/%Y")
    except Exception:
        return "-"


def _build_down_shelf_song(db_song):
    song_id = int(db_song["songNo"])
    levels, max_combo = _extract_levels_and_max_combo(db_song)
    artists = db_song.get("artists")
    if not isinstance(artists, list):
        artists = []
    version = db_song.get("version")
    if not isinstance(version, list):
        version = []
    title_jp = db_song.get("title") or "-"
    title_fallback = db_song.get("titleEn") or db_song.get("romaji") or title_jp
    mapped_type = _pick_song_type_from_genre(db_song)
    song_record = _apply_levels_and_max_combo(
        {
            "sort": db_song.get("order", 0),
            "id": song_id,
            "open_day": _build_open_day(db_song),
            "type": mapped_type if mapped_type else "-",
            "tag": "-",
            "song_name_jp": title_jp,
            "song_name": title_fallback,
            "subtitle": "-",
            "isPlayed": False,
            "bpm": _build_bpm_text(db_song),
            "version": version,
            "artists": artists,
            "shelf_status": SHELF_STATUS_DOWN,
        },
        levels,
        max_combo,
    )
    return song_record


def _pick_song_type_from_genre(db_song):
    genres = db_song.get("genre")
    if not isinstance(genres, list):
        return None

    normalized = []
    for genre in genres:
        if isinstance(genre, str):
            g = genre.strip().lower()
            if g:
                normalized.append(g)

    for genre in normalized:
        if genre != "namco" and genre in GENRE_TYPE_MAP:
            return GENRE_TYPE_MAP[genre]
    if "namco" in normalized:
        return GENRE_TYPE_MAP["namco"]
    return None


def _extract_other_db_songs(database_data):
    """Return taiko.wiki songs whose songNo is not a pure-digit string."""
    other_songs = []
    for song in database_data:
        if not isinstance(song, dict):
            continue
        song_no = song.get("songNo")
        if not isinstance(song_no, str) or song_no.isdigit():
            continue
        other_songs.append(song)
    other_songs.sort(key=lambda item: str(item.get("songNo") or ""))
    return other_songs


def _apply_other_song_wiki_fields(song_record, db_song):
    """Refresh taiko.wiki-derived fields on an existing 'other song' record."""
    song_record["songNo"] = db_song.get("songNo")
    levels, max_combo = _extract_levels_and_max_combo(db_song)
    artists = db_song.get("artists")
    if not isinstance(artists, list):
        artists = []
    version = db_song.get("version")
    if not isinstance(version, list):
        version = []
    song_record["version"] = version
    song_record["artists"] = artists
    _apply_levels_and_max_combo(song_record, levels, max_combo)
    bpm_text = _build_bpm_text(db_song)
    if bpm_text != "-":
        song_record["bpm"] = bpm_text
    mapped_type = _pick_song_type_from_genre(db_song)
    if mapped_type:
        song_record["type"] = mapped_type
    song_record["shelf_status"] = SHELF_STATUS_OTHER
    return song_record


def _build_other_song(db_song, song_id):
    """Build a song_data record for a non-numeric-songNo taiko.wiki song."""
    title_jp = db_song.get("title") or "-"
    title_fallback = db_song.get("titleEn") or db_song.get("romaji") or title_jp
    song_record = {
        "sort": int(song_id),
        "id": int(song_id),
        "open_day": _build_open_day(db_song),
        "type": "-",
        "tag": "-",
        "song_name_jp": title_jp,
        "song_name": title_fallback,
        "subtitle": "-",
        "isPlayed": False,
        "bpm": "-",
        "version": [],
        "artists": [],
        "shelf_status": SHELF_STATUS_OTHER,
    }
    return _apply_other_song_wiki_fields(song_record, db_song)


def _load_db_bpm_map():
    try:
        resp = requests.get(TAIKO_WIKI_SONG_URL, timeout=30)
        resp.raise_for_status()
        database_data = resp.json()
    except Exception:
        database_data = []

    bpm_map = {}
    for song in database_data:
        song_no = song.get("songNo")
        if not (isinstance(song_no, str) and song_no.isdigit()):
            continue
        bpm_text = _build_bpm_text(song)
        if bpm_text != "-":
            bpm_map[int(song_no)] = bpm_text
    return bpm_map


def _normalize_fumen_url(raw_url):
    if not isinstance(raw_url, str):
        return None
    raw_url = raw_url.strip()
    if not raw_url:
        return None
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return urljoin(TAIKO_WIKI_BASE_URL + "/", raw_url)


def download_missing_fumen_images(filtered_database):
    print("[FUMEN] 开始检查并补全谱面图...")

    for folder in DIFF_FOLDER_MAP.values():
        (FUMENS_BASE_DIR / folder).mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped_exists = 0
    skipped_no_link = 0
    failed = 0
    downloaded_files = []

    with requests.Session() as session:
        for song in filtered_database:
            song_no = song.get("songNo")
            if not (isinstance(song_no, str) and song_no.isdigit()):
                continue

            song_id = int(song_no)
            courses = song.get("courses")
            if not isinstance(courses, dict):
                continue

            for diff_key, folder in DIFF_FOLDER_MAP.items():
                course = courses.get(diff_key)
                if not isinstance(course, dict):
                    continue

                images = course.get("images")
                image_url = None
                if isinstance(images, list) and images:
                    image_url = images[0]

                image_url = _normalize_fumen_url(image_url)
                if not image_url:
                    skipped_no_link += 1
                    continue

                target_path = FUMENS_BASE_DIR / folder / f"{song_id}.png"
                if target_path.exists():
                    skipped_exists += 1
                    continue

                try:
                    resp = session.get(image_url, timeout=30)
                    resp.raise_for_status()
                    if not resp.content:
                        raise ValueError("响应为空")
                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    if content_type and "image" not in content_type:
                        raise ValueError(f"Content-Type 非图片: {content_type}")

                    target_path.write_bytes(resp.content)
                    downloaded += 1
                    downloaded_files.append(target_path)
                    print(
                        f"[FUMEN][DOWNLOADED] id={song_id} diff={diff_key} -> {target_path}"
                    )
                except Exception as e:
                    failed += 1
                    print(
                        f"[FUMEN][FAILED] id={song_id} diff={diff_key} url={image_url} err={e}"
                    )

    print(
        "[FUMEN] 处理完成:"
        f" downloaded={downloaded}, skipped_exists={skipped_exists},"
        f" skipped_no_link={skipped_no_link}, failed={failed}"
    )
    return {
        "downloaded": downloaded,
        "skipped_exists": skipped_exists,
        "skipped_no_link": skipped_no_link,
        "failed": failed,
        "downloaded_files": downloaded_files,
    }


def sync_fumens_to_oss(downloaded_files):
    if not downloaded_files:
        print("[FUMEN][OSS] 无新增谱面，跳过上传")
        return

    print(f"[FUMEN][OSS] 开始上传新增谱面: count={len(downloaded_files)}")
    uploaded = 0
    failed = 0

    for file_path in downloaded_files:
        rel_path = file_path.relative_to(FUMENS_BASE_DIR).as_posix()
        oss_target = f"{OSS_FUMEN_BASE_PATH}/{rel_path}"
        try:
            result = subprocess.run(
                ["ossutil", "cp", str(file_path), oss_target, "-f", "-u"],
                check=True,
                capture_output=True,
                text=True,
            )
            uploaded += 1
            print(f"[FUMEN][OSS][UPLOADED] {file_path} -> {oss_target}")
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if stdout:
                print(f"[FUMEN][OSS][STDOUT]\n{stdout}")
            if stderr:
                print(f"[FUMEN][OSS][STDERR]\n{stderr}")
        except Exception as e:
            failed += 1
            print(f"[FUMEN][OSS][FAILED] {file_path} -> {oss_target}, err={e}")

    print(f"[FUMEN][OSS] 上传完成: uploaded={uploaded}, failed={failed}")


def download_other_song_fumen_images(other_db_songs, id_by_songno):
    """下载"其他歌曲"(非数字 songNo) 的谱面预览图到本地并返回待上传清单。"""
    print("[FUMEN][OTHER] 开始检查并补全其他歌曲谱面图...")

    for folder in DIFF_FOLDER_MAP.values():
        (FUMENS_BASE_DIR / folder).mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped_exists = 0
    skipped_no_link = 0
    skipped_no_id = 0
    failed = 0
    downloaded_files = []

    with requests.Session() as session:
        for song in other_db_songs:
            song_no = song.get("songNo")
            song_id = id_by_songno.get(str(song_no))
            if song_id is None:
                skipped_no_id += 1
                continue
            courses = song.get("courses")
            if not isinstance(courses, dict):
                continue

            for diff_key, folder in DIFF_FOLDER_MAP.items():
                course = courses.get(diff_key)
                if not isinstance(course, dict):
                    continue

                images = course.get("images")
                image_url = None
                if isinstance(images, list) and images:
                    image_url = images[0]

                image_url = _normalize_fumen_url(image_url)
                if not image_url:
                    skipped_no_link += 1
                    continue

                target_path = FUMENS_BASE_DIR / folder / f"{song_id}.png"
                if target_path.exists():
                    skipped_exists += 1
                    continue

                try:
                    resp = session.get(image_url, timeout=30)
                    resp.raise_for_status()
                    if not resp.content:
                        raise ValueError("响应为空")
                    content_type = (resp.headers.get("Content-Type") or "").lower()
                    if content_type and "image" not in content_type:
                        raise ValueError(f"Content-Type 非图片: {content_type}")

                    target_path.write_bytes(resp.content)
                    downloaded += 1
                    downloaded_files.append(target_path)
                    print(
                        f"[FUMEN][OTHER][DOWNLOADED] id={song_id} songNo={song_no} "
                        f"diff={diff_key} -> {target_path}"
                    )
                except Exception as e:
                    failed += 1
                    print(
                        f"[FUMEN][OTHER][FAILED] id={song_id} songNo={song_no} "
                        f"diff={diff_key} url={image_url} err={e}"
                    )

    print(
        "[FUMEN][OTHER] 处理完成:"
        f" downloaded={downloaded}, skipped_exists={skipped_exists},"
        f" skipped_no_link={skipped_no_link}, skipped_no_id={skipped_no_id},"
        f" failed={failed}"
    )
    return {
        "downloaded": downloaded,
        "skipped_exists": skipped_exists,
        "skipped_no_link": skipped_no_link,
        "skipped_no_id": skipped_no_id,
        "failed": failed,
        "downloaded_files": downloaded_files,
    }


def _collect_oss_audio_index(prefix):
    try:
        result = subprocess.run(
            ["ossutil", "ls", prefix, "-s"],
            check=True,
            capture_output=True,
            text=True,
        )
        content = result.stdout or ""
    except Exception as e:
        print(f"[AUDIO][WARN] 无法扫描 {prefix}: {e}")
        return {}

    index = {}
    pattern = re.compile(
        r"^oss://[^/]+/.*/(?P<id>\d+)_(?P<diff>EASY|NORMAL|HARD|ONI|EDIT)(?:_.*)?\.mp3$",
        flags=re.IGNORECASE,
    )
    for raw in content.splitlines():
        line = raw.strip()
        if not line.startswith("oss://"):
            continue
        m = pattern.match(line)
        if not m:
            continue
        sid = int(m.group("id"))
        diff = m.group("diff").upper()
        if sid not in index:
            index[sid] = set()
        index[sid].add(diff)
    return index


def _collect_oss_pure_index(prefix):
    try:
        result = subprocess.run(
            ["ossutil", "ls", prefix, "-s"],
            check=True,
            capture_output=True,
            text=True,
        )
        content = result.stdout or ""
    except Exception as e:
        print(f"[AUDIO][WARN] 无法扫描 {prefix}: {e}")
        return set()

    index = set()
    pattern = re.compile(r"^oss://[^/]+/.*/(?P<id>\d+)\.mp3$", flags=re.IGNORECASE)
    for raw in content.splitlines():
        line = raw.strip()
        if not line.startswith("oss://"):
            continue
        m = pattern.match(line)
        if not m:
            continue
        try:
            index.add(int(m.group("id")))
        except Exception:
            continue
    return index


def _song_level_required(song, level):
    level_value = song.get(f"level_{level}")
    if level_value is None:
        return False
    if isinstance(level_value, str) and level_value.strip() == "-":
        return False
    return True


def _is_song_on_shelf(song):
    status = song.get("shelf_status")
    return status == SHELF_STATUS_UP or status == "未下架"


def _is_down_shelf_status(status):
    return status == SHELF_STATUS_DOWN or status == "已下架" or status == "1"


def check_missing_audio_for_song_data(song_data):
    drum_index = _collect_oss_audio_index(OSS_DRUM_AUDIO_PREFIX)
    mix_index = _collect_oss_audio_index(OSS_MIX_AUDIO_PREFIX)
    pure_index = _collect_oss_pure_index(OSS_PURE_AUDIO_PREFIX)

    missing = []
    drum_missing_count = 0
    mix_missing_count = 0
    pure_missing_song_ids = set()
    checked_count = 0
    checked_song_count = 0
    skipped_down_shelf_song_count = 0
    for song in song_data:
        if not isinstance(song, dict):
            continue
        if not _is_song_on_shelf(song):
            skipped_down_shelf_song_count += 1
            continue
        sid_raw = song.get("id")
        try:
            sid = int(sid_raw)
        except Exception:
            continue
        checked_song_count += 1
        title = song.get("song_name_jp") or song.get("song_name") or f"ID{sid}"
        in_pure = sid in pure_index
        if not in_pure:
            pure_missing_song_ids.add(sid)
        for level, diff_token in LEVEL_TO_DIFF_TOKEN.items():
            if not _song_level_required(song, level):
                continue
            checked_count += 1
            in_drum = diff_token in drum_index.get(sid, set())
            in_mix = diff_token in mix_index.get(sid, set())
            if in_drum and in_mix and in_pure:
                continue
            if not in_drum:
                drum_missing_count += 1
            if not in_mix:
                mix_missing_count += 1
            missing.append(
                {
                    "id": sid,
                    "title": title,
                    "level": level,
                    "difficulty": diff_token,
                    "in_drum": in_drum,
                    "in_mix": in_mix,
                    "in_pure": in_pure,
                }
            )

    print(
        f"[AUDIO] 已检查上架曲目: {checked_song_count}, "
        f"跳过未上架曲目: {skipped_down_shelf_song_count}"
    )
    print(f"[AUDIO] 已检查谱面音频数: {checked_count}")
    print(f"[AUDIO] 缺失条目数: {len(missing)}")
    print(f"[AUDIO] drum 缺失数: {drum_missing_count}")
    print(f"[AUDIO] mix 缺失数: {mix_missing_count}")
    print(f"[AUDIO] pure 缺失歌曲数: {len(pure_missing_song_ids)}")
    for entry in missing:
        missing_sides = []
        if not entry["in_drum"]:
            missing_sides.append("drum")
        if not entry["in_mix"]:
            missing_sides.append("mix")
        if not entry["in_pure"]:
            missing_sides.append("pure")
        print(
            "[AUDIO][MISSING] "
            f"id={entry['id']} title={entry['title']} "
            f"level_{entry['level']}({entry['difficulty']}) "
            f"missing={','.join(missing_sides)}"
        )

    AUDIO_MISSING_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checked_song_count": checked_song_count,
        "skipped_down_shelf_song_count": skipped_down_shelf_song_count,
        "checked_count": checked_count,
        "missing_count": len(missing),
        "missing_drum_count": drum_missing_count,
        "missing_mix_count": mix_missing_count,
        "missing_pure_count": len(pure_missing_song_ids),
        "missing": missing,
    }
    with open(AUDIO_MISSING_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[AUDIO] 缺失报告已写入: {AUDIO_MISSING_REPORT_PATH}")


def _is_level_available(song, level):
    value = song.get(f"level_{level}")
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "-":
        return False
    return True


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _extract_id_from_fumen_url(url):
    if not isinstance(url, str):
        return None
    m = re.search(r"/song/(\d+)(?:-\d+)?/", url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _strip_ura_suffix(title):
    if not isinstance(title, str):
        return ""
    t = title.strip()
    t = re.sub(r"[（(]裏[)）]\s*$", "", t)
    return t.strip()


def _optional_proxy_dict():
    proxy = (
        os.environ.get("MIHOMO_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if not proxy:
        return None
    proxy = str(proxy).strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _extract_chart_datas_from_html(html):
    m = re.search(r"const\s+chart_datas\s*=\s*\{(?P<body>.*?)\};", html, flags=re.S)
    if not m:
        return None
    body = m.group("body")

    def pick(key):
        p = re.search(rf"{key}\s*:\s*['\"](?P<v>.*?)['\"]", body, flags=re.S)
        if not p:
            return None
        return p.group("v").strip()

    return {
        "radar_compound": _to_float(pick("radar_compound")),
        "radar_density_ave": _to_float(pick("radar_density_ave")),
        "radar_density_inst": _to_float(pick("radar_density_inst")),
        "radar_change_hs": _to_float(pick("radar_change_hs")),
        "radar_change_bpm": _to_float(pick("radar_change_bpm")),
        "radar_division": _to_float(pick("radar_division")),
        "song_name": pick("song_name") or "",
    }


def _extract_score_const_from_html(html):
    score = "-"

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        const_elem = soup.select_one("#score_const_origin")
        if const_elem:
            score_text = const_elem.get_text(strip=True)
            parsed = _to_float(score_text, default=-1.0)
            if parsed >= 0:
                score = parsed
    else:
        m = re.search(
            r'id="score_const_origin">\s*([0-9]+(?:\.[0-9]+)?)\s*<', html, flags=re.S
        )
        if m:
            score = _to_float(m.group(1), default="-")

    return score


def _song_chart_sequence_value(song, field, diff_level):
    values = song.get(field)
    if not isinstance(values, list) or not (1 <= diff_level <= len(values)):
        return None
    return values[diff_level - 1]


def _song_chart_max_combo(song, diff_level):
    value = _song_chart_sequence_value(song, "max_combo", diff_level)
    try:
        return int(value)
    except Exception:
        return 0


def _has_local_chart_metadata(song, diff_level):
    if _song_chart_max_combo(song, diff_level) > 0:
        return True

    roll_time = _song_chart_sequence_value(song, "roll_time", diff_level)
    try:
        return float(roll_time) >= 0
    except Exception:
        return False


def _format_roll_time_value(song, diff_level):
    value = _song_chart_sequence_value(song, "roll_time", diff_level)
    seconds = _to_float(value, default=-1.0)
    if seconds < 0:
        return "-"
    return f"{seconds:.3f}秒"


def _format_balloon_num_value(song, diff_level):
    value = _song_chart_sequence_value(song, "balloon_num", diff_level)
    try:
        return int(value)
    except Exception:
        return "-"


def _build_rating_entry(song, diff_level, chart_datas, score_value):
    song_id = int(song.get("id"))
    base_title = song.get("song_name_jp") or song.get("song_name") or f"ID{song_id}"
    chart_title = f"{base_title}(裏)" if diff_level == 5 else str(base_title)
    song_name_cn = song.get("song_name") or str(base_title)

    radar_compound = _to_float(chart_datas.get("radar_compound"))
    radar_density_ave = _to_float(chart_datas.get("radar_density_ave"))
    radar_density_inst = _to_float(chart_datas.get("radar_density_inst"))
    radar_change_hs = _to_float(chart_datas.get("radar_change_hs"))
    radar_change_bpm = _to_float(chart_datas.get("radar_change_bpm"))
    radar_division = _to_float(chart_datas.get("radar_division"))
    rhythm = radar_division + (radar_division / 100.0) * (radar_change_bpm / 100.0) * (
        100.0 - radar_division
    )
    avg = (radar_compound + radar_density_ave + radar_density_inst + rhythm) / 4.0

    score = score_value
    if score == "-":
        score = _to_float(song.get(f"level_{diff_level}"), 0.0)

    entry = {
        "曲名": chart_title,
        "score": score,
        "combo": _song_chart_max_combo(song, diff_level),
        "复合处理": radar_compound,
        "平均密度": radar_density_ave,
        "瞬间密度": radar_density_inst,
        "叩き分け": radar_division,
        "BPM变化": radar_change_bpm,
        "HS变化": radar_change_hs,
        "复杂鱼蛋处理": radar_compound,
        "体力": radar_density_ave,
        "高速处理": radar_density_inst,
        "节奏处理": rhythm,
        "平均": avg,
        "url": FUMEN_DB_SONG_URL_TMPL.format(song_id=song_id, diff_level=diff_level),
        "bpm": song.get("bpm", "-"),
        "roll_time": _format_roll_time_value(song, diff_level),
        "balloon_num": _format_balloon_num_value(song, diff_level),
        "level": diff_level,
        "id": song_id,
        "song_name_cn": song_name_cn,
    }
    return chart_title, entry


def _fill_missing_rating_song_ids(rating_songs, song_data):
    id_to_song = {}
    title_to_id = {}
    for song in song_data:
        if not isinstance(song, dict):
            continue
        try:
            sid = int(song.get("id"))
        except Exception:
            continue
        id_to_song[sid] = song
        jp = str(song.get("song_name_jp") or "").strip()
        cn = str(song.get("song_name") or "").strip()
        if jp:
            title_to_id[jp] = sid
            title_to_id[f"{jp}(裏)"] = sid
        if cn:
            title_to_id[cn] = sid
            title_to_id[f"{cn}(裏)"] = sid

    updated = 0
    for key, info in rating_songs.items():
        if not isinstance(info, dict):
            continue
        sid = info.get("id")
        valid = True
        try:
            valid = int(sid) > 0
        except Exception:
            valid = False
        if valid:
            continue

        parsed_id = _extract_id_from_fumen_url(info.get("url"))
        if parsed_id is None:
            title = str(info.get("曲名") or key)
            parsed_id = title_to_id.get(title)
            if parsed_id is None:
                parsed_id = title_to_id.get(_strip_ura_suffix(title))
        if parsed_id is None:
            continue

        info["id"] = int(parsed_id)
        song_ref = id_to_song.get(int(parsed_id))
        if song_ref:
            info["song_name_cn"] = song_ref.get("song_name") or song_ref.get(
                "song_name_jp"
            )
        updated += 1

    return updated


def _build_existing_rating_pair_index(rating_songs):
    existing_pairs = {}
    for info in rating_songs.values():
        if not isinstance(info, dict):
            continue
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        if lvl in RATING_REFRESH_LEVELS:
            existing_pairs[(sid, lvl)] = str(info.get("曲名") or "")
    return existing_pairs


def _refresh_rating_song_local_metadata(rating_songs, song_data):
    song_by_id = {}
    for song in song_data:
        if not isinstance(song, dict):
            continue
        try:
            sid = int(song.get("id"))
        except Exception:
            continue
        song_by_id[sid] = song

    refreshed = 0
    for info in rating_songs.values():
        if not isinstance(info, dict):
            continue
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        song = song_by_id.get(sid)
        if not song:
            continue

        updated = False
        combo = _song_chart_max_combo(song, lvl)
        if info.get("combo") != combo:
            info["combo"] = combo
            updated = True

        bpm = song.get("bpm", "-")
        if info.get("bpm") != bpm:
            info["bpm"] = bpm
            updated = True

        roll_time = _format_roll_time_value(song, lvl)
        if info.get("roll_time") != roll_time:
            info["roll_time"] = roll_time
            updated = True

        balloon_num = _format_balloon_num_value(song, lvl)
        if info.get("balloon_num") != balloon_num:
            info["balloon_num"] = balloon_num
            updated = True

        if updated:
            refreshed += 1
    return refreshed


def _load_score_confirmed_rating_levels():
    if not SCORE_PATH.exists():
        return {}
    try:
        payload = json.load(open(SCORE_PATH, "r", encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    confirmed_by_id = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            sid = int(row.get("id"))
            level = int(row.get("level"))
        except Exception:
            continue
        if level not in RATING_REFRESH_LEVELS:
            continue
        confirmed_by_id.setdefault(sid, set()).add(level)
    return confirmed_by_id


def _collect_rating_target_pairs(song_data, score_confirmed_levels_by_id=None):
    confirmed_by_id = score_confirmed_levels_by_id or {}
    target_pairs = []
    for song in song_data:
        if not isinstance(song, dict):
            continue
        try:
            sid = int(song.get("id"))
        except Exception:
            continue
        if sid >= OTHER_SONG_ID_START:
            continue
        candidate_levels = {
            lvl
            for lvl in _normalize_confirmed_rating_levels(confirmed_by_id.get(sid))
            if _has_local_chart_metadata(song, lvl)
        }
        for lvl in RATING_REFRESH_LEVELS:
            if not _is_level_available(song, lvl):
                continue
            candidate_levels.add(lvl)
        for lvl in sorted(candidate_levels):
            target_pairs.append((sid, lvl))
    target_pairs.sort()
    return target_pairs


def _remove_rating_entry_by_pair(rating_songs, pair_to_key, pair):
    key = pair_to_key.pop(pair, None)
    if key and key in rating_songs:
        rating_songs.pop(key, None)
        return key
    return None


def _fetch_remote_rating_entry(session, song, sid, lvl):
    url = FUMEN_DB_SONG_URL_TMPL.format(song_id=sid, diff_level=lvl)
    resp = session.get(url, timeout=30)
    if resp.status_code == 404:
        raise RatingPageNotFoundError("HTTP 404")
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code}")
    html = resp.text
    if "404エラー用ページ" in html:
        raise RatingPageNotFoundError("页面不存在(404模板)")
    chart_datas = _extract_chart_datas_from_html(html)
    if not chart_datas:
        raise ValueError("未找到 chart_datas")
    score_value = _extract_score_const_from_html(html)
    key, entry = _build_rating_entry(song, lvl, chart_datas, score_value)
    return url, key, entry


def sync_rating_structured_with_song_data(song_data):
    if not RATING_STRUCTURED_WITH_IDS_PATH.exists():
        print(f"[RATING][WARN] 文件不存在: {RATING_STRUCTURED_WITH_IDS_PATH}")
        return

    payload = json.load(open(RATING_STRUCTURED_WITH_IDS_PATH, "r", encoding="utf-8"))
    rating_songs = payload.get("songs")
    if not isinstance(rating_songs, dict):
        raise ValueError("rating_structured_with_ids.json 的 songs 字段不是 dict")

    filled_id_count = _fill_missing_rating_song_ids(rating_songs, song_data)
    if filled_id_count > 0:
        print(f"[RATING] 已补全缺失 id: {filled_id_count}")
    local_meta_refreshed = _refresh_rating_song_local_metadata(rating_songs, song_data)
    if local_meta_refreshed > 0:
        print(f"[RATING] 已按 song_data 刷新本地谱面信息: {local_meta_refreshed}")

    pair_to_key = _build_existing_rating_pair_index(rating_songs)
    score_confirmed_levels_by_id = _load_score_confirmed_rating_levels()
    target_pairs = _collect_rating_target_pairs(
        song_data, score_confirmed_levels_by_id=score_confirmed_levels_by_id
    )
    target_pair_set = set(target_pairs)
    stale_local_pairs = [
        pair for pair in pair_to_key.keys() if pair not in target_pair_set
    ]

    print(
        f"[RATING] 开始全量刷新 level={','.join(map(str, RATING_REFRESH_LEVELS))}: "
        f"target={len(target_pairs)}, stale_local={len(stale_local_pairs)}"
    )
    if not target_pairs and filled_id_count == 0 and not stale_local_pairs:
        print("[RATING] 无需更新")
        return

    song_by_id = {}
    for song in song_data:
        if not isinstance(song, dict):
            continue
        try:
            sid = int(song.get("id"))
        except Exception:
            continue
        song_by_id[sid] = song

    refreshed = 0
    created = 0
    preserved_not_found = 0
    preserved_stale_local = 0
    renamed = 0
    failed = 0
    proxies = _optional_proxy_dict()
    if proxies:
        print(f"[RATING] 使用代理请求 fumen-database: {proxies.get('http')}")

    with requests.Session() as session:
        if proxies:
            session.proxies.update(proxies)
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
                )
            }
        )
        for index, (sid, lvl) in enumerate(target_pairs, start=1):
            song = song_by_id.get(sid)
            if not song:
                failed += 1
                print(f"[RATING][FAILED] id={sid} level={lvl} 原曲目不存在")
                continue
            try:
                url, key, entry = _fetch_remote_rating_entry(session, song, sid, lvl)
                pair = (sid, lvl)
                old_key = pair_to_key.get(pair)
                existed = old_key in rating_songs if old_key else False
                if old_key and old_key != key:
                    rating_songs.pop(old_key, None)
                    renamed += 1
                rating_songs[key] = entry
                pair_to_key[pair] = key
                if existed:
                    refreshed += 1
                else:
                    created += 1
                    print(f"[RATING][ADDED] id={sid} level={lvl} key={key} url={url}")
                if index % 100 == 0:
                    print(
                        f"[RATING][PROGRESS] done={index}/{len(target_pairs)} "
                        f"refreshed={refreshed} added={created} "
                        f"preserved_not_found={preserved_not_found} failed={failed}"
                    )
                time.sleep(0.1)
            except RatingPageNotFoundError as e:
                existing_key = pair_to_key.get((sid, lvl))
                if existing_key and existing_key in rating_songs:
                    preserved_not_found += 1
                    print(
                        f"[RATING][PRESERVED] id={sid} level={lvl} key={existing_key} "
                        f"reason={e}"
                    )
                else:
                    print(
                        f"[RATING][SKIPPED] id={sid} level={lvl} url={FUMEN_DB_SONG_URL_TMPL.format(song_id=sid, diff_level=lvl)} "
                        f"reason={e}"
                    )
            except Exception as e:
                failed += 1
                print(
                    f"[RATING][FAILED] id={sid} level={lvl} "
                    f"url={FUMEN_DB_SONG_URL_TMPL.format(song_id=sid, diff_level=lvl)} err={e}"
                )

    for pair in stale_local_pairs:
        preserved_key = pair_to_key.get(pair)
        if preserved_key and preserved_key in rating_songs:
            preserved_stale_local += 1
            sid, lvl = pair
            print(
                f"[RATING][PRESERVED_LOCAL] id={sid} level={lvl} key={preserved_key} "
                f"reason=曲库已无该谱面，保留历史数据"
            )

    local_meta_refreshed = _refresh_rating_song_local_metadata(rating_songs, song_data)
    if local_meta_refreshed > 0:
        print(f"[RATING] 远程刷新后再次校正本地谱面信息: {local_meta_refreshed}")

    payload["songs"] = rating_songs
    with open(RATING_STRUCTURED_WITH_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(
        f"[RATING] 已写回本地: {RATING_STRUCTURED_WITH_IDS_PATH}, "
        f"filled_id={filled_id_count}, refreshed={refreshed}, added={created}, "
        f"renamed={renamed}, preserved_not_found={preserved_not_found}, "
        f"preserved_stale_local={preserved_stale_local}, failed={failed}"
    )

    subprocess.run(
        [
            "ossutil",
            "cp",
            "-f",
            str(RATING_STRUCTURED_WITH_IDS_PATH),
            OSS_RATING_STRUCTURED_WITH_IDS_PATH,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    print(
        f"[RATING][OSS] 已同步: {RATING_STRUCTURED_WITH_IDS_PATH} -> "
        f"{OSS_RATING_STRUCTURED_WITH_IDS_PATH}"
    )


def _score_title_base(text):
    normalized = unescape(str(text or "")).strip()
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("〜", "～").replace("~", "～")
    normalized = normalized.replace("＆", "&").replace("＠", "@")
    normalized = normalized.replace("！", "!").replace("？", "?")
    normalized = normalized.replace("／", "/")
    for src in ("‐", "‑", "‒", "–", "—", "―", "－", "ｰ"):
        normalized = normalized.replace(src, "-")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("(裏譜面)", "").replace("(裏)", "")
    return normalized.lower()


def _score_row_identity_key(title, level):
    return (_score_title_base(title), int(level))


def _optional_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _cache_is_fresh_today(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date() == datetime.now().date()
    except Exception:
        return False


def _score_page_source_text(session, page, *, retries=4, sleep_seconds=1.0):
    WIKIWIKI_SCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_name = quote(page, safe="").replace("%", "_") + ".txt"
    cache_path = WIKIWIKI_SCORE_CACHE_DIR / cache_name
    if cache_path.exists() and _cache_is_fresh_today(cache_path):
        print(f"[SCORE][CACHE] 使用当日缓存源码: page={page}")
        return cache_path.read_text(encoding="utf-8")
    url = WIKIWIKI_SOURCE_URL_TMPL.format(page=quote(page, safe=""))
    last_error = None
    direct_session = requests.Session()
    direct_session.trust_env = False
    direct_session.headers.update(session.headers)
    session_variants = []
    active_proxy = session.proxies.get("https") or session.proxies.get("http")
    if active_proxy:
        session_variants.append(("proxy", session))
    session_variants.append(("direct", direct_session))
    try:
        for attempt in range(1, retries + 1):
            for mode, request_session in session_variants:
                try:
                    response = request_session.get(url, timeout=30)
                    response.raise_for_status()
                    html = response.text
                    if BeautifulSoup is not None:
                        soup = BeautifulSoup(html, "html.parser")
                        source_block = soup.select_one("pre#source code") or soup.select_one("pre#source")
                        if source_block is not None:
                            text = unescape(source_block.get_text("\n", strip=False))
                            cache_path.write_text(text, encoding="utf-8")
                            if mode != "proxy" and active_proxy:
                                print(f"[SCORE][FALLBACK] page={page} via={mode}")
                            return text
                    m = re.search(
                        r'<pre id="source"[^>]*><code>(?P<body>.*?)</code></pre>',
                        html,
                        flags=re.S,
                    )
                    if m:
                        text = unescape(re.sub(r"<[^>]+>", "", m.group("body")))
                        cache_path.write_text(text, encoding="utf-8")
                        if mode != "proxy" and active_proxy:
                            print(f"[SCORE][FALLBACK] page={page} via={mode}")
                        return text
                    raise ValueError(f"未能提取 wiki 源码: {page}")
                except Exception as exc:
                    last_error = exc
            if attempt >= retries:
                break
            time.sleep(max(sleep_seconds * attempt, 10.0 if "429" in str(last_error) else 0.0))
    finally:
        direct_session.close()
    if cache_path.exists():
        print(f"[SCORE][CACHE] 使用缓存源码: page={page}")
        return cache_path.read_text(encoding="utf-8")
    raise RuntimeError(f"failed to fetch wiki source {page}: {last_error}") from last_error


def _wiki_page_base_path(page):
    return str(page or "").split("#", 1)[0]


def _wiki_page_html(session, page, *, retries=4, sleep_seconds=1.0):
    page = _wiki_page_base_path(page)
    WIKIWIKI_SCORE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_name = f"{hashlib.md5(page.encode('utf-8')).hexdigest()}.page.html"
    cache_path = WIKIWIKI_SCORE_CACHE_DIR / cache_name
    if cache_path.exists() and _cache_is_fresh_today(cache_path):
        print(f"[SCORE][CACHE] 使用当日详情缓存: page={page}")
        return cache_path.read_text(encoding="utf-8")

    url = urljoin(WIKIWIKI_BASE_URL, quote(page, safe="/"))
    last_error = None
    direct_session = requests.Session()
    direct_session.trust_env = False
    direct_session.headers.update(session.headers)
    session_variants = [("direct", direct_session)]
    active_proxy = session.proxies.get("https") or session.proxies.get("http")
    if active_proxy:
        session_variants.append(("proxy", session))
    try:
        for attempt in range(1, retries + 1):
            for mode, request_session in session_variants:
                try:
                    response = request_session.get(url, timeout=30)
                    response.raise_for_status()
                    html = response.text
                    cache_path.write_text(html, encoding="utf-8")
                    if mode != "proxy" and active_proxy:
                        print(f"[SCORE][DETAIL][FALLBACK] page={page} via={mode}")
                    return html
                except Exception as exc:
                    last_error = exc
            if attempt >= retries:
                break
            time.sleep(max(sleep_seconds * attempt, 10.0 if "429" in str(last_error) else 0.0))
    finally:
        direct_session.close()

    if cache_path.exists():
        print(f"[SCORE][CACHE] 使用详情缓存: page={page}")
        return cache_path.read_text(encoding="utf-8")
    raise RuntimeError(f"failed to fetch wiki detail page {page}: {last_error}") from last_error


def _split_wiki_table_line(line):
    row = str(line or "").strip()
    if not row.startswith("|"):
        return []
    if row.endswith("|h") or row.endswith("|c"):
        row = row[:-2]
    if row.endswith("|"):
        row = row[:-1]
    if row.startswith("|"):
        row = row[1:]
    return [cell.strip() for cell in row.split("|")]


def _cleanup_wiki_cell(text):
    cleaned = unescape(str(text or ""))
    cleaned = re.sub(r"\(\(.*?\)\)", "", cleaned)
    cleaned = re.sub(r"BGCOLOR\([^)]*\):", "", cleaned)
    cleaned = re.sub(r"COLOR\([^)]*\):", "", cleaned)
    cleaned = re.sub(r"&aname\([^)]*\);?", "", cleaned)
    cleaned = cleaned.replace("&br;", " ")
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = cleaned.replace("''", "")
    cleaned = cleaned.replace("~", "")
    cleaned = re.sub(r"&nobr\{(.*?)\};", r"\1", cleaned)
    return cleaned.strip()


def _cleanup_wiki_cell_keep_notes(text):
    cleaned = unescape(str(text or ""))
    cleaned = re.sub(r"BGCOLOR\([^)]*\):", "", cleaned)
    cleaned = re.sub(r"COLOR\([^)]*\):", "", cleaned)
    cleaned = re.sub(r"&aname\([^)]*\);?", "", cleaned)
    cleaned = cleaned.replace("&br;", " ")
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = cleaned.replace("''", "")
    cleaned = cleaned.replace("~", "")
    cleaned = re.sub(r"&nobr\{(.*?)\};", r"\1", cleaned)
    return cleaned.strip()


def _extract_wiki_title(cell):
    cleaned = _cleanup_wiki_cell(cell)
    link_match = re.search(r"\[\[(?P<label>.*?)(?:>.*?)?\]\]", cleaned)
    title = link_match.group("label") if link_match else cleaned
    return title.strip()


def _extract_wiki_link_path(cell):
    text = str(cell or "")
    link_match = re.search(r"\[\[(?P<label>.*?)(?:>(?P<path>.*?))?\]\]", text)
    if not link_match:
        return None
    raw_path = (link_match.group("path") or link_match.group("label") or "").strip()
    raw_path = unescape(raw_path)
    raw_path = raw_path.lstrip("/")
    if not raw_path or raw_path == "収録曲/おに/":
        return None
    return raw_path


def _parse_wiki_int(cell):
    cleaned = _cleanup_wiki_cell(cell)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    m = re.search(r"\d[\d,]*", cleaned)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None


def _parse_wiki_score_tenjo(cell):
    cleaned = _cleanup_wiki_cell_keep_notes(cell)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    alt_match = re.search(r"除いた場合は(?P<score>\d[\d,]*)", cleaned)
    if alt_match:
        try:
            return int(alt_match.group("score").replace(",", ""))
        except Exception:
            pass
    return _parse_wiki_int(cleaned)


def _parse_wiki_float(cell):
    m = re.search(r"\d+(?:\.\d+)?", _cleanup_wiki_cell(cell))
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _parse_wiki_score_rows(source_text, source_page):
    rows = []
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or not line.startswith("|"):
            continue
        cells = _split_wiki_table_line(line)
        if len(cells) < 5:
            continue
        if "[[" not in cells[0]:
            continue
        title = _extract_wiki_title(cells[0])
        if not title or title in {"曲名", "''曲名''"}:
            continue
        goku_score = _parse_wiki_int(cells[2])
        if goku_score is None:
            continue
        level = 5 if "裏譜面" in title else 4
        tenjo_score = _parse_wiki_score_tenjo(cells[1])
        if tenjo_score is None:
            tenjo_score = goku_score
        roll_note = _cleanup_wiki_cell(cells[3])
        speed_note = _cleanup_wiki_cell(cells[4])
        roll_required = 0 if ("精度曲" in roll_note or "完全精度曲" in roll_note) else (_parse_wiki_int(cells[3]) or 0)
        roll_speed_ips = None if ("精度曲" in speed_note or "完全精度曲" in speed_note or not speed_note) else _parse_wiki_float(cells[4])
        rows.append(
            {
                "title": title,
                "level": level,
                "tenjo_score": tenjo_score,
                "goku_score": goku_score,
                "roll_required": roll_required,
                "roll_speed_ips": roll_speed_ips,
                "source_page": source_page,
                "source_roll_note": roll_note,
                "detail_page": _extract_wiki_link_path(cells[0]),
            }
        )
    return rows


def _expand_html_table(table):
    expanded_rows = []
    pending = {}
    max_cols = 0
    for tr in table.select("tr"):
        row = []
        col = 0
        cells = tr.find_all(["th", "td"], recursive=False)
        cell_index = 0
        while cell_index < len(cells) or pending:
            while col in pending:
                text, remaining = pending[col]
                row.append(text)
                if remaining <= 1:
                    pending.pop(col, None)
                else:
                    pending[col] = (text, remaining - 1)
                col += 1
            if cell_index >= len(cells):
                if not pending:
                    break
                next_cols = sorted(k for k in pending if k > col)
                if not next_cols:
                    break
                while col < next_cols[0]:
                    row.append("")
                    col += 1
                continue
            cell = cells[cell_index]
            cell_index += 1
            text = cell.get_text(" ", strip=True)
            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except Exception:
                rowspan = 1
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
            except Exception:
                colspan = 1
            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
        max_cols = max(max_cols, len(row))
        expanded_rows.append(row)
    return [row + [""] * (max_cols - len(row)) for row in expanded_rows]


def _parse_score_detail_rows_from_html(html):
    if BeautifulSoup is None:
        raise RuntimeError("bs4 不可用，无法解析 wiki 详情页")

    soup = BeautifulSoup(html, "html.parser")
    target_grid = None
    for table in soup.select("table"):
        grid = _expand_html_table(table)
        header_blob = " ".join(" ".join(row[:10]) for row in grid[:4])
        if "バージョン" in header_blob and "初項" in header_blob and "天井スコア" in header_blob:
            target_grid = grid
            break

    if target_grid is None:
        return []

    header_row = None
    for row in target_grid:
        header_text = " ".join(str(cell or "") for cell in row[:12])
        if "バージョン" in header_text and "初項" in header_text and "天井スコア" in header_text:
            header_row = row
            break
    if header_row is None:
        return []

    tenjo_score_idx = next(
        (idx for idx, cell in enumerate(header_row) if "天井スコア" in str(cell or "")),
        5,
    )
    initial_points_idx = next(
        (idx for idx, cell in enumerate(header_row) if "初項" in str(cell or "")),
        7,
    )

    rows = []
    last_primary_version = ""
    last_secondary_version = ""
    for row in target_grid:
        if len(row) <= tenjo_score_idx:
            continue
        header_text = " ".join(str(cell or "") for cell in row[:10])
        if "バージョン" in header_text and "初項" in header_text:
            continue

        tenjo_score = None
        for idx in (tenjo_score_idx, tenjo_score_idx + 1):
            if idx >= len(row):
                continue
            cell_text = str(row[idx] or "")
            if "点" not in cell_text:
                continue
            tenjo_score = _parse_wiki_int(cell_text)
            if tenjo_score is not None:
                break
        if tenjo_score is None:
            continue

        primary_version = str(row[0] or "").strip()
        secondary_version = str(row[1] or "").strip()
        if primary_version:
            last_primary_version = primary_version
        else:
            primary_version = last_primary_version
        if secondary_version:
            last_secondary_version = secondary_version
        else:
            secondary_version = last_secondary_version

        initial_cell = row[initial_points_idx] if initial_points_idx < len(row) else ""
        initial_points = _parse_wiki_int(initial_cell) if "点" in str(initial_cell or "") else None
        selected_version = primary_version or secondary_version or None
        rows.append(
            {
                "selected_version": selected_version,
                "tenjo_score": tenjo_score,
                "initial_points": initial_points,
                "row_index": len(rows),
            }
        )
    return rows


def _fetch_score_detail_metadata(session, title, tenjo_score, detail_page=None):
    page = detail_page or f"収録曲/おに/{title}"
    html = _wiki_page_html(session, page, sleep_seconds=1.5)
    detail_rows = _parse_score_detail_rows_from_html(html)
    matches = [
        row
        for row in detail_rows
        if _safe_int(row.get("tenjo_score"), 0) == _safe_int(tenjo_score, 0)
    ]
    if not matches:
        fallback_rows = [
            row
            for row in detail_rows
            if _safe_int(row.get("initial_points"), 0) > 0
            and not re.search(r"真打|モード", str(row.get("selected_version") or ""))
        ]
        if not fallback_rows:
            fallback_rows = [
                row for row in detail_rows if _safe_int(row.get("initial_points"), 0) > 0
            ]
        if not fallback_rows:
            return None
        fallback_rows.sort(
            key=lambda row: (
                1 if "AC16" in str(row.get("selected_version") or "") else 0,
                _safe_int(row.get("row_index"), 0),
            )
        )
        picked = fallback_rows[-1]
        return {
            "selected_version": picked.get("selected_version"),
            "initial_points": _optional_int(picked.get("initial_points")),
        }

    matches.sort(
        key=lambda row: (
            1 if _safe_int(row.get("initial_points"), 0) > 0 else 0,
            1 if row.get("selected_version") else 0,
            _safe_int(row.get("row_index"), 0),
        )
    )
    picked = matches[-1]
    return {
        "selected_version": picked.get("selected_version"),
        "initial_points": _optional_int(picked.get("initial_points")),
    }


def _build_score_detail_page_index():
    index = {}
    for slug in WIKIWIKI_SCORE_PAGE_SLUGS:
        page = f"作品/新AC/極スコア/おに/{slug}"
        cache_name = quote(page, safe="").replace("%", "_") + ".txt"
        cache_path = WIKIWIKI_SCORE_CACHE_DIR / cache_name
        if not cache_path.exists():
            continue
        try:
            source_text = cache_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for row in _parse_wiki_score_rows(source_text, slug):
            detail_page = row.get("detail_page")
            if not detail_page:
                continue
            index[_score_row_identity_key(row.get("title"), row.get("level"))] = detail_page
    return index


def _write_song_score_rows(rows):
    with open(SCORE_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")


def backfill_song_score_detail_metadata(*, limit=None, sleep_seconds=0.2, skip_dual_titles=False):
    if not SCORE_PATH.exists():
        return {
            "checked": 0,
            "updated": 0,
            "failed": 0,
        }

    rows = json.load(open(SCORE_PATH, "r", encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("song_score.json 不是列表")

    targets = []
    detail_page_index = _build_score_detail_page_index()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if skip_dual_titles and str(row.get("title") or "").startswith("【双打】"):
            continue
        if _safe_int(row.get("initial_points"), 0) > 0 and row.get("selected_version"):
            continue
        if not row.get("title") or _safe_int(row.get("tenjo_score"), 0) <= 0:
            continue
        targets.append(row)

    if limit is not None:
        targets = targets[: max(0, int(limit))]

    updated = 0
    failed = 0
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            )
        }
    )
    try:
        for index, row in enumerate(targets, start=1):
            try:
                meta = _fetch_score_detail_metadata(
                    session,
                    row["title"],
                    row["tenjo_score"],
                    detail_page=detail_page_index.get(
                        _score_row_identity_key(row.get("title"), row.get("level"))
                    ),
                )
                if meta is None:
                    failed += 1
                    print(
                        f"[SCORE][DETAIL][MISS] title={row['title']} "
                        f"tenjo={row['tenjo_score']}"
                    )
                else:
                    row_updated = False
                    if _safe_int(meta.get("initial_points"), 0) > 0 and _safe_int(
                        row.get("initial_points"), 0
                    ) <= 0:
                        row["initial_points"] = int(meta["initial_points"])
                        row_updated = True
                    if meta.get("selected_version") and not row.get("selected_version"):
                        row["selected_version"] = meta["selected_version"]
                        row_updated = True
                    if row_updated:
                        updated += 1
                        print(
                            f"[SCORE][DETAIL][UPDATED] title={row['title']} "
                            f"tenjo={row['tenjo_score']} initial={row.get('initial_points')} "
                            f"version={row.get('selected_version')}"
                        )
                if index % 25 == 0:
                    _write_song_score_rows(rows)
                    print(
                        f"[SCORE][DETAIL][PROGRESS] checked={index}/{len(targets)} "
                        f"updated={updated} failed={failed}"
                    )
                time.sleep(max(0.0, float(sleep_seconds)))
            except Exception as exc:
                failed += 1
                print(
                    f"[SCORE][DETAIL][FAILED] title={row.get('title')} "
                    f"tenjo={row.get('tenjo_score')} err={exc}"
                )
    finally:
        session.close()

    _write_song_score_rows(rows)
    print(
        f"[SCORE][DETAIL] 已回填: checked={len(targets)} updated={updated} failed={failed}"
    )
    return {
        "checked": len(targets),
        "updated": updated,
        "failed": failed,
    }


def _score_row_needs_detail_refresh(existing, parsed):
    if not isinstance(existing, dict):
        return True
    if _safe_int(existing.get("tenjo_score"), 0) != _safe_int(parsed.get("tenjo_score"), 0):
        return True
    if _safe_int(existing.get("goku_score"), 0) != _safe_int(parsed.get("goku_score"), 0):
        return True
    if _safe_int(existing.get("roll_required"), 0) != _safe_int(parsed.get("roll_required"), 0):
        return True
    existing_speed = existing.get("roll_speed_ips")
    parsed_speed = parsed.get("roll_speed_ips")
    if _to_float(existing_speed, -1.0) != _to_float(parsed_speed, -1.0):
        return True
    if _safe_int(existing.get("initial_points"), 0) <= 0:
        return True
    if not existing.get("selected_version"):
        return True
    return False


def _build_song_score_song_index(song_data):
    index = {}
    for song in song_data:
        if not isinstance(song, dict):
            continue
        try:
            sid = int(song.get("id"))
        except Exception:
            continue
        for level in RATING_REFRESH_LEVELS:
            for title in (song.get("song_name_jp"), song.get("song_name")):
                if not title:
                    continue
                actual = str(title)
                if level == 5:
                    index.setdefault(_score_row_identity_key(f"{actual}(裏譜面)", level), (sid, song))
                    index.setdefault(_score_row_identity_key(f"{actual}(裏)", level), (sid, song))
                else:
                    index.setdefault(_score_row_identity_key(actual, level), (sid, song))
    return index


def _build_existing_song_score_index(rows):
    index = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            level = int(row.get("level"))
        except Exception:
            continue
        key = _score_row_identity_key(row.get("title"), level)
        index[key] = row
    return index


def sync_song_score_with_wiki(song_data):
    proxies = _optional_proxy_dict()
    if proxies:
        print(f"[SCORE] 使用代理请求 wikiwiki: {proxies.get('http')}")

    existing_rows = []
    if SCORE_PATH.exists():
        try:
            payload = json.load(open(SCORE_PATH, "r", encoding="utf-8"))
            if isinstance(payload, list):
                existing_rows = payload
        except Exception:
            existing_rows = []

    existing_index = _build_existing_song_score_index(existing_rows)
    song_index = _build_song_score_song_index(song_data)
    kept_existing_keys = set()
    merged_rows = []

    with requests.Session() as session:
        if proxies:
            session.proxies.update(proxies)
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/133.0.0.0 Safari/537.36"
                )
            }
        )
        parsed_rows = []
        for slug in WIKIWIKI_SCORE_PAGE_SLUGS:
            page = f"作品/新AC/極スコア/おに/{slug}"
            try:
                source_text = _score_page_source_text(session, page)
                parsed_rows.extend(_parse_wiki_score_rows(source_text, slug))
            except Exception as exc:
                print(f"[SCORE][WARN] 跳过页面: page={page} err={exc}")

    parsed_by_key = {}
    parsed_order = []
    for parsed in parsed_rows:
        key = _score_row_identity_key(parsed["title"], parsed["level"])
        if key not in parsed_by_key:
            parsed_order.append(key)
        parsed_by_key[key] = parsed

    resolved = 0
    detail_attempted = 0
    detail_refreshed = 0
    detail_failed = 0
    for key in parsed_order:
        parsed = parsed_by_key[key]
        existing = existing_index.get(key)
        if existing is not None:
            kept_existing_keys.add(key)
        song_ref = song_index.get(key)

        if song_ref is not None:
            song_id, song = song_ref
            max_combo = _song_chart_max_combo(song, parsed["level"])
        else:
            song_id = _safe_int(existing.get("id"), 0) if isinstance(existing, dict) else 0
            song = None
            max_combo = _optional_int(existing.get("max_combo")) if isinstance(existing, dict) else None

        if (max_combo or 0) <= 0 and isinstance(existing, dict):
            max_combo = _optional_int(existing.get("max_combo"))

        selected_version = existing.get("selected_version") if isinstance(existing, dict) else None
        initial_points = (
            _optional_int(existing.get("initial_points")) if isinstance(existing, dict) else None
        )

        if _score_row_needs_detail_refresh(existing, parsed):
            detail_attempted += 1
            try:
                detail_meta = _fetch_score_detail_metadata(
                    session,
                    parsed["title"],
                    parsed["tenjo_score"],
                    detail_page=parsed.get("detail_page"),
                )
            except Exception as exc:
                detail_failed += 1
                print(
                    f"[SCORE][DETAIL][WARN] title={parsed['title']} "
                    f"tenjo={parsed['tenjo_score']} err={exc}"
                )
                detail_meta = None
            if detail_meta is not None:
                if _safe_int(detail_meta.get("initial_points"), 0) > 0:
                    initial_points = int(detail_meta["initial_points"])
                if detail_meta.get("selected_version"):
                    selected_version = detail_meta["selected_version"]
                detail_refreshed += 1
            time.sleep(0.2)

        merged_rows.append(
            {
                "title": parsed["title"],
                "level": int(parsed["level"]),
                "tenjo_score": int(parsed["tenjo_score"]),
                "goku_score": int(parsed["goku_score"]),
                "roll_required": int(parsed["roll_required"]),
                "roll_speed_ips": parsed["roll_speed_ips"],
                "max_combo": max_combo,
                "initial_points": initial_points,
                "selected_version": selected_version,
                "id": song_id or None,
            }
        )
        resolved += 1

    for row in existing_rows:
        if not isinstance(row, dict):
            continue
        try:
            level = int(row.get("level"))
        except Exception:
            continue
        key = _score_row_identity_key(row.get("title"), level)
        if key in kept_existing_keys:
            continue
        merged_rows.append(row)

    kept_old = len(merged_rows) - resolved
    before_deduplicate = len(merged_rows)
    merged_rows = deduplicate_scoreline_rows(merged_rows, song_data)
    deduplicated = before_deduplicate - len(merged_rows)
    merged_rows.sort(key=lambda item: (_score_title_base(item.get("title")), _safe_int(item.get("level"), 4)))
    with open(SCORE_PATH, "w", encoding="utf-8") as f:
        json.dump(merged_rows, f, ensure_ascii=False, indent=2)
    print(
        f"[SCORE] 已按 wikiwiki 刷新: {SCORE_PATH}, "
        f"parsed={len(parsed_rows)}, resolved={resolved}, "
        f"detail_attempted={detail_attempted}, detail_refreshed={detail_refreshed}, "
        f"detail_failed={detail_failed}, kept_old={kept_old}, "
        f"deduplicated={deduplicated}"
    )
    return merged_rows


def sync_song_data_with_taiko_database():
    resp = requests.get(TAIKO_WIKI_SONG_URL, timeout=30)
    resp.raise_for_status()
    database_data = resp.json()
    with open(TAIKO_SONG_DATABASE_PATH, "w", encoding="utf-8") as f:
        json.dump(database_data, f, ensure_ascii=False, indent=4)

    if not isinstance(database_data, list):
        raise ValueError("taiko.wiki 返回结果不是列表")

    filtered_database = []
    for song in database_data:
        song_no = song.get("songNo")
        if isinstance(song_no, str) and song_no.isdigit():
            filtered_database.append(song)
    fumen_result = download_missing_fumen_images(filtered_database)
    sync_fumens_to_oss(fumen_result.get("downloaded_files", []))

    other_db_songs = _extract_other_db_songs(database_data)
    other_db_by_songno = {
        str(song.get("songNo")): song for song in other_db_songs
    }

    old_data = json.load(open(SONG_DATA_PATH, "r", encoding="utf-8"))
    previous_roll_fields_by_id = {
        song.get("id"): {
            field: song.get(field)
            for field in ROLL_METADATA_FIELDS
        }
        for song in old_data
        if isinstance(song, dict) and song.get("id") is not None
    }
    old_main_songs = []
    old_other_songs = []
    for song in old_data:
        if not isinstance(song, dict):
            continue
        song_id = song.get("id")
        is_other = (
            song.get("shelf_status") == SHELF_STATUS_OTHER
            or song.get("songNo") is not None
            or (isinstance(song_id, int) and song_id >= OTHER_SONG_ID_START)
        )
        if is_other:
            old_other_songs.append(song)
        else:
            old_main_songs.append(song)

    old_by_id = {song.get("id"): song for song in old_main_songs if isinstance(song, dict)}
    db_by_id = {int(song["songNo"]): song for song in filtered_database}
    previous_down_shelf_ids = set()
    for song in old_main_songs:
        if not isinstance(song, dict):
            continue
        status = song.get("shelf_status")
        if status == SHELF_STATUS_DOWN or status == "已下架":
            previous_down_shelf_ids.add(song.get("id"))
    raw_shelf_status_by_id = {}
    raw_song_by_id = {}
    raw_snapshot_loaded = False
    if SONG_DATA_RAW_PATH.exists():
        try:
            raw_data = json.load(open(SONG_DATA_RAW_PATH, "r", encoding="utf-8"))
            raw_shelf_status_by_id = {
                song.get("id"): song.get("shelf_status")
                for song in raw_data
                if isinstance(song, dict) and isinstance(song.get("id"), int)
            }
            raw_song_by_id = {
                song.get("id"): song
                for song in raw_data
                if isinstance(song, dict) and isinstance(song.get("id"), int)
            }
            raw_snapshot_loaded = True
        except Exception:
            raw_shelf_status_by_id = {}
            raw_song_by_id = {}
            raw_snapshot_loaded = False
    score_confirmed_levels_by_id = _load_score_confirmed_rating_levels()
    merged = []

    for song in old_main_songs:
        if not isinstance(song, dict):
            continue
        song_id = song.get("id")
        db_song = db_by_id.get(song_id)
        if not db_song:
            updated_song = dict(song)
            if not isinstance(updated_song.get("version"), list):
                updated_song["version"] = []
            if not isinstance(updated_song.get("artists"), list):
                updated_song["artists"] = []
            if (
                not isinstance(updated_song.get("max_combo"), list)
                or len(updated_song["max_combo"]) != 5
            ):
                updated_song["max_combo"] = ["-", "-", "-", "-", "-"]
            if updated_song.get("shelf_status") not in (
                SHELF_STATUS_UP,
                SHELF_STATUS_DOWN,
                "未下架",
                "已下架",
            ):
                updated_song["shelf_status"] = SHELF_STATUS_UP
            merged.append(updated_song)
            continue
        levels, max_combo = _extract_levels_and_max_combo(db_song)
        artists = db_song.get("artists")
        if not isinstance(artists, list):
            artists = []
        version = db_song.get("version")
        if not isinstance(version, list):
            version = []

        updated_song = dict(song)
        updated_song["version"] = version
        updated_song["artists"] = artists
        _apply_levels_and_max_combo(updated_song, levels, max_combo)
        _restrict_levels_by_raw_snapshot(
            updated_song,
            raw_song_by_id.get(song_id),
            preserve_levels=score_confirmed_levels_by_id.get(song_id),
        )
        bpm_text = _build_bpm_text(db_song)
        if bpm_text != "-":
            updated_song["bpm"] = bpm_text
        mapped_type = _pick_song_type_from_genre(db_song)
        if mapped_type:
            updated_song["type"] = mapped_type
        if raw_snapshot_loaded:
            if song_id in raw_shelf_status_by_id:
                is_down_shelf = _is_down_shelf_status(raw_shelf_status_by_id.get(song_id))
            else:
                is_down_shelf = True
        else:
            is_down_shelf = song_id in previous_down_shelf_ids
        updated_song["shelf_status"] = (
            SHELF_STATUS_DOWN if is_down_shelf else SHELF_STATUS_UP
        )
        merged.append(updated_song)

    for song_id, db_song in db_by_id.items():
        if song_id in old_by_id:
            continue
        appended_song = _build_down_shelf_song(db_song)
        _restrict_levels_by_raw_snapshot(
            appended_song,
            raw_song_by_id.get(song_id),
            preserve_levels=score_confirmed_levels_by_id.get(song_id),
        )
        if song_id in raw_shelf_status_by_id:
            appended_song["shelf_status"] = (
                SHELF_STATUS_DOWN
                if _is_down_shelf_status(raw_shelf_status_by_id.get(song_id))
                else SHELF_STATUS_UP
            )
        merged.append(appended_song)

    # Merge "other songs" (taiko.wiki entries whose songNo is not numeric).
    assigned_other_songnos = set()
    max_other_id = OTHER_SONG_ID_START - 1
    for song in old_other_songs:
        try:
            sid = int(song.get("id"))
        except Exception:
            sid = 0
        if sid >= OTHER_SONG_ID_START:
            max_other_id = max(max_other_id, sid)

    for song in old_other_songs:
        song_no = song.get("songNo")
        db_song = (
            other_db_by_songno.get(str(song_no)) if song_no is not None else None
        )
        updated_song = dict(song)
        if db_song is not None:
            try:
                sid = int(song.get("id"))
            except Exception:
                sid = 0
            if sid < OTHER_SONG_ID_START:
                max_other_id += 1
                updated_song["id"] = max_other_id
                updated_song["sort"] = max_other_id
            _apply_other_song_wiki_fields(updated_song, db_song)
        else:
            updated_song["shelf_status"] = SHELF_STATUS_OTHER
        merged.append(updated_song)
        if song_no is not None:
            assigned_other_songnos.add(str(song_no))

    for song_no, db_song in other_db_by_songno.items():
        if song_no in assigned_other_songnos:
            continue
        max_other_id += 1
        merged.append(_build_other_song(db_song, max_other_id))

    if other_db_songs:
        other_id_by_songno = {
            str(song.get("songNo")): int(song.get("id"))
            for song in merged
            if isinstance(song, dict) and song.get("songNo") is not None
            and song.get("id") is not None
        }
        other_fumen_result = download_other_song_fumen_images(
            other_db_songs, other_id_by_songno
        )
        sync_fumens_to_oss(other_fumen_result.get("downloaded_files", []))

    # Replace upstream roll metadata with parser output only for songs and
    # courses that pass the audit. Blocked matches preserve their previous
    # values and are recorded for manual review.
    # Do not let the upstream API replace the previous local roll metadata
    # before the audit decides whether a TJA result is safe to write.
    for song in merged:
        previous = previous_roll_fields_by_id.get(song.get("id"))
        if previous:
            song.update(previous)
    try:
        song_tja_mapping = refresh_song_tja_mapping()
        mapping_source = SONG_TJA_MAPPING_URL
        logger.info(
            "歌曲 TJA 映射刷新完成: count=%d cache=%s",
            len(song_tja_mapping),
            SONG_TJA_MAPPING_PATH,
        )
    except Exception as exc:
        if not SONG_TJA_MAPPING_PATH.is_file():
            raise RuntimeError("歌曲 TJA 映射刷新失败且无本地缓存") from exc
        song_tja_mapping = load_song_tja_mapping()
        mapping_source = f"{SONG_TJA_MAPPING_PATH} (cached)"
        logger.warning(
            "歌曲 TJA 映射刷新失败，使用本地缓存: count=%d error=%s",
            len(song_tja_mapping),
            exc,
        )
    tja_audit = audit_song_data(
        merged,
        song_tja_mapping=song_tja_mapping,
        mapping_source=mapping_source,
    )
    write_audit_report(tja_audit)
    merged = tja_audit["proposedSongData"]

    # Canonical per-chart corrections must be the final authority.  Keep this
    # immediately before serialization so later upstream merge changes cannot
    # silently restore known-bad aggregate values (notably song 890 Oni).
    for song in merged:
        apply_chart_roll_metadata_overrides(song)

    with open(SONG_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
    audio_sync_report = sync_audio_from_ese(
        merged, mode="incremental", include_other=True
    )
    audio_sync_failure = _audio_sync_failure_message(audio_sync_report)
    if audio_sync_failure:
        print(f"[AUDIO][ESE][WARN] 自动补齐失败: {audio_sync_failure}")
    elif not BRANCH_AUDIO_MANIFEST_PATH.is_file():
        audio_sync_failure = (
            f"分歧音频清单未生成: {BRANCH_AUDIO_MANIFEST_PATH}"
        )
        print(f"[AUDIO][ESE][WARN] {audio_sync_failure}")
    check_missing_audio_for_song_data(merged)

    subprocess.run(
        ["ossutil", "cp", "-f", str(SONG_DATA_PATH), OSS_SONG_DATA_PATH],
        check=True,
        capture_output=True,
        text=True,
    )
    if not audio_sync_failure:
        subprocess.run(
            [
                "ossutil",
                "cp",
                "-f",
                str(BRANCH_AUDIO_MANIFEST_PATH),
                OSS_BRANCH_AUDIO_MANIFEST_PATH,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    sync_rating_structured_with_song_data(merged)
    sync_song_score_with_wiki(merged)
    rebuilt_count, matched_count = rebuild_scoreline_dataset(SCORELINE_DATA_PATH)
    print(
        f"[SCORELINE] 已重建: {SCORELINE_DATA_PATH}, "
        f"rows={rebuilt_count}, matched={matched_count}"
    )
    if audio_sync_failure:
        raise RuntimeError(f"[AUDIO][ESE] 自动补齐未完成: {audio_sync_failure}")


def update_taiko_music(interactive=True):
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    authorization = config["cookie"]
    url = "https://wl-taiko.wahlap.net/api/user/all/songs"
    data = {"page": 1, "pageSize": 3000, "sort": 1, "isPlayed": True}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541020) XWEB/16459",
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": authorization,
    }
    response = requests.post(url, json=data, headers=headers, timeout=30)
    response.raise_for_status()
    song_data = response.json()["data"]["list"]
    id_list = []
    new_data = []
    for music in song_data:
        if music["id"] not in id_list:
            id_list.append(music["id"])
            new_data.append(music)

    old_data = json.load(open(SONG_DATA_PATH, "r", encoding="utf-8"))
    new_by_id = {music["id"]: music for music in new_data}
    old_by_id = {music["id"]: music for music in old_data}
    db_bpm_map = _load_db_bpm_map()
    merged = []

    for old_music in old_data:
        new_music = new_by_id.get(old_music["id"])
        if new_music:
            merged.append(
                _merge_wahlap_song_without_roll_metadata(new_music, old_music)
            )
        else:
            merged.append(old_music)

    for music in new_data:
        if music["id"] not in old_by_id:
            music = _merge_wahlap_song_without_roll_metadata(music)
            parsed_bpm = db_bpm_map.get(int(music["id"]), "-")
            if parsed_bpm != "-":
                bpm = parsed_bpm
            elif interactive:
                bpm = input(f"请输入歌曲《{music['song_name_jp']}》的bpm:").strip()
                if not bpm:
                    bpm = "-"
            else:
                bpm = "-"
            music["bpm"] = bpm
            merged.append(music)

    with open(SONG_DATA_RAW_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
    # 先以 wahlap 全量结果更新 song_data，再基于 taiko.wiki 做字段补全/纠正
    for song in merged:
        apply_chart_roll_metadata_overrides(song)
    with open(SONG_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

    sync_song_data_with_taiko_database()
    title_items = refresh_title_catalog_cache()
    if not title_items:
        raise ValueError("称号目录缓存刷新失败：all/title 未返回有效数据")
    visible_conditions = sum(
        1
        for item in title_items
        if isinstance(item, dict) and str(item.get("subtitle") or "").strip() not in {"", "???", "？？？"}
    )
    logger.info(
        "称号目录缓存刷新完成: total=%d visible=%d cache=%s",
        len(title_items),
        visible_conditions,
        ROOT_DIR / "data" / "title_catalog_cache.json",
    )
    subprocess.run(
        [
            sys.executable,
            str(TITLE_RELATIONS_SCRIPT_PATH),
            "--input",
            str(TITLE_RELATIONS_INPUT_PATH),
            "--output",
            str(TITLE_RELATIONS_OUTPUT_PATH),
            "--title-catalog",
            str(TITLE_CATALOG_CACHE_PATH),
        ],
        check=True,
        cwd=str(TITLE_RELATIONS_SCRIPT_PATH.parent.parent),
    )
    logger.info("称号关系文件重建完成: %s", TITLE_RELATIONS_OUTPUT_PATH)
    clear_song_title_showcase_caches()
    logger.info("称号展示缓存已清理")


def _scheduled_update_job():
    try:
        logger.info("开始执行每日歌曲数据更新任务")
        update_taiko_music(interactive=False)
        logger.info("每日歌曲数据更新任务执行成功")
    except Exception:
        logger.exception("每日歌曲数据更新任务执行失败")


scheduler = BlockingScheduler()
scheduler.add_job(
    _scheduled_update_job,
    CronTrigger(hour=DAILY_UPDATE_HOUR, minute=DAILY_UPDATE_MINUTE),
    id=SCHEDULE_JOB_TAG,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Taiko song data scheduled updater")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="run one update immediately and exit",
    )
    args = parser.parse_args()
    if args.run_once:
        _scheduled_update_job()
        return
    logger.info(
        "启动 APScheduler 定时更新：每天 %02d:%02d",
        DAILY_UPDATE_HOUR,
        DAILY_UPDATE_MINUTE,
    )
    scheduler.start()


if __name__ == "__main__":
    main()


# if __name__ == "__main__":
#     update_taiko_music()
