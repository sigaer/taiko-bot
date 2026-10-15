from __future__ import annotations

import copy
import importlib

import nonebot


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()






class _LegacyBindCursor:
    def __init__(self, bind_rows: dict[str, tuple[str, int] | list]):
        self.bind_rows = bind_rows
        self.last_result = None

    def execute(self, query: str, params=()):
        sql = query.strip().lower()
        if sql.startswith("select id, coalesce(visible, 0) from bind where qq=%s"):
            key = str(params[0])
            row = self.bind_rows.get(key)
            self.last_result = None if row is None else tuple(row)
            return
        if sql.startswith("select id, coalesce(visible, 0), coalesce(source"):
            key = str(params[0])
            row = self.bind_rows.get(key)
            self.last_result = None if row is None else tuple(row) + ("wahlap",)
            return
        if sql.startswith("delete from bind where qq=%s"):
            self.bind_rows.pop(str(params[0]), None)
            self.last_result = None
            return
        if sql.startswith("insert into taiko_bind_identity_state"):
            self.last_result = None
            return
        if sql.startswith("insert into bind") and len(params) >= 3:
            key = str(params[0])
            self.bind_rows.setdefault(key, [str(params[1]), int(params[2])])
            self.last_result = None
            return
        if sql.startswith("insert into bind values") or sql.startswith(
            "insert into bind (qq, id, visible) values"
        ):
            key = str(params[0])
            self.bind_rows[key] = [str(params[1]), int(params[2])]
            self.last_result = None
            return
        if sql.startswith("update bind set id="):
            key = str(params[2])
            row = self.bind_rows.setdefault(key, ["", 0])
            row[0] = str(params[0])
            row[1] = int(params[1])
            self.last_result = None
            return
        raise AssertionError(f"unexpected sql: {query}")

    def fetchone(self):
        return self.last_result

    def fetchall(self):
        return [] if self.last_result is None else [self.last_result]

    def close(self):
        return None


class _LegacyBindDb:
    def __init__(self, bind_rows: dict[str, tuple[str, int] | list]):
        self.cursor_obj = _LegacyBindCursor(bind_rows)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        return None


def test_switch_bind_record_supports_u0_and_real_slots(monkeypatch):
    from taiko_bot.runtime.player.center import bot_binding_mutation as mutations
    taiko = _load_taiko_module()
    identity_key = "onebot_v11:12345"
    entry = {"ids": ["111", "222"], "current_index": 1, "current_slot": 2,
             "sources": {"111": "wahlap", "222": "wahlap"}}

    def switch(principal, action, **kwargs):
        assert principal == identity_key and action == "switch"
        entry["current_slot"] = kwargs["value"]
        return mutations.BotBindingMutationResult(entry, "222")

    # SQL semantics are exercised by nativeBindingMutationSql.test.mjs.
    # This retained command regression verifies labels from the committed DTO.
    monkeypatch.setattr(mutations, "mutate_bot_binding", switch)
    ok, msg = taiko._switch_bind_record(identity_key, 2)
    assert ok is True
    assert "已切换到 u2：222" in msg
    ok, msg = taiko._switch_bind_record(identity_key, 0)
    assert ok is True
    assert "已切换到 u0：合并账户（只读）" in msg
    assert entry["current_index"] == 1


def test_manual_binding_also_enables_virtual_slot():
    taiko = _load_taiko_module()
    entry = {
        "ids": ["111", "manual-1"],
        "sources": {"111": "wahlap", "manual-1": "manual"},
    }

    assert taiko._has_virtual_bind_slot(entry) is True


def test_remove_bind_record_disables_u0_after_falling_back_to_single_bind(monkeypatch):
    from taiko_bot.runtime.player.center import bot_binding_mutation as mutations
    taiko = _load_taiko_module()
    identity_key = "onebot_v11:12345"
    entry = {"ids": ["111"], "current_index": 0, "current_slot": 1,
             "sources": {"111": "wahlap"}}

    def remove(principal, action, **kwargs):
        assert principal == identity_key and action == "remove"
        assert kwargs["value"] == "222" and kwargs["force_last"] is False
        return mutations.BotBindingMutationResult(entry, "222")

    monkeypatch.setattr(mutations, "mutate_bot_binding", remove)
    ok, msg, need_confirm = taiko._remove_bind_record(identity_key, target="222")
    assert ok is True
    assert need_confirm is False
    assert "已删除绑定：222" in msg
    assert "u0:" not in msg
    assert "u1:111" in msg


def test_migrate_bind_from_legacy_qq_records_success_action(monkeypatch):
    from taiko_bot.runtime.player.center import bot_qq_migration
    taiko = _load_taiko_module()
    legacy_qq = "12345678"; target = "qq_official:openid_123"; code = "a"*32
    recorded = []; calls = []
    def migrate(qq, principal, **kwargs):
        calls.append((qq,principal,kwargs['code']))
        return bot_qq_migration.QqMigrationResult(
            {'ids':['99887766','11223344'],'current_index':0,'current_slot':1,'sources':{'99887766':'wahlap','11223344':'wahlap'}},
            ('99887766','11223344'),'99887766',True)
    monkeypatch.setattr(bot_qq_migration,'migrate_qq_bindings',migrate)
    monkeypatch.setattr(taiko,'_build_bind_auto_update_result',lambda *_args:None)
    monkeypatch.setattr(taiko,'_record_bind_qq_action',lambda **payload:recorded.append(payload))
    ok,msg,_=taiko._migrate_bind_from_legacy_qq_detail(legacy_qq,target,code=code)
    assert ok is True and '已根据 QQ 12345678 的历史绑定完成迁移' in msg
    assert calls==[(legacy_qq,target,code)]
    assert len(recorded)==1 and recorded[0]['status']=='success'
    assert recorded[0]['source_current_id']=='99887766' and recorded[0]['source_ids']==['99887766','11223344']
    assert code not in str(recorded)


def test_migrate_bind_from_legacy_qq_records_not_found_action(monkeypatch):
    from taiko_bot.runtime.player.center import bot_qq_migration
    taiko = _load_taiko_module();recorded=[]
    def denied(*_args,**_kwargs):
        raise bot_qq_migration.QqMigrationDenied('未找到该 QQ 的历史绑定，请发送“绑定 你的鼓众广场ID”完成验证。')
    monkeypatch.setattr(bot_qq_migration,'migrate_qq_bindings',denied)
    monkeypatch.setattr(taiko,'_record_bind_qq_action',lambda **payload:recorded.append(payload))
    ok,msg,_=taiko._migrate_bind_from_legacy_qq_detail('12345678','qq_official:openid_456',code='b'*32)
    assert ok is False and '未找到该 QQ 的历史绑定' in msg
    assert len(recorded)==1 and recorded[0]['status']=='denied'


def test_manual_action_summary_failure_does_not_mask_success(monkeypatch):
    taiko = _load_taiko_module()

    def fail_lookup(_identity_key):
        raise RuntimeError("collation mismatch")

    monkeypatch.setattr(taiko, "_get_current_bind_entry", fail_lookup)
    summary = taiko._format_current_bind_summary_safe("qq_official:test")
    assert "绑定摘要暂时不可用" in summary
