#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import json
import logging
import os
import re
import uuid
import sys
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


from taiko_store import PublicationError, PublicationStore
from taiko_store.reader import score_read_view

from .sync_dispatch_targets import SyncTarget, get_sync_targets, to_public_target


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
    def __init__(self, code: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


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


def _has_full_in_view(view):
    for name in sorted(view.history_names()):
        try:
            snapshot = json.loads(view.history_raw(name).decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        meta = snapshot.get("_meta", {})
        if (isinstance(meta, dict) and meta.get("full")) or (
            "songs" in snapshot and "profile" in snapshot and "achievement" in snapshot and not meta
        ):
            return True
    return False


def _previous_in_view(view):
    try:
        return json.loads(view.current_raw().decode("utf-8"))
    except FileNotFoundError:
        if view.manifest is not None and "current" in view.manifest["files"]:
            raise PublicationError("Canonical current is unavailable") from None
        return None
    except (ValueError, UnicodeError):
        if view.manifest is not None:
            raise PublicationError("Canonical current is invalid") from None
        return None


def build_delta_snapshot(save_path, user_history_dir, payload, snapshot_ts):
    identity = save_path.name.removesuffix("data.json")
    if save_path.name != identity + "data.json" or user_history_dir != save_path.parent / identity:
        raise PublicationError("Snapshot paths do not match")
    with score_read_view(save_path.parent, identity) as view:
        return _build_delta_from_state(_previous_in_view(view), _has_full_in_view(view), payload, snapshot_ts)


def _build_delta_from_state(prev_data, full_snapshot, payload, snapshot_ts):
    profile = payload.get("profile", {})
    if not isinstance(profile, dict):
        profile = {}
    achievement = payload.get("achievement", {})
    if not isinstance(achievement, dict):
        achievement = {}
    songs = payload.get("songs", [])
    if not isinstance(songs, list):
        songs = []

    if not isinstance(prev_data, dict) or not full_snapshot:
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


def read_local_userdata(userid: str, *, publication_store=None) -> LocalUserdata:
    if not isinstance(userid, str) or not re.fullmatch(r"[0-9A-Za-z_-]{1,128}", userid):
        raise RequestError("invalid_userid")
    def read(view):
        try:
            raw_buffer = view.current_raw()
        except FileNotFoundError:
            if view.manifest is not None and "current" in view.manifest["files"]:
                raise PublicationError("Canonical current is unavailable") from None
            raise RequestError("userdata_not_found", HTTPStatus.NOT_FOUND) from None
        try:
            parsed = json.loads(raw_buffer.decode("utf-8"))
        except (ValueError, UnicodeError):
            if view.manifest is not None:
                raise PublicationError("Canonical current is invalid") from None
            raise RequestError("userdata_invalid_json", HTTPStatus.INTERNAL_SERVER_ERROR) from None
        if not isinstance(parsed, dict):
            if view.manifest is not None:
                raise PublicationError("Canonical current is invalid")
            raise RequestError("userdata_invalid_payload", HTTPStatus.INTERNAL_SERVER_ERROR)
        return LocalUserdata(userid, view.store.root / (userid + "data.json"), raw_buffer, parsed, ZSTD.compress(raw_buffer))
    if publication_store is not None:
        publication_store._require_lock()
        if publication_store.identity != userid:
            raise PublicationError("Read Source does not match its lease")
        return read(publication_store.reader())
    with score_read_view(USERDATA_DIR, userid) as view:
        return read(view)


def write_local_snapshot(userid: str, parsed: dict[str, Any], *, publication_store=None) -> None:
    store = publication_store or PublicationStore(USERDATA_DIR, userid)
    def write():
        store._require_lock(write=True)
        if store.identity != userid:
            raise PublicationError("Snapshot Source does not match its lease")
        view = store.reader()
        snapshot_ts = get_snapshot_timestamp()
        delta = _build_delta_from_state(_previous_in_view(view), _has_full_in_view(view), parsed, snapshot_ts)
        sequence = (view.publication or {}).get("sequence", 0) + 1
        name = "data_" + snapshot_ts + "_" + str(sequence).zfill(20) + "_" + uuid.uuid4().hex + ".json"
        store.commit({"current": (json.dumps(parsed, ensure_ascii=False, indent=4) + "\n").encode("utf-8"),
                      "history/" + name: (json.dumps(delta, ensure_ascii=False, indent=4) + "\n").encode("utf-8")})
    if publication_store is not None:
        write()
    else:
        with store.exclusive():
            write()


def refresh_userdata_from_wahlap(userid: str, *, publication_store=None) -> str:
    # Preserve the actual R refresh/404/nonzero behavior; private diagnostics
    # never become an HTTP/CLI reply. A supplied EX is reused by acquisition.
    if not isinstance(userid, str) or not re.fullmatch(r"[0-9]{1,25}", userid):
        raise RequestError("invalid_userid")
    from taiko_bot.runtime.player.center.update_user import getUserData
    try:
        result = getUserData(userid, **({"publication_store": publication_store} if publication_store is not None else {}))
    except PublicationError:
        raise
    except Exception:
        raise RequestError("wahlap_sync_failed", HTTPStatus.BAD_GATEWAY) from None
    if result == 404:
        raise RequestError("wahlap_user_not_found", HTTPStatus.NOT_FOUND)
    if result != 0:
        raise RequestError("wahlap_sync_failed", HTTPStatus.BAD_GATEWAY)
    return userid


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


def dispatch_to_target(target: SyncTarget, userdata: LocalUserdata, *, publication_store=None) -> dict[str, Any]:
    songs = userdata.parsed.get("songs", [])
    song_count = len(songs) if isinstance(songs, list) else 0
    if target.kind == "local":
        write_local_snapshot(userdata.userid, userdata.parsed, **({"publication_store": publication_store} if publication_store is not None else {}))
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
                    "message": "请通过已登录的 Viewer 账号同步成绩。",
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
        self.send_json(HTTPStatus.GONE, {
            "ok": False,
            "error": "sync_dispatch_retired",
            "message": "请通过已登录的 Viewer 账号同步成绩。",
        })

    def handle_score_token_management(self) -> None:
        # Viewer manages tokens in its authenticated owner/current transaction.
        # Loopback plus a userid body cannot prove an account principal. Keep
        # an explicit retired endpoint; do not forward forged owner fields.
        self.send_json(HTTPStatus.GONE, {
            "ok": False,
            "error": "token_management_retired",
            "message": "请通过已登录的 Viewer 账号或私聊机器人管理成绩 token。",
        })

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
