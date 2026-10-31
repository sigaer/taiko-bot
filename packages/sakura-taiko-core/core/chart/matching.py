from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
import unicodedata
from ..parser.chart_analysis import TjaFileData, estimate_section_note_count, index_record_bpms, parse_bpm_number

COURSE_TO_LEVEL_FIELD = {'Easy': 'level_1', 'Normal': 'level_2', 'Hard': 'level_3', 'Oni': 'level_4', 'Edit': 'level_5'}
COURSE_TO_COMBO_INDEX = {'Easy': 0, 'Normal': 1, 'Hard': 2, 'Oni': 3, 'Edit': 4}
VARIANT_HINT_PATTERN = re.compile('(old|new|cover|original|audio|chart|version|ver\\.|anime matsuri|beena|ac\\d+|old audio|new audio)', flags=re.IGNORECASE)
COLLAB_MARKER_PATTERN = re.compile('(nijisanji|focus on|vα-liv|idolm@ster|765pro|im@s|valiv)', flags=re.IGNORECASE)
TRAILING_PAREN_PATTERN = re.compile('\\s*[\\(\\[（【].*?[\\)\\]】）]\\s*$')
TRAILING_VERSION_PATTERN = re.compile('\\s*[-–—~～]\\s*(?:old|new|cover|original|.*version.*|.*chart.*|.*audio.*)\\s*$', flags=re.IGNORECASE)
MANUAL_PATH_OVERRIDES = {2: '01 Pop/Tentai Kansoku/Tentai Kansoku -New Audio-.tja', 79: '06 Classical/Orpheus in the Underworld Overture/Orpheus in the Underworld Overture.tja', 92: '06 Classical/Pavane for a Dead Princess/Pavane for a Dead Princess.tja', 124: '09 Namco Original/Dream Tide/Dream Tide.tja', 135: '02 Anime/A Cruel Angel’s Thesis/A Cruel Angels Thesis -New Audio-.tja', 219: '09 Namco Original/Total Eclipse 2035/Total Eclipse 2035.tja', 303: '01 Pop/Natsu Matsuri/Natsu Matsuri -New Audio-.tja', 321: '07 Game Music/Knuckle Heads/Knuckle Heads.tja', 390: '09 Namco Original/SORA-II Gliese 581/SORA-II Gliese 581.tja', 391: '09 Namco Original/SORA-VI Hinotori/SORA-VI Hinotori.tja', 385: '01 Pop/Sakuranbo/Sakuranbo -New Audio-.tja', 417: '05 Variety/Grip & Break down !! -Tatsujin Edit.-/Grip & Break down !! Tatsujin Edit.tja', 496: '09 Namco Original/Scarlet Heart/Scarlet Heart.tja', 539: '09 Namco Original/Scream out! -Tatsujin Edit.-/Scream out! Tatsujin Edit.tja', 623: '07 Game Music/Battle -Clash of Prowess-/Battle Clash of Prowess.tja', 624: '07 Game Music/Good-bye my earth/Good-bye my earth.tja', 725: '02 Anime/Rei -ZERO-/Rei -ZERO-.tja', 831: '02 Anime/Gegege no Kitaro (Sixth Season)/Gegege no Kitaro.tja', 888: '06 Classical/Classical Medley (Rock Arrange)/Classical Medley (Rock Arrange).tja', 900: '09 Namco Original/Twin Strike/Double Play Twin Strike.tja', 811: '01 Pop/Anata to Tu-lat-tat-ta♪/Anata to Tu-lat-tat-ta -Original Version-.tja', 937: '01 Pop/Yoru ni Kakeru/Yoru ni Kakeru -Original Version-.tja', 956: '01 Pop/Dakara Boku wa Ongaku wo Yameta/Dakara Boku wa Ongaku wo Yameta -Original Version-.tja', 1130: '09 Namco Original/SORA-IV Bunpasong/SORA-IV Bunpasong.tja', 1226: '03 Vocaloid/Haikei, Gakkou ni te.../Haikei, Gakkou ni te....tja', 1290: '04 Children and Folk/Ba Luo Buo/Ba Luo Buo.tja', 1331: '01 Pop/Miss You 3000/Miss You 3000.tja', 1345: '06 Classical/Turkish March (Mozart)/Turkish March.tja', 1358: '01 Pop/Bansanka/Bansanka.tja'}

@dataclass
class CandidateSummary:
    path: str
    rel_path: str
    meta: Dict[str, str]
    course_levels: Dict[str, str]
    note_counts: Dict[str, int]
    bpm_value: Optional[float]
    exact_aliases: Set[str]
    normalized_aliases: Set[str]
    base_normalized_titles: Set[str]
    variant_penalty: int
    clean_base_bonus: int

