"""Versioned bounded caches for public catalogs; never use for player files."""
from functools import lru_cache
import json
import hashlib
import time
from pathlib import Path
from sakura_taiko_core.rating.v1 import build_const_table


def revision(path):
    path = Path(path).resolve()
    st = path.stat()
    # Hash only during the short window where filesystem timestamps may alias.
    digest = hashlib.sha256(path.read_bytes()).digest() if time.time_ns()-st.st_ctime_ns < 1_000_000_000 else None
    return str(path), st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns, digest


@lru_cache(maxsize=4)
def _json(key):
    return json.loads(Path(key[0]).read_text(encoding='utf-8'))


def load_public_json(path):
    return _json(revision(path))


@lru_cache(maxsize=4)
def _rating(key):
    config = _json(key)
    consts = build_const_table(config['const_table']['const_to_score'])
    index = {}
    for song in config['songs'].values():
        try:
            identity = int(song.get('id', 0)), int(song.get('level', 0))
        except Exception:
            continue
        index[identity] = song
    return config, index, consts


def rating_resources(path):
    return _rating(revision(path))


@lru_cache(maxsize=4)
def _song_index(key):
    index = {}
    for song in _json(key):
        try:
            index[int(song.get('id', 0))] = song
        except Exception:
            continue
    return index


def song_index(path):
    return _song_index(revision(path))


@lru_cache(maxsize=4)
def _client_groups(key):
    from sakura_taiko_core.chart.client_groups import build_rating_duplicate_groups
    groups = build_rating_duplicate_groups(_json(key))
    return groups, {song_id: index for index, group in enumerate(groups) for song_id in group}


def client_rating_groups(path):
    return _client_groups(revision(path))


def clear():
    _json.cache_clear()
    _rating.cache_clear()
    _song_index.cache_clear()
    _client_groups.cache_clear()
