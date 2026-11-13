"""Actual installed QQ/OneBot message models; no platform requests or real IDs."""
import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from nonebot.exception import FinishedException
from PIL import Image
import pytest
from taiko_application.commands import CommandResult
from taiko_bot.static_fumens import StaticFumen


class Capture:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    async def send(self, message):
        self.sent.append(message)
        if self.error:
            raise self.error

    async def finish(self, message=None, **kwargs):
        if message is not None:
            self.sent.append(message)
        raise FinishedException


@pytest.fixture(params=['center', 'client'])
def delivery(request, tmp_path, monkeypatch):
    import taiko_bot
    public = Path(taiko_bot.__file__).parent/'runtime/public'
    name = '_static_delivery_test'
    package = ModuleType(name)
    package.__path__ = [str(public)]
    config = ModuleType(name+'.config')
    config.root, config.profile = lambda: tmp_path, lambda: request.param
    provider = ModuleType(name+'.provider')
    provider.brief, provider.asset_ready = lambda sid: '【测试歌曲】\nBPM：120', lambda: (True, '')
    monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, config.__name__, config)
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    monkeypatch.setenv('TAIKO_BOT_ROOT', str(tmp_path))
    monkeypatch.setenv('TAIKO_RUNTIME_ROOT', str(tmp_path))
    module = importlib.import_module(name+'.delivery')
    import taiko_bot.runtime.center_markdown_media as center_cache
    import taiko_runtime.qq_markdown_media as client_cache
    for cache in (center_cache, client_cache):
        monkeypatch.setattr(cache, 'QQ_MARKDOWN_IMAGE_CACHE_DIR', tmp_path/'cache')
        monkeypatch.setattr(cache, 'QQ_MARKDOWN_IMAGE_BASE_URL', 'https://static.example.test/cache')
    folder = tmp_path/'assets/fumens/Oni'
    folder.mkdir(parents=True)
    with Image.new('RGB', (16, 24), 'red') as image:
        image.save(folder/'1.png')
    entry = StaticFumen('Oni', '1', 'https://static.example.test/approved/sha256/'+('a'*64)+'.png', 16, 24, 'a'*64, 'a'*64)
    monkeypatch.setattr(module.static_fumens, 'lookup', lambda *args: entry)
    yield module, tmp_path, entry, request.param
    for key in tuple(sys.modules):
        if key.startswith(name+'.'):
            sys.modules.pop(key, None)


def invoke(module, capture, platform='qq', result=None):
    event = SimpleNamespace(group_openid='synthetic-group', id='synthetic-id') if platform == 'qq' else SimpleNamespace()
    try:
        asyncio.run(module.deliver(capture, event, result or CommandResult('fumen', ('Oni', '1'))))
    except FinishedException:
        pass


def test_static_hit_is_one_markdown_with_no_png_or_cache(delivery, monkeypatch):
    module, root, entry, profile = delivery
    def forbidden(*args, **kwargs):
        raise AssertionError('static hit attempted PNG/cache IO')
    monkeypatch.setattr(module.provider, 'asset_ready', forbidden)
    monkeypatch.setattr(Image, 'open', forbidden)
    (root/'assets/fumens/Oni/1.png').unlink()
    capture = Capture()
    invoke(module, capture)
    assert len(capture.sent) == 1
    content = capture.sent[0][0].data['markdown'].content
    assert content.startswith('你要找的是不是：\n魔王 id1')
    assert f'![img#16px #24px]({entry.url})' in content
    assert ('【测试歌曲】' in content) == (profile == 'center')
    assert not (root/'cache').exists()


def test_fuzzy_hint_is_preserved(delivery):
    module, _, entry, _ = delivery
    capture = Capture()
    invoke(module, capture, result=CommandResult('fuzzy_fumen', [[1, '猜测歌', 62]], difficulty='Oni'))
    content = capture.sent[0][0].data['markdown'].content
    assert content.startswith('你要找的可能是：猜测歌\n匹配度：0.62')
    assert entry.url in content and len(capture.sent) == 1


def test_manifest_miss_uses_existing_random_cache(delivery, monkeypatch):
    module, root, _, _ = delivery
    monkeypatch.setattr(module.static_fumens, 'lookup', lambda *args: None)
    capture = Capture()
    invoke(module, capture)
    assert len(capture.sent) == 1 and capture.sent[0][0].type == 'markdown'
    assert len(list((root/'cache').glob('*.png'))) == 1


