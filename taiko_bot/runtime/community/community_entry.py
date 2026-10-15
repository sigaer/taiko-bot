"""Register once under the existing Taiko runtime package."""
from importlib import import_module
from nonebot import require
require('taiko_bot.runtime.public')
require('taiko_bot.runtime.player.entry')
from ..public.config import profile
for name in ('compat', 'draw_guess', 'cover') + (('annual',) if profile() == 'center' else ()):
    import_module(f'.{profile()}.{name}', __package__)
