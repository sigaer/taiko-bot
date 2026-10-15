"""Fail closed: service QA owns all data, credentials and outbound transports."""
import os
import sys
import tempfile
from pathlib import Path
import pytest

_ROOT = Path(tempfile.mkdtemp(prefix="taiko-service-qa-", dir="/var/tmp"))
for key, value in {
    "TAIKO_RUNTIME_ROOT": str(_ROOT), "TAIKO_CENTER_ROOT": str(_ROOT), "TAIKO_RUNTIME_ENV_FILE": str(_ROOT / "absent.env"),
    "TAIKO_USERDATA_DIR": str(_ROOT / "userdata"), "TAIKO_ACCOUNT_CACHE_DIR": str(_ROOT / "cache"),
    "TAIKO_HIROBA_TOKEN_DIR": str(_ROOT / "credentials"), "TAIKO_HIROBA_COOLDOWN_PATH": str(_ROOT / "cooldown.json"),
    "TAIKO_WAHLAP_CONFIG_PATH": str(_ROOT / "config.json"), "TAIKO_DB_USER": "synthetic",
    "TAIKO_DB_PASSWORD": "synthetic", "TAIKO_DB_NAME": "taiko_service_test", "HIROBA_CRED_KEY": "synthetic-qa-key",
}.items(): os.environ[key] = value

(_ROOT / "songs").mkdir()
(_ROOT / "songs/song_data.json").write_text("[]")
(_ROOT / "songs/grade_dojo_nijiiro_2025_simple.json").write_text('{"grades": []}')

def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = os.fsdecode(args[0])
        if path.startswith(("/home/sigaer/taiko/", "/home/sigaer/git/", "/etc/taiko", "/home/sigaer/taiko-bot/storage")):
            raise AssertionError("Production filesystem access forbidden")
    if event == "socket.connect":
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"} or address[1] in {3306, 3307, 6379, 3102, 9999}:
            raise AssertionError("External or production transport forbidden")
    if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "localhost", "::1"}:
        raise AssertionError("External DNS forbidden")

sys.addaudithook(audit)

@pytest.fixture(autouse=True)
def no_production_sql(monkeypatch):
    import pymysql
    def forbidden(*args, **kwargs): raise AssertionError("Native SQL requires a separate isolated integration harness")
    monkeypatch.setattr(pymysql, "connect", forbidden)

def pytest_sessionfinish(session, exitstatus):
    import shutil
    shutil.rmtree(_ROOT)
