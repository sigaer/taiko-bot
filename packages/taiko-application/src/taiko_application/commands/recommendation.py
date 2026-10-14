from __future__ import annotations
import re
from typing import Any, Callable
from dataclasses import dataclass
from .models import CommandContext, CommandResult


@dataclass(frozen=True)
class RecommendationPorts:
    DIM_MAP: Any
    FONT_PATH: Any
    TAIKOREC_COMMAND_EXTRACT_RE: Any
    compute_recommendations_for_user: Callable[..., Any]
    compute_target_recommendations_for_user: Callable[..., Any]
    generate_recommend_image: Callable[..., Any]
    parse_target_recommendation_request: Callable[..., Any]
    print: Callable[..., Any]
    render_target_recommendation_image_bytes: Callable[..., Any]
    target_recommendation_displays: Callable[..., Any]
    report_target_error: Callable[[Exception], Any] | None = None


@dataclass(frozen=True)
class RecommendationRequest:
    basis: str = "rating"
    dimension: str = "rating"
    limit: int = 20
    target_key: str | None = None
    star_filter: str | None = None


@dataclass(frozen=True)
class PreparedRecommendationCommand:
    """Host-captured result; contains no provider, storage handle or callback."""
    request: RecommendationRequest | CommandResult
    image: bytes | None = None
    failure: str | None = None
    missing_hint: str = ""
    target_message: str | None = None


def prepare_recommendation(context: CommandContext, ports):
    msg_text = context.text.strip()
    m = ports.TAIKOREC_COMMAND_EXTRACT_RE.match(msg_text)
    tail = (m.group(1) if m else "") or ""
    tail = tail.strip()
    if tail:
        target_key, target_star_filter, target_error = (
            ports.parse_target_recommendation_request(tail)
        )
        if target_key:
            if target_error == "too_many_args":
                return CommandResult(
                    "text",
                    (
                        "目标推荐固定返回20首，仅支持附加一个难度筛选。示例：推荐歌曲 紫雅 9星"
                        if context.profile == "client"
                        else "目标推荐最多返回20首，仅支持附加一个难度筛选。示例：推荐歌曲 紫雅 9星"
                    ),
                    delivery="reply",
                )
            if target_error == "invalid_star":
                return CommandResult(
                    "text",
                    "难度筛选仅支持 1-10、1星-10星 或 一星-十星。示例：推荐歌曲 紫雅 9星",
                    delivery="reply",
                )
            return RecommendationRequest(target_key=target_key, star_filter=target_star_filter)
    dim_in = "rating"
    n_in = "20"
    if tail:
        parts = tail.split()
        if len(parts) >= 2:
            dim_in = parts[0]
            n_in = parts[1]
        else:
            token = parts[0]
            if token.isdigit():
                n_in = token
            else:
                m2 = re.match("^(.*?)(\\d{1,2})$", token)
                if m2 and m2.group(1):
                    dim_in = m2.group(1)
                    n_in = m2.group(2)
                else:
                    dim_in = token
    dim_key = ports.DIM_MAP.get(dim_in, None)
    if not dim_key:
        return CommandResult(
            "text",
            "维度不支持。可用：rating/综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理；目标推荐可用："
            + ports.target_recommendation_displays(),
            delivery="reply",
        )
    try:
        limit = int(n_in)
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50
    except Exception:
        limit = 20
    return RecommendationRequest(basis=dim_key, dimension=dim_in, limit=limit)


def execute_recommendation(context, ports=None):
    if isinstance(context, PreparedRecommendationCommand):
        if isinstance(context.request, CommandResult):
            return context.request
        if context.failure:
            message = context.missing_hint if context.failure == "missing" else (
                ("目标推荐" if context.request.target_key else "推荐")
                + "计算失败，请检查曲库/数据匹配是否正常"
            )
            return CommandResult("text", message, delivery="reply")
        if context.target_message is not None:
            return CommandResult("text", context.target_message, delivery="reply")
        if not isinstance(context.image, bytes):
            raise TypeError("Prepared recommendation requires image bytes")
        return CommandResult("image", context.image, prefix_text="")
    request = prepare_recommendation(context, ports)
    if isinstance(request, CommandResult):
        return request
    taiko_id = context.user_id
    if request.target_key:
        try:
            result = ports.compute_target_recommendations_for_user(
                user_id=taiko_id,
                target_key=request.target_key,
                star_filter=request.star_filter,
            )
        except FileNotFoundError:
            return CommandResult(
                "text", context.missing_userdata_hint(), delivery="reply"
            )
        except Exception as e:
            (ports.report_target_error or ports.print)(e)
            return CommandResult(
                "text",
                "目标推荐计算失败，请检查曲库/数据匹配是否正常",
                delivery="reply",
            )
        if not result.is_enough:
            return CommandResult("text", result.message, delivery="reply")
        img_buf = ports.render_target_recommendation_image_bytes(
            user_id=taiko_id,
            userdata=result.userdata,
            target_display=result.target_display,
            rows=result.rows,
            font_path=ports.FONT_PATH,
        )
        return CommandResult("image", img_buf, prefix_text="")
    try:
        recs = ports.compute_recommendations_for_user(
            user_id=taiko_id,
            best_key=request.basis,
            limit=request.limit,
            json_path=context.rating_path,
        )
    except FileNotFoundError as e:
        ports.print(e)
        return CommandResult("text", context.missing_userdata_hint(), delivery="reply")
    except Exception as e:
        ports.print(e)
        return CommandResult(
            "text", "推荐计算失败，请检查曲库/数据匹配是否正常", delivery="reply"
        )
    subtitle = f"维度：{request.dimension}  数量：{request.limit}"
    img_buf = ports.generate_recommend_image(
        recs,
        title="以下是可供参考的推荐歌曲",
        subtitle=subtitle,
        user_id=int(taiko_id),
        font_path=ports.FONT_PATH,
    )
    return CommandResult("image", img_buf, prefix_text="")
