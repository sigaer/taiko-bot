"""Compact national song-position index and its query result.

Titles/aliases remain in the existing song catalog. Only category membership,
reference order and unresolved membership are persisted here.
"""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

GENRES = {
    'pops': '流行音乐', 'anime': '动漫音乐', 'kids': '儿童音乐',
    'vocaloid': '博歌乐音乐', 'variety': '综合音乐', 'classic': '古典音乐',
    'game': '游戏音乐', 'namco': '南梦宫原创音乐',
}
INDEX_NAME = 'cn_song_positions.json'
MAX_INDEX_BYTES = 128 * 1024


class PositionIndexUnavailable(ValueError):
    pass


def validate_index(payload):
    if not isinstance(payload, dict) or set(payload) != {'version', 'updated_at', 'categories'} or payload['version'] != 1:
        raise ValueError('Unsupported position index')
    updated = datetime.fromisoformat(payload['updated_at'])
    if updated.tzinfo is None:
        raise ValueError('Position index timestamp needs timezone')
    categories = payload['categories']
    if not isinstance(categories, dict) or set(categories) != set(GENRES.values()):
        raise ValueError('Incomplete position categories')
    membership_count = 0
    for category in categories.values():
        if not isinstance(category, dict) or set(category) != {'ordered', 'pending'}:
            raise ValueError('Invalid category structure')
        seen = set()
        for key in ('ordered', 'pending'):
            values = category[key]
            if not isinstance(values, list):
                raise ValueError('Invalid category IDs')
            for sid in values:
                if type(sid) is not int or sid < 0 or sid in seen:
                    raise ValueError('Invalid or duplicate category ID')
                seen.add(sid)
        membership_count += len(seen)
    if not membership_count:
        raise ValueError('Empty position index')
    return payload


def load_index(path: Path):
    try:
        with path.open('rb') as handle:
            blob = handle.read(MAX_INDEX_BYTES + 1)
        if len(blob) > MAX_INDEX_BYTES:
            raise ValueError('Position index exceeds size limit')
        return validate_index(json.loads(blob))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PositionIndexUnavailable('National position index unavailable') from exc


@dataclass(frozen=True)
class CategoryPosition:
    name: str
    rank: int | None
    ordered_count: int
    pending_count: int


@dataclass(frozen=True)
class NationalPosition:
    song_id: int
    title: str
    categories: tuple[CategoryPosition, ...]


def find_position(payload, song_id, title):
    categories = []
    for name, category in payload['categories'].items():
        ordered, pending = category['ordered'], category['pending']
        if song_id in ordered:
            rank = ordered.index(song_id) + 1
        elif song_id in pending:
            rank = None
        else:
            continue
        categories.append(CategoryPosition(name, rank, len(ordered), len(pending)))
    return NationalPosition(song_id, title, tuple(categories))


def format_national_position(result):
    lines = [f'【{result.title}】id{result.song_id}']
    if not result.categories:
        return '\n'.join(lines + ['当前国行曲表未收录。'])
    for category in result.categories:
        if category.rank is None:
            lines.append(f'{category.name}：位置待确认')
            continue
        reverse = category.ordered_count - category.rank + 1
        lines.append(f'{category.name}：参考第 {category.rank} / {category.ordered_count}（倒数第 {reverse}）')
        if category.pending_count:
            lines.append(f'该分类另有 {category.pending_count} 首位置待确认。')
    return '\n'.join(lines)
