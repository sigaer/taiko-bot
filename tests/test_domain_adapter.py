"""Standalone client adapters use owned catalog modules and pinned domain wheels."""
import pytest
from taiko_bot import domain
from taiko_bot.runtime.player.client.recommendation_support import catalog


def test_pinned_client_versions(monkeypatch):
    domain.assert_domain_versions()
    monkeypatch.setattr(domain, 'version', lambda package: '0.0.0')
    with pytest.raises(RuntimeError, match='version mismatch'):
        domain.assert_domain_versions()


def test_owned_catalog_inputs(monkeypatch):
    from types import SimpleNamespace
    group = SimpleNamespace(default_id=2)
    monkeypatch.setattr(catalog, '_group_cache', lambda: ({}, {1: group}, {}))
    assert domain.identity_inputs()[0] == {1: 2}
    monkeypatch.setattr(catalog, 'load_song_index', lambda: {153: {'id': 153}, 1429: {'id': 1429}})
    assert 153 in domain.visibility_inputs()
    assert 1429 not in domain.visibility_inputs()
