from __future__ import annotations
from taiko_bot.runtime.paths import root as _runtime_root



from .. import entry

from nonebot.adapters import Event as MessageEvent

from ...public.provider import query_with_mode as _query_music_with_mode

from typing import Any

from nonebot.adapters import Bot

from io import BytesIO

from typing import Dict

from .game_login_qr import GameLoginQrError

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from .hiroba.client import HirobaError

from .hiroba.client import HirobaProfilePrivateError

from typing import List

from .manual_account import ManualAccountApiError

from nonebot.matcher import Matcher

from nonebot.exception import MatcherException

from typing import Optional

from pathlib import Path

from nonebot.adapters.onebot.v11 import PrivateMessageEvent

from .public_score_token import PublicScoreTokenError

from .messages import QQ_OFFICIAL_PLATFORM

from nonebot.params import RegexMatched

from nonebot.rule import Rule

from typing import Set

from typing import Tuple

from .messages import _is_qq_passive_reply_limit_error

from .messages import _send_qq_proactive

import asyncio

from .manual_account import call_manual_account_api

from datetime import datetime

from .messages import extract_plain_text as extract_platform_plain_text

from .game_login_qr import fetch_game_login_qr_image

from .messages import get_identity_key

from .taiko_db import get_taiko_db_connection

from .hiroba.credentials import has_hiroba_credentials

import httpx

from .messages import is_onebot_message_targeting_other_account

from .messages import is_qq_official_event

from .messages import is_qq_official_group_event

from .messages import is_qq_official_private_event

from .public_score_token import issue_public_score_token_for_taiko_id

import json

from .hiroba.credentials import load_hiroba_credential_owner

from .game_login_qr import load_wahlap_authorization

from nonebot import logger

from .hiroba.service import login_hiroba_service_client

from nonebot.plugin import on_fullmatch

from nonebot.plugin import on_message

from nonebot.plugin import on_regex

import os

from .messages import parse_identity_key

from .hiroba.cooldown import peek_hiroba_sync_cooldown

import re

from .messages import resolve_target_identity_key

from .messages import send_image_reply

from .messages import send_text_reply

import shlex

import threading

import time

from .taiko_update_cooldown import try_acquire_taiko_update_slot

taiko_rule = entry.feature_on("taiko")

BIND_QQ_ACTION_LOG_PATH = Path(str(_runtime_root() / 'logs/bind_qq_action_log.json'))

CONFIG_PATH = Path(str(_runtime_root() / 'config.json'))

WAHLAP_BIND_TUTORIAL_IMAGE_PATH = Path(
    str(_runtime_root() / 'docs/鼓众广场绑定教程.png')
)

TAIKO_FORUM_BASE_URL = "https://forum.sakura-bot.cn"

DEVELOPER_QQ_EXPORT_DIR = Path(str(_runtime_root() / 'output/developer_userdata_exports'))

BIND_VERIFY_TIMEOUT_SECONDS = 600

BIND_VERIFY_BYPASS_IDS = {"2258735"}

GAME_LOGIN_QR_ALLOWED_IDENTITIES = frozenset(
    {
        "qq_official:204E3C57BC20A36DF2079772ECA08A7A",
        "onebot_v11:1106865024",
    }
)

BIND_VERIFY_SESSIONS: Dict[str, Dict[str, Any]] = {}

BIND_DELETE_CONFIRM_TIMEOUT_SECONDS = 300

BIND_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

MANUAL_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

MANUAL_SCORE_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

UPDATE_COMMAND_PATTERN = re.compile(
    r"^(?:taikoupdate|更新广场)(?:(?:\s+|)(?P<show_all>all|全部|全量|-a|--all))?\s*$",
    flags=re.IGNORECASE,
)

UPDATE_COMMAND_SEARCH_PATTERNS = (
    re.compile(r"taikoupdate", flags=re.IGNORECASE),
    re.compile(r"更新广场"),
)

UPDATE_SHOW_ALL_PATTERN = re.compile(
    r"(?:^|[\s,，/])(?P<flag>all|全部|全量|-a|--all)(?:$|[\s,，/])",
    flags=re.IGNORECASE,
)

COPIED_SAKURA_PREFIX_PATTERN = re.compile(
    r"^(?:[@＠]sakura)(?:(?=$)|[\s\u3000:：,，/]+)",
    flags=re.IGNORECASE,
)

UPDATE_TYPO_TARGET = "taikoupdate"

UPDATE_TYPO_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

def _build_single_edit_variants(target: str) -> Set[str]:
    variants: Set[str] = set()
    for idx in range(len(target)):
        variants.add(target[:idx] + target[idx + 1 :])
    for idx, original in enumerate(target):
        prefix = target[:idx]
        suffix = target[idx + 1 :]
        for ch in UPDATE_TYPO_ALPHABET:
            if ch != original:
                variants.add(prefix + ch + suffix)
    for idx in range(len(target) + 1):
        prefix = target[:idx]
        suffix = target[idx:]
        for ch in UPDATE_TYPO_ALPHABET:
            variants.add(prefix + ch + suffix)
    variants.discard(target)
    return variants

UPDATE_TYPO_VARIANTS = _build_single_edit_variants(UPDATE_TYPO_TARGET)

def _normalize_update_command_text(text: str) -> str:
    normalized = str(text or "").lstrip().lower()
    return normalized[1:] if normalized.startswith("/") else normalized

BIND_QQ_INPUT_REGEX = r"(?i)^/?绑定\s*qq(?:\s*你的qq号)?\s*([1-9]\d{4,14})(?:\s+([a-f0-9]{32}))?$"

BIND_INPUT_REGEX = (
    r"(?i)^/?绑定(?:(?:\s+|\+)?你的鼓众广场id)?(?:\s+|\+)?([0-9]{0,12})$"
)

def _is_hiroba_taiko_no(taiko_id: str) -> bool:
    return bool(re.fullmatch(r"\d{12}", str(taiko_id or "").strip()))

def _is_wahlap_taiko_id(taiko_id: str) -> bool:
    return bool(re.fullmatch(r"\d{5,11}", str(taiko_id or "").strip()))

