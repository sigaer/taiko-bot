"""Read-only OurTaiko fanmade search and plain-text result presentation."""
from __future__ import annotations

import asyncio
import json
import re

import httpx

API_URL = "https://fanmade.ourtaiko.org/api/v1/charts"
SITE_URL = "https://fanmade.ourtaiko.org"
COMMAND_PATTERN = r"^/?(?:(?:taiko|太鼓)\s+)?查自制(?P<args>.*)$"
COMMAND = re.compile(COMMAND_PATTERN, re.I | re.S)
USAGE = "用法：查自制 关键词\n翻页：查自制 关键词 第2页"
COURSES = {"Easy": "简单", "Normal": "普通", "Hard": "困难", "Oni": "魔王", "Edit": "里谱"}


class FanmadeUnavailable(Exception):
    """The remote service failed or returned an unsupported response."""


def parse_query(text: str) -> tuple[str, int]:
    match = COMMAND.fullmatch(text.strip())
    if not match:
        raise ValueError(USAGE)
    keyword = match["args"].strip()
    page = 1
    suffix = re.search(r"(?:^|\s+)第([0-9]+)页$", keyword)
    if suffix:
        digits = suffix[1]
        if len(digits) > 6 or int(digits) < 1:
            raise ValueError("页码须为 1～999999 的整数。\n" + USAGE)
        page = int(digits)
        keyword = keyword[:suffix.start()].strip()
    if not keyword:
        raise ValueError(USAGE)
    if len(keyword) > 100:
        raise ValueError("搜索关键词请控制在 100 字以内。")
    return keyword, page


async def search(keyword: str, page: int = 1) -> dict:
    try:
        # The overall deadline also bounds slow streams and connection setup.
        async with asyncio.timeout(12):
            async with httpx.AsyncClient(timeout=8) as client:
                async with client.stream("GET", API_URL, params={"q": keyword, "page": page}) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1024 * 1024:
                            raise ValueError("fanmade response too large")
                payload = json.loads(body)
        validate_result(payload, page)
        return payload
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError) as exc:
        raise FanmadeUnavailable from exc


def validate_result(payload: object, page: int) -> None:
    if not isinstance(payload, dict):
        raise ValueError("invalid fanmade result")
    if any(type(payload.get(key)) is not int for key in ("total", "page", "pageSize")):
        raise ValueError("invalid fanmade pagination")
    if payload["total"] < 0 or payload["page"] != page or not 1 <= payload["pageSize"] <= 20:
        raise ValueError("invalid fanmade pagination")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > payload["pageSize"]:
        raise ValueError("invalid fanmade items")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            raise ValueError("invalid fanmade chart")
        if not re.fullmatch(r"[0-9a-f]{32}", str(item.get("id", ""))):
            raise ValueError("invalid fanmade chart id")
        if item.get("difficulties") is not None and not isinstance(item["difficulties"], list):
            raise ValueError("invalid fanmade difficulties")


def _text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _difficulties(item: dict) -> str:
    labels = []
    for difficulty in (item.get("difficulties") or [])[:15]:
        if not isinstance(difficulty, dict):
            continue
        course = difficulty.get("course")
        level = difficulty.get("level")
        if not isinstance(course, str) or course not in COURSES or type(level) is not int:
            continue
        side = {"p1": "双打P1", "p2": "双打P2"}.get(str(difficulty.get("side")), "")
        labels.append(f"{COURSES[course]}{side}★{level}")
    return _text(" / ".join(labels), 70) or "难度未标注"


def format_result(keyword: str, payload: dict) -> str:
    total, page, size = (payload[key] for key in ("total", "page", "pageSize"))
    pages = max(1, (total + size - 1) // size)
    if not payload["items"]:
        if total:
            return f"这一页没有自制谱结果，共 {total} 条、{pages} 页。\n请发送：查自制 {keyword} 第1页"
        return f"未找到与「{keyword}」匹配的自制谱。"
    sections = [f"自制谱搜索「{keyword}」：共 {total} 条，第 {page}/{pages} 页"]
    for index, item in enumerate(payload["items"], (page - 1) * size + 1):
        maker = _text(item.get("maker"), 28) or "未标注"
        sections.append(
            f"{index}. {_text(item['title'], 40)}\n"
            f"谱师：{maker}｜{_difficulties(item)}\n"
            f"{SITE_URL}/charts/{item['id']}"
        )
    if page < pages:
        sections.append(f"下一页：查自制 {keyword} 第{page + 1}页")
    return "\n\n".join(sections)
