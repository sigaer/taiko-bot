from __future__ import annotations

import importlib


def _load_sync_module():
    return importlib.import_module("taiko_bot.runtime.player.center.display_settings")


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_load_web_mydon_showcase_title_overrides_preserves_slot_order(monkeypatch):
    sync_module = _load_sync_module()

    connection = _FakeConnection(
        [
            ("full", "  紫薔薇の融合  "),
            ("full", "赤薔薇の福音"),
            ("full", "紫薔薇の融合"),
            ("full", ""),
        ]
    )

    titles = sync_module.load_web_mydon_showcase_settings("2258735", connection_factory=lambda: connection).title_overrides

    assert titles == ("紫薔薇の融合", "赤薔薇の福音")
    assert connection.cursor_obj.executed is not None
    assert connection.cursor_obj.executed[1] == ("2258735",)
    assert connection.closed is True


def test_load_web_mydon_showcase_settings_keeps_layout_and_order(monkeypatch):
    sync_module = _load_sync_module()
    connection = _FakeConnection(
        [("full_gold", "称号A"), ("full_gold", "称号B")]
    )

    settings = sync_module.load_web_mydon_showcase_settings("2258735", connection_factory=lambda: connection)

    assert settings.showcase_layout == "full_gold"
    assert settings.title_overrides == ("称号A", "称号B")


def test_settings_connection_failure_keeps_default_layout():
    module = _load_sync_module()
    def unavailable():
        raise RuntimeError('isolated connection failure')
    result = module.load_web_mydon_showcase_settings('111', connection_factory=unavailable)
    assert result == module.WebMyDonShowcaseSettings()


def test_settings_query_failure_closes_connection_and_keeps_defaults(monkeypatch):
    module = _load_sync_module()
    connection = _FakeConnection([])
    def unavailable(*args):
        raise RuntimeError('isolated SELECT failure')
    monkeypatch.setattr(connection.cursor_obj, 'execute', unavailable)
    result = module.load_web_mydon_showcase_settings('111', connection_factory=lambda: connection)
    assert result == module.WebMyDonShowcaseSettings()
    assert connection.closed
