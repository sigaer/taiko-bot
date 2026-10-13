"""Explicit request data; providers and data acquisition remain caller-owned."""

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from sakura_taiko_core.chart.progress_catalog import ProgressCatalogInputs


class SimilarityProvider(Protocol):
    def __call__(self, left: str, right: str) -> int: ...


@dataclass(frozen=True)
class SongQueryContext:
    songs: Sequence[dict]
    aliases: Any
    groups_by_id: Mapping
    groups_by_title: Mapping
    similarity: SimilarityProvider
    group_provider: Callable[[], tuple[Mapping, Mapping]] | None = None
    query: str = ""
    allow_partial: bool = True
    allow_fuzzy: bool = True
    song_id: int | str = 0
    explicit_alias_id: bool = False


@dataclass(frozen=True)
class ConstantQueryContext:
    song_index: Mapping[int, dict]
    rating_entries: Iterable[dict]
    value: float
    include_shelf_status: bool = False


@dataclass(frozen=True)
class PaginationContext:
    rows: Sequence
    page: int
    page_size: int = 25


@dataclass(frozen=True)
class ProgressQueryContext:
    catalog: ProgressCatalogInputs
    value: Any = None
    items: Iterable = ()
    best_map: Mapping = field(default_factory=dict)
    available_chart_keys: Any = None


class TargetRecommendationView(Protocol):
    rows: Iterable[dict]
    target_key: str
    candidate_count: int
    required_count: int
    is_enough: bool


@dataclass(frozen=True)
class RecommendationContext:
    rating_results: Sequence = ()
    rows: Iterable[dict] = ()
    basis: str = "rating"
    target_result: TargetRecommendationView | None = None
