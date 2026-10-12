from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class SongPorts:
    _extract_what_song_query: Callable[..., Any]
    _is_rejected_fuzzy_query_result: Callable[..., Any]
    _resolve_what_song_query: Callable[..., Any]


def execute_song(context: CommandContext, ports: SongPorts) -> CommandResult | None:
    msg_text = context.text
    if msg_text.startswith("@菌菌"):
        return CommandResult("text", None, delivery="direct")
    raw_q = ports._extract_what_song_query(msg_text)
    if raw_q is None:
        return CommandResult("text", "格式不正确，应为：xx是什么歌", delivery="direct")
    if not raw_q:
        return CommandResult(
            "text", "请提供要查询的关键词，例如：千本桜是什么歌", delivery="direct"
        )
    diff = "Oni"
    stripped_q = raw_q
    if raw_q.startswith("简单"):
        diff = "Kantan"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("普通"):
        diff = "Futsuu"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("困难"):
        diff = "Muzukashii"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("魔王"):
        diff = "Oni"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("梅"):
        diff = "Kantan"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("竹"):
        diff = "Futsuu"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("松"):
        diff = "Muzukashii"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("鬼"):
        diff = "Oni"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("里"):
        diff = "InnerOni"
        stripped_q = raw_q[1:].strip()
    try:
        res: Any = ports._resolve_what_song_query(raw_q, stripped_q)
    except Exception as e:
        return CommandResult("text", f"queryMusic 调用失败：{e}", delivery="direct")
    if len(res) == 0:
        return CommandResult("text", "未找到任何歌曲？", delivery="reply")
    elif ports._is_rejected_fuzzy_query_result(res):
        return CommandResult("fuzzy_fumen", res, difficulty=diff)
    elif len(res) > 1:
        msg = "你要找的可能是：\n"
        for music in res:
            msg += f"id{music[0]} {music[1]}\n"
        return CommandResult("text", msg, delivery="direct")
    song_id = str(res[0][0]).strip()
    return CommandResult("fumen", (diff, song_id))
