#!/usr/bin/env python3
"""Small signing service for direct multipart uploads to Aliyun OSS."""

from __future__ import annotations

import base64
import configparser
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import oss2
from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix


MIB = 1024 * 1024
MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024
TOKEN_LIFETIME_SECONDS = 6 * 60 * 60
URL_LIFETIME_SECONDS = 60 * 60
MAX_PARTS_PER_SIGN_REQUEST = 24
PART_ETAG_RE = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True)
class Settings:
    endpoint: str
    access_key_id: str
    access_key_secret: str
    bucket: str = "sigaer"
    prefix: str = "video_4/"

    @classmethod
    def load(cls) -> "Settings":
        config_path = Path(os.getenv("OSS_CONFIG_FILE", "/root/.ossutilconfig"))
        parser = configparser.ConfigParser()
        parser.read(config_path, encoding="utf-8")
        credentials = parser["Credentials"] if parser.has_section("Credentials") else {}

        endpoint = os.getenv("OSS_ENDPOINT") or credentials.get("endpoint", "")
        access_key_id = os.getenv("OSS_ACCESS_KEY_ID") or credentials.get("accesskeyid", "")
        access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET") or credentials.get("accesskeysecret", "")
        if not all((endpoint, access_key_id, access_key_secret)):
            raise RuntimeError("OSS credentials are incomplete")
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}"

        prefix = os.getenv("OSS_UPLOAD_PREFIX", "video_4/").strip("/") + "/"
        return cls(
            endpoint=endpoint,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            bucket=os.getenv("OSS_BUCKET", "sigaer"),
            prefix=prefix,
        )


class RateLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[address]
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_filename(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("文件名无效")
    value = unicodedata.normalize("NFC", value).strip()
    if not value or value in {".", ".."}:
        raise ValueError("文件名不能为空")
    if "/" in value or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError("文件名不能包含路径或控制字符")
    if len(value) > 180:
        raise ValueError("文件名不能超过 180 个字符")
    return value


def choose_part_size(file_size: int) -> int:
    minimum = 16 * MIB
    required = math.ceil(file_size / 9500)
    return max(minimum, math.ceil(required / MIB) * MIB)


def create_token(secret: bytes, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = _b64encode(raw)
    signature = _b64encode(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def read_token(secret: bytes, token: Any) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 1:
        raise ValueError("上传会话无效")
    encoded, supplied_signature = token.split(".", 1)
    expected_signature = _b64encode(
        hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise ValueError("上传会话校验失败")
    try:
        payload = json.loads(_b64decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("上传会话无效") from exc
    if int(payload.get("expires", 0)) < int(time.time()):
        raise ValueError("上传会话已过期，请重新选择文件")
    return payload


def create_app(settings: Settings | None = None, bucket: Any | None = None) -> Flask:
    settings = settings or Settings.load()
    bucket = bucket or oss2.Bucket(
        oss2.Auth(settings.access_key_id, settings.access_key_secret),
        settings.endpoint,
        settings.bucket,
    )
    signing_secret = hmac.new(
        settings.access_key_secret.encode("utf-8"),
        b"hdu-video-4-upload-session",
        hashlib.sha256,
    ).digest()
    limiter = RateLimiter()

    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024

    def error(message: str, status: int = 400):
        return jsonify({"ok": False, "message": message}), status

    def verified_payload(body: dict[str, Any]) -> dict[str, Any]:
        payload = read_token(signing_secret, body.get("token"))
        if not str(payload.get("key", "")).startswith(settings.prefix):
            raise ValueError("上传目标无效")
        return payload

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "target": settings.prefix.rstrip("/")})

    @app.post("/api/uploads")
    def start_upload():
        if not limiter.allow(request.remote_addr or "unknown"):
            return error("操作太频繁，请稍后再试", 429)
        body = request.get_json(silent=True) or {}
        try:
            filename = normalize_filename(body.get("filename"))
            file_size = int(body.get("size", 0))
            if file_size <= 0:
                raise ValueError("不能上传空文件")
            if file_size > MAX_FILE_SIZE:
                raise ValueError("单个文件不能超过 100 GB")
            key = settings.prefix + filename
            content_type = str(body.get("contentType") or "application/octet-stream")
            if len(content_type) > 120 or any(ord(char) < 32 for char in content_type):
                content_type = "application/octet-stream"
            part_size = choose_part_size(file_size)
            part_count = math.ceil(file_size / part_size)
            overwritten = bool(bucket.object_exists(key))
            result = bucket.init_multipart_upload(key, headers={"Content-Type": content_type})
            expires = int(time.time()) + TOKEN_LIFETIME_SECONDS
            payload = {
                "key": key,
                "uploadId": result.upload_id,
                "parts": part_count,
                "expires": expires,
            }
            token = create_token(signing_secret, payload)
            return jsonify(
                {
                    "ok": True,
                    "token": token,
                    "partSize": part_size,
                    "partCount": part_count,
                    "overwritesExisting": overwritten,
                    "expiresAt": expires,
                }
            )
        except ValueError as exc:
            return error(str(exc))
        except oss2.exceptions.OssError:
            app.logger.exception("Unable to initiate OSS multipart upload")
            return error("OSS 暂时无法创建上传任务，请稍后重试", 502)

    @app.post("/api/uploads/parts")
    def sign_parts():
        body = request.get_json(silent=True) or {}
        try:
            payload = verified_payload(body)
            raw_numbers = body.get("partNumbers")
            if not isinstance(raw_numbers, list) or not raw_numbers:
                raise ValueError("缺少分片编号")
            if len(raw_numbers) > MAX_PARTS_PER_SIGN_REQUEST:
                raise ValueError("一次最多签名 24 个分片")
            numbers = sorted({int(number) for number in raw_numbers})
            if any(number < 1 or number > int(payload["parts"]) for number in numbers):
                raise ValueError("分片编号超出范围")
            headers = {"Content-Type": "application/octet-stream"}
            urls = {
                str(number): bucket.sign_url(
                    "PUT",
                    payload["key"],
                    URL_LIFETIME_SECONDS,
                    headers=headers,
                    params={"uploadId": payload["uploadId"], "partNumber": str(number)},
                    slash_safe=True,
                )
                for number in numbers
            }
            return jsonify({"ok": True, "urls": urls})
        except (TypeError, ValueError, KeyError) as exc:
            return error(str(exc))

    @app.post("/api/uploads/complete")
    def complete_upload():
        body = request.get_json(silent=True) or {}
        try:
            payload = verified_payload(body)
            raw_parts = body.get("parts")
            if not isinstance(raw_parts, list):
                raise ValueError("分片结果无效")
            parts_by_number: dict[int, str] = {}
            for item in raw_parts:
                number = int(item.get("partNumber", 0))
                etag = str(item.get("etag", "")).strip('"')
                if number in parts_by_number or not PART_ETAG_RE.fullmatch(etag):
                    raise ValueError("分片结果无效")
                parts_by_number[number] = etag.upper()
            expected = list(range(1, int(payload["parts"]) + 1))
            if sorted(parts_by_number) != expected:
                raise ValueError("仍有分片未上传完成")
            parts = [oss2.models.PartInfo(number, parts_by_number[number]) for number in expected]
            bucket.complete_multipart_upload(payload["key"], payload["uploadId"], parts)
            return jsonify({"ok": True, "filename": payload["key"][len(settings.prefix) :]})
        except (TypeError, ValueError, KeyError) as exc:
            return error(str(exc))
        except oss2.exceptions.OssError:
            app.logger.exception("Unable to complete OSS multipart upload")
            return error("OSS 合并文件失败，请重试", 502)

    @app.post("/api/uploads/abort")
    def abort_upload():
        body = request.get_json(silent=True) or {}
        try:
            payload = verified_payload(body)
            bucket.abort_multipart_upload(payload["key"], payload["uploadId"])
            return jsonify({"ok": True})
        except (TypeError, ValueError, KeyError) as exc:
            return error(str(exc))
        except oss2.exceptions.OssError:
            return jsonify({"ok": True})

    @app.errorhandler(413)
    def request_too_large(_exc):
        return error("请求内容过大", 413)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "3104")))
