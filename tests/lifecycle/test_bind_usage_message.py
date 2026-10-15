from __future__ import annotations

import importlib

import nonebot


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


class _FakeQQOfficialEvent:
    __module__ = "nonebot.adapters.qq.event"

    def get_user_id(self):
        return "user-openid"


def test_bind_usage_message_explains_private_verified_qq_migration():
    taiko = _load_taiko_module()
    text = taiko._taiko_bind_usage_message(_FakeQQOfficialEvent())

    assert "Sakura Taiko 模块" in text
    assert "私聊旧 bot 发送“迁移验证码”" in text
    assert "绑定QQ QQ号 验证码" in text
    assert "十分钟内有效" in text
    assert "绑定hiroba 邮箱 密码 [太鼓番]" in text
