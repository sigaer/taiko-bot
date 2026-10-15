"""Authenticated local Viewer sync. This service owns Source EX and SQL.

Wahlap acquisition and compatible local-target observations are independent
file commits, as in the actual runtime. A late SQL failure does not undo an
already authorized observation. One SQL transaction owns the current binding,
cooldown, sync log and minimal request receipt. No HTTP body is an actor grant.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path
from dataclasses import dataclass

from taiko_store import PublicationError, PublicationStore
from taiko_bot.services import sync_dispatch_server as dispatcher
from .taiko_db import get_taiko_db_connection
from .viewer_binding_authority import ViewerBindingDenied, capture_viewer_binding, require_viewer_current_binding


@dataclass
class AccountSyncError(Exception):
    status: int
    code: str
    message: str
    data: object = None


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sync_request_hash(user_id, binding, target_ids):
    return hashlib.sha256(_json({"version": 1, "userId": user_id,
        "binding": {"id": binding.id, "taiko_id": binding.taiko_id, "source": binding.source, "manual_account_id": binding.manual_account_id},
        "targetIds": target_ids}).encode()).hexdigest()


def validate_sync_request(request):
    if not isinstance(request, dict) or type(request.get("userId")) is not int or not 0 < request["userId"] <= 2**53-1:
        raise AccountSyncError(403, "owner_required", "账号归属无效。")
    try:
        binding = capture_viewer_binding(request.get("binding"))
    except ViewerBindingDenied:
        raise AccountSyncError(409, "profile_changed", "绑定已变更，请重新加载。") from None
    if binding.source == "manual" or binding.manual_account_id or re.fullmatch(r"98[0-9]{16}", binding.taiko_id):
        raise AccountSyncError(400, "manual_source", "手动账号无需拉取同步。")
    targets = request.get("targetIds")
    if not isinstance(targets, list) or not 0 < len(targets) <= 64 or len(set(map(str, targets))) != len(targets) or any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in targets
    ):
        raise AccountSyncError(400, "invalid_targets", "同步目标无效。")
    if not isinstance(request.get("requestId"), str) or not re.fullmatch(r"[a-f0-9]{32}", request["requestId"]):
        raise AccountSyncError(400, "invalid_request", "同步请求标识无效。")
    digest = sync_request_hash(request["userId"], binding, targets)
    if request.get("requestHash") != digest:
        raise AccountSyncError(400, "invalid_request", "同步请求标识无效。")
    return binding, digest


def _close(connection, cursor=None):
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


def _rollback(connection):
    if connection is not None:
        try:
            connection.rollback()
        except Exception:
            _close(connection)


def _receipt(cursor, request, digest):
    cursor.execute("SELECT request_hash,user_id,taiko_id,log_id,log_hash FROM web_data_sync_receipts WHERE request_id=%s FOR UPDATE", (request["requestId"],))
    row = cursor.fetchone()
    if row is None or row[:3] != (digest, request["userId"], request["binding"]["taiko_id"]):
        raise AccountSyncError(409, "request_conflict", "同步请求已变更，请重试。")
    return row[3], row[4]


def sync_log_hash(row):
    return hashlib.sha256(_json(dict(zip(("status", "targetIdsJson", "resultsJson", "originalBytes", "compressedBytes"), row))).encode()).hexdigest()


def _proof_log(cursor, request, log_id, expected_hash):
    cursor.execute("SELECT status,target_ids_json,result_json,original_bytes,compressed_bytes FROM web_data_sync_logs WHERE id=%s AND user_id=%s AND taiko_id=%s FOR UPDATE",
                   (log_id, request["userId"], request["binding"]["taiko_id"]))
    row = cursor.fetchone()
    if row is None or sync_log_hash(row) != expected_hash:
        raise AccountSyncError(503, "sync_unavailable", "同步服务暂不可用，请稍后重试。")


def _cooldown(cursor, user_id):
    cursor.execute("""SELECT TIMESTAMPDIFF(MICROSECOND,NOW(6),DATE_ADD(created_at,INTERVAL 1800 SECOND)),
        DATE_FORMAT(DATE_ADD(created_at,INTERVAL 1800 SECOND),'%%Y-%%m-%%dT%%H:%%i:%%s')
        FROM web_data_sync_logs WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT 1""", (user_id,))
    row = cursor.fetchone()
    if row and row[0] > 0:
        remaining = min(1800, math.ceil(row[0] / 1_000_000))
        raise AccountSyncError(429, "sync_cooldown", f"同步冷却中，请在 {remaining} 秒后重试",
                               {"remainingSeconds": remaining, "availableAt": row[1]})


def _acquire_and_dispatch(store, target_ids):
    targets = dispatcher.get_target_map()
    if any(value not in targets for value in target_ids):
        raise AccountSyncError(400, "invalid_targets", "同步目标无效。")
    dispatcher.refresh_userdata_from_wahlap(store.identity, publication_store=store)
    userdata = dispatcher.read_local_userdata(store.identity, publication_store=store)
    results = []
    for target_id in target_ids:
        target = targets[target_id]
        try:
            results.append(dispatcher.dispatch_to_target(target, userdata, publication_store=store))
        except PublicationError:
            raise
        except Exception:
            results.append({"targetId": target.id, "label": target.label, "ok": False, "statusCode": 500,
                "message": "服务端分发失败", "receivedBytes": len(userdata.compressed_buffer), "decompressedBytes": 0, "songCount": None})
    return userdata, results


def run_account_sync(request, *, connection_factory=None, userdata_root=None):
    binding, digest = validate_sync_request(request)
    factory = connection_factory or get_taiko_db_connection
    root = Path(userdata_root or os.getenv("TAIKO_USERDATA_DIR") or dispatcher.USERDATA_DIR)
    connection = cursor = None
    try:
        connection = factory()
        cursor = connection.cursor()
        # Optimistic SQL ends before Source EX; no SQL lock waits for a Source.
        require_viewer_current_binding(cursor, request["userId"], binding, lock=False)
        connection.commit()
        store = PublicationStore(root, binding.taiko_id)
        with store.exclusive():
            attempted = False
            log_id = None
            try:
                connection.begin()
                require_viewer_current_binding(cursor, request["userId"], binding)
                cursor.execute("""INSERT INTO web_data_sync_receipts(request_id,request_hash,user_id,taiko_id) VALUES (%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE request_id=request_id""", (request["requestId"], digest, request["userId"], binding.taiko_id))
                log_id, log_hash = _receipt(cursor, request, digest)
                if log_id is None:
                    _cooldown(cursor, request["userId"])
                    userdata, results = _acquire_and_dispatch(store, request["targetIds"])
                    status = "success" if all(item["ok"] for item in results) else "partial" if any(item["ok"] for item in results) else "failed"
                    log_values = (status, _json(request["targetIds"]), _json(results), len(userdata.raw_buffer), len(userdata.compressed_buffer))
                    cursor.execute("""INSERT INTO web_data_sync_logs(user_id,taiko_id,status,target_ids_json,result_json,original_bytes,compressed_bytes)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""", (request["userId"], binding.taiko_id, *log_values))
                    log_id = cursor.lastrowid
                    log_hash = sync_log_hash(log_values)
                    cursor.execute("UPDATE web_data_sync_receipts SET log_id=%s,log_hash=%s WHERE request_id=%s AND request_hash=%s", (log_id, log_hash, request["requestId"], digest))
                _proof_log(cursor, request, log_id, log_hash)
                require_viewer_current_binding(cursor, request["userId"], binding)
                store._require_lock(write=True)
                attempted = True
                connection.commit()
                store._require_lock(write=True)
            except Exception:
                _rollback(connection)
                if not attempted:
                    raise
                # Lost COMMIT acknowledgement is proved by the exact receipt
                # and log, with current ownership locked under the original EX.
                proof = proof_cursor = None
                try:
                    proof = factory()
                    proof_cursor = proof.cursor()
                    proof.begin()
                    require_viewer_current_binding(proof_cursor, request["userId"], binding)
                    if _receipt(proof_cursor, request, digest) != (log_id, log_hash):
                        raise PublicationError("Sync acknowledgement not proved")
                    _proof_log(proof_cursor, request, log_id, log_hash)
                    store._require_lock(write=True)
                    proof.commit()
                    store._require_lock(write=True)
                except Exception:
                    _rollback(proof)
                    raise PublicationError("Sync acknowledgement not proved") from None
                finally:
                    _close(proof, proof_cursor)
            if type(log_id) is not int or not 0 < log_id <= 2**53-1:
                raise PublicationError("Sync result is invalid")
            return {"requestId": request["requestId"], "userId": request["userId"], "taikoId": binding.taiko_id, "logId": log_id, "logHash": log_hash}
    except ViewerBindingDenied:
        _rollback(connection)
        raise AccountSyncError(409, "profile_changed", "绑定已变更，请重新加载。") from None
    except AccountSyncError:
        _rollback(connection)
        raise
    except dispatcher.RequestError as error:
        _rollback(connection)
        messages = {"wahlap_user_not_found": "未找到该鼓众 ID 的成绩，请确认绑定账号。", "wahlap_sync_failed": "从鼓众广场拉取成绩失败，请稍后重试。"}
        raise AccountSyncError(error.status, error.code, messages.get(error.code, "同步服务暂不可用，请稍后重试。")) from None
    except Exception:
        _rollback(connection)
        raise AccountSyncError(503, "sync_unavailable", "同步服务暂不可用，请稍后重试。") from None
    finally:
        _close(connection, cursor)
