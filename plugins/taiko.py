from .utils.taiko_db import get_taiko_db_connection
from taiko_bot.merged_source_id import build_center_virtual_user_id
from .utils.song_visibility import (
    is_song_id_publicly_visible,
    is_song_publicly_visible,
)
import random
import re
import asyncio
import subprocess
from io import BytesIO
from pathlib import Path
from datetime import datetime
import httpx
from PIL import Image, ImageDraw, ImageFont
import json
from fuzzywuzzy import fuzz
from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.exception import FinishedException
from nonebot.plugin import on_regex, on_fullmatch, on_message
from nonebot.params import RegexGroup
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from typing import Dict, Any, Tuple, List, Optional, Set
from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import UserdataProviderError, ensure_userdata_available
from taiko_bot.viewer_client import ViewerClientError, fetch_center_bind_info

_SETTINGS = get_settings()
ROOT_DIR = _SETTINGS.root_dir
ASSETS_DIR = ROOT_DIR / "assets"
SONGS_DIR = ROOT_DIR / "songs"


from nonebot.adapters.onebot.v11 import Message, MessageSegment
from feature_handler.feature_handler import feature_on, apply_switch
from taiko_runtime.platform_adapter import extract_plain_text as extract_platform_plain_text, get_group_key, get_identity_key, is_qq_official_event, is_qq_official_group_event, parse_identity_key, resolve_target_identity_key, send_text_reply

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule
tsearch_rule = feature_on("tsearch")
draw_guess_rule = feature_on("taiko_draw_guess")
SONG_DATA_PATH = SONGS_DIR / "song_data.json"
COVER_DIR = ASSETS_DIR / "cover"
OSS_COVER_PREFIX = "oss://sigaer/cover"
FONT_PATH = "assets/fonts/DDFont.ttf"

FUMENS_DIR = Path("assets") / "fumens"
TAIKO_MULTI_BIND_PATH = ROOT_DIR / "data" / "taiko_multi_bind.json"


def _normalize_slash_command_text(text: str) -> str:
    normalized = str(text or "").strip()
    return normalized[1:].lstrip() if normalized.startswith("/") else normalized


DRAW_GUESS_DATA_DIR = ROOT_DIR / "data" / "draw_guess"
DRAW_GUESS_IMAGE_DIR = DRAW_GUESS_DATA_DIR / "images"
DRAW_GUESS_DB_PATH = DRAW_GUESS_DATA_DIR / "records.json"
DRAW_GUESS_TEMPLATE_PATH = ASSETS_DIR / "templates" / "太鼓你画我猜.png"
DRAW_GUESS_TIMEOUT_SECONDS = 600
DRAW_GUESS_MAX_TRIES = 5
DRAW_GUESS_REPORT_DELETE_THRESHOLD = 5
DRAW_GUESS_DB_LOCK = asyncio.Lock()
DRAW_GUESS_MAKE_SESSIONS: Dict[str, Dict[str, Any]] = {}
DRAW_GUESS_GROUP_SESSIONS: Dict[str, Dict[str, Any]] = {}


