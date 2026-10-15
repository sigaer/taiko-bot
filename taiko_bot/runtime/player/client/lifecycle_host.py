from __future__ import annotations

from .. import entry

from nonebot.adapters import Event as MessageEvent

from ...public.provider import query_with_mode as _query_music_with_mode

from typing import Any

from nonebot.adapters import Bot

from io import BytesIO

from typing import Dict

from nonebot.exception import FinishedException

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from .hiroba.client import HirobaClient

from .hiroba.client import HirobaError

from .hiroba.client import HirobaProfilePrivateError

from typing import List

from taiko_bot.manual_account import ManualAccountApiError

from nonebot.matcher import Matcher

from typing import Optional

from pathlib import Path

from nonebot.adapters.onebot.v11 import PrivateMessageEvent

from .public_score_token import PublicScoreTokenError

from nonebot.params import RegexMatched

from nonebot.rule import Rule

from typing import Set

from typing import Tuple

from taiko_bot.viewer_client import ViewerClientError

import asyncio

from taiko_bot.viewer_client import bind_hiroba_credentials

from taiko_bot.manual_account import call_manual_account_api

from datetime import datetime

from taiko_bot.viewer_client import decode_image_bytes

from .hiroba.credentials import ensure_hiroba_credentials_table

from .messages import extract_plain_text as extract_platform_plain_text

from taiko_bot.viewer_client import fetch_center_bind_info

from taiko_bot.viewer_client import fetch_wahlap_player_profile

from .messages import get_identity_key

from taiko_bot.settings import get_settings

from taiko_bot.viewer_client import has_center_hiroba_credentials

import httpx

from .messages import is_onebot_message_targeting_other_account

from .messages import is_qq_official_event

from .messages import is_qq_official_group_event

from .messages import is_qq_official_private_event

from .public_score_token import issue_public_score_token_for_taiko_id

import json

from .hiroba.credentials import load_hiroba_credential_owner

from .hiroba.credentials import load_hiroba_credentials

from nonebot import logger

from nonebot.plugin import on_fullmatch

from nonebot.plugin import on_message

from nonebot.plugin import on_regex

from .messages import parse_identity_key

from .hiroba.parser import parse_profile

from taiko_bot.viewer_client import proxy_center_bind_switch_current

from taiko_bot.viewer_client import proxy_center_bind_upsert

from taiko_bot.viewer_client import proxy_center_hiroba_sync

from taiko_bot.viewer_client import proxy_center_userdata_update

import re

from .messages import resolve_target_identity_key

from .messages import send_image_reply

from .messages import send_text_reply

import shlex

import threading

import time

from taiko_bot.userdata_provider import update_userdata_cache_from_payload

taiko_rule = entry.feature_on("taiko")

_SETTINGS = get_settings()

ROOT_DIR = _SETTINGS.root_dir

TAIKO_FORUM_BASE_URL = _SETTINGS.viewer_base_url

DEVELOPER_QQ_EXPORT_DIR = ROOT_DIR / "output" / "developer_userdata_exports"

HIROBA_SERVICE_TAIKO_NO = "862074224984"

BIND_VERIFY_TIMEOUT_SECONDS = 600

BIND_VERIFY_BYPASS_IDS = {"2258735"}

BIND_VERIFY_SESSIONS: Dict[str, Dict[str, Any]] = {}

BIND_DELETE_CONFIRM_TIMEOUT_SECONDS = 300

BIND_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

MANUAL_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

MANUAL_SCORE_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}

