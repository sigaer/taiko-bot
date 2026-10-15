from __future__ import annotations
from . import lifecycle_host as host
from ..lifecycle_authority import lifecycle_boundary, delivery_for

from .lifecycle_host import (BIND_VERIFY_SESSIONS, BIND_VERIFY_TIMEOUT_SECONDS, HirobaError, HirobaProfilePrivateError, ManualAccountApiError, MessageEvent, RegexMatched, ViewerClientError, _SETTINGS, _bind_title_changed, _build_bind_profile_from_hiroba_public_profile, _build_bind_title_unchanged_message, _build_bind_verify_prompt, _build_update_command_hint, _can_direct_bind_hiroba_id, _center_bind_info_to_entry, _create_hiroba_progress_reporter, _execute_hiroba_update, _extract_bind_title_info, _fetch_bind_player_profile, _fetch_hiroba_public_profile_via_service_account, _finalize_bind_verification, _finalize_bind_without_verification, _finalize_hiroba_direct_bind, _finish_hiroba_update_success_reply, _finish_text_reply, _format_multi_bind_summary, _get_bind_delete_confirm_session, _get_bind_verify_session, _get_current_bind_entry, _get_current_bind_taiko_id, _get_taiko_bind_info_from_center, _infer_bind_source, _is_hiroba_taiko_no, _is_private_message_event, _is_wahlap_taiko_id, _migrate_bind_from_legacy_qq, _normalize_bind_input, _normalize_identity_key, _now_ts, _remove_bind_record, _resolve_bound_taiko_id, _resolve_requested_identity_key, _send_text_reply_without_finish, _set_taiko_bind_visibility, _should_skip_bind_verification, _switch_bind_record, _taiko_bind_usage_message, asyncio, bind_hiroba_credentials, call_manual_account_api, extract_plain_text, get_identity_key, on_fullmatch, on_regex, re, taiko_rule)

qq_migration_code = on_fullmatch("迁移验证码", rule=taiko_rule)

bind_qq = on_regex(r"(?i)^/?绑定\s*qq\s*([1-9]\d{4,14})(?:\s+([a-f0-9]{32}))?$", rule=taiko_rule)

bind_qq_prompt = on_fullmatch("绑定QQ", rule=taiko_rule)

bind = on_regex(r"^/?绑定(?:\s+|\+)?([0-9]{0,12})$", rule=taiko_rule)

bind_confirm = on_regex(
    r"^(确认绑定|绑定确认|验证绑定)\s*([0-9]{0,12})?$", rule=taiko_rule
)

bind_switch = on_regex(r"^[uU](0|[1-9]\d*)$", rule=taiko_rule)

