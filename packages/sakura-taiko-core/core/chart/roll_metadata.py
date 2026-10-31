from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

@dataclass(frozen=True)
class ChartRollMetadataOverride:
    """Known per-note roll metadata corrections for aggregated upstream rows."""
    roll_times: Tuple[float, ...]
    balloons: Tuple[int, ...]
    is_played: bool | None = None
    branch: str | None = None
    branch_balloons: Tuple[Tuple[str, Tuple[int, ...]], ...] = ()
_CHART_ROLL_METADATA_OVERRIDES = {(277, 4): ChartRollMetadataOverride(roll_times=(0.843,), balloons=(72,), is_played=True), (1214, 4): ChartRollMetadataOverride(roll_times=(17.291911,), balloons=(31,), is_played=True), (890, 4): ChartRollMetadataOverride(roll_times=(0.532, 0.532, 0.532, 0.231, 0.231, 0.231, 0.231, 0.231, 0.116), balloons=(6, 6, 6, 6, 6, 6, 6, 938, 8), is_played=True), (681, 5): ChartRollMetadataOverride(roll_times=(0.157143, 0.157143, 1.028571), balloons=(5, 4, 4, 4, 4), is_played=True), (1061, 5): ChartRollMetadataOverride(roll_times=(0.142045,) * 6 + (2.017045,), balloons=(2,), is_played=True), (1274, 4): ChartRollMetadataOverride(roll_times=(0.259434, 0.259434, 0.259434, 0.259434, 0.683962, 3.372642, 0.542453, 0.683962, 0.259434, 0.259434, 0.683962), balloons=(24,), is_played=True), (775, 5): ChartRollMetadataOverride(roll_times=(0.104167,), balloons=(45,), is_played=True), (1352, 4): ChartRollMetadataOverride(roll_times=(0.621622, 0.621622, 0.621622, 0.621622, 2.567568), balloons=(0,), is_played=True, branch='N'), (67, 4): ChartRollMetadataOverride(roll_times=(0.172414,), balloons=(30,), is_played=True, branch='N', branch_balloons=(('N', (30,)), ('E', (4,)), ('M', (12,)))), (519, 5): ChartRollMetadataOverride(roll_times=(0.71604,), balloons=(), is_played=True), (302, 4): ChartRollMetadataOverride(roll_times=(1.208849,), balloons=(), is_played=True), (751, 4): ChartRollMetadataOverride(roll_times=(0.201343,), balloons=(), is_played=True), (1130, 4): ChartRollMetadataOverride(roll_times=(0.653847,), balloons=(3,), is_played=True), (149, 4): ChartRollMetadataOverride(roll_times=(0.653845, 0.653845), balloons=(12, 12, 12, 12), is_played=True), (149, 5): ChartRollMetadataOverride(roll_times=(1.576921,), balloons=(), is_played=True), (163, 4): ChartRollMetadataOverride(roll_times=(0.5, 1.382352), balloons=(), is_played=True), (355, 4): ChartRollMetadataOverride(roll_times=(0.53125, 0.53125, 0.729167), balloons=(100, 6), is_played=True), (770, 4): ChartRollMetadataOverride(roll_times=(7.421042,), balloons=(), is_played=True)}

def resolve_chart_roll_metadata(song_id: int, level: int, roll_times: Iterable[float] | None, balloons: Iterable[int] | None, branch: str | None=None) -> tuple[list[float], list[int]]:
    override = _CHART_ROLL_METADATA_OVERRIDES.get((int(song_id), int(level)))
    if override is not None:
        selected_branch = (branch or override.branch or 'M').upper()
        branch_values = dict(override.branch_balloons).get(selected_branch)
        return (list(override.roll_times), list(branch_values if branch_values is not None else override.balloons))
    return (list(roll_times or ()), list(balloons or ()))

def has_chart_roll_metadata_override(song_id: int, level: int) -> bool:
    return (int(song_id), int(level)) in _CHART_ROLL_METADATA_OVERRIDES

def apply_chart_roll_metadata_overrides(song_record: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Apply canonical chart metadata immediately before a song record is saved."""
    try:
        song_id = int(song_record.get('id'))
    except (TypeError, ValueError):
        return song_record
    matching = [(level, override) for (override_song_id, level), override in _CHART_ROLL_METADATA_OVERRIDES.items() if override_song_id == song_id]
    if not matching:
        return song_record
    fields = {'roll_times': song_record.get('roll_times'), 'roll_time': song_record.get('roll_time'), 'balloons': song_record.get('balloons'), 'balloon_num': song_record.get('balloon_num')}
    for key, value in fields.items():
        if not isinstance(value, list):
            fields[key] = [None] * 5
        elif len(value) < 5:
            fields[key] = [*value, *[None] * (5 - len(value))]
        else:
            fields[key] = list(value)
    for level, override in matching:
        index = level - 1
        roll_times = list(override.roll_times)
        balloons = list(override.balloons)
        fields['roll_times'][index] = roll_times
        fields['roll_time'][index] = round(sum(roll_times), 6)
        fields['balloons'][index] = balloons
        fields['balloon_num'][index] = int(sum(balloons))
        if override.is_played is not None:
            song_record['isPlayed'] = override.is_played
    song_record.update(fields)
    return song_record
