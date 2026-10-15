from __future__ import annotations

from .lifecycle_host import (BIND_DELETE_CONFIRM_TIMEOUT_SECONDS, Dict, MANUAL_DELETE_CONFIRM_SESSIONS, MANUAL_SCORE_DELETE_CONFIRM_SESSIONS, ManualAccountApiError, MessageEvent, RegexMatched, _finish_text_reply, _format_current_bind_summary_safe, _manual_command_tokens, _manual_diff_level, _normalize_identity_key, _parse_manual_score_lookup, _resolve_manual_slot_taiko_id, _resolve_manual_song, call_manual_account_api, extract_plain_text, get_identity_key, on_fullmatch, on_regex, taiko_rule, time)
from . import lifecycle_host as host
from ..lifecycle_authority import manual_boundary, manual_call, manual_finish
_manual_api = call_manual_account_api
_text_reply = _finish_text_reply
async def call_manual_account_api(*args, **kwargs):
    return await manual_call(_manual_api, *args, **kwargs)
async def _finish_text_reply(*args, **kwargs):
    return await manual_finish(_text_reply, *args, **kwargs)


manual_create = on_regex(r"^新增空白账号(?:\s+(.+))?\s*$", rule=taiko_rule)

manual_rename = on_regex(r"^空白账号改名\s+(.+?)\s*$", rule=taiko_rule)

manual_claim_code = on_regex(r"^生成认领码(?:\s+(u[1-9]\d*))?\s*$", rule=taiko_rule)

manual_claim = on_regex(r"^认领空白账号\s+([A-Za-z0-9-]+)\s*$", rule=taiko_rule)

manual_detach = on_regex(r"^解绑空白账号(?:\s+(u[1-9]\d*))?\s*$", rule=taiko_rule)

manual_delete = on_regex(r"^永久删除空白账号(?:\s+(u[1-9]\d*))?\s*$", rule=taiko_rule)

manual_delete_confirm = on_fullmatch("确认永久删除空白账号", rule=taiko_rule)

manual_score_upsert = on_regex(r"^录入成绩\s+.+$", rule=taiko_rule)

manual_score_get = on_regex(r"^查看成绩\s+.+$", rule=taiko_rule)

manual_score_delete = on_regex(r"^删除成绩\s+.+$", rule=taiko_rule)

manual_score_delete_confirm = on_fullmatch("确认删除成绩", rule=taiko_rule)

@manual_create.handle()
@manual_boundary("manual_create", host)
async def manual_create_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    nickname = str((match.group(1) if match else "") or "").strip() or "我的手动成绩"
    try:
        result = await call_manual_account_api(identity_key, "create", nickname=nickname)
        await _finish_text_reply(
            manual_create,
            event,
            f"已新增空白账号“{result.get('nickname') or nickname}”并切换为当前账号。\n"
            f"当前绑定：{_format_current_bind_summary_safe(identity_key)}\n"
            "该账号仅保存手动录入成绩，不关联鼓众广场或 Hiroba。",
        )
    except ManualAccountApiError as exc:
        await _finish_text_reply(manual_create, event, f"新增失败：{exc}")

@manual_rename.handle()
@manual_boundary("manual_rename", host)
async def manual_rename_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        taiko_id, _ = _resolve_manual_slot_taiko_id(identity_key)
        nickname = str(match.group(1) or "").strip()
        result = await call_manual_account_api(
            identity_key, "rename", taikoId=taiko_id, nickname=nickname
        )
        await _finish_text_reply(
            manual_rename, event, f"手动账号已改名为“{result.get('nickname')}”。"
        )
    except (ValueError, ManualAccountApiError) as exc:
        await _finish_text_reply(manual_rename, event, f"改名失败：{exc}")

@manual_claim_code.handle()
@manual_boundary("manual_claim_code", host)
async def manual_claim_code_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        taiko_id, _ = _resolve_manual_slot_taiko_id(
            identity_key, str((match.group(1) if match else "") or "")
        )
        result = await call_manual_account_api(
            identity_key, "claim-code", taikoId=taiko_id
        )
        await _finish_text_reply(
            manual_claim_code,
            event,
            f"一次性认领码：{result.get('code')}\n"
            "10 分钟内有效且只能使用一次；可在 viewer 个人档案中输入，或由另一 bot 身份发送“认领空白账号 认领码”。",
        )
    except (ValueError, ManualAccountApiError) as exc:
        await _finish_text_reply(manual_claim_code, event, f"生成失败：{exc}")

