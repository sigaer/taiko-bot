from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

DIFFICULTY_BY_CLASS = {
    "easy": 1,
    "normal": 2,
    "hard": 3,
    "oni": 4,
    "oni_ura": 5,
}

DEFAULT_HIROBA_SYNC_LEVELS = frozenset({4, 5})

BADGE_NAME_TO_RANK = {
    "rainbow": 8,
    "purple": 7,
    "pink": 6,
    "gold": 5,
    "silver": 4,
    "bronze": 3,
    "white": 2,
}


@dataclass
class HirobaProfile:
    taiko_no: str
    nickname: str = ""
    title: str = ""


@dataclass
class HirobaSongRef:
    song_no: str
    title: str
    levels: Set[int] = field(default_factory=set)


@dataclass
class HirobaScoreDetail:
    song_no: str
    level: int
    title: str = ""
    crown: Optional[str] = None
    badge: Optional[str] = None
    score: int = 0
    ranking: int = 0
    good: int = 0
    ok: int = 0
    bad: int = 0
    max_combo: int = 0
    roll: int = 0
    stage_cnt: int = 0
    clear_cnt: int = 0
    full_combo_cnt: int = 0
    dondaful_combo_cnt: int = 0


def _parse_int(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


def _direct_div_text(node) -> str:
    if node is None:
        return ""
    return node.get_text(" ", strip=True)


def parse_profile(html: str) -> HirobaProfile:
    soup = BeautifulSoup(html, "html.parser")
    mydon = soup.select_one("#mydon_area")
    if mydon is None:
        raise ValueError("mydon_area not found")

    nickname = ""
    title = ""
    direct_divs = mydon.find_all("div", recursive=False)
    if direct_divs:
        title = _direct_div_text(direct_divs[0])
    if len(direct_divs) > 1:
        title_candidates = direct_divs[1].find_all("div", recursive=False)
        if title_candidates:
            nickname = _direct_div_text(title_candidates[0])

    if not nickname or not title:
        lines = [line.strip() for line in mydon.stripped_strings if line.strip()]
        if not title and lines:
            title = lines[0]
        if not nickname and len(lines) > 1:
            nickname = lines[1]

    detail = mydon.select_one(".detail")
    taiko_no = ""
    if detail:
        for p in detail.find_all("p"):
            text = p.get_text(strip=True)
            match = re.search(r"(\d{10,14})", text)
            if match:
                taiko_no = match.group(1)
                break
    if not taiko_no:
        match = re.search(r"太鼓番[：:]\s*(\d+)", mydon.get_text(" ", strip=True))
        if match:
            taiko_no = match.group(1)
    if not taiko_no:
        raise ValueError("Failed to parse taiko number from mypage")
    return HirobaProfile(taiko_no=taiko_no, nickname=nickname, title=title)


def parse_mypage_achievement(html: str) -> Dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.select_one(".total_score")
    if panel is None:
        return {}

    count_level = 1
    panel_img = panel.select_one("img")
    if panel_img and panel_img.get("src"):
        match = re.search(r"total_score_image_(\d+)", panel_img["src"])
        if match:
            count_level = int(match.group(1))

    rank_counts = [0] * 7
    for rank in range(2, 9):
        node = panel.select_one(f".best_rank_score_{rank}")
        rank_counts[rank - 2] = _parse_int(node.get_text()) if node else 0

    silver_node = panel.select_one(".silver_crown_count")
    gold_node = panel.select_one(".gold_crown_count")
    dondaful_node = panel.select_one(
        ".dondaful_crown_count, .donderful_crown_count"
    )
    crown_counts = [
        _parse_int(silver_node.get_text()) if silver_node else 0,
        _parse_int(gold_node.get_text()) if gold_node else 0,
        _parse_int(dondaful_node.get_text()) if dondaful_node else 0,
    ]

    return {
        "count_level": count_level,
        "ary_crown_count": crown_counts,
        "ary_score_rank_count": rank_counts,
    }


def _level_from_link(href: str, class_names: List[str]) -> Optional[int]:
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "level" in qs and qs["level"]:
        try:
            return int(qs["level"][0])
        except ValueError:
            pass
    for class_name in class_names:
        for key, level in DIFFICULTY_BY_CLASS.items():
            if key in class_name:
                return level
    return None


def _is_played_crown_src(src: str) -> bool:
    filename = (src or "").rsplit("/", 1)[-1].lower()
    if not filename.startswith("crown_button_") and not filename.startswith("crown_large_"):
        return False
    return "none" not in filename


def parse_score_list_page(html: str) -> Dict[str, HirobaSongRef]:
    soup = BeautifulSoup(html, "html.parser")
    songs: Dict[str, HirobaSongRef] = {}
    for box in soup.select(".contentBox"):
        title_node = box.select_one(".songName")
        if title_node is None:
            title_node = box.select_one(".songNameArea span")
        if title_node is None:
            continue
        title = title_node.get_text(strip=True)
        button_list = box.select_one(".buttonList")
        if button_list is None:
            continue
        for link in button_list.select("a"):
            href = link.get("href") or ""
            match = re.search(r"song_no=(\d+)", href)
            if not match:
                continue
            crown_img = link.select_one(".crown, img")
            if crown_img is None or not _is_played_crown_src(crown_img.get("src") or ""):
                continue
            song_no = match.group(1)
            class_names = crown_img.get("class") if crown_img is not None else []
            level = _level_from_link(href, class_names or [])
            if level is None:
                continue
            ref = songs.get(song_no)
            if ref is None:
                ref = HirobaSongRef(song_no=song_no, title=title)
                songs[song_no] = ref
            ref.levels.add(level)
            if title:
                ref.title = title
    return songs


def merge_song_refs(items: List[Dict[str, HirobaSongRef]]) -> Dict[str, HirobaSongRef]:
    merged: Dict[str, HirobaSongRef] = {}
    for chunk in items:
        for song_no, ref in chunk.items():
            existing = merged.get(song_no)
            if existing is None:
                merged[song_no] = HirobaSongRef(
                    song_no=ref.song_no,
                    title=ref.title,
                    levels=set(ref.levels),
                )
            else:
                existing.levels.update(ref.levels)
                if ref.title:
                    existing.title = ref.title
    return merged


def _badge_from_src(src: str) -> Optional[str]:
    match = re.search(r"best_score_rank_(\d+)_640", src)
    if not match:
        return None
    rank = match.group(1)
    mapping = {
        "8": "rainbow",
        "7": "purple",
        "6": "pink",
        "5": "gold",
        "4": "silver",
        "3": "bronze",
        "2": "white",
    }
    return mapping.get(rank)


def _crown_from_src(src: str) -> Optional[str]:
    match = re.search(r"crown_(?:large_|button_)?(\d+|\w+)_640", src)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return {"0": "played", "1": "silver", "2": "gold", "3": "dondaful"}.get(token)
    if token in {"played", "silver", "gold", "dondaful", "donderfull", "none"}:
        if token == "none":
            return None
        return "dondaful" if token == "donderfull" else token
    return None


def parse_score_detail(html: str, song_no: str, level: int) -> Optional[HirobaScoreDetail]:
    soup = BeautifulSoup(html, "html.parser")
    content_text = soup.select_one("#content")
    if content_text and "指定されたページは存在しません" in content_text.get_text():
        return None

    title = ""
    title_node = soup.select_one(".songNameTitleScore")
    if title_node:
        title = title_node.get_text(strip=True)

    detail = HirobaScoreDetail(song_no=song_no, level=level, title=title)
    status = soup.select_one(".scoreDetailStatus")
    if status is None or not status.select_one(".crown"):
        return detail

    crown_img = status.select_one(".crown")
    if crown_img and crown_img.get("src"):
        detail.crown = _crown_from_src(crown_img["src"])

    badge_img = status.select_one(".best_score_icon")
    if badge_img and badge_img.get("src"):
        detail.badge = _badge_from_src(badge_img["src"])

    high_score = soup.select(".high_score")
    if high_score:
        detail.score = _parse_int(high_score[0].get_text())

    ranking = soup.select_one(".ranking")
    if ranking:
        detail.ranking = _parse_int(ranking.get_text())

    def _count(selector: str) -> int:
        node = soup.select_one(selector)
        return _parse_int(node.get_text()) if node else 0

    detail.good = _count(".good_cnt")
    detail.ok = _count(".ok_cnt")
    detail.bad = _count(".ng_cnt")
    detail.max_combo = _count(".combo_cnt")
    detail.roll = _count(".pound_cnt")
    detail.stage_cnt = _count(".stage_cnt")
    detail.clear_cnt = _count(".clear_cnt")
    detail.full_combo_cnt = _count(".full_combo_cnt")
    detail.dondaful_combo_cnt = _count(".dondaful_combo_cnt, .dondafull_combo_cnt")
    return detail


def filter_song_refs_by_levels(
    merged: Dict[str, HirobaSongRef], levels: Set[int]
) -> Dict[str, HirobaSongRef]:
    if not levels:
        return merged
    filtered: Dict[str, HirobaSongRef] = {}
    for song_no, ref in merged.items():
        kept_levels = {level for level in ref.levels if level in levels}
        if not kept_levels:
            continue
        filtered[song_no] = HirobaSongRef(
            song_no=ref.song_no,
            title=ref.title,
            levels=kept_levels,
        )
    return filtered


def enumerate_fetch_tasks(
    merged: Dict[str, HirobaSongRef],
    *,
    levels: Optional[Set[int]] = None,
) -> List[Tuple[str, int]]:
    tasks: List[Tuple[str, int]] = []
    for song_no, ref in sorted(merged.items(), key=lambda item: int(item[0])):
        for level in sorted(ref.levels):
            if levels is not None and level not in levels:
                continue
            tasks.append((song_no, level))
    return tasks
