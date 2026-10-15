from __future__ import annotations
from ..concurrency import serialized
import os
from pathlib import Path
_CENTER_ROOT = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))

from ...public.provider import query_with_mode as _query_music_with_mode

from typing import Any

from nonebot.adapters import Bot

from io import BytesIO

from typing import Dict

from nonebot.adapters import Event

from taiko_bot.runtime.player.center.song_title_query import FUZZY_ACCEPT_THRESHOLD

from PIL import Image

from PIL import ImageDraw

from PIL import ImageFont

from typing import List

from nonebot.matcher import Matcher

from nonebot.exception import MatcherException

from nonebot.adapters.onebot.v11 import Message

from nonebot.adapters.onebot.v11 import MessageSegment

from typing import Optional

from pathlib import Path

from nonebot.params import RegexGroup

from nonebot.rule import Rule

from typing import Set

from typing import Tuple

from feature_handler.feature_handler import apply_switch

import asyncio

from datetime import datetime

from ...player.center.messages import extract_plain_text as extract_platform_plain_text

from feature_handler.feature_handler import feature_on

from nonebot import get_driver

from ...player.center.messages import get_group_identifier

from ...player.center.messages import get_group_key

import httpx

from taiko_bot.runtime.player.center.song_title_query import is_accepted_similarity

from ...player.center.messages import is_qq_official_event

from ...player.center.messages import is_qq_official_group_event

import json

from nonebot import logger

from nonebot.plugin import on_fullmatch

from nonebot.plugin import on_message

from nonebot.plugin import on_regex

import random

import re

from ...player.center.messages import send_image_reply

from ...player.center.messages import send_text_reply

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule

draw_guess_rule = feature_on("taiko_draw_guess")

SONG_DATA_PATH = (_CENTER_ROOT / "songs/song_data.json")

FONT_PATH = "assets/fonts/DDFont.ttf"

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

DRAW_GUESS_DATA_DIR = (_CENTER_ROOT / "data/draw_guess")

DRAW_GUESS_IMAGE_DIR = DRAW_GUESS_DATA_DIR / "images"

DRAW_GUESS_DB_PATH = DRAW_GUESS_DATA_DIR / "records.json"

DRAW_GUESS_TEMPLATE_PATH = (_CENTER_ROOT / "assets/templates/太鼓你画我猜.png")

DRAW_GUESS_TIMEOUT_SECONDS = 600

DRAW_GUESS_MAX_TRIES = 5

DRAW_GUESS_REPORT_DELETE_THRESHOLD = 5

DRAW_GUESS_DB_LOCK = asyncio.Lock()

DRAW_GUESS_MAKE_SESSIONS: Dict[str, Dict[str, Any]] = {}

DRAW_GUESS_GROUP_SESSIONS: Dict[str, Dict[str, Any]] = {}

