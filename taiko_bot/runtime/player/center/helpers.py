from __future__ import annotations
from typing import *
from io import BytesIO
from PIL import Image
from taiko_application.commands import CommandResult
from .messages import *
async def _finish_text_reply(
    matcher: Matcher,
    event: MessageEvent,
    text: str,
    *,
    quick_actions: Optional[bool] = None,
    markdown_text: Optional[str] = None,
) -> None:
    attach_quick_actions = (
        _should_attach_quick_actions_to_text(event, text)
        if quick_actions is None
        else bool(quick_actions)
    )
    resolved_markdown_text = markdown_text
    if resolved_markdown_text is None and text == _taiko_bind_usage_message(event):
        resolved_markdown_text = _taiko_bind_usage_markdown_message(event)
    await send_text_reply(
        matcher,
        event,
        text,
        quick_actions=attach_quick_actions,
        markdown_text=resolved_markdown_text,
    )


async def _finish_image_reply(
    matcher: Matcher,
    event: MessageEvent,
    image_bytes: bytes | BytesIO | Path,
    prefix_text: str = "",
    *,
    quick_actions: bool = False,
    prefer_markdown_image: bool = False,
    markdown_image_name: str = "taiko",
) -> None:
    await send_image_reply(
        matcher,
        event,
        image_bytes,
        prefix_text=prefix_text,
        quick_actions=quick_actions,
        prefer_markdown_image=prefer_markdown_image,
        markdown_image_name=markdown_image_name,
    )


def _to_jpeg_bytes(img_buf: bytes | BytesIO, quality: int = 85) -> bytes:
    if isinstance(img_buf, BytesIO):
        data = img_buf.getvalue()
    else:
        data = img_buf
    img = Image.open(BytesIO(data))
    if img.mode in ("RGBA", "LA"):
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img, mask=img.split()[-1])
        img = base
    else:
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""


def _resolve_requested_identity_key(event: MessageEvent) -> Tuple[str, bool]:
    self_identity = _normalize_identity_key(get_identity_key(event=event))
    target_identity = _normalize_identity_key(resolve_target_identity_key(event=event))
    is_self_query = self_identity == target_identity
    return target_identity or self_identity, is_self_query


def _taiko_bind_usage_message(event: Optional[MessageEvent] = None) -> str:
    base = (
        "请先绑定账号。\n"
        "国服/CN：发送“绑定 你的鼓众广场ID”或“绑定+你的鼓众广场ID”进行绑定。\n"
        "日服/JP：可直接发送“绑定 12位Hiroba太鼓番”绑定，默认通过服务账号读取公开成绩；"
        "若账号设为非公开，可再发送“绑定hiroba 邮箱 密码 [太鼓番]”。"
    )
    if event is not None and is_qq_official_event(event):
        return (
            f"{base}\n"
            "如果您以前在其他搭建了 Sakura Taiko 模块的 bot 上绑定过数据，"
            "可用原 QQ 私聊旧 bot 发送“迁移验证码”，再私聊这里发送“绑定QQ QQ号 验证码”。\n"
            "验证码十分钟内有效。"
        )
    return base


def _build_fuzzy_query_hint(results: List[List[Any]]) -> str:
    title = results[0][1]
    ratio = float(results[0][2]) / 100.0
    return f"你要找的可能是：{title}\n匹配度：{ratio:.2f}"


async def _deliver_application_command(matcher, event, result):
    """Keep permission-aware reply/media delivery in the Sakura adapter."""
    if result is None:
        return
    if result.kind == "silent":
        await matcher.finish()
    elif result.kind == "text":
        if result.delivery == "direct":
            await matcher.finish(result.payload)
        else:
            await _finish_text_reply(matcher, event, result.payload)
    elif result.kind == "image":
        if result.prefix_text:
            await _finish_image_reply(
                matcher, event, result.payload, prefix_text=result.prefix_text
            )
        else:
            await _finish_image_reply(matcher, event, result.payload)
    elif result.kind == "fumen":
        difficulty, song_id = result.payload
        await _send_fumen_or_hint(matcher, event, difficulty, song_id)
    elif result.kind == "fuzzy_fumen":
        await _finish_fuzzy_query_with_fumen(
            matcher, event, result.payload, difficulty=result.difficulty
        )
    else:
        raise ValueError("Unsupported command result")

QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS = (
    "请先绑定账号",
    "请输入正确",
    "参数错误",
    "查不到呢",
    "失败",
    "未找到",
    "暂无",
    "没有可用于",
    "没有可用",
    "没有待确认",
    "请更新数据后",
    "还未上传数据",
    "查询失败",
    "生成失败",
    "推荐计算失败",
    "验证未通过",
    "请确认",
    "请检查",
    "未支持",
    "未完成",
    "未找到该鼓众ID",
    "缺少登录cookie",
    "当前未绑定",
    "该歌曲没有",
    "未找到匹配",
    "未找到满足",
)


def _should_attach_quick_actions_to_text(event: MessageEvent, text: str) -> bool:
    if not is_qq_official_group_event(event):
        return False
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(
        keyword in normalized for keyword in QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS
    )


def _taiko_bind_usage_markdown_message(
    event: Optional[MessageEvent] = None,
) -> str:
    lines = [
        "# 请先绑定账号",
        "> 当前还没有可用的成绩数据，请先完成绑定再继续查询或更新。",
        "",
        "## 国服 / CN",
        "- 发送 `绑定 你的鼓众广场ID`",
        "- 或发送 `绑定+你的鼓众广场ID`",
        "",
        "## 日服 / JP",
        "- 公开资料：发送 `绑定 12位Hiroba太鼓番`",
        "- 非公开资料：发送 `绑定hiroba 邮箱 密码 [太鼓番]`",
        "",
        "## 推荐操作",
        "1. 点击下方 `绑定` 按钮自动填入命令",
        "2. 把自己的 `鼓众广场ID / Hiroba太鼓番` 补完整后发送",
        "3. 绑定完成后点击 `更新广场` 拉取成绩数据",
    ]
    if event is not None and is_qq_official_event(event):
        lines.extend(
            [
                "",
                "## 旧绑定迁移",
                "- 如果你以前在其他 Sakura Taiko bot 上绑定过，可点击下方 `旧绑定迁移`",
                "- 用原 QQ 私聊旧 bot 发送 `迁移验证码`，再私聊这里发送 `绑定QQ QQ号 验证码`",
                "> 验证码十分钟内有效。",
            ]
        )
    return "\n".join(lines)
