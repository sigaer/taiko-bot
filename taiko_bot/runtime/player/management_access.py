"""Shared public catalog access for Taiko settings and query commands."""
import json
from ..public.config import root, profile
from ..public.provider import query_with_mode, rejected_fuzzy

def queryMusic(query):
    return query_with_mode(query)[0]

def load_song_data(*, include_hidden=False):
    payload = json.loads((root() / 'songs/song_data.json').read_text(encoding='utf-8'))
    if profile() == 'center' or include_hidden or not isinstance(payload,list):
        return payload
    from sakura_taiko_core.chart.visibility import is_song_publicly_visible
    return [row for row in payload if isinstance(row,dict) and is_song_publicly_visible(row)]
