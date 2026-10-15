"""A single current snapshot, only when the frozen annual window is empty."""
from .model import WindowSelection
from .helpers import safe_int


def select_current_archive(history, end_date):
    latest = history.snapshots[-1]
    songs = latest.state.get("songs") or []
    if not any(safe_int(song.get("stage_cnt")) > 0 or safe_int(song.get("high_score")) > 0 for song in songs):
        raise ValueError("no snapshots with usable current scores")
    return WindowSelection(
        snapshots=[latest], window_snapshots=[latest], baseline=latest,
        start_state=latest.state, end_state=latest.state, partial_start=True,
        effective_end_date=end_date,
    )
