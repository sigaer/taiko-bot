from __future__ import annotations
from taiko_bot.runtime.paths import root as _runtime_root




import html

import json

import re

import unicodedata

from dataclasses import dataclass

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .duplicate_versions import default_song_id_for_query

from .title_catalog import build_title_rarity_lookup, load_title_catalog_items, normalize_title_display

ROOT_DIR = _runtime_root()

SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

RATING_DB_PATH = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

TITLE_RELATIONS_PATH = (
    ROOT_DIR / "taiko-forum" / "taiko_viewer" / "assets" / "data" / "title_song_relations.json"
)

TITLE_TABLE_JP_PATH = (
    ROOT_DIR / "taiko-forum" / "taiko_viewer" / "assets" / "data" / "title_wikitable.json"
)

TITLE_TABLE_CN_PATH = (
    ROOT_DIR / "taiko-forum" / "taiko_viewer" / "assets" / "data" / "title_wikitable_cn.json"
)

TAG_RE = re.compile(r"<[^>]+>")

ANCHOR_RE = re.compile(r"<a\s+([^>]*?)>(.*?)</a>", re.IGNORECASE | re.DOTALL)

ATTR_RE = re.compile(
    r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"|([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*\'([^\']*)\''
)

HIDDEN_SUBTITLE_MARKERS = {"", "???", "？？？"}

LIMITED_TITLE_PREFIX_RE = re.compile(r"^【限定】\s*")

HIDDEN_CHART_SUFFIX_RE = re.compile(r"\s*[（(]裏[)）]\s*$")

TRAILING_LOOKUP_PUNCT_RE = re.compile(r"[.!！?？。．…]+$")

LOOKUP_DASH_RE = re.compile(r"[‐‑‒–—―−]")

LOOKUP_APOSTROPHE_RE = re.compile(r"[’'`]")

LOOKUP_JOIN_PUNCT_RE = re.compile(r"\s*([:：\-～〜/／])\s*")

GENERIC_PHRASES = (
    "一局内",
    "1游玩内",
    "1プレイ内",
    "所有曲子",
    "曲を全て",
    "全部选择",
    "系列",
    "专辑",
    "选项",
    "双人模式",
    "同时",
    "歌曲",
    "特定の曲",
    "特定的曲",
    "全部达成",
    "全部全良",
    "全部全连",
)

PLATE_ID_MAP = {
    ("clear", "inner_oni"): 59,
    ("full_combo", "inner_oni"): 60,
    ("all_perfect", "inner_oni"): 61,
    ("clear", "oni"): 41,
    ("full_combo", "oni"): 42,
    ("all_perfect", "oni"): 43,
    ("clear", "unspecified"): 0,
    ("full_combo", "unspecified"): 2,
    ("all_perfect", "unspecified"): 1,
}

PLATE_ID_FALLBACK_ORDER = {
    0: (0, 41, 59),
    1: (1, 43, 61),
    2: (2, 42, 60),
    41: (41, 59, 0),
    42: (42, 60, 2),
    43: (43, 61, 1),
    59: (59, 41, 0),
    60: (60, 42, 2),
    61: (61, 43, 1),
}

SHOWCASE_PRIORITY = {
    "all_perfect": 0,
    "full_combo_group": 1,
    "full_combo": 2,
    "clear": 3,
}

SCOPE_PRIORITY = {
    "inner_oni": 2,
    "oni_or_inner_oni": 2,
    "oni": 1,
    "hard": 0,
    "normal": 0,
    "easy": 0,
    "unspecified": 0,
}

SHOWCASE_EXCLUDED_TITLES = frozenset(
    {
        "765の達人",
        "876の達人",
        "ガッガッガッ",
        "あふれるパッション",
        "Seafood Seeker",
        "セッションマスター",
    }
)

SHOWCASE_FULL_COMBO_LOWEST_TITLES = frozenset({"教授のきもち"})

SHOWCASE_CLEAR_LOWEST_TITLES = frozenset({"たいこのたしゅじん", "恋の病治療中"})

SHOWCASE_PRIORITY_CONST_BY_SONG = {"BATTLE NO.1": 8.5}

MANUAL_CANONICAL_SHOWCASE_TITLES = frozenset(
    {
        "紫薔薇の融合",
        "出会った仲間と共に乗り越えて行ける",
    }
)

