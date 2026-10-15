from __future__ import annotations
from .. import entry
from .. import query_access
from taiko_application.private_input import thaw
from nonebot.matcher import Matcher
from .summary_host import render_summary
from ...public.config import root
from ..management_access import queryMusic, rejected_fuzzy, load_song_data
from nonebot.adapters import Event as MessageEvent
from typing import Any
from nonebot.adapters import Bot
from io import BytesIO
from .arcade_map import CityShopQueryResult
from typing import Dict
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from typing import List
from nonebot.adapters.onebot.v11 import MessageSegment
from typing import Optional
from typing import Tuple
from taiko_bot.viewer_client import ViewerClientError
from .arcade_map import build_tencent_map_location_json
from taiko_bot.viewer_client import fetch_wahlap_ranking
from .twso import find_player
from .arcade_map import format_city_shop_forward_nickname
from .arcade_map import format_taiko_city_shop_entry
from .arcade_map import format_taiko_city_shop_reply
from .arcade_map import format_taiko_city_shop_summary
from taiko_bot.settings import get_settings
from .messages import is_qq_official_event
from sakura_taiko_core.chart.visibility import is_song_publicly_visible
import json
from nonebot import logger
from nonebot.plugin import on_fullmatch
from nonebot.plugin import on_regex
from .arcade_map import query_taiko_shops_by_city
import re
from .messages import send_onebot_forward_messages
taiko_rule = entry.feature_on("taiko")
_is_rejected_fuzzy_query_result = rejected_fuzzy
_is_fuzzy_query_result = rejected_fuzzy
_build_fuzzy_query_hint = entry.helpers._build_fuzzy_query_hint
_ensure_asset_resources_ready = query_access.ensure_assets
_finish_image_reply = entry.helpers._finish_image_reply
_finish_text_reply = entry.helpers._finish_text_reply
_taiko_bind_usage_message = entry.helpers._taiko_bind_usage_message
_to_jpeg_bytes = entry.helpers._to_jpeg_bytes
extract_plain_text = entry.helpers.extract_plain_text
_SETTINGS = get_settings()

ROOT_DIR = _SETTINGS.root_dir

SONGS_DIR = ROOT_DIR / "songs"

SONG_DATA_PATH = SONGS_DIR / "song_data.json"

SONG_RANK_FONT_PATH = "/usr/share/fonts/NotoSansCJKSC-Black.ttf"

REGION_MAP_PATH = SONGS_DIR / "region_map.json"

CITY_ARCADE_QUERY_REGEX = re.compile(r"^(?P<city>.+?)(?:哪有鼓|哪里有鼓)\s*[？?]?$")

RANK_DIFF_INPUT_MAP = {
    "简单": 1,
    "梅": 1,
    "一般": 2,
    "竹": 2,
    "困难": 3,
    "松": 3,
    "魔王": 4,
    "鬼": 4,
    "里魔王": 5,
    "里谱": 5,
    "里": 5,
}

RANK_DIFF_LABEL_MAP = {
    1: "简单",
    2: "一般",
    3: "困难",
    4: "魔王",
    5: "里魔王",
}

RANK_DIFF_EN_MAP = {
    "easy": 1,
    "normal": 2,
    "hard": 3,
    "oni": 4,
    "ura": 5,
    "inner": 5,
    "inneroni": 5,
}

REGION_SUFFIXES = [
    "省",
    "市",
    "自治区",
    "壮族自治区",
    "回族自治区",
    "维吾尔自治区",
    "特别行政区",
]

ONEBOT_EXTERNAL_BOT_QQ = "3889003795"

def _is_external_bot_mentioned(event: MessageEvent) -> bool:
    if is_qq_official_event(event):
        return False
    for seg in event.get_message():
        if seg.type == "at" and seg.data.get("qq") == ONEBOT_EXTERNAL_BOT_QQ:
            return True
    return False

