from __future__ import annotations

from .corrections import reconcile_manual_corrections
from .constants import MANUAL_SOURCES
from .helpers import SHANGHAI_TZ

import copy
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .dan_state import read_dan_state
from .finaltitle import compute_final_title
from .standing_dan import resolve_standing_presentation
from .aggregates import (
    build_achievements_and_breakthrough,
    build_cover_song_pool,
    build_favorite_song,
    build_keyword_and_rating,
    build_overview,
    build_static_personality_sections,
    build_time_sections,
    choose_final_title,
    load_song_meta_map,
)
from .constants import (
    ALGORITHM_VERSION,
    DEFAULT_VERSION,
    MIN_TIMED_ACTIVE_DAYS,
    MIN_TIMED_EVENT_RECORDS,
    RATING_DATA_PATH,
    SCHEMA_VERSION,
    SONG_DATA_PATH,
    TIME_COVERAGE_THRESHOLD,
    USERDATA_DIR,
)
from .events import build_observation_events
from .helpers import (
    content_sha256,
    file_sha256,
    format_dan_grade,
    iso_date,
    iso_datetime,
    metric,
    parse_datetime,
    safe_int,
)
from .snapshots import load_snapshot_history, select_window
from .archive_fallback import select_current_archive
from .profiling import mark_profile_stage, observe_profile_objects
from .reporting_window import ReportingWindow, resolve_reporting_window