UPDATE_COMMAND_PATTERN = re.compile(
    r"^(?:taikoupdate|更新广场)(?:(?:\s+|)(?P<show_all>all|全部|全量|-a|--all))?\s*$",
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

def _is_hiroba_taiko_no(taiko_id: str) -> bool:
    return bool(re.fullmatch(r"\d{12}", str(taiko_id or "").strip()))

def _is_wahlap_taiko_id(taiko_id: str) -> bool:
    return bool(re.fullmatch(r"\d{5,11}", str(taiko_id or "").strip()))

def _normalize_bind_input(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("+"):
        text = text[1:].strip()
    return text

def _parse_update_command(text: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_update_command_text(text)
    match = UPDATE_COMMAND_PATTERN.fullmatch(normalized)
    if not match:
        return None
    return {"show_all": bool(match.group("show_all"))}

def _should_trigger_update_command(text: str) -> bool:
    return _parse_update_command(text) is not None

def _is_update_typo_candidate_text(text: str) -> bool:
    normalized = _normalize_update_command_text(str(text or "").strip())
    return len(normalized) in (10, 11, 12)

def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段
    """
    return extract_platform_plain_text(event)

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
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
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

async def _send_text_reply_without_finish(
    matcher: Matcher,
    _event: MessageEvent,
    text: str,
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    await matcher.send(text)

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
    raise FinishedException

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

def _apply_center_sync_result(payload: Dict[str, Any], *, fallback_source: str, expected_identity: str) -> bytes | None:
    from ..lifecycle_authority import verify_active_binding
    from ..authority import TinfoDenied
    verify_active_binding()
    if str(payload.get('taikoId') or '').strip() != str(expected_identity):
        raise TinfoDenied()
    userdata = payload.get("userdata")
    if isinstance(userdata, dict):
        update_userdata_cache_from_payload(
            str(payload.get("taikoId") or "").strip(),
            userdata,
            source=str(payload.get("source") or fallback_source),
        )
    return decode_image_bytes(payload)

def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""

def _resolve_requested_identity_key(event: MessageEvent) -> Tuple[str, bool]:
    self_identity = _normalize_identity_key(get_identity_key(event=event))
    target_identity = _normalize_identity_key(resolve_target_identity_key(event=event))
    is_self_query = self_identity == target_identity
    return target_identity or self_identity, is_self_query

def _resolve_bound_taiko_id(event: MessageEvent):
    identity_key, is_self_query = _resolve_requested_identity_key(event)
    info = _get_taiko_bind_info_from_center(identity_key)
    if info is None:
        return 404
    taiko_id = info["id"]
    visible = info["visible"]
    if visible == 0 and not is_self_query:
        return 403
    return taiko_id

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

def _set_taiko_bind_visibility(identity_key: str, visible: int, event=None) -> int:
    from taiko_bot.binding_mutation_client import set_center_bind_visibility, command_request_id
    principal = _normalize_identity_key(identity_key)
    result = set_center_bind_visibility(principal, visible, settings=_SETTINGS,
        request_id=command_request_id(event, principal, "visibility"))
    return result["matched"]

def _taiko_bind_usage_message(event: Optional[MessageEvent] = None) -> str:
    base = "请先绑定账号，发送“绑定+你的鼓众广场ID”进行绑定。"
    if event is not None and is_qq_official_event(event):
        return (
            f"{base}\n"
            "旧绑定迁移：请用原 QQ 私聊旧 bot 发送“迁移验证码”，再私聊这里发送“绑定QQ QQ号 验证码”。"
        )
    return base

def _execute_taiko_update(
    taiko_id: str,
    *,
    show_all_changes: bool = False,
    include_changes_image: bool = True,
) -> Dict[str, Any]:
    try:
        payload = proxy_center_userdata_update(
            taiko_id,
            show_all=show_all_changes,
            include_image=include_changes_image,
        )
    except ViewerClientError as exc:
        if exc.status_code == 404:
            return {
                "ok": False,
                "message": "请确认绑定鼓众ID是否正确？",
                "image": None,
            }
        return {"ok": False, "message": str(exc), "image": None}
    img_buf = _apply_center_sync_result(payload, fallback_source="viewer-cache", expected_identity=taiko_id)
    return {
        "ok": True,
        "message": str(payload.get("message") or "更新成功！"),
        "image": img_buf,
    }

def _get_current_bind_entry(identity_key: str) -> Optional[Dict[str, Any]]:
    identity_key = _normalize_identity_key(identity_key)
    bind_info = _get_taiko_bind_info_from_center(identity_key)
    return _center_bind_info_to_entry(bind_info)

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
    sources = dict(entry.get("sources") or {})
    return (
        len(
            [
                taiko_id
                for taiko_id in _get_bind_ids(entry)
                if _infer_bind_source(taiko_id, sources) != "manual"
            ]
        )
        >= 2
    )

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
    show_all_changes: bool = False,
    include_changes_image: bool = True,
    progress=None,
) -> Dict[str, Any]:
    try:
        payload = proxy_center_hiroba_sync(
            taiko_id,
            show_all=show_all_changes,
            include_image=include_changes_image,
        )
    except ViewerClientError as exc:
        return {"ok": False, "message": f"Hiroba 更新失败：{exc}", "image": None}
    img_buf = _apply_center_sync_result(payload, fallback_source="viewer-cache", expected_identity=taiko_id)
    return {
        "ok": True,
        "message": str(payload.get("message") or "Hiroba 更新成功！"),
        "image": img_buf,
    }

def _create_hiroba_progress_reporter(
    matcher: Matcher,
    event: MessageEvent,
    *,
    min_interval: float = 8.0,
):
    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    state = {"last_ts": 0.0, "last_msg": ""}

    def report(message: str, *, force: bool = False) -> None:
        text = str(message or "").strip()
        if not text:
            return
        now = time.monotonic()
        with lock:
            if not force and text == state["last_msg"]:
                return
            if not force and now - state["last_ts"] < min_interval:
                return
            state["last_ts"] = now
            state["last_msg"] = text
        asyncio.run_coroutine_threadsafe(
            _send_text_reply_without_finish(matcher, event, text),
            loop,
        )

    return report

async def _finish_hiroba_update_success_reply(
    matcher: Matcher,
    event: MessageEvent,
    *,
    success_message: str,
    img_buf: bytes | BytesIO | Path | None,
    show_all_changes: bool = False,
) -> None:
    from ..lifecycle_authority import delivery_for
    matcher = delivery_for(matcher)
    final_message = str(success_message or "Hiroba 更新成功！")
    if show_all_changes:
        final_message += "\n已展示全部变更。"

    if img_buf is not None:
        try:
            await _finish_image_reply(
                matcher,
                event,
                img_buf,
                prefix_text=final_message,
                quick_actions=True,
                prefer_markdown_image=True,
                markdown_image_name="hirobaupdate",
            )
            return
        except FinishedException:
            raise
        except Exception:
            logger.exception("hiroba success image reply failed")

    await _finish_text_reply(
        matcher,
        event,
        final_message,
        quick_actions=True,
    )

async def _fetch_bind_player_profile(
    user_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        profile = fetch_wahlap_player_profile(str(user_id).strip())
    except ViewerClientError as exc:
        return None, str(exc)
    return profile if isinstance(profile, dict) else None, None

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
        "province": str(getattr(profile, "region", "") or "").strip(),
        "gameCostume": {
            "title": str(profile.title or "").strip(),
            "titleplate_id": 0,
        },
    }

def _fetch_hiroba_public_profile_via_service_account(taiko_id: str):
    ensure_hiroba_credentials_table()
    creds = load_hiroba_credentials(HIROBA_SERVICE_TAIKO_NO)
    if creds is None:
        raise RuntimeError(
            f"未配置 Hiroba 服务账号 {HIROBA_SERVICE_TAIKO_NO} 的登录凭据。"
        )
    email, password = creds
    client = HirobaClient(timeout=30)
    client.login(email, password, taiko_no=HIROBA_SERVICE_TAIKO_NO)
    html = client.fetch_public_profile(taiko_id)
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

def _should_skip_bind_verification(taiko_id: str) -> bool:
    return str(taiko_id).strip() in BIND_VERIFY_BYPASS_IDS

def _can_direct_bind_hiroba_id(identity_key: str, taiko_id: str) -> Tuple[bool, str]:
    normalized_identity_key = _normalize_identity_key(identity_key)
    normalized_taiko_id = str(taiko_id or "").strip()
    if not _is_hiroba_taiko_no(normalized_taiko_id):
        return False, "请输入正确的鼓众广场ID。"
    owner = load_hiroba_credential_owner(normalized_taiko_id)
    if owner and owner != normalized_identity_key:
        return (
            False,
            "该 12 位 Hiroba 太鼓番已由其他账号配置过 Hiroba 凭据，"
            "为防止冒绑，请改用“绑定hiroba 邮箱 密码 太鼓番”完成验证。",
        )
    if not _has_center_hiroba_credentials_cached(normalized_taiko_id):
        return (
            False,
            "该日服/Hiroba 太鼓番尚未在中心保存凭据。\n"
            "请先发送“绑定hiroba 邮箱 密码 太鼓番”完成首次验证与同步。",
        )
    bind_info = _get_taiko_bind_info_from_center(normalized_identity_key)
    if bind_info is None:
        return True, ""
    bindings = bind_info.get("bindings") or []
    if any(
        str(getattr(item, "taiko_id", "") or "").strip() == normalized_taiko_id
        for item in bindings
    ):
        return True, ""
    return True, ""

def _finalize_hiroba_direct_bind(identity_key: str, taiko_id: str) -> str:
    reply_msg, is_first_binding = _upsert_bind_record(identity_key, taiko_id, source="hiroba")
    auto_update_tip = _build_bind_auto_update_tip(
        identity_key,
        taiko_id,
        is_first_binding,
        source="hiroba",
    )
    return (
        "已按日服/Hiroba 太鼓番绑定。\n"
        f"{reply_msg}\n"
        "如需后续同步，请发送“更新hiroba”。"
        f"{auto_update_tip}"
    )

def _build_bind_auto_update_tip(
    identity_key: str,
    taiko_id: str,
    is_first_binding: bool,
    *,
    source: Optional[str] = None,
) -> str:
    if not is_first_binding:
        return ""
    inferred_source = str(source or "").strip().lower() or _infer_bind_source(taiko_id)
    if inferred_source == "hiroba":
        update_result = _execute_hiroba_update(taiko_id, include_changes_image=False)
        success_text = "\n首次绑定已自动执行一次 更新hiroba。"
        failure_text = (
            "\n首次绑定后已自动尝试执行一次 更新hiroba，但本次更新未完成，可稍后手动执行。"
        )
    else:
        update_result = _execute_taiko_update(taiko_id, include_changes_image=False)
        success_text = "\n首次绑定已自动执行一次 taikoupdate。"
        failure_text = (
            "\n首次绑定后已自动尝试执行一次 taikoupdate，但本次更新未完成，可稍后手动执行。"
        )
    if update_result.get("ok"):
        return success_text
    logger.warning(
        "首次绑定自动更新失败，qq=%s taiko_id=%s source=%s msg=%s",
        identity_key,
        taiko_id,
        inferred_source,
        update_result.get("message"),
    )
    return failure_text

def _finalize_bind_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> str:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_tip = _build_bind_auto_update_tip(
        identity_key, taiko_id, is_first_binding, source="wahlap"
    )
    return (
        f"{reply_msg}\n已通过称号变更验证。\n当前称号：{current_title or '空称号'}"
        f"{auto_update_tip}"
    )

def _finalize_bind_without_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> str:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_tip = _build_bind_auto_update_tip(
        identity_key, taiko_id, is_first_binding, source="wahlap"
    )
    return (
        f"{reply_msg}\n已按临时白名单跳过绑定验证。\n当前称号：{current_title or '空称号'}"
        f"{auto_update_tip}"
    )

def _migrate_bind_from_legacy_qq(legacy_qq: str, target_identity_key: str, *, code: str = "") -> Tuple[bool, str]:
    from taiko_bot.qq_migration_client import migrate_center_qq_bindings
    principal = _normalize_identity_key(target_identity_key)
    result = migrate_center_qq_bindings(legacy_qq,principal,code=code,settings=_SETTINGS)
    entry = _center_bind_info_to_entry(result['binding'])
    BIND_VERIFY_SESSIONS.pop(principal,None)
    if entry is None:
        return True,"迁移已完成，目前没有绑定账号。"
    try:summary = _format_multi_bind_summary(entry)
    except Exception:summary = "请查询当前绑定。"
    action = "完成迁移" if result['firstBinding'] else "完成合并"
    tip = ""
    if result['firstBinding'] and not result['replayed']:
        try:
            source = entry['sources'][result['sourceCurrentId']]
            tip = _build_bind_auto_update_tip(principal,result['sourceCurrentId'],True,source=source)
        except Exception:
            tip = "\n账号已绑定，本次自动更新未完成，请稍后手动更新。"
    return True,f"已根据 QQ {legacy_qq} 的历史绑定{action}。\n当前绑定：{summary}{tip}"

def _infer_bind_source(taiko_id: str, sources: Optional[Dict[str, str]] = None) -> str:
    taiko_id = str(taiko_id or "").strip()
    sources = sources or {}
    explicit = str(sources.get(taiko_id) or "").strip().lower()
    if explicit in {"hiroba", "wahlap", "manual"}:
        return explicit
    if _has_center_hiroba_credentials_cached(taiko_id):
        return "hiroba"
    return "wahlap"

def _has_center_hiroba_credentials_cached(taiko_id: str) -> bool:
    normalized = str(taiko_id or "").strip()
    if not normalized:
        return False
    return bool(has_center_hiroba_credentials(normalized))

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
            nickname = str((entry.get("names") or {}).get(taiko_id) or "手动账号")
            parts.append(f"u{idx}:{nickname}(手动){marker}")
        else:
            parts.append(f"u{idx}:{taiko_id}({_bind_source_label(source)}){marker}")
    return " / ".join(parts)

def _format_current_bind_summary_safe(identity_key: str) -> str:
    try:
        return _format_multi_bind_summary(_get_current_bind_entry(identity_key))
    except Exception as exc:
        logger.warning(
            "manual account action succeeded but bind summary lookup failed: "
            f"identity_key={identity_key} error={exc}"
        )
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

def _resolve_bind_remove_target(entry: Dict[str, Any], target: str) -> Tuple[int, str]:
    ids = list(entry.get("ids") or [])
    if not ids:
        raise ValueError("当前没有可删除的鼓众广场ID。")

    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    target = str(target or "").strip()
    if not target:
        return current_index, ids[current_index]

    slot_match = re.fullmatch(r"[uU]([1-9]\d*)", target)
    if slot_match:
        slot_index = int(slot_match.group(1)) - 1
        if slot_index < 0 or slot_index >= len(ids):
            raise ValueError(f"当前仅已绑定 u1~u{len(ids)}。")
        return slot_index, ids[slot_index]

    if target in ids:
        return ids.index(target), target

    if target.isdigit():
        raise ValueError("当前未绑定该鼓众广场ID。")

    raise ValueError(
        "参数错误，请使用 删除绑定 / 删除绑定 u2 / 删除绑定 123456 这类形式。"
    )

def _upsert_bind_record(
    qq: str, taiko_id: str, *, source: Optional[str] = None
) -> Tuple[str, bool]:
    qq = _normalize_identity_key(qq)
    taiko_id = str(taiko_id).strip()
    before_info = _get_taiko_bind_info_from_center(qq)
    before_entry = _center_bind_info_to_entry(before_info)
    existing_ids = _get_bind_ids(before_entry)
    was_existing = taiko_id in existing_ids
    after_info = proxy_center_bind_upsert(
        qq,
        taiko_id,
        visible=int(before_info.get("visible") or 0) if before_info else 0,
        source=str(source or "wahlap").strip().lower() or "wahlap",
        settings=_SETTINGS,
    )
    after_entry = _center_bind_info_to_entry(after_info)
    current_slot = int((after_info or {}).get("currentSlot") or 1)
    if not existing_ids:
        reply_msg = "绑定成功！已设为 u1。"
    elif was_existing:
        reply_msg = f"该ID已绑定，已切换到 u{current_slot}。"
    else:
        reply_msg = f"新增绑定成功！已设为 u{current_slot}。"
    summary = _format_multi_bind_summary(after_entry)
    return f"{reply_msg}\n当前绑定：{summary}", not existing_ids

def _switch_bind_record(
    qq: str, slot_number: int, event: Optional[MessageEvent] = None
) -> Tuple[bool, str]:
    qq = _normalize_identity_key(qq)
    info = _get_taiko_bind_info_from_center(qq)
    entry = _center_bind_info_to_entry(info)
    if entry is None:
        return False, _taiko_bind_usage_message(event)
    ids = _get_bind_ids(entry)
    if slot_number == 0:
        if not _has_virtual_bind_slot(entry):
            return False, "当前至少需要绑定 2 个 CN/JP 账号后才能切换到 u0。"
        switched = proxy_center_bind_switch_current(qq, 0, settings=_SETTINGS)
        switched_entry = _center_bind_info_to_entry(switched)
        return True, (
            "已切换到 u0：合并账户（只读）\n"
            f"当前绑定：{_format_multi_bind_summary(switched_entry)}"
        )
    if slot_number < 1 or slot_number > len(ids):
        return False, f"当前仅已绑定 u1~u{len(ids)}。"
    switched = proxy_center_bind_switch_current(qq, slot_number, settings=_SETTINGS)
    switched_entry = _center_bind_info_to_entry(switched)
    summary = _format_multi_bind_summary(switched_entry)
    target_id = str((switched or {}).get("id") or ids[slot_number - 1])
    source = _infer_bind_source(
        ids[slot_number - 1], (switched_entry or {}).get("sources") or {}
    )
    target_label = (
        str((switched_entry or {}).get("names", {}).get(ids[slot_number - 1]) or "手动账号")
        if source == "manual"
        else target_id
    )
    return True, f"已切换到 u{slot_number}：{target_label}\n当前绑定：{summary}"

def _remove_bind_record(
    qq: str,
    target: str = "",
    force_last: bool = False,
    event: Optional[MessageEvent] = None,
) -> Tuple[bool, str, bool]:
    from taiko_bot.binding_mutation_client import remove_center_bind, command_request_id
    principal = _normalize_identity_key(qq)
    if force_last and not re.fullmatch(r"[0-9]{1,25}", target):
        return False, "删除确认已失效，请重新发送“删除绑定”。", False
    info = fetch_center_bind_info(principal, _SETTINGS)
    entry = _center_bind_info_to_entry(info)
    if not entry:
        return False, _taiko_bind_usage_message(event), False
    try:
        _, target_id = _resolve_bind_remove_target(entry, target)
    except ValueError as error:
        return False, str(error), False
    if (entry.get("sources") or {}).get(target_id) == "manual":
        return False, "手动账号请使用“解绑空白账号”或“永久删除空白账号”。", False
    try:
        result = remove_center_bind(principal, target_id, force_last=force_last, settings=_SETTINGS,
            request_id=command_request_id(event, principal, "remove"))
    except ViewerClientError as error:
        if error.status_code == 404:
            return False, str(error), False
        raise
    if result["needsConfirmation"]:
        BIND_DELETE_CONFIRM_SESSIONS[principal] = {"taiko_id":target_id,
            "expires_at":_now_ts()+BIND_DELETE_CONFIRM_TIMEOUT_SECONDS}
        return (False, f"当前只剩最后 1 个鼓众广场ID：{target_id}\n"
            f"如需确认删除，请在 {BIND_DELETE_CONFIRM_TIMEOUT_SECONDS // 60} 分钟内发送“确认删除绑定”。", True)
    BIND_DELETE_CONFIRM_SESSIONS.pop(principal, None)
    after = _center_bind_info_to_entry(result["binding"])
    if after:
        reply = f"已删除绑定：{target_id}\n当前绑定：{_format_multi_bind_summary(after)}"
    else:
        reply = f"已删除最后一个绑定：{target_id}\n当前已无绑定的鼓众广场ID。"
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
        "1": 1, "简单": 1, "梅": 1,
        "2": 2, "一般": 2, "竹": 2,
        "3": 3, "困难": 3, "松": 3,
        "4": 4, "魔王": 4, "鬼": 4, "表": 4,
        "5": 5, "里谱": 5, "里": 5,
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
    body = str(text or "").strip()[len(command):].strip()
    try:
        return shlex.split(body)
    except ValueError as exc:
        raise ValueError(f"参数引号不完整：{exc}") from exc

def _parse_manual_score_lookup(text: str, command: str) -> Tuple[int, str, int]:
    tokens = _manual_command_tokens(text, command)
    if len(tokens) != 2:
        raise ValueError(f"格式：{command} <歌曲ID或曲名> <难度>")
    song_no, title = _resolve_manual_song(tokens[0], require_unknown_title=False)
    return _manual_diff_level(tokens[1]), title, song_no

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
_migrate_bind_from_legacy_qq = binding_mutation(_migrate_bind_from_legacy_qq)
_set_taiko_bind_visibility = binding_mutation(_set_taiko_bind_visibility)
bind_hiroba_credentials = binding_mutation(bind_hiroba_credentials)
