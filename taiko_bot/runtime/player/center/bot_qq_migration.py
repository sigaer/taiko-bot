from __future__ import annotations


from dataclasses import asdict, dataclass

import hashlib

import json

import re

import secrets

from .bot_binding_authority import normalize_bot_principal

from .bot_binding_mutation import _read, _entry, _state, principal_lock_name

class QqMigrationDenied(ValueError):
    def __init__(self, message="请先用原 QQ 私聊旧 bot 发送“迁移验证码”，再发送“绑定QQ QQ号 验证码”。", *, code="qq_proof_required", status=403):
        self.code, self.status = code, status
        super().__init__(message)

class QqMigrationUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("迁移结果暂无法确认，请查询当前绑定后再重试。")

@dataclass(frozen=True)
class QqMigrationResult:
    entry: dict | None
    source_ids: tuple[str, ...]
    source_current_id: str
    first_binding: bool
    replayed: bool = False

def _principal(value):
    if not isinstance(value, str) or value != value.strip():
        raise QqMigrationDenied()
    try: return normalize_bot_principal(value)
    except Exception: raise QqMigrationDenied() from None

def _qq(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{4,14}", value):
        raise QqMigrationDenied()
    return value

def _acquire(cursor, principals):
    # Multiple principal gates and bind/state reads always have one order.
    for principal in sorted(set(principals)):
        cursor.execute("SELECT GET_LOCK(%s,5)", (principal_lock_name(principal),))
        if cursor.fetchone() != (1,): raise QqMigrationUnavailable()

def _close(connection, cursor, principals):
    if cursor is not None:
        for principal in reversed(sorted(set(principals))):
            try: cursor.execute("SELECT RELEASE_LOCK(%s)", (principal_lock_name(principal),))
            except Exception: pass
        try: cursor.close()
        except Exception: pass
    if connection is not None:
        try: connection.close()
        except Exception: pass

def _capture(cursor, principals):
    return {principal:_read(cursor, principal) for principal in sorted(set(principals))}

def _fingerprint(data, source, bare):
    payload = [[key,[asdict(row) for row in data[key][0]],data[key][1]] for key in sorted({source,bare})]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()).hexdigest()

def _origin(data, source, bare):
    # Preserve the frozen canonical-first, bare-QQ fallback profile explicitly.
    rows = data[source][0] or data[bare][0]
    if not rows:
        raise QqMigrationDenied("未找到该 QQ 的历史绑定，请发送“绑定 你的鼓众广场ID”完成验证。",code="qq_source_missing",status=404)
    if any(row.source == "manual" for row in rows):
        raise QqMigrationDenied("历史绑定含手动账号，请先通过认领命令绑定手动账号。",code="qq_manual_origin")
    return rows

def issue_qq_migration_code(principal, *, connection_factory, authorize=None):
    principal = _principal(principal)
    if not principal.startswith("onebot_v11:"): raise QqMigrationDenied()
    qq = _qq(principal.split(":",1)[1]); principals = [principal,qq]
    connection = cursor = None
    try:
        connection=connection_factory();cursor=connection.cursor();_acquire(cursor,principals);connection.begin()
        if authorize:authorize(cursor,None)
        data=_capture(cursor,principals)
        if authorize:authorize(cursor,data)
        _origin(data,principal,qq)
        cursor.execute("SELECT source_principal,issued_at>UTC_TIMESTAMP()-INTERVAL 60 SECOND FROM taiko_qq_migration_codes WHERE source_principal=%s FOR UPDATE",(principal,))
        prior=cursor.fetchone()
        if prior is not None and (prior[0]!=principal or prior[1] not in (0,1)):
            raise QqMigrationUnavailable()
        if prior and prior[1]: raise QqMigrationDenied("请一分钟后再申请迁移验证码。",code="qq_code_cooldown",status=429)
        code=secrets.token_hex(16);code_hash=hashlib.sha256(code.encode()).hexdigest();source_hash=_fingerprint(data,principal,qq)
        cursor.execute("""INSERT INTO taiko_qq_migration_codes(source_principal,code_hash,source_hash,issued_at,expires_at)
            VALUES(%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP()+INTERVAL 10 MINUTE)
            ON DUPLICATE KEY UPDATE code_hash=VALUES(code_hash),source_hash=VALUES(source_hash),
            issued_at=VALUES(issued_at),expires_at=VALUES(expires_at),target_principal=NULL,consumed_at=NULL,effect_json=NULL,effect_hash=NULL""",
            (principal,code_hash,source_hash))
        cursor.execute("SELECT code_hash,source_hash,target_principal,consumed_at FROM taiko_qq_migration_codes WHERE source_principal=%s FOR UPDATE",(principal,))
        if cursor.fetchone()!=(code_hash,source_hash,None,None) or _fingerprint(_capture(cursor,principals),principal,qq)!=source_hash:
            raise QqMigrationUnavailable()
        if authorize:authorize(cursor,data)
        connection.commit();return code
    except Exception as error:
        if connection is not None:
            try: connection.rollback()
            except Exception: pass
        if isinstance(error,QqMigrationDenied):raise
        raise QqMigrationUnavailable() from None
    finally:_close(connection,cursor,principals)

