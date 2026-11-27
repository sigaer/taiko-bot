"""Reconcile single charts independently of V2 constant calculation.

Wiki describes the current release. A verified local newer arcade revision is
preferred over an old mapping; unresolved conflicts are reported, never guessed.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import re

from .catalog_chart_policy import is_double_song, single_profiles, version_rank
from .catalog_downloads import catalog_resource_root
from .catalog_resources import safe_resource
from .ourtaiko_catalog import positive_id, title_key
from .tja_roll_parser import read_tja_text, parse_tja_roll_metadata


def wiki_index(database):
    return {str(row['songNo']): row for row in database if row.get('songNo') is not None}


def catalog_changes(before, after):
    old = {song['id']:song for song in before}
    fields = ('tja_path','audio_path','max_combo',*(f'level_{i}' for i in range(1,6)))
    changes = []
    for song in after:
        previous = old.get(song['id'], {})
        if is_double_song(song): continue
        changed = {key:{'before':previous.get(key),'after':song.get(key)}
                   for key in fields if previous.get(key) != song.get(key)}
        if changed: changes.append({'id':song['id'], 'fields':changed})
    return changes


def reconcile_charts(songs, *, database, root, ese_root, mapping):
    wiki = wiki_index(database)
    cache, titles = {}, defaultdict(list)
    def profile(path):
        if path not in cache:
            text = read_tja_text(str(path))
            cache[path] = (single_profiles(text), text)
        return cache[path]
    for path in sorted(ese_root.rglob('*.tja')):
        try:
            profiles, text = profile(path)
            if profiles:
                for title in set(re.findall(r'^TITLE(?:JA|EN|ZH)?\s*:(.*)$', text, re.M | re.I)):
                    titles[title_key(title)].append(path)
        except (ValueError, UnicodeError):
            continue
    report = {'changed': [], 'issues': [], 'excludedDoubleSongs': 0}
    for song in songs:
        if is_double_song(song):
            report['excludedDoubleSongs'] += 1
            continue
        for i in range(1, 6):
            if not positive_id(song.get(f'level_{i}')):
                song[f'level_{i}'] = '-'
        sid = int(song['id'])
        db = wiki.get(str(sid)) if sid < 100000 else None
        if db is None:
            records = [wiki[k] for k in song.get('wiki_song_nos', []) if k in wiki]
            if len(records) == 1: db = records[0]
        courses = (db or {}).get('courses') or {}
        expected = {i: (positive_id(courses[k].get('level')), courses[k].get('maxCombo'))
                    for i,k in enumerate(('easy','normal','hard','oni','ura'), 1)
                    if isinstance(courses.get(k), dict) and positive_id(courses[k].get('level'))}
        source_root = catalog_resource_root(song, ese_root, runtime_root=root)
        current = safe_resource(source_root, song.get('tja_path'))
        mapped = safe_resource(ese_root, mapping.get(sid) or mapping.get(str(sid)))
        if not expected and not current and not mapped:
            expected = {i:(positive_id(song.get(f'level_{i}')), (song.get('max_combo') or [None]*5)[i-1])
                        for i in range(1,6) if positive_id(song.get(f'level_{i}'))}
        candidates = set(filter(None, (current, mapped)))
        # Never cross into a different arrangement just because its title is similar.
        for key in ('song_name_jp','song_name'):
            candidates.update(titles.get(title_key(song.get(key)), []))
        for path in (current, mapped):
            if path and path.is_relative_to(ese_root.resolve()):
                candidates.update(path.parent.glob('*.tja'))
        def compatible(path):
            try:
                profiles, _ = profile(path)
                return bool(profiles) and all(i in profiles
                    and (profiles[i]['branch'] == 'master' or not valid_count(notes) or profiles[i]['notes'] == notes)
                    for i,(level,notes) in expected.items())
            except (ValueError, UnicodeError): return False
        # With no Wiki identity, only the already resolved source is authoritative.
        verified = [p for p in candidates if expected and compatible(p)]
        path = max(verified, key=lambda p:(version_rank(p), p == current, p == mapped, str(p))) if verified else current or mapped
        if path is None:
            report['issues'].append({'id':sid, 'reason':'tja_unavailable'})
            continue
        try: profiles, text = profile(path)
        except (ValueError, UnicodeError) as error:
            report['issues'].append({'id':sid, 'reason':'invalid_tja', 'detail':str(error)})
            continue
        before = {key:song.get(key) for key in ('tja_path','audio_path','max_combo',*(f'level_{i}' for i in range(1,6)))}
        if path.is_relative_to(ese_root.resolve()):
            song['tja_path'] = path.relative_to(ese_root.resolve()).as_posix()
            for key in ('resource_source','tja_sha256','audio_sha256'): song.pop(key, None)
            mapping[sid] = song['tja_path']
            wave = re.search(r'^\s*WAVE\s*:(.+)$', text, re.M | re.I)
            audio = safe_resource(ese_root, str(path.parent.relative_to(ese_root.resolve()) / wave.group(1).strip())) if wave else None
            if audio: song['audio_path'] = audio.relative_to(ese_root.resolve()).as_posix()
        combos = list(song.get('max_combo') or [])[:5]
        combos += ['-'] * (5-len(combos))
        for i, chart in profiles.items():
            if i not in range(1,6): continue
            level, notes = expected.get(i, (None,None))
            if level and chart['branch'] != 'master' and valid_count(notes) and notes != chart['notes']:
                report['issues'].append({'id':sid,'difficulty':i,'reason':'latest_wiki_tja_conflict',
                    'wikiLevel':level,'wikiNotes':notes,'tjaLevel':chart['level'],'tjaNotes':chart['notes']})
                continue
            # Difficulty ratings can change without changing a single note.
            # Keep the current Wiki rating when the course's notes agree.
            song[f'level_{i}'] = level or chart['level']
            combos[i-1] = chart['notes']
            key = ('easy','normal','hard','oni','ura')[i-1]
            parsed = parse_tja_roll_metadata(chart['text'], branch='M').get(key)
            if parsed and not parsed.get('warnings') and not parsed.get('balloon_warning'):
                values = {'roll_times':parsed.get('roll_times', []), 'balloons':parsed.get('balloons', [])}
                values.update(roll_time=round(sum(values['roll_times']), 6), balloon_num=sum(values['balloons']))
                for field,value in values.items():
                    items = list(song.get(field) or [])[:5]
                    items += [None]*(5-len(items))
                    items[i-1] = value
                    song[field] = items
            else:
                report['issues'].append({'id':sid, 'difficulty':i, 'reason':'roll_parser_warning'})
        song['max_combo'] = combos
        from .chart_roll_metadata import apply_chart_roll_metadata_overrides
        apply_chart_roll_metadata_overrides(song)
        for i in range(1,6):
            if positive_id(song.get(f'level_{i}')) and i not in profiles:
                report['issues'].append({'id':sid,'difficulty':i,'reason':'single_course_unavailable'})
        changed = {k:{'before':v,'after':song.get(k)} for k,v in before.items() if v != song.get(k)}
        if changed: report['changed'].append({'id':sid,'fields':changed})
    return report


def valid_count(value):
    return type(value) is int and value > 0
