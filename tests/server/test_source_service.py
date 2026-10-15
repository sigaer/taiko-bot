"""Real authority/Source acquisition and writer; synthetic SQL and upstream only."""
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from taiko_store import PublicationStore, PublicationError
from taiko_bot.runtime.player.center import source_mutation as source
from taiko_bot.runtime.player.center import viewer_source_authority as authority
from taiko_bot.runtime.player.center import update_user, userdata_storage, daily_ability
from taiko_bot.services import sync_dispatch_server as dispatch
from token_bearer_fixture import synthetic_wahlap

IDENTITY = "114514"
ACTOR = {"kind": "session", "userId": 7, "credential": "a" * 64}
BINDING = {"id": "11", "taiko_id": IDENTITY, "source": "wahlap", "manual_account_id": None}

def request(**changes):
    return dict(scope="wahlap_update", source=IDENTITY, operationId="a" * 32, actor=ACTOR,
                grant={"kind": "owner", "binding": BINDING}, email="", password="",
                includeImage=False, showAll=False) | changes

class SQL:
    def __init__(self):
        self.trace = []; self.sql = ""; self.revoked = False; self.fail_commit = False
        self.binding = ("11", IDENTITY, "wahlap", None)
        self.proofs = 0
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): self.trace.append("cursor_close")
    def execute(self, sql, args=None):
        self.trace.append((sql, args)); self.sql = sql
        if sql.startswith("SELECT id FROM web_user_accounts"): self.proofs += 1
    def fetchone(self):
        if "web_user_accounts" in self.sql: return (7,)
        if "web_user_sessions" in self.sql: return None if self.revoked else (7,)
        if "web_developer_tokens" in self.sql: return ("2", 7) if not self.revoked else None
        if "taiko_source_service_grants" in self.sql: return self.service
        if "web_hiroba_credentials" in self.sql: return None
        raise AssertionError(self.sql)
    def fetchall(self): return [self.binding] if self.binding else []
    def begin(self): self.trace.append("begin")
    def commit(self):
        self.trace.append("commit")
        if self.fail_commit and self.proofs > 1: raise RuntimeError("synthetic late SQL failure")
    def rollback(self): self.trace.append("rollback")
    def close(self): self.trace.append("close")

@pytest.fixture
def acquisition(tmp_path, monkeypatch):
    data = tmp_path / "userdata"; data.mkdir()
    config = tmp_path / "config.json"; config.write_text('{"cookie":"synthetic"}')
    monkeypatch.setenv("TAIKO_WAHLAP_CONFIG_PATH", str(config))
    payload = {"profile": {"userid": IDENTITY}, "songs": [], "achievement": {}}
    synthetic_wahlap(update_user, IDENTITY, payload)
    monkeypatch.setattr(userdata_storage, "_load_locked_song_keys", lambda _: set())
    # Daily adapter still executes its publication hook, with a deterministic measurement.
    monkeypatch.setattr(daily_ability, "capture_snapshot", lambda *a, **kw: None)
    return data, tmp_path / "cache", payload

def run(req, db, fixture):
    data, cache, _ = fixture
    return source.run_source_mutation(req, connection_factory=lambda: db, userdata_root=data, cache_root=cache)

def sequence(data):
    with PublicationStore(data, IDENTITY).shared() as store:
        return store.reader().publication

def test_cold_hot_real_wahlap_writer_counts_and_order(acquisition):
    data, _, _ = acquisition
    for expected in (2, 4):
        db = SQL(); result = run(request(), db, acquisition)
        assert result["sequence"] == expected  # acquisition then dispatcher snapshot, as before
        assert db.trace.count("begin") == 1 and db.trace.count("commit") == 2
        assert "rollback" not in db.trace and db.trace[-1] == "close"
        queries = [sql for sql, _ in (x for x in db.trace if isinstance(x, tuple))]
        assert not queries[0].endswith("FOR UPDATE")
        assert sum(sql.endswith("FOR UPDATE") for sql in queries) >= 9
        with PublicationStore(data, IDENTITY).shared() as store:
            assert len(store.reader().history_names()) == expected
            assert json.loads(store.reader().current_raw())["profile"]["userid"] == IDENTITY

def test_revocation_before_execution_never_writes(acquisition):
    db = SQL(); db.revoked = True
    with pytest.raises(authority.SourceAuthorityError) as error: run(request(), db, acquisition)
    assert error.value.status == 401
    assert "begin" not in db.trace and "rollback" in db.trace
    assert sequence(acquisition[0]) is None