def _resolve_onebot_forward_sender_id(bot: Bot, event: MessageEvent) -> int:
    for candidate in (
        getattr(bot, "self_id", None),
        getattr(event, "self_id", None),
        event.get_user_id() if hasattr(event, "get_user_id") else None,
    ):
        try:
            return int(str(candidate or "").strip())
        except Exception:
            continue
    return 10000

def _build_city_arcade_forward_messages(
    bot: Bot,
    event: MessageEvent,
    result: CityShopQueryResult,
) -> list[MessageSegment]:
    sender_id = _resolve_onebot_forward_sender_id(bot, event)
    if not result.shops:
        return []
    nodes = [
        MessageSegment.node_custom(
            user_id=sender_id,
            nickname="太鼓地图",
            content=format_taiko_city_shop_summary(result),
        )
    ]
    for index, shop in enumerate(result.shops, start=1):
        map_json = build_tencent_map_location_json(shop)
        if map_json:
            content = MessageSegment.json(map_json)
        else:
            content = format_taiko_city_shop_entry(index, shop)
        nodes.append(
            MessageSegment.node_custom(
                user_id=sender_id,
                nickname=format_city_shop_forward_nickname(index, shop),
                content=content,
            )
        )
    return nodes


def load_region_map() -> Dict[str, int]:
    with REGION_MAP_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def _parse_rank_diff_token(token: str) -> Optional[int]:
    t = token.strip()
    if not t:
        return None
    if t in RANK_DIFF_INPUT_MAP:
        return RANK_DIFF_INPUT_MAP[t]
    t_lower = t.lower()
    if t_lower in RANK_DIFF_EN_MAP:
        return RANK_DIFF_EN_MAP[t_lower]
    if t.isdigit():
        v = int(t)
        if 1 <= v <= 5:
            return v
    m = re.match(r"^(?:难度|等级|level|lv)\s*([1-5])$", t, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"^(?:难度|等级)\s*(.+)$", t)
    if m:
        suffix = m.group(1).strip()
        if suffix in RANK_DIFF_INPUT_MAP:
            return RANK_DIFF_INPUT_MAP[suffix]
        if suffix.isdigit():
            v = int(suffix)
            if 1 <= v <= 5:
                return v
    return None

def _normalize_region_token(
    token: str, region_map: Dict[str, int], id_to_name: Dict[int, str]
) -> Optional[Tuple[str, int]]:
    t = token.strip().strip("，,。.;；")
    if not t:
        return None
    if t in region_map:
        return (t, region_map[t])
    if t.isdigit():
        rid = int(t)
        if rid in id_to_name:
            return (id_to_name[rid], rid)
    for suf in REGION_SUFFIXES:
        if t.endswith(suf):
            base = t[: -len(suf)]
            if base in region_map:
                return (base, region_map[base])
    return None

