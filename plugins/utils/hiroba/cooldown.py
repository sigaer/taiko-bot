from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional
from taiko_bot.settings import get_settings

HIROBA_SYNC_COOLDOWN_PATH = get_settings().root_dir / "data" / "hiroba_sync_cooldown.json"

_lock = threading.Lock()


def _normalize_day_marker(raw_value: object) -> Optional[str]:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            try:
                raw_value = int(text)
            except (TypeError, ValueError):
                return None
    if isinstance(raw_value, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw_value)).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _load_cooldowns() -> Dict[str, str]:
    path = HIROBA_SYNC_COOLDOWN_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, str] = {}
    for key, value in payload.items():
        taiko_no = str(key or "").strip()
        if not taiko_no:
            continue
        day_marker = _normalize_day_marker(value)
        if not day_marker:
            continue
        result[taiko_no] = day_marker
    return result


def _save_cooldowns(data: Dict[str, str]) -> None:
    path = HIROBA_SYNC_COOLDOWN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _today_key(now: datetime) -> str:
    return now.date().isoformat()


def _next_midnight(now: datetime) -> datetime:
    return datetime.combine(now.date(), datetime.min.time()) + timedelta(days=1)


def _format_cooldown_message(taiko_no: str, now: datetime) -> str:
    next_available_time = _next_midnight(now)
    remaining_seconds = max(0, int((next_available_time - now).total_seconds()))
    hours, remainder = divmod(remaining_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    next_time = next_available_time.strftime("%Y-%m-%d %H:%M")
    return (
        f"Hiroba 账号 {taiko_no} 今日已触发过成绩同步，每账号每天限 1 次。"
        f"请约 {hours} 小时 {minutes} 分钟后再试（每日 0 点刷新，预计 {next_time} 后可更新）。"
    )


def peek_hiroba_sync_cooldown(taiko_no: str) -> Optional[str]:
    taiko_no = str(taiko_no or "").strip()
    if not taiko_no:
        return None
    now = datetime.now()
    today_key = _today_key(now)
    with _lock:
        last_sync_day = _load_cooldowns().get(taiko_no)
    if last_sync_day != today_key:
        return None
    return _format_cooldown_message(taiko_no, now)


def acquire_hiroba_sync_slot(taiko_no: str) -> Optional[str]:
    taiko_no = str(taiko_no or "").strip()
    if not taiko_no:
        return None
    now = datetime.now()
    today_key = _today_key(now)
    with _lock:
        data = _load_cooldowns()
        if data.get(taiko_no) == today_key:
            return _format_cooldown_message(taiko_no, now)
        data[taiko_no] = today_key
        _save_cooldowns(data)
    return None