MANUAL_HIDDEN_TITLE_RELATIONS = (
    {
        "title_name": "Nijustat on Amatias",
        "song_names": ("Nijustat on Amatias",),
        "requirement_type": "full_combo",
        "difficulty_scope": "oni",
        "condition_text": "手动补充：Nijustat on Amatias（下架曲）魔王全连",
        "source_row_index": 15275,
    },
    {
        "title_name": "とても短い曲です(20秒)",
        "song_names": ("よくでる15300",),
        "requirement_type": "full_combo",
        "difficulty_scope": "oni",
        "condition_text": "手动补充：よくでる15300 魔王全连",
        "source_row_index": 15248,
    },
    {
        "title_name": "紫薔薇の融合",
        "song_names": ("Purple Rose Fusion",),
        "requirement_type": "full_combo",
        "difficulty_scope": "oni",
        "condition_text": "手动补充：Purple Rose Fusion 魔王全连",
        "source_row_index": 2666,
    },
    {
        "title_name": "出会った仲間と共に乗り越えて行ける",
        "song_names": ("4+1のそれぞれの未来(裏)",),
        "requirement_type": "full_combo",
        "difficulty_scope": "inner_oni",
        "condition_text": "手动修正：4+1のそれぞれの未来(裏) 里谱全连",
        "source_row_index": 523,
    },
)

MANUAL_SONG_ALIAS_GROUPS = (
    ("Nijustat on Amatias", "Nesin Amatias", "【限定】 Nesin Amatias"),
    ("よくでる15300", "【限定】 よくでる15300"),
    ("YELL EX MACHINA!", "YELL EX MAKINA!"),
)

@dataclass(frozen=True)
class SongTitleRelation:
    title_name: str
    song_names: Tuple[str, ...]
    requirement_type: str
    difficulty_scope: str
    condition_text: str
    source_row_index: int

@dataclass(frozen=True)
class ShowcaseTitle:
    title_name: str
    plate_id: int
    requirement_type: str
    difficulty_scope: str
    condition_text: str
    song_names: Tuple[str, ...]
    song_ids: Tuple[int, ...]
    const_value: float
    priority_const_value: float
    is_multi_song: bool
    showcase_bg_plate_id: Optional[int] = None
    source: str = "official"
    custom_title_id: Optional[int] = None
    difficulty_level: Optional[int] = None
    plate_style: Optional[str] = None

    @property
    def priority_key(self) -> str:
        if self.requirement_type == "all_perfect":
            return "all_perfect"
        if self.requirement_type == "full_combo":
            if normalize_title_display(self.title_name) in SHOWCASE_FULL_COMBO_LOWEST_TITLES:
                return "full_combo"
            if self.is_multi_song:
                return "full_combo_group"
            return "full_combo"
        return "clear"

@dataclass(frozen=True)
class Anchor:
    href: str
    title: str
    text: str

def _html_to_text(value: str) -> str:
    text = TAG_RE.sub("", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def _parse_anchor_attrs(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for match in ATTR_RE.finditer(raw):
        if match.group(1):
            attrs[match.group(1).lower()] = match.group(2)
        elif match.group(3):
            attrs[match.group(3).lower()] = match.group(4)
    return attrs

def _extract_anchors(value: str) -> List[Anchor]:
    anchors: List[Anchor] = []
    for match in ANCHOR_RE.finditer(value or ""):
        attrs = _parse_anchor_attrs(match.group(1))
        anchors.append(
            Anchor(
                href=attrs.get("href", "").strip(),
                title=html.unescape(attrs.get("title", "").strip()),
                text=_html_to_text(match.group(2)),
            )
        )
    return anchors

def _is_song_anchor(anchor: Anchor) -> bool:
    href = anchor.href
    if not href.startswith("http"):
        return False
    if "/taiko/" not in href and "/taiko-fumen/" not in href:
        return False
    if "/taiko-fumen/" in href and (
        "/作品/" in href
        or "%E4%BD%9C%E5%93%81/" in href
        or "/新AC/" in href
        or "%E6%96%B0AC/" in href
    ):
        return False
    if "index.php?title=" in href:
        return False
    if "页面不存在" in anchor.title:
        return False
    return bool(anchor.text or anchor.title)

def _normalize_lookup_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(value or "")))
    text = LOOKUP_DASH_RE.sub("-", text)
    text = re.sub(r"\s+", " ", text).strip()
    return LOOKUP_JOIN_PUNCT_RE.sub(r"\1", text)

def _normalize_title_key(value: str) -> str:
    return _normalize_lookup_text(value).casefold()

@lru_cache(maxsize=1)
def _load_song_alias_lookup() -> Dict[str, Tuple[str, ...]]:
    lookup: Dict[str, set[str]] = {}
    for group in MANUAL_SONG_ALIAS_GROUPS:
        normalized_group = {
            _normalize_title_key(item)
            for item in group
            if str(item or "").strip()
        }
        for key in normalized_group:
            lookup.setdefault(key, set()).update(normalized_group)
    return {
        key: tuple(sorted(values))
        for key, values in lookup.items()
        if values
    }

