"""Public catalog entries; simulated score remains host-owned due to refresh IO."""
from typing import List, Set
from nonebot import on_regex
from nonebot.adapters import Event as MessageEvent
from nonebot.params import RegexMatched
from feature_handler.feature_handler import feature_on
from taiko_application.commands import CommandContext, ConstantPorts, execute_constant
from .config import profile
from .delivery import reply
from . import provider, catalog_provider
from .pattern_query import _parse_chart_config_query, _parse_chart_config_bpm_range, _collect_chart_config_bpm_ids, _collect_chart_config_level_ids, _resolve_chart_config_song_name, _sample_chart_config_items

patterns = on_regex(r"^/?查配置(?:\s*.+)?$", rule=feature_on('taiko'))
const_query = on_regex(r"^/?查定数\s*(\d+\.\d)(?:\s+(.+))?\s*$", rule=feature_on('taiko'), block=True)

async def _finish_text_reply(matcher, event, text):
    await reply(matcher, event, text)

@const_query.handle()
async def const_query_handle(event: MessageEvent, match=RegexMatched()):
    if profile() == 'client':
        ok, error = provider.alias_assets_ready()
        if not ok:
            await reply(const_query, event, error)
            return
    renderer = catalog_provider.renderer()
    ports = ConstantPorts(25, catalog_provider.paginate_rows,
        catalog_provider.query_charts_by_const, renderer.render_const_query_image,
        renderer.render_const_query_notice)
    result = execute_constant(CommandContext(profile=profile(), match=match), ports)
    if result.kind == 'image':
        await reply(const_query, event, result.prefix_text, result.payload)
    else:
        await reply(const_query, event, result.payload)

@patterns.handle()
async def music_info_handle(event: MessageEvent):
    level_map = {
        "松": "ard",
        "竹": "mal",
        "梅": "asy",
    }
    letter_map = {
        "Edit": "里谱",
        "Oni": "魔王",
        "Hard": "困难",
        "Normal": "一般",
        "Easy": "简单",
    }

    parsed_query = _parse_chart_config_query(str(event.get_message()).strip())
    if not parsed_query:
        await _finish_text_reply(
            patterns,
            event,
            "格式不正确，应为：查配置 [分音符] 配置 [BPM] [难度]；省略分音符时默认按16分，也可仅输入 BPM 或 BPM+难度。",
        )

    bpm_range = _parse_chart_config_bpm_range(parsed_query.get("bpm_str"))
    pattern_data = catalog_provider.pattern_data()
    by_bpm = pattern_data["by_bpm"]
    by_level = pattern_data["by_level"]
    by_tag = pattern_data["by_tag"]
    song_meta = pattern_data["song_meta"]

    def format_items(ids: List[str]) -> List[str]:
        out = []
        for song_id in ids:
            title, course = song_id.split("||", 1)
            out.append(
                f"{_resolve_chart_config_song_name(song_meta, title)} {letter_map.get(course, course)}"
            )
        return out

    if parsed_query["mode"] == "bpm_only":
        bpm_ids = _collect_chart_config_bpm_ids(by_bpm, bpm_range)
        if not bpm_ids:
            await _finish_text_reply(patterns, event, "未找到满足该 BPM 条件的歌曲。")

        song_names = sorted(
            {
                _resolve_chart_config_song_name(song_meta, song_id.split("||", 1)[0])
                for song_id in bpm_ids
            }
        )
        song_count = len(song_names)
        song_show = _sample_chart_config_items(song_names, 10)

        msg_lines = ["为您找到以下歌曲：", f"【BPM匹配】{song_count} 首"]
        if song_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(song_show)
        await _finish_text_reply(patterns, event, "\n".join(msg_lines))
    if parsed_query["mode"] == "bpm_level_only":
        level = parsed_query["level"]
        bpm_ids = _collect_chart_config_bpm_ids(by_bpm, bpm_range)
        level_ids = _collect_chart_config_level_ids(by_level, level, level_map)
        matched_ids = list(bpm_ids & level_ids)
        if not matched_ids:
            await _finish_text_reply(
                patterns, event, "未找到满足该 BPM 和难度条件的谱面。"
            )

        match_count = len(matched_ids)
        match_show = _sample_chart_config_items(matched_ids, 10)
        msg_lines = ["为您找到以下谱面：", f"【BPM+难度匹配】{match_count} 条"]
        if match_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(match_show))
        await _finish_text_reply(patterns, event, "\n".join(msg_lines))

    division = parsed_query["division"]
    pattern_name = parsed_query["pattern_name"]
    level = parsed_query.get("level")
    dp = f"{division} {pattern_name}"

    # ---------- 1) 获取“精确命中集合” ----------
    exact_list = by_tag.get(dp, [])
    exact_set = set(exact_list)

    # ---------- 2) 若输入长度>=6，获取“子串命中集合”（同division下的 tag key 做包含判断） ----------
    substr_set = set()
    if len(pattern_name) >= 6:
        prefix = f"{division} "
        for tag_key, ids in by_tag.items():
            if not tag_key.startswith(prefix):
                continue
            long_pat = tag_key[len(prefix) :].lower()
            if pattern_name in long_pat:
                substr_set.update(ids)

        # 子串集合里去掉已经在精确集合中的部分，避免重复计入“子串命中”
        substr_set -= exact_set

    if not exact_set and not substr_set:
        await _finish_text_reply(patterns, event, "未找到匹配的谱面")

    # ---------- 3) BPM / 难度过滤函数（复用） ----------
    def apply_filters(song_ids: Set[str]) -> List[str]:
        if not song_ids:
            return []

        filtered = set(song_ids)

        if bpm_range:
            filtered &= _collect_chart_config_bpm_ids(by_bpm, bpm_range)

        if level:
            filtered &= _collect_chart_config_level_ids(by_level, level, level_map)

        return list(filtered)

    exact_res = apply_filters(exact_set)
    substr_res = apply_filters(substr_set)

    if not exact_res and not substr_res:
        await _finish_text_reply(patterns, event, "未找到满足该条件的谱面。")

    exact_count = len(exact_res)
    substr_count = len(substr_res)
    exact_show = _sample_chart_config_items(exact_res, 10)
    substr_show = _sample_chart_config_items(substr_res, 10)

    msg_lines = ["为您找到以下谱面："]

    if exact_count > 0:
        msg_lines.append(f"\n【精确匹配】{exact_count} 条")
        if exact_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(exact_show))

    if len(pattern_name) >= 6 and substr_count > 0:
        msg_lines.append(f"\n【子串匹配】{substr_count} 条")
        if substr_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(substr_show))

    await _finish_text_reply(patterns, event, "\n".join(msg_lines))
