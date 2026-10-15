from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SyncTargetKind = Literal["local", "http"]


@dataclass(frozen=True)
class SyncTarget:
    id: str
    label: str
    description: str
    kind: SyncTargetKind
    endpoint: str = ""
    timeout_ms: int = 10000


def get_sync_targets() -> list[SyncTarget]:
    return [
        SyncTarget(
            id="sakura-bot",
            label="Sakura bot",
            description="服务端从鼓众广场拉取 userdata 并刷新本地快照后分发。",
            kind="local",
        ),
    ]


def to_public_target(target: SyncTarget) -> dict[str, str]:
    return {
        "id": target.id,
        "label": target.label,
        "description": target.description,
    }
