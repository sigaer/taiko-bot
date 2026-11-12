from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from sakura_taiko_core.chart import identity

from .context import SongQueryContext
from .song_matching import normalize_song_query, song_similarity
from .song_phonetics import same_pronunciation


def _collapse(context: SongQueryContext, rows):
    by_id, by_title = (
        context.group_provider()
        if context.group_provider is not None
        else (context.groups_by_id, context.groups_by_title)
    )
    return identity.collapse_query_results_by_group(
        rows, groups_by_id=by_id, groups_by_title=by_title
    )


def _dedupe_by_id(rows: Iterable[list[Any]]) -> list[list[Any]]:
    seen = set()
    result = []
    for row in rows:
        if row[0] not in seen:
            seen.add(row[0])
            result.append(row)
    return result


def _name_hits(songs, query: str, key: Callable[[str], str], *, partial=False):
    hits = []
    for song in songs:
        jp = str(song.get("song_name_jp") or "")
        cn = str(song.get("song_name") or "")
        names = [key(value) for value in (jp, cn) if value]
        if any(query in name if partial else query == name for name in names):
            hits.append([song.get("id"), jp or cn])
    return _dedupe_by_id(hits)


def _alias_identity(entry, id_to_title):
    sid = entry.get("id")
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        pass
    title = entry.get("song_name_jp") or id_to_title.get(sid) or str(sid)
    return sid, title


def _alias_hits(aliases, query: str, id_to_title, key: Callable[[str], str]):
    return _dedupe_by_id(
        list(_alias_identity(entry, id_to_title))
        for entry in aliases
        if any(
            query == key(alias)
            for alias in entry.get("aliases") or []
            if isinstance(alias, str) and alias
        )
    )


def _fuzzy_candidates(context, id_to_title) -> Iterator[tuple[Any, str, str]]:
    for song in context.songs:
        sid = song.get("id")
        title = song.get("song_name_jp") or song.get("song_name") or str(sid)
        for field in ("song_name_jp", "song_name"):
            value = normalize_song_query(str(song.get(field) or ""))
            if value:
                yield sid, title, value
    for entry in context.aliases:
        sid, title = _alias_identity(entry, id_to_title)
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str):
                value = normalize_song_query(alias)
                if value:
                    yield sid, title, value


def query_music(context: SongQueryContext):
    query = (context.query or "").strip()
    if not query:
        return [], None
    query_lower = query.lower()
    query_key = normalize_song_query(query)
    id_to_title = {}
    for song in context.songs:
        try:
            sid = int(song.get("id"))
        except (TypeError, ValueError):
            continue
        id_to_title[sid] = song.get("song_name_jp") or song.get("song_name") or f"ID{sid}"

    # Keep literal names, explicit IDs and literal aliases ahead of normalization.
    hits = _name_hits(context.songs, query_lower, str.lower)
    if hits:
        return _collapse(context, hits), "exact_name"
    id_token = query_key.removeprefix("id")
    if id_token.isdigit() and int(id_token) in id_to_title:
        sid = int(id_token)
        return [[sid, id_to_title[sid]]], "exact_id"
    hits = _alias_hits(context.aliases, query_lower, id_to_title, str.lower)
    if hits:
        return _collapse(context, hits), "exact_alias"

    hits = _name_hits(context.songs, query_key, normalize_song_query)
    if hits:
        return _collapse(context, hits), "exact_name"
    hits = _alias_hits(context.aliases, query_key, id_to_title, normalize_song_query)
    if hits:
        return _collapse(context, hits), "exact_alias"
    if context.allow_partial:
        hits = _name_hits(context.songs, query_key, normalize_song_query, partial=True)
        if hits:
            return _collapse(context, hits), "partial_name"
    if not context.allow_fuzzy:
        return [], None

    phonetic = _dedupe_by_id(
        [sid, title, 90]
        for sid, title, value in _fuzzy_candidates(context, id_to_title)
        if same_pronunciation(query_key, value)
    )
    if phonetic:
        # Preserve every distinct song instead of letting catalog order decide
        # between homophones. Existing callers display the candidate list.
        return _collapse(context, phonetic), "fuzzy"

    # A per-query memo avoids rescoring names repeated across languages and aliases.
    scores = {}
    best = None
    for sid, title, value in _fuzzy_candidates(context, id_to_title):
        if value not in scores:
            scores[value] = song_similarity(
                query_key, value, context.similarity, allow_partial=context.allow_partial
            )
        score = scores[value]
        if best is None or score > best[2]:
            best = [sid, title, score]
    return ([best], "fuzzy") if best is not None else ([], None)