def _normalize_bind_input(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("+"):
        text = text[1:].strip()
    return text

def _extract_bind_input(text: str) -> str:
    match = re.match(BIND_INPUT_REGEX, str(text or "").strip())
    if not match:
        return ""
    return _normalize_bind_input(match.group(1) or "")

def _is_wahlap_bind_tutorial_request(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?i)/?绑定\s+你的鼓众广场id",
            str(text or "").strip(),
        )
    )

def _extract_bind_qq_input(text: str) -> str:
    match = re.match(BIND_QQ_INPUT_REGEX, str(text or "").strip())
    if not match:
        return ""
    return str(match.group(1) or "").strip()

def _strip_copied_sakura_prefix(text: str) -> str:
    normalized = str(text or "").lstrip()
    while normalized:
        match = COPIED_SAKURA_PREFIX_PATTERN.match(normalized)
        if not match:
            break
        normalized = normalized[match.end() :].lstrip()
    return normalized

def _parse_update_command(text: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_update_command_text(text)
    match = UPDATE_COMMAND_PATTERN.fullmatch(normalized)
    if match:
        return {"show_all": bool(match.group("show_all"))}

    for pattern in UPDATE_COMMAND_SEARCH_PATTERNS:
        keyword_match = pattern.search(normalized)
        if not keyword_match:
            continue
        suffix = normalized[keyword_match.end() :]
        return {"show_all": _contains_update_show_all_flag(suffix)}
    return None

def _should_trigger_update_command(text: str) -> bool:
    return _parse_update_command(text) is not None

def _is_update_typo_candidate_text(text: str) -> bool:
    normalized = _normalize_update_command_text(str(text or "").strip())
    return len(normalized) in (10, 11, 12)

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

ONEBOT_EXTERNAL_BOT_QQ = "3889003795"

def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)

def _match_plain_text_literal(event: MessageEvent, expected: str) -> bool:
    plain_text = extract_plain_text(event).strip()
    return bool(plain_text) and plain_text == expected

def _game_login_qr_command_rule(event: MessageEvent) -> bool:
    return _match_plain_text_literal(event, "码来")

def _can_request_game_login_qr(event: MessageEvent) -> bool:
    return get_identity_key(event=event) in GAME_LOGIN_QR_ALLOWED_IDENTITIES

def _contains_update_show_all_flag(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return UPDATE_SHOW_ALL_PATTERN.search(normalized) is not None

def _is_private_message_event(event: MessageEvent) -> bool:
    if isinstance(event, PrivateMessageEvent):
        return True
    return is_qq_official_private_event(event)

def _is_external_bot_mentioned(event: MessageEvent) -> bool:
    if is_qq_official_event(event):
        return False
    for seg in event.get_message():
        if seg.type == "at" and seg.data.get("qq") == ONEBOT_EXTERNAL_BOT_QQ:
            return True
    return False

def _is_update_command_targeting_other_account(event: MessageEvent) -> bool:
    # In mixed-bot groups, "@other bot /更新广场" is still visible to OneBot.
    return is_onebot_message_targeting_other_account(event)

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
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
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

async def _send_text_reply_without_finish(
    matcher: Matcher,
    _event: MessageEvent,
    text: str,
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    try:
        await matcher.send(text)
    except Exception as exc:
        if not _is_qq_passive_reply_limit_error(exc):
            raise
        if not await _send_qq_proactive(matcher, _event, text):
            raise

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
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    await send_image_reply(
        matcher,
        event,
        image_bytes,
        prefix_text=prefix_text,
        quick_actions=quick_actions,
        prefer_markdown_image=prefer_markdown_image,
        markdown_image_name=markdown_image_name,
    )

async def _upload_json_file_for_event(
    bot: Bot, event: MessageEvent, file_path: Path, display_name: str
) -> None:
    resolved = str(file_path.resolve())
    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "upload_group_file",
            group_id=int(event.group_id),
            file=resolved,
            name=display_name,
        )
        return
    if isinstance(event, PrivateMessageEvent):
        await bot.call_api(
            "upload_private_file",
            user_id=int(event.get_user_id()),
            file=resolved,
            name=display_name,
        )
        return
    raise RuntimeError("当前消息类型不支持发送 JSON 文件")

async def _fetch_developer_userdata_via_forum(
    token: str, user_id: str
) -> Dict[str, Any]:
    url = f"{TAIKO_FORUM_BASE_URL}/api/developer/userdata/{user_id}"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token.strip()}"},
        )
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        message = (
            payload.get("statusMessage")
            or payload.get("message")
            or f"请求失败，HTTP {response.status_code}"
        )
        raise RuntimeError(str(message))
    try:
        payload = response.json()
    except Exception as error:
        raise RuntimeError("开发者接口返回的 JSON 无法解析") from error
    if not isinstance(payload, dict):
        raise RuntimeError("开发者接口返回的内容不是对象 JSON")
    return payload

def append_bind_qq_action_log(entry: Dict[str, Any]) -> None:
    BIND_QQ_ACTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BIND_QQ_ACTION_LOG_PATH.exists():
        try:
            with BIND_QQ_ACTION_LOG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    else:
        data = []
    data.append(entry)
    with BIND_QQ_ACTION_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""

def _resolve_requested_identity_key(event: MessageEvent) -> Tuple[str, bool]:
    self_identity = _normalize_identity_key(get_identity_key(event=event))
    target_identity = _normalize_identity_key(resolve_target_identity_key(event=event))
    is_self_query = self_identity == target_identity
    return target_identity or self_identity, is_self_query

def _get_taiko_bind_info(identity_key: str) -> Optional[Dict[str, Any]]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        identity_key = _normalize_identity_key(identity_key)
        cursor.execute(
            """select id, coalesce(visible, 0), coalesce(source, 'wahlap')
                 from bind where qq=%s and cast(qq as binary)=cast(%s as binary)
                 order by is_current desc, slot_index asc, row_id asc limit 1""",
            (identity_key, identity_key),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0] or "").strip(),
            "visible": int(row[1] or 0),
            "source": str(row[2] or "wahlap").strip(),
        }
    except Exception:
        return None
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()

