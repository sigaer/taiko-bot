"""Real bearer/canonical/acquisition behavior without production DB or HTTP."""
import io
import ast
import logging
import json
import os
import subprocess
import tempfile
import types
import unittest
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from pathlib import Path
from unittest.mock import patch

from taiko_store import PublicationError, PublicationStore
from token_bearer_fixture import ROOT, OWNED, load_http_server, load_token_modules, synthetic_wahlap

TOKEN = "a" * 48
IDENTITY = "114514"


class Clock(datetime):
    @classmethod
    def utcnow(cls):
        return cls(2026, 10, 11, 16, 0, 0)


class FakeDb:
    def __init__(self):
        self.row = (42, IDENTITY)
        self.queries = []
        self.commits = self.begins = self.rollbacks = self.closed = self.used = 0
        self.fail_rollback = False
        self.on_query = self.on_commit = None

    def cursor(self):
        return self

    def execute(self, sql, args):
        self.queries.append(sql)
        if self.on_query:
            self.on_query(sql)
        if sql.startswith("UPDATE public_score_tokens"):
            self.used += 1

    def fetchone(self):
        return self.row

    def begin(self):
        self.begins += 1

    def commit(self):
        self.commits += 1
        if self.on_commit:
            self.on_commit()

    def rollback(self):
        self.rollbacks += 1
        self.used = 0
        if self.fail_rollback:
            raise RuntimeError("Synthetic failed rollback")

    def close(self):
        self.closed += 1


class BearerPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token, cls.update, cls.storage, cls.modules = load_token_modules()
        frozen = (ROOT / "fixtures/public_score_token_legacy.py").read_text()
        cls.frozen, _, _, cls.frozen_modules = load_token_modules("bearer_frozen", frozen)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="token-bearer-", dir="/var/tmp")
        self.root = Path(self.temporary.name)
        self.data = self.root / "userdata"
        self.data.mkdir()
        self.config = self.root / "wahlap.json"
        self.config.write_text('{"cookie":"synthetic-public-cookie"}')
        self.db = FakeDb()
        self.active = patch.dict("sys.modules", self.modules | self.frozen_modules)
        self.active.start()
        self.environment = patch.dict(os.environ, {"TAIKO_USERDATA_DIR": str(self.data), "TAIKO_WAHLAP_CONFIG_PATH": str(self.config)})
        self.environment.start()
        self.patches = []
        for module in (self.token, self.frozen):
            for name, value in {"USERDATA_DIR": self.data, "ensure_public_score_token_table": lambda: None,
                                "get_taiko_db_connection": lambda: self.db, "datetime": Clock,
                                "load_hiroba_credentials": lambda _identity: None,
                                "getUserData": lambda *_args, **_kwargs: 0,
                                "sync_bound_hiroba_userdata": lambda *_args, **_kwargs: IDENTITY}.items():
                p = patch.object(module, name, value)
                p.start()
                self.patches.append(p)
        self.payload = {"profile": {"userid": IDENTITY, "mydon_name": "Synthetic 鼓众"},
                        "_meta": {"source": "wahlap"}, "songs": [], "achievement": {"ary_crown_count": [1, 0, 0]}, "dojo": {}}
        self.store = PublicationStore(self.data, IDENTITY)
        with self.store.exclusive():
            self.store.commit({"current": json.dumps(self.payload, ensure_ascii=False).encode(), "history/data_initial.json": b'{}'})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.environment.stop()
        self.active.stop()
        self.temporary.cleanup()

    def fetch(self, token=TOKEN):
        return self.token.fetch_latest_userdata_by_token(token)

    def test_complete_healthy_bearer_dto_matches_frozen_6a90c7e(self):
        self.assertEqual(self.fetch(), self.frozen.fetch_latest_userdata_by_token(TOKEN))
        self.assertEqual(self.db.used, 2)

    def test_projection_loss_and_tamper_do_not_change_complete_bearer_dto(self):
        expected = self.fetch()
        projection = self.data / (IDENTITY + "data.json")
        projection.unlink()
        self.assertEqual(self.fetch(), expected)
        projection.write_text('{"profile":{"userid":"foreign"},"private":"wrong"}')
        self.assertEqual(self.fetch(), expected)

    def test_canonical_corruption_is_not_masked_by_refresh_or_projection(self):
        with self.store.shared():
            reference = self.store.view()["files"]["current"]
        (self.store.objects / reference["sha256"]).write_bytes(b"corrupt")
        calls = []
        with patch.object(self.token, "getUserData", side_effect=lambda *_args, **_kwargs: calls.append(True)):
            with self.assertRaises(self.token.PublicScoreTokenError) as error:
                self.fetch()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(calls, [])
        self.assertEqual(self.db.used, 0)
        self.assertNotIn(str(self.root), str(error.exception))

    def test_missing_canonical_object_is_not_recovered_from_a_valid_projection(self):
        with self.store.shared():
            reference = self.store.view()["files"]["current"]
        (self.store.objects / reference["sha256"]).unlink()
        with self.assertRaises(self.token.PublicScoreTokenError) as error:
            self.fetch()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.db.used, 0)

    def test_invalid_bearer_shape_never_connects_or_reads_source(self):
        with patch.object(self.token, "get_taiko_db_connection", side_effect=AssertionError("DB forbidden")):
            for token in (None, "", "x" * 10000, "A" * 48, "abc", {}):
                with self.subTest(kind=type(token).__name__), self.assertRaises(self.token.PublicScoreTokenError):
                    self.fetch(token)

    def test_leading_and_trailing_whitespace_keep_existing_token_semantics(self):
        self.assertEqual(self.fetch("  " + TOKEN + "\n"), self.fetch())

    def test_missing_or_unsafe_token_source_is_rejected_before_private_reads(self):
        for row in (None, (42, "../foreign"), (42, "98" + "1" * 16), (42, None), (42, 114514)):
            self.db.row = row
            with self.subTest(row=bool(row)), self.assertRaises(self.token.PublicScoreTokenError) as error:
                self.fetch()
            self.assertEqual(error.exception.status_code, 401)
        self.assertEqual(self.db.begins, 0)

    def test_full_token_identity_is_proved_after_source_ex_before_private_reads(self):
        def change(sql):
            if sql.endswith("FOR UPDATE"):
                self.db.row = (43, IDENTITY)
        self.db.on_query = change
        with patch.object(self.token, "_load_local_userdata", side_effect=AssertionError("Private reads forbidden")):
            with self.assertRaises(self.token.PublicScoreTokenError) as error:
                self.fetch()
        self.assertEqual(error.exception.status_code, 401)
        self.assertEqual(self.db.used, 0)

    def test_return_proof_checks_the_full_token_identity_again(self):
        def change(sql):
            if sql.endswith("FOR UPDATE") and sum(q.endswith("FOR UPDATE") for q in self.db.queries) == 2:
                self.db.row = (42, "123")
        self.db.on_query = change
        with self.assertRaises(self.token.PublicScoreTokenError) as error:
            self.fetch()
        self.assertEqual(error.exception.status_code, 401)
        self.assertEqual(self.db.used, 0)

    def test_source_ex_is_reused_by_actual_wahlap_fetch_and_full_delta_writer(self):
        incoming = {**self.payload, "songs": [{"song_no": 1, "level": 4, "high_score": 800000, "stage_cnt": 1}]}
        synthetic_wahlap(self.update, IDENTITY, incoming)
        with patch.object(self.token, "getUserData", self.update.getUserData):
            result = self.fetch()
        self.assertEqual(result["data"]["songs"], incoming["songs"])
        with self.store.shared():
            self.assertEqual(self.store.view()["sequence"], 2)
            self.assertEqual(len(self.store.reader().history_names()), 2)
        self.assertEqual(self.db.used, 1)

    def test_hiroba_receives_the_same_live_ex_and_retains_existing_local_fallback(self):
        calls = []
        with self.store.exclusive():
            self.store.commit({"current": json.dumps({**self.payload, "_meta": {"source": "hiroba"}}).encode()})
        def sync(identity, **kwargs):
            store = kwargs["publication_store"]
            store._require_lock(write=True)
            self.assertEqual(store.identity, identity)
            calls.append(store.root)
            raise self.token.HirobaError("Synthetic private upstream /password")
        with patch.object(self.token, "sync_bound_hiroba_userdata", sync):
            self.assertEqual(self.fetch()["data"]["_meta"]["source"], "hiroba")
        self.assertEqual(calls, [self.data])

    def test_hiroba_publication_failure_does_not_fall_back_to_cached_private_data(self):
        with patch.object(self.token, "_infer_public_token_source", return_value=("hiroba", None)), \
             patch.object(self.token, "sync_bound_hiroba_userdata", side_effect=PublicationError("Private store /path")):
            with self.assertRaises(self.token.PublicScoreTokenError) as error:
                self.fetch()
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("/path", str(error.exception))

    def test_failed_sql_rollback_closes_the_connection_and_sanitizes_errors(self):
        def fail(sql):
            if sql.startswith("UPDATE"):
                raise RuntimeError("Private SQL /password/hash")
        self.db.on_query = fail
        self.db.fail_rollback = True
        with self.assertRaises(self.token.PublicScoreTokenError) as error:
            self.fetch()
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("password", str(error.exception))
        self.assertGreaterEqual(self.db.closed, 1)

    def test_captured_connection_is_not_replaced_during_refresh(self):
        def refresh(*_args, **_kwargs):
            self.token.get_taiko_db_connection = lambda: (_ for _ in ()).throw(AssertionError("Replacement must not connect"))
            return 0
        with patch.object(self.token, "getUserData", refresh):
            self.assertEqual(self.fetch()["taikoId"], IDENTITY)

    def test_legacy_invalid_json_can_be_refreshed_using_its_owned_root(self):
        identity = "123"
        self.db.row = (42, identity)
        (self.data / (identity + "data.json")).write_text("{")
        incoming = {**self.payload, "profile": {"userid": identity}}
        synthetic_wahlap(self.update, identity, incoming)
        with patch.object(self.token, "getUserData", self.update.getUserData):
            self.assertEqual(self.fetch()["data"]["profile"]["userid"], identity)

    def test_tombstone_retains_existing_missing_local_state_if_refresh_does_not_supply_scores(self):
        with self.store.exclusive():
            self.store.commit({"current": None})
        with self.assertRaises(self.token.PublicScoreTokenError) as error:
            self.fetch()
        self.assertEqual(error.exception.status_code, 404)

    def test_source_lease_reuse_rejects_sh_expired_and_foreign_store(self):
        with self.store.shared(), self.assertRaises(PublicationError):
            self.storage.save_userdata(IDENTITY, self.payload, publication_store=self.store)
        with self.assertRaises(PublicationError):
            self.storage.save_userdata(IDENTITY, self.payload, publication_store=self.store)
        with self.store.exclusive(), self.assertRaises(PublicationError):
            self.storage.save_userdata("123", self.payload, publication_store=self.store)

    def test_actual_hiroba_private_public_and_both_save_branches_forward_the_owned_lease(self):
        # Execute every actual sync function; only remote transport/profile
        # parsing is synthetic. Save/lease/publication and routing are real.
        sync = types.ModuleType("actual_bearer_hiroba_sync")
        error = type("SyntheticHirobaError", (Exception,), {})
        class Client:
            def __init__(self, token=None, timeout=30):
                self.token, self.timeout = "synthetic-token", timeout
            def login(self, *_args, **_kwargs): pass
            def update_score(self): pass
            def fetch_mypage(self): return "profile"
            def fetch_public_profile(self, _identity): return "profile"
            def fetch_score_list(self, _genre): return "scores"
            def fetch_public_score_list(self, _identity, _genre): return "scores"
            def fetch_score_detail(self, *_args, **_kwargs): return "detail"
        task_count = [0]
        sync.__dict__.update(os=os, time=time, threading=__import__("threading"), logger=logging.getLogger(__name__),
            ThreadPoolExecutor=ThreadPoolExecutor, as_completed=as_completed,
            HirobaClient=Client, HirobaError=error, HirobaProfilePrivateError=type("Private", (error,), {}),
            HirobaSessionExpiredError=type("Expired", (error,), {}), HirobaUpdateScoreError=type("Update", (error,), {}),
            peek_hiroba_sync_cooldown=lambda _identity: None, acquire_hiroba_sync_slot=lambda _identity: None,
            release_hiroba_sync_slot=lambda _identity: None, delete_hiroba_token=lambda _identity: None,
            login_hiroba_service_client=lambda **_kwargs: Client(),
            parse_profile=lambda _html: types.SimpleNamespace(taiko_no=IDENTITY), parse_mypage_achievement=lambda _html: {},
            parse_score_list_page=lambda _html: {}, merge_song_refs=lambda _pages: {"1": types.SimpleNamespace(crowns={4:"gold"})},
            filter_song_refs_by_levels=lambda refs, _levels: refs,
            enumerate_fetch_tasks=lambda *_args, **_kwargs: [("1",4)] if task_count[0] else [],
            parse_score_detail=lambda *_args: types.SimpleNamespace(song_no="1",level=4,crown=None),
            build_userdata=lambda *_args: self.payload, save_userdata=self.storage.save_userdata)
        source = (OWNED / "hiroba/sync.py").read_text()
        nodes = [ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0)]
        nodes += [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(OWNED / "hiroba/sync.py"),"exec"),sync.__dict__)
        for private in (False, True):
            for count in (0, 1):
                task_count[0] = count
                with self.store.exclusive():
                    before = self.store.view()["sequence"]
                    sync.sync_bound_hiroba_userdata(IDENTITY,email="synthetic@example.test" if private else None,
                        password="synthetic" if private else None,request_delay=0,publication_store=self.store)
                    self.assertEqual(self.store.view()["sequence"],before+1)
                    self.assertEqual(json.loads(self.store.reader().current_raw())["_meta"]["source"],"hiroba")

    def test_http_body_limits_and_utf8_errors_precede_token_sql(self):
        server = load_http_server(self.token)
        for data, length, status in [(b'{', 1, 400), (b'\xff', 1, 400), (b'[]', 2, 400), (b'{}', 2, 400), (b'', 16385, 413)]:
            handler = object.__new__(server.SongDataHandler)
            handler.headers = {"Content-Length": str(length)}
            handler.rfile = io.BytesIO(data)
            handler.connection = types.SimpleNamespace(settimeout=lambda value: self.assertEqual(value, 15))
            replies = []
            handler.send_json = lambda code, body, **kwargs: replies.append((int(code), body, kwargs))
            with patch.object(server, "fetch_latest_userdata_by_token", side_effect=AssertionError("Token SQL forbidden")):
                handler.handle_public_score_post()
            self.assertEqual(replies[0][0], status)
            self.assertTrue(replies[0][2]["cors"])

    def test_http_valid_bearer_uses_the_actual_canonical_service(self):
        server = load_http_server(self.token)
        body = json.dumps({"token": TOKEN}).encode()
        handler = object.__new__(server.SongDataHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.connection = types.SimpleNamespace(settimeout=lambda _value: None)
        replies = []
        handler.send_json = lambda code, payload, **_kwargs: replies.append((int(code), payload))
        handler.handle_public_score_post()
        self.assertEqual(replies, [(200, self.fetch())])


if __name__ == "__main__":
    unittest.main()
