import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def launcher():
    spec = importlib.util.spec_from_file_location('taiko_screen_test', Path(__file__).parents[1] / 'scripts/taiko_screen.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_busy_screen_is_never_interrupted_or_replaced(monkeypatch):
    module = launcher()
    calls = []
    monkeypatch.setattr(module, 'prepare', lambda: None)
    monkeypatch.setattr(module, 'session', lambda: ('1.taiko', 2))
    monkeypatch.setattr(module, 'children', lambda _: [3])
    monkeypatch.setattr(module, 'owned_nb', lambda _: False)
    monkeypatch.setattr(module, 'run', lambda *args, **kw: calls.append(args))
    with pytest.raises(RuntimeError, match='not idle'):
        module.start()
    with pytest.raises(RuntimeError, match='another foreground command'):
        module.stop()
    assert calls == []


def test_other_listener_prevents_second_bot(monkeypatch):
    module = launcher()
    calls = []
    monkeypatch.setattr(module, 'prepare', lambda: None)
    monkeypatch.setattr(module, 'session', lambda: ('1.taiko', 2))
    monkeypatch.setattr(module, 'children', lambda _: [])
    def run(*args, **kw):
        calls.append(args)
        return SimpleNamespace(stdout='LISTEN another owner' if args[0] == 'ss' else '')
    monkeypatch.setattr(module, 'run', run)
    with pytest.raises(RuntimeError, match='port still occupied'):
        module.start()
    assert not any(args[0] == 'screen' for args in calls)


def test_prepare_keeps_installed_entry_and_refuses_user_files(tmp_path, monkeypatch):
    module = launcher()
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    module.prepare()
    entry = tmp_path / 'bot.py'
    assert entry.is_symlink()
    assert entry.resolve().is_relative_to('/opt/taiko-bot/releases')
    assert (tmp_path / 'pyproject.toml').read_text().startswith('# Runtime launcher metadata only')
    module.prepare()  # Idempotent; release-pointer symlink remains authoritative.
    (tmp_path / 'pyproject.toml').write_text('user metadata')
    with pytest.raises(RuntimeError, match='refusing to overwrite'):
        module.prepare()
    assert (tmp_path / 'pyproject.toml').read_text() == 'user metadata'


def test_foreign_regular_bot_file_is_preserved(tmp_path, monkeypatch):
    module = launcher()
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    (tmp_path / 'bot.py').write_text('# user bot')
    with pytest.raises(RuntimeError, match='refusing to overwrite user code'):
        module.prepare()
    assert (tmp_path / 'bot.py').read_text() == '# user bot'
