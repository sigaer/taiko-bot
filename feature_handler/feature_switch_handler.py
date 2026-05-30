# plugin_feature_control.py
from nonebot import on_regex
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import (
    GROUP_ADMIN,
    GROUP_OWNER,
    GroupMessageEvent,
    MessageSegment,
)
from nonebot.params import RegexGroup
from nonebot.permission import SUPERUSER
from taiko_runtime.platform_adapter import (
    get_group_key,
    get_message_claim_key,
    is_onebot_group_message_event,
)

from .feature_handler import apply_switch, is_first_handler


async def _onebot_group_rule(event) -> bool:
    return is_onebot_group_message_event(event)


switch_cmd = on_regex(
    r"^(开启|关闭)(pjsk|taiko|mai)功能$",
    priority=1,
    block=True,
    rule=Rule(_onebot_group_rule),
    permission=SUPERUSER | GROUP_OWNER | GROUP_ADMIN,
)


@switch_cmd.handle()
async def _(event: GroupMessageEvent, reg_group=RegexGroup()):
    msg_id = get_message_claim_key(event=event)
    if not is_first_handler(msg_id):
        return

    action, feature = reg_group
    enabled = action == "开启"
    group_id = get_group_key(event=event)
    if group_id is None:
        return

    changed = apply_switch(group_id, feature, enabled)
    print(changed)

    if changed:
        await switch_cmd.finish(
            MessageSegment.text(
                f"已在本群{'开启' if enabled else '关闭'} {feature} 功能。"
            )
        )