def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段，并兼容复制后的 @Sakura 文本前缀。
    """
    return _strip_copied_sakura_prefix(extract_platform_plain_text(event))

QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS = (
    "请先绑定账号",
    "请输入正确",
    "参数错误",
    "查不到呢",
    "失败",
    "未找到",
    "暂无",
    "没有可用于",
    "没有可用",
    "没有待确认",
    "请更新数据后",
    "还未上传数据",
    "查询失败",
    "生成失败",
    "推荐计算失败",
    "验证未通过",
    "请确认",
    "请检查",
    "未支持",
    "未完成",
    "未找到该鼓众ID",
    "缺少登录cookie",
    "当前未绑定",
    "该歌曲没有",
    "未找到匹配",
    "未找到满足",
)

def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)

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

def _is_superuser_event(event: MessageEvent) -> bool:
    try:
        configured = get_driver().config.superusers
    except Exception:
        configured = set()
    return str(event.get_user_id() or "").strip() in {
        str(item or "").strip() for item in configured
    }

def _can_manage_group_feature(event: MessageEvent) -> bool:
    if _event_group_scope_id(event) is None:
        return False
    if is_qq_official_group_event(event):
        # QQ 官方群事件当前不暴露可靠的群管理身份信息，只能退化为允许群成员切换群内功能。
        return True
    role = _sender_attr(getattr(event, "sender", None), "role").lower()
    return role in {"owner", "admin"} or _is_superuser_event(event)

def _format_draw_guess_user_id_label(user_id: str) -> str:
    normalized = str(user_id or "").strip()
    if not normalized:
        return "未知ID"
    if normalized.isdigit():
        return f"QQ:{normalized}"
    if len(normalized) <= 12:
        return f"ID:{normalized}"
    return f"ID:{normalized[:4]}...{normalized[-4:]}"

async def _ensure_group_feature_manage_permission(
    matcher: Matcher,
    event: MessageEvent,
) -> Optional[str]:
    group_scope = _event_group_scope_id(event)
    if group_scope is None:
        await matcher.finish("该指令仅支持群聊使用。")
    if _can_manage_group_feature(event):
        return group_scope
    await matcher.finish("仅群管理员、群主或 bot 超级用户可调整本群功能开关。")

def _should_attach_quick_actions_to_text(event: MessageEvent, text: str) -> bool:
    if not is_qq_official_group_event(event):
        return False
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(
        keyword in normalized for keyword in QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS
    )

async def _finish_text_reply(
    matcher: Matcher,
    event: MessageEvent,
    text: str,
    *,
    quick_actions: Optional[bool] = None,
    markdown_text: Optional[str] = None,
) -> None:
    attach_quick_actions = (
        _should_attach_quick_actions_to_text(event, text)
        if quick_actions is None
        else bool(quick_actions)
    )
    resolved_markdown_text = markdown_text
    if resolved_markdown_text is None and text == _taiko_bind_usage_message(event):
        resolved_markdown_text = _taiko_bind_usage_markdown_message(event)
    await send_text_reply(
        matcher,
        event,
        text,
        quick_actions=attach_quick_actions,
        markdown_text=resolved_markdown_text,
    )

async def _finish_image_reply(
    matcher: Matcher,
    event: MessageEvent,
    image_bytes: bytes | BytesIO | Path,
    prefix_text: str = "",
    *,
    quick_actions: bool = False,
    prefer_markdown_image: bool = False,
    markdown_image_name: str = "taiko",
) -> None:
    await send_image_reply(
        matcher,
        event,
        image_bytes,
        prefix_text=prefix_text,
        quick_actions=quick_actions,
        prefer_markdown_image=prefer_markdown_image,
        markdown_image_name=markdown_image_name,
    )

def load_song_data():
    """读取 song_data.json（dict 列表）"""
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_song_title_by_id(song_id: str) -> str:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item.get("song_name_jp") or item.get("song_name") or ""
    return ""

def _load_alias_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> List[str]:
    if "\n" in text:
        wrapped_lines: List[str] = []
        for raw_line in text.splitlines():
            if raw_line == "":
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(_wrap_text(draw, raw_line, font, max_w))
        return wrapped_lines if wrapped_lines else [""]

    if draw.textlength(text, font=font) <= max_w:
        return [text]
    lines: List[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        test = current + ch
        if draw.textlength(test, font=font) <= max_w or not current:
            current = test
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines

def render_draw_guess_list_image(
    header: str,
    lines: List[str],
    width: int = 1120,
    padding: int = 28,
    font_size: int = 24,
    line_gap: int = 8,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(FONT_PATH, font_size)
    title_font = _load_alias_font(FONT_PATH, font_size + 6)
    tmp = Image.new("RGBA", (width, 10), (*bg_color, 255))
    draw = ImageDraw.Draw(tmp)

    wrapped: List[Tuple[str, bool]] = []
    wrapped.extend(
        (line, True)
        for line in _wrap_text(draw, header, title_font, width - padding * 2)
    )
    wrapped.append(("", False))
    for line in lines:
        chunks = _wrap_text(draw, line, font, width - padding * 2)
        if not chunks:
            wrapped.append(("", False))
            continue
        for chunk in chunks:
            wrapped.append((chunk, False))

    title_line_h = int((font_size + 6) * 1.45)
    body_line_h = int(font_size * 1.4)
    content_height = 0
    for _, is_title in wrapped:
        content_height += title_line_h if is_title else body_line_h
        content_height += line_gap
    height = max(220, padding * 2 + content_height)

    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)
    y = padding
    for line, is_title in wrapped:
        use_font = title_font if is_title else font
        draw.text((padding, y), line, fill=fg_color, font=use_font)
        y += (title_line_h if is_title else body_line_h) + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def _taiko_bind_usage_message(event: Optional[MessageEvent] = None) -> str:
    base = (
        "请先绑定账号。\n"
        "国服/CN：发送“绑定 你的鼓众广场ID”或“绑定+你的鼓众广场ID”进行绑定。\n"
        "日服/JP：可直接发送“绑定 12位Hiroba太鼓番”绑定，默认通过服务账号读取公开成绩；"
        "若账号设为非公开，可再发送“绑定hiroba 邮箱 密码 [太鼓番]”。"
    )
    if event is not None and is_qq_official_event(event):
        return (
            f"{base}\n"
            "如果您以前在其他搭建了 Sakura Taiko 模块的 bot 上绑定过数据，"
            "可用原 QQ 私聊旧 bot 发送“迁移验证码”，再私聊这里发送“绑定QQ QQ号 验证码”。\n"
            "验证码十分钟内有效。"
        )
    return base

def _taiko_bind_usage_markdown_message(
    event: Optional[MessageEvent] = None,
) -> str:
    lines = [
        "# 请先绑定账号",
        "> 当前还没有可用的成绩数据，请先完成绑定再继续查询或更新。",
        "",
        "## 国服 / CN",
        "- 发送 `绑定 你的鼓众广场ID`",
        "- 或发送 `绑定+你的鼓众广场ID`",
        "",
        "## 日服 / JP",
        "- 公开资料：发送 `绑定 12位Hiroba太鼓番`",
        "- 非公开资料：发送 `绑定hiroba 邮箱 密码 [太鼓番]`",
        "",
        "## 推荐操作",
        "1. 点击下方 `绑定` 按钮自动填入命令",
        "2. 把自己的 `鼓众广场ID / Hiroba太鼓番` 补完整后发送",
        "3. 绑定完成后点击 `更新广场` 拉取成绩数据",
    ]
    if event is not None and is_qq_official_event(event):
        lines.extend(
            [
                "",
                "## 旧绑定迁移",
                "- 如果你以前在其他 Sakura Taiko bot 上绑定过，可点击下方 `旧绑定迁移`",
                "- 用原 QQ 私聊旧 bot 发送 `迁移验证码`，再私聊这里发送 `绑定QQ QQ号 验证码`",
                "> 验证码十分钟内有效。",
            ]
        )
    return "\n".join(lines)

def queryMusic(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> List[List[Any]]:
    results, _ = _query_music_with_mode(
        name, allow_partial=allow_partial, allow_fuzzy=allow_fuzzy
    )
    return results

def _is_fuzzy_query_result(results: List[List[Any]]) -> bool:
    return (
        bool(results)
        and len(results) == 1
        and len(results[0]) >= 3
        and isinstance(results[0][2], (int, float))
    )

def _is_accepted_fuzzy_query_result(results: List[List[Any]]) -> bool:
    return _is_fuzzy_query_result(results) and is_accepted_similarity(
        results[0][2],
        FUZZY_ACCEPT_THRESHOLD,
    )

def _is_rejected_fuzzy_query_result(results: List[List[Any]]) -> bool:
    return _is_fuzzy_query_result(results) and not _is_accepted_fuzzy_query_result(
        results
    )

def _build_fuzzy_query_hint(results: List[List[Any]]) -> str:
    title = results[0][1]
    ratio = float(results[0][2]) / 100.0
    return f"你要找的可能是：{title}\n匹配度：{ratio:.2f}"

def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())

def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _song_id_to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None

def _draw_guess_user_session_key(event: MessageEvent) -> str:
    group_scope = _event_group_scope_id(event)
    scope = f"group:{group_scope}" if group_scope is not None else "private"
    return f"{scope}:user:{event.get_user_id()}"

def _draw_guess_group_session_key(event: MessageEvent) -> Optional[str]:
    return _event_group_scope_id(event)

def _session_is_expired(last_active_ts: Any) -> bool:
    return (_now_ts() - _as_int(last_active_ts, 0)) >= DRAW_GUESS_TIMEOUT_SECONDS

def _touch_session(session: Dict[str, Any]) -> None:
    session["updated_at"] = _now_ts()

def _format_song_ids(song_ids: List[int]) -> str:
    cleaned = sorted({_as_int(v, -1) for v in song_ids if _as_int(v, -1) > 0})
    return "、".join(str(v) for v in cleaned)

def _normalize_song_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).lower()

def _extract_first_image_segment(msg: Message) -> Optional[MessageSegment]:
    for seg in msg:
        if seg.type == "image":
            return seg
    return None

def _sender_attr(sender: Any, key: str) -> str:
    if sender is None:
        return ""
    if isinstance(sender, dict):
        value = sender.get(key)
    else:
        value = getattr(sender, key, None)
    return str(value).strip() if value is not None else ""

def _extract_uploader_nickname(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    card = _sender_attr(sender, "card")
    if card:
        return card
    nickname = _sender_attr(sender, "nickname")
    if nickname:
        return nickname
    author = getattr(event, "author", None)
    author_name = _sender_attr(author, "username")
    if author_name:
        return author_name
    return event.get_user_id()

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

async def _download_image_segment_bytes(
    bot: Bot, image_seg: MessageSegment
) -> Optional[bytes]:
    img_url = image_seg.data.get("url")
    if not img_url:
        file_key = image_seg.data.get("file")
        if file_key:
            try:
                img_info = await bot.call_api("get_image", file=file_key)
                img_url = img_info.get("url") if isinstance(img_info, dict) else None
            except Exception:
                img_url = None
    if not img_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(img_url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None

def _convert_image_to_png_bytes(image_bytes: bytes) -> bytes:
    with Image.open(BytesIO(image_bytes)) as img:
        mode = "RGBA" if "A" in img.getbands() else "RGB"
        normalized = img.convert(mode)
        out = BytesIO()
        normalized.save(out, format="PNG")
        return out.getvalue()

def _default_draw_guess_db() -> Dict[str, Any]:
    return {"next_id": 1, "records": [], "user_guess_stats": {}}

def _ensure_draw_guess_storage() -> None:
    DRAW_GUESS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not DRAW_GUESS_DB_PATH.exists():
        with DRAW_GUESS_DB_PATH.open("w", encoding="utf-8") as f:
            json.dump(_default_draw_guess_db(), f, ensure_ascii=False, indent=2)
            f.write("\n")

def _load_draw_guess_db() -> Dict[str, Any]:
    _ensure_draw_guess_storage()
    try:
        with DRAW_GUESS_DB_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = _default_draw_guess_db()

    if not isinstance(data, dict):
        data = _default_draw_guess_db()
    next_id = _as_int(data.get("next_id"), 1)
    if next_id < 1:
        next_id = 1
    records = data.get("records")
    if not isinstance(records, list):
        records = []
    user_guess_stats = data.get("user_guess_stats")
    if not isinstance(user_guess_stats, dict):
        user_guess_stats = {}

    cleaned: List[Dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        rid = _as_int(item.get("id"), 0)
        if rid <= 0:
            continue
        item["id"] = rid
        if "song_ids" not in item or not isinstance(item["song_ids"], list):
            item["song_ids"] = []
        item["song_ids"] = [
            sid
            for sid in (_song_id_to_int(v) for v in item["song_ids"])
            if sid is not None
        ]
        for key in (
            "guess_correct_count",
            "guess_wrong_count",
            "like_count",
            "report_count",
        ):
            item[key] = max(0, _as_int(item.get(key), 0))
        item["active"] = bool(item.get("active", True))
        cleaned.append(item)

    cleaned_user_stats: Dict[str, Dict[str, Any]] = {}
    for user_id_raw, payload in user_guess_stats.items():
        user_id = str(user_id_raw).strip()
        if not user_id:
            continue
        if not isinstance(payload, dict):
            payload = {}
        nickname = str(payload.get("nickname") or user_id)
        total_correct = max(0, _as_int(payload.get("total_correct"), 0))
        groups = payload.get("groups")
        if not isinstance(groups, dict):
            groups = {}
        cleaned_groups: Dict[str, Dict[str, Any]] = {}
        for gid_raw, g_payload in groups.items():
            gid = str(gid_raw).strip()
            if not gid:
                continue
            if not isinstance(g_payload, dict):
                g_payload = {}
            cleaned_groups[gid] = {
                "correct": max(0, _as_int(g_payload.get("correct"), 0)),
                "group_name": str(g_payload.get("group_name") or f"群{gid}"),
            }
        cleaned_user_stats[user_id] = {
            "nickname": nickname,
            "total_correct": total_correct,
            "groups": cleaned_groups,
        }

    return {
        "next_id": next_id,
        "records": cleaned,
        "user_guess_stats": cleaned_user_stats,
    }

def _save_draw_guess_db(data: Dict[str, Any]) -> None:
    with DRAW_GUESS_DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def _draw_guess_record_image_path(record: Dict[str, Any]) -> Path:
    image_file = str(record.get("image_file") or "").strip()
    if image_file:
        p = Path(image_file)
        if p.is_absolute():
            return p
        return DRAW_GUESS_DATA_DIR / p
    return DRAW_GUESS_IMAGE_DIR / f"{_as_int(record.get('id'), 0)}.png"

def _find_draw_guess_record(
    records: List[Dict[str, Any]], record_id: int
) -> Optional[Dict[str, Any]]:
    for item in records:
        if _as_int(item.get("id"), -1) == record_id:
            return item
    return None

def _resolve_draw_song_selection(
    results: List[List[Any]],
) -> Tuple[Optional[str], List[int], str]:
    if not results:
        return None, [], ""

    fuzzy_hint = (
        _build_fuzzy_query_hint(results)
        if _is_rejected_fuzzy_query_result(results)
        else ""
    )
    normalized: List[Tuple[int, str]] = []
    seen_ids: Set[int] = set()
    for row in results:
        if not row:
            continue
        song_id = _song_id_to_int(row[0])
        if song_id is None or song_id in seen_ids:
            continue
        seen_ids.add(song_id)
        title = str(row[1] if len(row) > 1 else "").strip()
        if not title:
            title = get_song_title_by_id(str(song_id)) or f"id{song_id}"
        normalized.append((song_id, title))

    if not normalized:
        return None, [], fuzzy_hint

    song_ids = [sid for sid, _ in normalized]
    title_keys = {
        _normalize_song_title(title) for _, title in normalized if title.strip()
    }
    if len(song_ids) == 1 or (title_keys and len(title_keys) == 1):
        display_title = normalized[0][1]
        for _, title in normalized:
            if title.strip():
                display_title = title
                break
        return display_title, song_ids, fuzzy_hint
    return None, [], fuzzy_hint

def _build_draw_song_candidates_text(results: List[List[Any]]) -> str:
    lines = ["匹配到多首歌曲，请输入更精确的歌名或歌曲id。可随时输入“0”退出"]
    for row in results[:20]:
        if not row:
            continue
        song_id = row[0]
        title = str(row[1] if len(row) > 1 else "").strip() or f"id{song_id}"
        lines.append(f"id{song_id} {title}")
    if len(results) > 20:
        lines.append("...")
    return "\n".join(lines)

def _build_draw_guess_confirm_text(
    song_title: str, song_ids: List[int], fuzzy_hint: str = ""
) -> str:
    song_ids_text = _format_song_ids(song_ids)
    confirm_text = (
        f"您要制作的歌名是{song_title}，id是{song_ids_text}，确认请发送“绘图”"
    )
    if fuzzy_hint:
        return f"{fuzzy_hint}\n{confirm_text}"
    return confirm_text

def _resolve_draw_guess_song_input_message(
    text: str,
) -> Tuple[str, str, Optional[str], List[int]]:
    plain = (text or "").strip()
    if not plain:
        return (
            "need_text",
            "请输入歌名或歌曲id。可随时输入“0”退出",
            None,
            [],
        )

    try:
        results = queryMusic(plain)
    except Exception as e:
        return ("error", f"查询歌曲失败：{e}", None, [])

    if not results:
        return (
            "not_found",
            "未找到匹配的歌曲，请输入歌名或歌曲id。可随时输入“0”退出",
            None,
            [],
        )

    song_title, song_ids, fuzzy_hint = _resolve_draw_song_selection(results)
    if not song_title or not song_ids:
        return ("multiple", _build_draw_song_candidates_text(results), None, [])

    return (
        "confirmed",
        _build_draw_guess_confirm_text(song_title, song_ids, fuzzy_hint),
        song_title,
        song_ids,
    )

def _draw_guess_user_rank_sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
    return (-_as_int(item.get("correct"), 0), str(item.get("user_id") or ""))

async def _increment_draw_guess_user_correct_count(
    user_id: str,
    nickname: str,
    group_id: Optional[str],
    group_name: str,
    delta: int = 1,
) -> None:
    if delta <= 0:
        return
    user_id_text = str(user_id).strip()
    if not user_id_text:
        return
    group_id_text = str(group_id).strip() if group_id is not None else ""
    nickname_text = str(nickname or user_id_text).strip() or user_id_text
    group_name_text = str(group_name or "").strip()
    if group_id_text and not group_name_text:
        group_name_text = f"群{group_id_text}"

    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        user_stats = data.get("user_guess_stats")
        if not isinstance(user_stats, dict):
            user_stats = {}
            data["user_guess_stats"] = user_stats

        payload = user_stats.get(user_id_text)
        if not isinstance(payload, dict):
            payload = {}
            user_stats[user_id_text] = payload

        payload["nickname"] = nickname_text
        payload["total_correct"] = max(
            0, _as_int(payload.get("total_correct"), 0) + delta
        )

        groups = payload.get("groups")
        if not isinstance(groups, dict):
            groups = {}
            payload["groups"] = groups

        if group_id_text:
            group_payload = groups.get(group_id_text)
            if not isinstance(group_payload, dict):
                group_payload = {}
                groups[group_id_text] = group_payload
            group_payload["correct"] = max(
                0, _as_int(group_payload.get("correct"), 0) + delta
            )
            if group_name_text:
                group_payload["group_name"] = group_name_text
            elif not group_payload.get("group_name"):
                group_payload["group_name"] = f"群{group_id_text}"

        _save_draw_guess_db(data)

async def _list_draw_guess_user_rank_entries(
    group_id: Optional[str], all_groups: bool
) -> List[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        user_stats = data.get("user_guess_stats")
        if not isinstance(user_stats, dict):
            return []

        target_group = str(group_id) if group_id is not None else None
        out: List[Dict[str, Any]] = []
        for user_id_raw, payload in user_stats.items():
            user_id = str(user_id_raw).strip()
            if not user_id:
                continue
            if not isinstance(payload, dict):
                continue
            nickname = str(payload.get("nickname") or user_id)
            if all_groups:
                correct = max(0, _as_int(payload.get("total_correct"), 0))
                if correct <= 0:
                    continue
                out.append(
                    {
                        "user_id": user_id,
                        "nickname": nickname,
                        "correct": correct,
                    }
                )
                continue

            if target_group is None:
                continue
            groups = payload.get("groups")
            if not isinstance(groups, dict):
                continue
            group_payload = groups.get(target_group)
            if not isinstance(group_payload, dict):
                continue
            correct = max(0, _as_int(group_payload.get("correct"), 0))
            if correct <= 0:
                continue
            out.append(
                {
                    "user_id": user_id,
                    "nickname": nickname,
                    "correct": correct,
                    "group_name": str(
                        group_payload.get("group_name") or f"群{target_group}"
                    ),
                }
            )

        out.sort(key=_draw_guess_user_rank_sort_key)
        return out

def _resolve_guess_with_query_music_detail(
    text: str,
) -> Tuple[Set[int], str, Optional[str]]:
    plain = (text or "").strip()
    if not plain:
        return set(), "", None

    try:
        results = queryMusic(plain)
    except Exception:
        return set(), plain, None

    if not results:
        return set(), plain, None

    normalized: List[Tuple[int, str]] = []
    for row in results:
        if not row:
            continue
        sid = _song_id_to_int(row[0])
        if sid is None:
            continue
        title = str(row[1] if len(row) > 1 else "").strip()
        if not title:
            title = get_song_title_by_id(str(sid)) or f"id{sid}"
        normalized.append((sid, title))

    if not normalized:
        return set(), plain, None

    display_title = normalized[0][1]
    for _, title in normalized:
        if title:
            display_title = title
            break

    if _is_rejected_fuzzy_query_result(results):
        return set(), display_title, _build_fuzzy_query_hint(results)

    resolved_title, resolved_ids, _ = _resolve_draw_song_selection(results)
    if resolved_ids:
        return set(resolved_ids), (resolved_title or display_title), None

    if _is_accepted_fuzzy_query_result(results):
        return {normalized[0][0]}, display_title, None

    lines = ["你要猜的可能是以下歌曲："]
    for sid, title in normalized:
        lines.append(f"id{sid} {title}")
    return set(), display_title, "\n".join(lines)

async def _pick_random_active_draw_guess_record() -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records", [])
        if not isinstance(records, list):
            return None
        candidates: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if not bool(record.get("active", True)):
                continue
            song_ids = [
                sid
                for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
                if sid is not None
            ]
            if not song_ids:
                continue
            if not _draw_guess_record_image_path(record).exists():
                continue
            candidates.append(dict(record))
        if not candidates:
            return None
        return random.choice(candidates)

async def _get_draw_guess_record(record_id: int) -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records", [])
        if not isinstance(records, list):
            return None
        record = _find_draw_guess_record(records, record_id)
        if record is None:
            return None
        return dict(record)

async def _create_draw_guess_record(
    song_title: str,
    song_ids: List[int],
    uploader: Dict[str, str],
    image_bytes: bytes,
) -> Tuple[Optional[int], Optional[str]]:
    try:
        png_bytes = _convert_image_to_png_bytes(image_bytes)
    except Exception as e:
        return None, f"图片处理失败：{e}"

    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            records = []
            data["records"] = records

        record_id = max(1, _as_int(data.get("next_id"), 1))
        data["next_id"] = record_id + 1
        image_name = f"{record_id}.png"
        image_path = DRAW_GUESS_IMAGE_DIR / image_name
        image_rel = f"images/{image_name}"

        try:
            with image_path.open("wb") as f:
                f.write(png_bytes)
        except Exception as e:
            try:
                _save_draw_guess_db(data)
            except Exception:
                pass
            return None, f"保存图片失败：{e}"

        record = {
            "id": record_id,
            "song_title": song_title,
            "song_ids": sorted(
                {_as_int(sid, -1) for sid in song_ids if _as_int(sid, -1) > 0}
            ),
            "uploader_qq": uploader.get("qq", ""),
            "uploader_nickname": uploader.get("nickname", ""),
            "uploader_group_id": uploader.get("group_id", ""),
            "uploader_group_name": uploader.get("group_name", ""),
            "image_file": image_rel,
            "active": True,
            "guess_correct_count": 0,
            "guess_wrong_count": 0,
            "like_count": 0,
            "report_count": 0,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        records.append(record)
        try:
            _save_draw_guess_db(data)
        except Exception as e:
            try:
                image_path.unlink()
            except Exception:
                pass
            return None, f"保存记录失败：{e}"
        return record_id, None

async def _update_draw_guess_record_counters(
    record_id: int,
    guess_correct_delta: int = 0,
    guess_wrong_delta: int = 0,
    like_delta: int = 0,
    report_delta: int = 0,
    set_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            return None
        record = _find_draw_guess_record(records, record_id)
        if record is None:
            return None

        record["guess_correct_count"] = max(
            0, _as_int(record.get("guess_correct_count"), 0) + guess_correct_delta
        )
        record["guess_wrong_count"] = max(
            0, _as_int(record.get("guess_wrong_count"), 0) + guess_wrong_delta
        )
        record["like_count"] = max(0, _as_int(record.get("like_count"), 0) + like_delta)
        record["report_count"] = max(
            0, _as_int(record.get("report_count"), 0) + report_delta
        )
        if set_active is not None:
            record["active"] = bool(set_active)

        _save_draw_guess_db(data)
        return dict(record)

async def _list_draw_guess_records_by_uploader(user_id: str) -> List[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            return []
        matched = [
            dict(item)
            for item in records
            if isinstance(item, dict)
            and str(item.get("uploader_qq", "")) == str(user_id)
        ]
        matched.sort(key=lambda x: _as_int(x.get("id"), 0))
        return matched

def _get_active_group_guess_session(group_key: str) -> Optional[Dict[str, Any]]:
    session = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
    if session is None:
        return None
    if _session_is_expired(session.get("updated_at")):
        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        return None
    return session

async def _draw_guess_make_session_rule(event: Event) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    session_key = _draw_guess_user_session_key(event)
    return session_key in DRAW_GUESS_MAKE_SESSIONS

def file_to_bytesio(path: Path) -> BytesIO:
    """
    将本地文件读入 BytesIO，并重置指针到起始位置
    """
    bio = BytesIO()
    with path.open("rb") as f:
        bio.write(f.read())
    bio.seek(0)
    return bio

async def _finish_with_image_fallback(
    matcher: Matcher,
    event: MessageEvent,
    text: str,
    image: bytes | BytesIO | Path,
    fallback_note: str = "（图片发送失败，请稍后重试）",
    *,
    prefer_markdown_image: Optional[bool] = None,
    markdown_image_name: str = "fumen",
) -> None:
    if prefer_markdown_image is None:
        prefer_markdown_image = _is_qq_official_event(event)
    try:
        await _finish_image_reply(
            matcher,
            event,
            image,
            prefix_text=text,
            prefer_markdown_image=prefer_markdown_image,
            markdown_image_name=markdown_image_name,
        )
    except MatcherException:
        raise
    except Exception as e:
        logger.exception("send_image_failed text=%s error=%s", text.splitlines()[0], e)
        await _finish_text_reply(matcher, event, f"{text}\n{fallback_note}")

draw_guess_switch = on_regex(
    r"^(开启|关闭)太鼓你画我猜功能$",
    priority=10,
    rule=taiko_rule,
    block=True,
)

@draw_guess_switch.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        enabled = (groups[0] if groups else "") == "开启"
        group_scope = await _ensure_group_feature_manage_permission(matcher, event)
        group_key = get_group_key(event=event)
        if not group_scope or group_key is None:
            await matcher.finish("该指令仅支持群聊使用。")
        changed = apply_switch(group_key, "taiko_draw_guess", enabled)
        if not enabled:
            DRAW_GUESS_GROUP_SESSIONS.pop(group_scope, None)
            prefix = f"group:{group_scope}:user:"
            for key in list(DRAW_GUESS_MAKE_SESSIONS.keys()):
                if key.startswith(prefix):
                    DRAW_GUESS_MAKE_SESSIONS.pop(key, None)

        state_text = "开启" if enabled else "关闭"
        if changed:
            await matcher.finish(f"太鼓你画我猜功能已{state_text}（本群）")
        await matcher.finish(f"太鼓你画我猜功能已是{state_text}状态（本群）")

draw_guess_make_start = on_regex(
    r"^画太鼓歌名(?:\s*(.+))?$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

draw_guess_make_router = on_message(
    priority=4,
    rule=taiko_rule & draw_guess_rule & Rule(_draw_guess_make_session_rule),
    block=True,
)

@draw_guess_make_start.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        session_key = _draw_guess_user_session_key(event)
        DRAW_GUESS_MAKE_SESSIONS[session_key] = {
            "stage": "await_song",
            "updated_at": _now_ts(),
            "song_title": "",
            "song_ids": [],
        }
        first_input = str(groups[0] if groups and groups[0] is not None else "").strip()
        if not first_input:
            await matcher.finish(
                "请输入歌名或歌曲id。可随时输入“0”退出", reply_message=True
            )
        if first_input == "0":
            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish("流程已结束", reply_message=True)

        status, text, song_title, song_ids = _resolve_draw_guess_song_input_message(
            first_input
        )
        if status == "confirmed" and song_title and song_ids:
            DRAW_GUESS_MAKE_SESSIONS[session_key]["song_title"] = song_title
            DRAW_GUESS_MAKE_SESSIONS[session_key]["song_ids"] = song_ids
            DRAW_GUESS_MAKE_SESSIONS[session_key]["stage"] = "await_draw_confirm"
            _touch_session(DRAW_GUESS_MAKE_SESSIONS[session_key])
            await matcher.finish(text, reply_message=True)
        await matcher.finish(text, reply_message=True)

@draw_guess_make_router.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        session_key = _draw_guess_user_session_key(event)
        session = DRAW_GUESS_MAKE_SESSIONS.get(session_key)
        if session is None:
            return

        if _session_is_expired(session.get("updated_at")):
            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish("流程已结束", reply_message=True)

        stage = str(session.get("stage") or "")
        plain_text = extract_plain_text(event).strip()

        if stage == "await_song":
            _touch_session(session)
            if plain_text == "0":
                DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
                await matcher.finish("流程已结束", reply_message=True)
            status, text, song_title, song_ids = _resolve_draw_guess_song_input_message(
                plain_text
            )
            if status == "confirmed" and song_title and song_ids:
                session["song_title"] = song_title
                session["song_ids"] = song_ids
                session["stage"] = "await_draw_confirm"
                _touch_session(session)
                await matcher.finish(text, reply_message=True)
            await matcher.finish(text, reply_message=True)

        if stage == "await_draw_confirm":
            _touch_session(session)
            if plain_text == "0":
                DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
                await matcher.finish("流程已结束", reply_message=True)
            if plain_text != "绘图":
                await matcher.finish("确认请发送“绘图”", reply_message=True)

            session["stage"] = "await_image"
            _touch_session(session)
            if DRAW_GUESS_TEMPLATE_PATH.exists():
                await _finish_with_image_fallback(
                    matcher,
                    event,
                    "请上传图片",
                    file_to_bytesio(DRAW_GUESS_TEMPLATE_PATH),
                    fallback_note="（模板图片发送失败，请直接上传图片）",
                    prefer_markdown_image=False,
                    markdown_image_name="draw-guess-template",
                )
                return
            logger.warning("draw_guess_template_missing path=%s", DRAW_GUESS_TEMPLATE_PATH)
            await matcher.finish("请上传图片", reply_message=True)

        if stage == "await_image":
            image_seg = _extract_first_image_segment(event.get_message())
            if image_seg is None:
                _touch_session(session)
                if plain_text == "0":
                    DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
                    await matcher.finish("流程已结束", reply_message=True)
                await matcher.finish("请上传图片", reply_message=True)

            _touch_session(session)
            image_bytes = await _download_image_segment_bytes(bot, image_seg)
            if not image_bytes:
                await matcher.finish("请上传图片", reply_message=True)

            song_title = str(session.get("song_title") or "").strip()
            song_ids = [
                sid
                for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
                if sid is not None
            ]
            if not song_title or not song_ids:
                DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
                await matcher.finish("流程已结束", reply_message=True)

            group_scope = _event_group_scope_id(event)
            uploader = {
                "qq": event.get_user_id(),
                "nickname": _extract_uploader_nickname(event),
                "group_id": group_scope or "",
                "group_name": await _extract_uploader_group_name(bot, event),
            }
            record_id, err = await _create_draw_guess_record(
                song_title=song_title,
                song_ids=song_ids,
                uploader=uploader,
                image_bytes=image_bytes,
            )
            if record_id is None:
                logger.warning("draw_guess_create_record_failed err=%s", err)
                await matcher.finish("请上传图片", reply_message=True)

            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish(
                f"图片已上传，本条太鼓你画我猜编号为{record_id}", reply_message=True
            )

        DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
        await matcher.finish("流程已结束", reply_message=True)

draw_guess_start = on_fullmatch(
    "猜太鼓歌名", priority=10, rule=taiko_rule & draw_guess_rule, block=True
)

draw_guess_answer = on_regex(
    r"^猜(?!太鼓歌名)\s*(.+)$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

@draw_guess_start.handle()
async def _(matcher: Matcher, event: MessageEvent):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        group_key = _draw_guess_group_session_key(event)
        if group_key is None:
            await matcher.finish("该指令仅支持群聊使用。", reply_message=True)

        active_session = _get_active_group_guess_session(group_key)
        if active_session is not None:
            await matcher.finish("本群尚有猜歌名未结束", reply_message=True)

        record = await _pick_random_active_draw_guess_record()
        if record is None:
            await matcher.finish("暂无可用你画我猜图片。", reply_message=True)

        image_path = _draw_guess_record_image_path(record)
        if not image_path.exists():
            await matcher.finish("暂无可用你画我猜图片。", reply_message=True)

        song_ids = [
            sid
            for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
            if sid is not None
        ]
        DRAW_GUESS_GROUP_SESSIONS[group_key] = {
            "record_id": _as_int(record.get("id"), 0),
            "song_title": str(record.get("song_title") or ""),
            "song_ids": song_ids,
            "uploader_group_name": str(record.get("uploader_group_name") or ""),
            "uploader_nickname": str(record.get("uploader_nickname") or ""),
            "remaining": DRAW_GUESS_MAX_TRIES,
            "wrong_attempts": 0,
            "updated_at": _now_ts(),
        }
        await _finish_with_image_fallback(
            matcher,
            event,
            f"已发送图片，请输入“猜+歌名”，例如猜测图片中歌曲为百花缭乱，则输入“猜百花缭乱”，目前有{DRAW_GUESS_MAX_TRIES}次机会",
            file_to_bytesio(image_path),
            fallback_note="（题面图片发送失败，请重新发送“猜太鼓歌名”）",
            prefer_markdown_image=False,
            markdown_image_name="draw-guess",
        )

@draw_guess_answer.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent, groups=RegexGroup()):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        group_key = _draw_guess_group_session_key(event)
        if group_key is None:
            return

        existing = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
        if existing and _session_is_expired(existing.get("updated_at")):
            DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
            await matcher.finish("流程已结束", reply_message=True)

        session = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
        if session is None:
            return

        guess_text = str(groups[0] if groups and groups[0] is not None else "").strip()
        _touch_session(session)

        guessed_song_ids, guessed_song_title, candidate_tip = (
            _resolve_guess_with_query_music_detail(guess_text)
        )
        if candidate_tip:
            await matcher.finish(candidate_tip, reply_message=True)
        target_song_ids = {
            sid
            for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
            if sid is not None
        }
        is_correct = bool(guessed_song_ids & target_song_ids)
        if is_correct:
            record_id = _as_int(session.get("record_id"), 0)
            wrong_attempts = max(0, _as_int(session.get("wrong_attempts"), 0))
            group_name = await _extract_uploader_group_name(bot, event)
            await _increment_draw_guess_user_correct_count(
                user_id=event.get_user_id(),
                nickname=_extract_uploader_nickname(event),
                group_id=group_key,
                group_name=group_name,
                delta=1,
            )
            updated = await _update_draw_guess_record_counters(
                record_id,
                guess_correct_delta=1,
                guess_wrong_delta=wrong_attempts,
            )
            song_title = str(session.get("song_title") or "")
            song_ids = list(target_song_ids)
            uploader_group_name = str(session.get("uploader_group_name") or "未知群")
            uploader_nickname = str(session.get("uploader_nickname") or "未知用户")
            if updated is not None:
                song_title = str(updated.get("song_title") or song_title)
                song_ids = [
                    sid
                    for sid in (
                        _song_id_to_int(v) for v in (updated.get("song_ids") or song_ids)
                    )
                    if sid is not None
                ]
                uploader_group_name = str(
                    updated.get("uploader_group_name") or uploader_group_name
                )
                uploader_nickname = str(
                    updated.get("uploader_nickname") or uploader_nickname
                )

            DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
            await matcher.finish(
                f"恭喜你猜对了，这张图的歌名是{song_title}，歌曲id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}，本图片编号为{record_id}。如果你也想绘制图片，可以发送“画太鼓歌名”",
                reply_message=True,
            )

        session["wrong_attempts"] = _as_int(session.get("wrong_attempts"), 0) + 1
        session["remaining"] = max(
            0, _as_int(session.get("remaining"), DRAW_GUESS_MAX_TRIES) - 1
        )
        remaining = _as_int(session.get("remaining"), 0)
        if remaining > 0:
            guess_display = guessed_song_title if guessed_song_title else "你输入的歌名"
            await matcher.finish(
                f"正确答案不是{guess_display}哦，你猜错了，目前尚有{remaining}次机会",
                reply_message=True,
            )

        record_id = _as_int(session.get("record_id"), 0)
        wrong_attempts = _as_int(session.get("wrong_attempts"), 0)
        updated = await _update_draw_guess_record_counters(
            record_id, guess_wrong_delta=wrong_attempts
        )
        song_title = str(session.get("song_title") or "")
        song_ids = [
            sid
            for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
            if sid is not None
        ]
        uploader_group_name = str(session.get("uploader_group_name") or "未知群")
        uploader_nickname = str(session.get("uploader_nickname") or "未知用户")
        if updated is not None:
            song_title = str(updated.get("song_title") or song_title)
            song_ids = [
                sid
                for sid in (
                    _song_id_to_int(v) for v in (updated.get("song_ids") or song_ids)
                )
                if sid is not None
            ]
            uploader_group_name = str(
                updated.get("uploader_group_name") or uploader_group_name
            )
            uploader_nickname = str(updated.get("uploader_nickname") or uploader_nickname)

        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        await matcher.finish(
            f"本次游戏没有人猜对，这张图的歌名是{song_title}，id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}，本图片编号为{record_id}。如果你也想绘制图片，可以发送“画太鼓歌名”",
            reply_message=True,
        )

draw_guess_like = on_regex(
    r"^点赞你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

draw_guess_report = on_regex(
    r"^举报你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

draw_guess_view = on_regex(
    r"^查看你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

draw_guess_mine = on_fullmatch(
    "我的你画我猜", priority=10, rule=taiko_rule & draw_guess_rule, block=True
)

draw_guess_rank = on_regex(
    r"^(?:你画我猜排行|太鼓你画我猜排行)(?:\s*.*)?$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)

draw_guess_manual_exit = on_fullmatch("0", priority=10, rule=taiko_rule, block=False)

@draw_guess_like.handle()
async def _(matcher: Matcher, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _update_draw_guess_record_counters(record_id, like_delta=1)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)
    await matcher.finish(
        f"已为你画我猜id{record_id}点赞，本你画我猜已被{_as_int(record.get('like_count'), 0)}人点赞！",
        reply_message=True,
    )

@draw_guess_report.handle()
async def _(matcher: Matcher, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _update_draw_guess_record_counters(record_id, report_delta=1)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)

    report_count = _as_int(record.get("report_count"), 0)
    msg = f"已举报你画我猜id{record_id}，本你画我猜已被{report_count}人举报！"
    if report_count == DRAW_GUESS_REPORT_DELETE_THRESHOLD:
        await _update_draw_guess_record_counters(record_id, set_active=False)
        msg += f"\n你画我猜id{record_id}已删除。"
    await matcher.finish(msg, reply_message=True)

@draw_guess_view.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _get_draw_guess_record(record_id)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)

    image_path = _draw_guess_record_image_path(record)
    if not image_path.exists():
        await matcher.finish("该id不存在", reply_message=True)

    song_ids = [
        sid
        for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
        if sid is not None
    ]
    song_title = str(record.get("song_title") or "")
    uploader_group_name = str(record.get("uploader_group_name") or "未知群")
    uploader_nickname = str(record.get("uploader_nickname") or "未知用户")
    detail = (
        f"这张图的歌名是{song_title}，id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}。"
        f"该图已被猜对{_as_int(record.get('guess_correct_count'), 0)}次，"
        f"已被猜错{_as_int(record.get('guess_wrong_count'), 0)}次，"
        f"已被点赞{_as_int(record.get('like_count'), 0)}次"
    )
    await _finish_with_image_fallback(
        matcher,
        event,
        detail,
        file_to_bytesio(image_path),
        fallback_note="（图片发送失败，仅展示文字说明）",
        prefer_markdown_image=False,
        markdown_image_name="draw-guess-view",
    )

@draw_guess_mine.handle()
async def _(matcher: Matcher, event: MessageEvent):
    user_id = event.get_user_id()
    records = await _list_draw_guess_records_by_uploader(user_id)
    if not records:
        await matcher.finish(
            "目前没有上传过你画我猜。如果你也想绘制图片，可以发送“画太鼓歌名”",
            reply_message=True,
        )

    lines: List[str] = []
    for record in records:
        song_ids = [
            sid
            for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
            if sid is not None
        ]
        lines.append(
            f"id{_as_int(record.get('id'), 0)}，歌名是{record.get('song_title', '')}，id是{_format_song_ids(song_ids)}，"
            f"该图已被猜对{_as_int(record.get('guess_correct_count'), 0)}次，"
            f"已被猜错{_as_int(record.get('guess_wrong_count'), 0)}次，"
            f"已被点赞{_as_int(record.get('like_count'), 0)}次"
        )
    nickname = _extract_uploader_nickname(event)
    header = f"用户 {nickname}的你画我猜如下："
    img_buf = render_draw_guess_list_image(header, lines)
    await _finish_with_image_fallback(
        matcher,
        event,
        header,
        BytesIO(img_buf),
        fallback_note="（列表图片发送失败，仅展示标题）",
        prefer_markdown_image=False,
        markdown_image_name="draw-guess-mine",
    )

@draw_guess_rank.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event).strip()
    m = re.match(r"^(?:你画我猜排行|太鼓你画我猜排行)\s*(.*)$", msg_text)
    arg_text = (m.group(1) if m else "") or ""
    arg_text = arg_text.strip()
    args = arg_text.split() if arg_text else []

    all_groups = False
    page = 1
    for arg in args:
        low = arg.lower()
        if low in ("-a", "--all"):
            all_groups = True
            continue
        if arg.isdigit():
            page = int(arg)
            continue
        await matcher.finish(
            "格式不正确，应为：你画我猜排行 [页码] [-a|--all]",
            reply_message=True,
        )

    if page <= 0:
        page = 1

    group_scope = _draw_guess_group_session_key(event)
    if not all_groups and group_scope is None:
        await matcher.finish(
            "默认展示本群排行，私聊请使用：你画我猜排行 -a",
            reply_message=True,
        )

    group_key = None if all_groups else group_scope
    entries = await _list_draw_guess_user_rank_entries(group_key, all_groups)
    if not entries:
        mode_text = "总群" if all_groups else "本群"
        await matcher.finish(f"当前{mode_text}暂无排行数据。", reply_message=True)

    page_size = 20 if all_groups else 10
    total = len(entries)
    total_pages = (total + page_size - 1) // page_size
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    items = entries[start : start + page_size]
    mode_text = "总群" if all_groups else "本群"
    lines = [
        f"{mode_text}你画我猜猜歌排行 第{page}/{total_pages}页（每页{page_size}条，共{total}条）"
    ]
    for idx, item in enumerate(items, start=start + 1):
        user_id = str(item.get("user_id") or "")
        nickname = str(item.get("nickname") or user_id or "未知用户")
        correct_count = _as_int(item.get("correct"), 0)
        if all_groups:
            lines.append(
                f"{idx}. {nickname}({_format_draw_guess_user_id_label(user_id)}) | 猜对{correct_count}次"
            )
        else:
            lines.append(
                f"{idx}. {nickname}({_format_draw_guess_user_id_label(user_id)}) | 本群猜对{correct_count}次"
            )
    await matcher.finish("\n".join(lines), reply_message=True)

@draw_guess_manual_exit.handle()
async def _(matcher: Matcher, event: MessageEvent):
    async with serialized(("draw", _draw_guess_group_session_key(event) or _draw_guess_user_session_key(event))):
        exited = False
        user_key = _draw_guess_user_session_key(event)
        if user_key in DRAW_GUESS_MAKE_SESSIONS:
            DRAW_GUESS_MAKE_SESSIONS.pop(user_key, None)
            exited = True

        group_key = _draw_guess_group_session_key(event)
        if group_key is not None and group_key in DRAW_GUESS_GROUP_SESSIONS:
            DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
            exited = True

        if exited:
            await matcher.finish("流程已结束", reply_message=True)