bind_hiroba = on_regex(
    r"^/?绑定hiroba\s+(\S+@\S+\.\S+)\s+(\S+)(?:\s+(\d{10,14}))?\s*$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)

hiroba_update = on_regex(
    r"^(?:hirobaupdate|更新hiroba|更新ひろば)(?:(?:\s+|)(?P<show_all>all|全部|全量|-a|--all))?\s*$",
    flags=re.IGNORECASE,
    rule=taiko_rule,
)

bind_remove = on_regex(
    r"^(删除绑定|解绑)(?:\s*(u[1-9]\d*|[0-9]{5,12}))?$", rule=taiko_rule
)

bind_remove_confirm = on_regex(
    r"^(确认删除绑定|删除绑定确认|确认解绑)$", rule=taiko_rule
)

show_bind = on_fullmatch("给看", rule=taiko_rule)

unshow_bind = on_fullmatch("不给看", rule=taiko_rule)

@qq_migration_code.handle()
@lifecycle_boundary("qq_migration_code", host)
async def qq_migration_code_handle(event: MessageEvent):
    if not _is_private_message_event(event):
        await _finish_text_reply(qq_migration_code,event,"请私聊旧 bot 申请迁移验证码。")
        return
    from taiko_bot.qq_migration_client import issue_center_qq_migration_code
    principal = _normalize_identity_key(get_identity_key(event=event))
    try:
        code = await asyncio.to_thread(issue_center_qq_migration_code,principal,settings=_SETTINGS)
    except ViewerClientError as error:
        await _finish_text_reply(qq_migration_code,event,str(error))
        return
    except Exception:
        await _finish_text_reply(qq_migration_code,event,"迁移验证码暂不可用，请稍后重试。")
        return
    await _finish_text_reply(qq_migration_code,event,
        f"请私聊新 bot 发送：绑定QQ {principal.split(':',1)[1]} {code}\n验证码十分钟内有效。")

@bind_qq.handle()
@lifecycle_boundary("bind_qq", host)
async def bind_qq_handle(event: MessageEvent, match=RegexMatched()):
    if not _is_private_message_event(event):
        await _finish_text_reply(bind_qq,event,"请私聊 bot 完成 QQ 绑定迁移。")
        return
    principal = _normalize_identity_key(get_identity_key(event=event))
    try:
        success,reply = await asyncio.to_thread(_migrate_bind_from_legacy_qq,str(match.group(1)),principal,code=str(match.group(2) or '').lower())
    except ViewerClientError as error:
        await _finish_text_reply(bind_qq,event,str(error))
        return
    except Exception:
        await _finish_text_reply(bind_qq,event,"迁移结果暂无法确认，请查询当前绑定后再重试。")
        return
    await _finish_text_reply(bind_qq,event,reply,quick_actions=success)

@bind_qq_prompt.handle()
async def bind_qq_prompt_handle(event: MessageEvent):
    await _finish_text_reply(bind_qq_prompt,event,
        "请用原 QQ 私聊旧 bot 发送“迁移验证码”，再私聊这里发送“绑定QQ QQ号 验证码”。")

@bind.handle()
@lifecycle_boundary("bind", host)
async def bind_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    taiko_id = _normalize_bind_input(match.group(1) or "")
    if not taiko_id:
        await _finish_text_reply(bind, event, "请输入正确的鼓众广场ID。")
    if _is_hiroba_taiko_no(taiko_id):
        ok, message = _can_direct_bind_hiroba_id(identity_key, taiko_id)
        if not ok:
            await _finish_text_reply(bind, event, message)
        try:
            hiroba_profile = await asyncio.to_thread(
                _fetch_hiroba_public_profile_via_service_account,
                taiko_id,
            )
        except HirobaProfilePrivateError:
            await _finish_text_reply(
                bind,
                event,
                "该 Hiroba 账号当前为非公开资料，服务账号无法读取称号信息。\n"
                "请先发送“绑定hiroba 邮箱 密码 太鼓番”完成登录验证。",
            )
        except HirobaError as e:
            await _finish_text_reply(bind, event, f"读取 Hiroba 公开资料失败：{e}")
        except Exception as e:
            await _finish_text_reply(bind, event, f"读取 Hiroba 公开资料失败：{e}")

        profile = _build_bind_profile_from_hiroba_public_profile(hiroba_profile)
        current_title, current_titleplate_id = _extract_bind_title_info(profile)
        player_name = str(profile.get("mydon_name") or taiko_id).strip() or taiko_id
        province = str(profile.get("province") or "").strip()

        existing_session = _get_bind_verify_session(identity_key)
        if (
            existing_session is not None
            and str(existing_session.get("taiko_id") or "").strip() == taiko_id
        ):
            if _bind_title_changed(existing_session, profile):
                try:
                    reply_msg = _finalize_hiroba_direct_bind(identity_key, taiko_id)
                except Exception as e:
                    await _finish_text_reply(bind, event, f"写入绑定失败：{e}")
                BIND_VERIFY_SESSIONS.pop(identity_key, None)
                await _finish_text_reply(bind, event, reply_msg, quick_actions=True)
            await _finish_text_reply(
                bind,
                event,
                _build_bind_title_unchanged_message(
                    existing_session, current_title, taiko_id
                ),
            )

        BIND_VERIFY_SESSIONS[identity_key] = {
            "taiko_id": taiko_id,
            "title": current_title,
            "titleplate_id": current_titleplate_id,
            "player_name": player_name,
            "province": province,
            "expires_at": _now_ts() + BIND_VERIFY_TIMEOUT_SECONDS,
        }
        await _finish_text_reply(
            bind,
            event,
            _build_bind_verify_prompt(player_name, taiko_id, current_title, province),
        )
    if not _is_wahlap_taiko_id(taiko_id):
        await _finish_text_reply(bind, event, "请输入正确的鼓众广场ID。")

    profile, err = await _fetch_bind_player_profile(taiko_id)
    if err:
        await _finish_text_reply(bind, event, err)
    if not isinstance(profile, dict):
        await _finish_text_reply(bind, event, "未找到该鼓众ID，请确认输入是否正确。")

    current_title, current_titleplate_id = _extract_bind_title_info(profile)
    player_name = str(profile.get("mydon_name") or taiko_id).strip() or taiko_id
    province = str(profile.get("province") or "").strip()
    if _should_skip_bind_verification(taiko_id):
        try:
            reply_msg = _finalize_bind_without_verification(
                identity_key, taiko_id, current_title
            )
        except Exception as e:
            await _finish_text_reply(bind, event, f"写入绑定失败：{e}")
        await _finish_text_reply(bind, event, reply_msg, quick_actions=True)

    existing_session = _get_bind_verify_session(identity_key)
    if (
        existing_session is not None
        and str(existing_session.get("taiko_id") or "").strip() == taiko_id
    ):
        if _bind_title_changed(existing_session, profile):
            try:
                reply_msg = _finalize_bind_verification(
                    identity_key, taiko_id, current_title
                )
            except Exception as e:
                await _finish_text_reply(bind, event, f"写入绑定失败：{e}")
            await _finish_text_reply(bind, event, reply_msg, quick_actions=True)
        await _finish_text_reply(
            bind,
            event,
            _build_bind_title_unchanged_message(
                existing_session, current_title, taiko_id
            ),
        )

    BIND_VERIFY_SESSIONS[identity_key] = {
        "taiko_id": taiko_id,
        "title": current_title,
        "titleplate_id": current_titleplate_id,
        "player_name": player_name,
        "province": province,
        "expires_at": _now_ts() + BIND_VERIFY_TIMEOUT_SECONDS,
    }
    await _finish_text_reply(
        bind,
        event,
        _build_bind_verify_prompt(player_name, taiko_id, current_title, province),
    )

@bind_confirm.handle()
@lifecycle_boundary("bind_confirm", host)
async def bind_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    plain_text = extract_plain_text(event)
    match = re.match(r"^(确认绑定|绑定确认|验证绑定)\s*([0-9]{0,12})?$", plain_text)
    input_id = str(match.group(2) or "").strip() if match else ""

    session = _get_bind_verify_session(identity_key)
    if session is None:
        await _finish_text_reply(
            bind_confirm,
            event,
            "当前没有待确认的绑定请求，请先发送“绑定+你的鼓众广场ID”。",
        )

    taiko_id = str(session.get("taiko_id") or "").strip()
    if input_id and input_id != taiko_id:
        await _finish_text_reply(
            bind_confirm,
            event,
            f"待验证的鼓众ID是 {taiko_id}，请直接发送“确认绑定”或重新发起绑定。",
        )

    profile, err = await _fetch_bind_player_profile(taiko_id)
    if err:
        await _finish_text_reply(bind_confirm, event, err)
    if not isinstance(profile, dict):
        await _finish_text_reply(
            bind_confirm, event, "未找到该鼓众ID，请确认输入是否正确。"
        )

    current_title, _ = _extract_bind_title_info(profile)
    if not _bind_title_changed(session, profile):
        await _finish_text_reply(
            bind_confirm,
            event,
            _build_bind_title_unchanged_message(session, current_title, taiko_id),
        )

    try:
        reply_msg = _finalize_bind_verification(identity_key, taiko_id, current_title)
    except Exception as e:
        await _finish_text_reply(bind_confirm, event, f"写入绑定失败：{e}")
    await _finish_text_reply(
        bind_confirm,
        event,
        reply_msg,
        quick_actions=True,
    )

@bind_switch.handle()
@lifecycle_boundary("bind_switch", host)
async def bind_switch_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        slot_number = int(match.group(1))
    except Exception:
        await _finish_text_reply(
            bind_switch, event, "参数错误，请使用 u0 / u1 / u2 这类形式。"
        )

    try:
        ok, msg = _switch_bind_record(identity_key, slot_number, event=event)
    except Exception as e:
        await _finish_text_reply(bind_switch, event, f"切换绑定失败：{e}")

    await _finish_text_reply(bind_switch, event, msg)

@bind_hiroba.handle()
@lifecycle_boundary("bind_hiroba", host)
async def bind_hiroba_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    email = str(match.group(1) or "").strip()
    password = str(match.group(2) or "").strip()
    target_taiko_no = str(match.group(3) or "").strip()
    if not email or not password:
        await _finish_text_reply(
            bind_hiroba, event, "格式错误，请使用：绑定hiroba 邮箱 密码 [太鼓番]"
        )
        return

    try:
        await _send_text_reply_without_finish(
            bind_hiroba,
            event,
            "开始绑定 Hiroba 账号",
        )
        bind_result = await asyncio.to_thread(
            bind_hiroba_credentials,
            email=email,
            password=password,
            target_taiko_no=target_taiko_no,
            configured_by_qq=identity_key,
        )
        synced_ids = list(bind_result.get("taikoIds") or [])
        if not synced_ids:
            if target_taiko_no:
                raise RuntimeError(
                    f"该 Bandai Namco ID 下未找到太鼓番 {target_taiko_no}。"
                )
            raise RuntimeError("未找到可绑定的 Hiroba 太鼓番。")
        bind_info = bind_result.get("bind") if isinstance(bind_result.get("bind"), dict) else None
        entry = _center_bind_info_to_entry(bind_info)
        reply_msg = (
            f"已切换到 u{int(bind_info.get('currentSlot') or 1)}：{bind_info.get('currentTaikoId') or bind_info.get('id')}\n"
            f"当前绑定：{_format_multi_bind_summary(entry)}"
            if bind_info
            else f"当前绑定：{_format_multi_bind_summary(_get_current_bind_entry(identity_key))}"
        )
    except Exception as exc:
        await _finish_text_reply(bind_hiroba, event, f"Hiroba 绑定失败：{exc}")
        return

    bind_count = len(synced_ids)
    bind_mode_text = (
        f"已按指定太鼓番绑定 Hiroba 账号 {target_taiko_no}。"
        if target_taiko_no
        else f"已自动同步并绑定该 Bandai Namco ID 下的 {bind_count} 个 Hiroba 账号。"
    )
    await _finish_text_reply(
        bind_hiroba,
        event,
        f"{bind_mode_text}\n{reply_msg}\n已在中心保存 Hiroba 凭据，请后续使用“更新hiroba”同步中心成绩。",
        quick_actions=True,
    )

@hiroba_update.handle()
@lifecycle_boundary("hiroba_update", host)
async def hiroba_update_handle(event: MessageEvent):
    plain_text = extract_plain_text(event)
    show_all_match = re.fullmatch(
        r"^(?:hirobaupdate|更新hiroba|更新ひろば)(?:(?:\s+|)(all|全部|全量|-a|--all))?\s*$",
        plain_text.strip(),
        flags=re.IGNORECASE,
    )
    show_all_changes = bool(show_all_match and show_all_match.group(1))
    identity_key, _ = _resolve_requested_identity_key(event)
    bind_info = _get_taiko_bind_info_from_center(identity_key)

    taiko_id = _resolve_bound_taiko_id(event)
    if taiko_id == 404:
        await _finish_text_reply(hiroba_update, event, _taiko_bind_usage_message(event))
        return
    if taiko_id == 403:
        await _finish_text_reply(hiroba_update, event, "查不到呢，可能不给看哦~")
        return
    if bind_info and str(bind_info.get("currentSource") or "wahlap") != "hiroba":
        await _finish_text_reply(
            hiroba_update,
            event,
            _build_update_command_hint(identity_key, expected_source="hiroba"),
        )
        return

    progress = _create_hiroba_progress_reporter(hiroba_update, event)
    await _send_text_reply_without_finish(
        hiroba_update,
        event,
        "开始通过 Hiroba 更新当前绑定账号成绩",
    )
    update_result = await asyncio.to_thread(
        _execute_hiroba_update,
        taiko_id,
        show_all_changes=show_all_changes,
        include_changes_image=True,
        progress=progress,
    )
    if not update_result.get("ok"):
        await _finish_text_reply(
            hiroba_update,
            event,
            str(update_result.get("message") or "Hiroba 更新失败。"),
        )
        return

    img_buf = update_result.get("image")
    success_message = str(update_result.get("message") or "Hiroba 更新成功！")
    if show_all_changes:
        success_message += "\n已展示全部变更。"
    await _finish_hiroba_update_success_reply(
        hiroba_update,
        event,
        success_message=success_message,
        img_buf=img_buf,
        show_all_changes=show_all_changes,
    )

@bind_remove.handle()
@lifecycle_boundary("bind_remove", host)
async def bind_remove_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    plain_text = extract_plain_text(event).strip()
    match = re.match(r"^(删除绑定|解绑)(?:\s*(u[1-9]\d*|[0-9]{5,12}))?$", plain_text)
    target = str(match.group(2) or "").strip() if match else ""

    try:
        ok, msg, needs_confirm = _remove_bind_record(
            identity_key, target, force_last=False, event=event
        )
    except Exception as e:
        await _finish_text_reply(bind_remove, event, f"删除绑定失败：{e}")
        return

    await _finish_text_reply(bind_remove, event, msg)

@bind_remove_confirm.handle()
@lifecycle_boundary("bind_remove_confirm", host)
async def bind_remove_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    session = _get_bind_delete_confirm_session(identity_key)
    if session is None:
        await _finish_text_reply(
            bind_remove_confirm,
            event,
            "当前没有待确认的删除请求，请先发送“删除绑定”或“解绑”。",
        )

    try:
        ok, msg, _ = _remove_bind_record(
            identity_key,
            str(session.get("taiko_id") or "").strip(),
            force_last=True,
            event=event,
        )
    except Exception as e:
        await _finish_text_reply(bind_remove_confirm, event, f"删除绑定失败：{e}")
        return

    await _finish_text_reply(bind_remove_confirm, event, msg)

@show_bind.handle()
@lifecycle_boundary("show_bind", host)
async def show_bind_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    entry = _get_current_bind_entry(identity_key)
    if entry:
        taiko_id = _get_current_bind_taiko_id(entry)
        if taiko_id and _infer_bind_source(
            taiko_id, entry.get("sources") or {}
        ) == "manual":
            try:
                await call_manual_account_api(
                    identity_key,
                    "visibility",
                    settings=_SETTINGS,
                    taikoId=taiko_id,
                    visible=1,
                )
                await _finish_text_reply(show_bind, event, "给看!（手动录入）")
                return
            except ManualAccountApiError as exc:
                await _finish_text_reply(show_bind, event, f"设置失败：{exc}")
                return
    try:
        updated = _set_taiko_bind_visibility(get_identity_key(event=event), 1, event=event)
    except ViewerClientError as error:
        await _finish_text_reply(show_bind, event, str(error))
        return
    if updated == 0:
        await _finish_text_reply(show_bind, event, _taiko_bind_usage_message(event))
    await _finish_text_reply(show_bind, event, "给看!")

@unshow_bind.handle()
@lifecycle_boundary("unshow_bind", host)
async def unshow_bind_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    entry = _get_current_bind_entry(identity_key)
    if entry:
        taiko_id = _get_current_bind_taiko_id(entry)
        if taiko_id and _infer_bind_source(
            taiko_id, entry.get("sources") or {}
        ) == "manual":
            try:
                await call_manual_account_api(
                    identity_key,
                    "visibility",
                    settings=_SETTINGS,
                    taikoId=taiko_id,
                    visible=0,
                )
                await _finish_text_reply(unshow_bind, event, "不给看!（手动录入）")
                return
            except ManualAccountApiError as exc:
                await _finish_text_reply(unshow_bind, event, f"设置失败：{exc}")
                return
    try:
        updated = _set_taiko_bind_visibility(get_identity_key(event=event), 0, event=event)
    except ViewerClientError as error:
        await _finish_text_reply(unshow_bind, event, str(error))
        return
    if updated == 0:
        await _finish_text_reply(unshow_bind, event, _taiko_bind_usage_message(event))
    await _finish_text_reply(unshow_bind, event, "不给看!")
