"""Current-owner proof and actual Bot command without adapter registration."""
import ast
import asyncio
import logging
import sys
import types
import unittest
from unittest.mock import patch

from token_bearer_fixture import ROOT, load_token_modules
from taiko_bot.runtime.player.center.bot_binding_authority import BotBindingDenied, normalize_bot_principal, read_bot_current_binding

IDENTITY = "114514"
PRINCIPAL = "onebot_v11:1919810"


class Cursor:
    def __init__(self, rows=None, state=None):
        self.rows = [(42, PRINCIPAL, IDENTITY, "wahlap", 1, 1, 0)] if rows is None else rows
        self.state = state
        self.queries = []

    def execute(self, sql, args):
        self.queries.append((sql, args))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.state


class TokenIssuerProofTests(unittest.TestCase):
    def test_only_canonical_adapter_principals_are_accepted(self):
        for value in (None, 1, "viewer", "test:123", "onebot_v11:", "onebot_v11:abc", "qq_official:../../x", "qq_official:a:b", "onebot_v11:" + "1" * 129):
            with self.subTest(value=type(value).__name__), self.assertRaises(BotBindingDenied):
                normalize_bot_principal(value)
        self.assertEqual(normalize_bot_principal(" " + PRINCIPAL + " "), PRINCIPAL)
        self.assertEqual(normalize_bot_principal("qq_official:Abc_012"), "qq_official:Abc_012")

    def test_hidden_own_binding_is_owned_and_absent_virtual_state_is_legacy_real(self):
        cursor = Cursor()
        binding = read_bot_current_binding(cursor, PRINCIPAL, lock=True)
        self.assertEqual((binding.row_id, binding.taiko_id, binding.visible), (42, IDENTITY, 0))
        self.assertTrue(all(sql.endswith("FOR UPDATE") for sql, _ in cursor.queries if sql.startswith("SELECT")))
        self.assertIn("FROM bind", cursor.queries[0][0])
        self.assertIn("ON DUPLICATE KEY UPDATE identity_key=identity_key", cursor.queries[1][0])
        self.assertIn("taiko_bind_identity_state", cursor.queries[2][0])

    def test_unchosen_legacy_slots_use_first_slot_and_current_slot_wins(self):
        first = (42, PRINCIPAL, IDENTITY, "wahlap", 1, 0, 0)
        second = (43, PRINCIPAL, "226226", "hiroba", 2, 1, 0)
        self.assertEqual(read_bot_current_binding(Cursor([first, second]), PRINCIPAL).taiko_id, "226226")
        self.assertEqual(read_bot_current_binding(Cursor([first, second[:5] + (0, 0)]), PRINCIPAL).taiko_id, IDENTITY)

    def test_virtual_or_case_colliding_state_is_rejected(self):
        for state in ((PRINCIPAL, 1), (PRINCIPAL, 2), (PRINCIPAL.upper(), 0)):
            with self.subTest(state=state[1]), self.assertRaises(BotBindingDenied):
                read_bot_current_binding(Cursor(state=state), PRINCIPAL)

    def test_malformed_foreign_unsafe_or_unbounded_bindings_are_rejected(self):
        row = Cursor().rows[0]
        cases = [[], [row] * 129, [row, row[:4] + (2,) + row[5:]]]
        for index, replacement in ((0, 0), (1, "onebot_v11:999"), (2, 114514), (2, "../data"), (3, "unknown"), (4, 0), (5, 2), (6, 2)):
            altered = list(row)
            altered[index] = replacement
            cases.append([tuple(altered)])
        for rows in cases:
            with self.subTest(count=len(rows)), self.assertRaises(BotBindingDenied):
                read_bot_current_binding(Cursor(rows), PRINCIPAL)

    def test_ownerless_apis_and_unsafe_ids_fail_before_schema_or_source(self):
        token, _, _, modules = load_token_modules("issuer_denial_fixture")
        with patch.dict(sys.modules, modules), patch.object(token, "ensure_public_score_token_table", side_effect=AssertionError("SQL forbidden")):
            for function in (token.get_public_score_token_status, token.issue_public_score_token_for_taiko_id, token.revoke_public_score_token_for_taiko_id):
                with self.assertRaises(token.PublicScoreTokenError) as error:
                    function(IDENTITY)
                self.assertEqual(error.exception.status_code, 403)
            for identity in (None, 114514, "../private", "1" * 26):
                with self.assertRaises(token.PublicScoreTokenError) as error:
                    token.issue_public_score_token_for_taiko_id(identity, identity_key=PRINCIPAL)
                self.assertEqual(error.exception.status_code, 400)
            with self.assertRaises(token.PublicScoreTokenError) as error:
                token.issue_public_score_token_for_taiko_id(IDENTITY, identity_key=PRINCIPAL, require_bot_binding=False)
            self.assertEqual(error.exception.status_code, 403)


