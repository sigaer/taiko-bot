#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.utils.public_score_token import (
    PublicScoreTokenError,
    get_public_score_token_status,
    issue_public_score_token_for_taiko_id,
    revoke_public_score_token_for_taiko_id,
)
try:
    from .sync_dispatch_targets import SyncTarget, get_sync_targets, to_public_target
except ImportError:
    from sync_dispatch_targets import SyncTarget, get_sync_targets, to_public_target

DEBUG_LOG_PATH = Path(
    os.getenv(
        "TAIKO_DEBUG_LOG_PATH",
        "/home/sigaer/taiko/taiko-forum/taiko_viewer/.cursor/debug-b6e9de.log",
    )
)


HOST = str(os.getenv("TAIKO_SYNC_RECEIVER_HOST", "127.0.0.1")).strip() or "127.0.0.1"
PORT = int(os.getenv("TAIKO_SYNC_RECEIVER_PORT", "3102") or 3102)
RECEIVER_NAME = (
    str(os.getenv("TAIKO_SYNC_RECEIVER_NAME", "Sakura bot")).strip() or "Sakura bot"
)
USERDATA_DIR = Path(
    str(os.getenv("TAIKO_USERDATA_DIR", "/home/sigaer/taiko/userdata")).strip()
    or "/home/sigaer/taiko/userdata"
)
MAX_BODY_BYTES = int(
    os.getenv("TAIKO_SYNC_RECEIVER_MAX_BODY_BYTES", str(64 * 1024 * 1024))
    or 64 * 1024 * 1024
)
ZSTD_LEVEL = int(os.getenv("TAIKO_SYNC_RECEIVER_ZSTD_LEVEL", "9") or 9)


class RequestError(Exception):
    def __init__(
        self,
        code: str,
        status: int = HTTPStatus.BAD_REQUEST,
        *,
        detail: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail.strip()


def _agent_log(
    location: str,
    message: str,
    data: dict[str, Any],
    hypothesis_id: str,
    *,
    run_id: str = "pre-fix",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "b6e9de",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.now().timestamp() * 1000),
        }
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion


class ZstdCompressor:
    def __init__(self) -> None:
        library_path = ctypes.util.find_library("zstd") or "libzstd.so.1"
        self.lib = ctypes.CDLL(library_path)
        self.lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_compressBound.restype = ctypes.c_size_t
        self.lib.ZSTD_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        self.lib.ZSTD_compress.restype = ctypes.c_size_t
        self.lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_isError.restype = ctypes.c_uint
        self.lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_getErrorName.restype = ctypes.c_char_p

    def compress(self, payload: bytes, level: int = ZSTD_LEVEL) -> bytes:
        payload_size = len(payload)
        if payload_size == 0:
            return b""
        bound = int(self.lib.ZSTD_compressBound(payload_size))
        destination = ctypes.create_string_buffer(bound)
        source = (ctypes.c_ubyte * payload_size).from_buffer_copy(payload)
        result = int(
            self.lib.ZSTD_compress(
                destination,
                bound,
                source,
                payload_size,
                level,
            )
        )
        if self.lib.ZSTD_isError(result):
            error_name = self.lib.ZSTD_getErrorName(result)
            error_text = (
                error_name.decode("utf-8", errors="replace")
                if error_name
                else "zstd_unknown_error"
            )
            raise RuntimeError(f"zstd_compress_failed:{error_text}")
        return destination.raw[:result]


ZSTD = ZstdCompressor()
HTTP = requests.Session()
HTTP.trust_env = False


@dataclass
class LocalUserdata:
    userid: str
    save_path: Path
    raw_buffer: bytes
    parsed: dict[str, Any]
    compressed_buffer: bytes


def sanitize_userid(value: Any) -> str:
    userid = str(value or "").strip()
    if not userid:
        return ""
    return "".join(ch for ch in userid if ch.isalnum() or ch in "_-")