def _song_lookup_keys(value: str) -> Tuple[str, ...]:
    keys: List[str] = []
    candidates = [_normalize_lookup_text(value)]
    stripped = LIMITED_TITLE_PREFIX_RE.sub("", _normalize_lookup_text(value))
    if stripped and stripped not in candidates:
        candidates.append(stripped)

    expanded_candidates: List[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        if candidate not in expanded_candidates:
            expanded_candidates.append(candidate)
        no_apostrophe = LOOKUP_APOSTROPHE_RE.sub("", candidate).strip()
        if no_apostrophe and no_apostrophe not in expanded_candidates:
            expanded_candidates.append(no_apostrophe)
        no_hidden_suffix = HIDDEN_CHART_SUFFIX_RE.sub("", candidate).strip()
        if no_hidden_suffix and no_hidden_suffix not in expanded_candidates:
            expanded_candidates.append(no_hidden_suffix)
        no_trailing_punct = TRAILING_LOOKUP_PUNCT_RE.sub("", candidate).strip()
        if no_trailing_punct and no_trailing_punct not in expanded_candidates:
            expanded_candidates.append(no_trailing_punct)
        no_hidden_or_punct = HIDDEN_CHART_SUFFIX_RE.sub("", no_trailing_punct).strip()
        if no_hidden_or_punct and no_hidden_or_punct not in expanded_candidates:
            expanded_candidates.append(no_hidden_or_punct)
        no_spaces = candidate.replace(" ", "")
        if no_spaces and no_spaces not in expanded_candidates:
            expanded_candidates.append(no_spaces)

    for candidate in expanded_candidates:
        key = _normalize_title_key(candidate)
        if key and key not in keys:
            keys.append(key)
    alias_lookup = _load_song_alias_lookup()
    expanded: List[str] = []
    for key in keys:
        expanded.append(key)
        for alias_key in alias_lookup.get(key, ()):
            if alias_key not in expanded:
                expanded.append(alias_key)
    return tuple(expanded)

def _cleanup_song_name(name: str) -> str:
    value = html.unescape(str(name or "")).strip()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("》《", "|")
    return value.strip(" \t\r\n.,，。:：;；\"'[]《》")

def _cleanup_condition_song_name(name: str) -> str:
    value = html.unescape(str(name or "")).strip()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("》《", "|")
    return value.strip(" \t\r\n.,，。:：;；\"'")

def _split_song_blob(blob: str) -> List[str]:
    value = str(blob or "")
    for token in ("以及", "和", "及", "与", "、", ",", "，", "/", "|"):
        value = value.replace(token, "|")
    parts = [_cleanup_song_name(part) for part in value.split("|")]
    return [part for part in parts if part]

@lru_cache(maxsize=1)
def _load_title_rarity_lookup() -> Dict[str, Tuple[int, ...]]:
    return build_title_rarity_lookup(load_title_catalog_items())

@lru_cache(maxsize=1)
def _load_available_title_names() -> frozenset[str]:
    names = {
        normalize_title_display(item.get("name") or "")
        for item in load_title_catalog_items()
        if isinstance(item, dict)
    }
    names.discard("")
    return frozenset(names)

def _is_generic_candidate(name: str) -> bool:
    text = str(name or "")
    return any(phrase in text for phrase in GENERIC_PHRASES)

def _unique_keep_order(values: Iterable[str]) -> Tuple[str, ...]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)

def _detect_requirement_type(condition_text: str) -> Optional[str]:
    text = str(condition_text or "")
    if "全良" in text or "ドンダフルコンボ" in text:
        return "all_perfect"
    if "全连" in text or "フルコンボ" in text:
        return "full_combo"
    if "通关" in text or "过关" in text or "クリア" in text:
        return "clear"
    return None

def _detect_difficulty_scope(condition_text: str) -> str:
    text = str(condition_text or "")
    has_oni = bool(re.search(r"魔王|難易度おに|おにで|おに譜面", text))
    has_inner_oni = bool(
        re.search(r"魔王[（(]隐藏[)）]|魔王[（(]裏[)）]|[（(]裏[)）]|裏譜面|里谱|隠し譜面", text)
    )
    has_explicit_dual_scope = bool(
        re.search(
            r"魔王[^。；，]{0,6}(?:或|/|／|または)[^。；，]{0,6}"
            r"(?:魔王[（(](?:隐藏|裏)[)）]|里谱|裏譜面|隠し譜面)",
            text,
        )
        or re.search(
            r"おに[^。；，]{0,4}(?:/|／|または)[^。；，]{0,8}(?:裏|裏譜面|隠し譜面)",
            text,
        )
        or re.search(
            r"(?:裏|裏譜面|隠し譜面)[^。；，]{0,8}(?:/|／|または)[^。；，]{0,4}おに",
            text,
        )
    )
    if has_oni and has_inner_oni and has_explicit_dual_scope:
        return "oni_or_inner_oni"
    if has_inner_oni:
        return "inner_oni"
    if has_oni:
        return "oni"
    if "困难" in text or "むずかしい" in text:
        return "hard"
    if "普通" in text or "一般" in text or "ふつう" in text:
        return "normal"
    if "简单" in text or "かんたん" in text:
        return "easy"
    return "unspecified"

