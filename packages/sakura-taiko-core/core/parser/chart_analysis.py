from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

COURSE_NAME_MAP = {'0': 'Easy', 'easy': 'Easy', 'kantan': 'Easy', '1': 'Normal', 'normal': 'Normal', 'futsuu': 'Normal', 'futsu': 'Normal', '2': 'Hard', 'hard': 'Hard', 'muzukashii': 'Hard', 'muzukashi': 'Hard', '3': 'Oni', 'oni': 'Oni', '4': 'Edit', 'edit': 'Edit', 'ura': 'Edit', 'inneroni': 'Edit'}
COMBO_PATTERNS = ['oooxxx', 'xxxooo', 'oooxxxooo', 'xxxoooxxx', 'oooxxxoooxxx', 'xxxoooxxxooo']

@dataclass
class Bar:
    measure_a: int
    measure_b: int
    raw_digits: str

@dataclass
class ChartSection:
    course: str
    level: str
    bars: List[Bar]
    bpms: List[int] = field(default_factory=list)

@dataclass
class TjaFileData:
    path: str
    meta: Dict[str, str]
    sections: List[ChartSection]

def parse_tja_multi(text: str) -> Tuple[Dict[str, str], List[ChartSection]]:
    """
    解析一首 tja（多难度）。
    - #MEASURE 的 a/b 作用到后续小节，直到遇到新的 #MEASURE
    - 多行数字（逗号前）拼接为一个小节 raw_digits
    """
    meta_all: Dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.upper() == '#START':
            break
        if ':' in s:
            k, v = s.split(':', 1)
            meta_all[k.strip().upper()] = v.strip()
        i += 1
    meta = {'title': meta_all.get('TITLE', ''), 'title_ja': meta_all.get('TITLEJA', ''), 'subtitle': _clean_subtitle(meta_all.get('SUBTITLE', '')), 'subtitle_ja': _clean_subtitle(meta_all.get('SUBTITLEJA', '')), 'bpm': meta_all.get('BPM', ''), 'wave': meta_all.get('WAVE', '')}
    sections: List[ChartSection] = []
    current_course = ''
    current_level = ''
    current_measure = '4/4'
    capturing = False
    acc = ''
    acc_measure = current_measure
    header_bpm = bpm_to_index_value(meta.get('bpm', ''))
    section_bpms: Set[int] = set()

    def parse_measure_str(ms: str) -> Tuple[int, int]:
        try:
            a_str, b_str = ms.split('/')
            a, b = (int(a_str), int(b_str))
            if b == 0:
                b = 4
            return (a, b)
        except Exception:
            return (4, 4)

    def find_or_create_section(course: str, level: str) -> ChartSection:
        for section in sections:
            if section.course == course and section.level == level:
                return section
        section = ChartSection(course=course, level=level, bars=[])
        sections.append(section)
        return section

    def sync_section_bpms() -> None:
        if not current_course or not section_bpms:
            return
        section = find_or_create_section(current_course, current_level)
        merged = set(section.bpms)
        merged.update(section_bpms)
        section.bpms = sorted(merged)

    def reset_section_bpms() -> None:
        nonlocal section_bpms
        section_bpms = set()
        if header_bpm is not None:
            section_bpms.add(header_bpm)

    def submit() -> None:
        nonlocal acc, acc_measure
        if not acc:
            return
        a, b = parse_measure_str(acc_measure)
        section = find_or_create_section(current_course, current_level)
        section.bars.append(Bar(a, b, acc))
        acc = ''
        acc_measure = current_measure
    for raw in lines:
        t = raw.strip()
        if not t:
            continue
        if ':' in t and (not t.startswith('#')):
            k, v = t.split(':', 1)
            ku, vv = (k.strip().upper(), v.strip())
            if ku == 'COURSE':
                current_course = normalize_course_name(vv)
            elif ku == 'LEVEL':
                current_level = vv
        if t.upper().startswith('#MEASURE'):
            parts = t.split()
            if len(parts) >= 2:
                current_measure = parts[1].strip()
            continue
        if t.upper().startswith('#START'):
            capturing = True
            acc = ''
            acc_measure = current_measure
            reset_section_bpms()
            sync_section_bpms()
            continue
        if t.upper().startswith('#END'):
            sync_section_bpms()
            capturing = False
            acc = ''
            continue
        if t.upper().startswith('#BPMCHANGE'):
            parts = t.split()
            if len(parts) >= 2:
                changed = bpm_to_index_value(parts[1])
                if changed is not None:
                    section_bpms.add(changed)
                    sync_section_bpms()
            continue
        if capturing:
            m = re.fullmatch('(\\d+),?', t)
            if m:
                acc += m.group(1)
                if t.endswith(','):
                    submit()
    return (meta, sections)

