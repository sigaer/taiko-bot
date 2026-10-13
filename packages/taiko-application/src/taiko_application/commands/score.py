from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class ScorePorts:
    _build_fuzzy_query_hint: Callable[..., Any]
    _is_rejected_fuzzy_query_result: Callable[..., Any]
    _to_jpeg_bytes: Callable[..., Any]
    generate_score_image: Callable[..., Any]
    print: Callable[..., Any]
    queryMusic: Callable[..., Any]


def execute_score(context: CommandContext, ports: ScorePorts) -> CommandResult | None:
    m = context.match
    user_id = context.user_id
    if not m:
        return CommandResult("text", "格式不正确，应为：tinfo 歌名", delivery="direct")
    music_name = m.group(1)
    music_list = ports.queryMusic(music_name)
    music_id = -1
    fuzzy_hint = ""
    msg = ""
    if len(music_list) == 0:
        return CommandResult("text", "未找到任何歌曲？", delivery="reply")
    elif ports._is_rejected_fuzzy_query_result(music_list):
        fuzzy_hint = ports._build_fuzzy_query_hint(music_list)
        music_id = int(music_list[0][0])
    elif len(music_list) == 1:
        music_id = int(music_list[0][0])
    else:
        msg = "你要找的可能是：\n"
        for music in music_list:
            msg += f"id{music[0]} {music[1]}\n"
        return CommandResult("text", msg, delivery="direct")
    if music_id == -1:
        return CommandResult("text", "查询失败，怎么回事呢？", delivery="direct")
    else:
        try:
            res_img = ports.generate_score_image(
                song_no=music_id, user_id=user_id, prefer_best_in_group=True
            )
        except FileNotFoundError as e:
            ports.print(e)
            return CommandResult(
                "text",
                "您还未上传数据哦~请先发送“taikoupdate”进行上传",
                delivery="reply",
            )
        except Exception as e:
            return CommandResult("text", f"{e}", delivery="direct")
        img_jpg = ports._to_jpeg_bytes(res_img, quality=85)
        if fuzzy_hint:
            return CommandResult("image", img_jpg, prefix_text=fuzzy_hint)
        else:
            return CommandResult("image", img_jpg, prefix_text="")