def _set_taiko_bind_visibility(identity_key: str, visible: int) -> int:
    from .bot_binding_mutation import mutate_bot_binding
    result = mutate_bot_binding(
        _normalize_identity_key(identity_key), "visibility", value=visible,
        connection_factory=_get_taiko_db_connection,
    )
    return result.matched

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

def _get_taiko_db_connection():
    return get_taiko_db_connection()

def _execute_taiko_update(
    taiko_id: str, *, identity_key: Optional[str] = None,
    show_all_changes: bool = False, include_changes_image: bool = True,
) -> Dict[str, Any]:
    if not identity_key:
        return {'ok':False,'message':'请使用自己的当前国服实账号更新。','image':None}
    from .native_wahlap_update import update_native_wahlap,NativeWahlapDenied
    try:
        return update_native_wahlap(identity_key,taiko_id,connection_factory=_get_taiko_db_connection,
            userdata_root=Path(os.getenv('TAIKO_USERDATA_DIR') or str(_runtime_root() / 'userdata')),
            include_image=include_changes_image,show_all=show_all_changes)
    except NativeWahlapDenied:
        return {'ok':False,'message':'绑定状态已变化，请查询当前绑定后再更新。','image':None}
    except Exception:
        return {'ok':False,'message':'更新暂不可用，请稍后重试。','image':None}

def _get_current_bind_entry(identity_key: str) -> Optional[Dict[str, Any]]:
    identity_key = _normalize_identity_key(identity_key)
    store = _load_multi_bind_store([identity_key])
    return _ensure_multi_bind_entry(store, identity_key)

def _get_bind_ids(entry: Optional[Dict[str, Any]]) -> List[str]:
    if not entry:
        return []
    return [
        str(raw or "").strip()
        for raw in (entry.get("ids") or [])
        if str(raw or "").strip()
    ]

def _has_virtual_bind_slot(entry: Optional[Dict[str, Any]]) -> bool:
    if not entry:
        return False
    # Every real binding, including manually managed accounts, contributes to u0.
    return len(_get_bind_ids(entry)) >= 2

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

def _get_current_real_bind_slot_number(entry: Optional[Dict[str, Any]]) -> int:
    if not entry:
        return None
    ids = _get_bind_ids(entry)
    if not ids:
        return 0
    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    return current_index + 1

