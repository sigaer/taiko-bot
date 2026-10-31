"""Contract identities and legacy-compatible numerical value models."""
from dataclasses import dataclass
from sakura_taiko_contract.types import User, Binding, ExternalIdentity, DeveloperIdentity, Song, Chart, Score
from .calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef

@dataclass(frozen=True)
class Player:
    user_id: str
    binding_id: str
    external_identity: ExternalIdentity
