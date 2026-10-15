from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ChartKey = Tuple[int, int]


@dataclass(frozen=True)
class SnapshotPlanEntry:
    path: Path
    observed_at: datetime
    is_full: bool
    source: str
    source_account: Optional[str]
    merge_topology: List[str]
    content_hash: str
    size: int
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RebuiltSnapshot:
    path: Path
    observed_at: datetime
    state: Dict[str, Any]
    source: str
    source_account: Optional[str]
    merge_topology: List[str]
    content_hash: str
    warnings: List[str] = field(default_factory=list)
    # Chart keys whose payload changed relative to the previous retained
    # snapshot.  This is an internal replay hint; it is not serialized.
    changed_keys: Tuple[ChartKey, ...] = ()


@dataclass(frozen=True)
class SnapshotHistory:
    snapshots: List[RebuiltSnapshot]
    warnings: List[str]
    ignored_files: int = 0


@dataclass(frozen=True)
class WindowSelection:
    snapshots: List[RebuiltSnapshot]
    window_snapshots: List[RebuiltSnapshot]
    baseline: RebuiltSnapshot
    start_state: Dict[str, Any]
    end_state: Dict[str, Any]
    partial_start: bool
    effective_end_date: Any


@dataclass
class CounterEpoch:
    identity: Tuple[str, Optional[str], Tuple[str, ...]]
    high_water: int
    previous: int
    suppressed: bool = False
