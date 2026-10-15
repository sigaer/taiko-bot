"""Actual account-sync transaction/retry path with a recording SQL boundary."""
import json
from unittest.mock import patch
import pytest
from taiko_bot.runtime.player.center import account_sync as account
from taiko_bot.runtime.player.center.viewer_binding_authority import capture_viewer_binding
from taiko_bot.services import sync_dispatch_server as dispatcher
from taiko_store import PublicationStore

BINDING = {"id":"11", "taiko_id":"114514", "source":"wahlap", "manual_account_id":None}

def request():
    result = {"userId":7, "binding":BINDING, "targetIds":[dispatcher.get_sync_targets()[0].id], "requestId":"a"*32}
    result["requestHash"] = account.sync_request_hash(7, capture_viewer_binding(BINDING), result["targetIds"])
    return result

class Database:
    def __init__(self):
        self.trace=[]; self.receipt=None; self.log=None; self.lost_ack=False; self.lose_once=False; self.revoked=False; self.cooldown=None
    def connection(self): return Connection(self)

class Connection:
    def __init__(self, db): self.db=db; self.sql=""; self.args=(); self.lastrowid=9
    def cursor(self): return self
    def execute(self, sql, args=None):
        self.sql=sql; self.args=args; self.db.trace.append((sql,args))
        if sql.startswith("INSERT INTO web_data_sync_receipts") and self.db.receipt is None:
            self.db.receipt=(args[1],args[2],args[3],None,None)
        if sql.startswith("INSERT INTO web_data_sync_logs"):
            self.db.log=args[2:]
        if sql.startswith("UPDATE web_data_sync_receipts SET"):
            self.db.receipt=self.db.receipt[:3]+tuple(args[:2])
    def fetchone(self):
        sql=self.sql
        if "web_user_accounts" in sql: return (7,)
        if "web_data_sync_receipts" in sql: return self.db.receipt
        if "TIMESTAMPDIFF" in sql: return self.db.cooldown
        if "web_data_sync_logs" in sql: return self.db.log
        if "web_taiko_bindings" in sql: return None if self.db.revoked else ("11","114514","wahlap",None)
        raise AssertionError(sql)
    def fetchall(self): return [] if self.db.revoked else [("11","114514","wahlap",None,1)]
    def begin(self): self.db.trace.append("begin")
    def commit(self):
        self.db.trace.append("commit")
        if self.db.lost_ack and self.db.log is not None and not self.db.lose_once:
            self.db.lose_once=True
            raise RuntimeError("synthetic lost acknowledgement")
    def rollback(self): self.db.trace.append("rollback")
    def close(self): self.db.trace.append("close")

def acquire(root, monkeypatch):
    # Keep real local dispatch, compression, publication and SQL; only upstream acquisition is synthetic.
    calls=[]
    def refresh(identity, *, publication_store):
        publication_store._require_lock(write=True); calls.append(identity)
        payload={"profile":{"userid":identity},"songs":[],"achievement":{}}
        publication_store.commit({"current":json.dumps(payload).encode()})
        return identity
    monkeypatch.setattr(dispatcher,"refresh_userdata_from_wahlap",refresh)
    return calls

def run(db, root):
    try: return account.run_account_sync(request(),connection_factory=db.connection,userdata_root=root)
    except account.AccountSyncError as error:
        if error.code == "sync_unavailable" and error.__context__: raise error.__context__
        raise

def test_success_retry_and_lost_ack_have_one_sql_log_and_no_repeat_dispatch(tmp_path,monkeypatch):
    calls=acquire(tmp_path,monkeypatch); db=Database();db.lost_ack=True
    first=run(db,tmp_path); second=run(db,tmp_path)
    assert first==second and first["logId"]==9 and calls==["114514"]
    assert "rollback" in db.trace
    queries=[x[0] for x in db.trace if isinstance(x,tuple)]
    assert sum(q.startswith("INSERT INTO web_data_sync_logs") for q in queries)==1
    assert sum(q.startswith("UPDATE web_data_sync_receipts SET") for q in queries)==1
    assert db.trace[-1]=="close"

def test_revoked_binding_and_cooldown_prevent_acquisition(tmp_path,monkeypatch):
    calls=acquire(tmp_path,monkeypatch)
    for revoked,cooldown,status in [(True,None,409),(False,(1500000,"2026-10-15T00:00:02"),429)]:
        db=Database();db.revoked=revoked;db.cooldown=cooldown
        with pytest.raises(account.AccountSyncError) as caught:run(db,tmp_path)
        assert caught.value.status==status and db.trace[-1]=="close"
    assert not calls

def test_failed_remote_target_still_logs_failed_result(tmp_path,monkeypatch):
    acquire(tmp_path,monkeypatch);db=Database()
    monkeypatch.setattr(dispatcher,"dispatch_to_target",lambda *a,**kw:(_ for _ in ()).throw(RuntimeError("synthetic remote")))
    result=run(db,tmp_path)
    assert result["logId"]==9 and db.log[0]=="failed"
    assert json.loads(db.log[2])[0]["message"]=="服务端分发失败"

def test_request_hash_and_replaced_receipt_fail_closed(tmp_path,monkeypatch):
    calls=acquire(tmp_path,monkeypatch);db=Database();db.receipt=("foreign",7,"114514",9,"foreign")
    with pytest.raises(account.AccountSyncError) as caught:run(db,tmp_path)
    assert caught.value.code=="request_conflict" and not calls