def _extract_api_condition_song_names(condition_text: str) -> Tuple[str, ...]:
    text = str(condition_text or "")
    matches = re.findall(r"《([^》]+)》", text)
    cleaned: List[str] = []
    for match in matches:
        song_name = _cleanup_condition_song_name(match)
        if not song_name or _is_generic_candidate(song_name):
            continue
        cleaned.append(song_name)
    return _unique_keep_order(cleaned)

def _extract_all_perfect_song_names(condition_text: str) -> Tuple[str, ...]:
    text = str(condition_text or "")
    names: List[str] = []

    for match in re.finditer(r"([^，。,；;]+?)在[^，。,；;]{0,24}全良", text):
        names.extend(_split_song_blob(match.group(1)))
    for match in re.finditer(r"的(.+?)全良", text):
        names.extend(_split_song_blob(match.group(1)))
    tail_match = re.search(r"全良\s*([^，。,；;]+)$", text)
    if tail_match:
        names.extend(_split_song_blob(tail_match.group(1)))
    for match in re.finditer(r"([^，。,；;]+?)全良", text):
        names.extend(_split_song_blob(match.group(1)))

    cleaned = []
    for name in names:
        song = _cleanup_song_name(name)
        if not song or _is_generic_candidate(song):
            continue
        cleaned.append(song)
    return _unique_keep_order(cleaned)

@lru_cache(maxsize=1)
def _load_song_lookup() -> Tuple[
    Dict[str, Tuple[int, ...]],
    Dict[Tuple[int, int], float],
    Dict[Tuple[str, int], float],
    Dict[Tuple[int, int], float],
]:
    title_to_song_ids: Dict[str, set[int]] = {}
    const_by_song_level: Dict[Tuple[int, int], float] = {}
    const_by_title_level: Dict[Tuple[str, int], float] = {}
    level_by_song_level: Dict[Tuple[int, int], float] = {}

    if SONG_DATA_PATH.exists():
        payload = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                try:
                    song_id = int(row.get("id"))
                except Exception:
                    continue
                for level in range(1, 6):
                    raw_level = row.get(f"level_{level}")
                    try:
                        level_value = float(raw_level)
                    except Exception:
                        continue
                    level_by_song_level[(song_id, level)] = level_value
                for key in ("song_name", "song_name_jp"):
                    value = str(row.get(key) or "").strip()
                    if not value:
                        continue
                    for normalized_title in _song_lookup_keys(value):
                        title_to_song_ids.setdefault(normalized_title, set()).add(song_id)

    if RATING_DB_PATH.exists():
        payload = json.loads(RATING_DB_PATH.read_text(encoding="utf-8"))
        songs = payload.get("songs") or {}
        rows = songs.values() if isinstance(songs, dict) else songs
        if isinstance(rows, Iterable):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    song_id = int(row.get("id"))
                    level = int(row.get("level"))
                    score = float(row.get("score"))
                except Exception:
                    continue
                key = (song_id, level)
                if score > const_by_song_level.get(key, 0.0):
                    const_by_song_level[key] = score
                for key_name in ("曲名", "song_name_cn"):
                    value = str(row.get(key_name) or "").strip()
                    if not value:
                        continue
                    for normalized_title in _song_lookup_keys(value):
                        title_to_song_ids.setdefault(normalized_title, set()).add(song_id)
                        title_level_key = (normalized_title, level)
                        if score > const_by_title_level.get(title_level_key, 0.0):
                            const_by_title_level[title_level_key] = score

    frozen_lookup = {
        key: tuple(sorted(song_ids))
        for key, song_ids in title_to_song_ids.items()
        if song_ids
    }
    return frozen_lookup, const_by_song_level, const_by_title_level, level_by_song_level

@lru_cache(maxsize=1)
def _load_api_song_title_relations() -> Tuple[SongTitleRelation, ...]:
    relations: List[SongTitleRelation] = []
    for item in load_title_catalog_items():
        if not isinstance(item, dict):
            continue
        title_name = normalize_title_display(item.get("name") or "")
        if title_name in SHOWCASE_EXCLUDED_TITLES:
            continue
        condition_text = str(item.get("subtitle") or "").strip()
        if not title_name or condition_text in HIDDEN_SUBTITLE_MARKERS:
            continue
        requirement_type = _detect_requirement_type(condition_text)
        if requirement_type is None:
            continue
        song_names = _extract_api_condition_song_names(condition_text)
        if not song_names:
            continue
        relations.append(
            SongTitleRelation(
                title_name=title_name,
                song_names=song_names,
                requirement_type=requirement_type,
                difficulty_scope=_detect_difficulty_scope(condition_text),
                condition_text=condition_text,
                source_row_index=int(item.get("sort_no", -1) or -1),
            )
        )
    return tuple(relations)

