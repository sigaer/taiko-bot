from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from sakura_taiko_core.chart import identity
from .context import SongQueryContext


def _collapse(context, rows):
    by_id, by_title = (
        context.group_provider()
        if context.group_provider is not None
        else (context.groups_by_id, context.groups_by_title)
    )
    return identity.collapse_query_results_by_group(
        rows, groups_by_id=by_id, groups_by_title=by_title
    )


def query_music(context: SongQueryContext):
    song_data, alias_data = context.songs, context.aliases
    name = context.query
    allow_partial, allow_fuzzy = context.allow_partial, context.allow_fuzzy
    query = (name or "").strip()
    if not query:
        return ([], None)
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
        return (_collapse(context, exact_name_hits), "exact_name")
    id_token = query_lower
    if id_token.startswith("id"):
        id_token = id_token[2:]
    id_token = id_token.strip()
    if id_token.isdigit():
        target_id = int(id_token)
        if target_id in id_to_title:
            return ([[target_id, id_to_title[target_id]]], "exact_id")
    exact_alias_hits: List[List[Any]] = []
    for entry in alias_data:
        aliases = entry.get("aliases") or []
        sid = entry.get("id")
        try:
            sid_int = int(sid)
        except Exception:
            sid_int = sid
        for alias in aliases:
            if isinstance(alias, str) and query_lower == alias.lower():
                title = (
                    entry.get("song_name_jp") or id_to_title.get(sid_int) or str(sid)
                )
                exact_alias_hits.append([sid_int, title])
                break
    exact_alias_hits = _dedupe_by_id(exact_alias_hits)
    if exact_alias_hits:
        return (_collapse(context, exact_alias_hits), "exact_alias")
    if allow_partial:
        partial_name_hits: List[List[Any]] = []
        for music in song_data:
            jp = str(music.get("song_name_jp") or "")
            cn = str(music.get("song_name") or "")
            jp_lower = jp.lower()
            cn_lower = cn.lower()
            if (
                jp_lower
                and query_lower in jp_lower
                or (cn_lower and query_lower in cn_lower)
            ):
                partial_name_hits.append([music.get("id"), jp or cn])
        partial_name_hits = _dedupe_by_id(partial_name_hits)
        if partial_name_hits:
            return (_collapse(context, partial_name_hits), "partial_name")
    if not allow_fuzzy:
        return ([], None)
    best_match: Optional[Dict[str, Any]] = None
    for music in song_data:
        sid = music.get("id")
        title = music.get("song_name_jp") or music.get("song_name") or str(sid)
        candidates = [
            str(music.get("song_name_jp") or "").lower(),
            str(music.get("song_name") or "").lower(),
        ]
        scores = [context.similarity(query_lower, cand) for cand in candidates if cand]
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
            ratio = context.similarity(query_lower, alias.lower())
            if best_match is None or ratio > best_match["ratio"]:
                best_match = {"id": sid, "title": title, "ratio": ratio}
    if best_match is None:
        return ([], None)
    return ([[best_match["id"], best_match["title"], best_match["ratio"]]], "fuzzy")
