from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Annual outputs after a reporting-window change")
    parser.add_argument("--source-root", help="Optional assertion of installed Taiko package root; select versions with the Python interpreter")
    parser.add_argument("--userdata-dir", required=True)
    parser.add_argument("--version-json-file", required=True)
    parser.add_argument("--baseline-results-dir")
    parser.add_argument("--baseline-compacts-dir")
    parser.add_argument("--candidate-compacts-dir")
    parser.add_argument("--song-data", required=True)
    parser.add_argument("--rating-data", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=1, choices=(1, 2))
    parser.add_argument("--limit", type=int, default=0)
    return parser


def _account_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _metric_available(node: Any) -> bool:
    if not isinstance(node, dict) or node.get("status") == "unavailable":
        return False
    data = node.get("data")
    return data is not None and (not isinstance(data, list) or bool(data))


def _page_count(summary: Dict[str, Any]) -> int:
    sections = summary.get("sections") or {}
    optional = (
        "favoriteSong", "obsessionSong", "favoriteShift", "keyword", "ratingRank",
        "monthlyFavorites", "weekdayActivity", "calendarActivity", "timeOfDay", "lateNight",
        "speedProfile", "nearDondaful", "challenge", "pound", "highScore", "milestones",
    )
    return 5 + sum(_metric_available(sections.get(key)) for key in optional)