def resolve_version(version: str | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(version, dict):
        payload = {**DEFAULT_VERSION, **version}
    elif str(version).strip() == DEFAULT_VERSION["key"]:
        payload = dict(DEFAULT_VERSION)
    else:
        raise ValueError(f"unsupported annual version: {version}")
    payload["key"] = str(payload.get("key") or DEFAULT_VERSION["key"]).strip()
    payload["name"] = str(payload.get("name") or DEFAULT_VERSION["name"]).strip()
    payload["timezone"] = "Asia/Shanghai"
    return payload


def _profile_card(state: Dict[str, Any]) -> Dict[str, Any]:
    profile = state.get("profile") or {}
    costume = profile.get("gameCostume") if isinstance(profile.get("gameCostume"), dict) else {}
    dan = costume.get("dan_name") if isinstance(costume.get("dan_name"), dict) else {}
    return {
        "nickname": str(profile.get("mydon_name") or costume.get("mydon_name") or "太鼓玩家").strip(),
        "title": str(costume.get("title") or profile.get("title") or "").strip(),
        "titleplateId": safe_int(costume.get("titleplate_id"), 0),
        "province": str(profile.get("province") or "").strip() or None,
        "displayDan": bool(profile.get("is_disp_dan_on", costume.get("is_disp_dan_on", False))),
        "danName": format_dan_grade(dan.get("grade")),
        "danLevel": safe_int(dan.get("level"), 0) or None,
        "danMax": safe_int(costume.get("got_dan_max"), 0) or None,
        "myDonUrl": "/api/account/my-don",
        "costume": {
            key: safe_int(costume.get(key), 0)
            for key in (
                "costume_1",
                "costume_2",
                "costume_3",
                "costume_4",
                "costume_5",
                "color_limb",
                "color_body",
                "color_face",
            )
        },
    }


def _time_coverage(events: list[Dict[str, Any]]) -> Dict[str, Any]:
    plays = [item for item in events if item.get("type") == "play_delta"]
    total = sum(safe_int((item.get("delta") or {}).get("playCount")) for item in plays)
    trusted = [
        item
        for item in plays
        if item.get("timePrecision") == "batch_last_play_proxy" and item.get("representativeAt")
    ]
    timed = sum(safe_int((item.get("delta") or {}).get("playCount")) for item in trusted)
    ratio = timed / total if total > 0 else 0.0
    active_days = len({item.get("representativeDate") for item in trusted if item.get("representativeDate")})
    eligible = (
        total > 0
        and ratio >= TIME_COVERAGE_THRESHOLD
        and len(trusted) >= MIN_TIMED_EVENT_RECORDS
        and active_days >= MIN_TIMED_ACTIVE_DAYS
    )
    return {
        "status": "proxy" if eligible else "unavailable",
        "totalObservedPlayCount": total,
        "trustedProxyPlayCount": timed,
        "ratio": round(ratio, 4),
        "trustedEventCount": len(trusted),
        "activeDays": active_days,
        "threshold": TIME_COVERAGE_THRESHOLD,
        "minimumEventCount": MIN_TIMED_EVENT_RECORDS,
        "minimumActiveDays": MIN_TIMED_ACTIVE_DAYS,
        "eligible": eligible,
    }


def _source_breakdown(selection: Any) -> list[Dict[str, Any]]:
    counts = Counter(item.source for item in selection.window_snapshots)
    return [{"source": source, "snapshotCount": count} for source, count in sorted(counts.items())]


def _input_fingerprint(
    selection: Any,
    song_data_path: str | Path,
    rating_path: Optional[str | Path],
    reporting_window: ReportingWindow,
    correction_snapshots=(),
) -> str:
    inputs: Dict[str, Any] = {
        "algorithm": ALGORITHM_VERSION,
        "manualCorrections": [{"name": item.path.name, "sha256": item.content_hash} for item in correction_snapshots],
        "reportingWindow": reporting_window.fingerprint_payload(),
        "snapshots": [
            {"name": item.path.name, "sha256": item.content_hash}
            for item in selection.snapshots
        ],
    }
    for key, raw_path in (("songData", song_data_path), ("ratingData", rating_path)):
        if raw_path and Path(raw_path).exists():
            inputs[key] = file_sha256(raw_path)
    return content_sha256(inputs)


def build_annual_result(
    taiko_id: str | int,
    version: str | Dict[str, Any] = DEFAULT_VERSION["key"],
    *,
    userdata_dir: str | Path = USERDATA_DIR,
    song_data_path: str | Path = SONG_DATA_PATH,
    rating_path: Optional[str | Path] = RATING_DATA_PATH,
    generated_at: Optional[datetime] = None,
    progress: Optional[Callable[[str, int, Dict[str, Any]], None]] = None,
    allow_current_archive: bool = False,
) -> Dict[str, Any]:
    def report(stage: str, percent: int, **detail: Any) -> None:
        if progress:
            progress(stage, percent, detail)

    generated_at = generated_at or datetime.now()
    version_payload = resolve_version(version)
    reporting_window = resolve_reporting_window(version_payload)
    start_date = reporting_window.start_date
    end_date = reporting_window.end_inclusive_date
    start_at = reporting_window.start_at
    end_exclusive_at = reporting_window.end_exclusive_at
    report("history", 15)
    history = load_snapshot_history(taiko_id, userdata_dir=userdata_dir)
    if not history.snapshots:
        raise ValueError("no snapshots available")
    archive_fallback = False
    try:
        selection = select_window(
            history.snapshots,
            start_date=start_date,
            generated_at=generated_at,
            end_date=end_date,
            start_at=start_at,
            end_exclusive_at=end_exclusive_at,
        )
    except ValueError as error:
        if not allow_current_archive or str(error) != "no snapshots in annual window":
            raise
        selection = select_current_archive(history, end_date)
        archive_fallback = True
        history.warnings.append("current_archive_fallback:" + iso_datetime(selection.baseline.observed_at))
    mark_profile_stage("selection_complete", rebuiltStateCount=len(history.snapshots))
    # The account's first real record is the earliest snapshot the sync pipeline
    # ever captured for it, not a timestamp inherited from the game's own
    # highscore archive. `select_window` only trims observation events, so the
    # replayed history still carries every snapshot the account has, and its
    # first entry is the authoritative "we started recording this player here".
    first_record_at = selection.snapshots[0].observed_at if selection.snapshots else None
    report("events", 42, snapshotCount=len(selection.window_snapshots))
    events, event_stats = build_observation_events(
        selection,
        start_date=start_date,
        effective_end_date=selection.effective_end_date,
        start_at=start_at,
        end_exclusive_at=end_exclusive_at,
    )
    events, selection, correction_warnings = reconcile_manual_corrections(events, selection, history)
    history.warnings.extend(correction_warnings)
    observe_profile_objects(event_count=len(events))
    mark_profile_stage("event_build_complete", eventCount=len(events))
    mode = "version_observed" if event_stats["comparableTransitionCount"] > 0 else "current_archive"
    if archive_fallback:
        mode = "current_archive"
    if mode == "current_archive":
        events = [item for item in events if item.get("type") == "manual_adjustment"]
    play_events = [item for item in events if item.get("type") == "play_delta"]
    report("summaries", 68, snapshotCount=len(selection.window_snapshots), eventCount=len(events))
    time_coverage = _time_coverage(events)
    song_meta = load_song_meta_map(song_data_path)
    overview = build_overview(mode, events, selection.end_state, partial_start=selection.partial_start)
    overview["data"]["coverSongs"] = build_cover_song_pool(
        selection.end_state,
        song_meta,
        seed=str(taiko_id),
        cover_dir=Path(song_data_path).parent.parent / "assets" / "cover",
    )
    favorite = build_favorite_song(mode, events, selection.end_state, song_meta, partial_start=selection.partial_start)
    # The preference shift compares the player with their own history, so both the
    # section windows and the reported span use the observed play span rather than
    # the fixed season window.
    observed_moments = sorted(
        moment
        for moment in (
            parse_datetime(item.get("representativeAt"))
            for item in play_events
            if item.get("timePrecision") == "batch_last_play_proxy"
        )
        if moment is not None
    )
    time_sections = build_time_sections(
        events,
        song_meta,
        start_date=start_date,
        effective_end_date=selection.effective_end_date,
        time_eligible=time_coverage["eligible"],
        observed_first_date=observed_moments[0].date() if observed_moments else None,
        observed_last_date=observed_moments[-1].date() if observed_moments else None,
    )
    keyword, rating, rating_end = build_keyword_and_rating(
        mode,
        events,
        selection.end_state,
        rating_path=rating_path,
    )
    personality = build_static_personality_sections(mode, events, selection.end_state, song_meta)
    achievements, breakthrough = build_achievements_and_breakthrough(
        events,
        selection.start_state,
        selection.end_state,
        song_meta,
        rating_end=rating_end,
    )
    sections = {
        "favoriteSong": favorite,
        **time_sections,
        "keyword": keyword,
        "ratingRank": rating,
        **personality,
        "milestones": metric("observed", achievements["highlights"]) if achievements["highlights"] else metric("unavailable", None, "no_observed_unlocks"),
        "breakthrough": breakthrough,
    }
    # The legacy FinalTitle waterfall (newcomer -> breakthrough -> speed -> keyword ->
    # archive_keeper/encouragement) is superseded by the Copy-3B personality model below;
    # `choose_final_title` is kept for reference tooling only.
    input_fingerprint = _input_fingerprint(selection, song_data_path, rating_path, reporting_window, (item for item in history.snapshots if item.source in MANUAL_SOURCES or "kinoko-" in item.path.name))
    if archive_fallback:
        input_fingerprint = content_sha256({"input": input_fingerprint, "fallback": "single-current-v1"})
    summary_id = f"annual_{content_sha256({'taikoId': str(taiko_id), 'version': version_payload['key'], 'input': input_fingerprint})[:24]}"

    precise_moments = [
        item.get("representativeAt")
        for item in play_events
        if item.get("representativeAt")
    ]
    observed_dates = {
        item.get("representativeDate")
        for item in play_events
        if item.get("timePrecision") == "batch_last_play_proxy" and item.get("representativeDate")
    }
    event_warnings = sorted({warning for item in events for warning in item.get("warnings") or []})
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "summaryId": summary_id,
        "generatedAt": (generated_at.replace(tzinfo=SHANGHAI_TZ) if generated_at.tzinfo is None else generated_at.astimezone(SHANGHAI_TZ)).isoformat(timespec="milliseconds"),
        "mode": mode,
        "version": {
            "key": version_payload["key"],
            "name": version_payload["name"],
            "startDate": iso_date(start_date),
            "endDate": iso_date(end_date),
            "effectiveEndDate": iso_date(selection.effective_end_date),
            "isOngoing": end_date is None,
            "timezone": "Asia/Shanghai",
        },
        "coverage": {
            "snapshotCount": len(selection.window_snapshots),
            "comparableSnapshotCount": event_stats["comparableTransitionCount"] + (1 if event_stats["comparableTransitionCount"] else 0),
            "firstSnapshotAt": iso_datetime(selection.window_snapshots[0].observed_at),
            "lastSnapshotAt": iso_datetime(selection.window_snapshots[-1].observed_at),
            "partialStart": selection.partial_start,
            "hasBaselineBeforeStart": not selection.partial_start,
            "sourceBreakdown": _source_breakdown(selection),
            "time": time_coverage,
            "warnings": sorted(set(history.warnings + event_warnings)),
        },
        "profileCard": _profile_card(selection.end_state),
        "period": {
            "status": "proxy" if time_coverage["eligible"] else "observed" if mode == "version_observed" else "exact",
            "firstActualPlayDate": iso_date(first_record_at.date()) if first_record_at else None,
            "firstRecordAt": iso_datetime(first_record_at),
            "lastRecordAt": max(precise_moments) if precise_moments else None,
            "totalDays": min(
                reporting_window.calendar_days,
                (selection.effective_end_date - start_date).days + 1,
            ),
            "activeDays": len(observed_dates) if time_coverage["eligible"] else None,
        },
        "overview": overview,
        "sections": sections,
        "achievements": achievements,
        "poster": {
            "status": "ready_for_render",
            "summaryId": summary_id,
            "defaultLocale": "zh-CN",
            "supportedLocales": ["zh-CN", "ja-JP"],
            "width": 1080,
            "height": 1440,
        },
        "provenance": {
            "algorithmVersion": ALGORITHM_VERSION,
            "inputFingerprint": input_fingerprint,
            "eventCount": len(events),
            "playEventCount": len(play_events),
            "sourceSnapshotRange": {
                "first": selection.snapshots[0].path.name,
                "last": selection.snapshots[-1].path.name,
            },
            "inputSnapshotCount": len(selection.snapshots),
            "ignoredSnapshotCount": history.ignored_files,
            "warnings": sorted(set(history.warnings + event_warnings)),
        },
    }
    if archive_fallback:
        summary["period"].update(totalDays=1, lastRecordAt=iso_datetime(selection.baseline.observed_at))
    end_dan_state = read_dan_state(selection.end_state)
    final_decision = compute_final_title(
        summary,
        dan_state=end_dan_state,
        snapshots=((item.observed_at, item.state) for item in selection.window_snapshots),
        start_at=start_at,
        end_at=end_exclusive_at,
    )
    public_final_title = final_decision.public()
    # V4.1 strongDan overlay: presentation-only, on top of the untouched 45-key model.
    standing_presentation = resolve_standing_presentation(end_dan_state)
    public_final_title["strongDan"] = standing_presentation is not None
    public_final_title["standingPresentation"] = standing_presentation
    summary["finalTitle"] = public_final_title

    report("personal_complete", 80, snapshotCount=len(selection.window_snapshots), eventCount=len(events))
    mark_profile_stage("summary_complete", eventCount=len(events))
    return {"summary": summary, "events": events}


def build_annual_summary(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return build_annual_result(*args, **kwargs)["summary"]


def build_public_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    public = copy.deepcopy(summary)
    provenance = public.get("provenance") or {}
    public["provenance"] = {
        "algorithmVersion": provenance.get("algorithmVersion"),
        "eventCount": provenance.get("eventCount"),
    }
    rating = ((public.get("sections") or {}).get("ratingRank") or {}).get("data")
    if isinstance(rating, dict):
        tier = rating.get("tier")
        public["sections"]["ratingRank"]["data"] = {"tier": tier}
    return public
