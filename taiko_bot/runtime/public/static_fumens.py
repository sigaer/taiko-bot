"""Public-song-only opt-in; other image senders never import this module."""
import os
from taiko_bot.static_fumens import StaticFumenStore
from .config import root

_store = StaticFumenStore()


def lookup(difficulty, song_id):
    if os.environ.get('TAIKO_STATIC_FUMEN_ENABLED') != '1':
        return None
    return _store.lookup(root(), os.environ.get('TAIKO_STATIC_FUMEN_BASE_URL', ''), difficulty, song_id)