def test_exact_binding_tuple_and_manual_source_rejected(acquisition):
    for binding in [("12", IDENTITY, "wahlap", None), ("11", IDENTITY, "hiroba", None), None]:
        db = SQL(); db.binding = binding
        with pytest.raises(authority.SourceAuthorityError): run(request(), db, acquisition)
    with pytest.raises(authority.SourceAuthorityError): run(request(source="980000000000000001"), SQL(), acquisition)
    assert sequence(acquisition[0]) is None

def test_late_sql_failure_keeps_authorized_file_observations_and_releases_lock(acquisition):
    db = SQL(); db.fail_commit = True
    with pytest.raises(RuntimeError): run(request(), db, acquisition)
    assert "rollback" in db.trace and db.trace[-1] == "close"
    assert sequence(acquisition[0])["sequence"] == 2
    assert run(request(), SQL(), acquisition)["sequence"] == 4

def test_revocation_at_publish_prevents_writer(acquisition, monkeypatch):
    db = SQL()
    original = source.AuthorizedPublicationStore.publish
    def revoked(store, *args, **kwargs):
        db.revoked = True
        return original(store, *args, **kwargs)
    monkeypatch.setattr(source.AuthorizedPublicationStore, "publish", revoked)
    with pytest.raises(authority.SourceAuthorityError): run(request(), db, acquisition)
    assert sequence(acquisition[0]) is None and "rollback" in db.trace

def test_image_sha_exclusive_nonce_and_capacity(acquisition, monkeypatch):
    from taiko_bot.runtime.player.center import draw_dress
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO(); Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    image = buffer.getvalue()
    monkeypatch.setattr(draw_dress, "render_update_changes_image", lambda *a, **kw: image)
    result = run(request(includeImage=True), SQL(), acquisition)
    path = acquisition[1] / "source-render" / ("a" * 32 + ".png")
    assert result["imageHash"] == hashlib.sha256(image).hexdigest()
    assert path.read_bytes() == image and path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): run(request(includeImage=True), SQL(), acquisition)
    monkeypatch.setattr(draw_dress, "render_update_changes_image", lambda *a, **kw: b"")
    with pytest.raises(PublicationError): run(request(includeImage=True), SQL(), acquisition)

def test_concurrent_source_calls_preserve_all_observations(acquisition):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(request(), SQL(), acquisition), range(2)))
    assert sorted(r["sequence"] for r in results) == [2, 4]
    assert sequence(acquisition[0])["sequence"] == 4

def test_private_hiroba_requires_credentials_under_grant(acquisition):
    db = SQL(); db.binding = ("11", IDENTITY, "hiroba", None)
    req = request(scope="hiroba_sync", grant={"kind":"owner", "binding": BINDING | {"source":"hiroba"}})
    with pytest.raises(authority.SourceAuthorityError) as error: run(req, db, acquisition)
    assert error.value.code == "hiroba_credentials_missing" and "rollback" in db.trace

def test_service_policy_exact_revision_scope_source_and_revocation():
    db = SQL(); actor = ACTOR | {"kind":"developer", "tokenId":"2"}
    row = ("1", 7, "synthetic", '["wahlap_update"]', '["114514"]', "b"*32, "active", None, 7)
    db.service = row
    authority.require_source_authority(db, actor, {"kind":"service", "tuple":list(row)}, IDENTITY, "wahlap_update", lock=True)
    for scope, identity, grant in [("hiroba_sync", IDENTITY, row), ("wahlap_update", "999", row), ("wahlap_update", IDENTITY, row[:5]+("c"*32,)+row[6:])]:
        with pytest.raises(authority.SourceAuthorityError): authority.require_source_authority(db, actor, {"kind":"service", "tuple":list(grant)}, identity, scope, lock=True)
    db.revoked = True
    with pytest.raises(authority.SourceAuthorityError): authority.require_source_authority(db, actor, {"kind":"service", "tuple":list(row)}, IDENTITY, "wahlap_update")

def test_service_publication_backup_restore_bytes(acquisition, tmp_path):
    import shutil
    from taiko_store.backup import export_source_backup, restore_source_backup
    run(request(), SQL(), acquisition)
    store=PublicationStore(acquisition[0],IDENTITY)
    with store.exclusive():
        before=store.reader()
        current=hashlib.sha256(before.current_raw()).hexdigest()
        history={name:hashlib.sha256(before.history_raw(name)).hexdigest() for name in before.history_names()}
        export_source_backup(store,"b"*32)
    restored=PublicationStore(tmp_path/"restore",IDENTITY)
    shutil.copytree(store.root/".manual_deleted",restored.root/".manual_deleted")
    with restored.exclusive():
        restore_source_backup(restored,"b"*32,transaction_id="c"*32)
        after=restored.reader()
        assert hashlib.sha256(after.current_raw()).hexdigest()==current
        assert {name:hashlib.sha256(after.history_raw(name)).hexdigest() for name in after.history_names()}==history