def sample_bar_by_basegrid(raw_digits: str, a: int, b: int, n_div: int) -> List[str]:
    """
    返回小节在 n_div（12/16/24）下的严格采样 token 列表（o/x/-）。
    采样条件不满足时返回 ['-'] 作为断点。
    """
    digits_len = len(raw_digits)
    if a == 0:
        return ['-']
    base_grid = int(round(digits_len * b / a))
    if base_grid % n_div != 0:
        return ['-']
    grid_block_len = base_grid // n_div
    num = a * n_div
    if num % b != 0:
        return ['-']
    tokens = num // b
    if tokens == 0 or digits_len % tokens != 0:
        return ['-']
    block_len = digits_len // tokens
    if block_len != grid_block_len:
        return ['-']
    o_block = '1' + '0' * (block_len - 1)
    x_block = '2' + '0' * (block_len - 1)
    zero_block = '0' * block_len
    out: List[str] = []
    for i in range(0, digits_len, block_len):
        block = raw_digits[i:i + block_len]
        if block == x_block:
            out.append('x')
        elif block == o_block:
            out.append('o')
        elif block == zero_block:
            out.append('-')
        else:
            out.append('-')
    return out

def build_stream_dynamic_strict(bars: List[Bar], n_div: int) -> List[str]:
    stream: List[str] = []
    for bar in bars:
        stream.extend(sample_bar_by_basegrid(bar.raw_digits, bar.measure_a, bar.measure_b, n_div))
    return stream

def extract_runs(tokens: List[str]) -> List[Tuple[int, int, str]]:
    runs: List[Tuple[int, int, str]] = []
    start = None
    for i, token in enumerate(tokens + ['-']):
        if token != '-' and start is None:
            start = i
        elif token == '-' and start is not None:
            runs.append((start, i - 1, ''.join(tokens[start:i])))
            start = None
    return runs

def count_runs_by_length(tokens: List[str], allowed_lengths: Iterable[int]) -> Dict[str, int]:
    allowed = set(allowed_lengths)
    counts: Dict[str, int] = {}
    for _, _, text in extract_runs(tokens):
        if len(text) in allowed:
            counts[text] = counts.get(text, 0) + 1
    return counts

