from __future__ import annotations

import io
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..score_calculator import (
    aggregate_topN_value,
    compute_all_from_userdata_records,
)
from .constants import (
    DIMENSION_CONFIG,
    KEYWORD_CHART_LIMIT,
    KEYWORD_TITLE_KEYS,
    MIN_CHALLENGE_PLAYS,
    MIN_SPEED_RECORDS,
    VALID_SPEEDS,
)
from .eligibility import highest_difficulty_tier, is_eligible_candidate
from .helpers import build_song_map, content_sha256, iso_datetime, metric, parse_datetime, safe_float, safe_int
from ..chart_roll_metadata import has_chart_roll_metadata_override, resolve_chart_roll_metadata

MAX_POUND_SPEED = 60.0


def load_song_meta_map(path: str | Path) -> Dict[int, Dict[str, Any]]:
    try:
        import json

        with Path(path).open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return {}
    rows = payload if isinstance(payload, list) else payload.get("songs", []) if isinstance(payload, dict) else []
    return {
        safe_int(item.get("id")): item
        for item in rows
        if isinstance(item, dict) and safe_int(item.get("id")) > 0
    }


def song_name(song_no: int, song_meta: Dict[int, Dict[str, Any]], fallback: str = "") -> str:
    meta = song_meta.get(song_no) or {}
    return str(meta.get("song_name") or meta.get("song_name_jp") or fallback or f"ID {song_no}").strip()


def song_payload(
    song_no: int,
    level: int,
    song_meta: Dict[int, Dict[str, Any]],
    fallback: str = "",
) -> Dict[str, Any]:
    meta = song_meta.get(song_no) or {}
    return {
        "songNo": song_no,
        "level": level,
        "songName": song_name(song_no, song_meta, fallback),
        "songNameJa": str(meta.get("song_name_jp") or meta.get("song_name") or fallback or f"ID {song_no}").strip(),
        "stars": safe_float(meta.get(f"level_{level}"), 0.0),
    }


def estimate_pound_speed(song: Dict[str, Any], song_meta: Dict[int, Dict[str, Any]], key: Tuple[int, int]) -> Optional[float]:
    """Estimate hits per second from a chart's roll window and user roll count.

    The annual pound story intentionally uses one explicit definition:
    ``(pound_cnt - fixed balloon hits) / variable roll seconds``.
    ``None`` means the chart metadata is insufficient and must stay a fallback.
    """
    song_no, level = key
    meta = song_meta.get(song_no) or {}
    roll_time_rows = meta.get("roll_times")
    balloon_rows = meta.get("balloons")
    roll_times = meta.get("roll_time")
    balloon_nums = meta.get("balloon_num")
    raw_rolls = roll_time_rows[level - 1] if isinstance(roll_time_rows, list) and 1 <= level <= len(roll_time_rows) else None
    raw_balloons = balloon_rows[level - 1] if isinstance(balloon_rows, list) and 1 <= level <= len(balloon_rows) else None
    branch = "N" if (song_no, level) in {(1352, 4), (67, 4)} else "M"
    resolved_rolls, resolved_balloons = resolve_chart_roll_metadata(
        song_no, level, raw_rolls, raw_balloons, branch=branch
    )
    if resolved_rolls:
        roll_seconds = sum(safe_float(value, 0.0) for value in resolved_rolls)
    elif not isinstance(roll_times, list) or not 1 <= level <= len(roll_times):
        return None
    else:
        roll_seconds = safe_float(roll_times[level - 1], 0.0)
    if roll_seconds <= 0:
        return None
    fixed_balloons = 0
    if has_chart_roll_metadata_override(song_no, level):
        fixed_balloons = max(0, sum(safe_int(value) for value in resolved_balloons))
    elif resolved_balloons:
        fixed_balloons = max(0, sum(safe_int(value) for value in resolved_balloons))
    elif isinstance(balloon_nums, list) and 1 <= level <= len(balloon_nums):
        fixed_balloons = max(0, safe_int(balloon_nums[level - 1]))
    pound_count = max(0, safe_int(song.get("pound_cnt")))
    speed = round(max(0.0, pound_count - fixed_balloons) / roll_seconds, 2)
    # A chart-speed estimate above 60 hits/s is not a plausible player
    # result; treat it as invalid metadata rather than presenting a capped or
    # otherwise fabricated value in the annual report.
    if speed > MAX_POUND_SPEED:
        return None
    return speed


