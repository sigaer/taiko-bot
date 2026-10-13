"""Platform-neutral request/result; authorized providers are supplied by the host."""

from dataclasses import dataclass
from typing import Any, Literal, Callable


@dataclass(frozen=True)
class CommandContext:
    text: str = ""
    match: Any = None
    user_id: str = ""
    missing_userdata_hint: Callable[[], str] | None = None
    assets_base: str = ""
    rating_path: str = ""
    profile: Literal["center", "client"] = "center"

    def __post_init__(self):
        if self.profile not in ("center", "client"):
            raise ValueError("Unknown command profile")


@dataclass(frozen=True)
class CommandResult:
    kind: Literal["text", "image", "silent", "fumen", "fuzzy_fumen"]
    payload: Any = None
    delivery: Literal["direct", "reply"] = "reply"
    prefix_text: str = ""
    difficulty: str = "Oni"
