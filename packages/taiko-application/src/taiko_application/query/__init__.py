"""Injected query/application API. No filesystem, SQL, host or network access."""

from .context import (
    SongQueryContext,
    ConstantQueryContext,
    PaginationContext,
    ProgressQueryContext,
    RecommendationContext,
    SimilarityProvider,
)
from .song import query_music
from .alias import query_aliases
from .constant import ConstChartRow, query_charts_by_const, paginate_rows
from .progress import summarize_progress
from .recommendation import (
    project_player_rating,
    project_ordinary_recommendations,
    project_target_recommendations,
)
