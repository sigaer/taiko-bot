# plugin_feature_control.py
from nonebot import get_driver, on_regex
from nonebot.adapters import Event
from nonebot.params import RegexGroup
from nonebot.rule import Rule
from taiko_runtime.platform_adapter import is_qq_official_event, send_text_reply

from .feature_handler import (
    apply_switch,
    is_first_handler,
    resolve_feature_group_key,
    resolve_message_claim_key,
)


def _is_superuser_event(event: Event) -> bool:
    try:
        configured = get_driver().config.superusers
    except Exception:
        configured = set()
    user_id = (
        str(event.get_user_id() or "").strip() if hasattr(event, "get_user_id") else ""
    )
    return user_id in {str(item or "").strip() for item in configured}


def _onebot_sender_role(event: Event) -> str:
    sender = getattr(event, "sender", None)
    if sender is None:
        return ""
    if isinstance(sender, dict):
        role = sender.get("role")
    else:
        role = getattr(sender, "role", None)
    return str(role or "").strip().lower()


async def _group_rule(event: Event) -> bool:
    return (
        getattr(event, "group_id", None) is not None
        or getattr(event, "group_openid", None) is not None
    )


def _can_manage_group_feature(event: Event) -> bool:
    if is_qq_official_event(event) and getattr(event, "group_openid", None) is not None:
        # 官方群事件当前没有稳定的管理员/群主字段，退化为按群作用域允许切换。
        return True
    return _onebot_sender_role(event) in {"owner", "admin"} or _is_superuser_event(event)


switch_cmd = on_regex(
    r"^(开启|关闭)(pjsk|taiko|mai)功能$",
    priority=1,
    block=True,
    rule=Rule(_group_rule),
)


@switch_cmd.handle()
async def _(event: Event, reg_group=RegexGroup()):
    msg_id = resolve_message_claim_key(event)
    if not is_first_handler(msg_id):
        return

    if not _can_manage_group_feature(event):
        await send_text_reply(
            switch_cmd,
            event,
            "仅群管理员、群主或 bot 超级用户可调整本群功能开关。",
        )
        return

    action, feature = reg_group
    enabled = action == "开启"
    group_id = resolve_feature_group_key(event)
    if group_id is None:
        return

    changed = apply_switch(group_id, feature, enabled)
    if changed:
        await send_text_reply(
            switch_cmd,
            event,
            f"已在本群{'开启' if enabled else '关闭'} {feature} 功能。",
        )
        return

    await send_text_reply(
        switch_cmd,
        event,
        f"{feature} 功能已是{'开启' if enabled else '关闭'}状态。",
    )
