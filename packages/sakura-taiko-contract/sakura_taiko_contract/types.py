# Generated from schema/contract-v1.json. Run tools/generate_bindings.py.
from __future__ import annotations
from typing import Any, Dict, List, Literal, NotRequired, TypedDict
CONTRACT_VERSION = "1.0"
class ExternalIdentity(TypedDict):
    namespace: Literal['wahlap', 'hiroba', 'qq', 'onebot', 'manual', 'legacy-content']
    id: str
class User(TypedDict):
    id: str
    namespace: Literal['viewer']
    displayName: str | None
class Binding(TypedDict):
    id: str
    userId: str
    externalIdentity: ExternalIdentity
    isCurrent: bool
    verifiedAt: str | None
class DeveloperIdentity(TypedDict):
    id: str
    ownerUserId: str
    scopes: List[str]
class Song(TypedDict):
    songId: str
    title: str | None
    catalogRevision: str | None
class Chart(TypedDict):
    songId: str
    chartId: str
    difficulty: int
    level: float | None
    type: Literal['single', 'double', 'unknown']
    variant: str | None
    catalogRevision: str | None
class ScoreCounts(TypedDict):
    clear: int | None
    fullCombo: int | None
    dondafulCombo: int | None
    stage: int | None
    roll: int | None
class Score(TypedDict):
    song: Song
    chart: Chart
    score: int | None
    good: int | None
    ok: int | None
    ng: int | None
    combo: int | None
    clear: bool | None
    fullCombo: bool | None
    dondafulCombo: bool | None
    rank: int | None
    capturedAt: str | None
    source: str
    counts: ScoreCounts
    highscoreAt: str | None
    updatedAt: str | None
    legacy: NotRequired[Dict[str, Any]]
class GrowthObservation(TypedDict):
    token: str
    orderKey: str
    revision: str
    contentRevision: str | None
    observedAt: str
    source: str
    eventDays: List[str]
    evidenceLevel: Literal['L0', 'L1']
    excludedReason: Literal[None, 'import', 'manual', 'repair', 'content-edit', 'dispatcher-transfer', 'counter-regression', 'unknown-source', 'source-switch', 'discontinuity-baseline']
class GrowthTemporal(TypedDict):
    attributedDay: NotRequired[str | None]
    occurredAt: NotRequired[str | None]
    observedAt: NotRequired[str | None]
    confirmedAt: NotRequired[str | None]
    precision: Literal['instant', 'day', 'observation', 'unknown']
class GrowthEvidence(TypedDict):
    source: Literal['score-history', 'goal']
    sourceRevision: NotRequired[str]
    evidenceVersion: int
    provenance: NotRequired[Any]
class CanonicalFact(TypedDict):
    id: str
    factKey: str
    ownerId: str
    bindingId: str
    type: Literal['played', 'score-pb', 'ng-reduced', 'combo-improved', 'clear', 'fc', 'df', 'rank-upgrade', 'goal-completed']
    title: NotRequired[str]
    songId: NotRequired[int | None]
    difficultyType: NotRequired[int | None]
    before: NotRequired[float | None]
    after: NotRequired[float | None]
    delta: NotRequired[float | None]
    goalId: NotRequired[str | None]
    goalType: NotRequired[str | None]
    evidence: GrowthEvidence
    temporal: GrowthTemporal
class GrowthProjection(TypedDict):
    ownerId: str
    bindingId: str
    timezone: Literal['Asia/Shanghai']
    facts: List[CanonicalFact]
    projectionVersion: str
class CalculationProfile(TypedDict):
    algorithmVersion: Literal['v1-great-only', 'v1-comprehensive', 'v2-center-20261010', 'v2-client-20261010']
    modelRevision: str
    catalogRevision: str
    topN: int
    availabilityRevision: str