def get_snapshot_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def read_json_file(file_path: Path) -> Any | None:
    try:
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def build_song_key(song: Any) -> tuple[int, int]:
    if not isinstance(song, dict):
        return (0, 0)
    return (
        int(song.get("song_no", 0) or 0),
        int(song.get("level", 0) or 0),
    )


def build_song_map(songs: Any) -> dict[tuple[int, int], dict[str, Any]]:
    song_map: dict[tuple[int, int], dict[str, Any]] = {}
    for song in songs if isinstance(songs, list) else []:
        if isinstance(song, dict):
            song_map[build_song_key(song)] = song
    return song_map


def has_full_snapshot(user_history_dir: Path) -> bool:
    try:
        files = sorted(user_history_dir.glob("data_*.json"))
    except Exception:
        return False
    for file_path in files:
        snapshot = read_json_file(file_path)
        if not isinstance(snapshot, dict):
            continue
        meta = snapshot.get("_meta", {})
        if isinstance(meta, dict) and meta.get("full"):
            return True
        if (
            "songs" in snapshot
            and "profile" in snapshot
            and "achievement" in snapshot
            and not meta
        ):
            return True
    return False


def build_delta_snapshot(
    save_path: Path, user_history_dir: Path, payload: dict[str, Any], snapshot_ts: str
) -> dict[str, Any]:
    profile = payload.get("profile", {})
    if not isinstance(profile, dict):
        profile = {}
    achievement = payload.get("achievement", {})
    if not isinstance(achievement, dict):
        achievement = {}
    songs = payload.get("songs", [])
    if not isinstance(songs, list):
        songs = []

    prev_data = read_json_file(save_path)
    if not isinstance(prev_data, dict) or not has_full_snapshot(user_history_dir):
        return {
            "_meta": {"full": True, "ts": snapshot_ts, "source": "sakura-bot-sync"},
            "profile": profile,
            "achievement": achievement,
            "songs": songs,
        }

    delta_snapshot: dict[str, Any] = {
        "_meta": {"full": False, "ts": snapshot_ts, "source": "sakura-bot-sync"},
        "songs": [],
    }
    if prev_data.get("profile") != profile:
        delta_snapshot["profile"] = profile
    if prev_data.get("achievement") != achievement:
        delta_snapshot["achievement"] = achievement

    prev_map = build_song_map(prev_data.get("songs"))
    next_map = build_song_map(songs)
    delta_snapshot["songs"] = [
        next_song
        for song_key, next_song in next_map.items()
        if prev_map.get(song_key) != next_song
    ]

    removed_songs = [
        [song_no, level]
        for song_no, level in prev_map.keys()
        if (song_no, level) not in next_map
    ]
    if removed_songs:
        delta_snapshot["songs_removed"] = removed_songs

    return delta_snapshot


