from __future__ import annotations
from taiko_bot.runtime.public.config import root as _runtime_root




import base64

import binascii

import json

from pathlib import Path

from typing import Any, Mapping

import httpx

CONFIG_PATH = Path(str(_runtime_root() / 'config.json'))

GAME_LOGIN_QR_URL = "https://wl-taiko.wahlap.net/api/user/gameInCode"

WAHLAP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541020) XWEB/16459"
)

class GameLoginQrError(RuntimeError):
    pass

def load_wahlap_authorization(config_path: Path = CONFIG_PATH) -> str:
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        raise GameLoginQrError("无法读取华立登录凭证。") from error

    authorization = str(config.get("cookie") or "").strip()
    if not authorization:
        raise GameLoginQrError("缺少华立登录凭证。")
    return authorization

def build_wahlap_headers(authorization: str) -> dict[str, str]:
    return {
        "User-Agent": WAHLAP_USER_AGENT,
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": authorization,
    }

def decode_game_login_qr(payload: Mapping[str, Any]) -> bytes:
    if payload.get("status") not in (0, "0"):
        message = str(payload.get("message") or "上游接口返回失败").strip()
        raise GameLoginQrError(message)

    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise GameLoginQrError("上游接口未返回二维码数据。")
    qr_content = data.get("qrContent")
    if not isinstance(qr_content, str) or not qr_content.strip():
        raise GameLoginQrError("上游接口未返回二维码图片。")

    try:
        image_bytes = base64.b64decode(qr_content, validate=True)
    except (binascii.Error, ValueError) as error:
        raise GameLoginQrError("上游接口返回的二维码图片无效。") from error
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise GameLoginQrError("上游接口返回的二维码图片格式无效。")
    return image_bytes

async def fetch_game_login_qr_image(authorization: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                GAME_LOGIN_QR_URL,
                headers=build_wahlap_headers(authorization),
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise GameLoginQrError("请求登录二维码失败。") from error

    if not isinstance(payload, Mapping):
        raise GameLoginQrError("上游接口响应格式无效。")
    return decode_game_login_qr(payload)
