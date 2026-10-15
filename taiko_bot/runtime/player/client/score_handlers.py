from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import re
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.params import RegexGroup
from .. import entry
from ...public.provider import query_with_mode, resolve, rejected_fuzzy
from .score_data import available_levels_for_song, get_scoreline_entry, parse_scoreline_request, compute_scoreline_result, format_scoreline_message, compute_score
extract_plain_text = entry.helpers.extract_plain_text
_build_fuzzy_query_hint = entry.helpers._build_fuzzy_query_hint
_is_fuzzy_query_result = rejected_fuzzy
_is_rejected_fuzzy_query_result = rejected_fuzzy
_resolve_what_song_query = resolve
queryMusic = lambda query: query_with_mode(query)[0]
_finish_text_reply = entry.helpers._finish_text_reply


async def handle_line(matcher: Matcher, event: Event):
    plain_text = extract_plain_text(event)
    try:
        request = parse_scoreline_request(plain_text)
    except ValueError as e:
        await matcher.finish(str(e))

    try:
        results: List[List[Any]] = queryMusic(request.song_query)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    fuzzy_hint = ""
    if not results:
        await matcher.finish("未找到匹配的歌曲，请检查别名或歌曲id。")
    if _is_fuzzy_query_result(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        await matcher.finish(
            f"匹配结果过多（{len(results)} 条），请提供更精确的歌曲别名或id。"
        )

    song_id = int(results[0][0])
    song_title = str(results[0][1] or "")
    entry = get_scoreline_entry(song_id, request.level, fallback_title=song_title)
    if entry is None:
        available_levels = available_levels_for_song(song_id, fallback_title=song_title)
        if request.level == 3:
            if 4 in available_levels or 5 in available_levels:
                await matcher.finish(
                    "当前分数线数据仅支持表谱/里谱，松谱暂不支持。"
                )
            await matcher.finish("该歌曲暂无松谱分数线数据。")
        if request.level == 4 and 5 in available_levels:
            await matcher.finish(
                f"这首歌暂无表谱分数线数据，可尝试：分数线 里{request.song_query} {request.rating_display} {int(request.speed_ips)}"
            )
        if request.level == 5 and 4 in available_levels:
            await matcher.finish(
                f"这首歌暂无里谱分数线数据，可尝试：分数线 表{request.song_query} {request.rating_display} {int(request.speed_ips)}"
            )
        await matcher.finish("该歌曲暂无该难度分数线数据。")

    try:
        result = compute_scoreline_result(entry, request.rating_key, request.speed_ips)
    except ValueError as e:
        await matcher.finish(str(e))
    except Exception as e:
        await matcher.finish(f"分数线计算失败：{e}")

    body = format_scoreline_message(entry, result, request)
    if fuzzy_hint:
        await matcher.finish(f"{fuzzy_hint}\n{body}")
    await matcher.finish(body)

async def handle_score(
    matcher: Matcher, event: Event,
    groups: Tuple[Optional[str], str, str, str, Optional[str]] = RegexGroup(),
):
    flag, alias, good_s, ok_s, drumroll_s = groups

    # 解析 level：里=5；表/缺省=4
    if flag == "里":
        level = 5
    else:
        level = 4  # flag 为 "表" 或 None

    # 1) 用你的 queryMusic 做别名->id
    try:
        results: List[List] = queryMusic(alias)
    except Exception as e:
        await matcher.finish(f"查询别名时出错：{e}")

    fuzzy_hint = ""
    if not results:
        await matcher.finish("未找到匹配的歌曲，请检查别名。")
    if _is_fuzzy_query_result(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        await matcher.finish(
            f"匹配结果过多（{len(results)} 条），请提供更精确的别名。"
        )

    # 唯一命中：取 id
    song_id = int(results[0][0])
    song_title = results[0][1]

    # 2) 解析数值入参
    try:
        good = int(good_s)
        ok = int(ok_s)
        drumroll = int(drumroll_s) if drumroll_s is not None else 0
    except (TypeError, ValueError):
        await matcher.finish("良/可/连打数必须为非负整数。")

    if good < 0 or ok < 0 or drumroll < 0:
        await matcher.finish("良/可/连打数必须为非负整数。")

    # 3) 计算分数
    try:
        total_score = compute_score(song_id, good, ok, drumroll, level=level)
    except FileNotFoundError as e:
        await matcher.finish(str(e))
    except (KeyError, TypeError, ValueError) as e:
        await matcher.finish(f"分值配置异常：{e}")
    except Exception as e:
        await matcher.finish(f"计算失败：{e}")

    # 4) 输出
    face = "（里谱）" if level == 5 else "（表谱）"
    body = f"歌曲：{song_title}{face}\n良：{good}  可：{ok}  连打：{drumroll}\n总分：{total_score}"
    if fuzzy_hint:
        await matcher.finish(f"{fuzzy_hint}\n{body}")
    else:
        await matcher.finish(body)