def normalize_text(value: str) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).strip().lower()
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    text = re.sub('\\s+', '', text)
    text = re.sub('[‐‑‒–—―－]', '-', text)
    text = re.sub('[~〜～]', '-', text)
    text = re.sub('[・･]', '', text)
    text = re.sub('[!！?？。、，,./\\\\\'\\";:：`´·•※\\[\\]{}<>《》「」『』【】（）()]', '', text)
    text = text.replace('&', '').replace('＆', '')
    return text

def strip_variant_suffix(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    prev = None
    while prev != text:
        prev = text
        text = TRAILING_PAREN_PATTERN.sub('', text).strip()
        text = TRAILING_VERSION_PATTERN.sub('', text).strip()
    return text

def clean_subtitle(value: str) -> str:
    text = str(value or '').strip()
    text = re.sub('^-+', '', text).strip()
    return text

def parse_song_bpm_range(raw_bpm: object) -> Tuple[Optional[float], Optional[float]]:
    nums = re.findall('\\d+(?:\\.\\d+)?', str(raw_bpm or ''))
    if not nums:
        return (None, None)
    values = [float(v) for v in nums]
    return (min(values), max(values))

def build_song_keys(song: Dict[str, object]) -> Tuple[Set[str], Set[str], Set[str]]:
    exact: Set[str] = set()
    normalized: Set[str] = set()
    base_normalized: Set[str] = set()
    subtitle = clean_subtitle(str(song.get('subtitle') or ''))
    values = [str(song.get('song_name_jp') or '').strip(), str(song.get('song_name') or '').strip()]
    for value in values:
        if not value:
            continue
        exact.add(value)
        normalized.add(normalize_text(value))
        base_normalized.add(normalize_text(strip_variant_suffix(value)))
        if subtitle:
            combined = f'{value}{subtitle}'
            exact.add(combined)
            normalized.add(normalize_text(combined))
            base_normalized.add(normalize_text(strip_variant_suffix(combined)))
    for value in list(values):
        if not value:
            continue
        stripped = strip_variant_suffix(value)
        if stripped and stripped != value:
            exact.add(stripped)
            normalized.add(normalize_text(stripped))
            base_normalized.add(normalize_text(stripped))
    return (exact, {item for item in normalized if item}, {item for item in base_normalized if item})

def build_candidate_summary(path, rel_path, tja_data) -> CandidateSummary:
    meta = tja_data.meta
    title_ja = str(meta.get('title_ja') or '').strip()
    title_raw = str(meta.get('title') or '').strip()
    subtitle_ja = clean_subtitle(meta.get('subtitle_ja', ''))
    subtitle = clean_subtitle(meta.get('subtitle', ''))
    course_levels: Dict[str, str] = {}
    note_counts: Dict[str, int] = {}
    for section in tja_data.sections:
        if not section.course:
            continue
        course_levels[section.course] = str(section.level)
        note_counts[section.course] = estimate_section_note_count(section)
    alias_texts: Set[str] = set()
    for title in (title_ja, title_raw):
        if title:
            alias_texts.add(title)
    for title in (title_ja, title_raw):
        for sub in (subtitle_ja, subtitle):
            if title and sub:
                alias_texts.add(f'{title}{sub}')
    base_titles = {strip_variant_suffix(title) for title in (title_ja, title_raw) if strip_variant_suffix(title)}
    alias_texts |= base_titles
    variant_penalty = count_variant_penalty(' '.join([rel_path, title_ja, title_raw, subtitle_ja, subtitle]))
    clean_base_bonus = 1 if any((bt and bt in {title_ja, title_raw} for bt in base_titles)) else 0
    return CandidateSummary(path=path, rel_path=rel_path, meta=meta, course_levels=course_levels, note_counts=note_counts, bpm_value=parse_bpm_number(meta.get('bpm', '')), exact_aliases=alias_texts, normalized_aliases={normalize_text(item) for item in alias_texts if item}, base_normalized_titles={normalize_text(item) for item in base_titles if item}, variant_penalty=variant_penalty, clean_base_bonus=clean_base_bonus)

def count_variant_penalty(text: str) -> int:
    return len(VARIANT_HINT_PATTERN.findall(text or ''))

def extract_ascii_tokens(value: str) -> Set[str]:
    return {token.lower() for token in re.findall('[A-Za-z0-9@]{3,}', str(value or '')) if len(token) >= 3}

def build_candidate_indexes(candidates: Sequence[CandidateSummary]) -> Tuple[Dict[str, Set[int]], Dict[str, Set[int]], Dict[str, Set[int]]]:
    exact_map: Dict[str, Set[int]] = {}
    normalized_map: Dict[str, Set[int]] = {}
    base_map: Dict[str, Set[int]] = {}
    for idx, candidate in enumerate(candidates):
        for key in candidate.exact_aliases:
            exact_map.setdefault(key, set()).add(idx)
        for key in candidate.normalized_aliases:
            normalized_map.setdefault(key, set()).add(idx)
        for key in candidate.base_normalized_titles:
            base_map.setdefault(key, set()).add(idx)
    return (exact_map, normalized_map, base_map)

def collect_song_course_levels(song: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for course, field in COURSE_TO_LEVEL_FIELD.items():
        value = song.get(field)
        if value in (None, '', '-'):
            continue
        out[course] = str(value)
    return out

def collect_song_course_combos(song: Dict[str, object]) -> Dict[str, int]:
    combos = song.get('max_combo')
    if not isinstance(combos, list):
        return {}
    out: Dict[str, int] = {}
    for course, index in COURSE_TO_COMBO_INDEX.items():
        if index >= len(combos):
            continue
        value = combos[index]
        if isinstance(value, int):
            out[course] = value
            continue
        if isinstance(value, str) and value.isdigit():
            out[course] = int(value)
    return out

def choose_candidate_pool(song: Dict[str, object], candidates: Sequence[CandidateSummary], exact_map: Dict[str, Set[int]], normalized_map: Dict[str, Set[int]], base_map: Dict[str, Set[int]]) -> Set[int]:
    song_exact, song_norm, song_base = build_song_keys(song)
    pool: Set[int] = set()
    for key in song_exact:
        pool |= exact_map.get(key, set())
    for key in song_norm:
        pool |= normalized_map.get(key, set())
    for key in song_base:
        pool |= base_map.get(key, set())
    if pool:
        return pool
    for idx, candidate in enumerate(candidates):
        if any((key and cand_key and (key in cand_key or cand_key in key) for key in song_base for cand_key in candidate.base_normalized_titles)):
            pool.add(idx)
            continue
        if any((key and cand_key and (key in cand_key or cand_key in key) for key in song_norm for cand_key in candidate.normalized_aliases)):
            pool.add(idx)
    return pool

def score_candidate(song: Dict[str, object], candidate: CandidateSummary) -> Tuple[Tuple[int, int, int, int, int], List[str]]:
    song_exact, song_norm, song_base = build_song_keys(song)
    song_levels = collect_song_course_levels(song)
    song_combos = collect_song_course_combos(song)
    song_subtitle = clean_subtitle(str(song.get('subtitle') or ''))
    song_bpm_lo, song_bpm_hi = parse_song_bpm_range(song.get('bpm'))
    score = 0
    title_hits = 0
    level_hits = 0
    combo_hits = 0
    reasons: List[str] = []
    candidate_title_ja = str(candidate.meta.get('title_ja') or '')
    candidate_title = str(candidate.meta.get('title') or '')
    candidate_subtitle_ja = clean_subtitle(candidate.meta.get('subtitle_ja', ''))
    candidate_subtitle = clean_subtitle(candidate.meta.get('subtitle', ''))
    song_jp = str(song.get('song_name_jp') or '').strip()
    song_name = str(song.get('song_name') or '').strip()
    if song_jp and song_jp == candidate_title_ja:
        score += 260
        title_hits += 5
        reasons.append('song_name_jp=TITLEJA')
    if song_jp and song_jp == candidate_title:
        score += 220
        title_hits += 4
        reasons.append('song_name_jp=TITLE')
    if song_name and song_name == candidate_title:
        score += 180
        title_hits += 4
        reasons.append('song_name=TITLE')
    if song_name and song_name == candidate_title_ja:
        score += 140
        title_hits += 3
        reasons.append('song_name=TITLEJA')
    norm_title_ja = normalize_text(candidate_title_ja)
    norm_title = normalize_text(candidate_title)
    if song_jp and normalize_text(song_jp) == norm_title_ja:
        score += 210
        title_hits += 4
        reasons.append('song_name_jp~=TITLEJA')
    if song_jp and normalize_text(song_jp) == norm_title:
        score += 170
        title_hits += 3
        reasons.append('song_name_jp~=TITLE')
    if song_name and normalize_text(song_name) == norm_title:
        score += 140
        title_hits += 3
        reasons.append('song_name~=TITLE')
    if any((key in candidate.exact_aliases for key in song_exact)):
        score += 130
        title_hits += 2
        reasons.append('alias exact')
    if any((key in candidate.normalized_aliases for key in song_norm)):
        score += 110
        title_hits += 2
        reasons.append('alias normalized')
    if any((key in candidate.base_normalized_titles for key in song_base)):
        score += 95
        title_hits += 2
        reasons.append('base title')
    if any((key and alias and (key in alias or alias in key) for key in song_base for alias in candidate.base_normalized_titles)):
        score += 35
        title_hits += 1
        reasons.append('base substring')
    if song_subtitle and song_subtitle in {candidate_subtitle_ja, candidate_subtitle}:
        score += 30
        reasons.append('subtitle exact')
    elif song_subtitle and normalize_text(song_subtitle) in {normalize_text(candidate_subtitle_ja), normalize_text(candidate_subtitle)}:
        score += 20
        reasons.append('subtitle normalized')
    song_ascii_tokens = extract_ascii_tokens(song_subtitle)
    candidate_ascii_text = ' '.join([candidate.rel_path, candidate_subtitle_ja, candidate_subtitle, candidate_title_ja, candidate_title]).lower()
    subtitle_token_hits = sum((1 for token in song_ascii_tokens if token in candidate_ascii_text))
    if subtitle_token_hits:
        score += subtitle_token_hits * 18
        reasons.append(f'subtitle token x{subtitle_token_hits}')
    elif song_ascii_tokens:
        score -= 20
    has_collab_marker = bool(COLLAB_MARKER_PATTERN.search(candidate_ascii_text))
    if song_ascii_tokens and has_collab_marker:
        score += 25
        reasons.append('collab marker')
    elif not song_ascii_tokens and has_collab_marker:
        score -= 35
        reasons.append('unexpected collab marker')
    for course, song_level in song_levels.items():
        candidate_level = candidate.course_levels.get(course)
        if candidate_level is None:
            score -= 24
            continue
        if str(candidate_level) == str(song_level):
            score += 18
            level_hits += 1
        else:
            score -= 16
    if 'Edit' not in song_levels and 'Edit' in candidate.course_levels:
        score -= 30
        reasons.append('unexpected edit')
    for course, combo in song_combos.items():
        candidate_count = candidate.note_counts.get(course)
        if candidate_count is None:
            score -= 10
            continue
        diff = abs(candidate_count - combo)
        if diff == 0:
            score += 24
            combo_hits += 1
        elif diff <= 1:
            score += 18
            combo_hits += 1
        elif diff <= 3:
            score += 12
        elif diff <= 8:
            score += 6
        else:
            score -= min(18, diff // 10 + 3)
    if candidate.bpm_value is not None and song_bpm_lo is not None and (song_bpm_hi is not None):
        if song_bpm_lo - 0.5 <= candidate.bpm_value <= song_bpm_hi + 0.5:
            score += 25
            reasons.append('bpm in range')
        elif min(abs(candidate.bpm_value - song_bpm_lo), abs(candidate.bpm_value - song_bpm_hi)) <= 5:
            score += 10
            reasons.append('bpm near range')
        else:
            score -= 12
    if candidate.clean_base_bonus:
        score += 8
    if candidate.variant_penalty:
        score -= candidate.variant_penalty * 12
    rank = (score, title_hits, level_hits, combo_hits, -candidate.variant_penalty)
    return (rank, reasons)

def select_candidate(song: Dict[str, object], candidates: Sequence[CandidateSummary], exact_map: Dict[str, Set[int]], normalized_map: Dict[str, Set[int]], base_map: Dict[str, Set[int]], *, override_path=None) -> Tuple[Optional[CandidateSummary], Dict[str, object]]:
    song_id = int(song.get('id', 0))
    if override_path:
        candidate = next((item for item in candidates if item.path == override_path), None)
        if candidate is not None:
            return (candidate, {'reason': 'manual_override', 'path': candidate.rel_path})
    pool = choose_candidate_pool(song, candidates, exact_map, normalized_map, base_map)
    if not pool:
        return (None, {'reason': 'no_candidate'})
    scored: List[Tuple[Tuple[int, int, int, int, int], CandidateSummary, List[str]]] = []
    for idx in pool:
        candidate = candidates[idx]
        rank, reasons = score_candidate(song, candidate)
        scored.append((rank, candidate, reasons))
    scored.sort(key=lambda item: (item[0][0], item[0][1], item[0][2], item[0][3], item[0][4], item[1].clean_base_bonus, -len(item[1].rel_path)), reverse=True)
    top_rank, top_candidate, top_reasons = scored[0]
    top_candidates = [item for item in scored if item[0] == top_rank]
    if len(top_candidates) > 1:
        clean_best = [item for item in top_candidates if item[1].clean_base_bonus]
        if len(clean_best) == 1:
            chosen = clean_best[0]
            return (chosen[1], {'reason': 'auto_clean_base', 'score': chosen[0][0], 'path': chosen[1].rel_path, 'why': chosen[2]})
        return (None, {'reason': 'score_tie', 'candidates': [{'path': item[1].rel_path, 'score': item[0][0], 'why': item[2]} for item in top_candidates[:8]]})
    if top_rank[1] <= 0:
        return (None, {'reason': 'no_title_match', 'candidates': [{'path': item[1].rel_path, 'score': item[0][0], 'why': item[2]} for item in scored[:5]]})
    return (top_candidate, {'reason': 'auto', 'score': top_rank[0], 'path': top_candidate.rel_path, 'why': top_reasons})

def build_song_records(song: Dict[str, object], analysis_records) -> Tuple[Optional[List[Dict[str, object]]], Optional[Dict[str, object]]]:
    expected_levels = collect_song_course_levels(song)
    expected_combos = collect_song_course_combos(song)
    by_course: Dict[str, List[Dict[str, object]]] = {}
    for record in analysis_records:
        by_course.setdefault(str(record.get('course') or ''), []).append(record)
    final_records: List[Dict[str, object]] = []
    fallback_single_course = len(by_course) == 1 and (not expected_combos)
    for course, level in expected_levels.items():
        course_records = list(by_course.get(course, []))
        source_course = course
        if not course_records and course == 'Edit' and ('Oni' in by_course) and ('Oni' not in expected_levels):
            course_records = list(by_course['Oni'])
            source_course = 'Oni'
        elif not course_records and course == 'Oni' and ('Edit' in by_course) and ('Edit' not in expected_levels):
            course_records = list(by_course['Edit'])
            source_course = 'Edit'
        elif not course_records and fallback_single_course:
            source_course = next(iter(by_course))
            course_records = list(by_course[source_course])
        if len(course_records) > 1:
            exact_level_records = [record for record in course_records if str(record.get('level')) == str(level)]
            if len(exact_level_records) == 1:
                course_records = exact_level_records
        if len(course_records) != 1:
            return (None, {'reason': 'course_mismatch', 'course': course, 'level': level, 'available': [{'course': record.get('course'), 'level': record.get('level')} for record in analysis_records]})
        record = dict(course_records[0])
        record['source_course'] = source_course
        record['course'] = course
        record['level'] = str(level)
        record['title'] = str(song.get('song_name_jp') or song.get('song_name') or record['title'])
        final_records.append(record)
    return (final_records, None)

def build_filtered_index(records: Iterable[Tuple[Dict[str, object], List[Dict[str, object]]]]) -> Dict[str, object]:
    records = list(records)
    by_bpm: Dict[str, Set[str]] = {}
    by_level: Dict[str, Set[str]] = {}
    by_tag: Dict[str, Set[str]] = {}
    song_meta: Dict[str, Dict[str, object]] = {}
    title_counts: Dict[str, int] = {}
    for song, _ in records:
        title = str(song.get('song_name_jp') or song.get('song_name') or '')
        title_counts[title] = title_counts.get(title, 0) + 1

    def song_key_for(song: Dict[str, object]) -> str:
        title = str(song.get('song_name_jp') or song.get('song_name') or '')
        if title_counts.get(title, 0) <= 1:
            return title
        return f"{title}@@{song.get('id')}"
    for song, chart_records in records:
        song_key = song_key_for(song)
        title = str(song.get('song_name_jp') or song.get('song_name') or '')
        song_meta[song_key] = song
        for record in chart_records:
            item_id = f"{song_key}||{record['course']}"
            index_record_bpms(by_bpm, item_id, record)
            by_level.setdefault(str(record.get('level') or ''), set()).add(item_id)
            for tag in record.get('tags', []):
                by_tag.setdefault(str(tag), set()).add(item_id)
    return {'by_bpm': {key: sorted(value) for key, value in sorted(by_bpm.items(), key=lambda item: int(item[0]))}, 'by_level': {key: sorted(value) for key, value in sorted(by_level.items(), key=lambda item: int(item[0]))}, 'by_tag': {key: sorted(value) for key, value in sorted(by_tag.items())}, 'song_meta': song_meta}
