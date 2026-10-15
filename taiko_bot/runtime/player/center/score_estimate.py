"""Host preparation from captured current; the Core kernel receives a value profile."""
from taiko_application.private_input import thaw
from .recommendation_support.taiko_domain_adapter import with_host_clock
from sakura_taiko_core.recommendation.estimator import _estimate_with_profile

calculate = with_host_clock(_estimate_with_profile)


def prepare_estimate(private, song_id, level):
    from .recommendation_support.score_estimator import build_score_estimator_profile
    if private.current_failure:
        if private.current_failure.missing:
            raise FileNotFoundError('userdata not found')
        raise ValueError(private.current_failure.message)
    current = thaw(private.current)
    rows = current.get('songs')
    records = rows if isinstance(rows, list) else []
    profile = build_score_estimator_profile(records, exclude_song_id=song_id, exclude_level=level)
    return calculate(profile, song_id, level)
