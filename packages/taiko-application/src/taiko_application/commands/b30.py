from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class B30Ports:
    TAIKOB_FONT_PATH: Any
    TAIKOB_V2_DIM_USAGE: Any
    V2DataSourceError: Any
    V2_TAIKOB_DIM_ALIASES: Any
    _extract_rating_version: Callable[..., Any]
    _load_user_song_records: Callable[..., Any]
    _parse_taikob_dim_arg: Callable[..., Any]
    _resolve_taikob_dim_arg: Callable[..., Any]
    _to_jpeg_bytes: Callable[..., Any]
    compute_all_from_userdata: Callable[..., Any]
    generate_dim_top_image: Callable[..., Any]
    generate_top_N_image: Callable[..., Any]
    render_b20_v2_dim_image: Callable[..., Any]
    render_b20_v2_image: Callable[..., Any]
    render_b30_image: Callable[..., Any]


def execute_b30(
    context: CommandContext, ports: B30Ports, prepared
) -> CommandResult | None:
    taiko_id = context.user_id
    N, args, use_v2, dynamic_origin, dim = prepared
    client = context.profile == "client"
    if use_v2:
        parse_args = [a for a in args if str(a).lower() != "v2"] if client else args
        v2_dim, v2_unknown_tokens = ports._parse_taikob_dim_arg(
            parse_args, ports.V2_TAIKOB_DIM_ALIASES
        )
        if client and N != 20:
            return CommandResult("text", "v2 目前仅支持 taikob20 v2", delivery="direct")
        if dynamic_origin:
            return CommandResult(
                "text", f"taikob{N} v2 暂不支持 -r 参数", delivery="direct"
            )
        if v2_unknown_tokens:
            return CommandResult(
                "text",
                f"taikob{N} v2 仅支持单维度参数：{ports.TAIKOB_V2_DIM_USAGE}",
                delivery="direct",
            )
        try:
            if v2_dim is not None and (not client or v2_dim != "综合Rating"):
                img_buf = ports.render_b20_v2_dim_image(
                    taiko_id, dim=v2_dim, N=N, font_path=ports.TAIKOB_FONT_PATH
                )
            else:
                img_buf = (
                    ports.render_b20_v2_image(taiko_id)
                    if client
                    else ports.render_b20_v2_image(taiko_id, N=N)
                )
        except FileNotFoundError as exc:
            if not client and "userdata not found" in str(exc):
                return CommandResult(
                    "text",
                    "您还未上传数据哦~请先发送“taikoupdate”进行上传",
                    delivery="direct",
                )
            return CommandResult(
                "text",
                f"缺少 taikob{N} v2 数据文件，请先同步公共曲库后再试",
                delivery="direct",
            )
        except ports.V2DataSourceError:
            if client:
                raise
            return CommandResult(
                "text",
                f"taikob{N} v2 上游定数数据暂时不可用，请稍后再试",
                delivery="direct",
            )
        except TypeError:
            if client:
                raise
            return CommandResult("text", "请更新数据~", delivery="direct")
        img_jpg = ports._to_jpeg_bytes(img_buf, quality=85)
        return CommandResult("image", img_jpg, prefix_text="")
    try:
        result = ports.compute_all_from_userdata(
            taiko_id, collapse_duplicate_versions=True
        )
    except FileNotFoundError:
        return CommandResult(
            "text", "您还未上传数据哦~请先发送“taikoupdate”进行上传", delivery="direct"
        )
    except TypeError:
        return CommandResult("text", "请更新数据~", delivery="direct")
    if not result:
        if client:
            return CommandResult(
                "text", "请游玩鬼难度歌曲后再来使用哦~", delivery="direct"
            )
        try:
            has_oni_record = any(
                (
                    int(record.get("level", 0) or 0) >= 4
                    for record in ports._load_user_song_records(int(taiko_id))
                )
            )
        except (FileNotFoundError, TypeError, ValueError):
            has_oni_record = False
        if has_oni_record:
            return CommandResult(
                "text",
                "检测到鬼难度成绩，但目前没有达到75%良率的可计入成绩，请提高良率后再试哦~",
                delivery="direct",
            )
        return CommandResult("text", "请游玩鬼难度歌曲后再来使用哦~", delivery="direct")
    if not args:
        img_buf = ports.render_b30_image(
            taiko_id, N=N, collapse_duplicate_versions=True
        )
        img_jpg = ports._to_jpeg_bytes(img_buf, quality=85)
        return CommandResult("image", img_jpg, prefix_text="")
    if dim is not None:
        img_buf = ports.generate_dim_top_image(
            result, N=N, dim=dim, user_id=taiko_id, font_path=ports.TAIKOB_FONT_PATH
        )
        img_jpg = ports._to_jpeg_bytes(img_buf, quality=85)
        return CommandResult("image", img_jpg, prefix_text="")
    img_buf = ports.generate_top_N_image(
        result,
        N,
        user_id=taiko_id,
        dynamic_origin=dynamic_origin,
        font_path=ports.TAIKOB_FONT_PATH,
    )
    img_jpg = ports._to_jpeg_bytes(img_buf, quality=85)
    return CommandResult("image", img_jpg, prefix_text="")


def prepare_b30(context: CommandContext, ports: B30Ports):
    m = context.match
    client = context.profile == "client"
    if not m:
        return CommandResult(
            "text",
            (
                "参数错误。示例：taikob 30 / taikob 30 精度 / taikob30 -r"
                if client
                else "参数错误。示例：taikob / taikob 30 / taikob 30 精度 / taikob30 -r"
            ),
            delivery="direct",
        )
    if client:
        N = int(m.group(1))
        args = (m.group(2) or "").strip().split()
        return (
            N,
            args,
            any(str(a).lower() == "v2" for a in args),
            any(a.lower() == "-r" for a in args),
            ports._resolve_taikob_dim_arg(args),
        )
    N = int(m.group(1) or 20)
    arg_str = (m.group(2) or "").strip()
    try:
        rating_version, arg_str = ports._extract_rating_version(arg_str)
    except ValueError as error:
        return CommandResult("text", str(error), delivery="direct")
    args = arg_str.split() if arg_str else []
    use_v2 = rating_version == "v2"
    dynamic_origin = any((a.lower() == "-r" for a in args))
    dim = ports._resolve_taikob_dim_arg(args)
    return (N, args, use_v2, dynamic_origin, dim)