def count_all_runs(tokens: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for _, _, text in extract_runs(tokens):
        counts[text] = counts.get(text, 0) + 1
    return counts

def count_combo_patterns(tokens: List[str], patterns: List[str]) -> Dict[str, int]:
    wanted = set(patterns)
    counts = {pattern: 0 for pattern in patterns}
    for _, _, text in extract_runs(tokens):
        if text in wanted:
            counts[text] += 1
    return counts

def compute_tags(result: Dict) -> List[str]:
    tags_set: Set[str] = set()
    counts = result.get('counts', {})
    runs = counts.get('runs', {})
    patterns = counts.get('patterns', {})
    runs24_all = runs.get('24_all', {}) or {}
    for pattern, cnt in runs24_all.items():
        if cnt >= 1:
            tags_set.add(f'24 {pattern}')
    runs16_selected = runs.get('16_selected', {}) or {}
    for pattern, cnt in runs16_selected.items():
        length = len(pattern)
        if length in (4, 5) and cnt >= 5:
            tags_set.add(f'16 {pattern}')
        if length in (2, 3) and cnt >= 8:
            tags_set.add(f'16 {pattern}')
    runs16_all = runs.get('16_all', {}) or {}
    for pattern, cnt in runs16_all.items():
        if len(pattern) >= 6 and cnt >= 1:
            tags_set.add(f'16 {pattern}')
    runs12_all = runs.get('12_all', {}) or {}
    for pattern, cnt in runs12_all.items():
        if len(pattern) >= 6 and cnt >= 1:
            tags_set.add(f'12 {pattern}')
    for div in ('12', '16', '24'):
        pmap = patterns.get(div, {}) or {}
        for pattern in COMBO_PATTERNS:
            if pmap.get(pattern, 0) >= 2:
                tags_set.add(f'{div} {pattern}')
    return sorted(tags_set)

def parse_bpm_number(raw_bpm: str) -> Optional[float]:
    if raw_bpm is None:
        return None
    match = re.search('\\d+(?:\\.\\d+)?', str(raw_bpm))
    if not match:
        return None
    try:
        return float(match.group())
    except Exception:
        return None

def bpm_to_index_value(raw_bpm: object) -> Optional[int]:
    value = parse_bpm_number(str(raw_bpm))
    if value is None:
        return None
    return int(round(value))

def collect_record_bpms(meta: Dict[str, str], section: ChartSection) -> List[int]:
    values: Set[int] = set(section.bpms)
    header = bpm_to_index_value(meta.get('bpm', ''))
    if header is not None:
        values.add(header)
    if not values:
        return []
    return sorted(values)

def index_record_bpms(by_bpm: Dict[str, Set[str]], item_id: str, record: Dict) -> None:
    bpms = record.get('bpms') or []
    if not bpms:
        primary = record.get('bpm')
        if isinstance(primary, int):
            bpms = [primary]
    for bpm in bpms:
        if isinstance(bpm, int):
            by_bpm.setdefault(str(bpm), set()).add(item_id)

def estimate_section_note_count(section: ChartSection) -> int:
    total = 0
    for bar in section.bars:
        total += sum((ch in '1234' for ch in bar.raw_digits))
    return total

def analyze_section(meta: Dict[str, str], section: ChartSection) -> Dict:
    bpm_raw = meta.get('bpm', '')
    bpm_value = parse_bpm_number(bpm_raw)
    if bpm_value is None:
        bpm_export: object = bpm_raw
    else:
        bpm_export = int(round(bpm_value))
    stream12 = build_stream_dynamic_strict(section.bars, 12)
    stream16 = build_stream_dynamic_strict(section.bars, 16)
    stream24 = build_stream_dynamic_strict(section.bars, 24)
    run_counts_12_all = count_all_runs(stream12)
    run_counts_16_all = count_all_runs(stream16)
    run_counts_16_sel = count_runs_by_length(stream16, [2, 3, 4, 5])
    run_counts_24_all = count_all_runs(stream24)
    pattern_counts = {'12': count_combo_patterns(stream12, COMBO_PATTERNS), '16': count_combo_patterns(stream16, COMBO_PATTERNS), '24': count_combo_patterns(stream24, COMBO_PATTERNS)}
    display_title = meta.get('title_ja') or meta.get('title') or ''
    section_bpms = collect_record_bpms(meta, section)
    result = {'title': display_title, 'title_ja': meta.get('title_ja', ''), 'title_raw': meta.get('title', ''), 'subtitle': meta.get('subtitle', ''), 'subtitle_ja': meta.get('subtitle_ja', ''), 'bpm': bpm_export, 'bpms': section_bpms, 'bpm_raw': bpm_raw, 'course': section.course, 'level': section.level, 'note_count': estimate_section_note_count(section), 'counts': {'runs': {'12_all': run_counts_12_all, '16_all': run_counts_16_all, '16_selected': run_counts_16_sel, '24_all': run_counts_24_all}, 'patterns': pattern_counts}}
    result['tags'] = compute_tags(result)
    return result

def sanitize_filename(name: str) -> str:
    return re.sub('[\\\\/:*?"<>|]+', '_', name)

def build_inverted_index_from_records(records: List[Dict]) -> Dict:
    by_bpm: Dict[str, Set[str]] = {}
    by_level: Dict[str, Set[str]] = {}
    by_tag: Dict[str, Set[str]] = {}
    catalog: Dict[str, Dict[str, object]] = {}
    for record in records:
        item_id = f"{record.get('title', '')}||{record.get('course', '')}"
        title = record.get('title', '')
        course = record.get('course', '')
        level = str(record.get('level', ''))
        bpm = record.get('bpm')
        catalog[item_id] = {'title': title, 'course': course, 'level': level, 'bpm': bpm, 'bpms': record.get('bpms', [])}
        index_record_bpms(by_bpm, item_id, record)
        by_level.setdefault(level, set()).add(item_id)
        for tag in record.get('tags', []):
            by_tag.setdefault(tag, set()).add(item_id)
    return {'by_bpm': {key: sorted(value) for key, value in sorted(by_bpm.items(), key=lambda item: int(item[0]))}, 'by_level': {str(k): sorted(v) for k, v in by_level.items()}, 'by_tag': {k: sorted(v) for k, v in by_tag.items()}, 'catalog': catalog}

def _ids_by_bpm_range(idx: Dict, lo: int, hi: int) -> Set[str]:
    out: Set[str] = set()
    for bpm in range(lo, hi + 1):
        out |= set(idx['by_bpm'].get(str(bpm), []))
    return out

def _clean_subtitle(value: str) -> str:
    text = str(value or '').strip()
    text = re.sub('^-+', '', text).strip()
    return text

def normalize_course_name(value: str) -> str:
    raw = str(value or '').strip()
    normalized = re.sub('\\s+', '', raw).lower()
    return COURSE_NAME_MAP.get(normalized, raw)
