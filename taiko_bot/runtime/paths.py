"""Runtime data root shared by Bot and standalone services.

Service launchers set TAIKO_RUNTIME_ROOT (or use the existing runtime working
 directory). No data is created or moved by resolving this path.
"""
import os
from pathlib import Path


def root():
    from nonebot import get_driver
    try:
        config = get_driver().config
    except ValueError:
        return Path(os.environ.get("TAIKO_RUNTIME_ROOT", ".")).resolve()
    if getattr(config, "taiko_song_profile", "center") == "client":
        from taiko_bot.settings import get_settings
        return get_settings().root_dir
    return Path(getattr(config, "taiko_song_public_root", ".")).resolve()
