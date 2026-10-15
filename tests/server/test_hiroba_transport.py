from __future__ import annotations

import requests

from taiko_bot.runtime.player.center.hiroba.client import HirobaClient


def test_hiroba_client_normalizes_environment_proxy(monkeypatch):
    monkeypatch.delenv("HIROBA_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:33233")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7897/")

    client = HirobaClient(timeout=5)

    assert client.session.trust_env is False
    assert client.session.proxies == {
        "http": "http://127.0.0.1:33233",
        "https": "http://127.0.0.1:33233",
    }


def test_hiroba_login_falls_back_to_direct_after_env_proxy_ssl_error(monkeypatch):
    monkeypatch.delenv("HIROBA_PROXY", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:33233")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7897/")

    client = HirobaClient(timeout=5)
    attempts: list[str] = []

    def fake_login_once(self: HirobaClient, _email: str, _password: str) -> str:
        transport = self.session.proxies.get("https") or "direct"
        attempts.append(transport)
        if transport != "direct":
            raise requests.exceptions.SSLError("EOF occurred in violation of protocol")
        return "https://oauth.example/start"

    monkeypatch.setattr(HirobaClient, "_login_to_bandainamco_once", fake_login_once)

    assert client._login_to_bandainamco("user@example.com", "secret") == "https://oauth.example/start"
    assert attempts == ["http://127.0.0.1:33233", "direct"]
