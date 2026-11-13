"""Existing Viewer chart URL; no catalog, publication or network work here."""
import os
import re

from PIL import Image

from .config import root


DIFFICULTIES = {'Kantan': 1, 'Futsuu': 2, 'Muzukashii': 3, 'Oni': 4, 'InnerOni': 5}


def markdown_image(difficulty, song_id):
    if os.getenv('TAIKO_QQ_FIXED_FUMEN_URL', '0') != '1':
        return None
    song_id = str(song_id)
    number = DIFFICULTIES.get(difficulty)
    if number is None or not re.fullmatch(r'[1-9][0-9]{0,9}', song_id):
        return None
    try:
        # Header metadata only: no pixel decode, full PNG read or random copy.
        # Local missing/unreadable images fall back before attempting a send.
        with Image.open(root()/'assets/fumens'/difficulty/f'{song_id}.png') as image:
            if image.format != 'PNG':
                return None
            width, height = image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    url = f'https://viewer.sakura-bot.cn/api/content/songs/{song_id}/chart-image?difficulty={number}'
    return f'![img#{width}px #{height}px]({url})'