def _get_current_real_bind_taiko_id(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not entry:
        return None
    ids = _get_bind_ids(entry)
    if not ids:
        return None
    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    return str(ids[current_index])

def _get_current_bind_taiko_id(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    ids = _get_bind_ids(entry)
    if not ids:
        return None
    selected_slot = _get_selected_bind_slot_number(entry)
    if selected_slot <= 0:
        return None
    selected_index = max(0, min(selected_slot - 1, len(ids) - 1))
    return str(ids[selected_index])

def _build_bind_switch_hint(entry: Optional[Dict[str, Any]]) -> str:
    ids = _get_bind_ids(entry)
    if len(ids) <= 1:
        return ""
    slots = [f"u{idx}" for idx in range(1, len(ids) + 1)]
    if _has_virtual_bind_slot(entry):
        slots.insert(0, "u0")
    return "\n如需切换其他账号，请先发送 " + " / ".join(slots) + "。"

def _build_u0_readonly_message(
    entry: Optional[Dict[str, Any]], *, action_text: str
) -> str:
    summary = _format_multi_bind_summary(entry)
    real_slot = _get_current_real_bind_slot_number(entry)
    real_id = _get_current_real_bind_taiko_id(entry) or "-"
    return (
        "当前正在使用 u0：合并账户（只读）。\n"
        f"{action_text} 仅支持真实绑定账号，请先切换到 u1~u{len(_get_bind_ids(entry))} 后再试。\n"
        f"当前展示资料来源：u{real_slot}：{real_id}\n"
        f"当前绑定：{summary}{_build_bind_switch_hint(entry)}"
    )

def _build_update_command_hint(
    identity_key: str,
    *,
    expected_source: str,
) -> str:
    entry = _get_current_bind_entry(identity_key)
    if entry is None:
        return _taiko_bind_usage_message()

    selected_slot = _get_selected_bind_slot_number(entry)
    if selected_slot == 0:
        return _build_u0_readonly_message(entry, action_text="更新命令")

    taiko_id = _get_current_bind_taiko_id(entry)
    if not taiko_id:
        return _taiko_bind_usage_message()

    actual_source = _infer_bind_source(taiko_id, entry.get("sources") or {})
    actual_label = _bind_source_label(actual_source)
    if actual_source == "manual":
        return (
            f"当前正在使用 u{selected_slot}：手动账号。\n"
            "手动账号不关联鼓众广场或 Hiroba，请使用“录入成绩”维护数据。\n"
            f"当前绑定：{_format_multi_bind_summary(entry)}{_build_bind_switch_hint(entry)}"
        )
    recommended_command = "更新hiroba" if actual_source == "hiroba" else "taikoupdate"
    expected_label = _bind_source_label(expected_source)
    return (
        f"当前正在使用 u{selected_slot}：{taiko_id}（{actual_label}）。\n"
        f"这不是 {expected_label} 服账号，请改用“{recommended_command}”。\n"
        f"当前绑定：{_format_multi_bind_summary(entry)}{_build_bind_switch_hint(entry)}"
    )

def _execute_hiroba_update(
    taiko_id: str,
    *,
    identity_key: Optional[str] = None,
    show_all_changes: bool = False,
    include_changes_image: bool = True,
    progress=None,
) -> Dict[str, Any]:
    from .hiroba.native_binding import sync_native_hiroba, NativeHirobaCredentialUnavailable
    if not identity_key:
        return {"ok": False, "message": "请使用自己的 Hiroba 实账号更新。", "image": None}
    cooldown_msg = peek_hiroba_sync_cooldown(taiko_id)
    if cooldown_msg:
        return {"ok": False, "message": cooldown_msg, "image": None}
    try:
        return sync_native_hiroba(identity_key, taiko_id,
            connection_factory=_get_taiko_db_connection,
            userdata_root=Path(os.getenv("TAIKO_USERDATA_DIR") or str(_runtime_root() / 'userdata')),
            include_image=include_changes_image, show_all=show_all_changes, progress=progress)
    except NativeHirobaCredentialUnavailable:
        return {"ok": False, "message": f"Hiroba 凭据无法读取，请发送“绑定hiroba 邮箱 密码 {taiko_id}”重新绑定后重试。", "image": None}
    except Exception:
        return {"ok": False, "message": "Hiroba 更新暂不可用，请稍后重试。", "image": None}

def _execute_hiroba_bind(identity_key: str, email: str, password: str, target: str, progress=None):
    from .hiroba.native_binding import bind_native_hiroba, sync_native_hiroba
    root = Path(os.getenv("TAIKO_USERDATA_DIR") or str(_runtime_root() / 'userdata'))
    result = bind_native_hiroba(identity_key, email, password, target=target,
        connection_factory=_get_taiko_db_connection)
    synced = 0
    for identity in result.taiko_ids:
        try:
            sync_native_hiroba(identity_key, identity, connection_factory=_get_taiko_db_connection,
                userdata_root=root, current_only=False, progress=progress)
            synced += 1
        except Exception:
            break
    return result, synced

def _create_hiroba_progress_reporter(
    matcher: Matcher,
    event: MessageEvent,
    *,
    min_interval: float = 8.0,
    send_timeout: float = 15.0,
):
    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    state = {
        "last_ts": 0.0,
        "last_msg": "",
        "pending_future": None,
        "midpoint_sent": False,
    }
    is_qq_group = is_qq_official_group_event(event)

    def _reply_debug_context() -> Dict[str, Any]:
        event_id = str(
            getattr(event, "id", None) or getattr(event, "event_id", None) or ""
        ).strip()
        return {
            "event_type": event.__class__.__name__,
            "event_id": event_id,
            "group_openid": str(getattr(event, "group_openid", "") or "").strip(),
            "user_id": (
                str(event.get_user_id() or "").strip()
                if hasattr(event, "get_user_id")
                else ""
            ),
            "reply_seq": getattr(event, "_reply_seq", None),
        }

    async def _send_progress_text(text: str) -> None:
        debug_ctx = _reply_debug_context()
        logger.info("hiroba progress reply start: text=%s context=%s", text, debug_ctx)
        started = time.monotonic()
        await asyncio.wait_for(
            _send_text_reply_without_finish(matcher, event, text),
            timeout=send_timeout,
        )
        logger.info(
            "hiroba progress reply sent: text=%s elapsed_ms=%s context=%s",
            text,
            int((time.monotonic() - started) * 1000),
            _reply_debug_context(),
        )

    def _handle_progress_future_done(future, text: str) -> None:
        try:
            future.result()
        except Exception as exc:
            logger.warning(
                "hiroba progress reply failed: text=%s context=%s error=%s",
                text,
                _reply_debug_context(),
                exc,
            )

    def _should_forward_progress_text(text: str) -> bool:
        if not is_qq_group:
            return True
        if text.startswith("已识别 "):
            return True
        if text == "同步完成":
            return False
        if text.startswith("正在拉取谱面详情 "):
            match = re.search(r"(\d+)\s*/\s*(\d+)", text)
            if not match:
                return False
            completed = int(match.group(1))
            total = max(1, int(match.group(2)))
            if state["midpoint_sent"]:
                return False
            if completed < max(1, total // 2):
                return False
            state["midpoint_sent"] = True
            return True
        return True

    def report(message: str, *, force: bool = False) -> None:
        text = str(message or "").strip()
        if not text:
            return
        now = time.monotonic()
        with lock:
            if not _should_forward_progress_text(text):
                return
            if not force and text == state["last_msg"]:
                return
            if not force and now - state["last_ts"] < min_interval:
                return
            pending_future = state.get("pending_future")
            if pending_future is not None and not pending_future.done():
                return
            state["last_ts"] = now
            state["last_msg"] = text
            future = asyncio.run_coroutine_threadsafe(
                _send_progress_text(text),
                loop,
            )
            state["pending_future"] = future
        future.add_done_callback(
            lambda done, _text=text: _handle_progress_future_done(done, _text)
        )

    return report

async def _finish_hiroba_update_success_reply(
    matcher: Matcher,
    event: MessageEvent,
    *,
    success_message: str,
    img_buf: bytes | BytesIO | Path | None,
    show_all_changes: bool = False,
    image_timeout: float = 20.0,
    text_timeout: float = 15.0,
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    final_message = str(success_message or "Hiroba 更新成功！")
    if show_all_changes:
        final_message += "\n已展示全部变更。"

    def _reply_debug_context() -> Dict[str, Any]:
        event_id = str(
            getattr(event, "id", None) or getattr(event, "event_id", None) or ""
        ).strip()
        return {
            "event_type": event.__class__.__name__,
            "event_id": event_id,
            "group_openid": str(getattr(event, "group_openid", "") or "").strip(),
            "user_id": (
                str(event.get_user_id() or "").strip()
                if hasattr(event, "get_user_id")
                else ""
            ),
            "reply_seq": getattr(event, "_reply_seq", None),
        }

    if img_buf is not None:
        try:
            started = time.monotonic()
            logger.info(
                "hiroba success image reply start: bytes=%s context=%s",
                len(img_buf) if isinstance(img_buf, (bytes, bytearray)) else -1,
                _reply_debug_context(),
            )
            await asyncio.wait_for(
                _finish_image_reply(
                    matcher,
                    event,
                    img_buf,
                    prefix_text=final_message,
                    quick_actions=True,
                    prefer_markdown_image=True,
                    markdown_image_name="hirobaupdate",
                ),
                timeout=image_timeout,
            )
            logger.info(
                "hiroba success image reply sent: elapsed_ms=%s context=%s",
                int((time.monotonic() - started) * 1000),
                _reply_debug_context(),
            )
            return
        except MatcherException:
            raise
        except Exception:
            logger.exception(
                "hiroba success image reply failed: context=%s",
                _reply_debug_context(),
            )

    try:
        started = time.monotonic()
        logger.info(
            "hiroba success text reply start: text=%s context=%s",
            final_message,
            _reply_debug_context(),
        )
        await asyncio.wait_for(
            _finish_text_reply(
                matcher,
                event,
                final_message,
                quick_actions=True,
            ),
            timeout=text_timeout,
        )
        logger.info(
            "hiroba success text reply sent: elapsed_ms=%s context=%s",
            int((time.monotonic() - started) * 1000),
            _reply_debug_context(),
        )
    except MatcherException:
        raise
    except Exception:
        logger.exception(
            "hiroba success text reply failed: context=%s",
            _reply_debug_context(),
        )
        try:
            started = time.monotonic()
            logger.info(
                "hiroba fallback text send start: text=%s context=%s",
                final_message,
                _reply_debug_context(),
            )
            await asyncio.wait_for(
                _send_text_reply_without_finish(matcher, event, final_message),
                timeout=text_timeout,
            )
            logger.info(
                "hiroba fallback text send sent: elapsed_ms=%s context=%s",
                int((time.monotonic() - started) * 1000),
                _reply_debug_context(),
            )
        except Exception:
            logger.exception(
                "hiroba fallback send failed: context=%s",
                _reply_debug_context(),
            )

def _load_wahlap_cookie() -> str:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return ""
    return str(config.get("cookie") or "").strip()

async def _fetch_bind_player_profile(
    user_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    auth = _load_wahlap_cookie()
    if not auth:
        return None, "未配置鼓众 cookie，暂时无法验证绑定。"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": auth,
    }
    payload = {"keyword": str(user_id).strip(), "page": 1, "pageSize": 10}
    url = "https://wl-taiko.wahlap.net/api/user/search/player"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception as e:
        return None, f"读取鼓众资料失败：{e}"

    if resp.status_code not in (200, 201):
        return None, f"读取鼓众资料失败，HTTP {resp.status_code}"

    try:
        data = resp.json()
    except Exception:
        return None, "读取鼓众资料失败：返回内容无法解析。"

    players = (
        ((data.get("data") or {}).get("players") or [])
        if isinstance(data, dict)
        else []
    )
    if not isinstance(players, list) or not players:
        return None, "未找到该鼓众ID，请确认输入是否正确。"

    user_id_text = str(user_id).strip()
    for player in players:
        if (
            isinstance(player, dict)
            and str(player.get("userid") or "").strip() == user_id_text
        ):
            return player, None

    if len(players) == 1 and isinstance(players[0], dict):
        return players[0], None
    return None, "未找到该鼓众ID，请确认输入是否正确。"

def _extract_bind_title_info(profile: Dict[str, Any]) -> Tuple[str, int]:
    costume = profile.get("gameCostume") or {}
    if not isinstance(costume, dict):
        costume = {}
    title = str(costume.get("title") or "").strip()
    try:
        titleplate_id = int(costume.get("titleplate_id"))
    except Exception:
        titleplate_id = -1
    return title, titleplate_id

def _build_bind_profile_from_hiroba_public_profile(profile) -> Dict[str, Any]:
    return {
        "userid": str(profile.taiko_no or "").strip(),
        "mydon_name": str(profile.nickname or profile.taiko_no).strip(),
        "province": str(profile.region or "").strip(),
        "gameCostume": {
            "title": str(profile.title or "").strip(),
            "titleplate_id": 0,
        },
    }

def _fetch_hiroba_public_profile_via_service_account(taiko_id: str):
    client = login_hiroba_service_client(timeout=30)
    html = client.fetch_public_profile(taiko_id)
    from .hiroba.parser import parse_profile

    return parse_profile(html)

def _get_bind_verify_session(qq: str) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq))
    session = BIND_VERIFY_SESSIONS.get(qq)
    if session is None:
        return None
    if int(session.get("expires_at", 0) or 0) <= _now_ts():
        BIND_VERIFY_SESSIONS.pop(qq, None)
        return None
    return session

def _bind_title_changed(session: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    current_title, current_titleplate_id = _extract_bind_title_info(profile)
    return current_title != str(
        session.get("title") or ""
    ).strip() or current_titleplate_id != int(session.get("titleplate_id", -1) or -1)

def _build_bind_verify_prompt(
    player_name: str,
    taiko_id: str,
    current_title: str,
    province: str = "",
) -> str:
    title_text = current_title or "空称号"
    province_text = f"\n地区：{province}" if province else ""
    return (
        f"已发起绑定验证。\n玩家：{player_name}\n当前称号：{title_text}{province_text}\n"
        f"请先在鼓众广场更换称号，再发送“确认绑定”完成验证。\n"
        f"更换后也可再次发送“绑定 {taiko_id}”完成验证。\n"
        f"本次验证 {BIND_VERIFY_TIMEOUT_SECONDS // 60} 分钟内有效。"
    )

def _build_bind_title_unchanged_message(
    session: Dict[str, Any], current_title: str, taiko_id: str
) -> str:
    original_title = str(session.get("title") or "").strip() or "空称号"
    return (
        "验证未通过，检测到称号尚未变化。\n"
        f"当前称号：{current_title or '空称号'}\n"
        f"初始称号：{original_title}\n"
        f"请先更换称号后再发送“确认绑定”或重新发送“绑定 {taiko_id}”。"
    )

def _finalize_hiroba_direct_bind(identity_key: str, taiko_id: str) -> str:
    reply_msg, _ = _upsert_bind_record(identity_key, taiko_id, source="hiroba")
    return (
        f"{reply_msg}\n"
        "已按日服/Hiroba 太鼓番绑定。\n"
        "后续将默认通过 Hiroba 服务账号读取公开成绩；"
        f"若账号设为非公开，可发送“绑定hiroba 邮箱 密码 {taiko_id}”保存登录凭据后再同步。"
    )

def _should_skip_bind_verification(taiko_id: str) -> bool:
    return str(taiko_id).strip() in BIND_VERIFY_BYPASS_IDS

def _build_bind_auto_update_result(
    identity_key: str, taiko_id: str, is_first_binding: bool
) -> Optional[Dict[str, Any]]:
    if not is_first_binding:
        return None
    update_result = _execute_taiko_update(taiko_id, identity_key=identity_key, include_changes_image=True)
    if update_result.get("ok"):
        return {
            "ok": True,
            "message": "首次绑定已自动执行一次 taikoupdate。",
            "image": update_result.get("image"),
        }
    logger.warning(
        "首次绑定自动 taikoupdate 失败，qq=%s taiko_id=%s msg=%s",
        identity_key,
        taiko_id,
        update_result.get("message"),
    )
    return {
        "ok": False,
        "message": "首次绑定后已自动尝试执行一次 taikoupdate，但本次更新未完成，可稍后手动执行。",
        "image": None,
    }

async def _finish_bind_success_reply(
    matcher: Matcher,
    event: MessageEvent,
    base_message: str,
    auto_update_result: Optional[Dict[str, Any]] = None,
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    final_message = str(base_message or "").strip()
    if auto_update_result:
        tail_message = str(auto_update_result.get("message") or "").strip()
        if tail_message:
            final_message = f"{final_message}\n{tail_message}" if final_message else tail_message

    image = auto_update_result.get("image") if auto_update_result else None
    if auto_update_result and auto_update_result.get("ok") and image is not None:
        try:
            await _finish_image_reply(
                matcher,
                event,
                image,
                prefix_text=final_message,
                quick_actions=True,
                prefer_markdown_image=_is_qq_official_event(event),
                markdown_image_name="taikoupdate",
            )
            return
        except MatcherException:
            raise
        except Exception:
            logger.exception("send bind auto update image failed")

    await _finish_text_reply(matcher, event, final_message, quick_actions=True)

def _finalize_bind_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> Tuple[str, Optional[Dict[str, Any]]]:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_result = _build_bind_auto_update_result(
        identity_key, taiko_id, is_first_binding
    )
    return (
        f"{reply_msg}\n已通过称号变更验证。\n当前称号：{current_title or '空称号'}"
        ,
        auto_update_result,
    )

def _finalize_bind_without_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> Tuple[str, Optional[Dict[str, Any]]]:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_result = _build_bind_auto_update_result(
        identity_key, taiko_id, is_first_binding
    )
    return (
        f"{reply_msg}\n已按临时白名单跳过绑定验证。\n当前称号：{current_title or '空称号'}"
        ,
        auto_update_result,
    )

def _record_bind_qq_action(
    *,
    legacy_qq: str,
    target_identity_key: str,
    status: str,
    message: str,
    source_identity_key: str = "",
    source_db_id: str = "",
    source_ids: Optional[List[str]] = None,
    source_current_id: str = "",
) -> None:
    try:
        platform, raw_user_id = parse_identity_key(target_identity_key)
        append_bind_qq_action_log(
            {
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "action": "bind_qq_migration",
                "status": str(status or "").strip() or "unknown",
                "message": str(message or "").strip(),
                "legacy_qq_input": str(legacy_qq or "").strip(),
                "user_openid": raw_user_id if platform == QQ_OFFICIAL_PLATFORM else "",
                "target_identity_key": str(target_identity_key or "").strip(),
                "source_identity_key": str(source_identity_key or "").strip(),
                "legacy_db_taiko_id": str(source_db_id or "").strip(),
                "legacy_current_taiko_id": str(source_current_id or "").strip(),
                "legacy_taiko_ids": _normalize_multi_bind_ids(source_ids or []),
            }
        )
    except Exception as e:
        logger.warning("bind_qq_action_log_failed error=%s", e)

def _migrate_bind_from_legacy_qq_detail(
    legacy_qq: str, target_identity_key: str, *, code: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    from .bot_qq_migration import migrate_qq_bindings, QqMigrationDenied
    try:
        result = migrate_qq_bindings(legacy_qq, target_identity_key, code=code,
            connection_factory=_get_taiko_db_connection)
    except QqMigrationDenied as error:
        message = str(error)
        _record_bind_qq_action(legacy_qq=legacy_qq,target_identity_key=target_identity_key,
            source_identity_key="onebot_v11:"+legacy_qq,status="denied",message=message)
        return False, message, None
    BIND_VERIFY_SESSIONS.pop(target_identity_key, None)
    auto_update_result = None
    if result.entry is None:
        reply = "迁移已完成，目前没有绑定账号。"
    else:
        try: summary = _format_bind_entry_summary_safe(result.entry)
        except Exception: summary = "请查询当前绑定。"
        action = "完成迁移" if result.first_binding else "完成合并"
        reply = f"已根据 QQ {legacy_qq} 的历史绑定{action}。\n当前绑定：{summary}"
        if result.first_binding and not result.replayed:
            try:
                if result.entry['sources'][result.source_current_id] == 'hiroba':
                    auto_update_result = _execute_hiroba_update(result.source_current_id,identity_key=target_identity_key)
                else:
                    auto_update_result = _build_bind_auto_update_result(target_identity_key,result.source_current_id,True)
            except Exception:
                auto_update_result = {'ok':False,'message':'账号已绑定，本次自动更新未完成，请稍后手动更新。','image':None}
    _record_bind_qq_action(legacy_qq=legacy_qq,target_identity_key=target_identity_key,
        source_identity_key="onebot_v11:"+legacy_qq,source_db_id=result.source_ids[0],
        source_ids=list(result.source_ids),source_current_id=result.source_current_id,
        status="replayed" if result.replayed else "success",message=reply)
    return True, reply, auto_update_result

def _normalize_multi_bind_ids(ids: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    if not isinstance(ids, list):
        return out
    for raw in ids:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out

def _load_multi_bind_store(identity_keys) -> Dict[str, Dict[str, Any]]:
    from .bot_binding_metadata import read_bot_binding_metadata
    return read_bot_binding_metadata(identity_keys, connection_factory=_get_taiko_db_connection)

def _ensure_multi_bind_entry(
    store: Dict[str, Dict[str, Any]], qq: str, fallback_id: str = ""
) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq).strip())
    fallback = str(fallback_id or "").strip()
    payload = store.get(qq)
    ids = _normalize_multi_bind_ids(
        payload.get("ids") if isinstance(payload, dict) else None
    )
    if not ids and fallback:
        ids = [fallback]
    if not ids:
        return None

    try:
        current_index = int((payload or {}).get("current_index", 0) or 0)
    except Exception:
        current_index = 0
    try:
        current_slot = int((payload or {}).get("current_slot", current_index + 1) or 0)
    except Exception:
        current_slot = current_index + 1
    if fallback and fallback in ids:
        current_index = ids.index(fallback)
        if current_slot != 0:
            current_slot = current_index + 1
    current_index = max(0, min(current_index, len(ids) - 1))
    if len(ids) < 2:
        current_slot = 1
    else:
        current_slot = max(0, min(current_slot, len(ids)))
    sources = (payload or {}).get("sources") if isinstance(payload, dict) else {}
    if not isinstance(sources, dict):
        sources = {}
    entry = {
        "ids": ids,
        "current_index": current_index,
        "current_slot": current_slot,
        "sources": {
            str(taiko_id): str(source)
            for taiko_id, source in sources.items()
            if str(taiko_id) in ids and str(source).strip()
        },
    }
    store[qq] = entry
    return entry

def _infer_bind_source(taiko_id: str, sources: Optional[Dict[str, str]] = None) -> str:
    taiko_id = str(taiko_id or "").strip()
    sources = sources or {}
    explicit = str(sources.get(taiko_id) or "").strip().lower()
    if explicit in {"hiroba", "wahlap", "manual"}:
        return explicit
    if _is_hiroba_taiko_no(taiko_id):
        return "hiroba"
    if has_hiroba_credentials(taiko_id):
        return "hiroba"
    return "wahlap"

def _bind_source_label(source: str) -> str:
    if source == "manual":
        return "手动"
    return "JP" if source == "hiroba" else "CN"

def _format_multi_bind_summary(entry: Optional[Dict[str, Any]]) -> str:
    if not entry:
        return "暂无已绑定的鼓众广场ID。"
    ids = _get_bind_ids(entry)
    current_slot = _get_selected_bind_slot_number(entry)
    parts = []
    if _has_virtual_bind_slot(entry):
        marker = "（当前）" if current_slot == 0 else ""
        parts.append(f"u0:合并账户(只读){marker}")
    for idx, taiko_id in enumerate(ids, start=1):
        marker = "（当前）" if idx == current_slot else ""
        source = _infer_bind_source(str(taiko_id), entry.get("sources") or {})
        if source == "manual":
            nickname = "手动账号"
            db = _get_taiko_db_connection()
            cursor = db.cursor()
            try:
                cursor.execute(
                    "select nickname from taiko_manual_accounts where taiko_id=%s",
                    (taiko_id,),
                )
                row = cursor.fetchone()
                if row:
                    nickname = str(row[0] or nickname)
            finally:
                cursor.close()
                db.close()
            parts.append(f"u{idx}:{nickname}(手动){marker}")
        else:
            parts.append(f"u{idx}:{taiko_id}({_bind_source_label(source)}){marker}")
    return " / ".join(parts)

def _format_bind_entry_summary_safe(entry: Optional[Dict[str, Any]]) -> str:
    try:
        return _format_multi_bind_summary(entry)
    except Exception:
        logger.warning("binding action completed but summary formatting is unavailable")
        return "绑定摘要暂时不可用，请稍后发送“u1”或账号查询命令确认。"

def _format_current_bind_summary_safe(identity_key: str) -> str:
    try:
        return _format_bind_entry_summary_safe(_get_current_bind_entry(identity_key))
    except Exception:
        logger.warning("manual account action completed but binding lookup is unavailable")
        return "绑定摘要暂时不可用，请稍后发送“u1”或账号查询命令确认。"

def _get_bind_delete_confirm_session(qq: str) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq))
    session = BIND_DELETE_CONFIRM_SESSIONS.get(qq)
    if not session:
        return None
    if float(session.get("expires_at", 0) or 0) < _now_ts():
        BIND_DELETE_CONFIRM_SESSIONS.pop(qq, None)
        return None
    return session

def _upsert_bind_record(
    qq: str, taiko_id: str, *, source: Optional[str] = None
) -> Tuple[str, bool]:
    from .bot_binding_mutation import mutate_bot_binding
    identity = str(taiko_id).strip()
    result = mutate_bot_binding(
        _normalize_identity_key(qq), "upsert", value=identity,
        source=source or _infer_bind_source(identity),
        connection_factory=_get_taiko_db_connection,
    )
    slot = result.entry["current_index"] + 1
    if result.added:
        reply = "绑定成功！已设为 u1。" if result.first_binding else f"新增绑定成功！已设为 u{slot}。"
    else:
        reply = f"该ID已绑定，已切换到 u{slot}。"
    return f"{reply}\n当前绑定：{_format_bind_entry_summary_safe(result.entry)}", result.first_binding

def _switch_bind_record(
    qq: str, slot_number: int, event: Optional[MessageEvent] = None
) -> Tuple[bool, str]:
    from .bot_binding_mutation import mutate_bot_binding, BotBindingMutationRejected
    try:
        result = mutate_bot_binding(
            _normalize_identity_key(qq), "switch", value=slot_number,
            connection_factory=_get_taiko_db_connection,
        )
    except BotBindingMutationRejected as error:
        return False, _taiko_bind_usage_message(event) if error.reason == "empty" else str(error)
    summary = _format_bind_entry_summary_safe(result.entry)
    if slot_number == 0:
        return True, f"已切换到 u0：合并账户（只读）\n当前绑定：{summary}"
    source = result.entry["sources"][result.target_id]
    target_label = (
        next((part.split(":", 1)[1].split("(", 1)[0] for part in summary.split(" / ")
              if part.startswith(f"u{slot_number}:")), "手动账号")
        if source == "manual" else result.target_id
    )
    return True, f"已切换到 u{slot_number}：{target_label}\n当前绑定：{summary}"

def _remove_bind_record(
    qq: str,
    target: str = "",
    force_last: bool = False,
    event: Optional[MessageEvent] = None,
) -> Tuple[bool, str, bool]:
    from .bot_binding_mutation import mutate_bot_binding, BotBindingMutationRejected
    principal = _normalize_identity_key(qq)
    try:
        result = mutate_bot_binding(
            principal, "remove", value=target, force_last=force_last,
            connection_factory=_get_taiko_db_connection,
        )
    except BotBindingMutationRejected as error:
        if error.reason == "empty":
            return False, _taiko_bind_usage_message(event), False
        if error.reason == "confirm":
            BIND_DELETE_CONFIRM_SESSIONS[principal] = {
                "taiko_id": str(error),
                "expires_at": _now_ts() + BIND_DELETE_CONFIRM_TIMEOUT_SECONDS,
            }
            return (False, f"当前只剩最后 1 个鼓众广场ID：{error}\n"
                    f"如需确认删除，请在 {BIND_DELETE_CONFIRM_TIMEOUT_SECONDS // 60} 分钟内发送“确认删除绑定”。", True)
        return False, str(error), False
    BIND_DELETE_CONFIRM_SESSIONS.pop(principal, None)
    if result.entry:
        reply = f"已删除绑定：{result.target_id}\n当前绑定：{_format_bind_entry_summary_safe(result.entry)}"
    else:
        reply = f"已删除最后一个绑定：{result.target_id}\n当前已无绑定的鼓众广场ID。"
    return True, reply, False

def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())

def _resolve_manual_slot_taiko_id(
    identity_key: str, slot_token: str = ""
) -> Tuple[str, int]:
    entry = _get_current_bind_entry(identity_key)
    if not entry:
        raise ValueError("当前还没有账号，请先发送“新增空白账号 昵称”。")
    ids = _get_bind_ids(entry)
    token = str(slot_token or "").strip().lower()
    if token:
        match = re.fullmatch(r"u([1-9]\d*)", token)
        if not match:
            raise ValueError("账号槽位无效，请使用 u1 / u2 这类形式。")
        slot = int(match.group(1))
    else:
        slot = _get_selected_bind_slot_number(entry)
    if slot <= 0 or slot > len(ids):
        raise ValueError("请先切换到一个真实的手动账号槽位。")
    taiko_id = ids[slot - 1]
    if _infer_bind_source(taiko_id, entry.get("sources") or {}) != "manual":
        raise ValueError(f"u{slot} 不是手动账号，请先切换或指定手动账号槽位。")
    return taiko_id, slot

def _manual_diff_level(token: str) -> int:
    mapping = {
        "1": 1,
        "简单": 1,
        "梅": 1,
        "2": 2,
        "一般": 2,
        "竹": 2,
        "3": 3,
        "困难": 3,
        "松": 3,
        "4": 4,
        "魔王": 4,
        "鬼": 4,
        "表": 4,
        "5": 5,
        "里谱": 5,
        "里": 5,
    }
    level = mapping.get(str(token or "").strip())
    if not level:
        raise ValueError("难度无效，请使用 1~5 或 简单/一般/困难/魔王/里谱。")
    return level

def _resolve_manual_song(
    song_token: str, custom_title: str = "", *, require_unknown_title: bool = True
) -> Tuple[int, str]:
    token = str(song_token or "").strip()
    if token.isdigit():
        song_no = int(token)
        rows, _ = _query_music_with_mode(token)
        title = str(rows[0][1]) if len(rows) == 1 else str(custom_title or "").strip()
        if not rows and not title and require_unknown_title:
            raise ValueError('未收录数字 ID 必须追加 曲名="曲名"。')
        return song_no, title
    rows, _ = _query_music_with_mode(token)
    if not rows:
        raise ValueError("未找到歌曲；未收录曲目请使用数字 ID 并追加曲名。")
    if len(rows) > 1:
        candidates = " / ".join(f"ID {row[0]} {row[1]}" for row in rows[:8])
        raise ValueError(f"曲名有歧义，请改用歌曲 ID：{candidates}")
    return int(rows[0][0]), str(rows[0][1])

def _manual_command_tokens(text: str, command: str) -> List[str]:
    body = str(text or "").strip()[len(command) :].strip()
    try:
        return shlex.split(body)
    except ValueError as exc:
        raise ValueError(f"参数引号不完整：{exc}") from exc

def _parse_manual_score_lookup(text: str, command: str) -> Tuple[str, int, str, int]:
    tokens = _manual_command_tokens(text, command)
    if len(tokens) != 2:
        raise ValueError(f"格式：{command} <歌曲ID或曲名> <难度>")
    song_no, title = _resolve_manual_song(tokens[0], require_unknown_title=False)
    return str(song_no), _manual_diff_level(tokens[1]), title, song_no

async def _update_typo_rule(event: MessageEvent) -> bool:
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return False
    return _is_update_typo_candidate_text(extract_plain_text(event))

async def _update_command_rule(event: MessageEvent) -> bool:
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return False
    return _should_trigger_update_command(extract_plain_text(event))

from ..lifecycle_authority import binding_mutation
_finalize_bind_verification = binding_mutation(_finalize_bind_verification)
_finalize_bind_without_verification = binding_mutation(_finalize_bind_without_verification)
_finalize_hiroba_direct_bind = binding_mutation(_finalize_hiroba_direct_bind)
_switch_bind_record = binding_mutation(_switch_bind_record)
_remove_bind_record = binding_mutation(_remove_bind_record)
_migrate_bind_from_legacy_qq_detail = binding_mutation(_migrate_bind_from_legacy_qq_detail)
_set_taiko_bind_visibility = binding_mutation(_set_taiko_bind_visibility)
_execute_hiroba_bind = binding_mutation(_execute_hiroba_bind)
