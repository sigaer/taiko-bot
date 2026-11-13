"""Interval arithmetic and cohort isolation for production timing archives."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "compare_latency", Path(__file__).resolve().parents[2] / "scripts/performance/compare_latency.py")
latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latency)


def test_interval_union_merges_nesting_overlaps_and_adjacent_intervals():
    assert latency.union_duration([(20, 30), (1, 10), (3, 5), (9, 15), (15, 20)]) == 29
    assert latency.union_duration([]) == 0
    with pytest.raises(ValueError):
        latency.union_duration([(10, 9)])


def row(key="request", release="0.23.0", parse=1, send=2000, status="completed"):
    return dict(request_id=key, release=release, platform="qq_official", profile="center",
                command=dict(top_n=20, rating="v2", dynamic=False, dimension=None),
                journal_timestamp_us=10_000_000, status=status,
                dropped_spans=0, unfinished_api_calls=0, dispatch_to_finish_ms=3000,
                dispatch_to_send_ack_ms=3000 if status == "completed" else None,
                spans=[dict(name=name, start_ms=start, duration_ms=duration) for name, start, duration in [
                    ("command.parse", 0, parse), ("provider.prepare", 100, 90),
                    ("history.capture", 130, 40), ("inputs.build_ports", 185, 15),
                    ("render.compute", 210, 700), ("delivery", 950, 2050),
                    ("api.post_group_messages", 970, send)]])


def test_preparation_does_not_double_count_nested_stages_and_delivery_clips_apis():
    result = latency.observation(row(send=2100))["metrics"]
    assert result["prepare_and_history_union_ms"] == 100
    assert result["delivery_non_api_ms"] == 20
    assert result["upload_api_calls"] == 0
    assert result["send_api_calls"] == 1


def test_cold_and_other_command_groups_cannot_contaminate_comparison():
    prior = dict(records=[row("old", "0.22.1")])
    other = row("other")
    other["command"]["top_n"] = 50
    after = dict(boundary="dispatch to ACK", records=[row(), row("init", parse=101), other])
    result = latency.compare(prior, after, ["old"], "0.23.0", 7_000_000)
    assert result["groups"]["current_all"]["n"] == 2
    assert result["groups"]["current_steady"]["request_ids"] == ["request"]
    assert result["groups"]["current_initialization"]["request_ids"] == ["init"]
    assert result["groups"]["round_window_steady"]["n"] == 1
    assert result["not_comparable_request_ids"] == ["other"]


def test_failed_requests_are_counted_without_inventing_zero_ack_latencies():
    result = latency.group([latency.observation(row()), latency.observation(row("failed", status="error"))])
    assert result["n"] == 2 and result["valid_successes"] == 1
    assert result["status_counts"] == dict(completed=1, error=1)
    assert result["metrics"]["dispatch_to_send_ack_ms"]["n"] == 1
    assert latency.stats([]) is None


def test_api_totals_are_computed_per_request_before_group_statistics():
    observations = []
    for index, (upload, send) in enumerate([(1, 100), (100, 1), (100, 100)]):
        sample = row(str(index), send=send)
        sample["spans"].append(dict(name="api.post_group_files", start_ms=950, duration_ms=upload))
        # Keep upload and send intervals separate in each request.
        sample["spans"][-2]["start_ms"] = 950 + upload
        observations.append(latency.observation(sample))
    metrics = latency.group(observations)["metrics"]
    assert metrics["upload_ms"]["median"] == 100
    assert metrics["send_ms"]["median"] == 100
    assert metrics["api_union_ms"]["median"] == 101


def test_duplicate_samples_and_missing_baselines_fail_closed():
    prior = dict(records=[row("old", "0.22.1")])
    after = dict(boundary="ACK", records=[row(), row()])
    with pytest.raises(ValueError, match="duplicate current"):
        latency.compare(prior, after, ["old"], "0.23.0", 0)
    with pytest.raises(ValueError, match="baseline request"):
        latency.compare(prior, after, ["absent"], "0.23.0", 0)
    with pytest.raises(ValueError, match="duplicate baseline telemetry"):
        latency.compare(dict(records=prior["records"] * 2), after, ["old"], "0.23.0", 0)
