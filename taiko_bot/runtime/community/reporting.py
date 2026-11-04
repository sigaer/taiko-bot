"""Shared, persistent per-user reporting for center and client hosts."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ReportResult:
    status: Literal["accepted", "duplicate", "inactive", "missing", "invalid_user"]
    count: int = 0
    deactivated: bool = False

    def message(self, record_id: int) -> str:
        if self.status == "missing":
            return "该id不存在"
        if self.status == "invalid_user":
            return "无法识别举报用户，请稍后重试。"
        if self.status == "duplicate":
            return f"你已举报过你画我猜id{record_id}，请勿重复举报。"
        if self.status == "inactive":
            return f"你画我猜id{record_id}已停用，无需举报。"
        message = f"已举报你画我猜id{record_id}，本你画我猜已被{self.count}人举报！"
        if self.deactivated:
            message += f"\n你画我猜id{record_id}已删除。"
        return message


async def submit_report(
    record_id: int,
    reporter_id: str,
    *,
    lock: asyncio.Lock,
    load_db: Callable[[], dict[str, Any]],
    save_db: Callable[[dict[str, Any]], None],
    threshold: int,
) -> ReportResult:
    """Check identity, count and deactivate in the same storage transaction.

    Old anonymous counts cannot establish distinct reporters. On the first new
    report, the persisted reporter list becomes the sole counting authority.
    Existing inactive records are never reactivated.
    """
    reporter_id = reporter_id.strip()
    if not reporter_id:
        return ReportResult("invalid_user")

    async with lock:
        data = load_db()
        record = next(
            (item for item in data["records"] if item["id"] == record_id), None
        )
        if record is None:
            return ReportResult("missing")
        raw_reporters = record.get("reporter_ids")
        reporters = list(dict.fromkeys(
            value.strip() for value in raw_reporters
            if isinstance(value, str) and value.strip()
        )) if isinstance(raw_reporters, list) else []
        if reporter_id in reporters:
            return ReportResult("duplicate", len(reporters))
        if not record.get("active", True):
            return ReportResult("inactive", len(reporters))

        reporters.append(reporter_id)
        record["reporter_ids"] = reporters
        record["report_count"] = len(reporters)
        deactivated = len(reporters) >= threshold
        if deactivated:
            record["active"] = False
        save_db(data)
        return ReportResult("accepted", len(reporters), deactivated)
