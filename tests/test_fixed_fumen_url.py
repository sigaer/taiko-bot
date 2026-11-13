"""Official QQ center delivery only; actual QQ message models, no network."""
import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from nonebot.exception import FinishedException
from PIL import Image
import pytest
from taiko_application.commands import CommandResult


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


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    import taiko_bot
    name = '_fixed_fumen_test'
    package = ModuleType(name)
    package.__path__ = [str(Path(taiko_bot.__file__).parent/'runtime/public')]
    config = ModuleType(name+'.config')
    config.root, config.profile = lambda: tmp_path, lambda: 'center'
    provider = ModuleType(name+'.provider')
    provider.brief, provider.asset_ready = lambda sid: '【测试歌曲】\nBPM：120', lambda: (True, '')
    for module in (package, config, provider):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv('TAIKO_QQ_FIXED_FUMEN_URL', '1')
    module = importlib.import_module(name+'.delivery')
    import taiko_bot.runtime.center_markdown_media as cache
    monkeypatch.setattr(cache, 'QQ_MARKDOWN_IMAGE_CACHE_DIR', tmp_path/'cache')
    monkeypatch.setattr(cache, 'QQ_MARKDOWN_IMAGE_BASE_URL', 'https://static.example.test/cache')
    for difficulty in module.fumen_url.DIFFICULTIES:
        folder = tmp_path/'assets/fumens'/difficulty
        folder.mkdir(parents=True)
        with Image.new('RGB', (16, 24), 'red') as image:
            image.save(folder/'1.png')
    yield module, tmp_path
    for key in tuple(sys.modules):
        if key.startswith(name+'.'):
            sys.modules.pop(key, None)


def invoke(module, capture, result=None):
    event = SimpleNamespace(group_openid='synthetic-group', id='synthetic-id')
    try:
        asyncio.run(module.deliver(capture, event, result or CommandResult('fumen', ('Oni', '1'))))
    except FinishedException:
        pass


@pytest.mark.parametrize('difficulty,label,number', [
    ('Kantan', '简单', 1), ('Futsuu', '普通', 2), ('Muzukashii', '困难', 3),
    ('Oni', '魔王', 4), ('InnerOni', '里谱', 5)])
def test_fixed_hit_preserves_hint_and_difficulty_without_full_read_or_write(delivery, monkeypatch, difficulty, label, number):
    module, root = delivery
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('full PNG read'))
    monkeypatch.setattr(Image.Image, 'load', lambda *a: pytest.fail('pixel decode'))
    monkeypatch.setattr(module.provider, 'asset_ready', lambda: pytest.fail('fallback'))
    capture = Capture()
    invoke(module, capture, CommandResult('fumen', (difficulty, '1')))
    assert len(capture.sent) == 1
    content = capture.sent[0][0].data['markdown'].content
    assert content == (f'你要找的是不是：\n{label} id1\n【测试歌曲】\nBPM：120\n\n'
        f'![img#16px #24px](https://viewer.sakura-bot.cn/api/content/songs/1/chart-image?difficulty={number})')
    assert not (root/'cache').exists()


def test_fuzzy_hint_preserved(delivery):
    module, _ = delivery
    capture = Capture()
    invoke(module, capture, CommandResult('fuzzy_fumen', [[1, '猜测歌', 62]], difficulty='Oni'))
    assert len(capture.sent) == 1
    assert capture.sent[0][0].data['markdown'].content.startswith('你要找的可能是：猜测歌\n匹配度：0.62\n【测试歌曲】')


@pytest.mark.parametrize('sid', ['../1', '1?x=2', '0', '-1', '01', '1/2', '1\n', 'https://evil.test', '999999999999999'])
def test_id_validation(delivery, sid):
    assert delivery[0].fumen_url.markdown_image('Oni', sid) is None


@pytest.mark.parametrize('difficulty', ['../Oni', '', 'oni', '6'])
def test_difficulty_validation(delivery, difficulty):
    assert delivery[0].fumen_url.markdown_image(difficulty, '1') is None


@pytest.mark.parametrize('state', ['missing', 'broken', 'not-png'])
def test_unavailable_image_falls_back_before_send(delivery, monkeypatch, state):
    module, root = delivery
    path = root/'assets/fumens/Oni/1.png'
    if state == 'missing':
        path.unlink()
    elif state == 'broken':
        path.write_bytes(b'broken')
    else:
        with Image.new('RGB', (16, 24)) as image:
            image.save(path, format='JPEG')
    assert module.fumen_url.markdown_image('Oni', '1') is None
    ready = []
    monkeypatch.setattr(module.provider, 'asset_ready', lambda: (ready.append(True) or True, ''))
    capture = Capture()
    invoke(module, capture)
    assert ready == [True] and len(capture.sent) == 1
    if state != 'missing':
        assert 'https://static.example.test/cache/' in capture.sent[0][0].data['markdown'].content


def test_default_off_uses_original_random_cache(delivery, monkeypatch):
    module, root = delivery
    monkeypatch.delenv('TAIKO_QQ_FIXED_FUMEN_URL')
    capture = Capture()
    invoke(module, capture)
    assert len(capture.sent) == 1 and len(list((root/'cache').glob('*.png'))) == 1


def test_construction_failure_falls_back_before_send(delivery, monkeypatch):
    from nonebot.adapters.qq import MessageSegment
    module, root = delivery
    original = MessageSegment.markdown
    calls = []
    def prepare(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise ValueError('pre-send construction failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(MessageSegment, 'markdown', prepare)
    capture = Capture()
    invoke(module, capture)
    assert len(capture.sent) == 1 and len(calls) == 2
    assert len(list((root/'cache').glob('*.png'))) == 1


@pytest.mark.parametrize('enabled', ['0', '1'])
@pytest.mark.parametrize('error', [TimeoutError('unknown outcome'), RuntimeError('unknown transport error')])
def test_attempted_send_never_falls_back(delivery, monkeypatch, enabled, error):
    module, _ = delivery
    monkeypatch.setenv('TAIKO_QQ_FIXED_FUMEN_URL', enabled)
    capture = Capture(error)
    with pytest.raises(type(error)):
        invoke(module, capture)
    assert len(capture.sent) == 1


def test_known_passive_rejection_preserves_existing_proactive_rule(delivery, monkeypatch):
    module, _ = delivery
    proactive = []
    async def send(matcher, event, message):
        proactive.append(message)
        return True
    monkeypatch.setattr(module.transport(), '_send_qq_proactive', send)
    capture = Capture(RuntimeError('40034128'))
    invoke(module, capture)
    assert len(capture.sent) == len(proactive) == 1
