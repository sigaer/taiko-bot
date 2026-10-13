from pathlib import Path
from nonebot import get_driver


def profile():
    value = getattr(get_driver().config, 'taiko_song_profile', 'center')
    if value not in ('center', 'client'):
        raise ValueError('taiko_song_profile must be center or client')
    return value


def root():
    if profile() == 'client':
        from taiko_bot.settings import get_settings
        return get_settings().root_dir
    return Path(getattr(get_driver().config, 'taiko_song_public_root', '.')).resolve()