def _compact(result: Dict[str, Any]) -> Dict[str, Any]:
    summary = result["summary"]
    sections = summary.get("sections") or {}
    overview = (summary.get("overview") or {}).get("data") or {}
    calendar = (sections.get("calendarActivity") or {}).get("data") or {}
    monthly = (sections.get("monthlyFavorites") or {}).get("data") or []
    final_title = summary.get("finalTitle") or {}
    events = result.get("events") or []
    representative = sorted(
        str(item.get("representativeAt")) for item in events if item.get("representativeAt")
    )
    return {
        "summaryId": summary.get("summaryId"),
        "algorithmVersion": (summary.get("provenance") or {}).get("algorithmVersion"),
        "version": summary.get("version"),
        "mode": summary.get("mode"),
        "coverage": {
            "snapshotCount": (summary.get("coverage") or {}).get("snapshotCount"),
            "firstSnapshotAt": (summary.get("coverage") or {}).get("firstSnapshotAt"),
            "lastSnapshotAt": (summary.get("coverage") or {}).get("lastSnapshotAt"),
            "partialStart": (summary.get("coverage") or {}).get("partialStart"),
        },
        "period": summary.get("period"),
        "overview": {
            key: overview.get(key)
            for key in ("playCount", "uniqueSongs", "uniqueCharts", "currentClearCharts",
                        "currentFullComboCharts", "currentDondafulCharts", "currentKiwamiCharts")
        },
        "sectionHashes": {
            key: hashlib.sha256(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            for key, value in sorted(sections.items())
        },
        "monthlyKeys": [item.get("month") for item in monthly if isinstance(item, dict)],
        "calendar": {
            "activeDays": calendar.get("activeDays"),
            "longestStreak": calendar.get("longestStreak"),
            "first": min((item.get("date") for item in calendar.get("days") or []), default=None),
            "last": max((item.get("date") for item in calendar.get("days") or []), default=None),
        },
        "finalTitle": {
            key: final_title.get(key)
            for key in ("titleKey", "evidenceKey", "evidenceValue", "strongDan", "standingPresentation")
        },
        "eventCount": len(events),
        "eventFirst": representative[0] if representative else None,
        "eventLast": representative[-1] if representative else None,
        "pageCount": _page_count(summary),
    }


def _invariants(result: Dict[str, Any], version: Dict[str, Any]) -> list[str]:
    errors: list[str] = []
    summary = result.get("summary") or {}
    events = result.get("events") or []
    start = f"{version['startDate']}T00:00:00+08:00"
    end = f"{version['endExclusive']}T00:00:00+08:00"
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("nan_or_non_json")
    period = summary.get("period") or {}
    total_days = period.get("totalDays")
    if total_days is not None and not (0 <= int(total_days) <= int(version["calendarDays"])):
        errors.append("total_days_out_of_range")
    active_days = period.get("activeDays")
    if active_days is not None and not (0 <= int(active_days) <= int(version["calendarDays"])):
        errors.append("active_days_out_of_range")
    calendar = (((summary.get("sections") or {}).get("calendarActivity") or {}).get("data") or {})
    calendar_active = calendar.get("activeDays")
    streak = calendar.get("longestStreak")
    if calendar_active is not None and not (0 <= int(calendar_active) <= int(version["calendarDays"])):
        errors.append("calendar_active_days_out_of_range")
    if streak is not None and calendar_active is not None and int(streak) > int(calendar_active):
        errors.append("streak_exceeds_active_days")
    if active_days is not None and calendar_active is not None and int(active_days) != int(calendar_active):
        errors.append("summary_page_active_days_mismatch")
    dates = [item.get("date") for item in calendar.get("days") or [] if isinstance(item, dict)]
    if dates != sorted(dates) or any(not (version["startDate"] <= item < version["endExclusive"]) for item in dates):
        errors.append("calendar_date_order_or_range")
    monthly = (((summary.get("sections") or {}).get("monthlyFavorites") or {}).get("data") or [])
    month_keys = [item.get("month") for item in monthly if isinstance(item, dict)]
    if month_keys != sorted(month_keys):
        errors.append("month_order")
    identifiers = [item.get("eventId") for item in events]
    if len(identifiers) != len(set(identifiers)):
        errors.append("duplicate_event")
    observed_to_values = [
        (item.get("observedBetween") or {}).get("to") for item in events
        if (item.get("observedBetween") or {}).get("to")
    ]
    if observed_to_values != sorted(observed_to_values):
        errors.append("event_observation_order")
    representative_values = [item.get("representativeAt") for item in events if item.get("representativeAt")]
    if representative_values != sorted(representative_values):
        errors.append("event_representative_order")
    for event in events:
        moment = event.get("representativeAt")
        if moment and not (start <= str(moment) < end):
            errors.append("event_timestamp_out_of_range")
            break
        observed_to = ((event.get("observedBetween") or {}).get("to"))
        if observed_to and not (start <= str(observed_to) < end):
            errors.append("observed_event_out_of_range")
            break
    overview = ((summary.get("overview") or {}).get("data") or {})
    if summary.get("mode") == "version_observed":
        observed_plays = sum(
            int((item.get("delta") or {}).get("playCount") or 0)
            for item in events if item.get("type") == "play_delta"
        )
        if int(overview.get("playCount") or 0) != observed_plays:
            errors.append("summary_page_play_count_mismatch")
    final_title = summary.get("finalTitle") or {}
    if not final_title.get("titleKey"):
        errors.append("missing_final_title")
    if not final_title.get("evidenceKey") or final_title.get("evidenceValue") is None:
        errors.append("empty_final_title_evidence")
    if _page_count(summary) < 5 or _page_count(summary) > 21:
        errors.append("page_count_out_of_contract")
    return sorted(set(errors))


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _load_baseline(task: Dict[str, Any], account_id: str) -> Optional[Dict[str, Any]]:
    compact_dir = task.get("baselineCompactsDir")
    if compact_dir:
        compact = _read_json(Path(compact_dir) / f"{_account_key(account_id)}.json")
        if compact is not None:
            return compact
    results_dir = task.get("baselineResultsDir")
    if results_dir:
        result = _read_json(Path(results_dir) / f"{account_id}.json")
        if result is not None:
            return _compact(result)
    return None


def _audit_one(task: Dict[str, Any]) -> Dict[str, Any]:
    if task["sourceRoot"] and Path(task["sourceRoot"]).resolve() != Path(__file__).resolve().parents[1]:
        raise ValueError("source-root must match the installed Taiko package; select the wheel interpreter")
    os.environ.pop("TAIKO_ANNUAL_CACHE_DIR", None)
    from taiko_bot.offline.annual_summary.service import build_annual_result

    account_id = task["accountId"]
    started = time.monotonic()
    row: Dict[str, Any] = {"accountKey": _account_key(account_id)}
    baseline = _load_baseline(task, account_id)
    try:
        candidate = build_annual_result(
            account_id,
            task["version"],
            userdata_dir=task["userdataDir"],
            song_data_path=task["songData"],
            rating_path=task["ratingData"],
            generated_at=datetime.fromisoformat(task["generatedAt"]),
        )
        row["candidateStatus"] = "success"
        row["invariants"] = _invariants(candidate, task["version"])
        compact = _compact(candidate)
        row["candidate"] = compact
        compact_dir = task.get("candidateCompactsDir")
        if compact_dir:
            compact_path = Path(compact_dir) / f"{row['accountKey']}.json"
            compact_path.write_text(
                json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        if baseline:
            row["baselineStatus"] = "success"
            old = baseline
            changed = sorted(key for key in compact if compact[key] != old.get(key))
            row["changedFields"] = changed
            same_observation_bounds = compact["coverage"] == old.get("coverage")
            row["diffClass"] = (
                "UNCHANGED" if not changed
                else "EXPECTED_BOUNDARY_DIFF" if same_observation_bounds
                else "EXPECTED_WINDOW_DIFF"
            )
        else:
            row["baselineStatus"] = "missing"
            row["diffClass"] = "EXPECTED_CORPUS_ADDITION"
    except Exception as error:
        row["candidateStatus"] = "no_data" if isinstance(error, ValueError) and "no snapshots" in str(error) else "error"
        row["errorType"] = type(error).__name__
        row["errorReason"] = str(error)[:240]
        row["baselineStatus"] = "success" if baseline else "missing"
        row["diffClass"] = "BUG" if baseline or row["candidateStatus"] == "error" else "UNCHANGED_NO_DATA"
    row["seconds"] = round(time.monotonic() - started, 4)
    return row


def _account_ids(userdata_dir: Path) -> Iterable[str]:
    ids = {path.name[:-9] for path in userdata_dir.glob("*data.json")}
    ids.update(path.name for path in userdata_dir.iterdir() if path.is_dir() and path.name.isdigit())
    return sorted(ids)


def main() -> int:
    args = _parser().parse_args()
    version = json.loads(Path(args.version_json_file).read_text(encoding="utf-8"))
    accounts = list(_account_ids(Path(args.userdata_dir)))
    if args.limit > 0:
        accounts = accounts[: args.limit]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    records_path = output.with_suffix(".records.jsonl")
    common = {
        "sourceRoot": args.source_root,
        "userdataDir": args.userdata_dir,
        "version": version,
        "baselineResultsDir": args.baseline_results_dir,
        "baselineCompactsDir": args.baseline_compacts_dir,
        "candidateCompactsDir": args.candidate_compacts_dir,
        "songData": args.song_data,
        "ratingData": args.rating_data,
        "generatedAt": args.generated_at,
    }
    rows: list[Dict[str, Any]] = []
    started = time.monotonic()
    if args.candidate_compacts_dir:
        Path(args.candidate_compacts_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    with records_path.open("w", encoding="utf-8") as record_file:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_audit_one, {**common, "accountId": account}) for account in accounts]
            for index, future in enumerate(as_completed(futures), 1):
                row = future.result()
                rows.append(row)
                record_file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                record_file.flush()
                if index % 100 == 0:
                    print(json.dumps({"completed": index, "total": len(accounts)}), flush=True)
    counts: Dict[str, int] = {}
    invariant_counts: Dict[str, int] = {}
    page_omissions = 0
    for row in rows:
        counts[row["diffClass"]] = counts.get(row["diffClass"], 0) + 1
        for value in row.get("invariants") or []:
            invariant_counts[value] = invariant_counts.get(value, 0) + 1
        candidate = row.get("candidate") or {}
        if candidate and candidate.get("pageCount", 21) < 21:
            page_omissions += 1
    report = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "reportingWindow": version,
        "scannedCount": len(rows),
        "candidateSuccessCount": sum(row.get("candidateStatus") == "success" for row in rows),
        "zeroDataCount": sum(row.get("candidateStatus") == "no_data" for row in rows),
        "exceptionCount": sum(row.get("candidateStatus") == "error" for row in rows),
        "pageOmissionCount": page_omissions,
        "diffCounts": dict(sorted(counts.items())),
        "invariantFailures": dict(sorted(invariant_counts.items())),
        "bugCount": counts.get("BUG", 0) + sum(invariant_counts.values()),
        "wallSeconds": round(time.monotonic() - started, 3),
        "recordsFile": str(records_path),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report["bugCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