def _parse_song_rank_args(
    arg_str: str, region_map: Dict[str, int]
) -> Tuple[str, Optional[int], Optional[int], Optional[str]]:
    text = re.sub(r"\s+", " ", arg_str).strip()
    if not text:
        return "", None, None, None

    tokens = text.split(" ")
    id_to_name: Dict[int, str] = {}
    for name, rid in region_map.items():
        if rid not in id_to_name:
            id_to_name[rid] = name

    diff_id: Optional[int] = None
    province_id: Optional[int] = None
    province_name: Optional[str] = None
    alias_tokens: List[str] = []

    if len(tokens) > 1:
        for tok in tokens:
            if not tok:
                continue
            key_val = re.split(r"[=:：]", tok, maxsplit=1)
            if len(key_val) == 2:
                key, val = key_val[0].strip(), key_val[1].strip()
                if key.lower() in ("难度", "等级", "level", "lv"):
                    diff = _parse_rank_diff_token(val)
                    if diff is not None and diff_id is None:
                        diff_id = diff
                        continue
                if key.lower() in ("省份", "地区", "地域", "region"):
                    region = _normalize_region_token(val, region_map, id_to_name)
                    if region and province_id is None:
                        province_name, province_id = region
                        continue

            if diff_id is None:
                diff = _parse_rank_diff_token(tok)
                if diff is not None:
                    diff_id = diff
                    continue
            if province_id is None:
                if tok in ("全国", "全服", "全区", "全国榜", "全服榜"):
                    province_name = "全国"
                    province_id = None
                    continue
                region = _normalize_region_token(tok, region_map, id_to_name)
                if region:
                    province_name, province_id = region
                    continue
            alias_tokens.append(tok)

    parsed_any = diff_id is not None or province_name is not None
    if alias_tokens:
        alias = " ".join(alias_tokens).strip()
    else:
        alias = "" if parsed_any and len(tokens) > 1 else text

    # 兼容无空格输入：从首尾提取难度/地区
    remainder = alias
    if remainder and (diff_id is None or province_id is None):
        if province_id is None:
            region_keys = sorted(region_map.keys(), key=len, reverse=True)
            for key in region_keys:
                if remainder.endswith(key) and len(remainder) > len(key):
                    province_name = key
                    province_id = region_map[key]
                    remainder = remainder[: -len(key)].strip()
                    break
            if province_id is None:
                for suf in REGION_SUFFIXES:
                    if remainder.endswith(suf) and len(remainder) > len(suf):
                        base = remainder[: -len(suf)].strip()
                        if base in region_map:
                            province_name = base
                            province_id = region_map[base]
                            remainder = remainder[: -len(suf)].strip()
                            break
        if diff_id is None:
            diff_keys = sorted(RANK_DIFF_INPUT_MAP.keys(), key=len, reverse=True)
            for key in diff_keys:
                if remainder.endswith(key) and len(remainder) > len(key):
                    diff_id = RANK_DIFF_INPUT_MAP[key]
                    remainder = remainder[: -len(key)].strip()
                    break
            if diff_id is None:
                for key in diff_keys:
                    if remainder.startswith(key) and len(remainder) > len(key):
                        diff_id = RANK_DIFF_INPUT_MAP[key]
                        remainder = remainder[len(key) :].strip()
                        break

    alias = remainder or alias
    return alias, diff_id, province_id, province_name

def get_song_entry_by_id(song_id: str) -> Optional[Dict[str, Any]]:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item
    return None

