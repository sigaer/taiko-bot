from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class ProgressPorts:
    STAR_PROGRESS_REGEX: Any
    _load_decimal_progress_set: Callable[..., Any]
    _load_pass_progress_set: Callable[..., Any]
    _load_progress_name_set: Callable[..., Any]
    _load_star_progress_set: Callable[..., Any]
    _parse_star_progress_value: Callable[..., Any]
    parse_dani_progress_request: Callable[..., Any]
    render_dani_progress_image_bytes: Callable[..., Any]
    render_pass_progress_image_bytes: Callable[..., Any]
    render_progress_image_bytes: Callable[..., Any]
    render_progress_image_bytes_by_list: Callable[..., Any]
    render_star_progress_image_bytes: Callable[..., Any]


def execute_progress(
    context: CommandContext, ports: ProgressPorts, prepared
) -> CommandResult | None:
    text, page = prepared
    taiko_id = context.user_id
    dani_request = ports.parse_dani_progress_request(text)
    if dani_request:
        png = ports.render_dani_progress_image_bytes(
            user_id=taiko_id,
            grade_name=dani_request["grade"],
            version=dani_request["version"],
            explicit_version=dani_request.get("explicitVersion") == "1",
        )
        return CommandResult("image", png, prefix_text="")
    m = re.fullmatch("^(?P<decimal>\\d+\\.\\d)(?P<mode>综合|过关|定数)?进度$", text)
    if m:
        decimal = m.group("decimal")
        mode = m.group("mode") or ""
        dynamic_available = decimal in ports._load_decimal_progress_set()
        pass_available = decimal in ports._load_pass_progress_set()
        if mode == "过关":
            if not pass_available:
                return CommandResult(
                    "text",
                    f"{decimal} 暂无过关难度进度表，可尝试“{decimal}综合进度”",
                    delivery="reply",
                )
            png = ports.render_pass_progress_image_bytes(
                user_id=taiko_id, decimal=decimal, page=page
            )
        elif mode in {"综合", "定数"}:
            if not dynamic_available:
                return CommandResult(
                    "text",
                    f"{decimal} 暂无综合难度进度表，可尝试“{decimal}过关进度”",
                    delivery="reply",
                )
            png = ports.render_progress_image_bytes(
                user_id=taiko_id, decimal=decimal, page=page
            )
        elif pass_available:
            png = ports.render_pass_progress_image_bytes(
                user_id=taiko_id, decimal=decimal, page=page
            )
        elif dynamic_available:
            png = ports.render_progress_image_bytes(
                user_id=taiko_id, decimal=decimal, page=page
            )
        else:
            return
        return CommandResult("image", png, prefix_text="")
    m = ports.STAR_PROGRESS_REGEX.fullmatch(text)
    if m:
        star_value = ports._parse_star_progress_value(m.group("star"))
        if star_value is None:
            return
        if star_value not in ports._load_star_progress_set():
            return
        png = ports.render_star_progress_image_bytes(
            user_id=taiko_id, star_value=star_value, page=page
        )
        return CommandResult("image", png, prefix_text="")
    text = re.sub("个", "個", text)
    text = re.sub("底", "地", text)
    text = text.upper()
    progress_name = text[:-2]
    if progress_name not in ports._load_progress_name_set():
        return
    png = ports.render_progress_image_bytes_by_list(
        user_id=taiko_id,
        progress_name=progress_name,
        assets_base=context.assets_base,
        page=page,
    )
    return CommandResult("image", png, prefix_text="")


def prepare_progress(context: CommandContext, ports: ProgressPorts):
    page_match = context.match
    if not page_match:
        return
    text = page_match.group("body").strip()
    page = int(page_match.group("page") or "1")
    if page <= 0:
        return CommandResult(
            "text", "页码必须是正整数，示例：6星进度 2", delivery="reply"
        )
    return (text, page)
