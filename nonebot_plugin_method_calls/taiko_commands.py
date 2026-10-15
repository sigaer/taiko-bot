from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Any, Callable

from nonebot import logger

from .reserved_commands import is_foreign_progress_command
from taiko_bot.runtime.player.center.messages import (
    extract_plain_text,
    get_group_identifier,
    get_platform_kind,
    is_onebot_message_targeting_other_account,
)

DisplayExtractor = Callable[[str], str | None]


@dataclass(frozen=True)
class TaikoCommandSpec:
    canonical: str
    display: str | None = None
    display_extractor: DisplayExtractor | None = None


@dataclass(frozen=True)
class TaikoCommandMatch:
    canonical: str
    display: str
    platform: str
    group_id: str | None


def _fixed_display(value: str) -> DisplayExtractor:
    def _extractor(_: str) -> str:
        return value

    return _extractor


def _capture_first_group(pattern: str, *, flags: int = 0) -> DisplayExtractor:
    compiled = re.compile(pattern, flags)

    def _extractor(text: str) -> str | None:
        match = compiled.match(text.strip())
        if not match:
            return None
        value = str(match.group(1) or "").strip()
        return value or None

    return _extractor


def _capture_bind_qq_display(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped == "绑定QQ":
        return stripped
    match = re.match(
        r"(?i)^/?(绑定\s*qq)(?:\s*你的qq号)?\s*[1-9]\d{4,11}$",
        stripped,
    )
    if not match:
        return None
    return match.group(1).replace(" ", "") or "绑定QQ"


def _capture_public_score_token_display(text: str) -> str | None:
    match = re.match(
        r"^(网页成绩token|成绩token|scoretoken|获取token)(?:\s*(?:重置|刷新|reset))?$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return str(match.group(1) or "").strip() or None


def _capture_tcloud_display(text: str) -> str | None:
    match = re.match(r"^(tcloud|太鼓词云|词云)\s*$", text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return str(match.group(1) or "").strip() or None


def _capture_taikorec_display(text: str) -> str | None:
    match = re.match(r"^(taikorec|推荐歌曲|歌曲推荐).*$", text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return str(match.group(1) or "").strip() or None


def _capture_progress_display(text: str) -> str | None:
    match = re.match(r"^(?P<body>.+进度)(?:\s+(?P<page>\d+))?$", text.strip())
    if not match:
        return None
    body = str(match.group("body") or "").strip()
    if is_foreign_progress_command(body):
        # 其他 bot 的进度指令，不计入 taiko 的「进度」使用统计
        return None
    return body or None


def _capture_song_metric_display(_: str) -> str:
    return "成绩筛选"


def _capture_song_position_display(text: str) -> str | None:
    stripped = text.strip()
    if re.match(r"^位置\s*id\d+\s*$", stripped, flags=re.IGNORECASE):
        return "位置"
    if stripped.endswith("在哪"):
        return "在哪"
    if stripped.endswith("在什么位置"):
        return "在什么位置"
    return None


def _capture_tsearch_display(text: str) -> str | None:
    stripped = text.strip()
    if re.match(r"^tsearch\s*(on|off)$", stripped, flags=re.IGNORECASE):
        return "tsearch"
    if re.match(r"^(开启|关闭)(?:tsearch|太鼓搜歌|太鼓查歌|太鼓是什么歌)功能$", stripped):
        return "tsearch"
    return None


def _capture_alias_query_display(_: str) -> str:
    return "有什么别名"


def _capture_diff_by_id_display(_: str) -> str:
    return "查谱"


def _capture_draw_guess_switch_display(_: str) -> str:
    return "你画我猜功能"


def _build_spec_map() -> dict[str, TaikoCommandSpec]:
    return {
        "qq_migration_code": TaikoCommandSpec("迁移验证码", display="迁移验证码"),
        "bind_confirm": TaikoCommandSpec("确认绑定", display="确认绑定"),
        "bind_remove_confirm": TaikoCommandSpec("确认删除绑定", display="确认删除绑定"),
        "update_typo": TaikoCommandSpec("taikoupdate拼写提示", display="taikoupdate拼写提示"),
        "game_login_qr": TaikoCommandSpec("码来", display="码来"),
        "manual_create": TaikoCommandSpec("新增空白账号", display="新增空白账号"),
        "manual_rename": TaikoCommandSpec("空白账号改名", display="空白账号改名"),
        "manual_claim_code": TaikoCommandSpec("生成认领码", display="生成认领码"),
        "manual_claim": TaikoCommandSpec("认领空白账号", display="认领空白账号"),
        "manual_detach": TaikoCommandSpec("解绑空白账号", display="解绑空白账号"),
        "manual_delete": TaikoCommandSpec("永久删除空白账号", display="永久删除空白账号"),
        "manual_delete_confirm": TaikoCommandSpec("确认永久删除空白账号", display="确认永久删除空白账号"),
        "manual_score_upsert": TaikoCommandSpec("录入成绩", display="录入成绩"),
        "manual_score_get": TaikoCommandSpec("查看成绩", display="查看成绩"),
        "manual_score_delete": TaikoCommandSpec("删除成绩", display="删除成绩"),
        "manual_score_delete_confirm": TaikoCommandSpec("确认删除成绩", display="确认删除成绩"),
        "bind_qq_prompt": TaikoCommandSpec("绑定QQ", display_extractor=_capture_bind_qq_display),
        "bind_qq": TaikoCommandSpec("绑定QQ", display_extractor=_capture_bind_qq_display),
        "bind_switch": TaikoCommandSpec("切换绑定", display="切换绑定"),
        "bind": TaikoCommandSpec("绑定", display="绑定"),
        "bind_hiroba": TaikoCommandSpec("绑定hiroba", display="绑定hiroba"),
        "hiroba_update": TaikoCommandSpec(
            "hirobaupdate",
            display_extractor=_capture_first_group(
                r"^(hirobaupdate|更新hiroba|更新ひろば)(?:(?:\s+|)(?:all|全部|全量|-a|--all))?\s*$",
                flags=re.IGNORECASE,
            ),
        ),
        "bind_remove": TaikoCommandSpec("删除绑定", display="删除绑定"),
        "show_bind": TaikoCommandSpec("给看", display="给看"),
        "unshow_bind": TaikoCommandSpec("不给看", display="不给看"),
        "update": TaikoCommandSpec(
            "taikoupdate",
            display_extractor=_capture_first_group(
                r"^(taikoupdate|更新广场)(?:(?:\s+|)(?:all|全部|全量|-a|--all))?\s*$",
                flags=re.IGNORECASE,
            ),
        ),
        "quick_actions_panel": TaikoCommandSpec(
            "快捷操作",
            display_extractor=_capture_first_group(
                r"^(/?快捷操作|/?taiko帮助)\s*$",
                flags=re.IGNORECASE,
            ),
        ),
        "developer_userdata": TaikoCommandSpec("开发者数据", display="开发者数据"),
        "public_score_token": TaikoCommandSpec(
            "网页成绩token",
            display_extractor=_capture_public_score_token_display,
        ),
        "trend": TaikoCommandSpec(
            "taikotrend",
            display_extractor=_capture_first_group(
                r"^/?(taikotrend|rating走势)\s*(.*)$",
                flags=re.IGNORECASE,
            ),
        ),
        "playtrend": TaikoCommandSpec(
            "taikoplaytrend",
            display_extractor=_capture_first_group(
                r"^/?(taikoplaytrend|rating场次|rating游玩)\s*(.*)$",
                flags=re.IGNORECASE,
            ),
        ),
        "song_rank": TaikoCommandSpec(
            "歌曲排行",
            display_extractor=_capture_first_group(
                r"^(歌曲排行|歌曲排名|歌曲排行榜|排行歌曲|排名歌曲)\s*(.*)$"
            ),
        ),
        "summary": TaikoCommandSpec("taiko2025", display="taiko2025"),
        "my_don": TaikoCommandSpec("我的小咚", display="我的小咚"),
        "song_metric_query": TaikoCommandSpec(
            "成绩筛选",
            display_extractor=_capture_song_metric_display,
        ),
        "tcloud": TaikoCommandSpec("tcloud", display_extractor=_capture_tcloud_display),
        "taikob": TaikoCommandSpec("taikob", display="taikob"),
        "music_info": TaikoCommandSpec("tinfo", display="tinfo"),
        "patterns": TaikoCommandSpec("查配置", display="查配置"),
        "twso": TaikoCommandSpec("活动查分", display="查分"),
        "note_count": TaikoCommandSpec("太鼓查物量", display="太鼓查物量"),
        "const_query": TaikoCommandSpec("查定数", display="查定数"),
        "matcher": TaikoCommandSpec("进度", display_extractor=_capture_progress_display),
        "score_line_cmd": TaikoCommandSpec("分数线", display="分数线"),
        "score_estimate_cmd": TaikoCommandSpec("估分", display="估分"),
        "score_cmd": TaikoCommandSpec("查分计算", display="查分"),
        "annual_2025_report": TaikoCommandSpec("2025年度报告", display="2025年度报告"),
        "qq_official_ping": TaikoCommandSpec("ping", display="ping"),
        "draw_guess_answer": TaikoCommandSpec("猜太鼓答案", display="猜太鼓答案"),
        "cover_cmd": TaikoCommandSpec("cover", display="cover"),
        "taikorec": TaikoCommandSpec("taikorec", display_extractor=_capture_taikorec_display),
        "tsearch_switch": TaikoCommandSpec("tsearch", display_extractor=_capture_tsearch_display),
        "alias_query": TaikoCommandSpec("有什么别名", display_extractor=_capture_alias_query_display),
        "tset_alias": TaikoCommandSpec("tset", display="tset"),
        "song_title_query": TaikoCommandSpec("查称号", display="查称号"),
        "custom_title_add": TaikoCommandSpec("加称号", display="加称号"),
        "song_where": TaikoCommandSpec("位置", display_extractor=_capture_song_position_display),
        "song_position_phrase": TaikoCommandSpec("位置", display_extractor=_capture_song_position_display),
        "song_pos_by_id": TaikoCommandSpec("位置", display_extractor=_capture_song_position_display),
        "city_arcade_query": TaikoCommandSpec("哪有鼓", display="哪有鼓"),
        "what_song": TaikoCommandSpec("是什么歌", display="是什么歌"),
        "diff_by_id": TaikoCommandSpec("查谱", display_extractor=_capture_diff_by_id_display),
        "draw_guess_switch": TaikoCommandSpec(
            "你画我猜功能",
            display_extractor=_capture_draw_guess_switch_display,
        ),
        "draw_guess_make_start": TaikoCommandSpec("画太鼓歌名", display="画太鼓歌名"),
        "draw_guess_start": TaikoCommandSpec("猜太鼓歌名", display="猜太鼓歌名"),
        "draw_guess_like": TaikoCommandSpec("点赞你画我猜", display="点赞你画我猜"),
        "draw_guess_report": TaikoCommandSpec("举报你画我猜", display="举报你画我猜"),
        "draw_guess_view": TaikoCommandSpec("查看你画我猜", display="查看你画我猜"),
        "draw_guess_mine": TaikoCommandSpec("我的你画我猜", display="我的你画我猜"),
        "draw_guess_rank": TaikoCommandSpec("你画我猜排行", display="你画我猜排行"),
    }


# Temporary Sakura-owned statistics integration. Move this registry/recorder to
# taiko-bot in a later ownership step; do not import/register matchers here.
_MIGRATED_MATCHER_MODULES = {
    "city_arcade_query": "taiko_bot.runtime.player.center.query_cluster",
    "custom_title_add": "taiko_bot.runtime.player.center.management_cluster",
    "quick_actions_panel": "taiko_bot.runtime.player.center.query_cluster",
    "song_rank": "taiko_bot.runtime.player.center.query_cluster",
    "song_title_query": "taiko_bot.runtime.player.center.management_cluster",
    "summary": "taiko_bot.runtime.player.center.query_cluster",
    "tsearch_switch": "taiko_bot.runtime.player.center.management_cluster",
    "tset_alias": "taiko_bot.runtime.player.center.management_cluster",
    "twso": "taiko_bot.runtime.player.center.query_cluster",

    "score_cmd": "taiko_bot.runtime.player.scoring",
    "score_estimate_cmd": "taiko_bot.runtime.player.scoring",
    "score_line_cmd": "taiko_bot.runtime.player.scoring",
    "what_song": "taiko_bot.runtime.public",
    "alias_query": "taiko_bot.runtime.public.public_commands",
    "song_where": "taiko_bot.runtime.public.public_commands",
    "song_position_phrase": "taiko_bot.runtime.public.public_commands",
    "song_pos_by_id": "taiko_bot.runtime.public.public_commands",
    "diff_by_id": "taiko_bot.runtime.public.public_commands",
    "note_count": "taiko_bot.runtime.public.public_commands",
    "const_query": "taiko_bot.runtime.public.catalog_commands",
    "patterns": "taiko_bot.runtime.public.catalog_commands",
    "music_info": "taiko_bot.runtime.player.entry",
    "taikorec": "taiko_bot.runtime.player.recommendation",
    "matcher": "taiko_bot.runtime.player.progress",
    "taikob": "taiko_bot.runtime.player.b30",
    "my_don": "taiko_bot.runtime.player.personal",
    "song_metric_query": "taiko_bot.runtime.player.personal",
    "tcloud": "taiko_bot.runtime.player.personal",

    "trend": "taiko_bot.runtime.player.trend",
    "playtrend": "taiko_bot.runtime.player.trend",
    "qq_migration_code": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_qq": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_qq_prompt": "taiko_bot.runtime.player.center.identity_cluster",
    "bind": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_confirm": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_switch": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_hiroba": "taiko_bot.runtime.player.center.identity_cluster",
    "hiroba_update": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_remove": "taiko_bot.runtime.player.center.identity_cluster",
    "bind_remove_confirm": "taiko_bot.runtime.player.center.identity_cluster",
    "show_bind": "taiko_bot.runtime.player.center.identity_cluster",
    "unshow_bind": "taiko_bot.runtime.player.center.identity_cluster",
    "manual_create": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_rename": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_claim_code": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_claim": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_detach": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_delete": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_delete_confirm": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_score_upsert": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_score_get": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_score_delete": "taiko_bot.runtime.player.center.manual_cluster",
    "manual_score_delete_confirm": "taiko_bot.runtime.player.center.manual_cluster",
    "update": "taiko_bot.runtime.player.center.update_cluster",
    "update_typo": "taiko_bot.runtime.player.center.update_cluster",
    "public_score_token": "taiko_bot.runtime.player.center.update_cluster",
    "developer_userdata": "taiko_bot.runtime.player.center.update_cluster",
    "game_login_qr": "taiko_bot.runtime.player.center.update_cluster",
}
_MIGRATED_MATCHER_MODULES.update({
    name: "taiko_bot.runtime.community.center.draw_guess"
    for name in ("draw_guess_switch", "draw_guess_make_start", "draw_guess_start", "draw_guess_answer", "draw_guess_like", "draw_guess_report", "draw_guess_view", "draw_guess_mine", "draw_guess_rank", "draw_guess_manual_exit")
})
_MIGRATED_MATCHER_MODULES.update(cover_cmd="taiko_bot.runtime.community.center.cover", annual_2025_report="taiko_bot.runtime.community.center.annual", qq_official_ping="taiko_bot.runtime.community.center.compat")

_TAIKO_MATCHER_MODULES = frozenset(_MIGRATED_MATCHER_MODULES.values()) | frozenset(
    name.replace(".center.", ".client.") for name in _MIGRATED_MATCHER_MODULES.values()
)


def _is_owned_taiko_matcher(matcher: Any) -> bool:
    matcher_type = _matcher_type(matcher)
    module_name = str(getattr(matcher_type, "module_name", "") or "").strip()
    module = str(getattr(matcher_type, "__module__", "") or "").strip()
    return module_name in _TAIKO_MATCHER_MODULES or module in _TAIKO_MATCHER_MODULES


def _matcher_type(matcher: Any) -> Any:
    if isinstance(matcher, type):
        return matcher
    return getattr(matcher, "__class__", matcher)


def _iter_matcher_types(matcher: Any) -> tuple[Any, ...]:
    matcher_type = _matcher_type(matcher)
    return tuple(getattr(matcher_type, "__mro__", (matcher_type,)))


def _matcher_specs() -> dict[Any, TaikoCommandSpec]:
    # Resolve only loaded owners. A request before plugin load must not cache an
    # incomplete registry, nor cause the recorder to register another matcher.
    specs: dict[Any, TaikoCommandSpec] = {}
    for matcher_name, spec in _build_spec_map().items():
        owner = _MIGRATED_MATCHER_MODULES.get(matcher_name, "")
        module = sys.modules.get(owner)
        if module is None and ".center." in owner:
            module = sys.modules.get(owner.replace(".center.", ".client."))
        matcher = getattr(module, matcher_name, None)
        if matcher is not None:
            specs[matcher] = spec
    return specs


def _resolve_taiko_spec(matcher: Any) -> TaikoCommandSpec | None:
    specs = _matcher_specs()
    for matcher_type in _iter_matcher_types(matcher):
        spec = specs.get(matcher_type)
        if spec is not None:
            return spec
    return None


def is_taiko_matcher(matcher: Any) -> bool:
    if not _is_owned_taiko_matcher(matcher):
        return False
    return _resolve_taiko_spec(matcher) is not None


def normalize_taiko_command(event: Any, matcher: Any) -> TaikoCommandMatch | None:
    if not _is_owned_taiko_matcher(matcher):
        return None
    spec = _resolve_taiko_spec(matcher)
    if spec is None:
        return None
    if is_onebot_message_targeting_other_account(event):
        return None

    plain_text = extract_plain_text(event)
    if spec.canonical == "taikoupdate拼写提示":
        # Its historical rule accepts every 10–12 character message; only an
        # actual typo response is a command invocation, not the silent probes.
        candidates = _iter_matcher_types(matcher)
        owner = next((sys.modules.get(str(getattr(item, "module_name", ""))) for item in candidates
                      if str(getattr(item, "module_name", "")).endswith(".update_cluster")), None)
        if owner is None or owner._normalize_update_command_text(plain_text) not in owner.UPDATE_TYPO_VARIANTS:
            return None
    display = None
    if spec.display_extractor is not None:
        try:
            display = spec.display_extractor(plain_text)
        except Exception:
            logger.exception("method_calls taiko display extractor failed")
    if not display:
        display = spec.display or spec.canonical

    return TaikoCommandMatch(
        canonical=spec.canonical,
        display=str(display).strip() or spec.canonical,
        platform=get_platform_kind(event=event),
        group_id=get_group_identifier(event=event),
    )
