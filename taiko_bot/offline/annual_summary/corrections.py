"""Reconcile assertions with explicit score corrections, never with lock status.

Unchanged counters keep their observations. A reduced play counter cannot identify
which plays in an observed batch were wrong: batches above the corrected ceiling
are excluded, not assigned invented dates. Raw snapshots are never modified.
"""
from dataclasses import replace
from .constants import MANUAL_SOURCES
from .helpers import build_song_map, parse_datetime, safe_int

FIELDS = ('stage_cnt', 'high_score', 'clear_cnt', 'full_combo_cnt',
          'dondaful_combo_cnt', 'best_score_rank', 'pound_cnt', 'good_cnt',
          'ok_cnt', 'ng_cnt', 'combo_cnt', 'option_flg')
FLAGS = {'clear_cnt': 'clearUnlocked', 'full_combo_cnt': 'fullComboUnlocked',
         'dondaful_combo_cnt': 'dondafulUnlocked'}


def reconcile_manual_corrections(events, selection, history):
    corrections = {}
    previous = {}
    post_window = []
    selected_end = selection.window_snapshots[-1].observed_at
    for snapshot in history.snapshots:
        current = build_song_map(snapshot.state)
        if snapshot.source in MANUAL_SOURCES:
            for key in snapshot.changed_keys:
                before, after = previous.get(key), current.get(key)
                if before is None:
                    continue
                if after is None:
                    corrections.setdefault(key, []).append((snapshot.observed_at, {f: 0 for f in FIELDS if f != 'option_flg'}))
                    if snapshot.observed_at > selected_end:
                        post_window.append((key, None))
                    continue
                changed = {f: after.get(f) for f in FIELDS if before.get(f) != after.get(f)}
                lowered = {f: safe_int(after.get(f)) for f in FIELDS
                           if f != 'option_flg' and safe_int(after.get(f)) < safe_int(before.get(f))}
                if lowered:
                    corrections.setdefault(key, []).append((snapshot.observed_at, lowered))
                if changed and snapshot.observed_at > selected_end:
                    post_window.append((key, changed))
        previous = current
    result, removed, corrected = [], 0, 0
    for event in events:
        moment = parse_datetime((event.get('observedBetween') or {}).get('to'))
        limits = {}
        for at, fields in corrections.get((event.get('songNo'), event.get('level')), []):
            if moment and moment < at:
                for field, value in fields.items():
                    limits[field] = min(limits.get(field, value), value)
        after = event.get('after') or {}
        if (event.get('type') == 'high_score' and 'high_score' in limits
                and safe_int(after.get('high_score')) > limits['high_score']):
            removed += 1
            continue
        if (event.get('type') == 'play_delta' and 'stage_cnt' in limits
                and safe_int(after.get('stage_cnt')) > limits['stage_cnt']):
            removed += 1
            continue
        if event.get('type') == 'play_delta':
            delta = dict(event.get('delta') or {})
            warnings = list(event.get('warnings') or [])
            for field, flag in FLAGS.items():
                if limits.get(field) == 0 and delta.get(flag):
                    delta[flag] = False
                    warnings.append('manual_correction_invalidates:' + field)
            if limits.get('best_score_rank', 8) < 8:
                warnings.append('manual_correction_invalidates:best_score_rank')
            if warnings != (event.get('warnings') or []):
                event = {**event, 'delta': delta, 'warnings': sorted(set(warnings))}
                corrected += 1
        result.append(event)
    # Corrections submitted after the reporting window may correct its records,
    # but never import post-window plays or create a new chart in that window.
    state = selection.end_state
    if post_window:
        songs = build_song_map(state)
        for key, fields in post_window:
            if fields is None:
                songs.pop(key, None)
            elif key in songs:
                fields = dict(fields)
                if 'stage_cnt' in fields:
                    fields['stage_cnt'] = min(safe_int(fields['stage_cnt']), safe_int(songs[key].get('stage_cnt')))
                songs[key] = {**songs[key], **fields}
        state = {**state, 'songs': list(songs.values())}
    warnings = []
    if removed or corrected or post_window:
        warnings = [f'manual_corrections_reconciled:removed={removed},flags={corrected},post_window={len(post_window)}']
    return result, replace(selection, end_state=state), warnings