def _load_alias_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> List[str]:
    if "\n" in text:
        wrapped_lines: List[str] = []
        for raw_line in text.splitlines():
            if raw_line == "":
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(_wrap_text(draw, raw_line, font, max_w))
        return wrapped_lines if wrapped_lines else [""]

    if draw.textlength(text, font=font) <= max_w:
        return [text]
    lines: List[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        test = current + ch
        if draw.textlength(test, font=font) <= max_w or not current:
            current = test
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines

def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    if draw.textlength(ell, font=font) > max_w:
        return ""
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        t = text[:mid] + ell
        if draw.textlength(t, font=font) <= max_w:
            left = mid + 1
        else:
            right = mid
    return text[: right - 1] + ell if right > 0 else ell

def render_ranking_image(
    song_title: str,
    sections: List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]],
    province_name: Optional[str] = None,
    width: int = 1040,
    padding: int = 28,
    font_size: int = 22,
    line_gap: int = 10,
    bg_color: Tuple[int, int, int] = (244, 246, 249),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(SONG_RANK_FONT_PATH, font_size)
    title_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size + 10)
    section_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size + 3)
    header_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size)
    tmp = Image.new("RGBA", (width, 10), (*bg_color, 255))
    draw = ImageDraw.Draw(tmp)

    title = f"歌曲排行 {song_title}"
    if province_name:
        title += f"（{province_name}）"

    title_lines = _wrap_text(draw, title, title_font, width - padding * 2)
    title_h = int((font_size + 10) * 1.55) * len(title_lines)
    section_h = int((font_size + 3) * 1.45)
    row_h = int(font_size * 1.5)
    rank_w = 52
    score_w = 140
    gap = 10
    min_name_w = int(draw.textlength("测" * 5, font=font)) + 8
    columns = max(1, len(sections))
    col_gap = 32 if columns >= 4 else 28
    min_col_width = rank_w + gap + score_w + gap + min_name_w
    width = max(
        width,
        padding * 2 + columns * min_col_width + col_gap * (columns - 1),
    )
    col_width = int((width - padding * 2 - col_gap * (columns - 1)) / columns)

    def section_height(rankings: Optional[List[Tuple[int, str, Optional[int]]]]) -> int:
        row_count = 1
        if rankings:
            row_count = len(rankings)
        return section_h + line_gap + row_h + line_gap + row_count * (row_h + line_gap)

    rows: List[List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]]] = []
    for i in range(0, len(sections), columns):
        rows.append(sections[i : i + columns])

    height = padding * 2 + title_h + line_gap
    for row in rows:
        row_heights = [section_height(rankings) for _, rankings in row]
        height += max(row_heights) + line_gap

    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    y = padding
    for line in title_lines:
        line_w = draw.textlength(line, font=title_font)
        draw.text(((width - line_w) / 2, y), line, fill=fg_color, font=title_font)
        y += int((font_size + 10) * 1.55)
    y += line_gap

    section_bg = (230, 235, 242)
    row_alt = (236, 239, 244)
    header_fg = (60, 66, 75)
    line_color = (210, 214, 220)

    for row in rows:
        row_heights = [section_height(rankings) for _, rankings in row]
        row_height = max(row_heights)
        for col_idx, (diff_label, rankings) in enumerate(row):
            x = padding + col_idx * (col_width + col_gap)
            score_right = x + col_width
            name_x = x + rank_w + gap
            name_w = max(min_name_w, score_right - score_w - name_x - gap)

            draw.rectangle([x, y, x + col_width, y + section_h], fill=section_bg)
            section_text = f"{diff_label} Top20"
            section_w = draw.textlength(section_text, font=section_font)
            draw.text(
                (x + (col_width - section_w) / 2, y + 2),
                section_text,
                fill=fg_color,
                font=section_font,
            )
            y_section = y + section_h + line_gap

            rank_text = "排名"
            rank_text_w = draw.textlength(rank_text, font=header_font)
            draw.text(
                (x + (rank_w - rank_text_w) / 2, y_section),
                rank_text,
                fill=header_fg,
                font=header_font,
            )
            name_text = "玩家"
            name_text_w = draw.textlength(name_text, font=header_font)
            draw.text(
                (name_x + (name_w - name_text_w) / 2, y_section),
                name_text,
                fill=header_fg,
                font=header_font,
            )
            score_text = "分数"
            score_text_w = draw.textlength(score_text, font=header_font)
            draw.text(
                (score_right - score_w + (score_w - score_text_w) / 2, y_section),
                score_text,
                fill=header_fg,
                font=header_font,
            )
            y_section += row_h + line_gap

            data_rows: List[Tuple[Optional[int], str, Optional[int]]] = []
            if rankings is None:
                data_rows = [(None, "获取失败", None)]
            elif not rankings:
                data_rows = [(None, "暂无排行数据", None)]
            else:
                data_rows = rankings

            for idx, row_item in enumerate(data_rows):
                if idx % 2 == 0:
                    draw.rectangle(
                        [x, y_section - 2, x + col_width, y_section + row_h + 2],
                        fill=row_alt,
                    )
                rank, name, score = row_item
                rank_text = "--" if rank is None else str(rank)
                rank_text_w = draw.textlength(rank_text, font=font)
                draw.text(
                    (x + (rank_w - rank_text_w) / 2, y_section),
                    rank_text,
                    fill=fg_color,
                    font=font,
                )

                name_text = name or "未知"
                name_disp = _truncate_text(draw, name_text, font, name_w)
                name_disp_w = draw.textlength(name_disp, font=font)
                draw.text(
                    (name_x + (name_w - name_disp_w) / 2, y_section),
                    name_disp,
                    fill=fg_color,
                    font=font,
                )

                score_text = "--" if score is None else f"{score:,}"
                score_w_text = draw.textlength(score_text, font=font)
                draw.text(
                    (score_right - score_w + (score_w - score_w_text) / 2, y_section),
                    score_text,
                    fill=fg_color,
                    font=font,
                )
                draw.line(
                    [x, y_section + row_h + 2, x + col_width, y_section + row_h + 2],
                    fill=line_color,
                    width=1,
                )
                y_section += row_h + line_gap

        y += row_height + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def _extract_rankings(
    payload: Dict[str, Any], diff_id: int
) -> Optional[List[Tuple[int, str, Optional[int]]]]:
    if "status" in payload and payload.get("status") not in (0, "0"):
        return None
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rank_data = data.get("rank_data", [])
    if isinstance(rank_data, dict):
        rank_data = [rank_data]
    target = None
    for item in rank_data:
        if item.get("level") == diff_id:
            target = item
            break
    if target is None and rank_data:
        target = rank_data[0]
    if not target:
        return []

    rankings = []
    for entry in target.get("rankings", []) or []:
        rank = entry.get("rank")
        costume = entry.get("gameCostume") or {}
        name = costume.get("mydon_name") or entry.get("mydon_name") or "未知"
        score = entry.get("score")
        try:
            rank_val = int(rank)
        except Exception:
            continue
        score_val = None
        try:
            score_val = int(score) if score is not None else None
        except Exception:
            score_val = None
        rankings.append((rank_val, name, score_val))
    rankings.sort(key=lambda x: x[0])
    return rankings[:20]

