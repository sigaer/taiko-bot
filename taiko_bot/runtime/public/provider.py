import json
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity
from taiko_application.query import SongQueryContext
from .config import profile, root
from .resolve import resolve_query
from .catalog import catalog_request, get_snapshot


def query_with_mode(query, **kwargs):
    if profile() == 'client':
        from .client_provider import _query_music_with_mode
        return _query_music_with_mode(query, **kwargs)
    return get_snapshot().query(query, fuzz.ratio, **kwargs)


def resolve(raw, stripped):
    with catalog_request():
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
    index = get_snapshot().index
    sid = int(song_id)
    text = index.briefs.get(sid, '')
    if sid in index.untitled_ids:
        text = f'【ID{song_id}】' + text[len(f'【ID{sid}】'):]
    return text


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
    if profile() == 'center':
        from taiko_bot.song_positions import INDEX_NAME, find_position, load_index
        payload = load_index(root() / 'songs' / INDEX_NAME)
        rows = json.loads((root() / 'songs/song_data.json').read_text(encoding='utf-8'))
        row = next((row for row in rows if row.get('id') == int(song_id)), None)
        if row is None:
            return None
        title = row.get('song_name') or row.get('song_name_jp') or f'ID{song_id}'
        return find_position(payload, int(song_id), title)
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