def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段
    """
    return extract_platform_plain_text(event)


QQ_OFFICIAL_UNSUPPORTED_MESSAGE = (
    "该功能暂未支持 QQ 官方机器人，当前仅支持太鼓核心查询链路。"
)
QQ_OFFICIAL_UNSUPPORTED_PATTERNS = [
    re.compile(r"^(?:开发者数据|taikodevdata)\b", re.IGNORECASE),
    re.compile(r"^taiko2025$", re.IGNORECASE),
    re.compile(r"^cover\s*\d+", re.IGNORECASE),
    re.compile(r"^(开启|关闭)(pjsk|taiko|mai)功能$"),
    re.compile(r"^tsearch\s*(on|off)$", re.IGNORECASE),
    re.compile(r"^(开启|关闭)太鼓你画我猜功能$"),
    re.compile(r"^画太鼓歌名(?:\s|$)"),
    re.compile(r"^猜太鼓歌名$"),
    re.compile(r"^猜(?!太鼓歌名)\s*.+$"),
    re.compile(r"^(点赞|举报|查看)你画我猜id\s*\d+\s*$"),
    re.compile(r"^我的你画我猜$"),
    re.compile(r"^(?:你画我猜排行|太鼓你画我猜排行)(?:\s*.*)?$"),
    re.compile(r"^(开启|关闭)太鼓技术吸取功能$"),
    re.compile(r"^重置太鼓技术吸取记录$"),
    re.compile(r"^太鼓技术吸取保护$"),
    re.compile(r"^解除太鼓技术吸取保护$"),
    re.compile(r"^查看太鼓技术吸取保护名单$"),
    re.compile(r"^太鼓技术吸取记录$"),
    re.compile(r"^太鼓技术吸取.*$"),
]
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


def _is_qq_official_unsupported_command(event: MessageEvent) -> bool:
    if not is_qq_official_group_event(event):
        return False
    text = extract_plain_text(event)
    if not text:
        return False
    return any(pattern.match(text) for pattern in QQ_OFFICIAL_UNSUPPORTED_PATTERNS)


def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)


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
) -> None:
    attach_quick_actions = (
        _should_attach_quick_actions_to_text(event, text)
        if quick_actions is None
        else bool(quick_actions)
    )
    await send_text_reply(
        matcher,
        event,
        text,
        quick_actions=attach_quick_actions,
    )
    raise FinishedException


def load_song_data(*, include_hidden: bool = False):
    """读取 song_data.json（dict 列表）"""
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if include_hidden or not isinstance(payload, list):
        return payload
    return [
        item
        for item in payload
        if isinstance(item, dict) and is_song_publicly_visible(item)
    ]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def get_song_title_by_id(song_id: str) -> str:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item.get("song_name_jp") or item.get("song_name") or ""
    return ""


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


def song_id_exists(target_id: str) -> bool:
    """判断 song_data.json 中是否存在给定 id"""
    data = load_song_data()
    for item in data:
        # id 可能是 int 也可能是 str，这里统一转成 str 比较
        if str(item.get("id")) == target_id:
            return True
    return False


def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""


def _resolve_requested_identity_key(event: MessageEvent) -> Tuple[str, bool]:
    self_identity = _normalize_identity_key(get_identity_key(event=event))
    target_identity = _normalize_identity_key(resolve_target_identity_key(event=event))
    is_self_query = self_identity == target_identity
    return target_identity or self_identity, is_self_query


def _get_taiko_bind_info_from_center(identity_key: str) -> Optional[Dict[str, Any]]:
    try:
        return fetch_center_bind_info(identity_key, _SETTINGS)
    except ViewerClientError as error:
        logger.warning(
            f"center bind lookup failed: identity_key={identity_key} error={error}"
        )
        return None
    except Exception as error:
        logger.warning(
            f"unexpected center bind lookup failure: identity_key={identity_key} error={error}"
        )
        return None


def _center_bind_info_to_entry(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not info:
        return None
    bindings = info.get("bindings") or []
    ids: List[str] = []
    sources: Dict[str, str] = {}
    names: Dict[str, str] = {}
    current_slot = int(info.get("currentSlot") if info.get("currentSlot") is not None else 1)
    current_index = 0
    for item in bindings:
        taiko_id = str(getattr(item, "taiko_id", "") or "").strip()
        if not taiko_id:
            continue
        ids.append(taiko_id)
        source = str(getattr(item, "source", "") or "").strip().lower()
        if source:
            sources[taiko_id] = source
        display_name = str(getattr(item, "display_name", "") or "").strip()
        if display_name:
            names[taiko_id] = display_name
        if bool(getattr(item, "is_current", False)):
            current_index = len(ids) - 1
    if not ids:
        taiko_id = str(info.get("id") or "").strip()
        if not taiko_id:
            return None
        ids = [taiko_id]
        current_slot = 1
        current_index = 0
        current_source = str(info.get("currentSource") or "").strip().lower()
        if current_source:
            sources[taiko_id] = current_source
    return {
        "ids": ids,
        "current_slot": current_slot,
        "current_index": max(0, min(current_index, len(ids) - 1)),
        "sources": sources,
        "names": names,
    }


def _get_taiko_db_connection():
    return get_taiko_db_connection()


def _get_bind_ids(entry: Optional[Dict[str, Any]]) -> List[str]:
    if not entry:
        return []
    return [
        str(raw or "").strip()
        for raw in (entry.get("ids") or [])
        if str(raw or "").strip()
    ]


def _get_selected_bind_slot_number(entry: Optional[Dict[str, Any]]) -> int:
    ids = _get_bind_ids(entry)
    if not ids:
        return 0
    if len(ids) < 2:
        return 1
    try:
        current_slot = int(
            entry.get("current_slot", int(entry.get("current_index", 0) or 0) + 1) or 0
        )
    except Exception:
        current_slot = int(entry.get("current_index", 0) or 0) + 1
    return max(0, min(current_slot, len(ids)))


def _resolve_read_bind_target(event: MessageEvent):
    identity_key, is_self_query = _resolve_requested_identity_key(event)
    info = _get_taiko_bind_info_from_center(identity_key)
    if info is None:
        return 404
    visible = info["visible"]
    if visible == 0 and not is_self_query:
        return 403
    entry = _center_bind_info_to_entry(info)
    if entry and _get_selected_bind_slot_number(entry) == 0:
        virtual_id = build_center_virtual_user_id(identity_key)
        ensure_userdata_available(virtual_id)
        return {
            "identity_key": identity_key,
            "entry": entry,
            "is_virtual": True,
            "user_id": virtual_id,
            "source": "merged-bind",
        }
    selected_id = str(info["id"] or "").strip()
    ensure_userdata_available(selected_id)
    return {
        "identity_key": identity_key,
        "entry": entry,
        "is_virtual": False,
        "user_id": selected_id,
        "source": str(info.get("currentSource") or "wahlap"),
    }


def _resolve_read_bind_target_safe(event: MessageEvent):
    try:
        return _resolve_read_bind_target(event)
    except UserdataProviderError as error:
        return {"error": str(error)}


def _query_music_with_mode(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> Tuple[List[List[Any]], Optional[str]]:
    alias_data = json.load(open("songs/song_alias.json", "r", encoding="utf-8"))
    song_data = load_song_data()
    query = (name or "").strip()
    if not query:
        return [], None
    query_lower = query.lower()

    id_to_title: Dict[int, str] = {}
    for music in song_data:
        try:
            sid = int(music.get("id"))
        except Exception:
            continue
        title = music.get("song_name_jp") or music.get("song_name") or f"ID{sid}"
        id_to_title[sid] = title

    def _dedupe_by_id(rows: List[List[Any]]) -> List[List[Any]]:
        seen = set()
        out: List[List[Any]] = []
        for row in rows:
            if not row:
                continue
            sid = row[0]
            if sid in seen:
                continue
            seen.add(sid)
            out.append(row)
        return out

    # 1) 精准匹配全名（song_name_jp / song_name，不区分大小写）
    exact_name_hits: List[List[Any]] = []
    for music in song_data:
        jp = str(music.get("song_name_jp") or "")
        cn = str(music.get("song_name") or "")
        jp_lower = jp.lower()
        cn_lower = cn.lower()
        if query_lower == jp_lower or query_lower == cn_lower:
            exact_name_hits.append([music.get("id"), jp or cn])
    exact_name_hits = _dedupe_by_id(exact_name_hits)
    if exact_name_hits:
        return exact_name_hits, "exact_name"

    # 2) 精准匹配 id（兼容 id 前缀）
    id_token = query_lower
    if id_token.startswith("id"):
        id_token = id_token[2:]
    id_token = id_token.strip()
    if id_token.isdigit():
        target_id = int(id_token)
        if target_id in id_to_title:
            return [[target_id, id_to_title[target_id]]], "exact_id"

    # 3) 精准匹配别名（不区分大小写）
    exact_alias_hits: List[List[Any]] = []
    for entry in alias_data:
        aliases = entry.get("aliases") or []
        sid = entry.get("id")
        try:
            sid_int = int(sid)
        except Exception:
            sid_int = sid
        if not is_song_id_publicly_visible(sid_int):
            continue
        for alias in aliases:
            if isinstance(alias, str) and query_lower == alias.lower():
                title = (
                    entry.get("song_name_jp") or id_to_title.get(sid_int) or str(sid)
                )
                exact_alias_hits.append([sid_int, title])
                break
    exact_alias_hits = _dedupe_by_id(exact_alias_hits)
    if exact_alias_hits:
        return exact_alias_hits, "exact_alias"

    # 4) 全名部分匹配（输入是曲名连续子串，不区分大小写）
    if allow_partial:
        partial_name_hits: List[List[Any]] = []
        for music in song_data:
            jp = str(music.get("song_name_jp") or "")
            cn = str(music.get("song_name") or "")
            jp_lower = jp.lower()
            cn_lower = cn.lower()
            if (jp_lower and query_lower in jp_lower) or (
                cn_lower and query_lower in cn_lower
            ):
                partial_name_hits.append([music.get("id"), jp or cn])
        partial_name_hits = _dedupe_by_id(partial_name_hits)
        if partial_name_hits:
            return partial_name_hits, "partial_name"

    if not allow_fuzzy:
        return [], None

    # 5) 模糊匹配（返回单条，并附带匹配度）
    best_match: Optional[Dict[str, Any]] = None

    for music in song_data:
        sid = music.get("id")
        title = music.get("song_name_jp") or music.get("song_name") or str(sid)
        candidates = [
            str(music.get("song_name_jp") or "").lower(),
            str(music.get("song_name") or "").lower(),
        ]
        scores = [fuzz.ratio(query_lower, cand) for cand in candidates if cand]
        if not scores:
            continue
        ratio = max(scores)
        if best_match is None or ratio > best_match["ratio"]:
            best_match = {"id": sid, "title": title, "ratio": ratio}

    for entry in alias_data:
        sid = entry.get("id")
        if str(sid).isdigit():
            sid_as_int = int(sid)
            title = entry.get("song_name_jp") or id_to_title.get(sid_as_int) or str(sid)
        else:
            title = entry.get("song_name_jp") or str(sid)
        aliases = entry.get("aliases") or []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            ratio = fuzz.ratio(query_lower, alias.lower())
            if best_match is None or ratio > best_match["ratio"]:
                best_match = {"id": sid, "title": title, "ratio": ratio}

    if best_match is None:
        return [], None
    return [[best_match["id"], best_match["title"], best_match["ratio"]]], "fuzzy"


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
    group_id = getattr(event, "group_id", None)
    scope = f"group:{group_id}" if group_id is not None else "private"
    return f"{scope}:user:{event.get_user_id()}"


def _draw_guess_group_session_key(event: MessageEvent) -> Optional[str]:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return None
    return str(group_id)


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
    return event.get_user_id()


async def _extract_uploader_group_name(bot: Bot, event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return "私聊"
    try:
        info = await bot.call_api(
            "get_group_info", group_id=int(group_id), no_cache=True
        )
        name = info.get("group_name") if isinstance(info, dict) else ""
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception as e:
        logger.debug("get_group_info_failed group_id=%s err=%s", group_id, e)
    return f"群{group_id}"


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
        _build_fuzzy_query_hint(results) if _is_fuzzy_query_result(results) else ""
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


def _resolve_guess_with_query_music(text: str) -> Tuple[Set[int], str]:
    guessed_ids, guessed_title, _ = _resolve_guess_with_query_music_detail(text)
    return guessed_ids, guessed_title


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

    resolved_title, resolved_ids, _ = _resolve_draw_song_selection(results)
    if resolved_ids:
        return set(resolved_ids), (resolved_title or display_title), None

    if _is_fuzzy_query_result(results):
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


qq_official_unsupported_gate = on_message(
    priority=0,
    rule=Rule(_is_qq_official_unsupported_command),
    block=True,
)


@qq_official_unsupported_gate.handle()
async def qq_official_unsupported_gate_handle(event: MessageEvent):
    await send_text_reply(
        qq_official_unsupported_gate,
        event,
        QQ_OFFICIAL_UNSUPPORTED_MESSAGE,
        quick_actions=True,
    )


qq_official_ping = on_regex(
    r"^/ping\s*$",
    priority=1,
    rule=Rule(_is_qq_official_event),
    block=True,
)


@qq_official_ping.handle()
async def qq_official_ping_handle(event: MessageEvent):
    await _finish_text_reply(qq_official_ping, event, "pong")


# 查配置
# [n分音符] 配置 [bpm] [难度]
# 若省略分音符，则默认按 16 分音符处理
# 也支持仅输入 bpm / bpm区间 查歌名


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


# 支持：
# taikorec
# taikorec 体力
# taikorec 体力 30
# taikorec stamina 15


# ================
# 工具函数
# ================


def file_to_bytesio(path: Path) -> BytesIO:
    """
    将本地文件读入 BytesIO，并重置指针到起始位置
    """
    bio = BytesIO()
    with path.open("rb") as f:
        bio.write(f.read())
    bio.seek(0)
    return bio


# =========================
# 指令：tsearch on/off
# =========================


# =========================
# 指令：xx有什么别名
# =========================


# =========================
# 指令：tset xxx to xxx
# =========================


# =========================
# 指令：歌曲分类位序
# =========================


# =========================
# 指令：xx哪有鼓
# =========================


# =========================
# 指令 1：xx是什么歌
# =========================
# 例：千本桜是什么歌
# 这里用正则捕获 xx


# =========================
# 指令 2：里/鬼/表/松/竹/梅 idxxxx
# =========================
# 允许：里id1234 / 里 id1234 / 里 1234 / 里  id1234
# 也允许：鬼id0001、表 999、松 id12


# =========================
# 你画我猜：功能开关
# =========================
draw_guess_switch = on_regex(
    r"^(开启|关闭)太鼓你画我猜功能$",
    priority=10,
    rule=taiko_rule,
    permission=SUPERUSER | GROUP_ADMIN | GROUP_OWNER,
    block=True,
)


@draw_guess_switch.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        await matcher.finish("该指令仅支持群聊使用。")

    enabled = (groups[0] if groups else "") == "开启"
    group_key = get_group_key(event=event)
    if group_key is None:
        await matcher.finish("该指令仅支持群聊使用。")
    changed = apply_switch(group_key, "taiko_draw_guess", enabled)
    if not enabled:
        DRAW_GUESS_GROUP_SESSIONS.pop(str(group_id), None)
        prefix = f"group:{group_id}:user:"
        for key in list(DRAW_GUESS_MAKE_SESSIONS.keys()):
            if key.startswith(prefix):
                DRAW_GUESS_MAKE_SESSIONS.pop(key, None)

    state_text = "开启" if enabled else "关闭"
    if changed:
        await matcher.finish(f"太鼓你画我猜功能已{state_text}（本群）")
    await matcher.finish(f"太鼓你画我猜功能已是{state_text}状态（本群）")


# =========================
# 你画我猜：制作流程
# =========================
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
            await matcher.finish(
                MessageSegment.image(file_to_bytesio(DRAW_GUESS_TEMPLATE_PATH))
                + Message("\n请上传图片"),
                reply_message=True,
            )
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

        group_id = getattr(event, "group_id", None)
        uploader = {
            "qq": event.get_user_id(),
            "nickname": _extract_uploader_nickname(event),
            "group_id": str(group_id) if group_id is not None else "",
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


# =========================
# 你画我猜：猜歌流程
# =========================
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
    await matcher.finish(
        MessageSegment.image(file_to_bytesio(image_path))
        + Message(
            f"\n已发送图片，请输入“猜+歌名”，例如猜测图片中歌曲为百花缭乱，则输入“猜百花缭乱”，目前有{DRAW_GUESS_MAX_TRIES}次机会"
        ),
        reply_message=True,
    )


@draw_guess_answer.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent, groups=RegexGroup()):
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


# =========================
# 你画我猜：评价与查看
# =========================
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
async def _(matcher: Matcher, groups=RegexGroup()):
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
    await matcher.finish(
        MessageSegment.image(file_to_bytesio(image_path)) + Message(f"\n{detail}"),
        reply_message=True,
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
    await matcher.finish(MessageSegment.image(img_buf), reply_message=True)


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

    group_id = getattr(event, "group_id", None)
    if not all_groups and group_id is None:
        await matcher.finish(
            "默认展示本群排行，私聊请使用：你画我猜排行 -a",
            reply_message=True,
        )

    group_key = None if all_groups else str(group_id)
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
            lines.append(f"{idx}. {nickname}(QQ:{user_id}) | 猜对{correct_count}次")
        else:
            lines.append(f"{idx}. {nickname}(QQ:{user_id}) | 本群猜对{correct_count}次")
    await matcher.finish("\n".join(lines), reply_message=True)


@draw_guess_manual_exit.handle()
async def _(matcher: Matcher, event: MessageEvent):
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


anti_sb = on_regex(r"^@菌菌.*", priority=10, rule=taiko_rule, block=True)


@anti_sb.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = event.get_message()

    # =========================
    # ① 若 at 了指定 QQ（3889003795），完全不响应
    # =========================
    # for seg in msg:
    #     if seg.type == "at" and seg.data.get("qq") == "3889003795":
    #         return

    msg_text = str(msg).strip()

    # =========================
    # ② 以 "@菌菌" 开头：提示不能复制粘贴
    # =========================
    if msg_text.startswith("@菌菌"):
        await anti_sb.finish("您似乎复制粘贴了'@菌菌'3个字符，这是个无法复制的指令哦~")


anti = on_regex(r".*", priority=1000, rule=taiko_rule, block=True)


@anti.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = event.get_message()

    # =========================
    # ① 若 at 了指定 QQ（3889003795），完全不响应
    # =========================
    for seg in msg:
        if seg.type == "json":
            print(seg.data["data"])
            return


async def _require_private_send_authority(matcher, event, bind_target):
    from taiko_runtime.send_authority import has_current_send_authority

    if not has_current_send_authority(event, bind_target, _resolve_read_bind_target_safe):
        await _finish_text_reply(matcher, event, "授权已失效，请重新查询。")
