"""Request-owned private data. Observation identifiers are not authorization grants."""
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
import math


def freeze(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(type(k) is not str for k in value):
            raise TypeError("Private data keys must be strings")
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if type(value) in (list, tuple):
        return tuple(freeze(v) for v in value)
    raise TypeError("Private input accepts JSON data only")


def thaw(value):
    """A caller-owned JSON projection, never a resolver or shared cache."""
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if type(value) is tuple:
        return [thaw(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class AuthorizedTarget:
    actor: str
    principal: str
    user_id: str
    members: tuple[str, ...]
    profile_source: str
    binding_observation: str

    def __post_init__(self):
        for value in (self.actor, self.principal, self.user_id, self.profile_source, self.binding_observation, *self.members):
            if type(value) is not str or not value or "/" in value or "\\" in value:
                raise ValueError("Invalid target identifier")
        if type(self.members) is not tuple or not self.members or self.profile_source not in self.members or len(set(self.members)) != len(self.members):
            raise ValueError("Invalid target members/profile")


@dataclass(frozen=True, slots=True)
class Provenance:
    representation: str
    current_view: str
    history_view: str | None
    dependency_hash: str | None
    members: tuple[str, ...]
    profile_source: str

    def __post_init__(self):
        if self.representation not in ("native-publication", "native-legacy", "remote-source-view", "unavailable"):
            raise ValueError("Unknown private input representation")
        for value in (self.current_view, self.profile_source, *self.members):
            if type(value) is not str or not value or "/" in value or "\\" in value:
                raise ValueError("Invalid provenance identifier")
        if type(self.members) is not tuple or not self.members or self.profile_source not in self.members:
            raise ValueError("Invalid provenance members/profile")
        for value in (self.history_view, self.dependency_hash):
            if value is not None and (type(value) is not str or not value or "/" in value or "\\" in value):
                raise TypeError("Provenance accepts observation data only")


@dataclass(frozen=True, slots=True)
class ReadFailure:
    missing: bool
    message: str

    def __post_init__(self):
        if type(self.missing) is not bool or type(self.message) is not str:
            raise TypeError("Read failure accepts only boolean/text")


@dataclass(frozen=True, slots=True)
class PreparedPrivateInput:
    authorized_target: AuthorizedTarget
    current: object
    history: tuple | None
    provenance: Provenance
    current_failure: ReadFailure | None = None

    def __post_init__(self):
        if type(self.authorized_target) is not AuthorizedTarget or type(self.provenance) is not Provenance:
            raise TypeError("Explicit target and provenance required")
        t, p = self.authorized_target, self.provenance
        if t.members != p.members or t.profile_source != p.profile_source:
            raise ValueError("Target/provenance mismatch")
        if (self.history is None) != (p.history_view is None):
            raise ValueError("History observation mismatch")
        if self.history is not None and p.history_view != p.current_view:
            raise ValueError("Mixed private observations")
        if self.current_failure is not None and type(self.current_failure) is not ReadFailure:
            raise TypeError("Read failure must be data")
        object.__setattr__(self, "current", freeze(self.current))
        object.__setattr__(self, "history", freeze(self.history))
