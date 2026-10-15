from __future__ import annotations
from .. import entry
from .nickname_host import prepare_nickname
from ...public.config import root
from ..management_access import queryMusic, rejected_fuzzy, load_song_data
from nonebot.adapters import Event as MessageEvent
from typing import Any
from .display_host_support.custom_title import CUSTOM_TITLE_ACHIEVEMENT_LABELS
from .display_host_support.custom_title import CUSTOM_TITLE_ACHIEVEMENT_STYLES
from .display_host_support.custom_title import CUSTOM_TITLE_COMMAND_PATTERN
from .display_host_support.custom_title import CUSTOM_TITLE_LEVEL_LABELS
from .display_host_support.custom_title import CUSTOM_TITLE_USAGE
from .display_host_support.custom_title import CustomTitleError
from typing import Dict
from .song_title_query import FUZZY_ACCEPT_THRESHOLD
from typing import List
from nonebot.matcher import Matcher
from typing import Optional
from pathlib import Path
from .song_title_query import SONG_TITLE_QUERY_PATTERN
from feature_handler.feature_handler import apply_switch
from .song_title_query import build_rejected_match_suggestions
from .duplicate_versions import collapse_query_results_by_group
from .song_title_query import collect_accepted_song_matches
from .display_host_support.custom_title import create_custom_title
from datetime import datetime
from .song_title_query import find_songs_by_title
from nonebot import get_driver
from .messages import get_group_identifier
from .messages import get_group_key
from .messages import get_identity_key
from .messages import is_qq_official_group_event
import json
from .song_title_query import extract_player_nickname
from .song_title_query import load_song_title_query_entries
from nonebot import logger
from nonebot.plugin import on_regex
from .display_host_support.custom_title import parse_custom_title_command
from .song_title_query import parse_song_title_query
import re
from .song_title_query import render_song_title_query
from .admin_audit import write_admin_action_log
taiko_rule = entry.feature_on("taiko")
_is_rejected_fuzzy_query_result = rejected_fuzzy
_is_fuzzy_query_result = rejected_fuzzy
_build_fuzzy_query_hint = entry.helpers._build_fuzzy_query_hint
_finish_image_reply = entry.helpers._finish_image_reply
extract_plain_text = entry.helpers.extract_plain_text
SONG_DATA_PATH = root() / "songs/song_data.json"

ALIAS_LOG_PATH = root() / "logs/alias_action_log.json"

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


def load_alias_data():
    """读取 song_alias.json（dict 列表）"""
    with open("songs/song_alias.json", "r", encoding="utf-8") as f:
        return json.load(f)

