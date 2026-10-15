from pathlib import Path
from nonebot import get_driver


def profile():
    value = getattr(get_driver().config, 'taiko_song_profile', 'center')
    if value not in ('center', 'client'):
        raise ValueError('taiko_song_profile must be center or client')
    return value


from taiko_bot.runtime.paths import root
