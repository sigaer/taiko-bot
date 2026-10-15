"""Official QQ command transport; report computation stays in the Viewer service."""
from __future__ import annotations

import os
import json
import time

import httpx
from nonebot import logger
from ...player.center.messages import (
    get_identity_key, is_qq_official_event, _load_qq_quick_action_api,
    _build_qq_markdown_image_block, _is_qq_passive_reply_limit_error, _send_qq_proactive,
)
from ...player.center.qq_markdown_media import cache_markdown_image_url

COMMANDS = frozenset({
    '2025版本总结', '2025年度报告', '2025版本报告', '2025年度总结',
    '虹2025年度报告', '虹2025版本总结', '虹2025版本报告', '虹2025年度总结',
})
REPORT_URL = 'https://viewer.sakura-bot.cn/annual'
REPORT_TEXT = '完整版报告请移步至Viewer网页端查看~'
_active: set[str] = set()
_cooldown: dict[str, float] = {}


class AnnualReportError(RuntimeError):
    pass


async def fetch_annual_card(identity: str) -> bytes:
    token = os.getenv('TAIKO_BOT_SERVICE_TOKEN', '').strip()
    if not token:
        raise AnnualReportError('版本总结服务暂未配置，请先在 Viewer 网页端查看。')
    base = os.getenv('TAIKO_VIEWER_INTERNAL_BASE_URL', 'http://127.0.0.1:3100').rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=5.0), trust_env=False) as client:
            async with client.stream('POST', base + '/api/taiko/internal/annual-card',
                                     headers={'X-Taiko-Bot-Token': token}, json={'identityKey': identity}) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    try:
                        error = json.loads(raw)
                        message = error.get('statusMessage') or error.get('message')
                    except (ValueError, AttributeError):
                        message = None
                    raise AnnualReportError(message if response.status_code in (400, 403, 404, 409, 422, 429, 503) and message else '版本总结暂时无法生成，请稍后再试。')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 20 * 1024 * 1024:
                        raise AnnualReportError('版本总结图片暂时不可用，请在 Viewer 网页端查看。')
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise AnnualReportError('版本总结图片暂时不可用，请在 Viewer 网页端查看。')
        return bytes(data)
    except httpx.TimeoutException as exc:
        raise AnnualReportError('报告仍在等待或生成中，请稍后重新查询，也可以前往 Viewer 网页端查看。') from exc
    except httpx.HTTPError as exc:
        raise AnnualReportError('版本总结服务暂时不可用，请稍后再试。') from exc


def build_report_message(image: bytes):
    (Message, Segment, Keyboard, Inline, Row, Button, Render, Action, Permission) = _load_qq_quick_action_api()
    url = cache_markdown_image_url(image, prefix='annual-2025')
    keyboard = Keyboard(content=Inline(rows=[Row(buttons=[Button(
        id='annual_2025_viewer', render_data=Render(label='查看完整版报告', visited_label='查看完整版报告', style=1),
        action=Action(type=0, permission=Permission(type=2), data=REPORT_URL,
                      unsupport_tips='请使用浏览器打开 viewer.sakura-bot.cn/annual'),
    )])]))
    message = Message()
    message += Segment.markdown(_build_qq_markdown_image_block(url, image) + '\n\n' + REPORT_TEXT)
    message += Segment.keyboard(keyboard)
    return message


async def handle_annual_report(matcher, event) -> None:
    if not is_qq_official_event(event):
        return
    identity = get_identity_key(event=event)
    now = time.monotonic()
    if identity in _active:
        await matcher.finish('你的版本总结正在处理中，请稍候。')
    if _cooldown.get(identity, 0) > now:
        await matcher.finish('查询过于频繁，请稍后再试。')
    if len(_active) >= 4:
        await matcher.finish('版本总结服务繁忙，请稍后再试。')
    if len(_cooldown) >= 5000:
        for key in list(_cooldown):
            if _cooldown[key] <= now:
                _cooldown.pop(key, None)
        if len(_cooldown) >= 5000:
            await matcher.finish('版本总结服务繁忙，请稍后再试。')
    _active.add(identity)
    _cooldown[identity] = now + 30
    try:
        image = await fetch_annual_card(identity)
        message = build_report_message(image)
        try:
            await matcher.send(message)
        except Exception as exc:
            if not _is_qq_passive_reply_limit_error(exc) or not await _send_qq_proactive(matcher, event, message):
                raise
    except AnnualReportError as exc:
        await matcher.send(str(exc))
    except Exception:
        logger.exception('Official QQ annual report delivery failed')
        await matcher.send('版本总结发送失败，请前往 Viewer 网页端查看。')
    finally:
        _active.discard(identity)
