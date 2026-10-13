"""Experimental data-only boundary. An authorization observation is not a grant."""
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
            raise TypeError('Only string data keys are allowed')
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if type(value) in (list, tuple):
        return tuple(freeze(v) for v in value)
    raise TypeError('Prepared input accepts JSON data only')


def text(value):
    if type(value) is not str or not value or '/' in value or '\\' in value:
        raise ValueError('Invalid observation identifier')


@dataclass(frozen=True, slots=True)
class AuthorizedTarget:
    actor: str
    principal: str
    user_id: str
    members: tuple[str, ...]
    profile_source: str
    authorization_observation: str

    def __post_init__(self):
        for value in (self.actor, self.principal, self.user_id, self.profile_source, self.authorization_observation):
            text(value)
        if type(self.members) is not tuple or not self.members:
            raise TypeError('Members must be a nonempty immutable vector')
        for value in self.members:
            text(value)
        if len(set(self.members)) != len(self.members) or self.profile_source not in self.members:
            raise ValueError('Invalid member/profile combination')


@dataclass(frozen=True, slots=True)
class Provenance:
    representation: str
    current_view: str
    history_view: str | None
    members: tuple[str, ...]
    profile_source: str
    rule_revision: str

    def __post_init__(self):
        if self.representation not in ('synthetic-normal', 'synthetic-u0'):
            raise ValueError('Not a fixture representation')
        for value in (self.current_view, self.profile_source, self.rule_revision):
            text(value)
        if self.history_view is not None:
            text(self.history_view)
        if type(self.members) is not tuple or not self.members:
            raise TypeError('Members must be an immutable vector')
        for value in self.members:
            text(value)


@dataclass(frozen=True, slots=True)
class PreparedPrivateInput:
    authorized_target: AuthorizedTarget
    current: Mapping
    history: tuple[Mapping, ...] | None
    provenance: Provenance

    def __post_init__(self):
        if type(self.authorized_target) is not AuthorizedTarget or type(self.provenance) is not Provenance:
            raise TypeError('Explicit target and provenance data required')
        if not isinstance(self.current, Mapping):
            raise TypeError('Current must be an object')
        p, t = self.provenance, self.authorized_target
        if p.members != t.members or p.profile_source != t.profile_source:
            raise ValueError('Target/provenance mismatch')
        if self.history is not None:
            if type(self.history) not in (list, tuple) or any(not isinstance(x, Mapping) for x in self.history):
                raise TypeError('History must be a sequence of objects')
            if p.history_view != p.current_view:
                raise ValueError('Mixed current/history views')
        elif p.history_view is not None:
            raise ValueError('Missing history has a history observation')
        object.__setattr__(self, 'current', freeze(self.current))
        object.__setattr__(self, 'history', None if self.history is None else freeze(self.history))
