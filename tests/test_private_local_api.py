import httpx
import pytest
from starlette.testclient import TestClient, _TestClientTransport

from taiko_bot import local_api
from test_private_read_cache import cfg, transport


class OwnedAppClient(TestClient):
    def send(self, request, **kwargs):
        # Explicit ASGI transport only; the guarded validator forbids sockets.
        assert isinstance(self._transport, _TestClientTransport)
        return self._send_single_request(request)


@pytest.mark.parametrize("kind", ["current", "history"])
def test_actual_local_api_never_lends_configured_service_credentials_to_anonymous_callers(cfg, monkeypatch, kind):
    monkeypatch.setattr(local_api, "get_settings", lambda: cfg)
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "snapshots": []}))
    app = local_api.create_app()
    path = "/v1/userdata/1001" + ("/history" if kind == "history" else "")
    with OwnedAppClient(app) as client:
        for headers in [{}, {"authorization": "Basic secret"}, {"authorization": "Bearer short"}]:
            response = client.get(path, headers=headers)
            assert response.status_code == 401
        assert not calls
        response = client.get(path, headers={"authorization": "Bearer " + "a" * 24})
        assert response.status_code == 200
        assert calls[0].headers["authorization"] == "Bearer " + "a" * 24
        assert cfg.viewer_developer_token not in calls[0].headers["authorization"]


@pytest.mark.parametrize("kind", ["current", "history"])
def test_local_api_revocation_propagates_403_instead_of_stale_cache_or_404(cfg, monkeypatch, kind):
    monkeypatch.setattr(local_api, "get_settings", lambda: cfg)
    state = {"status": 200}
    calls = transport(monkeypatch, lambda request: httpx.Response(state["status"], json={"songs": [], "snapshots": []}, headers={"etag": '"taiko-' + kind + '-v1-' + "a" * 64 + '"'}))
    app = local_api.create_app()
    path = "/v1/userdata/1001" + ("/history" if kind == "history" else "")
    with OwnedAppClient(app) as client:
        assert client.get(path, headers={"authorization": "Bearer " + "a" * 24}).status_code == 200
        state["status"] = 403
        denied = client.get(path, headers={"authorization": "Bearer " + "a" * 24})
        assert denied.status_code == 403 and len(calls) == 2
