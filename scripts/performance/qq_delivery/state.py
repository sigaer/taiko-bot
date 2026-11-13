from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from .config import Blocked, Config, private_directory


def atomic_json(path: Path, data) -> None:
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    try:
        with open(temporary, "x", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


class State:
    def __init__(self, config: Config):
        self.config = config
        self.directory = Path(config.private_dir)
        private_directory(self.directory)
        self.path = self.directory / "state.json"
        self.data = None

    @contextmanager
    def locked(self):
        with open(self.directory / "probe.lock", "a", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Blocked("another_probe_is_running") from None
            try:
                if self.path.exists():
                    if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                        raise Blocked("private_state_permissions")
                    self.data = json.loads(self.path.read_text())
                else:
                    self.data = dict(schema=1, salt=secrets.token_hex(32), rows=[], rounds={},
                                     used_events=[], blocked_modes=[], media=None, public_image=None,
                                     last_finished=0, paused=False)
                scope = self.digest(self.config.bot_id + "\0" + self.config.group_openid)
                if self.data.get("scope", scope) != scope:
                    raise Blocked("state_target_mismatch")
                self.data["scope"] = scope
                for row in self.data["rows"]:
                    if row["status"] == "pending":
                        row["status"] = "unknown"
                self.save()
                yield self
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def digest(self, value: str) -> str:
        return hashlib.sha256((self.data["salt"] + value).encode()).hexdigest()

    def save(self) -> None:
        atomic_json(self.path, self.data)

    def reserve(self, mode: str, event_id: str, image_sha256: str, now=None):
        now = time.time() if now is None else now
        if self.data["paused"]:
            raise Blocked("experiment_paused")
        if any(r["status"] in ("pending", "unknown") and not r.get("resolved") for r in self.data["rows"]):
            raise Blocked("manual_check_of_unknown_result_required")
        if mode in self.data["blocked_modes"]:
            raise Blocked("mode_stopped_after_failure")
        if now - self.data["last_finished"] < self.config.interval_seconds:
            raise Blocked("minimum_interval_not_elapsed")
        event_hash = self.digest(event_id)
        if event_hash in self.data["used_events"]:
            raise Blocked("event_already_consumed")
        rounds = self.data["rounds"]
        used = rounds.get(self.config.round_id, 0)
        if used >= self.config.max_sends_per_round:
            raise Blocked("round_send_budget_exhausted")
        same = [r for r in self.data["rows"] if r["mode"] == mode and r["phase"] == self.config.phase]
        limit = min(3, self.config.max_samples_per_mode) if self.config.phase == "protocol" else self.config.max_samples_per_mode
        if len(same) >= limit:
            raise Blocked("mode_sample_budget_exhausted")
        if self.config.phase == "performance" and not self.passed(mode):
            raise Blocked("mode_protocol_not_verified_on_client")
        if self.config.phase == "performance" and not any(
            self.passed(m) for m in ("B-data", "B-url")
        ) and mode.startswith("B"):
            raise Blocked("active_protocol_not_verified")
        rounds[self.config.round_id] = used + 1
        self.data["used_events"].append(event_hash)
        row = dict(sample=secrets.token_hex(6), mode=mode, phase=self.config.phase,
                   round_id=self.config.round_id, status="pending", started_at=now,
                   image_sha256=image_sha256, image_bytes=0, calls=[], observations=[],
                   transport=self.config.transport, ttl_seconds=None, receipt_id_present=False,
                   active_quota_before=None, active_quota_after=None, error=None)
        self.data["rows"].append(row)
        self.data["last_finished"] = now
        self.save()  # Persist before any side effect. Crashes never release this reservation.
        return row

    def passed(self, mode):
        rows = [r for r in self.data["rows"] if r["mode"] == mode and r["phase"] == "protocol"
                and any(c.get("http_requests",0) for c in r["calls"])]
        return bool(rows) and mode not in self.data["blocked_modes"] and rows[-1]["status"] == "acknowledged" and any(
            o.get("device") == "android" and o.get("received") is True
            and o.get("duplicates") == 0 and o.get("render_ok") is True
            for o in rows[-1]["observations"]
        )
