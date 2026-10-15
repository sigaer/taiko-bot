from __future__ import annotations
from . import lifecycle_host as host
from ..lifecycle_authority import lifecycle_boundary, delivery_for

from .lifecycle_host import (Bot, DEVELOPER_QQ_EXPORT_DIR, MessageEvent, PublicScoreTokenError, Rule, UPDATE_TYPO_VARIANTS, ViewerClientError, _SETTINGS, _build_update_command_hint, _execute_taiko_update, _fetch_developer_userdata_via_forum, _finish_image_reply, _finish_text_reply, _get_taiko_bind_info_from_center, _is_external_bot_mentioned, _is_private_message_event, _is_update_command_targeting_other_account, _normalize_identity_key, _normalize_update_command_text, _parse_update_command, _resolve_bound_taiko_id, _resolve_requested_identity_key, _should_trigger_update_command, _taiko_bind_usage_message, _update_command_rule, _update_typo_rule, _upload_json_file_for_event, asyncio, datetime, extract_plain_text, fetch_center_bind_info, get_identity_key, issue_public_score_token_for_taiko_id, json, on_message, on_regex, re, taiko_rule)

update = on_message(rule=taiko_rule & Rule(_update_command_rule), block=False)

update_typo = on_message(rule=taiko_rule & Rule(_update_typo_rule), block=False)

