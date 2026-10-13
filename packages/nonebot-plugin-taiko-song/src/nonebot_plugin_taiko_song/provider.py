import json
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity
from taiko_application.query import SongQueryContext, query_music
from .config import profile, root
from .resolve import resolve_query


def query_with_mode(query, **kwargs):
    if profile() == 'client':
        from .client_provider import _query_music_with_mode
        return _query_music_with_mode(query, **kwargs)
    aliases = json.loads((root()/'songs/song_alias.json').read_text(encoding='utf-8'))
    songs = json.loads((root()/'songs/song_data.json').read_text(encoding='utf-8'))
    def groups():
        _, by_id, by_title = identity.build_group_maps(songs)
        return by_id, by_title
    return query_music(SongQueryContext(songs=songs, aliases=aliases,
        groups_by_id={}, groups_by_title={}, group_provider=groups,
        similarity=fuzz.ratio, query=query, **kwargs))


def resolve(raw, stripped):
    return resolve_query(raw, stripped, query_with_mode)


def rejected_fuzzy(rows):
    fuzzy = bool(rows) and len(rows) == 1 and len(rows[0]) >= 3 and isinstance(rows[0][2], (int, float))
    if not fuzzy:
        return False
    value = float(rows[0][2])
    if value > 1:
        value /= 100
    return profile() == 'client' or value < .75


def brief(song_id):
    rows = json.loads((root()/'songs/song_data.json').read_text(encoding='utf-8'))
    index = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            sid = int(row.get('id'))
        except Exception:
            continue
        index[sid] = row
    row = index.get(int(song_id))
    if not row:
        return ''
    title = str(row.get('song_name_jp') or row.get('song_name') or f'ID{song_id}').strip()
    category = str(row.get('type') or '').strip()
    bpm = str(row.get('bpm') or '').strip()
    return '\n'.join(x for x in (f'【{title}】' if title else '', f'分类：{category}' if category else '', f'BPM：{bpm}' if bpm else '') if x)


def asset_ready():
    if profile() == 'client':
        from taiko_bot.public_data import ensure_asset_resource_available
        from taiko_bot.settings import get_settings
        return ensure_asset_resource_available(('fumens-assets',), get_settings())
    return True, ''


def aliases(song_id):
    if profile() == 'client':
        from .client_provider import is_song_id_publicly_visible
        if not is_song_id_publicly_visible(song_id):
            return '', []
    payload = json.loads((root()/'songs/song_alias.json').read_text(encoding='utf-8'))
    if profile() == 'client':
        for entry in payload:
            if str(entry.get('id')) == str(song_id):
                return entry.get('song_name_jp') or '', entry.get('aliases') or []
        return '', []
    from taiko_application.query import query_aliases
    by_id, by_title = {}, {}
    if isinstance(payload, list):
        songs = json.loads((root()/'songs/song_data.json').read_text(encoding='utf-8'))
        _, by_id, by_title = identity.build_group_maps(songs)
    title, values, _ = query_aliases(SongQueryContext(songs=(), aliases=payload,
        groups_by_id=by_id, groups_by_title=by_title, similarity=lambda a,b:0,
        song_id=song_id, explicit_alias_id=False))
    return title, values


def position(song_id):
    from sakura_taiko_core.chart import position as core
    rows = json.loads((root()/'songs/song_data.json').read_text(encoding='utf-8'))
    options = {'profile': 'position-client-20261010'} if profile() == 'client' else {}
    catalog = core.build_song_catalog(rows, **options)
    return core.get_song_position_by_id(song_id, catalog=catalog, **options)


def note_counts():
    with (root()/'songs/tja_note_counts.json').open('r') as handle:
        return json.load(handle)


def alias_assets_ready():
    if profile() == 'client':
        from taiko_bot.public_data import ensure_asset_resource_available
        from taiko_bot.settings import get_settings
        return ensure_asset_resource_available(('core-assets',), get_settings())
    return True, ''
