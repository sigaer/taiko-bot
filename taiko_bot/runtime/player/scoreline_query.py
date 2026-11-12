"""Resolve difficulty-looking aliases using the existing host parser."""

from dataclasses import replace
import re


def song_choice_message(rows):
    choices = '\n'.join(f'id{row[0]} {row[1]}' for row in rows[:20])
    return f'你要找的可能是：\n{choices}\n请用歌曲 id 或更完整的别名查询。'


def resolve_scoreline_query(text, parse_request, query_with_mode, difficulty_prefixes):
    request = parse_request(text)
    normalized = re.sub(r'\s+', ' ', text.strip())
    marker = '__taiko_song_query__'
    for prefix, level, _ in difficulty_prefixes:
        if level != request.level:
            continue
        raw_query = prefix + request.song_query
        if raw_query not in normalized:
            continue
        # Ask the real parser to verify that this span is the complete song
        # argument. This also preserves its rating/evaluation validation.
        try:
            intact = parse_request(normalized.replace(raw_query, marker, 1))
        except ValueError:
            continue
        if intact.song_query != marker:
            continue
        rows, _ = query_with_mode(raw_query, allow_partial=False, allow_fuzzy=False)
        if rows:
            return replace(intact, song_query=raw_query), rows
    return request, query_with_mode(request.song_query)[0]