def refresh_userdata_from_wahlap(userid: str) -> str:
    sanitized_userid = sanitize_userid(userid)
    if not sanitized_userid:
        raise RequestError("invalid_userid")

    from plugins.utils.update_user import getUserData

    _agent_log(
        "sync_dispatch_server.py:refresh_userdata_from_wahlap",
        "wahlap_pull_attempt",
        {"userid": sanitized_userid},
        "H-cn",
    )

    try:
        result = getUserData(sanitized_userid)
    except Exception as exc:
        _agent_log(
            "sync_dispatch_server.py:refresh_userdata_from_wahlap",
            "wahlap_pull_failed",
            {"userid": sanitized_userid, "error": str(exc)},
            "H-cn",
        )
        raise RequestError(
            "wahlap_sync_failed",
            HTTPStatus.BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    if result == 404:
        _agent_log(
            "sync_dispatch_server.py:refresh_userdata_from_wahlap",
            "wahlap_pull_not_found",
            {"userid": sanitized_userid},
            "H-cn",
        )
        raise RequestError(
            "wahlap_user_not_found",
            HTTPStatus.NOT_FOUND,
            detail="请确认网页端绑定的鼓众 ID 是否正确",
        )
    if result != 0:
        _agent_log(
            "sync_dispatch_server.py:refresh_userdata_from_wahlap",
            "wahlap_pull_failed",
            {"userid": sanitized_userid, "result": result},
            "H-cn",
        )
        raise RequestError(
            "wahlap_sync_failed",
            HTTPStatus.BAD_GATEWAY,
            detail="从鼓众广场拉取成绩失败，请稍后重试",
        )

    _agent_log(
        "sync_dispatch_server.py:refresh_userdata_from_wahlap",
        "wahlap_pull_ok",
        {"userid": sanitized_userid},
        "H-cn",
    )
    return sanitized_userid


def read_local_userdata(userid: str) -> LocalUserdata:
    sanitized_userid = sanitize_userid(userid)
    if not sanitized_userid:
        raise RequestError("invalid_userid")
    save_path = USERDATA_DIR / f"{sanitized_userid}data.json"
    try:
        raw_buffer = save_path.read_bytes()
    except FileNotFoundError as exc:
        raise RequestError("userdata_not_found", HTTPStatus.NOT_FOUND) from exc
    try:
        parsed = json.loads(raw_buffer.decode("utf-8"))
    except Exception as exc:
        raise RequestError("userdata_invalid_json", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    if not isinstance(parsed, dict):
        raise RequestError("userdata_invalid_payload", HTTPStatus.INTERNAL_SERVER_ERROR)
    return LocalUserdata(
        userid=sanitized_userid,
        save_path=save_path,
        raw_buffer=raw_buffer,
        parsed=parsed,
        compressed_buffer=ZSTD.compress(raw_buffer),
    )


def write_local_snapshot(userid: str, parsed: dict[str, Any]) -> None:
    save_path = USERDATA_DIR / f"{userid}data.json"
    user_history_dir = USERDATA_DIR / userid
    snapshot_ts = get_snapshot_timestamp()
    history_path = user_history_dir / f"data_{snapshot_ts}.json"
    USERDATA_DIR.mkdir(parents=True, exist_ok=True)
    user_history_dir.mkdir(parents=True, exist_ok=True)
    delta_snapshot = build_delta_snapshot(save_path, user_history_dir, parsed, snapshot_ts)
    payload_text = json.dumps(parsed, ensure_ascii=False, indent=4) + "\n"
    delta_text = json.dumps(delta_snapshot, ensure_ascii=False, indent=4) + "\n"
    save_path.write_text(payload_text, encoding="utf-8")
    history_path.write_text(delta_text, encoding="utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_response_payload(response: requests.Response) -> dict[str, Any]:
    content_type = str(response.headers.get("content-type", "")).lower()
    if "application/json" in content_type:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return {
            "message": str(
                payload.get("message") or payload.get("statusMessage") or f"HTTP {response.status_code}"
            ).strip()
            or f"HTTP {response.status_code}",
            "receivedBytes": int(payload.get("receivedBytes") or 0),
            "decompressedBytes": int(payload.get("decompressedBytes") or 0),
            "songCount": (
                None
                if payload.get("songCount") is None
                else int(payload.get("songCount") or 0)
            ),
        }
    text = response.text.strip()
    return {
        "message": text or f"HTTP {response.status_code}",
        "receivedBytes": 0,
        "decompressedBytes": 0,
        "songCount": None,
    }


def forward_compressed_payload(
    target: SyncTarget, userid: str, compressed_buffer: bytes
) -> dict[str, Any]:
    response = HTTP.post(
        target.endpoint,
        headers={
            "Content-Type": "application/zstd",
            "X-Taiko-Userid": userid,
            "X-Taiko-Compression": "zstd",
            "X-Taiko-Payload-Sha256": sha256_hex(compressed_buffer),
        },
        data=compressed_buffer,
        timeout=max(target.timeout_ms, 1000) / 1000,
    )
    payload = read_response_payload(response)
    return {
        "targetId": target.id,
        "label": target.label,
        "ok": response.ok,
        "statusCode": response.status_code,
        "message": payload["message"],
        "receivedBytes": payload["receivedBytes"] or len(compressed_buffer),
        "decompressedBytes": payload["decompressedBytes"],
        "songCount": payload["songCount"],
    }


def dispatch_to_target(target: SyncTarget, userdata: LocalUserdata) -> dict[str, Any]:
    songs = userdata.parsed.get("songs", [])
    song_count = len(songs) if isinstance(songs, list) else 0
    if target.kind == "local":
        write_local_snapshot(userdata.userid, userdata.parsed)
        return {
            "targetId": target.id,
            "label": target.label,
            "ok": True,
            "statusCode": HTTPStatus.OK,
            "message": f"{target.label} 已刷新 userdata 与历史快照",
            "receivedBytes": len(userdata.compressed_buffer),
            "decompressedBytes": len(userdata.raw_buffer),
            "songCount": song_count,
        }
    return forward_compressed_payload(target, userdata.userid, userdata.compressed_buffer)


def get_target_map() -> dict[str, SyncTarget]:
    return {target.id: target for target in get_sync_targets()}


def parse_dispatch_body(raw_body: bytes) -> tuple[str, list[str]]:
    if not raw_body:
        raise RequestError("empty_body")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise RequestError("invalid_json") from exc
    userid = sanitize_userid(payload.get("userid") if isinstance(payload, dict) else "")
    raw_target_ids = payload.get("targetIds") if isinstance(payload, dict) else []
    target_ids = list(
        dict.fromkeys(
            str(item or "").strip()
            for item in raw_target_ids
            if str(item or "").strip()
        )
    ) if isinstance(raw_target_ids, list) else []
    if not userid:
        raise RequestError("missing_userid")
    if not target_ids:
        raise RequestError("missing_targets")
    return userid, target_ids


def parse_score_token_body(raw_body: bytes) -> tuple[str, str]:
    if not raw_body:
        raise RequestError("empty_body")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise RequestError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise RequestError("invalid_json")
    raw_userid = str(payload.get("userid") or "").strip()
    userid = sanitize_userid(raw_userid)
    action = str(payload.get("action") or "status").strip().lower()
    if not userid or userid != raw_userid:
        raise RequestError("invalid_userid")
    if action not in {"status", "issue", "revoke"}:
        raise RequestError("invalid_action")
    return userid, action


class SyncDispatchHandler(BaseHTTPRequestHandler):
    server_version = "TaikoSyncDispatchHTTP/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), format % args)

    def read_request_body(self) -> bytes:
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError as exc:
            raise RequestError("invalid_content_length") from exc
        if content_length <= 0:
            raise RequestError("empty_body")
        if content_length > MAX_BODY_BYTES:
            raise RequestError("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return self.rfile.read(content_length)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_GET(self) -> None:
        request_url = urlparse(self.path)
        if request_url.path == "/health":
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "receiver": RECEIVER_NAME,
                    "host": HOST,
                    "port": PORT,
                    "userdataDir": str(USERDATA_DIR),
                    "targetCount": len(get_sync_targets()),
                },
            )
            return
        if request_url.path == "/targets":
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "receiver": RECEIVER_NAME,
                    "targets": [to_public_target(target) for target in get_sync_targets()],
                },
            )
            return
        if request_url.path in {"/", "/receive"}:
            self.send_json(
                HTTPStatus.GONE,
                {
                    "ok": False,
                    "message": "直接上传 zstd 数据已停用，请改为向 /dispatch 发送服务端同步请求",
                },
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "未找到请求路径"})

    def do_POST(self) -> None:
        request_url = urlparse(self.path)
        if request_url.path == "/score-token":
            self.handle_score_token_management()
            return
        if request_url.path != "/dispatch":
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "未找到请求路径"})
            return
        try:
            raw_body = self.read_request_body()
            userid, target_ids = parse_dispatch_body(raw_body)
            target_map = get_target_map()
            selected_targets = [target_map.get(target_id) for target_id in target_ids]
            if any(target is None for target in selected_targets):
                raise RequestError("invalid_targets")
            refresh_userdata_from_wahlap(userid)
            userdata = read_local_userdata(userid)
            results = []
            for target in selected_targets:
                assert target is not None
                try:
                    results.append(dispatch_to_target(target, userdata))
                except Exception as exc:
                    logging.exception("Sync dispatch target failed: %s", target.id)
                    results.append(
                        {
                            "targetId": target.id,
                            "label": target.label,
                            "ok": False,
                            "statusCode": HTTPStatus.INTERNAL_SERVER_ERROR,
                            "message": str(exc) or "服务端分发失败",
                            "receivedBytes": len(userdata.compressed_buffer),
                            "decompressedBytes": 0,
                            "songCount": None,
                        }
                    )
        except RequestError as exc:
            message_map = {
                "invalid_content_length": "请求头 Content-Length 无效",
                "payload_too_large": f"请求体超过上限 {MAX_BODY_BYTES} bytes",
                "empty_body": "未收到同步请求内容",
                "invalid_json": "同步请求 JSON 无法解析",
                "missing_userid": "请提供 userid",
                "missing_targets": "请至少选择一个同步目标",
                "invalid_targets": "包含无效的同步目标",
                "invalid_userid": "userid 无效",
                "userdata_not_found": "未找到对应 userid 的 userdata",
                "userdata_invalid_json": "本地 userdata 已损坏",
                "userdata_invalid_payload": "本地 userdata 已损坏",
                "wahlap_user_not_found": "未找到该鼓众 ID 的成绩",
                "wahlap_sync_failed": "从鼓众广场拉取成绩失败",
            }
            message = message_map.get(exc.code, "同步请求无效")
            if exc.detail:
                message = f"{message}：{exc.detail}"
            self.send_json(
                exc.status,
                {"ok": False, "message": message},
            )
            return
        except Exception:
            logging.exception("Unhandled sync dispatch error")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "message": "同步网关内部错误"},
            )
            return

        self.send_json(
            HTTPStatus.OK,
            {
                "ok": all(result["ok"] for result in results),
                "receiver": RECEIVER_NAME,
                "userid": userdata.userid,
                "originalBytes": len(userdata.raw_buffer),
                "compressedBytes": len(userdata.compressed_buffer),
                "results": results,
                "message": f"{RECEIVER_NAME} 已在服务端完成 {len(results)} 个目标的同步请求",
            },
        )

    def handle_score_token_management(self) -> None:
        try:
            userid, action = parse_score_token_body(self.read_request_body())
            if action == "issue":
                issued = issue_public_score_token_for_taiko_id(
                    userid, require_bot_binding=False
                )
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "action": action,
                        "token": issued["token"],
                        "status": get_public_score_token_status(userid),
                    },
                )
                return
            if action == "revoke":
                revoked = revoke_public_score_token_for_taiko_id(userid)
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "action": action,
                        "revoked": revoked["revoked"],
                        "status": get_public_score_token_status(userid),
                    },
                )
                return
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "action": action,
                    "status": get_public_score_token_status(userid),
                },
            )
        except RequestError as exc:
            message_map = {
                "invalid_content_length": "请求头 Content-Length 无效",
                "payload_too_large": f"请求体超过上限 {MAX_BODY_BYTES} bytes",
                "empty_body": "未收到 token 管理请求内容",
                "invalid_json": "token 管理请求 JSON 无法解析",
                "invalid_userid": "userid 无效",
                "invalid_action": "不支持的 token 管理操作",
            }
            message = message_map.get(exc.code, "token 管理请求无效")
            self.send_json(exc.status, {"ok": False, "message": message})
        except PublicScoreTokenError as exc:
            self.send_json(
                exc.status_code,
                {"ok": False, "error": exc.error, "message": exc.message},
            )
        except Exception:
            logging.exception("Unhandled score token management error")
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "message": "token 管理服务内部错误"},
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[taiko-sync-dispatch] %(asctime)s %(levelname)s %(message)s",
    )
    server = ThreadingHTTPServer((HOST, PORT), SyncDispatchHandler)
    logging.info("%s listening on http://%s:%s", RECEIVER_NAME, HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("收到 KeyboardInterrupt，准备退出")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
