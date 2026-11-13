from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("A-data", "A-url", "B-data", "B-url", "C", "D")


class Blocked(Exception):
    """Only fixed machine-readable reasons may cross the private boundary."""

    def __init__(self, reason, *, http_status=None):
        super().__init__(reason)
        self.http_status = http_status if type(http_status) is int else None


@dataclass(repr=False)
class Config:
    bot_id: str = ""
    group_openid: str = ""
    admin_openids: list[str] = field(default_factory=list)
    active_test_authorized: bool = False
    max_sends_per_round: int = 0
    round_id: str = "preflight-1"
    interval_seconds: float = 25
    phase: str = "protocol"
    max_samples_per_mode: int = 10
    extended_test_authorized: bool = False
    active_performance_authorized: bool = False
    runtime_env_file: str = "/home/sigaer/taiko/.env.prod"
    private_dir: str = ""
    static_root: str = ""
    static_base_url: str = ""
    static_ttl_seconds: int = 600
    cleanup_timer_unit: str = "taiko-qq-delivery-probe-cleanup.timer"
    markdown_authorized: bool = False
    domain_whitelisted: bool = False
    domain_preflight_authorized: bool = False
    external_access_verified: bool = False
    external_probe_proxy: str = ""
    active_permission: bool | None = None
    group_active_allowed: bool | None = None
    transport: str = "adapter"
    timeout_seconds: float = 30

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise Blocked("private_config_permissions")
            if info.st_uid not in (0, os.getuid()):
                raise Blocked("private_config_owner")
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
                raise Blocked("private_config_schema")
            return cls(**data)
        except Blocked:
            raise
        except Exception:
            raise Blocked("private_config_invalid") from None

    def validate_live(self) -> None:
        if not all(isinstance(v, str) and v.strip() for v in (self.bot_id, self.group_openid)):
            raise Blocked("missing_test_bot_or_group")
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,160}",v) for v in (self.bot_id,self.group_openid)):
            raise Blocked("invalid_target_identifier")
        if self.active_test_authorized is not True:
            raise Blocked("missing_active_test_authorization")
        for key in ("extended_test_authorized", "active_performance_authorized", "markdown_authorized",
                    "domain_whitelisted", "domain_preflight_authorized", "external_access_verified"):
            if type(getattr(self,key)) is not bool:
                raise Blocked("invalid_boolean_config")
        if any(v is not None and type(v) is not bool for v in (self.active_permission,self.group_active_allowed)):
            raise Blocked("invalid_capability_declaration")
        if type(self.max_sends_per_round) is not int or not 1 <= self.max_sends_per_round <= 6:
            raise Blocked("round_send_budget_required_1_to_6")
        if not isinstance(self.admin_openids, list) or not self.admin_openids or not all(
            isinstance(v, str) and v for v in self.admin_openids
        ):
            raise Blocked("missing_authorized_test_admin")
        if not isinstance(self.round_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", self.round_id):
            raise Blocked("invalid_round_id")
        if type(self.interval_seconds) not in (int, float) or not 20 <= self.interval_seconds <= 3600:
            raise Blocked("interval_must_be_at_least_20_seconds")
        if self.phase not in ("protocol", "performance"):
            raise Blocked("invalid_phase")
        if type(self.max_samples_per_mode) is not int or not 1 <= self.max_samples_per_mode <= 20:
            raise Blocked("invalid_sample_limit")
        if self.max_samples_per_mode > 10 and self.extended_test_authorized is not True:
            raise Blocked("extended_test_authorization_required")
        if self.transport not in ("adapter", "traced_httpx"):
            raise Blocked("invalid_transport")
        if type(self.timeout_seconds) not in (int, float) or not 10 <= self.timeout_seconds <= 120:
            raise Blocked("invalid_timeout")
        if not self.private_dir or not Path(self.private_dir).is_absolute():
            raise Blocked("private_state_directory_required")
        if not 300 <= self.static_ttl_seconds <= 1800:
            raise Blocked("invalid_static_ttl")


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise Blocked("private_directory_symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise Blocked("private_directory_permissions")
