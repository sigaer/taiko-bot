"""Prepared input and display models. No filesystem or account lookup here."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DaniInputs:
    grade_payloads: dict[str, dict[str, Any]]
    song_catalog: list[dict[str, Any]]
    roll_catalog: list[dict[str, Any]]
    rating_context: dict[str, Any]


@dataclass(frozen=True)
class DaniAssets:
    upper: Path
    lower: Path
    difficulty_icons: Path
    dani_icons: Path
    font: Path
    ddfont: Path


@dataclass(frozen=True)
class DaniSection:
    title: str
    songs: list[dict[str, Any]]
    footer: list[dict[str, Any]]
    title_icon: int = 0


@dataclass(frozen=True)
class DaniProgress:
    grade: dict[str, Any] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    sections: tuple[DaniSection, ...] = ()
    notice: str | None = None