@manual_claim.handle()
@manual_boundary("manual_claim", host)
async def manual_claim_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    code = str(match.group(1) or "").strip()
    try:
        result = await call_manual_account_api(identity_key, "claim", code=code)
        await _finish_text_reply(
            manual_claim,
            event,
            f"已认领手动账号“{result.get('nickname')}”并切换为当前账号。\n"
            f"当前绑定：{_format_current_bind_summary_safe(identity_key)}",
        )
    except ManualAccountApiError as exc:
        await _finish_text_reply(manual_claim, event, f"认领失败：{exc}")

@manual_detach.handle()
@manual_boundary("manual_detach", host)
async def manual_detach_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        taiko_id, _ = _resolve_manual_slot_taiko_id(
            identity_key, str((match.group(1) if match else "") or "")
        )
        await call_manual_account_api(identity_key, "detach", taikoId=taiko_id)
        await _finish_text_reply(
            manual_detach,
            event,
            "已从当前 bot 身份解绑，另一端和成绩仍然保留。\n"
            f"当前绑定：{_format_current_bind_summary_safe(identity_key)}",
        )
    except (ValueError, ManualAccountApiError) as exc:
        await _finish_text_reply(manual_detach, event, f"解绑失败：{exc}")

@manual_delete.handle()
@manual_boundary("manual_delete", host)
async def manual_delete_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        taiko_id, slot = _resolve_manual_slot_taiko_id(
            identity_key, str((match.group(1) if match else "") or "")
        )
        MANUAL_DELETE_CONFIRM_SESSIONS[identity_key] = {
            "taiko_id": taiko_id,
            "expires_at": time.time() + BIND_DELETE_CONFIRM_TIMEOUT_SECONDS,
        }
        await _finish_text_reply(
            manual_delete,
            event,
            f"即将永久删除 u{slot} 手动账号及全部成绩历史。\n"
            f"请在 {BIND_DELETE_CONFIRM_TIMEOUT_SECONDS // 60} 分钟内发送“确认永久删除空白账号”。",
        )
    except ValueError as exc:
        await _finish_text_reply(manual_delete, event, str(exc))

@manual_delete_confirm.handle()
@manual_boundary("manual_delete_confirm", host)
async def manual_delete_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    session = MANUAL_DELETE_CONFIRM_SESSIONS.get(identity_key)
    if not session or float(session.get("expires_at", 0)) < time.time():
        MANUAL_DELETE_CONFIRM_SESSIONS.pop(identity_key, None)
        await _finish_text_reply(
            manual_delete_confirm, event, "没有待确认的永久删除操作，或确认已过期。"
        )
        return
    try:
        await call_manual_account_api(
            identity_key,
            "delete-account",
            taikoId=session["taiko_id"],
            confirmed=True,
        )
        MANUAL_DELETE_CONFIRM_SESSIONS.pop(identity_key, None)
        await _finish_text_reply(
            manual_delete_confirm,
            event,
            "手动账号已永久删除；服务端已留下带时间戳的恢复备份。",
        )
    except ManualAccountApiError as exc:
        await _finish_text_reply(manual_delete_confirm, event, f"删除失败：{exc}")

@manual_score_upsert.handle()
@manual_boundary("manual_score_upsert", host)
async def manual_score_upsert_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    text = extract_plain_text(event).strip()
    try:
        tokens = _manual_command_tokens(text, "录入成绩")
        if len(tokens) < 6:
            raise ValueError(
                "格式：录入成绩 <歌曲ID或曲名> <难度> <分数> <良> <可> <不可> [连打=n] [连击=n] [评价=n] [游玩=n] [通关=n] [全连=n] [全良=n]"
            )
        option_tokens = tokens[6:]
        options: Dict[str, str] = {}
        for token in option_tokens:
            if "=" not in token:
                raise ValueError(f"可选参数“{token}”需要使用 名称=数值。")
            key, value = token.split("=", 1)
            options[key.strip()] = value.strip()
        song_no, title = _resolve_manual_song(tokens[0], options.get("曲名", ""))
        level = _manual_diff_level(tokens[1])
        positional_keys = ["high_score", "good_cnt", "ok_cnt", "ng_cnt"]
        values = {key: int(value) for key, value in zip(positional_keys, tokens[2:6])}
        option_map = {
            "连打": "pound_cnt",
            "连击": "combo_cnt",
            "评价": "best_score_rank",
            "游玩": "stage_cnt",
            "通关": "clear_cnt",
            "全连": "full_combo_cnt",
            "全良": "dondaful_combo_cnt",
        }
        for key, field in option_map.items():
            if key in options:
                values[field] = int(options[key])
        taiko_id, slot = _resolve_manual_slot_taiko_id(identity_key)
        result = await call_manual_account_api(
            identity_key,
            "score-upsert",
            taikoId=taiko_id,
            songNo=song_no,
            level=level,
            title=title,
            values=values,
        )
        verb = "新增" if result.get("created") else "更新"
        await _finish_text_reply(
            manual_score_upsert,
            event,
            f"已{verb} u{slot} 的手动成绩：{title or f'ID {song_no}'} · "
            f"{['', '简单', '一般', '困难', '魔王', '里谱'][level]} · {values['high_score']} 分\n"
            "来源：手动录入（不进入官方排行或认证统计）",
        )
    except (ValueError, ManualAccountApiError) as exc:
        await _finish_text_reply(manual_score_upsert, event, f"录入失败：{exc}")

