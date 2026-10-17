from __future__ import annotations
from ..concurrency import serialized
import os
from pathlib import Path
_CENTER_ROOT = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))

from ...public.provider import query_with_mode as _query_music_with_mode

from nonebot.adapters import Bot

from io import BytesIO

from nonebot.adapters import Event

from PIL import Image

from typing import Optional

from pathlib import Path

from nonebot.rule import Rule

from typing import Tuple

import asyncio

from ...player.center.messages import extract_plain_text as extract_platform_plain_text

from feature_handler.feature_handler import feature_on

from ...player.center.messages import get_group_identifier

import httpx

from ...player.center.messages import is_qq_official_group_event

import json

from nonebot import logger

from nonebot.plugin import on_message

import re

import subprocess

from ...player.center.admin_audit import write_admin_action_log

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule

SONG_DATA_PATH = (_CENTER_ROOT / "songs/song_data.json")

COVER_DIR = (_CENTER_ROOT / "assets/cover")

OSS_COVER_PREFIX = "oss://sigaer/cover"

COPIED_SAKURA_PREFIX_PATTERN = re.compile(
    r"^(?:[@＠]sakura)(?:(?=$)|[\s\u3000:：,，/]+)",
    flags=re.IGNORECASE,
)

def _strip_copied_sakura_prefix(text: str) -> str:
    normalized = str(text or "").lstrip()
    while normalized:
        match = COPIED_SAKURA_PREFIX_PATTERN.match(normalized)
        if not match:
            break
        normalized = normalized[match.end() :].lstrip()
    return normalized

def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段，并兼容复制后的 @Sakura 文本前缀。
    """
    return _strip_copied_sakura_prefix(extract_platform_plain_text(event))

def _match_plain_text_pattern(
    event: MessageEvent,
    pattern: re.Pattern[str],
    *,
    fullmatch: bool = False,
):
    plain_text = extract_plain_text(event).strip()
    if not plain_text:
        return None
    if fullmatch:
        return pattern.fullmatch(plain_text)
    return pattern.match(plain_text)

def _event_group_scope_id(event: MessageEvent) -> Optional[str]:
    group_scope = get_group_identifier(event=event)
    if not group_scope:
        return None
    normalized = str(group_scope or "").strip()
    return normalized or None

def _default_group_scope_name(event: MessageEvent) -> str:
    group_scope = _event_group_scope_id(event)
    if not group_scope:
        return "私聊"
    explicit_name = str(getattr(event, "group_name", "") or "").strip()
    if explicit_name:
        return explicit_name
    if is_qq_official_group_event(event):
        return "官方群"
    return f"群{group_scope}"

def _upload_cover_to_oss(cover_path: Path) -> Tuple[bool, str]:
    from ..cover_upload import upload_cover
    return upload_cover(cover_path)

async def _extract_uploader_group_name(bot: Bot, event: MessageEvent) -> str:
    group_scope = _event_group_scope_id(event)
    if group_scope is None:
        return "私聊"
    if is_qq_official_group_event(event):
        return "官方群"
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return _default_group_scope_name(event)
    try:
        info = await bot.call_api(
            "get_group_info", group_id=int(group_id), no_cache=True
        )
        name = info.get("group_name") if isinstance(info, dict) else ""
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception as e:
        logger.debug("get_group_info_failed group_id=%s err=%s", group_id, e)
    return _default_group_scope_name(event)

COVER_COMMAND_RE = re.compile(r"^/?cover\s*(\d+)", flags=re.IGNORECASE)

def _extract_cover_command_match(event: MessageEvent):
    return _match_plain_text_pattern(event, COVER_COMMAND_RE)

async def _cover_command_rule(event: MessageEvent) -> bool:
    return _extract_cover_command_match(event) is not None

cover_cmd = on_message(rule=taiko_rule & Rule(_cover_command_rule))

@cover_cmd.handle()
async def handle_cover(bot: Bot, event: MessageEvent):
    """
    指令为：cover + 数字 + 图片
    - 无空格：cover1234
    - 有空格：cover 1234
    消息中必须有一张图片（同一条消息中）
    """

    # 1. 从正则捕获中获取数字
    match = _extract_cover_command_match(event)
    if match is None:
        # 正常情况下命令规则已保证这里有值，这个分支理论上不会走到
        await cover_cmd.finish("请使用：cover数字 + 一张图片，例如：cover1234 + 图片")

    song_id_str = str(match.group(1) or "").strip()
    async with serialized(("cover", song_id_str)):
        save_path = COVER_DIR / f"{song_id_str}.png"
        db_data = json.load(open(SONG_DATA_PATH, "r", encoding="utf-8"))
        id_list = [song["id"] for song in db_data]
        if int(song_id_str) not in id_list:
            await cover_cmd.finish("歌曲ID不存在，请确认后再上传封面。")
        # 2. 检查文件是否已存在
        if save_path.exists():
            uploaded, detail = await asyncio.to_thread(_upload_cover_to_oss, save_path)
            await cover_cmd.finish(detail)

        # 3. 从消息中提取图片
        msg = event.get_message()
        image_seg = None
        for seg in msg:
            if seg.type == "image":
                image_seg = seg
                break

        if image_seg is None:
            await cover_cmd.finish("请在指令中附带一张图片，例如：cover1234 + 图片")

        # 4. 获取图片 URL 并下载
        img_url = image_seg.data.get("url")

        # 某些实现下没有 url，可以尝试调用 get_image
        if not img_url:
            try:
                img_info = await bot.call_api("get_image", file=image_seg.data["file"])
                img_url = img_info.get("url")
            except Exception:
                img_url = None

        if not img_url:
            await cover_cmd.finish(
                "无法获取图片地址，可能是适配器或 go-cqhttp 配置不支持 get_image"
            )

        # 下载图片
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(img_url)
                resp.raise_for_status()
                img_bytes = resp.content
        except Exception as e:
            await cover_cmd.finish(f"下载图片失败：{e}")

        # 5. 使用 Pillow 将图片强制压缩为 400×400 并保存
        try:
            img = Image.open(BytesIO(img_bytes))
            img = img.resize((400, 400), Image.Resampling.LANCZOS)

            img.save(save_path, format="PNG")
        except Exception as e:
            await cover_cmd.finish(f"处理或保存图片失败：{e}")

        # 6. 上传到 OSS
        uploaded, detail = await asyncio.to_thread(_upload_cover_to_oss, save_path)
        group_id = _event_group_scope_id(event)
        group_name = await _extract_uploader_group_name(bot, event)
        user_nickname = ""
        if hasattr(event, "sender") and event.sender:
            user_nickname = getattr(event.sender, "nickname", "") or ""
        try:
            write_admin_action_log(
                actor_type="bot-user",
                actor_id=event.get_user_id(),
                actor_name=user_nickname or event.get_user_id(),
                source="bot-cover",
                target_type="song-cover",
                target_key=song_id_str,
                action="create",
                extra={
                    "song_id": int(song_id_str),
                    "oss_synced": bool(uploaded),
                    "oss_detail": detail,
                    "group_id": group_id,
                    "group_name": group_name,
                },
            )
        except Exception as e:
            logger.warning("admin_cover_audit_failed error=%s", e)
        if uploaded:
            await cover_cmd.finish("上传成功，原图及 200/400 缩略图已同步到 OSS")
        await cover_cmd.finish(f"本地封面已保存；{detail}")