@lru_cache(maxsize=1)
def _load_legacy_base_song_title_relations() -> Tuple[SongTitleRelation, ...]:
    if TITLE_TABLE_JP_PATH.exists():
        payload = json.loads(TITLE_TABLE_JP_PATH.read_text(encoding="utf-8"))
        rows = payload.get("rows") or []
        relations: List[SongTitleRelation] = []

        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            cells = row.get("cells") or []
            if len(cells) < 3:
                continue
            title_name = _html_to_text(cells[1].get("html", ""))
            condition_html = cells[2].get("html", "")
            condition_text = _html_to_text(condition_html)
            if not title_name or not condition_text:
                continue

            requirement_type = _detect_requirement_type(condition_text)
            if requirement_type not in {"clear", "full_combo"}:
                continue

            anchors = [anchor for anchor in _extract_anchors(condition_html) if _is_song_anchor(anchor)]
            if not anchors:
                continue

            song_names: List[str] = []
            for anchor in anchors:
                primary = _cleanup_song_name(anchor.title) if anchor.title else ""
                fallback = _cleanup_song_name(anchor.text)
                selected = primary or fallback
                if selected and not _is_generic_candidate(selected):
                    song_names.append(selected)

            deduped_song_names = _unique_keep_order(song_names)
            if not deduped_song_names:
                continue

            relations.append(
                SongTitleRelation(
                    title_name=title_name,
                    song_names=deduped_song_names,
                    requirement_type=requirement_type,
                    difficulty_scope=_detect_difficulty_scope(condition_text),
                    condition_text=condition_text,
                    source_row_index=row_index,
                )
            )

        deduped: Dict[Tuple[str, Tuple[str, ...], str, str, str], SongTitleRelation] = {}
        for item in relations:
            key = (
                item.title_name,
                item.song_names,
                item.requirement_type,
                item.difficulty_scope,
                item.condition_text,
            )
            deduped[key] = item
        return tuple(deduped.values())

    if not TITLE_RELATIONS_PATH.exists():
        return ()
    payload = json.loads(TITLE_RELATIONS_PATH.read_text(encoding="utf-8"))
    grouped: Dict[Tuple[str, str, str, str], List[str]] = {}
    source_rows: Dict[Tuple[str, str, str, str], int] = {}

    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        title_name = str(item.get("title_name") or "").strip()
        song_name = str(item.get("song_name") or "").strip()
        requirement_type = str(item.get("requirement_type") or "").strip()
        difficulty_scope = str(item.get("difficulty_scope") or "unspecified").strip() or "unspecified"
        condition_text = str(item.get("condition_text") or "").strip()
        if not title_name or not song_name or requirement_type not in {"clear", "full_combo", "all_perfect"}:
            continue
        key = (title_name, requirement_type, difficulty_scope, condition_text)
        grouped.setdefault(key, []).append(song_name)
        try:
            source_rows[key] = int(item.get("source_row_index"))
        except Exception:
            source_rows[key] = -1

    relations: List[SongTitleRelation] = []
    for key, song_names in grouped.items():
        title_name, requirement_type, difficulty_scope, condition_text = key
        relations.append(
            SongTitleRelation(
                title_name=title_name,
                song_names=_unique_keep_order(song_names),
                requirement_type=requirement_type,
                difficulty_scope=difficulty_scope,
                condition_text=condition_text,
                source_row_index=source_rows.get(key, -1),
            )
        )
    return tuple(relations)

