"""The six public song entries owned by Taiko; no host plugin imports."""
import re
from typing import List
from nonebot import on_regex
from nonebot.adapters import Event as MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import RegexMatched
from feature_handler.feature_handler import feature_on
from taiko_application.commands import CommandResult
from .config import profile, root
from . import provider
from .delivery import reply, deliver, transport
from .alias_renderer import render_alias_image
from .public_queries import find_by_volume, format_position_reply, _strip_song_query_diff_prefix, _build_fuzzy_query_hint

DIFF_MAP = {
    "里": "InnerOni",
    "鬼": "Oni",
    "表": "Oni",
    "魔王": "Oni",
    "松": "Muzukashii",
    "困难": "Muzukashii",
    "竹": "Futsuu",
    "一般": "Futsuu",
    "梅": "Kantan",
    "简单": "Kantan",
}

taiko_rule = feature_on("taiko")
tsearch_rule = feature_on("tsearch")

def extract_plain_text(event):
    return transport().extract_plain_text(event)

def _is_external_bot_mentioned(event):
    return not transport().is_qq_official_event(event) and any(
        seg.type == "at" and seg.data.get("qq") == "3889003795" for seg in event.get_message())

def queryMusic(query):
    return provider.query_with_mode(query)[0]

async def _finish_text_reply(matcher, event, text):
    await reply(matcher, event, text)

async def _finish_image_reply(matcher, event, image, prefix_text=""):
    await reply(matcher, event, prefix_text, image)

async def _send_fumen_or_hint(matcher, event, difficulty, song_id):
    await deliver(matcher, event, CommandResult("fumen", (difficulty, song_id)))

ALIAS_QUERY_REGEX = re.compile(r"^(?P<q>.+?)有什么别名[？?]?$")

SONG_WHERE_REGEX = re.compile(r"^(?P<q>.+?)歌在哪[？?]?$")

SONG_POSITION_REGEX = re.compile(r"^(?P<q>.+?)在什么位置[？?]?$")

SONG_POS_BY_ID_REGEX = re.compile(r"^位置\s*(?:id)?\s*(?P<id>\d+)\s*[？?]?$")

DIFF_BY_ID_REGEX = re.compile(
    r"^(?P<diff>里|鬼|表|松|竹|梅|简单|一般|困难|魔王)\s*(?:id)?\s*(?P<id>\d+)\s*[？?]?$"
)

note_count = on_regex(r"^太鼓查物量\s?(\d+)\s*", rule=taiko_rule)

@note_count.handle()
async def note_count_handle(event: MessageEvent, match=RegexMatched()):
    number = match.group(1)
    nc_data = provider.note_counts()
    res = find_by_volume(nc_data, int(number), "total")
    if len(res) != 0:
        msg = f"以下为对应物量的谱面：(共{len(res)}条)\n"
        if len(res) > 20:
            msg += f"仅显示前20条：\n"
            res = res[:20]
    else:
        msg = "没有找到对应物量的谱面。"
    for title, course in res:
        msg += f"{title} {course}\n"
    await _finish_text_reply(note_count, event, msg)

alias_query = on_regex(
    ALIAS_QUERY_REGEX.pattern, priority=10, rule=taiko_rule & tsearch_rule, block=True
)

@alias_query.handle()
async def _(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = ALIAS_QUERY_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx有什么别名")

    q = m.group("q").strip()
    if not q:
        await matcher.finish("请提供歌曲名或别名")

    try:
        results = queryMusic(q)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    fuzzy_hint = ""
    if not results:
        await matcher.finish("未找到匹配的歌曲。")
    if provider.rejected_fuzzy(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        msg = "你要找的可能是：\n"
        for music in results:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg.strip())

    song_id = str(results[0][0])
    song_title = results[0][1]
    alias_title, aliases = provider.aliases(song_id)
    show_title = alias_title or song_title

    cleaned: List[str] = []
    seen = set()
    for a in aliases:
        if not a:
            continue
        if a in seen:
            continue
        seen.add(a)
        cleaned.append(a)

    ok, error = provider.alias_assets_ready()
    if not ok:
        await _finish_text_reply(matcher, event, error)
        return
    img_buf = render_alias_image(show_title, song_id, cleaned, str(root()/"assets/fonts/DDFont.ttf"))
    if fuzzy_hint:
        await _finish_image_reply(matcher, event, img_buf, prefix_text=fuzzy_hint)
    else:
        await _finish_image_reply(matcher, event, img_buf)

async def _finish_song_position_by_id(
    matcher: Matcher, event: MessageEvent, song_id: int, prefix_text: str = ""
) -> None:
    result = provider.position(song_id)
    if not result:
        await matcher.finish(f"未找到 id{song_id} 的歌曲信息。")
    reply = format_position_reply(result)
    if prefix_text:
        reply = f"{prefix_text}\n{reply}"
    await _finish_text_reply(matcher, event, reply)

async def _finish_song_position_by_name(
    matcher: Matcher, event: MessageEvent, raw_q: str
) -> None:
    stripped_q = _strip_song_query_diff_prefix(raw_q)
    try:
        results = provider.resolve(raw_q, stripped_q)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    if not results:
        await matcher.finish("未找到匹配的歌曲。")
    if provider.rejected_fuzzy(results):
        if profile() == "client":
            await matcher.finish(_build_fuzzy_query_hint(results))
        await _finish_song_position_by_id(
            matcher,
            event,
            int(results[0][0]),
            prefix_text=_build_fuzzy_query_hint(results),
        )
        return
    if len(results) > 1:
        msg = "你要找的可能是：\n"
        for music in results:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg.strip())

    song_id = int(results[0][0])
    await _finish_song_position_by_id(matcher, event, song_id)

song_where = on_regex(
    SONG_WHERE_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)

song_position_phrase = on_regex(
    SONG_POSITION_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)

song_pos_by_id = on_regex(
    SONG_POS_BY_ID_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)

@song_where.handle()
async def song_where_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_WHERE_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx在哪")
    raw_q = (m.group("q") or "").strip()
    if not raw_q:
        await matcher.finish("请提供歌曲名或别名，例如：千本桜在哪")
    await _finish_song_position_by_name(matcher, event, raw_q)

@song_position_phrase.handle()
async def song_position_phrase_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_POSITION_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx在什么位置")
    raw_q = (m.group("q") or "").strip()
    if not raw_q:
        await matcher.finish("请提供歌曲名或别名，例如：千本桜在什么位置")
    await _finish_song_position_by_name(matcher, event, raw_q)

@song_pos_by_id.handle()
async def song_pos_by_id_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_POS_BY_ID_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：位置 id1156")
    song_id = int(m.group("id"))
    await _finish_song_position_by_id(matcher, event, song_id)

diff_by_id = on_regex(
    DIFF_BY_ID_REGEX.pattern,
    priority=10,
    block=True,
    rule=taiko_rule & tsearch_rule,
)

@diff_by_id.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = extract_plain_text(event)
    m = DIFF_BY_ID_REGEX.match(msg)
    if not m:
        await matcher.finish(
            "格式不正确，应为：里/鬼/表/松/竹/梅/简单/一般/困难/魔王 idxxxx（例如：里 id1234）"
        )

    diff_alias = m.group("diff")
    song_id = m.group("id")

    difficulty = DIFF_MAP.get(diff_alias)
    if not difficulty:
        await matcher.finish(f"未知难度标记：{diff_alias}")

    await _send_fumen_or_hint(matcher, event, difficulty, song_id)