def _play_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [item for item in events if item.get("type") == "play_delta" and safe_int((item.get("delta") or {}).get("playCount")) > 0]


def _timed_play_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        item
        for item in _play_events(events)
        if item.get("timePrecision") == "batch_last_play_proxy" and item.get("representativeAt")
    ]


def _event_moment(event: Dict[str, Any]) -> Optional[datetime]:
    return parse_datetime(event.get("representativeAt"))


def _event_plays(event: Dict[str, Any]) -> int:
    return safe_int((event.get("delta") or {}).get("playCount"))


def _event_fallback_date(event: Dict[str, Any]) -> str:
    if event.get("representativeDate"):
        return str(event["representativeDate"])
    observed = (event.get("observedBetween") or {}).get("to")
    parsed = parse_datetime(observed)
    return parsed.date().isoformat() if parsed else ""


def aggregate_observed_charts(events: Iterable[Dict[str, Any]]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    result: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for event in _play_events(events):
        key = safe_int(event.get("songNo")), safe_int(event.get("level"))
        row = result.setdefault(key, {"playCount": 0, "activeDates": set(), "events": []})
        row["playCount"] += _event_plays(event)
        active_date = _event_fallback_date(event)
        if active_date:
            row["activeDates"].add(active_date)
        row["events"].append(event)
    return result


def build_overview(
    mode: str,
    events: List[Dict[str, Any]],
    end_state: Dict[str, Any],
    *,
    partial_start: bool,
) -> Dict[str, Any]:
    chart_totals: Dict[Tuple[int, int], Dict[str, Any]] = {}
    if mode == "version_observed":
        chart_totals = aggregate_observed_charts(events)
        play_count = sum(row["playCount"] for row in chart_totals.values())
        unique_songs = len({key[0] for key, row in chart_totals.items() if row["playCount"] > 0})
        status = "lower_bound" if partial_start else "observed"
    else:
        current = build_song_map(end_state)
        play_count = sum(max(safe_int(song.get("stage_cnt")), 0) for song in current.values())
        unique_songs = len({key[0] for key, song in current.items() if safe_int(song.get("stage_cnt")) > 0})
        status = "exact"
    end_map = build_song_map(end_state)
    unique_charts = sum(1 for song in end_map.values() if safe_int(song.get("stage_cnt")) > 0)
    current_clear = sum(1 for song in end_map.values() if safe_int(song.get("clear_cnt")) > 0)
    current_full_combo = sum(1 for song in end_map.values() if safe_int(song.get("full_combo_cnt")) > 0)
    current_dondaful = sum(1 for song in end_map.values() if safe_int(song.get("dondaful_combo_cnt")) > 0)
    current_kiwami = sum(1 for song in end_map.values() if safe_int(song.get("best_score_rank")) >= 8)
    return metric(
        status,
        {
            "playCount": play_count,
            "uniqueSongs": unique_songs,
            "uniqueCharts": unique_charts if mode == "current_archive" else len(chart_totals),
            "estimatedSeconds": play_count * 180,
            "estimatedTimeText": "",
            "currentClearCharts": current_clear,
            "currentFullComboCharts": current_full_combo,
            "currentDondafulCharts": current_dondaful,
            "currentKiwamiCharts": current_kiwami,
        },
    )


def build_cover_song_pool(
    end_state: Dict[str, Any],
    song_meta: Dict[int, Dict[str, Any]],
    *,
    seed: str,
    cover_dir: str | Path,
    limit: int = 36,
) -> List[Dict[str, Any]]:
    cover_root = Path(cover_dir)
    songs: Dict[int, Tuple[int, int]] = {}
    for (song_no, level), song in build_song_map(end_state).items():
        plays = max(safe_int(song.get("stage_cnt")), 0)
        if plays <= 0 or not (cover_root / f"{song_no}.png").is_file():
            continue
        current = songs.get(song_no)
        if current is None or (plays, level) > current:
            songs[song_no] = (plays, level)
    ranked = sorted(
        songs.items(),
        key=lambda item: content_sha256({"seed": seed, "songNo": item[0]}),
    )[:limit]
    return [
        {**song_payload(song_no, level, song_meta), "playCount": plays}
        for song_no, (plays, level) in ranked
    ]


def build_favorite_song(
    mode: str,
    events: List[Dict[str, Any]],
    end_state: Dict[str, Any],
    song_meta: Dict[int, Dict[str, Any]],
    *,
    partial_start: bool,
) -> Dict[str, Any]:
    charts: Dict[Tuple[int, int], Dict[str, Any]] = {}
    if mode == "version_observed":
        charts = aggregate_observed_charts(events)
    else:
        for key, song in build_song_map(end_state).items():
            count = max(safe_int(song.get("stage_cnt")), 0)
            if count:
                charts[key] = {"playCount": count, "activeDates": set(), "events": []}
    songs: Dict[int, Dict[str, Any]] = {}
    for (song_no, level), row in charts.items():
        target = songs.setdefault(song_no, {"playCount": 0, "activeDates": set(), "levels": Counter()})
        target["playCount"] += row["playCount"]
        target["activeDates"].update(row.get("activeDates") or set())
        target["levels"][level] += row["playCount"]
    if not songs:
        return metric("unavailable", None, "no_play_records")
    song_no, row = max(
        songs.items(),
        key=lambda item: (item[1]["playCount"], len(item[1]["activeDates"]), -item[0]),
    )
    favorite_level = max(row["levels"], key=lambda level: (row["levels"][level], level))
    status = "exact" if mode == "current_archive" else "lower_bound" if partial_start else "observed"
    return metric(
        status,
        {
            **song_payload(song_no, favorite_level, song_meta),
            "playCount": row["playCount"],
            "activeDays": len(row["activeDates"]),
            "favoriteLevel": favorite_level,
        },
    )


def _top_song_from_events(
    events: Iterable[Dict[str, Any]], song_meta: Dict[int, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    totals: Dict[int, Dict[str, Any]] = {}
    for event in events:
        song_no = safe_int(event.get("songNo"))
        level = safe_int(event.get("level"))
        row = totals.setdefault(song_no, {"playCount": 0, "levels": Counter()})
        row["playCount"] += _event_plays(event)
        row["levels"][level] += _event_plays(event)
    if not totals:
        return None
    song_no, row = max(totals.items(), key=lambda item: (item[1]["playCount"], -item[0]))
    level = max(row["levels"], key=lambda value: (row["levels"][value], value))
    return {**song_payload(song_no, level, song_meta), "playCount": row["playCount"]}


def build_time_sections(
    events: List[Dict[str, Any]],
    song_meta: Dict[int, Dict[str, Any]],
    *,
    start_date: date,
    effective_end_date: date,
    time_eligible: bool,
    observed_first_date: Optional[date] = None,
    observed_last_date: Optional[date] = None,
) -> Dict[str, Dict[str, Any]]:
    names = (
        "obsessionSong",
        "favoriteShift",
        "monthlyFavorites",
        "weekdayActivity",
        "calendarActivity",
        "timeOfDay",
        "lateNight",
    )
    if not time_eligible:
        return {name: metric("unavailable", None, "insufficient_trusted_time_coverage") for name in names}
    timed = _timed_play_events(events)
    active_by_song: Dict[int, set[str]] = defaultdict(set)
    totals_by_song: Counter[int] = Counter()
    levels_by_song: Dict[int, Counter[int]] = defaultdict(Counter)
    for event in timed:
        song_no = safe_int(event.get("songNo"))
        active_by_song[song_no].add(str(event.get("representativeDate")))
        totals_by_song[song_no] += _event_plays(event)
        levels_by_song[song_no][safe_int(event.get("level"))] += _event_plays(event)
    obsession = None
    if active_by_song:
        song_no = max(active_by_song, key=lambda value: (len(active_by_song[value]), totals_by_song[value], -value))
        level = max(levels_by_song[song_no], key=lambda value: (levels_by_song[song_no][value], value))
        obsession = {
            **song_payload(song_no, level, song_meta),
            "activeDays": len(active_by_song[song_no]),
            "playCount": totals_by_song[song_no],
        }

    # The preference shift compares the player against their own history, so the
    # early/late windows are anchored to the span this account actually played
    # instead of the fixed season window. A season-anchored window can fall
    # entirely before the first observed play and silently produce no shift.
    shift_first = observed_first_date or start_date
    shift_last = observed_last_date or effective_end_date
    if shift_last < shift_first:
        shift_first, shift_last = start_date, effective_end_date
    period_seconds = max(
        (datetime.combine(shift_last, time.max) - datetime.combine(shift_first, time.min)).total_seconds(),
        1,
    )
    early_limit = datetime.combine(shift_first, time.min) + timedelta(seconds=period_seconds * 0.25)
    late_limit = datetime.combine(shift_last, time.max) - timedelta(seconds=period_seconds * 0.25)
    early = _top_song_from_events((e for e in timed if (_event_moment(e) or datetime.max) <= early_limit), song_meta)
    late = _top_song_from_events((e for e in timed if (_event_moment(e) or datetime.min) >= late_limit), song_meta)
    shift = {"oldFavorite": early, "newFavorite": late} if early and late and early["songNo"] != late["songNo"] else None

    months: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    weekday = [0] * 7
    dates: Counter[str] = Counter()
    periods = {"early_morning": 0, "morning": 0, "noon": 0, "afternoon": 0, "evening": 0, "late_night": 0}
    hourly = [0] * 24
    by_period: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    late_events: List[Dict[str, Any]] = []
    for event in timed:
        moment = _event_moment(event)
        if moment is None:
            continue
        plays = _event_plays(event)
        months[moment.strftime("%Y-%m")].append(event)
        weekday[moment.weekday()] += plays
        dates[moment.date().isoformat()] += plays
        hourly[moment.hour] += plays
        if moment.hour >= 22 or moment.hour < 5:
            period = "late_night"
            late_events.append(event)
        elif moment.hour < 9:
            period = "early_morning"
        elif moment.hour < 12:
            period = "morning"
        elif moment.hour < 14:
            period = "noon"
        elif moment.hour < 18:
            period = "afternoon"
        else:
            period = "evening"
        periods[period] += plays
        by_period[period].append(event)

    monthly = []
    for month, rows in sorted(months.items()):
        top = _top_song_from_events(rows, song_meta)
        monthly.append(
            {
                "month": month,
                "playCount": sum(_event_plays(row) for row in rows),
                "estimatedSeconds": sum(_event_plays(row) for row in rows) * 180,
                "song": top,
            }
        )
    active_weekdays = [index for index, value in enumerate(weekday) if value > 0]
    top_weekday = max(active_weekdays, key=lambda index: (weekday[index], -index)) if active_weekdays else 0
    bottom_weekday = min(active_weekdays, key=lambda index: (weekday[index], index)) if active_weekdays else 0

    longest = 0
    longest_start: Optional[date] = None
    longest_end: Optional[date] = None
    streak_start: Optional[date] = None
    previous_date: Optional[date] = None
    current = 0
    for active_date in [date.fromisoformat(value) for value in sorted(dates)]:
        if previous_date and active_date == previous_date + timedelta(days=1):
            current += 1
        else:
            current = 1
            streak_start = active_date
        if current > longest:
            longest = current
            longest_start = streak_start
            longest_end = active_date
        previous_date = active_date

    top_period = max(periods, key=periods.get)
    favorite_hour = max(range(24), key=lambda hour: (hourly[hour], -hour))
    latest_late = max(
        late_events,
        key=lambda event: (
            ((_event_moment(event) or datetime.min).hour + (24 if (_event_moment(event) or datetime.min).hour < 5 else 0)),
            (_event_moment(event) or datetime.min),
        ),
    ) if late_events else None
    night_dates = {str(event.get("nightDate")) for event in late_events}
    return {
        "obsessionSong": metric("proxy", obsession) if obsession else metric("unavailable", None, "no_timed_records"),
        "favoriteShift": metric("proxy", shift) if shift else metric("unavailable", None, "no_favorite_change"),
        "monthlyFavorites": metric("proxy", monthly),
        "weekdayActivity": metric("proxy", {"counts": weekday, "topWeekday": top_weekday, "bottomWeekday": bottom_weekday, "totalPlays": sum(weekday)}),
        "calendarActivity": metric("proxy", {"days": [{"date": key, "playCount": value} for key, value in sorted(dates.items())], "maxPlayCount": max(dates.values(), default=0), "activeDays": len(dates), "longestStreak": longest, "streakStart": longest_start.isoformat() if longest_start else None, "streakEnd": longest_end.isoformat() if longest_end else None}),
        "timeOfDay": metric("proxy", {"periods": periods, "hourlyCounts": hourly, "topPeriod": top_period, "favoriteHour": favorite_hour, "favoriteSong": _top_song_from_events(by_period[top_period], song_meta), "totalPlays": sum(periods.values())}),
        "lateNight": metric("proxy", {"playCount": sum(_event_plays(event) for event in late_events), "activeDays": len(night_dates), "latestAt": latest_late.get("representativeAt") if latest_late else None, "song": song_payload(safe_int(latest_late.get("songNo")), safe_int(latest_late.get("level")), song_meta) if latest_late else None}) if latest_late else metric("unavailable", None, "no_late_night_records"),
    }


def build_keyword_and_rating(
    mode: str,
    events: List[Dict[str, Any]],
    end_state: Dict[str, Any],
    *,
    rating_path: Optional[str | Path],
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[float]]:
    song_map = build_song_map(end_state)
    if not song_map or not rating_path:
        unavailable = metric("unavailable", None, "rating_data_unavailable")
        return unavailable, unavailable, None
    try:
        with redirect_stdout(io.StringIO()):
            results = compute_all_from_userdata_records(list(song_map.values()), json_path=str(rating_path))
            rating_value = float(aggregate_topN_value(results, "AI_rating", KEYWORD_CHART_LIMIT)) if results else 0.0
    except Exception:
        unavailable = metric("unavailable", None, "rating_calculation_failed")
        return unavailable, unavailable, None
    if not results:
        unavailable = metric("unavailable", None, "no_rating_candidates")
        return unavailable, unavailable, rating_value or None

    # Keep this profile identical to the default ``taikob20`` radar: every
    # dimension independently selects and aggregates its own Top 20 from the
    # user's complete score set.  The old annual implementation instead
    # averaged the year's most-played charts, which measured play preference
    # and could differ substantially from the player's taikob20 profile.
    radar = {
        key: round(float(aggregate_topN_value(results, label, KEYWORD_CHART_LIMIT)), 4)
        for key, label, _attr in DIMENSION_CONFIG
    }
    dimension = max(radar, key=radar.get)
    keyword = metric("exact", {"dimensionKey": dimension, "titleKey": KEYWORD_TITLE_KEYS[dimension], "score": radar[dimension], "radarValues": radar, "candidateCount": len(results)})
    rating = metric("exact", {"rating": round(rating_value, 4), "rank": None, "rankMin": None, "rankMax": None, "sampleSize": None, "percentile": None, "tier": None}) if rating_value > 0 else metric("unavailable", None, "rating_calculation_failed")
    return keyword, rating, rating_value or None


def build_static_personality_sections(
    mode: str,
    events: List[Dict[str, Any]],
    end_state: Dict[str, Any],
    song_meta: Dict[int, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    song_map = build_song_map(end_state)
    speed_counts: Counter[float] = Counter()
    for song in song_map.values():
        option = song.get("option_flg")
        if not isinstance(option, list) or not option:
            continue
        speed = round(safe_float(option[0]), 1)
        if speed in VALID_SPEEDS:
            speed_counts[speed] += 1
    speed = None
    if sum(speed_counts.values()) >= MIN_SPEED_RECORDS:
        preferred = max(speed_counts, key=lambda value: (speed_counts[value], value))
        speed = {"speed": preferred, "chartCount": speed_counts[preferred], "eligibleChartCount": sum(speed_counts.values()), "distribution": {f"{key:.1f}": value for key, value in sorted(speed_counts.items())}}

    # Near Dondaful, KEEP TRYING and HIGH SCORE all describe the top of the
    # player's range, so they share one candidate pool: their own hardest
    # difficulty tier, with 双打 charts and charts that are no longer on the
    # shelf removed first. Only after that trim does each section apply its own
    # ranking rule below.
    candidate_tier = highest_difficulty_tier(song_map.keys(), song_meta)

    near = []
    for key, song in song_map.items():
        if not is_eligible_candidate(key[0], key[1], song_meta, tier=candidate_tier):
            continue
        if safe_int(song.get("dondaful_combo_cnt")) > 0 or safe_int(song.get("ng_cnt")) != 0:
            continue
        ok = safe_int(song.get("ok_cnt"))
        if not 1 <= ok <= 10:
            continue
        near.append((ok, -key[1], -safe_int(song.get("high_score")), key[0], key, song))
    near.sort()
    near_data = None
    if near:
        _ok, _level_sort, _score_sort, _song_sort, key, song = near[0]
        near_data = {**song_payload(key[0], key[1], song_meta), "okCount": safe_int(song.get("ok_cnt")), "highScore": safe_int(song.get("high_score"))}

    observed = aggregate_observed_charts(events)
    challenge_rows = []
    for key, row in observed.items():
        if not is_eligible_candidate(key[0], key[1], song_meta, tier=candidate_tier):
            continue
        if row["playCount"] < MIN_CHALLENGE_PLAYS:
            continue
        current_song = song_map.get(key) or {}
        has_completion_record = (
            safe_int(current_song.get("full_combo_cnt")) > 0
            or safe_int(current_song.get("dondaful_combo_cnt")) > 0
        )
        unlocked = any((event.get("delta") or {}).get("fullComboUnlocked") or (event.get("delta") or {}).get("dondafulUnlocked") for event in row["events"])
        if has_completion_record or unlocked:
            continue
        stars = safe_float((song_meta.get(key[0]) or {}).get(f"level_{key[1]}"), 0.0)
        total_plays = max(safe_int(current_song.get("stage_cnt")), row["playCount"])
        challenge_rows.append((-row["playCount"], -stars, -total_plays, -key[1], key[0], key))
    challenge_rows.sort()
    challenge = None
    if challenge_rows:
        key = challenge_rows[0][-1]
        observed_plays = observed[key]["playCount"]
        total_plays = max(safe_int((song_map.get(key) or {}).get("stage_cnt")), observed_plays)
        challenge = {
            **song_payload(key[0], key[1], song_meta),
            "playCount": total_plays,
            "observedPlayCount": observed_plays,
        }

    pound_total = 0
    pound_max = None
    pound_speed_max = None
    for key, song in song_map.items():
        value = max(safe_int(song.get("pound_cnt")), 0)
        pound_total += value
        if pound_max is None or (value, -key[0], -key[1]) > (pound_max[0], -pound_max[1][0], -pound_max[1][1]):
            pound_max = (value, key)
        chart_speed = estimate_pound_speed(song, song_meta, key)
        if chart_speed is not None and (pound_speed_max is None or (chart_speed, -key[0], -key[1]) > (pound_speed_max[0], -pound_speed_max[1][0], -pound_speed_max[1][1])):
            pound_speed_max = (chart_speed, key, value)
    # Keep legacy pound ordering only when this build has no chart metadata at
    # all (for example, a fixture with an intentionally empty song catalog).
    # Real annual builds always load song_data.json, so the speed definition is
    # authoritative whenever at least one chart can be evaluated.
    selected_pound = pound_speed_max or pound_max
    top_pound_song = song_payload(selected_pound[1][0], selected_pound[1][1], song_meta) if selected_pound else None
    pound = {
        "totalPoundCount": pound_total,
        "topSong": top_pound_song,
        "topPoundCount": (pound_speed_max[2] if pound_speed_max else pound_max[0] if pound_max else 0),
        "speed": pound_speed_max[0] if pound_speed_max else None,
        "speedDefinition": "(pound_cnt - fixed_balloon_hits) / variable_roll_seconds",
        "copyKey": "pound_speed",
    }

    high_scores = [
        event
        for event in events
        if event.get("type") == "high_score"
        and event.get("timePrecision") == "source_highscore_time"
        and event.get("representativeAt")
        and is_eligible_candidate(
            safe_int(event.get("songNo")),
            event.get("level"),
            song_meta,
            tier=candidate_tier,
        )
    ]
    high_score = None
    if high_scores:
        event = max(high_scores, key=lambda item: (safe_int((item.get("after") or {}).get("high_score")), safe_int((item.get("delta") or {}).get("score")), item.get("representativeAt") or ""))
        high_score = {**song_payload(safe_int(event.get("songNo")), safe_int(event.get("level")), song_meta), "highScore": safe_int((event.get("after") or {}).get("high_score")), "scoreDelta": safe_int((event.get("delta") or {}).get("score")), "recordedAt": event.get("representativeAt"), "timePrecision": "source_highscore_time"}

    observed_status = "observed" if mode == "version_observed" else "unavailable"
    return {
        "speedProfile": metric("exact", speed) if speed else metric("unavailable", None, "fewer_than_11_non_default_speed_records"),
        "nearDondaful": metric("exact", near_data) if near_data else metric("unavailable", None, "no_near_dondaful_record"),
        "challenge": metric(observed_status, challenge) if challenge else metric("unavailable", None, "no_qualifying_challenge"),
        "pound": metric("exact", pound),
        "highScore": metric("proxy", high_score) if high_score else metric("unavailable", None, "no_trusted_highscore_time"),
    }


def build_achievements_and_breakthrough(
    events: List[Dict[str, Any]],
    start_state: Dict[str, Any],
    end_state: Dict[str, Any],
    song_meta: Dict[int, Dict[str, Any]],
    *,
    rating_start: Optional[float] = None,
    rating_end: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    end_map = build_song_map(end_state)
    observed = aggregate_observed_charts(events)
    current = {
        "clearCharts": sum(1 for song in end_map.values() if safe_int(song.get("clear_cnt")) > 0),
        "fullComboCharts": sum(1 for song in end_map.values() if safe_int(song.get("full_combo_cnt")) > 0),
        "dondafulCharts": sum(1 for song in end_map.values() if safe_int(song.get("dondaful_combo_cnt")) > 0),
        "extremeCharts": sum(1 for song in end_map.values() if safe_int(song.get("best_score_rank")) >= 8),
    }
    unlock_flags = (("clearUnlocked", "clear"), ("fullComboUnlocked", "full_combo"), ("dondafulUnlocked", "dondaful"))
    counter_fields = {
        "clear": "clear_cnt",
        "full_combo": "full_combo_cnt",
        "dondaful": "dondaful_combo_cnt",
    }
    unlocks: Dict[str, List[Dict[str, Any]]] = {kind: [] for _flag, kind in unlock_flags}
    firsts = []
    highlights = []

    def achievement_payload(event: Dict[str, Any], kind: str) -> Dict[str, Any]:
        key = safe_int(event.get("songNo")), safe_int(event.get("level"))
        end_song = end_map.get(key) or {}
        total_plays = max(safe_int(end_song.get("stage_cnt")), 0)
        achievement_count = max(safe_int(end_song.get(counter_fields[kind])), 0)
        observed_plays = safe_int((observed.get(key) or {}).get("playCount"))
        stars = safe_float((song_meta.get(key[0]) or {}).get(f"level_{key[1]}"), 0.0)
        rarity_bonus = 42.0 if achievement_count == 1 else 12.0 / max(achievement_count, 1)
        hardship_score = round(stars * 12.0 + min(total_plays, 120) * 0.75 + observed_plays * 0.2 + rarity_bonus, 2)
        return {
            "type": kind,
            "scope": "observation_window",
            "observedAt": event.get("representativeAt"),
            "observedBetween": event.get("observedBetween"),
            "song": {
                **song_payload(key[0], key[1], song_meta),
                "playCount": total_plays,
            },
            "playCount": total_plays,
            "observedPlayCount": observed_plays,
            "achievementCount": achievement_count,
            "hardshipScore": hardship_score,
        }

    for flag, kind in unlock_flags:
        matching = [event for event in _play_events(events) if (event.get("delta") or {}).get(flag)]
        seen = set()
        candidates = []
        for event in matching:
            key = safe_int(event.get("songNo")), safe_int(event.get("level"))
            if key in seen:
                continue
            seen.add(key)
            candidate = achievement_payload(event, kind)
            candidates.append(candidate)
            unlocks[kind].append({
                **candidate["song"],
                "observedAt": candidate["observedAt"],
                "observedBetween": candidate["observedBetween"],
                "achievementCount": candidate["achievementCount"],
                "hardshipScore": candidate["hardshipScore"],
            })
        if matching:
            event = min(matching, key=lambda item: (item.get("representativeAt") or (item.get("observedBetween") or {}).get("to") or "", item.get("eventId") or ""))
            firsts.append(achievement_payload(event, kind))
        if candidates:
            highlights.append(max(
                candidates,
                key=lambda item: (
                    safe_float(item.get("hardshipScore")),
                    safe_float((item.get("song") or {}).get("stars")),
                    safe_int(item.get("playCount")),
                    -safe_int((item.get("song") or {}).get("songNo")),
                ),
            ))

    achievements = {
        "status": "observed",
        "current": current,
        "observedUnlocks": {key: {"count": len(value), "charts": value} for key, value in unlocks.items()},
        "observedFirsts": firsts,
        "highlights": highlights,
    }

    candidates: List[Tuple[float, int, str, Dict[str, Any]]] = []
    start_costume = ((start_state.get("profile") or {}).get("gameCostume") or {})
    end_costume = ((end_state.get("profile") or {}).get("gameCostume") or {})
    dan_before = safe_int(start_costume.get("got_dan_max"), 0)
    dan_after = safe_int(end_costume.get("got_dan_max"), 0)
    if dan_after > dan_before:
        candidates.append((10_000.0, 8, "dan", {"danBefore": dan_before, "danAfter": dan_after, "occurredAt": None, "observedBetween": None}))

    kind_weights = {
        "dondaful": 70.0,
        "extreme": 62.0,
        "full_combo": 44.0,
        "clear": 20.0,
    }

    def breakthrough_payload(event: Dict[str, Any], kind: str) -> Tuple[float, Dict[str, Any]]:
        key = safe_int(event.get("songNo")), safe_int(event.get("level"))
        end_song = end_map.get(key) or {}
        stars = safe_float((song_meta.get(key[0]) or {}).get(f"level_{key[1]}"), 0.0)
        total_plays = max(safe_int(end_song.get("stage_cnt")), 0)
        observed_plays = safe_int((observed.get(key) or {}).get("playCount"))
        count_field = counter_fields.get(kind)
        achievement_count = max(safe_int(end_song.get(count_field)), 0) if count_field else 0
        singleton_bonus = 38.0 if achievement_count == 1 else 0.0
        score = (
            kind_weights[kind]
            + stars * 10.0
            + min(total_plays, 120) * 0.8
            + observed_plays * 0.2
            + singleton_bonus
        )
        return score, {
            **song_payload(key[0], key[1], song_meta),
            "occurredAt": event.get("representativeAt"),
            "observedBetween": event.get("observedBetween"),
            "playCount": total_plays,
            "observedPlayCount": observed_plays,
            "achievementCount": achievement_count,
            "hardshipScore": round(score, 2),
        }

    for event in _play_events(events):
        key = safe_int(event.get("songNo")), safe_int(event.get("level"))
        stars = safe_float((song_meta.get(key[0]) or {}).get(f"level_{key[1]}"), 0.0)
        delta = event.get("delta") or {}
        if delta.get("dondafulUnlocked"):
            score, data = breakthrough_payload(event, "dondaful")
            candidates.append((score, 7, "dondaful", data))
        if "manual_correction_invalidates:best_score_rank" not in (event.get("warnings") or []) and safe_int((event.get("after") or {}).get("best_score_rank")) >= 8 > safe_int((event.get("before") or {}).get("best_score_rank")):
            score, data = breakthrough_payload(event, "extreme")
            candidates.append((score, 6, "extreme", data))
        if delta.get("fullComboUnlocked"):
            score, data = breakthrough_payload(event, "full_combo")
            kind = "ten_star_full_combo" if stars >= 10 else "full_combo"
            candidates.append((score, 5 if stars >= 10 else 4, kind, data))
        if delta.get("clearUnlocked"):
            score, data = breakthrough_payload(event, "clear")
            kind = "ten_star_clear" if stars >= 10 else "clear"
            candidates.append((score, 3 if stars >= 10 else 2, kind, data))
    if rating_start and rating_end and rating_end > rating_start:
        candidates.append((10.0, 1, "rating_gain", {"ratingBefore": round(rating_start, 4), "ratingAfter": round(rating_end, 4), "ratingDelta": round(rating_end - rating_start, 4), "occurredAt": None, "observedBetween": None}))
    if candidates:
        _score, _priority, kind, data = max(candidates, key=lambda item: (item[0], item[1], item[3].get("occurredAt") or ""))
        breakthrough = metric("observed", {"type": kind, **data})
    else:
        breakthrough = metric("unavailable", None, "no_observed_breakthrough")
    return achievements, breakthrough


def choose_final_title(
    mode: str,
    overview: Dict[str, Any],
    breakthrough: Dict[str, Any],
    speed: Dict[str, Any],
    keyword: Dict[str, Any],
) -> Dict[str, Any]:
    play_count = safe_int((overview.get("data") or {}).get("playCount"))
    if mode == "version_observed" and play_count < 5:
        return {"titleKey": "newcomer", "evidenceKey": "observed_play_count", "evidenceValue": play_count}
    if breakthrough.get("data"):
        return {"titleKey": f"breakthrough_{breakthrough['data'].get('type')}", "evidenceKey": "breakthrough", "evidenceValue": breakthrough["data"].get("type")}
    if speed.get("data"):
        return {"titleKey": "speed_profile", "evidenceKey": "speed", "evidenceValue": speed["data"].get("speed")}
    if keyword.get("data"):
        return {"titleKey": keyword["data"].get("titleKey", "encouragement"), "evidenceKey": "keyword", "evidenceValue": keyword["data"].get("dimensionKey")}
    return {"titleKey": "archive_keeper" if mode == "current_archive" else "encouragement", "evidenceKey": "mode", "evidenceValue": mode}