def test_message_preparation_failure_falls_back_before_first_send(delivery, monkeypatch):
    module, root, _, _ = delivery
    from nonebot.adapters.qq import MessageSegment
    original = MessageSegment.markdown
    calls = []
    def prepare(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError('static preparation failed')
        return original(*args, **kwargs)
    monkeypatch.setattr(MessageSegment, 'markdown', prepare)
    capture = Capture()
    invoke(module, capture)
    assert len(capture.sent) == 1 and len(calls) == 2
    assert len(list((root/'cache').glob('*.png'))) == 1


def test_onebot_does_not_consult_static_manifest(delivery, monkeypatch):
    module, root, _, _ = delivery
    monkeypatch.setattr(module.static_fumens, 'lookup', lambda *args: pytest.fail('OneBot looked up static URL'))
    capture = Capture()
    invoke(module, capture, 'onebot')
    assert len(capture.sent) == 1 and any(segment.type == 'image' for segment in capture.sent[0])
    assert not (root/'cache').exists()


@pytest.mark.parametrize('hit', [True, False])
@pytest.mark.parametrize('error', [TimeoutError('uncertain outcome'), RuntimeError('unknown network error')])
def test_send_timeout_or_unknown_never_sends_a_second_message(delivery, monkeypatch, hit, error):
    module, _, _, _ = delivery
    if not hit:
        monkeypatch.setattr(module.static_fumens, 'lookup', lambda *args: None)
    capture = Capture(error)
    with pytest.raises(type(error)):
        invoke(module, capture)
    assert len(capture.sent) == 1


def test_explicit_passive_rejection_preserves_center_proactive_rule(delivery, monkeypatch):
    module, _, _, profile = delivery
    proactive = []
    async def send(matcher, event, message):
        proactive.append(message)
        return True
    monkeypatch.setattr(module.center_messages, '_send_qq_proactive', send)
    capture = Capture(RuntimeError('40034128'))
    if profile == 'center':
        invoke(module, capture)
        assert len(proactive) == 1 and proactive[0] is capture.sent[0]
    else:
        with pytest.raises(RuntimeError):
            invoke(module, capture)
        assert not proactive
    assert len(capture.sent) == 1


def test_explicit_proactive_failure_does_not_fall_back_again(delivery, monkeypatch):
    module, _, _, _ = delivery
    proactive = []
    async def fail(matcher, event, message):
        proactive.append(message)
        return False
    monkeypatch.setattr(module.center_messages, '_send_qq_proactive', fail)
    capture = Capture(RuntimeError('40034128'))
    with pytest.raises(RuntimeError):
        invoke(module, capture)
    assert len(capture.sent) == 1 and len(proactive) <= 1


def test_feature_is_disabled_without_explicit_opt_in(delivery, monkeypatch):
    module, _, _, _ = delivery
    import importlib.util
    path = Path(module.__file__).with_name('static_fumens.py')
    spec = importlib.util.spec_from_file_location(module.__package__+'.disabled_static', path)
    static = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(static)
    monkeypatch.delenv('TAIKO_STATIC_FUMEN_ENABLED', raising=False)
    monkeypatch.setattr(static._store, 'lookup', lambda *a: pytest.fail('disabled feature read metadata'))
    assert static.lookup('Oni', '1') is None


def test_optional_warmup_reuses_existing_provider_and_recovers(delivery, monkeypatch):
    module, _, _, _ = delivery
    warmup = importlib.import_module(module.__package__+'.warmup')
    calls = []
    monkeypatch.setattr(warmup.provider, 'get_snapshot', lambda: calls.append(True), raising=False)
    monkeypatch.delenv('TAIKO_SONG_QUERY_PREWARM', raising=False)
    assert asyncio.run(warmup.prewarm()) is False and not calls
    monkeypatch.setenv('TAIKO_SONG_QUERY_PREWARM', '1')
    assert asyncio.run(warmup.prewarm()) is True and len(calls) == 1
    def fail():
        raise ValueError('bad first catalog')
    monkeypatch.setattr(warmup.provider, 'get_snapshot', fail)
    assert asyncio.run(warmup.prewarm()) is False


def test_warmup_registration_supports_driver_and_offline_builder_import(delivery, monkeypatch):
    module, _, _, _ = delivery
    import nonebot
    warmup = importlib.import_module(module.__package__+'.warmup')
    def absent():
        raise ValueError('NoneBot has not been initialized')
    monkeypatch.setattr(nonebot, 'get_driver', absent)
    assert warmup.register_startup() is False
    hooks = []
    monkeypatch.setattr(nonebot, 'get_driver', lambda: SimpleNamespace(on_startup=hooks.append))
    assert warmup.register_startup() is True and hooks == [warmup.prewarm]
