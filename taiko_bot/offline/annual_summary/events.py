from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    ARCHIVE_ONLY_SOURCES,
    COUNTER_FIELDS,
    MANUAL_SOURCES,
    TRUSTED_PLAY_TIME_SOURCES,
)
from .helpers import build_song_map, content_sha256, iso_datetime, parse_datetime, safe_int
from .model import CounterEpoch, RebuiltSnapshot, WindowSelection


def _identity(snapshot: RebuiltSnapshot) -> Tuple[str, Optional[str], Tuple[str, ...]]:
    return snapshot.source, snapshot.source_account, tuple(snapshot.merge_topology)


def _bounded_source_time(
    raw_value: Any,
    previous_observed_at: datetime,
    current_observed_at: datetime,
    reporting_start_at: datetime,
    reporting_end_exclusive_at: datetime,
) -> Optional[datetime]:
    parsed = parse_datetime(raw_value)
    if parsed is None:
        return None
    if (
        reporting_start_at <= parsed < reporting_end_exclusive_at
        and previous_observed_at <= parsed <= current_observed_at
    ):
        return parsed
    return None


def _source_time_outside_window(
    raw_value: Any,
    reporting_start_at: datetime,
    reporting_end_exclusive_at: datetime,
) -> bool:
    parsed = parse_datetime(raw_value)
    return parsed is not None and not (
        reporting_start_at <= parsed < reporting_end_exclusive_at
    )


def _night_date(moment: datetime) -> str:
    adjusted = moment.date() - timedelta(days=1) if moment.hour < 5 else moment.date()
    return adjusted.isoformat()


def _event_id(payload: Dict[str, Any]) -> str:
    stable = {
        "type": payload.get("type"),
        "source": payload.get("source"),
        "songNo": payload.get("songNo"),
        "level": payload.get("level"),
        "observedBetween": payload.get("observedBetween"),
        "representativeAt": payload.get("representativeAt"),
        "delta": payload.get("delta"),
        "sourceRef": payload.get("sourceRef"),
    }
    return f"evt_{content_sha256(stable)[:24]}"


def _counter_delta(
    epochs: Dict[Tuple[int, int], CounterEpoch],
    key: Tuple[int, int],
    identity: Tuple[str, Optional[str], Tuple[str, ...]],
    previous_value: int,
    current_value: int,
) -> Tuple[int, List[str]]:
    warnings: List[str] = []
    epoch = epochs.get(key)
    if epoch is None or epoch.identity != identity:
        epochs[key] = CounterEpoch(identity=identity, high_water=current_value, previous=current_value)
        return 0, ["counter_epoch_started"]

    if current_value < epoch.previous:
        epoch.previous = current_value
        epoch.suppressed = True
        warnings.append("counter_regression")
        return 0, warnings

    epoch.previous = current_value
    if current_value <= epoch.high_water:
        if epoch.suppressed:
            warnings.append("counter_recovery_suppressed")
        return 0, warnings

    delta = current_value - epoch.high_water
    epoch.high_water = current_value
    epoch.suppressed = False
    return delta, warnings


def _base_event(
    *,
    event_type: str,
    previous: RebuiltSnapshot,
    current: RebuiltSnapshot,
    key: Tuple[int, int],
    representative_at: Optional[datetime],
    time_precision: str,
    before: Dict[str, Any],
    after: Dict[str, Any],
    delta: Dict[str, Any],
    warnings: List[str],
) -> Dict[str, Any]:
    event = {
        "eventId": "",
        "type": event_type,
        "source": current.source,
        "sourceAccount": current.source_account,
        "mergeTopology": list(current.merge_topology),
        "songNo": key[0],
        "level": key[1],
        "observedBetween": {
            "from": iso_datetime(previous.observed_at),
            "to": iso_datetime(current.observed_at),
        },
        "representativeAt": iso_datetime(representative_at),
        "representativeDate": representative_at.date().isoformat() if representative_at else None,
        "nightDate": _night_date(representative_at) if representative_at else None,
        "timePrecision": time_precision,
        "before": before,
        "after": after,
        "delta": delta,
        "warnings": sorted(set(warnings)),
        "sourceRef": {
            "from": {"file": previous.path.name, "sha256": previous.content_hash},
            "to": {"file": current.path.name, "sha256": current.content_hash},
        },
    }
    event["eventId"] = _event_id(event)
    return event


_SONG_VALUE_FIELDS = (
    *COUNTER_FIELDS,
    "pound_cnt",
    "good_cnt",
    "ok_cnt",
    "ng_cnt",
    "best_score_rank",
)


def _song_value_tuple(song: Dict[str, Any]) -> Tuple[int, ...]:
    get = song.get
    return (
        safe_int(get("stage_cnt")),
        safe_int(get("high_score")),
        safe_int(get("clear_cnt")),
        safe_int(get("full_combo_cnt")),
        safe_int(get("dondaful_combo_cnt")),
        safe_int(get("pound_cnt")),
        safe_int(get("good_cnt")),
        safe_int(get("ok_cnt")),
        safe_int(get("ng_cnt")),
        safe_int(get("best_score_rank")),
    )


