"""Compare archived numeric B20 telemetry without reading events or player data."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics


PREPARATION = {"provider.prepare", "inputs.build_ports", "history.reconstruct",
               "history.rating_points"}
UPLOADS = {"api.post_group_files", "api.post_c2c_files", "api.post_group_upload_prepare",
           "api.post_c2c_upload_prepare", "api.put_upload_part",
           "api.post_group_upload_part_finish", "api.post_c2c_upload_part_finish"}
SENDS = {"api.post_group_messages", "api.post_c2c_messages"}
STAGES = {"provider_prepare_ms": "provider.prepare", "inputs_build_ports_ms": "inputs.build_ports",
          "history_capture_ms": "history.capture", "history_read_ms": "history.read",
          "history_reconstruct_ms": "history.reconstruct", "history_rating_points_ms": "history.rating_points",
          "command_parse_ms": "command.parse", "render_compute_ms": "render.compute",
          "render_queue_ms": "render.queue", "render_jpeg_ms": "render.jpeg", "delivery_ms": "delivery"}


def union_duration(intervals):
    total, end = 0.0, float("-inf")
    for start, stop in sorted(intervals):
        if stop < start:
            raise ValueError("negative interval")
        total += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return round(total, 3)


def intervals(row, names):
    return [(s["start_ms"], s["start_ms"] + s["duration_ms"])
            for s in row["spans"] if s["name"] in names]


def duration(row, names):
    return round(sum(s["duration_ms"] for s in row["spans"] if s["name"] in names), 3)


def observation(row):
    metrics = {key: duration(row, {name}) for key, name in STAGES.items()}
    apis = intervals(row, UPLOADS | SENDS)
    delivery = intervals(row, {"delivery"})
    # Clip API intervals to delivery before subtracting; this is a residual,
    # not a direct measurement of image writing or DNS/TTFB.
    overlap = [(max(a, c), min(b, d)) for a, b in apis for c, d in delivery
               if max(a, c) < min(b, d)]
    metrics.update(
        prepare_and_history_union_ms=union_duration(intervals(row, PREPARATION)),
        before_compute_ms=min((s["start_ms"] for s in row["spans"]
                               if s["name"] == "render.compute"), default=None),
        upload_ms=duration(row, UPLOADS), send_ms=duration(row, SENDS),
        api_union_ms=union_duration(apis),
        delivery_non_api_ms=round(union_duration(delivery) - union_duration(overlap), 3),
        dispatch_to_send_ack_ms=row["dispatch_to_send_ack_ms"],
        dispatch_to_finish_ms=row["dispatch_to_finish_ms"],
        upload_api_calls=sum(s["name"] in UPLOADS for s in row["spans"]),
        send_api_calls=sum(s["name"] in SENDS for s in row["spans"]))
    return dict(request_id=row["request_id"], release=row["release"],
                finished_at=datetime.fromtimestamp(row["journal_timestamp_us"] / 1e6, timezone.utc).isoformat(),
                dispatch_timestamp_us=round(row["journal_timestamp_us"] - row["dispatch_to_finish_ms"] * 1000),
                status=row["status"], parse_over_100_ms=metrics["command_parse_ms"] > 100,
                dropped_spans=row["dropped_spans"], unfinished_api_calls=row["unfinished_api_calls"],
                metrics=metrics)


def stats(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return dict(n=len(values), median=round(statistics.median(values), 3),
                p95_nearest_rank=values[math.ceil(.95 * len(values)) - 1],
                minimum=values[0], maximum=values[-1])


def group(rows):
    successful = [r for r in rows if r["status"] == "completed"
                  and r["metrics"]["dispatch_to_send_ack_ms"] is not None
                  and not r["dropped_spans"] and not r["unfinished_api_calls"]]
    return dict(n=len(rows), valid_successes=len(successful), request_ids=[r["request_id"] for r in rows],
                status_counts=dict(Counter(r["status"] for r in rows)),
                metrics={name: stats([r["metrics"][name] for r in successful])
                         for name in (successful[0]["metrics"] if successful else [])})


def comparable(row, release):
    return (row["release"] == release and row["platform"] == "qq_official"
            and row["profile"] == "center" and row["command"] == dict(
                top_n=20, rating="v2", dynamic=False, dimension=None)
            and any(s["name"] == "api.post_group_messages" for s in row["spans"]))


def compare(before, after, reference_ids, release, round_after_us):
    previous = {r["request_id"]: r for r in before["records"]}
    if len(previous) != len(before["records"]):
        raise ValueError("duplicate baseline telemetry records")
    if len(reference_ids) != len(set(reference_ids)) or not set(reference_ids) <= previous.keys():
        raise ValueError("missing or duplicate baseline request IDs")
    if any(not comparable(previous[key], "0.22.1") for key in reference_ids):
        raise ValueError("baseline must match center official QQ group B20 v2")
    selected = [r for r in after["records"] if comparable(r, release)]
    if len({r["request_id"] for r in selected}) != len(selected):
        raise ValueError("duplicate current request IDs")
    current = [observation(r) for r in selected]
    steady = [r for r in current if not r["parse_over_100_ms"]]
    return dict(schema=1, release=release, unit="milliseconds",
                count_metric_names=["upload_api_calls", "send_api_calls"],
                method=dict(boundary=after["boundary"],
                    selection="center official QQ group B20 v2, dynamic=false, dimension=null",
                    initialization="command.parse >100ms, same descriptive rule as 0.22.1; not a general cold-start detector",
                    preparation="interval union of " + ", ".join(sorted(PREPARATION)),
                    delivery_non_api="delivery interval union minus clipped API interval union; includes authorization/cache/message work; not isolated image-write timing",
                    statistics="sum same-name spans within each request, then summarize requests; never add stage medians",
                    p95="nearest-rank, descriptive only at this sample size",
                    round_after_us=round_after_us,
                    round_selection="dispatch time approximated from journal completion minus dispatch_to_finish; temporal association only, telemetry contains no group/player identity",
                    client_complete_image_ms=None,
                    limitations=["Unmatched natural requests across dates; not a controlled causal speedup.",
                                 "No client load timer, HTTP internal phases, image byte count or URL-cache status in this telemetry.",
                                 "API receipt does not establish client completeness or absence of duplicate images."]),
                groups=dict(baseline_0_22_1=group([observation(previous[key]) for key in reference_ids]),
                            current_all=group(current), current_initialization=group([r for r in current if r["parse_over_100_ms"]]),
                            current_steady=group(steady),
                            round_window_steady=group([r for r in steady if r["dispatch_timestamp_us"] >= round_after_us])),
                observations=current,
                not_comparable_request_ids=[r["request_id"] for r in after["records"] if not comparable(r, release)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="0.22.1 latency-comparison.json")
    parser.add_argument("--release", default="0.23.0")
    parser.add_argument("--round-after", required=True, help="ISO timestamp with explicit UTC offset")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.round_after)
    if cutoff.utcoffset() is None:
        parser.error("--round-after requires a UTC offset")
    reference = json.loads(args.reference.read_text())
    result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()),
                     reference["groups"]["after_0.22.1_group_steady_5"]["request_ids"],
                     args.release, round(cutoff.timestamp() * 1e6))
    result["sources"] = {name: dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                         for name, path in (("before", args.before), ("after", args.after), ("reference", args.reference))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: dict(n=g["n"], valid_successes=g["valid_successes"],
                                ack_ms=g["metrics"].get("dispatch_to_send_ack_ms"))
                      for name, g in result["groups"].items()}))


if __name__ == "__main__":
    main()
