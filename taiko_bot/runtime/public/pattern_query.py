"""Original public chart parsing and sampling semantics."""
import re, random
from typing import Any, Dict, List, Optional, Set, Tuple

_CHART_CONFIG_BPM_RE = re.compile(r"^\d+(?:-\d+)?$")

_CHART_CONFIG_PATTERN_RE = re.compile(r"^[ox]+$", re.IGNORECASE)

_CHART_CONFIG_LEVEL_RE = re.compile(r"^[鬼松竹梅]\d+$")

def _parse_chart_config_query(command_text: str) -> Optional[Dict[str, str]]:
    args_text = re.sub(r"^/?查配置\s*", "", command_text).strip()
    if not args_text:
        return None

    tokens = args_text.split()
    if len(tokens) == 1 and _CHART_CONFIG_BPM_RE.fullmatch(tokens[0]):
        return {"mode": "bpm_only", "bpm_str": tokens[0]}
    if (
        len(tokens) == 2
        and any(_CHART_CONFIG_BPM_RE.fullmatch(token) for token in tokens)
        and any(_CHART_CONFIG_LEVEL_RE.fullmatch(token) for token in tokens)
    ):
        return {
            "mode": "bpm_level_only",
            "bpm_str": next(
                token for token in tokens if _CHART_CONFIG_BPM_RE.fullmatch(token)
            ),
            "level": next(
                token for token in tokens if _CHART_CONFIG_LEVEL_RE.fullmatch(token)
            ),
        }

    division = "16"
    token_index = 0
    if (
        len(tokens) >= 2
        and _CHART_CONFIG_BPM_RE.fullmatch(tokens[0])
        and _CHART_CONFIG_PATTERN_RE.fullmatch(tokens[1])
    ):
        division = tokens[0]
        token_index = 1

    if token_index >= len(tokens):
        return None

    pattern_name = tokens[token_index].lower()
    if not _CHART_CONFIG_PATTERN_RE.fullmatch(pattern_name):
        return None

    bpm_str = None
    level = None
    remain_tokens = tokens[token_index + 1 :]
    if remain_tokens:
        first = remain_tokens.pop(0)
        if _CHART_CONFIG_BPM_RE.fullmatch(first):
            bpm_str = first
            if remain_tokens:
                second = remain_tokens.pop(0)
                if not _CHART_CONFIG_LEVEL_RE.fullmatch(second):
                    return None
                level = second
        elif _CHART_CONFIG_LEVEL_RE.fullmatch(first):
            level = first
        else:
            return None

    if remain_tokens:
        return None

    return {
        "mode": "pattern",
        "division": division,
        "pattern_name": pattern_name,
        "bpm_str": bpm_str,
        "level": level,
    }

def _parse_chart_config_bpm_range(
    bpm_str: Optional[str],
) -> Optional[Tuple[int, int]]:
    if not bpm_str:
        return None
    if "-" in bpm_str:
        lo, hi = map(int, bpm_str.split("-", 1))
        return (min(lo, hi), max(lo, hi))

    bpm = int(bpm_str)
    return (bpm, bpm)

def _collect_chart_config_bpm_ids(
    by_bpm: Dict[str, List[str]], bpm_range: Optional[Tuple[int, int]]
) -> Set[str]:
    if not bpm_range:
        return set()

    bpm_ids = set()
    for bpm in range(bpm_range[0], bpm_range[1] + 1):
        ids = by_bpm.get(str(bpm))
        if ids:
            bpm_ids.update(ids)
    return bpm_ids

def _collect_chart_config_level_ids(
    by_level: Dict[str, List[str]], level: Optional[str], level_map: Dict[str, str]
) -> Set[str]:
    if not level:
        return set()

    level_number = level[1:]
    level_rank = level[0]
    target_diff = by_level.get(str(level_number), [])

    if level_rank == "鬼":
        return set(filter(lambda x: x[-3:] in ["dit", "Oni"], target_diff))

    suffix = level_map.get(level_rank, "")
    return set(filter(lambda x: x[-3:] == suffix, target_diff))

def _resolve_chart_config_song_name(song_meta: Dict[str, Any], title: str) -> str:
    meta = song_meta.get(title, {})
    return meta.get("song_name") or meta.get("song_name_jp") or title

def _sample_chart_config_items(items: List[str], limit: int = 10) -> List[str]:
    if len(items) > limit:
        return random.sample(items, limit)
    return items