@lru_cache(maxsize=1)
def _load_legacy_all_perfect_relations() -> Tuple[SongTitleRelation, ...]:
    if not TITLE_TABLE_CN_PATH.exists():
        return ()
    payload = json.loads(TITLE_TABLE_CN_PATH.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    relations: List[SongTitleRelation] = []

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cells = row.get("cells") or []
        if len(cells) < 3:
            continue
        title_name = _html_to_text(cells[1].get("html", ""))
        condition_text = _html_to_text(cells[2].get("html", ""))
        if not title_name or not condition_text:
            continue
        if "全良" not in condition_text and "ドンダフルコンボ" not in condition_text:
            continue

        song_names = _extract_all_perfect_song_names(condition_text)
        if not song_names:
            continue

        relations.append(
            SongTitleRelation(
                title_name=title_name,
                song_names=song_names,
                requirement_type="all_perfect",
                difficulty_scope=_detect_difficulty_scope(condition_text),
                condition_text=condition_text,
                source_row_index=row_index,
            )
        )

    deduped: Dict[Tuple[str, Tuple[str, ...], str, str, str], SongTitleRelation] = {}
    for item in relations:
        key = (
            item.title_name,
            item.song_names,
            item.requirement_type,
            item.difficulty_scope,
            item.condition_text,
        )
        deduped[key] = item
    return tuple(deduped.values())

@lru_cache(maxsize=1)
def _load_manual_hidden_relations() -> Tuple[SongTitleRelation, ...]:
    return tuple(
        SongTitleRelation(
            title_name=item["title_name"],
            song_names=tuple(item["song_names"]),
            requirement_type=item["requirement_type"],
            difficulty_scope=item["difficulty_scope"],
            condition_text=item["condition_text"],
            source_row_index=int(item["source_row_index"]),
        )
        for item in MANUAL_HIDDEN_TITLE_RELATIONS
        if item["title_name"] not in SHOWCASE_EXCLUDED_TITLES
    )

def _relation_merge_key(item: SongTitleRelation) -> Tuple[str, str, str]:
    return (
        _normalize_title_key(item.title_name),
        item.requirement_type,
        str(item.difficulty_scope or "unspecified"),
    )

@lru_cache(maxsize=1)
def load_song_title_relations() -> Tuple[SongTitleRelation, ...]:
    api_relations = list(_load_api_song_title_relations())
    relations = list(api_relations)
    seen_api_keys = {_relation_merge_key(item) for item in api_relations}
    canonical_override_titles: set[str] = set()

    for manual_relation in _load_manual_hidden_relations():
        normalized_title = normalize_title_display(manual_relation.title_name)
        if normalized_title in MANUAL_CANONICAL_SHOWCASE_TITLES:
            relations = [
                item
                for item in relations
                if not (
                    normalize_title_display(item.title_name) == normalized_title
                    and item.requirement_type == manual_relation.requirement_type
                )
            ]
            seen_api_keys = {
                key
                for key in seen_api_keys
                if not (
                    key[0] == _normalize_title_key(manual_relation.title_name)
                    and key[1] == manual_relation.requirement_type
                )
            }
            canonical_override_titles.add(normalized_title)
        if _relation_merge_key(manual_relation) in seen_api_keys:
            continue
        relations.append(manual_relation)
        seen_api_keys.add(_relation_merge_key(manual_relation))

    for legacy_relation in list(_load_legacy_base_song_title_relations()) + list(
        _load_legacy_all_perfect_relations()
    ):
        if normalize_title_display(legacy_relation.title_name) in canonical_override_titles:
            continue
        if _relation_merge_key(legacy_relation) in seen_api_keys:
            continue
        if normalize_title_display(legacy_relation.title_name) in SHOWCASE_EXCLUDED_TITLES:
            continue
        relations.append(legacy_relation)

    relations = [
        item
        for item in relations
        if normalize_title_display(item.title_name) not in SHOWCASE_EXCLUDED_TITLES
    ]
    available_title_names = _load_available_title_names()
    if available_title_names:
        relations = [
            item
            for item in relations
            if normalize_title_display(item.title_name) in available_title_names
        ]
    relations.sort(
        key=lambda item: (
            SHOWCASE_PRIORITY.get(
                "full_combo_group"
                if item.requirement_type == "full_combo" and len(item.song_names) > 1
                else item.requirement_type,
                99,
            ),
            item.source_row_index,
            item.title_name.casefold(),
        )
    )
    return tuple(relations)

def _levels_for_scope(scope: str) -> Tuple[int, ...]:
    if scope == "inner_oni":
        return (5,)
    if scope == "oni_or_inner_oni":
        return (4, 5)
    if scope == "oni":
        return (4,)
    if scope == "hard":
        return (3,)
    if scope == "normal":
        return (2,)
    if scope == "easy":
        return (1,)
    return (1, 2, 3, 4, 5)

def _record_satisfies(record: Optional[Dict[str, Any]], requirement_type: str) -> bool:
    if not isinstance(record, dict):
        return False
    dondaful = int(record.get("dondaful_combo_cnt", 0) or 0)
    full_combo = int(record.get("full_combo_cnt", 0) or 0)
    clear = int(record.get("clear_cnt", 0) or 0)
    if requirement_type == "all_perfect":
        return dondaful > 0
    if requirement_type == "full_combo":
        return dondaful > 0 or full_combo > 0
    return dondaful > 0 or full_combo > 0 or clear > 0

def _generic_relation_plate_id(requirement_type: str, difficulty_scope: str) -> int:
    if (requirement_type, difficulty_scope) in PLATE_ID_MAP:
        return PLATE_ID_MAP[(requirement_type, difficulty_scope)]
    return PLATE_ID_MAP[(requirement_type, "unspecified")]

def _resolve_relation_plate_id_from_candidates(
    generic_plate_id: int,
    rarity_candidates: Tuple[int, ...],
) -> int:
    fallback_order = PLATE_ID_FALLBACK_ORDER.get(generic_plate_id, (generic_plate_id,))
    for candidate in fallback_order:
        if candidate in rarity_candidates:
            return candidate
    return rarity_candidates[0]

def _relation_plate_id(title_name: str, requirement_type: str, difficulty_scope: str) -> int:
    title_lookup = _load_title_rarity_lookup()
    generic_plate_id = _generic_relation_plate_id(requirement_type, difficulty_scope)
    rarity_candidates = title_lookup.get(normalize_title_display(title_name))
    if rarity_candidates:
        if len(rarity_candidates) == 1:
            resolved_plate_id = rarity_candidates[0]
            if resolved_plate_id == 2 and generic_plate_id in {42, 60}:
                return generic_plate_id
            return resolved_plate_id
        return _resolve_relation_plate_id_from_candidates(
            generic_plate_id,
            rarity_candidates,
        )
    return generic_plate_id

def _relation_showcase_bg_plate_id(title_name: str, resolved_plate_id: int) -> int:
    rarity_candidates = _load_title_rarity_lookup().get(normalize_title_display(title_name))
    if (
        rarity_candidates
        and len(rarity_candidates) == 1
        and rarity_candidates[0] == 2
        and int(resolved_plate_id) in {42, 60}
    ):
        return 2
    return int(resolved_plate_id)

def _showcase_sort_key(item: ShowcaseTitle) -> Tuple[Any, ...]:
    normalized_title = normalize_title_display(item.title_name)
    return (
        SHOWCASE_PRIORITY.get(item.priority_key, 99),
        1
        if item.requirement_type == "full_combo"
        and normalized_title in SHOWCASE_FULL_COMBO_LOWEST_TITLES
        else 1
        if item.requirement_type == "clear"
        and normalized_title in SHOWCASE_CLEAR_LOWEST_TITLES
        else 0,
        -float(item.priority_const_value or 0.0),
        -SCOPE_PRIORITY.get(item.difficulty_scope, 0),
        -len(item.song_names),
        item.title_name.casefold(),
        item.source,
        int(item.custom_title_id or 0),
    )

def _resolve_showcase_priority_const(song_names: Iterable[str], const_value: float) -> float:
    priority_const_value = float(const_value or 0.0)
    for target_song_name, overridden_const_value in SHOWCASE_PRIORITY_CONST_BY_SONG.items():
        target_keys = set(_song_lookup_keys(target_song_name))
        if not target_keys:
            continue
        for song_name in song_names:
            if target_keys.intersection(_song_lookup_keys(song_name)):
                return float(overridden_const_value)
    return priority_const_value

def _collect_song_title_showcase_candidates(
    songs: Iterable[Dict[str, Any]],
) -> List[ShowcaseTitle]:
    title_lookup, const_by_song_level, const_by_title_level, level_by_song_level = _load_song_lookup()
    user_song_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for song in songs:
        if not isinstance(song, dict):
            continue
        try:
            key = (int(song.get("song_no")), int(song.get("level")))
        except Exception:
            continue
        user_song_map[key] = song

    best_by_title: Dict[str, ShowcaseTitle] = {}
    for relation in load_song_title_relations():
        matched_song_ids: List[int] = []
        matched_consts: List[float] = []
        matched_levels: List[int] = []
        scope_levels = _levels_for_scope(relation.difficulty_scope)

        satisfied = True
        for song_name in relation.song_names:
            candidate_ids: Tuple[int, ...] = ()
            seen_song_ids: set[int] = set()
            for lookup_key in _song_lookup_keys(song_name):
                for song_id in title_lookup.get(lookup_key, ()):
                    if song_id in seen_song_ids:
                        continue
                    seen_song_ids.add(song_id)
                    candidate_ids += (song_id,)
            best_match: Optional[Tuple[float, int, int]] = None
            for song_id in candidate_ids:
                best_const_for_song = -1.0
                best_level_for_song = -1
                for level in scope_levels:
                    record = user_song_map.get((song_id, level))
                    if not _record_satisfies(record, relation.requirement_type):
                        continue
                    const_value = float(const_by_song_level.get((song_id, level), 0.0) or 0.0)
                    if const_value <= 0:
                        title_level_const = 0.0
                        for lookup_key in _song_lookup_keys(song_name):
                            title_level_const = max(
                                title_level_const,
                                float(const_by_title_level.get((lookup_key, level), 0.0) or 0.0),
                            )
                        const_value = title_level_const
                    if const_value <= 0:
                        const_value = float(level_by_song_level.get((song_id, level), 0.0) or 0.0)
                    if const_value > best_const_for_song:
                        best_const_for_song = const_value
                        best_level_for_song = level
                if best_const_for_song >= 0:
                    if best_match is None or best_const_for_song > best_match[0]:
                        best_match = (best_const_for_song, song_id, best_level_for_song)
            if best_match is None:
                satisfied = False
                break
            matched_consts.append(best_match[0])
            matched_song_ids.append(best_match[1])
            matched_levels.append(best_match[2])

        if not satisfied:
            continue

        showcase_scope = relation.difficulty_scope
        if relation.requirement_type == "full_combo" and relation.difficulty_scope == "oni_or_inner_oni":
            if matched_levels and all(level == 5 for level in matched_levels):
                showcase_scope = "inner_oni"
            elif matched_levels and all(level == 4 for level in matched_levels):
                showcase_scope = "oni"

        plate_id = _relation_plate_id(
            relation.title_name,
            relation.requirement_type,
            showcase_scope,
        )
        showcase = ShowcaseTitle(
            title_name=relation.title_name,
            plate_id=plate_id,
            requirement_type=relation.requirement_type,
            difficulty_scope=relation.difficulty_scope,
            condition_text=relation.condition_text,
            song_names=relation.song_names,
            song_ids=tuple(matched_song_ids),
            const_value=max(matched_consts) if matched_consts else 0.0,
            priority_const_value=_resolve_showcase_priority_const(
                relation.song_names,
                max(matched_consts) if matched_consts else 0.0,
            ),
            is_multi_song=len(relation.song_names) > 1,
            showcase_bg_plate_id=_relation_showcase_bg_plate_id(
                relation.title_name,
                plate_id,
            ),
        )

        current = best_by_title.get(showcase.title_name)
        if current is None or _showcase_sort_key(showcase) < _showcase_sort_key(current):
            best_by_title[showcase.title_name] = showcase

    return sorted(best_by_title.values(), key=_showcase_sort_key)

def list_song_title_showcase_candidates(
    songs: Iterable[Dict[str, Any]],
    *,
    limit: Optional[int] = None,
) -> List[ShowcaseTitle]:
    songs = list(songs)
    result = _collect_song_title_showcase_candidates(songs)
    try:
        from .custom_title import list_custom_title_showcase_candidates

        result.extend(list_custom_title_showcase_candidates(songs))
    except Exception:
        # 自定义称号数据库故障不应影响既有“我的小咚”生成。
        pass
    result.sort(key=_showcase_sort_key)
    if limit is None:
        return result
    return result[: max(0, int(limit))]

def resolve_song_title_showcase_selection(
    songs: Iterable[Dict[str, Any]],
    title_names: Iterable[str],
    *,
    limit: int = 5,
) -> List[ShowcaseTitle]:
    available = {
        normalize_title_display(item.title_name): item
        for item in list_song_title_showcase_candidates(songs)
    }
    resolved: List[ShowcaseTitle] = []
    seen: set[str] = set()
    for raw_title_name in title_names:
        title_name = normalize_title_display(raw_title_name)
        if not title_name or title_name in seen:
            continue
        item = available.get(title_name)
        if item is None:
            continue
        resolved.append(item)
        seen.add(title_name)
        if len(resolved) >= max(0, int(limit)):
            break
    return resolved

def infer_song_title_showcase(
    songs: Iterable[Dict[str, Any]],
    *,
    limit: int = 5,
) -> List[ShowcaseTitle]:
    resolved_limit = max(0, int(limit))
    if resolved_limit == 0:
        return []

    songs = list(songs)
    official_titles = _collect_song_title_showcase_candidates(songs)
    try:
        from .custom_title import list_custom_title_showcase_candidates

        custom_titles = list_custom_title_showcase_candidates(songs)
    except Exception:
        # 自定义称号数据库故障不应影响“我的小咚”其余内容生成。
        custom_titles = []

    official_song_ids = {
        default_song_id_for_query(song_id) or int(song_id)
        for item in official_titles
        for song_id in item.song_ids
    }
    filtered_custom_titles = [
        item
        for item in custom_titles
        if all(
            (default_song_id_for_query(song_id) or int(song_id))
            not in official_song_ids
            for song_id in item.song_ids
        )
    ]
    earliest_custom_title = min(
        filtered_custom_titles,
        key=lambda item: (
            item.custom_title_id
            if item.custom_title_id is not None
            else 2**63 - 1,
            _showcase_sort_key(item),
        ),
        default=None,
    )
    result = official_titles + (
        [earliest_custom_title] if earliest_custom_title is not None else []
    )
    result.sort(key=_showcase_sort_key)
    return result[:resolved_limit]


def serialize_showcase_titles(titles: Iterable[ShowcaseTitle]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for item in titles:
        payload.append(
            {
                "titleName": item.title_name,
                "plateId": int(item.plate_id),
                "requirementType": item.requirement_type,
                "difficultyScope": item.difficulty_scope,
                "conditionText": item.condition_text,
                "songNames": list(item.song_names),
                "songIds": list(item.song_ids),
                "constValue": float(item.const_value or 0.0),
                "isMultiSong": bool(item.is_multi_song),
                "source": item.source,
                "customTitleId": item.custom_title_id,
                "difficultyLevel": item.difficulty_level,
                "plateStyle": item.plate_style,
            }
        )
    return payload



def clear_song_title_showcase_caches() -> None:
    load_title_catalog_items.cache_clear()
    _load_song_alias_lookup.cache_clear()
    _load_title_rarity_lookup.cache_clear()
    _load_available_title_names.cache_clear()
    _load_song_lookup.cache_clear()
    _load_api_song_title_relations.cache_clear()
    _load_legacy_base_song_title_relations.cache_clear()
    _load_legacy_all_perfect_relations.cache_clear()
    _load_manual_hidden_relations.cache_clear()
    load_song_title_relations.cache_clear()