def _song_value_dict(values: Tuple[int, ...]) -> Dict[str, int]:
    return dict(zip(_SONG_VALUE_FIELDS, values))


def build_observation_events(
    selection: WindowSelection,
    *,
    start_date: date,
    effective_end_date: date,
    start_at: Optional[datetime] = None,
    end_exclusive_at: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    reporting_start_at = start_at or datetime.combine(start_date, datetime.min.time())
    reporting_end_exclusive_at = end_exclusive_at or datetime.combine(
        effective_end_date + timedelta(days=1), datetime.min.time()
    )
    snapshots = selection.snapshots
    events: List[Dict[str, Any]] = []
    stage_epochs: Dict[Tuple[int, int], CounterEpoch] = {}
    score_epochs: Dict[Tuple[int, int], CounterEpoch] = {}
    comparable_transitions = 0
    skipped_source_transitions = 0

    if snapshots:
        initial_map = build_song_map(snapshots[0].state)
        identity = _identity(snapshots[0])
        for key, song in initial_map.items():
            stage = safe_int(song.get("stage_cnt"))
            score = safe_int(song.get("high_score"))
            stage_epochs[key] = CounterEpoch(identity, stage, stage)
            score_epochs[key] = CounterEpoch(identity, score, score)

    previous_map = build_song_map(snapshots[0].state) if snapshots else {}
    for index in range(1, len(snapshots)):
        previous = snapshots[index - 1]
        current = snapshots[index]
        if not (reporting_start_at <= current.observed_at < reporting_end_exclusive_at):
            previous_map = build_song_map(current.state)
            continue
        current_map = build_song_map(current.state)
        identity = _identity(current)
        same_identity = identity == _identity(previous)
        source_allows_diff = current.source not in ARCHIVE_ONLY_SOURCES
        is_manual = current.source in MANUAL_SOURCES
        if same_identity and source_allows_diff and not is_manual:
            comparable_transitions += 1
        else:
            skipped_source_transitions += 1

        if same_identity and source_allows_diff and not is_manual:
            keys = ((key, current_map[key]) for key in current.changed_keys if key in current_map)
        else:
            keys = current_map.items()
        for key, current_song in keys:
            previous_song = previous_map.get(key)
            if previous_song is None:
                stage = safe_int(current_song.get("stage_cnt"))
                score = safe_int(current_song.get("high_score"))
                stage_epochs[key] = CounterEpoch(identity, stage, stage)
                score_epochs[key] = CounterEpoch(identity, score, score)
                # A chart the archive had never seen before. It is still a real
                # play when the record's own last-play stamp falls inside this
                # observation interval: the stamp only moves when the chart is
                # played, so a stamp inside the interval proves at least one play
                # happened there. An archive backfill carries stamps from before
                # the interval and stays uncounted, which is what keeps a bulk
                # import from being booked as activity on the import date.
                first_seen_moment = None
                first_seen_warnings = ["first_seen_chart"]
                if same_identity and source_allows_diff and not is_manual:
                    if current.source in TRUSTED_PLAY_TIME_SOURCES:
                        first_seen_raw = current_song.get("update_datetime") or current_song.get("highscore_datetime")
                        first_seen_moment = _bounded_source_time(
                            first_seen_raw,
                            previous.observed_at,
                            current.observed_at,
                            reporting_start_at,
                            reporting_end_exclusive_at,
                        )
                        if first_seen_moment is None:
                            first_seen_warnings.append("record_updated_at_outside_observation_interval")
                    else:
                        first_seen_warnings.append("untrusted_time_source")
                if first_seen_moment is not None:
                    # Only the provable minimum is credited: the cumulative
                    # stage_cnt of a first appearance also covers plays from
                    # before this archive ever saw the chart.
                    after = _song_value_dict(_song_value_tuple(current_song))
                    events.append(
                        _base_event(
                            event_type="play_delta",
                            previous=previous,
                            current=current,
                            key=key,
                            representative_at=first_seen_moment,
                            time_precision="batch_last_play_proxy",
                            before={field: 0 for field in _SONG_VALUE_FIELDS},
                            after=after,
                            delta={
                                "playCount": 1,
                                "score": 0,
                                "clearUnlocked": False,
                                "fullComboUnlocked": False,
                                "dondafulUnlocked": False,
                            },
                            warnings=first_seen_warnings,
                        )
                    )
                continue

            if not same_identity or not source_allows_diff:
                stage = safe_int(current_song.get("stage_cnt"))
                score = safe_int(current_song.get("high_score"))
                stage_epochs[key] = CounterEpoch(identity, stage, stage)
                score_epochs[key] = CounterEpoch(identity, score, score)
                continue
            if is_manual:
                before_values = _song_value_tuple(previous_song)
                after_values = _song_value_tuple(current_song)
                changed = before_values != after_values
                if changed:
                    before = _song_value_dict(before_values)
                    after = _song_value_dict(after_values)
                    events.append(
                        _base_event(
                            event_type="manual_adjustment",
                            previous=previous,
                            current=current,
                            key=key,
                            representative_at=None,
                            time_precision="none",
                            before=before,
                            after=after,
                            delta={
                                "playCount": max(after["stage_cnt"] - before["stage_cnt"], 0),
                                "score": max(after["high_score"] - before["high_score"], 0),
                            },
                            warnings=["manual_source_not_counted_as_play"],
                        )
                    )
                stage_epochs[key] = CounterEpoch(identity, after_values[0], after_values[0])
                score_epochs[key] = CounterEpoch(identity, after_values[1], after_values[1])
                continue

            stage_delta, stage_warnings = _counter_delta(
                stage_epochs,
                key,
                identity,
                safe_int(previous_song.get("stage_cnt")),
                safe_int(current_song.get("stage_cnt")),
            )
            score_delta, score_warnings = _counter_delta(
                score_epochs,
                key,
                identity,
                safe_int(previous_song.get("high_score")),
                safe_int(current_song.get("high_score")),
            )

            stage_regressed = "counter_regression" in stage_warnings
            score_regressed = "counter_regression" in score_warnings
            if stage_regressed or score_regressed or stage_delta > 0 or score_delta > 0:
                before_values = _song_value_tuple(previous_song)
                after_values = _song_value_tuple(current_song)
                before = _song_value_dict(before_values)
                after = _song_value_dict(after_values)

            if stage_regressed or score_regressed:
                regression_fields = []
                if stage_regressed:
                    regression_fields.append("stage_cnt")
                if score_regressed:
                    regression_fields.append("high_score")
                events.append(
                    _base_event(
                        event_type="counter_anomaly",
                        previous=previous,
                        current=current,
                        key=key,
                        representative_at=None,
                        time_precision="none",
                        before=before,
                        after=after,
                        delta={"fields": regression_fields},
                        warnings=stage_warnings + score_warnings,
                    )
                )

            if stage_delta > 0:
                representative_at = None
                precision = "interval_only"
                warnings = list(stage_warnings)
                if current.source in TRUSTED_PLAY_TIME_SOURCES:
                    update_raw = current_song.get("update_datetime")
                    if _source_time_outside_window(
                        update_raw, reporting_start_at, reporting_end_exclusive_at
                    ):
                        warnings.append("record_updated_at_outside_reporting_window")
                        representative_at = None
                    else:
                        representative_at = _bounded_source_time(
                            update_raw,
                            previous.observed_at,
                            current.observed_at,
                            reporting_start_at,
                            reporting_end_exclusive_at,
                        )
                    if representative_at:
                        precision = "batch_last_play_proxy"
                    elif stage_delta > 0:
                        warnings.append("record_updated_at_outside_observation_interval")
                else:
                    warnings.append("untrusted_time_source")
                events.append(
                    _base_event(
                        event_type="play_delta",
                        previous=previous,
                        current=current,
                        key=key,
                        representative_at=representative_at,
                        time_precision=precision,
                        before=before,
                        after=after,
                        delta={
                            "playCount": stage_delta,
                            "score": score_delta,
                            "clearUnlocked": before["clear_cnt"] <= 0 < after["clear_cnt"],
                            "fullComboUnlocked": before["full_combo_cnt"] <= 0 < after["full_combo_cnt"],
                            "dondafulUnlocked": before["dondaful_combo_cnt"] <= 0 < after["dondaful_combo_cnt"],
                        },
                        warnings=warnings,
                    )
                )

            if score_delta > 0:
                representative_at = None
                precision = "interval_only"
                warnings = list(score_warnings)
                if current.source in TRUSTED_PLAY_TIME_SOURCES:
                    highscore_raw = current_song.get("highscore_datetime")
                    if _source_time_outside_window(
                        highscore_raw, reporting_start_at, reporting_end_exclusive_at
                    ):
                        warnings.append("highscore_recorded_at_outside_reporting_window")
                        representative_at = None
                    else:
                        representative_at = _bounded_source_time(
                            highscore_raw,
                            previous.observed_at,
                            current.observed_at,
                            reporting_start_at,
                            reporting_end_exclusive_at,
                        )
                    if representative_at:
                        precision = "source_highscore_time"
                    elif score_delta > 0:
                        warnings.append("highscore_recorded_at_outside_observation_interval")
                else:
                    warnings.append("untrusted_time_source")
                events.append(
                    _base_event(
                        event_type="high_score",
                        previous=previous,
                        current=current,
                        key=key,
                        representative_at=representative_at,
                        time_precision=precision,
                        before=before,
                        after=after,
                        delta={"score": score_delta},
                        warnings=warnings,
                    )
                )

        previous_map = current_map

    events.sort(
        key=lambda item: (
            item["observedBetween"]["to"],
            item.get("representativeAt") or "",
            item["songNo"],
            item["level"],
            item["type"],
            item["eventId"],
        )
    )
    return events, {
        "comparableTransitionCount": comparable_transitions,
        "skippedSourceTransitionCount": skipped_source_transitions,
    }