quick_actions_panel = on_regex(r"^/?快捷操作$", rule=taiko_rule)

song_rank = on_regex(r"^(歌曲排行|歌曲排名|排行歌曲)\s*(.*)$", rule=taiko_rule)

summary = on_fullmatch("taiko2025", rule=taiko_rule)

twso = on_regex(r"^/?查分$", rule=taiko_rule)

city_arcade_query = on_regex(
    CITY_ARCADE_QUERY_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)

quick_actions_panel.append_handler(query_access.quick_actions_panel_handle)

@song_rank.handle()
async def song_rank_handle(event: MessageEvent):
    plain_text = extract_plain_text(event)
    m = re.match('^(歌曲排行|歌曲排名|排行歌曲)\\s*(.*)$', plain_text)
    if not m:
        await song_rank.finish('参数错误。示例：歌曲排行 歌名 困难 广东')
    arg_str = (m.group(2) or '').strip()
    if not arg_str:
        await song_rank.finish('歌曲别名为必填参数。示例：歌曲排行 歌名 困难 广东')
    region_map = load_region_map()
    song_alias, diff_id, province_id, province_name = _parse_song_rank_args(arg_str, region_map)
    if not song_alias:
        await song_rank.finish('歌曲别名为必填参数。示例：歌曲排行 歌名 困难 广东')
    music_list = queryMusic(song_alias)
    if len(music_list) == 0:
        await _finish_text_reply(song_rank, event, '未找到任何歌曲？')
    fuzzy_hint = ''
    if _is_fuzzy_query_result(music_list):
        fuzzy_hint = _build_fuzzy_query_hint(music_list)
    elif len(music_list) > 1:
        msg = '你要找的可能是：\n'
        for music in music_list:
            msg += f'id{music[0]} {music[1]}\n'
        await song_rank.finish(msg)
    song_id = int(music_list[0][0])
    song_title = music_list[0][1]
    song_entry = get_song_entry_by_id(song_id)
    if not song_entry:
        await _finish_text_reply(song_rank, event, '歌曲信息缺失，无法查询排行。')
    if diff_id is not None:
        level_val = song_entry.get(f'level_{diff_id}')
        if level_val is None or (isinstance(level_val, str) and level_val.strip() == '-'):
            await _finish_text_reply(song_rank, event, '该歌曲没有该难度。')
        diff_ids = [diff_id]
    else:
        diff_ids = []
        for i in range(1, 6):
            level_val = song_entry.get(f'level_{i}')
            if level_val is None:
                continue
            if isinstance(level_val, str) and level_val.strip() == '-':
                continue
            diff_ids.append(i)
    if not diff_ids:
        await _finish_text_reply(song_rank, event, '该歌曲没有可用难度。')
    sections: List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]] = []
    ranking_error: Optional[str] = None
    for d in diff_ids:
        try:
            payload = fetch_wahlap_ranking(song_id, d, province_id=province_id)
            rankings = _extract_rankings(payload, d)
        except ViewerClientError as exc:
            if ranking_error is None:
                ranking_error = str(exc)
            rankings = None
        sections.append((RANK_DIFF_LABEL_MAP.get(d, f'难度{d}'), rankings))
    if ranking_error and all((rankings is None for _label, rankings in sections)):
        await _finish_text_reply(song_rank, event, ranking_error)
    if not await _ensure_asset_resources_ready(song_rank, event, 'core-assets', 'cover-assets'):
        return
    img_buf = render_ranking_image(song_title, sections, province_name=province_name)
    img_jpg = _to_jpeg_bytes(img_buf, quality=85)
    if fuzzy_hint:
        await _finish_image_reply(song_rank, event, img_jpg, prefix_text=fuzzy_hint)
    else:
        await _finish_image_reply(song_rank, event, img_jpg)