def migrate_qq_bindings(qq, target, *, code="", connection_factory, authorize=None):
    qq=_qq(qq);target=_principal(target);source="onebot_v11:"+qq;principals=[source,qq,target]
    self_owned=target==source
    if (not isinstance(code,str) or (code and not re.fullmatch(r"[a-f0-9]{32}",code)) or (not self_owned and not code)):
        raise QqMigrationDenied()
    connection=cursor=None
    try:
        connection=connection_factory();cursor=connection.cursor();_acquire(cursor,principals);connection.begin()
        if authorize:authorize(cursor,None)
        data=_capture(cursor,principals)
        if authorize:authorize(cursor,data)
        proof_hash=_fingerprint(data,source,qq)
        proof=None
        if not self_owned:
            cursor.execute("""SELECT source_principal,code_hash,source_hash,target_principal,consumed_at,
                expires_at>UTC_TIMESTAMP(),effect_json,effect_hash FROM taiko_qq_migration_codes WHERE source_principal=%s FOR UPDATE""",(source,))
            proof=cursor.fetchone()
            if (proof is None or proof[0]!=source or not isinstance(proof[1],str)
                    or not secrets.compare_digest(proof[1],hashlib.sha256(code.encode()).hexdigest())):
                raise QqMigrationDenied()
            if proof[4] is not None:
                if (proof[3]!=target or not isinstance(proof[6],str) or len(proof[6].encode())>4096
                        or proof[7]!=hashlib.sha256((source+":"+target+":"+proof[1]+":"+proof[6]).encode()).hexdigest()):
                    raise QqMigrationDenied()
                effect=json.loads(proof[6])
                if (set(effect)!={"sourceIds","sourceCurrentId","firstBinding"}
                        or not isinstance(effect["sourceIds"],list) or not 0<len(effect["sourceIds"])<=128
                        or any(not isinstance(v,str) or not re.fullmatch(r"[0-9]{1,25}",v) for v in effect["sourceIds"])
                        or effect["sourceCurrentId"] not in effect["sourceIds"] or type(effect["firstBinding"]) is not bool):
                    raise QqMigrationUnavailable()
                if authorize:authorize(cursor,data)
                connection.commit()
                return QqMigrationResult(_entry(*data[target]),tuple(effect["sourceIds"]),effect["sourceCurrentId"],effect["firstBinding"],True)
            if proof[3] is not None or proof[5]!=1 or proof[2]!=proof_hash:
                raise QqMigrationDenied("验证码已过期或历史绑定已改变，请重新申请迁移验证码。",code="qq_proof_expired",status=409)
        rows=_origin(data,source,qq);target_rows=data[target][0]
        selected=next((row for row in rows if row.current),rows[0])
        merged={row.identity:row for row in rows}
        for row in target_rows:
            if row.identity not in merged:merged[row.identity]=row
        if len(merged)>128:raise QqMigrationDenied("绑定数量已达上限。",code="qq_capacity",status=409)
        # Existing target manual members stay untouched. A manual origin is
        # rejected above because its dedicated lifecycle must prove ownership.
        if any(row.identity in merged and merged[row.identity].source!=row.source for row in target_rows):
            raise QqMigrationDenied("两边绑定的账号来源不一致，请先检查当前绑定。",code="qq_source_conflict",status=409)
        visible=target_rows[0].visible if target_rows else rows[0].visible
        # Credential lock order matches native Hiroba and center adapters.
        credentials=[]
        for row in sorted(rows,key=lambda row:row.identity):
            if row.source!="hiroba":continue
            cursor.execute("SELECT configured_by_qq FROM web_hiroba_credentials WHERE taiko_no=%s FOR UPDATE",(row.identity,))
            credential=cursor.fetchone()
            if credential and credential[0] in {source,qq}:
                credentials.append(row.identity)
        cursor.execute("DELETE FROM bind WHERE qq=%s AND CAST(qq AS BINARY)=CAST(%s AS BINARY)",(target,target))
        for slot,row in enumerate(merged.values(),1):
            cursor.execute("""INSERT INTO bind(qq,id,visible,slot_index,is_current,source) VALUES(%s,%s,%s,%s,%s,%s)""",
                (target,row.identity,visible,slot,int(row.identity==selected.identity),row.source))
        _state(cursor,target,False)
        for identity in credentials:
            cursor.execute("UPDATE web_hiroba_credentials SET configured_by_qq=%s,updated_at=CURRENT_TIMESTAMP WHERE taiko_no=%s",(target,identity))
        first=not target_rows
        if proof is not None:
            effect=json.dumps(dict(sourceIds=[r.identity for r in rows],sourceCurrentId=selected.identity,firstBinding=first),separators=(",",":"))
            effect_hash=hashlib.sha256((source+":"+target+":"+proof[1]+":"+effect).encode()).hexdigest()
            cursor.execute("""UPDATE taiko_qq_migration_codes SET target_principal=%s,consumed_at=UTC_TIMESTAMP(),effect_json=%s,effect_hash=%s
                WHERE source_principal=%s AND code_hash=%s AND source_hash=%s AND consumed_at IS NULL""",(target,effect,effect_hash,source,proof[1],proof[2]))
            if cursor.rowcount!=1:raise QqMigrationDenied()
        final=_read(cursor,target)
        if ([r.identity for r in final[0]]!=list(merged) or final[1]
                or next((r.identity for r in final[0] if r.current),None)!=selected.identity
                or any(r.visible!=visible or r.source!=merged[r.identity].source for r in final[0])):
            raise QqMigrationUnavailable()
        if not self_owned and _fingerprint(_capture(cursor,[source,qq]),source,qq)!=proof_hash:
            raise QqMigrationDenied()
        for identity in credentials:
            cursor.execute("SELECT configured_by_qq FROM web_hiroba_credentials WHERE taiko_no=%s FOR UPDATE",(identity,))
            if cursor.fetchone()!=(target,):raise QqMigrationDenied()
        if proof is not None:
            cursor.execute("SELECT code_hash,source_hash,target_principal,consumed_at IS NOT NULL,effect_json,effect_hash FROM taiko_qq_migration_codes WHERE source_principal=%s FOR UPDATE",(source,))
            if cursor.fetchone()!=(proof[1],proof[2],target,1,effect,effect_hash):raise QqMigrationDenied()
        if authorize:authorize(cursor,{**data,target:final})
        connection.commit()
        return QqMigrationResult(_entry(*final),tuple(r.identity for r in rows),selected.identity,first)
    except Exception as error:
        if connection is not None:
            try:connection.rollback()
            except Exception:pass
        if isinstance(error,QqMigrationDenied):raise
        raise QqMigrationUnavailable() from None
    finally:_close(connection,cursor,principals)
