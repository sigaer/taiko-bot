"""Single-player, latest-version chart identity shared by catalog consumers."""
from __future__ import annotations

import re
from .tja_roll_parser import _expand_branches

COURSES = ('easy', 'normal', 'hard', 'oni', 'edit')
ALIASES = {**{name: i for i, name in enumerate(COURSES, 1)},
           **{str(i): i + 1 for i in range(5)}, 'ura': 5}


def is_double_song(song):
    return any(str(song.get(key, '')).startswith('【双打】') for key in ('song_name', 'song_name_jp'))


def normalize_courses(text):
    """The pinned calculator does not normalize numeric Easy/Normal headers."""
    def replace(match):
        value = match.group(2).strip().lower()
        index = ALIASES.get(value)
        return match.group(1) + (COURSES[index - 1].title() if index else match.group(2))
    return re.sub(r'(?im)^(\s*COURSE\s*:\s*)([^\r\n/]+)', replace, text)


def single_profiles(text):
    """Count judgeable notes on M only; #START P1/P2 never become singles."""
    course, level, style = 4, None, 'single'
    lines, active, result = [], False, {}
    bpm, balloons = '120', ''
    for raw in text.splitlines():
        line = raw.split('//', 1)[0].strip()
        upper = line.upper()
        if upper.startswith('#START'):
            active = upper == '#START' and style in ('single', '1')
            lines = []
        elif upper == '#END':
            if active and course and level:
                branched, paths = _expand_branches(lines)
                notes = sum(sum(c in '1234' for c in row) for row in paths['M']
                            if re.fullmatch(r'[0-9A-Za-z,\s]+', row))
                profile = {'level': level, 'notes': notes, 'branch': 'master' if branched else 'unbranched',
                           'text': f'BPM:{bpm}\nCOURSE:{COURSES[course-1]}\nBALLOON:{balloons}\n#START\n' + '\n'.join(lines) + '\n#END\n'}
                if course in result:
                    raise ValueError('Ambiguous duplicate single course')
                result[course] = profile
            active = False
        elif active:
            lines.append(line)
        elif ':' in line:
            key, value = line.split(':', 1)
            key, value = key.strip().lower(), value.strip().lower()
            if key == 'course':
                course, level, style = ALIASES.get(value), None, 'single'
                balloons = ''
            elif key == 'bpm':
                bpm = value
            elif key == 'balloon':
                balloons = value
            elif key == 'level':
                try: level = int(value)
                except ValueError: level = None
            elif key == 'style':
                style = value
    return result


def version_rank(path):
    """Explicit arcade revisions, never filesystem mtimes or download order."""
    name = path.stem.casefold()
    if 'nijiiro' in name or 'nijiro' in name:
        return (16, 0)
    matches = re.findall(r'(?<![a-z])ac\s*(\d+)(?:[. _-](\d+))?', name)
    return max(((int(major), int(minor or 0)) for major, minor in matches), default=(0, 0))


def canonical_single_text(song, text):
    """Use latest star reassessments only after matching the exact note count.

    This view is for derived constants/images, never writes over source TJAs.
    """
    blocks = []
    for index, chart in single_profiles(text).items():
        level = song.get(f'level_{index}')
        notes = (song.get('max_combo') or [None]*5)[index-1]
        if type(level) is not int or type(notes) is not int or notes != chart['notes']:
            continue
        blocks.append(chart['text'].replace(f'COURSE:{COURSES[index-1]}\n',
                                             f'COURSE:{COURSES[index-1]}\nLEVEL:{level}\n'))
    return '\n'.join(blocks)