@manual_score_get.handle()
@manual_boundary("manual_score_get", host)
async def manual_score_get_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        _, level, title, song_no = _parse_manual_score_lookup(
            extract_plain_text(event).strip(), "查看成绩"
        )
        taiko_id, slot = _resolve_manual_slot_taiko_id(identity_key)
        result = await call_manual_account_api(
            identity_key,
            "score-get",
            taikoId=taiko_id,
            songNo=song_no,
            level=level,
        )
        item = result.get("item") or {}
        await _finish_text_reply(
            manual_score_get,
            event,
            f"u{slot} · {title or item.get('song_name') or f'ID {song_no}'} · "
            f"{['', '简单', '一般', '困难', '魔王', '里谱'][level]}\n"
            f"分数 {item.get('high_score', 0)}｜良 {item.get('good_cnt', 0)}｜"
            f"可 {item.get('ok_cnt', 0)}｜不可 {item.get('ng_cnt', 0)}｜"
            f"连击 {item.get('combo_cnt', 0)}\n"
            "来源：手动录入（不进入官方排行或认证统计）",
        )
    except (ValueError, ManualAccountApiError) as exc:
        await _finish_text_reply(manual_score_get, event, f"查询失败：{exc}")

@manual_score_delete.handle()
@manual_boundary("manual_score_delete", host)
async def manual_score_delete_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        _, level, title, song_no = _parse_manual_score_lookup(
            extract_plain_text(event).strip(), "删除成绩"
        )
        taiko_id, slot = _resolve_manual_slot_taiko_id(identity_key)
        MANUAL_SCORE_DELETE_CONFIRM_SESSIONS[identity_key] = {
            "taiko_id": taiko_id,
            "song_no": song_no,
            "level": level,
            "expires_at": time.time() + BIND_DELETE_CONFIRM_TIMEOUT_SECONDS,
        }
        await _finish_text_reply(
            manual_score_delete,
            event,
            f"即将删除 u{slot} 的手动成绩：{title or f'ID {song_no}'}。\n"
            f"请在 {BIND_DELETE_CONFIRM_TIMEOUT_SECONDS // 60} 分钟内发送“确认删除成绩”。",
        )
    except ValueError as exc:
        await _finish_text_reply(manual_score_delete, event, str(exc))

@manual_score_delete_confirm.handle()
@manual_boundary("manual_score_delete_confirm", host)
async def manual_score_delete_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    session = MANUAL_SCORE_DELETE_CONFIRM_SESSIONS.get(identity_key)
    if not session or float(session.get("expires_at", 0)) < time.time():
        MANUAL_SCORE_DELETE_CONFIRM_SESSIONS.pop(identity_key, None)
        await _finish_text_reply(
            manual_score_delete_confirm, event, "没有待确认的成绩删除操作，或确认已过期。"
        )
        return
    try:
        await call_manual_account_api(
            identity_key,
            "score-delete",
            taikoId=session["taiko_id"],
            songNo=session["song_no"],
            level=session["level"],
            confirmed=True,
        )
        MANUAL_SCORE_DELETE_CONFIRM_SESSIONS.pop(identity_key, None)
        await _finish_text_reply(
            manual_score_delete_confirm, event, "手动成绩已删除，成就统计和历史已重算。"
        )
    except ManualAccountApiError as exc:
        await _finish_text_reply(manual_score_delete_confirm, event, f"删除失败：{exc}")