class Finished(Exception):
    def __init__(self, text):
        self.text = text


class TokenBotCommandTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from token_bearer_fixture import OWNED
        source = (OWNED / "update_cluster.py").read_text()
        node = next(node for node in ast.parse(source).body if isinstance(node, ast.AsyncFunctionDef) and node.name == "public_score_token_handle")
        node.decorator_list = []
        token, _, _, _ = load_token_modules("issuer_command_fixture")
        self.error_type = token.PublicScoreTokenError
        self.sent = []
        self.calls = []
        self.info = {"id": IDENTITY, "visible": 0}
        self.selected = 1
        self.target = PRINCIPAL
        self.private = True
        async def finish(text, **_kwargs):
            self.sent.append(text)
            raise Finished(text)
        async def finish_text(_matcher, _event, text):
            await finish(text)
        def issue(identity, **kwargs):
            self.calls.append((identity, kwargs))
            return {"taiko_id": identity, "owner_display": "1919810", "token": "a" * 48}
        self.env = {"delivery_for": lambda matcher: matcher, "_is_private_message_event": lambda _event: self.private,
                    "public_score_token": types.SimpleNamespace(finish=finish),
                    "_normalize_identity_key": lambda value: value,
                    "get_identity_key": lambda **_kwargs: PRINCIPAL,
                    "_resolve_requested_identity_key": lambda _event: (self.target, self.target == PRINCIPAL),
                    "_get_taiko_bind_info": lambda identity: self.info if identity == PRINCIPAL else None,
                    "_finish_text_reply": finish_text, "_taiko_bind_usage_message": lambda _event: "绑定提示",
                    "_get_current_bind_entry": lambda identity: {"identity": identity},
                    "_get_selected_bind_slot_number": lambda _entry: self.selected,
                    "_build_u0_readonly_message": lambda *_args, **_kwargs: "u0 只读",
                    "issue_public_score_token_for_taiko_id": issue,
                    "PublicScoreTokenError": self.error_type, "logger": logging.getLogger("issuer-command-qa")}
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "owned-public-score-token-handler", "exec"), self.env)

    def run_command(self):
        with self.assertRaises(Finished):
            asyncio.run(self.env["public_score_token_handle"](types.SimpleNamespace()))
        return self.sent[-1]

    def test_own_hidden_real_binding_supplies_actual_sender_to_issuer(self):
        text = self.run_command()
        self.assertEqual(self.calls, [(IDENTITY, {"identity_key": PRINCIPAL})])
        self.assertIn("token：" + "a" * 48, text)

    def test_visible_foreign_target_never_reaches_binding_or_issuer(self):
        self.target = "onebot_v11:999"
        self.env["_get_taiko_bind_info"] = lambda _identity: self.fail("Foreign caller must be rejected before binding lookup")
        self.assertIn("自己的", self.run_command())
        self.assertEqual(self.calls, [])

    def test_group_command_never_reads_binding_or_issues(self):
        self.private = False
        self.env["_get_taiko_bind_info"] = lambda _identity: self.fail("Private command only")
        self.assertIn("私聊", self.run_command())
        self.assertEqual(self.calls, [])

    def test_virtual_slot_never_issues(self):
        self.selected = 0
        self.assertEqual(self.run_command(), "u0 只读")
        self.assertEqual(self.calls, [])

    def test_missing_binding_keeps_existing_bind_prompt(self):
        self.info = None
        self.assertEqual(self.run_command(), "绑定提示")
        self.assertEqual(self.calls, [])

    def test_driver_errors_do_not_leak_into_bot_reply(self):
        def failure(*_args, **_kwargs):
            raise RuntimeError("synthetic private /path/password")
        self.env["issue_public_score_token_for_taiko_id"] = failure
        with patch.object(self.env["logger"], "exception"):
            self.assertEqual(self.run_command(), "成绩 token 服务暂时不可用，请稍后重试。")


if __name__ == "__main__":
    unittest.main()
