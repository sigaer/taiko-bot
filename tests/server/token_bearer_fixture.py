"""Actual token/acquisition modules, synthetic remote services and owned roots.

The SQL integration harness replaces only the connection factory with a guarded
native PyMySQL connection. No Bot registration or production credentials load.
"""
import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
import taiko_bot.runtime.player.center as _owner
OWNED = Path(_owner.__file__).parent


def load_token_modules(name="bearer_fixture", source=None, *, synthetic_song_locks=True):
    package = types.ModuleType(name)
    package.__path__ = [str(OWNED)]
    hiroba = types.ModuleType(name + ".hiroba")
    hiroba.__path__ = []
    client = types.ModuleType(name + ".hiroba.client")
    client.HirobaError = type("HirobaError", (Exception,), {})
    cooldown = types.ModuleType(name + ".hiroba.cooldown")
    cooldown.peek_hiroba_sync_cooldown = lambda _identity: None
    credentials = types.ModuleType(name + ".hiroba.credentials")
    credentials.load_hiroba_credentials = lambda _identity: None
    sync = types.ModuleType(name + ".hiroba.sync")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Remote Hiroba services are synthetic in bearer QA")
    sync.sync_bound_hiroba_userdata = forbidden
    modules = {module.__name__: module for module in (package, hiroba, client, cooldown, credentials, sync)}
    token = types.ModuleType(name + ".public_score_token")
    token.__package__ = name
    modules[token.__name__] = token
    with patch.dict(sys.modules, modules), patch("taiko_bot.runtime.player.center.runtime_env.load_runtime_environment"):
        update = importlib.import_module(name + ".update_user")
        storage = importlib.import_module(name + ".userdata_storage")
        exec(compile(source or (OWNED / "public_score_token.py").read_text(),
                     str(OWNED / "public_score_token.py"), "exec"), token.__dict__)
    daily = types.ModuleType(name + ".daily_ability")
    daily.capture_snapshot = lambda *_args, **_kwargs: None
    modules.update({token.__name__: token, update.__name__: update, storage.__name__: storage,
                    daily.__name__: daily})
    if synthetic_song_locks:
        storage._load_locked_song_keys = lambda _identity: set()
    return token, update, storage, modules


def synthetic_wahlap(update, identity, payload):
    def response(data):
        return types.SimpleNamespace(status_code=200, json=lambda: json.loads(json.dumps(data)))
    def post(url, **kwargs):
        assert kwargs.get("timeout") == (5, 30), "Actual acquisition HTTP needs bounded timeouts"
        if url.endswith("/all/songs"):
            assert str(kwargs["json"]["userid"]) == identity
            return response({"message": "ok", "data": {"playedRecords": {"scoreInfo": payload.get("songs", [])}}})
        assert url.endswith("/search/player")
        return response({"data": {"players": [payload["profile"]]}})
    def get(url, **kwargs):
        assert kwargs.get("timeout") == (5, 30)
        assert url.endswith("/" + identity)
        return response({"data": payload.get("achievement", {})} if "/achievement/" in url else {"data": []})
    update.requests = types.SimpleNamespace(post=post, get=get)


def load_http_server(token):
    modules = {"plugins": types.ModuleType("plugins"), "taiko_bot.runtime.player.center": types.ModuleType("taiko_bot.runtime.player.center"),
               "taiko_bot.runtime.player.center.public_score_token": token}
    server = types.ModuleType("bearer_http_fixture")
    from taiko_bot.services import public_api
    server.__file__ = public_api.__file__
    with patch.dict(sys.modules, modules):
        exec(compile(Path(server.__file__).read_text(), server.__file__, "exec"), server.__dict__)
    return server