def save_alias_data(data: List[Dict[str, Any]]) -> None:
    with open("songs/song_alias.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_alias_log(entry: Dict[str, Any]) -> None:
    ALIAS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ALIAS_LOG_PATH.exists():
        try:
            with ALIAS_LOG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    else:
        data = []
    data.append(entry)
    with ALIAS_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_song_title_by_id(song_id: str) -> str:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item.get("song_name_jp") or item.get("song_name") or ""
    return ""

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

tsearch_switch = on_regex(
    r"^(?:tsearch\s*(?P<state>on|off)|(?P<switch>开启|关闭)(?:tsearch|太鼓搜歌|太鼓查歌|太鼓是什么歌)功能)$",
    priority=10,
    rule=taiko_rule,
    block=True,
)

song_title_query = on_regex(
    SONG_TITLE_QUERY_PATTERN.pattern,
    flags=re.IGNORECASE,
    priority=10,
    rule=taiko_rule,
    block=True,
)

custom_title_add = on_regex(
    CUSTOM_TITLE_COMMAND_PATTERN.pattern,
    flags=re.IGNORECASE,
    priority=10,
    rule=taiko_rule,
    block=True,
)

tset_alias = on_regex(r"^tset\b.*", priority=10, rule=taiko_rule, block=True)

@tsearch_switch.handle()
async def tsearch_switch_handle(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event).strip().lower()
    m = re.match('^(?:tsearch\\s*(?P<state>on|off)|(?P<switch>开启|关闭)(?:tsearch|太鼓搜歌|太鼓查歌|太鼓是什么歌)功能)$', msg_text)
    if not m:
        await matcher.finish('格式不正确，应为：tsearch on/off 或 开启/关闭太鼓搜歌功能')
    group_scope = await _ensure_group_feature_manage_permission(matcher, event)
    if group_scope is None:
        return
    enabled = m.group('state') == 'on' if m.group('state') else m.group('switch') == '开启'
    group_key = get_group_key(event=event)
    if group_key is None:
        await matcher.finish('该指令仅支持群聊使用。')
    changed = apply_switch(group_key, 'tsearch', enabled)
    state_text = '开启' if enabled else '关闭'
    if changed:
        await matcher.finish(f'太鼓搜歌功能已{state_text}（本群）')
    else:
        await matcher.finish(f'太鼓搜歌功能已是{state_text}状态（本群）')

@song_title_query.handle()
async def song_title_query_handle(matcher: Matcher, event: MessageEvent):
    original_matcher = matcher
    try:
        query = parse_song_title_query(extract_plain_text(event))
        if query is None:
            await matcher.finish('格式不正确，应为：查称号 歌曲名或称号原文')
        try:
            song_results = queryMusic(query)
            title_results = find_songs_by_title(query)
        except Exception as exc:
            await matcher.finish(f'查询歌曲或称号失败：{exc}')
        accepted_songs = collect_accepted_song_matches(song_results, title_results, threshold=FUZZY_ACCEPT_THRESHOLD)
        accepted_songs = {int(row[0]): str(row[1]) for row in collapse_query_results_by_group([[song_id, song_title] for song_id, song_title in accepted_songs.items()])}
        if not accepted_songs:
            suggestions = build_rejected_match_suggestions(song_results, title_results, threshold=FUZZY_ACCEPT_THRESHOLD)
            if suggestions:
                await matcher.finish('你要找的可能是：\n' + '\n'.join(suggestions))
            await matcher.finish('未找到匹配的歌曲或称号。')
        if len(accepted_songs) > 1:
            choices = '\n'.join((f'id{song_id} {song_title}' for song_id, song_title in sorted(accepted_songs.items())))
            await matcher.finish(f'匹配到多个相关歌曲，请进一步指定歌名或 ID：\n{choices}')
        song_id, song_title = next(iter(accepted_songs.items()))
        try:
            official_titles, custom_titles = load_song_title_query_entries(song_id)
            nickname, delivery = prepare_nickname(event, matcher)
            matcher = delivery
            image = render_song_title_query(song_title, song_id, nickname, official_titles, custom_titles)
        except Exception:
            logger.exception('song_title_query_failed song_id=%s', song_id)
            await matcher.finish('称号查询失败，请稍后再试。')
        await _finish_image_reply(matcher, event, image)
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(original_matcher, event, "查不到呢，可能不给看哦~")

@custom_title_add.handle()
async def custom_title_add_handle(matcher: Matcher, event: MessageEvent):
    parsed = parse_custom_title_command(extract_plain_text(event))
    if parsed is None:
        await matcher.finish(CUSTOM_TITLE_USAGE)
    try:
        results = queryMusic(parsed.song_query)
    except Exception as exc:
        await matcher.finish(f'查询歌曲失败：{exc}')
    if not results:
        await matcher.finish('未找到匹配的歌曲。')
    if _is_rejected_fuzzy_query_result(results):
        await matcher.finish(_build_fuzzy_query_hint(results))
    if len(results) > 1:
        choices = '\n'.join((f'id{music[0]} {music[1]}' for music in results))
        await matcher.finish(f'你要找的可能是：\n{choices}')
    song_id = int(results[0][0])
    song_title = str(results[0][1])
    song_meta = next((item for item in load_song_data() if int(item.get('id', 0) or 0) == song_id), None)
    chart_value = song_meta.get(f'level_{parsed.difficulty_level}') if isinstance(song_meta, dict) else None
    if chart_value is None or str(chart_value).strip() in {'', '-'}:
        difficulty = CUSTOM_TITLE_LEVEL_LABELS[parsed.difficulty_level]
        await matcher.finish(f'《{song_title}》没有{difficulty}谱，未添加称号。')
    group_id = _event_group_scope_id(event)
    group_name = _default_group_scope_name(event)
    creator_name = _extract_uploader_nickname(event) or event.get_user_id()
    creator_id = get_identity_key(event=event) or event.get_user_id()
    try:
        record = create_custom_title(title_name=parsed.title_name, song_id=song_id, difficulty_level=parsed.difficulty_level, achievement_type=parsed.achievement_type, song_title=song_title, creator_type='bot-user', creator_id=creator_id, creator_name=creator_name, source='bot-custom-title', group_id=group_id, group_name=group_name, enforce_cooldown=True)
    except CustomTitleError as exc:
        await matcher.finish(str(exc))
    except Exception:
        logger.exception('custom_title_create_failed actor=%s song_id=%s level=%s', creator_id, song_id, parsed.difficulty_level)
        await matcher.finish('称号保存失败，请稍后再试。')
    difficulty = CUSTOM_TITLE_LEVEL_LABELS[record.difficulty_level]
    achievement = CUSTOM_TITLE_ACHIEVEMENT_LABELS[record.achievement_type]
    style = {'silver': '银色', 'gold': '金色', 'rainbow': '彩虹'}[CUSTOM_TITLE_ACHIEVEMENT_STYLES[record.achievement_type]]
    await matcher.finish(f'已添加自定义称号：{record.title_name}\n获得条件：{achievement}《{song_title}》{difficulty}谱\n称号固定显示为{style}样式，不会随更高成绩自动升级。')

@tset_alias.handle()
async def tset_alias_handle(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event)
    m = re.match('^tset\\s*(.+?)\\s*to\\s*(.+)$', msg_text, flags=re.IGNORECASE)
    if not m:
        await matcher.finish('格式好像有问题捏，格式：tsetxxx to xxx')
    alias_to_add = m.group(1).strip()
    target_key = m.group(2).strip()
    if not alias_to_add or not target_key:
        await matcher.finish('格式好像有问题捏，格式：tsetxxx to xxx')
    try:
        results = queryMusic(target_key)
    except Exception as e:
        await matcher.finish(f'查询歌曲失败：{e}')
    if not results:
        await matcher.finish('未找到匹配的歌曲。')
    if _is_rejected_fuzzy_query_result(results):
        await matcher.finish(_build_fuzzy_query_hint(results))
    if len(results) > 1:
        msg = '你要找的可能是：\n'
        for music in results:
            msg += f'id{music[0]} {music[1]}\n'
        await matcher.finish(msg.strip())
    song_id = str(results[0][0])
    song_title = results[0][1]
    alias_data = load_alias_data()
    target_entry = None
    for entry in alias_data:
        if str(entry.get('id')) == song_id:
            target_entry = entry
            break
    if target_entry is None:
        title = get_song_title_by_id(song_id) or song_title
        target_entry = {'id': int(song_id), 'aliases': [], 'song_name_jp': title}
        alias_data.append(target_entry)
    aliases = target_entry.get('aliases') or []
    existing_lower = {str(a).lower() for a in aliases}
    base_title = (target_entry.get('song_name_jp') or song_title or '').lower()
    if alias_to_add.lower() in existing_lower or alias_to_add.lower() == base_title:
        await matcher.finish('该别名已存在，无需重复添加。')
    aliases.append(alias_to_add)
    target_entry['aliases'] = aliases
    try:
        save_alias_data(alias_data)
    except Exception as e:
        await matcher.finish(f'保存失败：{e}')
    group_scope = _event_group_scope_id(event)
    group_text = group_scope or 'private'
    user_nickname = _extract_uploader_nickname(event)
    group_name = _default_group_scope_name(event)
    logger.info('alias_add user_id=%s user_nickname=%s group_id=%s group_name=%s song_id=%s alias=%s', event.get_user_id(), user_nickname, group_text, group_name, song_id, alias_to_add)
    try:
        append_alias_log({'time': datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'action': 'add_alias', 'user_id': event.get_user_id(), 'user_nickname': user_nickname, 'group_id': group_text if group_scope is not None else None, 'group_name': group_name, 'song_id': song_id, 'song_title': song_title, 'alias': alias_to_add})
    except Exception as e:
        logger.warning('alias_add_log_failed error=%s', e)
    try:
        write_admin_action_log(actor_type='bot-user', actor_id=event.get_user_id(), actor_name=user_nickname or event.get_user_id(), source='bot-tset', target_type='song-alias', target_key=f'{song_id}:{alias_to_add}', action='create', after={'song_id': song_id, 'song_title': song_title, 'alias': alias_to_add}, extra={'group_id': group_text if group_scope is not None else None, 'group_name': group_name, 'legacy_log': True})
    except Exception as e:
        logger.warning('admin_alias_audit_failed error=%s', e)
    await matcher.finish(f'已添加别名：{alias_to_add} -> {song_title} (id{song_id})')
