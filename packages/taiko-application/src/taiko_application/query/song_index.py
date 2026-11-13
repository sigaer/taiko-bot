"""Immutable, finite-catalog search preparation. No IO or query-result cache.

Keep the legacy unindexed query as an independent oracle/API fallback. Tuples
retain catalog order, raw ID types, duplicate-ID first hits and fuzzy tie order.
Only compact search fields survive preparation; full chart trees are not held.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sakura_taiko_core.chart import identity

from .song import _alias_identity, _dedupe_by_id
from .song_matching import normalize_song_query, song_similarity
from .song_phonetics import _is_han, _tokens


def _freeze_hits(values):
    return MappingProxyType({key: tuple(tuple(row) for row in _dedupe_by_id(rows))
                             for key, rows in values.items()})


@dataclass(frozen=True)
class SongIndex:
    literal_names: Mapping
    literal_aliases: Mapping
    normalized_names: Mapping
    normalized_aliases: Mapping
    id_to_title: Mapping
    briefs: Mapping
    untitled_ids: frozenset
    names: tuple
    fuzzy_candidates: tuple
    phonetics_by_length: Mapping
    groups_by_id: Mapping
    groups_by_title: Mapping

    def _collapse(self, rows):
        return identity.collapse_query_results_by_group(
            rows, groups_by_id=self.groups_by_id, groups_by_title=self.groups_by_title)

    def query(self, context):
        query = (context.query or '').strip()
        if not query:
            return [], None
        literal, normalized = query.lower(), normalize_song_query(query)
        rows = self.literal_names.get(literal)
        if rows:
            return self._collapse(rows), 'exact_name'
        token = normalized.removeprefix('id')
        if token.isdigit() and int(token) in self.id_to_title:
            sid = int(token)
            return [[sid, self.id_to_title[sid]]], 'exact_id'
        for table, key, mode in (
            (self.literal_aliases, literal, 'exact_alias'),
            (self.normalized_names, normalized, 'exact_name'),
            (self.normalized_aliases, normalized, 'exact_alias'),
        ):
            rows = table.get(key)
            if rows:
                return self._collapse(rows), mode
        if context.allow_fuzzy and any(map(_is_han, normalized)):
            tokens = _tokens(normalized)
            rows = _dedupe_by_id(
                [sid, title, 90]
                for sid, title, candidate in self.phonetics_by_length.get(len(normalized), ())
                if all(left & right for left, right in zip(tokens, candidate)))
            if rows:
                return self._collapse(rows), 'fuzzy'
        if context.allow_partial:
            rows = _dedupe_by_id([sid, title] for sid, title, names in self.names
                                 if any(normalized in name for name in names))
            if rows:
                return self._collapse(rows), 'partial_name'
        if not context.allow_fuzzy:
            return [], None
        scores, best = {}, None
        for sid, title, value in self.fuzzy_candidates:
            if value not in scores:
                scores[value] = song_similarity(normalized, value, context.similarity,
                                                allow_partial=context.allow_partial)
            score = scores[value]
            if best is None or score > best[2]:
                best = [sid, title, score]
        return ([best], 'fuzzy') if best is not None else ([], None)


def build_song_index(songs, aliases, *, collapse_versions=False):
    normalized_pool = {}
    def normalized_text(value):
        normalized = normalize_song_query(value)
        return normalized_pool.setdefault(normalized, normalized)
    id_to_title, briefs, untitled_ids = {}, {}, set()
    for row in songs:
        try:
            sid = int(row.get('id'))
        except (TypeError, ValueError):
            continue
        id_to_title[sid] = row.get('song_name_jp') or row.get('song_name') or f'ID{sid}'
        if row.get('song_name_jp') or row.get('song_name'):
            untitled_ids.discard(sid)
        else:
            untitled_ids.add(sid)
        title = str(id_to_title[sid]).strip()
        category, bpm = str(row.get('type') or '').strip(), str(row.get('bpm') or '').strip()
        briefs[sid] = '\n'.join(part for part in (
            f'【{title}】' if title else '', f'分类：{category}' if category else '',
            f'BPM：{bpm}' if bpm else '') if part)
    literal_names, normalized_names, literal_aliases, normalized_aliases = {}, {}, {}, {}
    names, candidates = [], []
    for row in songs:
        sid = row.get('id')
        jp, cn = str(row.get('song_name_jp') or ''), str(row.get('song_name') or '')
        normalized = tuple(normalized_text(value) for value in (jp, cn) if value)
        names.append((sid, jp or cn, normalized))
        for value in (jp, cn):
            if value:
                literal_names.setdefault(value.lower(), []).append([sid, jp or cn])
                normalized_names.setdefault(normalized_text(value), []).append([sid, jp or cn])
        # Fuzzy display title deliberately retains the old fallback/type behavior.
        title = row.get('song_name_jp') or row.get('song_name') or str(sid)
        candidates.extend((sid, title, value) for value in normalized if value)
    for entry in aliases:
        sid, title = _alias_identity(entry, id_to_title)
        for value in entry.get('aliases') or []:
            if isinstance(value, str):
                normalized = normalized_text(value)
                if value:
                    literal_aliases.setdefault(value.lower(), []).append([sid, title])
                    normalized_aliases.setdefault(normalized, []).append([sid, title])
                if normalized:
                    candidates.append((sid, title, normalized))
    phonetics, character_tokens = {}, {}
    for sid, title, value in candidates:
        if any(map(_is_han, value)):
            # Legacy phonetics are defined character-by-character, without word
            # context. Share immutable character sets across the finite catalog
            # instead of keeping another full-title LRU of repeated sets.
            for char in value:
                if char not in character_tokens:
                    character_tokens[char] = _tokens(char)[0]
            tokens = tuple(character_tokens[char] for char in value)
            phonetics.setdefault(len(value), []).append((sid, title, tokens))
    by_id, by_title = {}, {}
    if collapse_versions:
        _, by_id, by_title = identity.build_group_maps(songs)
    return SongIndex(
        _freeze_hits(literal_names), _freeze_hits(literal_aliases),
        _freeze_hits(normalized_names), _freeze_hits(normalized_aliases),
        MappingProxyType(id_to_title), MappingProxyType(briefs), frozenset(untitled_ids), tuple(names), tuple(candidates),
        MappingProxyType({key: tuple(rows) for key, rows in phonetics.items()}),
        MappingProxyType(by_id), MappingProxyType(by_title))
