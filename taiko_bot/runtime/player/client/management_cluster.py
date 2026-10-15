from __future__ import annotations
from .. import entry
from ...public.config import root
from ..management_access import queryMusic, rejected_fuzzy, load_song_data
from nonebot.adapters import Event as MessageEvent
from typing import Any
from typing import Dict
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN
from nonebot.adapters.onebot.v11.permission import GROUP_OWNER
from typing import List
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from feature_handler.feature_handler import apply_switch
from datetime import datetime
from .messages import get_group_key
from taiko_bot.settings import get_settings
from sakura_taiko_core.chart.visibility import is_song_publicly_visible
import json
from nonebot import logger
from nonebot.plugin import on_regex
import re
taiko_rule = entry.feature_on("taiko")
_is_rejected_fuzzy_query_result = rejected_fuzzy
_is_fuzzy_query_result = rejected_fuzzy
_build_fuzzy_query_hint = entry.helpers._build_fuzzy_query_hint
extract_plain_text = entry.helpers.extract_plain_text
_SETTINGS = get_settings()

ROOT_DIR = _SETTINGS.root_dir

SONGS_DIR = ROOT_DIR / "songs"

SONG_DATA_PATH = SONGS_DIR / "song_data.json"

ALIAS_LOG_PATH = ROOT_DIR / "logs" / "alias_action_log.json"


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

tsearch_switch = on_regex(
    r"^tsearch\s*(?P<state>on|off)$",
    priority=10,
    rule=taiko_rule,
    permission=SUPERUSER | GROUP_ADMIN | GROUP_OWNER,
    block=True,
)

tset_alias = on_regex(r"^tset\b.*", priority=10, rule=taiko_rule, block=True)

@tsearch_switch.handle()
async def tsearch_switch_handle(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event).strip().lower()
    m = re.match('^tsearch\\s*(?P<state>on|off)$', msg_text)
    if not m:
        await matcher.finish('格式不正确，应为：tsearch on/off')
    group_id = getattr(event, 'group_id', None)
    if group_id is None:
        await matcher.finish('该指令仅支持群聊使用。')
    enabled = m.group('state') == 'on'
    group_key = get_group_key(event=event)
    if group_key is None:
        await matcher.finish('该指令仅支持群聊使用。')
    changed = apply_switch(group_key, 'tsearch', enabled)
    state_text = '开启' if enabled else '关闭'
    if changed:
        await matcher.finish(f'tsearch 已{state_text}（本群）')
    else:
        await matcher.finish(f'tsearch 已是{state_text}状态（本群）')

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
    if _is_fuzzy_query_result(results):
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
    group_id = getattr(event, 'group_id', None)
    group_text = str(group_id) if group_id is not None else 'private'
    user_nickname = ''
    group_name = ''
    if hasattr(event, 'sender') and event.sender:
        user_nickname = getattr(event.sender, 'nickname', '') or ''
    if group_id is not None:
        group_name = getattr(event, 'group_name', '') or ''
    logger.info('alias_add user_id=%s user_nickname=%s group_id=%s group_name=%s song_id=%s alias=%s', event.get_user_id(), user_nickname, group_text, group_name, song_id, alias_to_add)
    try:
        append_alias_log({'time': datetime.utcnow().isoformat(timespec='seconds') + 'Z', 'action': 'add_alias', 'user_id': event.get_user_id(), 'user_nickname': user_nickname, 'group_id': group_id, 'group_name': group_name, 'song_id': song_id, 'song_title': song_title, 'alias': alias_to_add})
    except Exception as e:
        logger.warning('alias_add_log_failed error=%s', e)
    await matcher.finish(f'已添加别名：{alias_to_add} -> {song_title} (id{song_id})')