public_score_token = on_regex(
    r"^(?:网页成绩token|成绩token|scoretoken|获取token)(?:\s*(?:重置|刷新|reset))?$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)

developer_userdata = on_regex(
    r"^(?:开发者数据|taikodevdata)\s+([0-9A-Za-z]{24})\s+([0-9]{5,12})$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)

@update.handle()
@lifecycle_boundary("update", host)
async def update_handle(event: MessageEvent):
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return
    plain_text = extract_plain_text(event)
    parsed_command = _parse_update_command(plain_text)
    if parsed_command is None:
        return
    show_all_changes = bool(parsed_command.get("show_all"))
    identity_key, _ = _resolve_requested_identity_key(event)
    bind_info = _get_taiko_bind_info_from_center(identity_key)

    taiko_id = _resolve_bound_taiko_id(event)
    if taiko_id == 404:
        await _finish_text_reply(update, event, _taiko_bind_usage_message(event))
        return
    if taiko_id == 403:
        await _finish_text_reply(update, event, "查不到呢，可能不给看哦~")
        return
    if bind_info and str(bind_info.get("currentSource") or "wahlap") != "wahlap":
        await _finish_text_reply(
            update,
            event,
            _build_update_command_hint(identity_key, expected_source="wahlap"),
        )
        return
    update_result = await asyncio.to_thread(
        _execute_taiko_update,
        taiko_id,
        show_all_changes=show_all_changes,
        include_changes_image=True,
    )
    if not update_result.get("ok"):
        await _finish_text_reply(
            update,
            event,
            str(update_result.get("message") or "更新失败，怎么回事呢？"),
        )
        return

    img_buf = update_result.get("image")
    success_message = "更新成功！"
    if show_all_changes:
        success_message += "\n已展示全部变更。"
    else:
        success_message += (
            "\n默认每项最多展示5个；查看全部请使用“taikoupdate all”或“更新广场 全部”。"
        )
    if img_buf is not None:
        await _finish_image_reply(
            update,
            event,
            img_buf,
            prefix_text=success_message,
            quick_actions=True,
            prefer_markdown_image=True,
            markdown_image_name="taikoupdate",
        )
    await _finish_text_reply(update, event, success_message, quick_actions=True)

@update_typo.handle()
async def update_typo_handle(event: MessageEvent):
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return
    plain_text = extract_plain_text(event)
    if _should_trigger_update_command(plain_text):
        return
    normalized = _normalize_update_command_text(plain_text)
    if not normalized:
        return
    if normalized in UPDATE_TYPO_VARIANTS:
        await _finish_text_reply(update_typo, event, "别急")

@public_score_token.handle()
@lifecycle_boundary("public_score_token", host)
async def public_score_token_handle(event: MessageEvent):
    public_score_token = delivery_for(globals()["public_score_token"])
    if not _is_private_message_event(event):
        await public_score_token.finish(
            "该 token 可直接读取完整成绩，请私聊机器人发送“网页成绩token”生成，避免群聊泄露。",
            reply_message=True,
        )
        return

    try:
        identity_key = _normalize_identity_key(get_identity_key(event=event))
        info = fetch_center_bind_info(identity_key, _SETTINGS)
    except ViewerClientError as error:
        await public_score_token.finish(str(error), reply_message=True)
        return
    except Exception:
        await public_score_token.finish("中心绑定服务暂不可用，请稍后重试。", reply_message=True)
        return
    if info is None:
        await public_score_token.finish(_taiko_bind_usage_message(event), reply_message=True)
        return
    if info.get("currentVirtual") or info.get("currentSource") == "manual":
        await public_score_token.finish("请切换到自己的实账号生成成绩 token。", reply_message=True)
        return
    try:
        issued = issue_public_score_token_for_taiko_id(str(info["id"]), identity_key=identity_key)
    except PublicScoreTokenError as error:
        await public_score_token.finish(str(error), reply_message=True)
        return
    except ViewerClientError as error:
        await public_score_token.finish(str(error), reply_message=True)
        return
    except Exception:
        await public_score_token.finish("中心成绩 token 服务暂不可用，请稍后重试。", reply_message=True)
        return

    token = str(issued["token"])
    await public_score_token.finish(
        "已生成新的网页成绩 token。再次执行本指令会使旧 token 失效。\n"
        f"当前鼓众ID：{issued['taiko_id']}\n"
        f"来源绑定：{issued['owner_display']}\n"
        f"token：{token}\n"
        "请在对应的网页输入这串 token。\n"
        "请妥善保管，不要发到群里。",
        reply_message=True,
    )

@developer_userdata.handle()
async def developer_userdata_handle(event: MessageEvent, bot: Bot):
    plain_text = extract_plain_text(event).strip()
    command_match = re.match(
        r"^(?:开发者数据|taikodevdata)\s+([0-9A-Za-z]{24})\s+([0-9]{5,12})$",
        plain_text,
        flags=re.IGNORECASE,
    )
    if not command_match:
        await developer_userdata.finish(
            "格式错误，请使用：开发者数据 <24位token> <userid>",
            reply_message=True,
        )

    token = command_match.group(1).strip()
    user_id = command_match.group(2).strip()
    try:
        payload = await _fetch_developer_userdata_via_forum(token, user_id)
    except Exception as error:
        await developer_userdata.finish(
            f"开发者数据查询失败：{error}",
            reply_message=True,
        )

    try:
        DEVELOPER_QQ_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = (
            DEVELOPER_QQ_EXPORT_DIR
            / f"developer_userdata_{user_id}_{event.get_user_id()}_{timestamp}.json"
        )
        export_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await _fetch_developer_userdata_via_forum(token, user_id)
        await _upload_json_file_for_event(
            bot,
            event,
            export_path,
            f"developer_userdata_{user_id}.json",
        )
    except Exception as error:
        try:
            await _fetch_developer_userdata_via_forum(token, user_id)
        except Exception:
            await developer_userdata.finish("开发者数据访问权限已失效，请重新验证 token。", reply_message=True)
            return
        preview = json.dumps(payload, ensure_ascii=False, indent=2)[:1200]
        await developer_userdata.finish(
            f"完整 JSON 获取成功，但发送文件失败：{error}\n以下为前 1200 字预览：\n{preview}",
            reply_message=True,
        )

    await developer_userdata.finish(
        f"已发送 userid={user_id} 的完整 JSON 文件。",
        reply_message=True,
    )
