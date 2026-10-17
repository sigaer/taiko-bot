from taiko_bot.runtime.center_platform_adapter import (
    is_qq_official_group_event,
    is_qq_official_private_event,
)


class _FakeC2CEvent:
    __module__ = "nonebot.adapters.qq.event"


class _FakeGroupAtEvent:
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "group-openid"


def test_qq_official_private_event_detection():
    c2c_event = _FakeC2CEvent()
    group_event = _FakeGroupAtEvent()

    assert is_qq_official_private_event(c2c_event)
    assert not is_qq_official_group_event(c2c_event)
    assert is_qq_official_group_event(group_event)
    assert not is_qq_official_private_event(group_event)
