"""Load installed runtime owners before importing the remaining legacy host.
Matches the host pyproject order and avoids importing feature_handler outside
NoneBot's plugin manager. No Bot connection or startup hooks are run.
"""
import nonebot


def load_tinfo_owner():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    return nonebot.require('taiko_bot.runtime.player.entry')


def load_community_owner():
    from importlib import import_module
    load_tinfo_owner()
    nonebot.require("taiko_bot.runtime.community.community_entry")
    from types import SimpleNamespace
    modules = [import_module("taiko_bot.runtime.community.center." + n) for n in ("compat", "cover", "draw_guess")]
    from taiko_bot.runtime.player.center.trend_support import parsing
    values = {name: value for module in [parsing, *modules] for name,value in vars(module).items() if name != "__name__"}
    return SimpleNamespace(**values)
