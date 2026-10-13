"""Prepared score presentation inputs. Acquisition and authorization belong to caller."""

from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image


@dataclass(frozen=True)
class ScorePresentationContext:
    assets_base: Path
    layout_assets_base: Path | None = None
    background_path: Path | None = None
    template_path: Path | None = None
    font_path: str | None = None
    title_font_candidates: tuple[Path, ...] = ()
    entry: dict = field(default_factory=dict)
    song_info: dict = field(default_factory=dict)
    rating: float = 0.0
    show_new: bool = False
    rating_delta: float | None = None
    song_no: int = 0
    entries_by_level: dict = field(default_factory=dict)
    rating_index: dict = field(default_factory=dict)
    player_metrics: dict = field(default_factory=dict)
    v2_charts: dict = field(default_factory=dict)
    v2_player_values: dict = field(default_factory=dict)
    top_entries: list = field(default_factory=list)
    song_index: dict = field(default_factory=dict)
    card_ratings: dict = field(default_factory=dict)
    overall: float = 0.0
    dim_means: dict = field(default_factory=dict)
    trend_rows: list = field(default_factory=list)
    trend_columns: list = field(default_factory=list)
    trend_labels: dict = field(default_factory=dict)
    update_diff: tuple = field(default_factory=lambda: (set(), {}, {}, 0.0))
    update_text: str = "更新于未知"
    has_results: bool = False
    count: int = 30
    rating_label: str | None = None
    dress_image: Image.Image | None = None
    title_image: Image.Image | None = None
    profile_panel: Image.Image | None = None
    recommendations: list = field(default_factory=list)
    song_star_map: dict = field(default_factory=dict)
    title: str = "Taiko 推荐歌曲"
    subtitle: str | None = None
