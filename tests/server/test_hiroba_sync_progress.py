from __future__ import annotations

from taiko_bot.runtime.player.center.hiroba.sync import _fetch_report_milestones, _sync_duration_hint


def test_fetch_report_milestones_caps_at_four_for_large_totals():
    assert _fetch_report_milestones(100) == [25, 50, 75, 100]


def test_fetch_report_milestones_reports_every_item_for_small_totals():
    assert _fetch_report_milestones(3) == [1, 2, 3]
    assert _fetch_report_milestones(4) == [1, 2, 3, 4]


def test_fetch_report_milestones_deduplicates_overlapping_quarters():
    assert _fetch_report_milestones(5) == [1, 2, 3, 5]


def test_sync_duration_hint_for_large_totals():
    assert _sync_duration_hint(1419) == "，谱面较多，完整同步通常需要 5-7 分钟"
    assert _sync_duration_hint(900) == "，谱面较多，完整同步通常需要数分钟"
    assert _sync_duration_hint(600) == ""