@summary.handle()
async def summary_handle(event: MessageEvent, matcher: Matcher):
    try:
        provider, private, summary = await query_access.prepare(matcher, event, summary=True)
        bind_target = {"user_id": private.authorized_target.user_id, "is_virtual": len(private.authorized_target.members)>1 or private.authorized_target.user_id.startswith("u0")}
        taiko_id = str(bind_target['user_id'])
        try:
            utime = provider.summary_utime
            t = utime.split('-')
        except Exception as e:
            await summary.finish('请更新数据后使用~', reply_message=True)
        if int(t[0]) < 2026:
            await summary.finish('请更新数据后使用~', reply_message=True)
        elif int(t[1]) == 1 and int(t[2][:2]) < 3:
            await summary.finish('请更新数据后使用~', reply_message=True)
        if not await _ensure_asset_resources_ready(summary, event, 'core-assets', 'cover-assets', 'dress-assets', 'nameplate-assets'):
            return
        try:
            result = render_summary(provider, private)
        except Exception as e:
            await summary.finish('查不到捏，怎么回事呢？', reply_message=True)
        await summary.finish(MessageSegment.image(result), reply_message=True)
    except (entry.TinfoDenied, entry.TinfoUnavailable):
        await entry.helpers._finish_text_reply(matcher, event, "查不到呢，可能不给看哦~")

twso.append_handler(query_access.twso_handle)

@city_arcade_query.handle()
async def city_arcade_query_handle(bot: Bot, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event).strip()
    match = CITY_ARCADE_QUERY_REGEX.fullmatch(msg_text)
    if not match:
        await _finish_text_reply(city_arcade_query, event, '格式错误，请直接发送“鞍山哪有鼓”这类指令。')
        return
    city_name = match.group('city').strip()
    try:
        result = await query_taiko_shops_by_city(city_name)
    except ValueError as exc:
        await _finish_text_reply(city_arcade_query, event, str(exc))
        return
    except RuntimeError as exc:
        await _finish_text_reply(city_arcade_query, event, str(exc))
        return
    except Exception:
        logger.exception('query taiko city shops failed: city=%s', city_name)
        await _finish_text_reply(city_arcade_query, event, '查询失败，鼓众地图可能暂时不可用，请稍后再试。')
        return
    reply_text = format_taiko_city_shop_reply(result)
    if not is_qq_official_event(event):
        try:
            forward_messages = _build_city_arcade_forward_messages(bot, event, result)
            if forward_messages and await send_onebot_forward_messages(city_arcade_query, bot, event, forward_messages):
                return
        except Exception:
            logger.exception('send city arcade forward reply failed: city=%s', city_name)
    await _finish_text_reply(city_arcade_query, event, reply_text)
