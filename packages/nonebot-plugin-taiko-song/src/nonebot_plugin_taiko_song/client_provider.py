from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart.visibility import is_song_publicly_visible
from .config import root

SONG_DATA_PATH=root()/"songs/song_data.json"

def load_song_data(*, include_hidden: bool = False):
    """读取 song_data.json（dict 列表）"""
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if include_hidden or not isinstance(payload, list):
        return payload
    return [
        item
        for item in payload
        if isinstance(item, dict) and is_song_publicly_visible(item)
    ]

def _query_music_with_mode(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> Tuple[List[List[Any]], Optional[str]]:
    alias_data = json.loads((root()/"songs/song_alias.json").read_text(encoding="utf-8"))
    song_data = load_song_data()
    query = (name or "").strip()
    if not query:
        return [], None
    query_lower = query.lower()

    id_to_title: Dict[int, str] = {}
    for music in song_data:
        try:
            sid = int(music.get("id"))
        except Exception:
            continue
        title = music.get("song_name_jp") or music.get("song_name") or f"ID{sid}"
        id_to_title[sid] = title

    def _dedupe_by_id(rows: List[List[Any]]) -> List[List[Any]]:
        seen = set()
        out: List[List[Any]] = []
        for row in rows:
            if not row:
                continue
            sid = row[0]
            if sid in seen:
                continue
            seen.add(sid)
            out.append(row)
        return out

    # 1) 精准匹配全名（song_name_jp / song_name，不区分大小写）
    exact_name_hits: List[List[Any]] = []
    for music in song_data:
        jp = str(music.get("song_name_jp") or "")
        cn = str(music.get("song_name") or "")
        jp_lower = jp.lower()
        cn_lower = cn.lower()
        if query_lower == jp_lower or query_lower == cn_lower:
            exact_name_hits.append([music.get("id"), jp or cn])
    exact_name_hits = _dedupe_by_id(exact_name_hits)
    if exact_name_hits:
        return exact_name_hits, "exact_name"

    # 2) 精准匹配 id（兼容 id 前缀）
    id_token = query_lower
    if id_token.startswith("id"):
        id_token = id_token[2:]
    id_token = id_token.strip()
    if id_token.isdigit():
        target_id = int(id_token)
        if target_id in id_to_title:
            return [[target_id, id_to_title[target_id]]], "exact_id"

    # 3) 精准匹配别名（不区分大小写）
    exact_alias_hits: List[List[Any]] = []
    for entry in alias_data:
        aliases = entry.get("aliases") or []
        sid = entry.get("id")
        try:
            sid_int = int(sid)
        except Exception:
            sid_int = sid
        if not is_song_id_publicly_visible(sid_int):
            continue
        for alias in aliases:
            if isinstance(alias, str) and query_lower == alias.lower():
                title = (
                    entry.get("song_name_jp") or id_to_title.get(sid_int) or str(sid)
                )
                exact_alias_hits.append([sid_int, title])
                break
    exact_alias_hits = _dedupe_by_id(exact_alias_hits)
    if exact_alias_hits:
        return exact_alias_hits, "exact_alias"

    # 4) 全名部分匹配（输入是曲名连续子串，不区分大小写）
    if allow_partial:
        partial_name_hits: List[List[Any]] = []
        for music in song_data:
            jp = str(music.get("song_name_jp") or "")
            cn = str(music.get("song_name") or "")
            jp_lower = jp.lower()
            cn_lower = cn.lower()
            if (jp_lower and query_lower in jp_lower) or (
                cn_lower and query_lower in cn_lower
            ):
                partial_name_hits.append([music.get("id"), jp or cn])
        partial_name_hits = _dedupe_by_id(partial_name_hits)
        if partial_name_hits:
            return partial_name_hits, "partial_name"

    if not allow_fuzzy:
        return [], None

    # 5) 模糊匹配（返回单条，并附带匹配度）
    best_match: Optional[Dict[str, Any]] = None

    for music in song_data:
        sid = music.get("id")
        title = music.get("song_name_jp") or music.get("song_name") or str(sid)
        candidates = [
            str(music.get("song_name_jp") or "").lower(),
            str(music.get("song_name") or "").lower(),
        ]
        scores = [fuzz.ratio(query_lower, cand) for cand in candidates if cand]
        if not scores:
            continue
        ratio = max(scores)
        if best_match is None or ratio > best_match["ratio"]:
            best_match = {"id": sid, "title": title, "ratio": ratio}

    for entry in alias_data:
        sid = entry.get("id")
        if str(sid).isdigit():
            sid_as_int = int(sid)
            title = entry.get("song_name_jp") or id_to_title.get(sid_as_int) or str(sid)
        else:
            title = entry.get("song_name_jp") or str(sid)
        aliases = entry.get("aliases") or []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            ratio = fuzz.ratio(query_lower, alias.lower())
            if best_match is None or ratio > best_match["ratio"]:
                best_match = {"id": sid, "title": title, "ratio": ratio}

    if best_match is None:
        return [], None
    return [[best_match["id"], best_match["title"], best_match["ratio"]]], "fuzzy"

def is_song_id_publicly_visible(song_id):
    from sakura_taiko_core.chart.visibility import is_song_id_publicly_visible as visible
    rows=load_song_data(include_hidden=True)
    index={int(row["id"]):row for row in rows if isinstance(row,dict) and str(row.get("id", "")).isdigit()}
    return visible(song_id,song_index=index)
