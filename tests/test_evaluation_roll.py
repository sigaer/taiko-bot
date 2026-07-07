from __future__ import annotations

from plugins.utils.evaluation_roll import (
    ROTTER_TARMINATION_BALLOON_ROLL_SECONDS,
    compute_rating_roll_breakdown,
)


def test_compute_rating_roll_breakdown_replaces_special_balloon_hits():
    entry = {
        "id": 402,
        "level": 4,
        "roll_total_seconds": 2.0,
        "balloon_hits": 999,
        "balloons": [999],
    }

    result = compute_rating_roll_breakdown(entry, speed_ips=20.0)

    assert result.adjusted is True
    assert result.replaced_balloon_hits == 999
    assert result.preserved_balloon_hits == 0
    assert result.special_balloon_seconds == ROTTER_TARMINATION_BALLOON_ROLL_SECONDS
    assert result.effective_roll_hits == 40 + int(round(ROTTER_TARMINATION_BALLOON_ROLL_SECONDS * 20.0))
