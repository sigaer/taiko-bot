from nonebot import get_driver
from nonebot.plugin.manager import PluginLoader

from .config import Config

config = Config()

if isinstance(globals().get("__loader__"), PluginLoader):
    global_config = get_driver().config
    config = Config(**global_config.dict())
    from . import taiko  # noqa: F401
