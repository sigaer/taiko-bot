from __future__ import annotations
from ..concurrency import serialized

from ...public.provider import query_with_mode as _query_music_with_mode

from nonebot.adapters import Bot

from io import BytesIO

from nonebot.adapters import Event

from PIL import Image

from pathlib import Path

from nonebot.params import RegexGroup

from typing import Tuple

import asyncio

from feature_handler.feature_handler import feature_on

from taiko_bot.settings import get_settings

import httpx

import json

from nonebot.plugin import on_regex

import re

import subprocess

_SETTINGS = get_settings()

ROOT_DIR = _SETTINGS.root_dir

ASSETS_DIR = ROOT_DIR / "assets"

SONGS_DIR = ROOT_DIR / "songs"

taiko_rule = feature_on("taiko")  # 复用这个 Rule

SONG_DATA_PATH = SONGS_DIR / "song_data.json"

COVER_DIR = ASSETS_DIR / "cover"

OSS_COVER_PREFIX = "oss://sigaer/cover"

def _upload_cover_to_oss(cover_path: Path) -> Tuple[bool, str]:
    oss_target = f"{OSS_COVER_PREFIX}/{cover_path.name}"
    try:
        subprocess.run(
            ["ossutil", "cp", "-f", str(cover_path), oss_target],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, oss_target
    except Exception as e:
        return False, str(e)

cover_cmd = on_regex(r"^cover\s*(\d+)", flags=re.IGNORECASE, rule=taiko_rule)

@cover_cmd.handle()
async def handle_cover(bot: Bot, event: Event, reg_group=RegexGroup()):
    """
    指令为：cover + 数字 + 图片
    - 无空格：cover1234
    - 有空格：cover 1234
    消息中必须有一张图片（同一条消息中）
    """

    # 1. 从正则捕获中获取数字
    if not reg_group or not reg_group[0]:
        # 正常情况下 on_regex 能保证这里有值，这个分支理论上不会走到
        await cover_cmd.finish("请使用：cover数字 + 一张图片，例如：cover1234 + 图片")

    song_id_str = reg_group[0]  # 第一个括号捕获的就是数字部分，例如 "1234"
    async with serialized(("cover", song_id_str)):
        save_path = COVER_DIR / f"{song_id_str}.png"
        db_data = json.load(open(SONG_DATA_PATH, "r", encoding="utf-8"))
        id_list = [song["id"] for song in db_data]
        if int(song_id_str) not in id_list:
            await cover_cmd.finish("歌曲ID不存在，请确认后再上传封面。")
        # 2. 检查文件是否已存在
        if save_path.exists():
            await cover_cmd.finish("该歌曲封面已存在，若要更换请先删除旧文件。")

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
        if uploaded:
            await cover_cmd.finish("上传成功，并已同步到OSS")
        await cover_cmd.finish(f"上传成功，但同步到OSS失败：{detail}")
