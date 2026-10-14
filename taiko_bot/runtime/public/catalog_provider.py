"""Read-only public catalog inputs and fixed host presentation profiles."""
import json
from functools import lru_cache
from taiko_application.query import ConstantQueryContext, PaginationContext
from taiko_application.query import constant
from .config import root, profile

@lru_cache(maxsize=1)
def _load_song_index():
    with (root()/'songs/song_data.json').open(encoding='utf-8') as handle:
        songs = json.load(handle)
    return {int(s['id']):s for s in songs if s.get('id') is not None}

@lru_cache(maxsize=1)
def _load_rating_entries():
    with (root()/'songs/rating_structured_with_ids.json').open(encoding='utf-8') as handle:
        payload = json.load(handle)
    songs = payload.get('songs') or {}
    return list(songs.values()) if isinstance(songs,dict) else songs if isinstance(songs,list) else []

def query_charts_by_const(value, *, include_shelf_status=False):
    index = _load_song_index()
    entries = _load_rating_entries()
    if profile() == 'client':
        from sakura_taiko_core.chart.visibility import is_song_publicly_visible
        # Client visibility precedes projection; do not apply the center shelf profile.
        selected=[]
        for chart in entries:
            score=constant._to_float(chart.get('score'))
            if score is None or abs(score-value)>=1e-6:
                continue
            try:
                sid=int(chart.get('id'));int(chart.get('level'))
            except (TypeError,ValueError):
                continue
            if include_shelf_status or is_song_publicly_visible(index.get(sid),song_id=sid):
                selected.append(chart)
        entries=selected
        include_shelf_status=True
    return constant.query_charts_by_const(ConstantQueryContext(index,entries,value,include_shelf_status))

def paginate_rows(rows, *, page, page_size=25):
    return constant.paginate_rows(PaginationContext(rows,page,page_size))

def pattern_data():
    relative = 'songs/analyze_result_filtered.json'
    try:
        with (root()/relative).open(encoding='utf-8') as handle:
            return json.load(handle)
    except OSError as error:
        # Keep the old public input filename in propagated diagnostics.
        error.filename = relative
        raise

def renderer():
    if profile()=='center':
        from . import constant_center_renderer as renderer
    else:
        from . import constant_client_renderer as renderer
    return renderer
