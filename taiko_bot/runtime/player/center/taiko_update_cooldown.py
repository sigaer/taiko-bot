from __future__ import annotations


import threading

import time

from typing import Dict

TAIKO_UPDATE_COOLDOWN_SECONDS = 3 * 60

_lock = threading.Lock()

_last_triggered_at: Dict[str, float] = {}

def try_acquire_taiko_update_slot(taiko_id: str) -> bool:
    """Reserve an update slot for an ID, returning False during cooldown."""
    normalized_id = str(taiko_id or "").strip()
    if not normalized_id:
        return True

    now = time.monotonic()
    with _lock:
        expired_before = now - TAIKO_UPDATE_COOLDOWN_SECONDS
        expired_ids = [
            stored_id
            for stored_id, triggered_at in _last_triggered_at.items()
            if triggered_at <= expired_before
        ]
        for stored_id in expired_ids:
            _last_triggered_at.pop(stored_id, None)

        last_triggered_at = _last_triggered_at.get(normalized_id)
        if (
            last_triggered_at is not None
            and now - last_triggered_at < TAIKO_UPDATE_COOLDOWN_SECONDS
        ):
            return False

        _last_triggered_at[normalized_id] = now
        return True
