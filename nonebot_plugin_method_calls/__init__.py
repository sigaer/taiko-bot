from nonebot.plugin import PluginMetadata
from nonebot import get_driver

from .cleanup import register_cleanup_job
from . import recorder  # noqa: F401
from .store import register_store_lifecycle

__plugin_meta__ = PluginMetadata(
    name="Method Calls Stats",
    description="Record bot command invocations into bot.method_calls for help page stats.",
    usage="Auto-loaded; configure via METHOD_CALLS_* environment variables.",
)

try:
    get_driver()
except ValueError:
    pass
else:
    register_store_lifecycle()
    register_cleanup_job()
