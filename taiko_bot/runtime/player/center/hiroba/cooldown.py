from __future__ import annotations
from taiko_bot.runtime.paths import root as _runtime_root




import json

import os

import threading

from datetime import datetime, timedelta

from pathlib import Path

from typing import Dict, Optional

HIROBA_SYNC_COOLDOWN_PATH = Path(os.getenv("TAIKO_HIROBA_COOLDOWN_PATH") or str(_runtime_root() / 'data/hiroba_sync_cooldown.json'))

_lock = threading.Lock()

HIROBA_SYNC_COOLDOWN = timedelta(hours=1)

def _normalize_sync_timestamp(raw_value: object) -> Optional[int]:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        try:
            return int(datetime.fromisoformat(text).timestamp())
        except ValueError:
            try:
                raw_value = int(text)
            except (TypeError, ValueError):
                return None
    if isinstance(raw_value, (int, float)):
        try:
            timestamp = int(raw_value)
            datetime.fromtimestamp(timestamp)
            return timestamp if timestamp > 0 else None
        except (OSError, OverflowError, ValueError):
            return None
    return None

def _load_cooldowns() -> Dict[str, int]:
    path = HIROBA_SYNC_COOLDOWN_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, int] = {}
    for key, value in payload.items():
        taiko_no = str(key or "").strip()
        if not taiko_no:
            continue
        sync_timestamp = _normalize_sync_timestamp(value)
        if sync_timestamp is None:
            continue
        result[taiko_no] = sync_timestamp
    return result

def _save_cooldowns(data: Dict[str, int]) -> None:
    path = HIROBA_SYNC_COOLDOWN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

def _next_available_time(last_sync_timestamp: int) -> datetime:
    return datetime.fromtimestamp(last_sync_timestamp) + HIROBA_SYNC_COOLDOWN

def _format_cooldown_message(
    taiko_no: str,
    now: datetime,
    last_sync_timestamp: int,
) -> str:
    next_available_time = _next_available_time(last_sync_timestamp)
    remaining_minutes = max(
        1,
        int((next_available_time - now).total_seconds() + 59) // 60,
    )
    hours, minutes = divmod(remaining_minutes, 60)
    remaining_text = (
        f"{hours} 小时 {minutes} 分钟" if hours else f"{minutes} 分钟"
    )
    next_time = next_available_time.strftime("%Y-%m-%d %H:%M")
    return (
        f"Hiroba 账号 {taiko_no} 最近 1 小时内已触发过成绩同步，每账号每小时限 1 次。"
        f"请约 {remaining_text}后再试（预计 {next_time} 后可更新）。"
    )

def peek_hiroba_sync_cooldown(taiko_no: str) -> Optional[str]:
    taiko_no = str(taiko_no or "").strip()
    if not taiko_no:
        return None
    now = datetime.now()
    with _lock:
        last_sync_timestamp = _load_cooldowns().get(taiko_no)
    if last_sync_timestamp is None:
        return None
    if now >= _next_available_time(last_sync_timestamp):
        return None
    return _format_cooldown_message(taiko_no, now, last_sync_timestamp)

def acquire_hiroba_sync_slot(taiko_no: str) -> Optional[str]:
    taiko_no = str(taiko_no or "").strip()
    if not taiko_no:
        return None
    now = datetime.now()
    with _lock:
        data = _load_cooldowns()
        last_sync_timestamp = data.get(taiko_no)
        if (
            last_sync_timestamp is not None
            and now < _next_available_time(last_sync_timestamp)
        ):
            return _format_cooldown_message(
                taiko_no,
                now,
                last_sync_timestamp,
            )
        data[taiko_no] = int(now.timestamp())
        _save_cooldowns(data)
    return None

def release_hiroba_sync_slot(taiko_no: str) -> None:
    taiko_no = str(taiko_no or "").strip()
    if not taiko_no:
        return
    with _lock:
        data = _load_cooldowns()
        if taiko_no not in data:
            return
        data.pop(taiko_no, None)
        _save_cooldowns(data)
