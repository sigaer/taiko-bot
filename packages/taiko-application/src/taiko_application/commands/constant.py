from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class ConstantPorts:
    DEFAULT_PAGE_SIZE: Any
    paginate_rows: Callable[..., Any]
    query_charts_by_const: Callable[..., Any]
    render_const_query_image: Callable[..., Any]
    render_const_query_notice: Callable[..., Any]


def execute_constant(
    context: CommandContext, ports: ConstantPorts
) -> CommandResult | None:
    match = context.match
    const_text = match.group(1)
    extra_text = (match.group(2) or "").strip()
    try:
        const_value = float(const_text)
    except ValueError:
        return CommandResult("text", "定数格式错误，示例：查定数6.6", delivery="reply")
    page = 1
    include_shelf_status = False
    for token in extra_text.split():
        if token in ("含下架", "下架"):
            include_shelf_status = True
            continue
        try:
            page = int(token)
        except ValueError:
            return CommandResult(
                "text",
                "参数错误。示例：查定数6.6 / 查定数8.5 2 / 查定数6.6 含下架",
                delivery="reply",
            )
        if page < 1:
            return CommandResult(
                "text", "页码必须是正整数，示例：查定数8.5 2", delivery="reply"
            )
    rows = ports.query_charts_by_const(
        const_value, include_shelf_status=include_shelf_status
    )
    if not rows:
        if (
            context.profile == "center"
            and not include_shelf_status
            and ports.query_charts_by_const(const_value, include_shelf_status=True)
        ):
            png = ports.render_const_query_notice(
                f"定数 {const_value:g} 暂无未下架曲目，发送「查定数{const_value:g} 含下架」可查看全部曲目。"
            )
        else:
            png = ports.render_const_query_notice(
                f"未找到定数 {const_value:g} 的曲目。"
            )
        return CommandResult("image", png, prefix_text="")
    total_pages = max(
        1, (len(rows) + ports.DEFAULT_PAGE_SIZE - 1) // ports.DEFAULT_PAGE_SIZE
    )
    if extra_text and page > total_pages:
        return CommandResult(
            "text",
            f"定数 {const_value:g} 共 {len(rows)} 首，有效页码 1-{total_pages}。",
            delivery="reply",
        )
    page_rows, page, total_pages = ports.paginate_rows(rows, page=page)
    global_offset = (page - 1) * ports.DEFAULT_PAGE_SIZE
    png = ports.render_const_query_image(
        const_value,
        page_rows,
        page=page,
        global_offset=global_offset,
        total_count=len(rows),
        total_pages=total_pages,
        show_shelf_status=include_shelf_status,
    )
    return CommandResult("image", png, prefix_text="")
