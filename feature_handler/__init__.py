# nonebot_plugin_feature_switch/__init__.py
from nonebot import on_message
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from .bot_group_whitelist import should_block_group_event
from .feature_handler import feature_on, init_db  # 暴露给外部使用
from . import feature_switch_handler  # 确保指令被注册

__plugin_meta__ = PluginMetadata(
    name="Feature Switch",
    description="Per-group feature on/off switch",
    usage="发送：开启pjsk功能 / 关闭taiko功能 等",
)

group_whitelist_guard = on_message(
    priority=1, block=True, rule=Rule(should_block_group_event)
)


@group_whitelist_guard.handle()
async def _silence_blocked_group():
    await group_whitelist_guard.finish()


try:
    from nonebot import get_driver

    @get_driver().on_startup
    async def _init_feature_switch_db() -> None:
        init_db()

except ValueError:
    pass
