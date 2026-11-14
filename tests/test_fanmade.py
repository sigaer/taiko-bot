"""Offline API/command checks; no business data or outbound messages."""
import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from taiko_bot import fanmade


def result(page=1, total=13):
    return {"items": [{"id": "a" * 32, "title": "测试曲", "maker": "测试谱师",
        "difficulties": [{"course": "Oni", "side": "single", "level": 10},
                         {"course": "Edit", "side": "p1", "level": 9}]}],
        "page": page, "pageSize": 12, "total": total}


@pytest.mark.parametrize("text,expected", [
    ("查自制神威", ("神威", 1)), (" /查自制 神威 ", ("神威", 1)),
    ("太鼓 查自制 神威 第2页", ("神威", 2)),
    ("TAIKO 查自制 A & B? #1 第3页", ("A & B? #1", 3)),
    ("查自制 123", ("123", 1)),
])
def test_parse(text, expected):
    assert fanmade.parse_query(text) == expected


@pytest.mark.parametrize("text", ["查自制", "查自制 第2页", "查自制 神威 第0页",
    "查自制 神威 第9999999页", "查自制 " + "a" * 101, "其他命令"])
def test_invalid_query(text):
    with pytest.raises(ValueError):
        fanmade.parse_query(text)


def mock_http(monkeypatch, handler):
    factory = httpx.AsyncClient
    monkeypatch.setattr(fanmade.httpx, "AsyncClient", lambda **kwargs:
        factory(transport=httpx.MockTransport(handler), **kwargs))


def test_api_encoding_and_pagination(monkeypatch):
    def handler(request):
        assert str(request.url).startswith(fanmade.API_URL + "?")
        assert dict(request.url.params) == {"q": "神 & ?#1", "page": "2"}
        return httpx.Response(200, json=result(page=2))
    mock_http(monkeypatch, handler)
    data = asyncio.run(fanmade.search("神 & ?#1", 2))
    text = fanmade.format_result("神 & ?#1", data)
    assert "第 2/2 页" in text and "13. 测试曲" in text
    assert "测试谱师" in text and "魔王★10" in text and "里谱双打P1★9" in text
    assert fanmade.SITE_URL + "/charts/" + "a" * 32 in text
    assert "下一页" not in text


@pytest.mark.parametrize("mode", ["503", "timeout", "json", "schema", "oversize", "difficulty"])
def test_remote_errors(monkeypatch, mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("offline timeout", request=request)
        if mode == "503":
            return httpx.Response(503)
        if mode == "json":
            return httpx.Response(200, content=b"<html>upstream unavailable</html>")
        if mode == "oversize":
            return httpx.Response(200, content=b" " * (1024 * 1024 + 1))
        payload = result()
        if mode == "schema":
            payload["pageSize"] = 0
        else:
            payload["items"][0]["difficulties"] = 42
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handler)
    with pytest.raises(fanmade.FanmadeUnavailable):
        asyncio.run(fanmade.search("神威"))


def test_empty_and_next_page():
    assert "下一页：查自制 神威 第2页" in fanmade.format_result("神威", result())
    empty = {"items": [], "page": 1, "pageSize": 12, "total": 0}
    assert "未找到" in fanmade.format_result("神威", empty)
    empty.update(page=99, total=13)
    assert "共 13 条、2 页" in fanmade.format_result("神威", empty)


def test_bounded_text():
    payload = result()
    item = payload["items"][0]
    item.update(title="长标题\n" * 100, maker="长谱师\n" * 100,
                difficulties=[{"course": "Edit", "level": 10, "side": "p1"}] * 15)
    payload["items"] = [item] * 12
    assert len(fanmade.format_result("a" * 100, payload)) < 3500


@pytest.fixture
def entry(tmp_path, monkeypatch):
    import nonebot
    import taiko_bot
    monkeypatch.chdir(tmp_path)
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init(_env_file=None, log_level="ERROR")
    name = "_fanmade_command_test"
    package = ModuleType(name)
    package.__path__ = [str(Path(taiko_bot.__file__).parent / "runtime/public")]
    delivery = ModuleType(name + ".delivery")
    delivery.reply = AsyncMock()
    delivery.transport = lambda: SimpleNamespace(
        extract_plain_text=lambda event: event.text,
        is_qq_official_event=lambda event: hasattr(event, "group_openid"))
    # Load the real feature rules without registering the host plugin/startup DB.
    feature_package = ModuleType("feature_handler")
    feature_package.__path__ = [str(Path(taiko_bot.__file__).parent.parent / "feature_handler")]
    for module in (package, delivery, feature_package):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    feature = importlib.import_module("feature_handler.feature_handler")
    monkeypatch.setattr(feature, "is_group_allowed", lambda *args: True)
    monkeypatch.setattr(feature, "is_feature_enabled", lambda *args, **kwargs: True)
    module = importlib.import_module(name + ".fanmade_commands")
    yield module, delivery, feature
    sys.modules.pop(module.__name__, None)


@pytest.mark.parametrize("official", [False, True])
def test_command_uses_shared_reply(entry, monkeypatch, official):
    module, delivery, _ = entry
    event = SimpleNamespace(text="/查自制 神威", get_message=lambda: [])
    if official:
        event.group_openid = "synthetic-group"
    lookup = AsyncMock(return_value=result())
    monkeypatch.setattr(fanmade, "search", lookup)
    asyncio.run(module.fanmade_handle("matcher", event))
    lookup.assert_awaited_once_with("神威", 1)
    assert "测试曲" in delivery.reply.await_args.args[2]


def test_command_failure_and_usage(entry, monkeypatch):
    module, delivery, _ = entry
    lookup = AsyncMock(side_effect=fanmade.FanmadeUnavailable)
    monkeypatch.setattr(fanmade, "search", lookup)
    event = SimpleNamespace(text="查自制", get_message=lambda: [])
    asyncio.run(module.fanmade_handle("matcher", event))
    lookup.assert_not_awaited()
    assert "用法" in delivery.reply.await_args.args[2]
    event.text = "查自制 神威"
    asyncio.run(module.fanmade_handle("matcher", event))
    assert "暂时不可用" in delivery.reply.await_args.args[2]


@pytest.mark.parametrize("disabled", ["taiko", "tsearch"])
def test_feature_rules_block_disabled_commands(entry, monkeypatch, disabled):
    module, _, feature = entry
    monkeypatch.setattr(feature, "is_feature_enabled", lambda group, name, **kw: name != disabled)
    event = SimpleNamespace(group_id=123, self_id="synthetic-bot")
    from nonebot.rule import RegexRule
    checks = [checker.call for checker in module.fanmade_search.rule.checkers
              if not isinstance(checker.call, RegexRule)]
    assert not all(asyncio.run(check(event)) for check in checks)
