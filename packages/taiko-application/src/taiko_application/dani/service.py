"""Dani request parsing, target allocation and presentation model. No host IO."""

from __future__ import annotations

import io
import math
import re
from typing import Any, Dict, List, Optional, Tuple
from contextlib import redirect_stdout
from functools import lru_cache
from sakura_taiko_core.score.dojo import build_dojo_score_map, level_mark_to_icon
from .models import DaniInputs, DaniProgress, DaniSection
from .common import (
    FORMULA_GOOD,
    FORMULA_OK,
    GRADE_ALIASES,
    _NUMERIC_DAN_ALIASES,
    _NUMERIC_KYU_ALIASES,
    CURRENT_DANI_VERSION,
    DOJO_DATA_VERSION,
    SUPPORTED_DANI_VERSIONS,
    DANI_VERSION_PREFIXES,
    DANI_VERSION_PATTERN,
    NIJIIRO_2026_GOLD_SOUL_GAUGE_BY_GRADE,
    NIJIIRO_2026_DAN_GRADES,
    DANI_DYNAMIC_PROFILE_MIN_RATED_SONGS,
    DANI_DYNAMIC_PRESSURE_CLAMP,
    DANI_DYNAMIC_ROLE_WEIGHT,
    DANI_DYNAMIC_ABSOLUTE_WEIGHT,
    DANI_DYNAMIC_CONST_WEIGHT,
    DANI_DYNAMIC_CONST_MIN_FACTOR,
    DANI_DYNAMIC_RATE_LOAD_LIMIT,
    DANI_DYNAMIC_RATE_LOAD_WEIGHTS,
    DANI_DYNAMIC_RATE_LOAD_COST_POWER,
    DANI_DYNAMIC_ACCURACY_OVER_TOLERANCE,
    DANI_DYNAMIC_ACCURACY_OVER_WEIGHT,
    DANI_DYNAMIC_REFERENCE_DISTANCE_SCALE,
    DANI_DYNAMIC_PRESSURE_TIGHTEN_COST_SCALE,
    DANI_DYNAMIC_PRESSURE_LOOSEN_COST_SCALE,
    DANI_DYNAMIC_LOOSEN_PRESSURE_WEIGHT,
    DANI_DYNAMIC_LOOSEN_WEIGHT_MIN,
    DANI_DYNAMIC_LOOSEN_WEIGHT_MAX,
    DANI_DYNAMIC_MIN_LOOSEN_SHARE_FACTOR,
    DANI_DYNAMIC_SOFT_MIN_OK_LIMIT,
    DANI_DYNAMIC_NEAR_FULL_COST_SCALE,
    DANI_DYNAMIC_DIMENSION_SPECS,
    STRUCTURE_ROLE_DIMENSION_SPECS,
    LEVEL_STAR_FIELD,
    _difficulty_level,
    _normalize_song_title,
    _safe_float,
    _safe_int,
    _safe_optional_int,
)

_CACHE_MISS = object()


class DaniProgressService:
    """One instance per request; caches never retain another player's records."""

    def requires_roll_catalog(self, grade: dict) -> bool:
        """Acquire roll metadata only where the existing allocator needs it.

        Per-song targets (including 2025 六段) must not trigger the host's
        scoreline cache refresh just because the renderer has been extracted.
        """
        conditions = [
            grade["conditions"]["pass"],
            self._resolved_gold_conditions(grade),
        ]
        return any(
            not isinstance(row.get("drumrollCountAtLeast"), list)
            and _safe_int(row.get("drumrollCountAtLeast"), 0) > 0
            for row in conditions
        )

    def __init__(self, inputs: DaniInputs):
        self.inputs = inputs
        self._summary_cache = {}
        self._rate_cache = {}
        # Only these finite catalog indexes are memoized for the request lifetime.
        self._load_grade_payload = lru_cache(maxsize=8)(self._load_grade_payload)
        self._load_song_roll_meta_index = lru_cache(maxsize=8)(
            self._load_song_roll_meta_index
        )
        self._load_dani_dynamic_score_context = lru_cache(maxsize=8)(
            self._load_dani_dynamic_score_context
        )
        self._load_grade_index = lru_cache(maxsize=8)(self._load_grade_index)
        self._load_dani_dynamic_song_title_level_index = lru_cache(maxsize=8)(
            self._load_dani_dynamic_song_title_level_index
        )
        self._load_song_note_map = lru_cache(maxsize=8)(self._load_song_note_map)
        self._load_song_title_level_index = lru_cache(maxsize=8)(
            self._load_song_title_level_index
        )
        self._load_song_chart_meta_index = lru_cache(maxsize=8)(
            self._load_song_chart_meta_index
        )

    def _grade_alias_variants(self, canonical: str) -> set[str]:
        variants = {canonical}
        changed = True
        while changed:
            changed = False
            for item in list(variants):
                for left, right in GRADE_ALIASES:
                    if left in item:
                        nxt = item.replace(left, right)
                        if nxt not in variants:
                            variants.add(nxt)
                            changed = True
        return variants

    def _normalize_numeric_grade_input(self, text: str) -> str:
        raw = str(text).strip()
        if not raw:
            return raw
        dan_match = re.fullmatch("(\\d+)段", raw)
        if dan_match:
            num = int(dan_match.group(1))
            return _NUMERIC_DAN_ALIASES.get(num, raw)
        kyu_match = re.fullmatch("(\\d+)[级級]", raw)
        if kyu_match:
            num = int(kyu_match.group(1))
            return _NUMERIC_KYU_ALIASES.get(num, raw)
        return raw

    def _load_grade_payload(self, version: str) -> dict:
        return self.inputs.grade_payloads[str(version or CURRENT_DANI_VERSION)]

    def _load_grade_index(
        self, version: str = CURRENT_DANI_VERSION
    ) -> Dict[str, Dict[str, Any]]:
        payload = self._load_grade_payload(version)
        index: Dict[str, Dict[str, Any]] = {}
        for grade in payload["grades"]:
            grade = {**grade, "sourceYear": str(payload.get("year") or version)}
            canonical = str(grade["grade"]).strip()
            for item in self._grade_alias_variants(canonical):
                index[item] = grade
        return index

    def _grade_name(self, grade: Dict[str, Any]) -> str:
        return str(grade.get("grade") or grade.get("slug") or "").strip()

    def _grade_source_year(self, grade: Dict[str, Any]) -> str:
        if grade.get("sourceYear"):
            return str(grade["sourceYear"])
        source_url = str(grade.get("sourceUrl") or "")
        match = re.search("ニジイロ(20\\d{2})", source_url)
        return match.group(1) if match else "2025"

    def _resolved_gold_conditions(self, grade: Dict[str, Any]) -> Dict[str, Any]:
        pass_cond = dict((grade.get("conditions") or {}).get("pass") or {})
        gold_cond = dict((grade.get("conditions") or {}).get("gold") or {})
        if self._grade_source_year(grade) != "2026":
            return gold_cond
        grade_name = self._grade_name(grade)
        known_gold_gauge = NIJIIRO_2026_GOLD_SOUL_GAUGE_BY_GRADE.get(grade_name)
        if known_gold_gauge is not None:
            gold_cond.setdefault("soulGaugePercent", known_gold_gauge)
        elif grade_name in NIJIIRO_2026_DAN_GRADES:
            gold_cond.setdefault("soulGaugePercent", 100)
        pass_bad = pass_cond.get("badCountLessThan")
        if (
            gold_cond.get("badCountLessThan") is None
            and isinstance(pass_bad, int)
            and (pass_bad > 0)
        ):
            gold_cond["badCountLessThan"] = pass_bad // 2
        return gold_cond

    def parse_dani_progress_request(self, text: str) -> Optional[Dict[str, str]]:
        raw = str(text).strip()
        if raw.endswith("进度"):
            raw = raw[:-2]
        raw = raw.strip()
        if not raw:
            return None
        version = CURRENT_DANI_VERSION
        explicit_version = False
        has_prefix = False
        for prefix in DANI_VERSION_PREFIXES:
            if raw.startswith(prefix):
                raw = raw[len(prefix) :].strip()
                has_prefix = True
                break
        match = DANI_VERSION_PATTERN.match(raw)
        if match:
            version = "20" + match.group(1)
            raw = match.group(2).strip()
            explicit_version = True
        elif has_prefix:
            return None
        if version not in SUPPORTED_DANI_VERSIONS:
            return None
        raw = self._normalize_numeric_grade_input("初段" if raw == "一段" else raw)
        grade = self._load_grade_index(version).get(raw)
        if not grade:
            return None
        return {
            "version": version,
            "grade": str(grade["grade"]),
            "explicitVersion": "1" if explicit_version else "0",
        }

    def normalize_dani_grade_name(self, text: str) -> Optional[str]:
        request = self.parse_dani_progress_request(text)
        return request["grade"] if request else None

    def _footer_uses_ok_count(self, grade: Dict[str, Any]) -> bool:
        pass_cond = (grade or {}).get("conditions", {}).get("pass", {})
        return pass_cond.get("okCountLessThan") is not None

    def _load_song_note_map(self) -> Dict[Tuple[int, int], int]:
        payload = self.inputs.song_catalog
        mapping: Dict[Tuple[int, int], int] = {}
        for song in payload:
            sid = _safe_int(song.get("id"), -1)
            combos = song.get("max_combo") or []
            if sid < 0 or not isinstance(combos, list):
                continue
            for level, value in enumerate(combos, start=1):
                if value in (None, "-"):
                    continue
                try:
                    mapping[sid, level] = int(value)
                except Exception:
                    continue
        return mapping

    def _load_song_title_level_index(
        self,
    ) -> Dict[Tuple[str, int], List[Dict[str, Optional[int]]]]:
        payload = self.inputs.song_catalog
        mapping: Dict[Tuple[str, int], List[Dict[str, Optional[int]]]] = {}
        for song in payload:
            song_id = _safe_int(song.get("id"), -1)
            if song_id <= 0:
                continue
            titles = {
                _normalize_song_title(song.get("song_name_jp")),
                _normalize_song_title(song.get("song_name")),
            }
            combos = (
                song.get("max_combo") if isinstance(song.get("max_combo"), list) else []
            )
            for level in range(1, 6):
                if song.get(f"level_{level}") in (None, "", "-"):
                    continue
                note_count = None
                if level - 1 < len(combos):
                    note_count = _safe_optional_int(combos[level - 1])
                candidate = {"id": song_id, "noteCount": note_count}
                for title in titles:
                    if not title:
                        continue
                    mapping.setdefault((title, level), []).append(candidate)
        return mapping

    def _load_song_chart_meta_index(
        self,
    ) -> Tuple[
        Dict[Tuple[int, int], Dict[str, Any]],
        Dict[Tuple[str, int], List[Dict[str, Any]]],
    ]:
        payload = self.inputs.song_catalog
        by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
        by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for song in payload:
            song_id = _safe_int(song.get("id"), -1)
            if song_id <= 0:
                continue
            titles = {
                _normalize_song_title(song.get("song_name_jp")),
                _normalize_song_title(song.get("song_name")),
            }
            combos = (
                song.get("max_combo") if isinstance(song.get("max_combo"), list) else []
            )
            for level in range(1, 6):
                star_raw = song.get(LEVEL_STAR_FIELD[level])
                if star_raw in (None, "", "-"):
                    continue
                note_count = None
                if level - 1 < len(combos):
                    note_count = _safe_optional_int(combos[level - 1])
                candidate = {
                    "id": song_id,
                    "noteCount": note_count,
                    "star": str(star_raw),
                }
                by_id[song_id, level] = candidate
                for title in titles:
                    if not title:
                        continue
                    by_title.setdefault((title, level), []).append(candidate)
        return (by_id, by_title)

    def _resolve_song_star(self, song: Dict[str, Any]) -> str:
        level = _difficulty_level(song.get("difficulty"))
        song_id = _safe_int(song.get("id"), -1)
        by_id, by_title = self._load_song_chart_meta_index()
        if song_id > 0:
            exact_meta = by_id.get((song_id, level))
            if exact_meta is not None:
                return str(exact_meta.get("star") or "-")
        title = _normalize_song_title(song.get("title"))
        if not title:
            return "-"
        candidates = list(by_title.get((title, level), []))
        if not candidates:
            return "-"
        note_count = _safe_int(song.get("noteCount"), 0)
        if note_count > 0:
            note_matches = [
                item
                for item in candidates
                if _safe_int(item.get("noteCount"), -1) == note_count
            ]
            if note_matches:
                candidates = note_matches
        if len(candidates) == 1:
            return str(candidates[0].get("star") or "-")
        matched_ids = {
            candidate_id
            for candidate_id in (_safe_int(item.get("id"), -1) for item in candidates)
            if candidate_id > 0
        }
        if len(matched_ids) == 1 and candidates:
            return str(candidates[0].get("star") or "-")
        return "-"

    def _load_song_roll_meta_index(
        self,
    ) -> Tuple[
        Dict[Tuple[int, int], Dict[str, Any]],
        Dict[Tuple[str, int], List[Dict[str, Any]]],
    ]:
        payload = self.inputs.roll_catalog
        by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
        by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for row in payload:
            level = _safe_int(row.get("level"), 0)
            if level <= 0:
                continue
            meta = {
                "id": _safe_optional_int(row.get("id")),
                "noteCount": _safe_optional_int(row.get("max_combo")),
                "rollTotalSeconds": max(
                    0.0, _safe_float(row.get("roll_total_seconds"), 0.0)
                ),
                "balloonHits": max(0, _safe_int(row.get("balloon_hits"), 0)),
            }
            song_id = meta["id"]
            if isinstance(song_id, int) and song_id > 0:
                by_id[song_id, level] = meta
            titles = {
                _normalize_song_title(row.get("title")),
                _normalize_song_title(row.get("title_jp")),
                _normalize_song_title(row.get("title_cn")),
            }
            for title in titles:
                if not title:
                    continue
                by_title.setdefault((title, level), []).append(meta)
        return (by_id, by_title)

    def _resolve_song_roll_meta(self, song: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        level = _difficulty_level(song.get("difficulty"))
        song_id = _safe_int(song.get("id"), -1)
        by_id, by_title = self._load_song_roll_meta_index()
        if song_id > 0:
            exact_meta = by_id.get((song_id, level))
            if exact_meta is not None:
                return exact_meta
        title = _normalize_song_title(song.get("title"))
        if not title:
            return None
        candidates = list(by_title.get((title, level), []))
        if not candidates:
            return None
        note_count = _safe_int(song.get("noteCount"), 0)
        if note_count > 0:
            note_matches = [
                item
                for item in candidates
                if _safe_int(item.get("noteCount"), -1) == note_count
            ]
            if note_matches:
                candidates = note_matches
        if len(candidates) == 1:
            return candidates[0]
        matched_ids = {
            candidate_id
            for candidate_id in (_safe_int(item.get("id"), -1) for item in candidates)
            if candidate_id > 0
        }
        if len(matched_ids) == 1 and candidates:
            return candidates[0]
        return None

    def _note_count(self, song: Dict[str, Any]) -> int:
        note_count = _safe_int(song.get("noteCount"), 0)
        if note_count > 0:
            return note_count
        return self._load_song_note_map().get(
            (_safe_int(song.get("id")), _difficulty_level(song.get("difficulty"))), 0
        )

    def _accuracy_formula(self, song: Dict[str, Any]) -> str:
        formula = str(song.get("accuracyFormula") or "").strip()
        if formula in {FORMULA_GOOD, FORMULA_OK}:
            return formula
        return FORMULA_GOOD

    def _build_best_entry_map(
        self, user_scores: List[Dict[str, Any]]
    ) -> Dict[Tuple[int, int], Dict[str, Any]]:
        best: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for row in user_scores:
            try:
                key = (int(row["song_no"]), int(row["level"]))
                score = int(row.get("high_score", 0) or 0)
            except Exception:
                continue
            if key not in best or score > int(best[key].get("high_score", 0) or 0):
                best[key] = row
        return best

    def _entry_accuracy_for_song(
        self, song: Dict[str, Any], entry: Dict[str, Any]
    ) -> float:
        counts = self._entry_counts(entry)
        return self._accuracy_percent(
            counts, self._note_count(song), self._accuracy_formula(song)
        )

    def _pick_best_song_entry(
        self, song: Dict[str, Any], entries: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not entries:
            return None

        def _sort_key(entry: Dict[str, Any]) -> Tuple[float, int, int, int]:
            return (
                self._entry_accuracy_for_song(song, entry),
                _safe_int(entry.get("high_score"), 0),
                _safe_int(entry.get("good_cnt"), 0),
                -_safe_int(entry.get("song_no", entry.get("id")), 0),
            )

        return max(entries, key=_sort_key)

    def _resolve_song_entry(
        self, song: Dict[str, Any], best_map: Dict[Tuple[int, int], Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        level = _difficulty_level(song.get("difficulty"))
        song_id = _safe_int(song.get("id"), -1)
        matched_entries: List[Dict[str, Any]] = []
        matched_keys: set[Tuple[int, int]] = set()
        if song_id > 0:
            exact_entry = best_map.get((song_id, level))
            if exact_entry is not None:
                key = (
                    _safe_int(exact_entry.get("song_no", exact_entry.get("id")), 0),
                    _safe_int(exact_entry.get("level"), level),
                )
                matched_keys.add(key)
                matched_entries.append(exact_entry)
        title = _normalize_song_title(song.get("title"))
        if not title:
            return self._pick_best_song_entry(song, matched_entries)
        candidates = list(self._load_song_title_level_index().get((title, level), []))
        if candidates:
            note_count = _safe_int(song.get("noteCount"), 0)
            if note_count > 0:
                note_matches = [
                    item
                    for item in candidates
                    if _safe_int(item.get("noteCount"), -1) == note_count
                ]
                if note_matches:
                    candidates = note_matches
            for candidate in candidates:
                candidate_id = _safe_int(candidate.get("id"), -1)
                if candidate_id <= 0:
                    continue
                entry = best_map.get((candidate_id, level))
                if entry is None:
                    continue
                key = (
                    _safe_int(entry.get("song_no", entry.get("id")), 0),
                    _safe_int(entry.get("level"), level),
                )
                if key in matched_keys:
                    continue
                matched_keys.add(key)
                matched_entries.append(entry)
        return self._pick_best_song_entry(song, matched_entries)

    def _entry_counts(self, entry: Optional[Dict[str, Any]]) -> Dict[str, int]:
        if not entry:
            return {"score": 0, "good": 0, "ok": 0, "bad": 0, "drumroll": 0, "hit": 0}
        hit_value = _safe_optional_int(entry.get("hit_cnt"))
        if hit_value is None:
            hit_value = (
                _safe_int(entry.get("good_cnt"), 0)
                + _safe_int(entry.get("ok_cnt"), 0)
                + _safe_int(entry.get("pound_cnt"), 0)
            )
        return {
            "score": _safe_int(entry.get("high_score"), 0),
            "good": _safe_int(entry.get("good_cnt"), 0),
            "ok": _safe_int(entry.get("ok_cnt"), 0),
            "bad": _safe_int(entry.get("ng_cnt", entry.get("bad_cnt")), 0),
            "drumroll": _safe_int(entry.get("pound_cnt"), 0),
            "hit": hit_value,
        }

    def _accuracy_percent(
        self, counts: Dict[str, int], note_count: int, formula: str
    ) -> float:
        if note_count <= 0:
            return 0.0
        if (
            counts.get("score", 0) <= 0
            and counts.get("good", 0) <= 0
            and (counts.get("ok", 0) <= 0)
            and (counts.get("bad", 0) <= 0)
            and (counts.get("drumroll", 0) <= 0)
        ):
            return 0.0
        value = (counts["good"] + counts["ok"] * 0.5) / float(note_count)
        return max(0.0, min(100.0, value * 100.0))

    def _all_good(self, counts: Dict[str, int], note_count: int) -> bool:
        return counts["ok"] == 0 and counts["bad"] == 0

    def _full_combo(self, counts: Dict[str, int]) -> bool:
        return counts["bad"] == 0

    def _rate_from_good_target(self, note_count: int, good_target: int) -> float:
        if note_count <= 0:
            return 0.0
        clamped_good = max(0, min(note_count, good_target))
        value = (
            (clamped_good + 0.5 * (note_count - clamped_good))
            / float(note_count)
            * 100.0
        )
        return max(0.0, min(100.0, value))

    def _rate_from_ok_limit(self, note_count: int, ok_limit: int) -> float:
        if note_count <= 0:
            return 0.0
        max_ok = max(0, ok_limit - 1)
        value = (note_count - 0.5 * max_ok) / float(note_count) * 100.0
        return max(0.0, min(100.0, value))

    def _rate_target_list(
        self,
        note_counts: List[int],
        cond: Dict[str, Any],
        *,
        good_targets: Optional[List[int]] = None,
        ok_limits: Optional[List[int]] = None,
    ) -> List[float]:
        if cond.get("goodCountAtLeast") is not None:
            targets = good_targets or self._scalar_or_list(
                cond.get("goodCountAtLeast"), note_counts
            )
            return [
                self._rate_from_good_target(note_count, good_target)
                for note_count, good_target in zip(note_counts, targets)
            ]
        if cond.get("okCountLessThan") is not None:
            limits = ok_limits or self._scalar_or_list(
                cond.get("okCountLessThan"), note_counts
            )
            return [
                self._rate_from_ok_limit(note_count, ok_limit)
                for note_count, ok_limit in zip(note_counts, limits)
            ]
        gauge = float(_safe_int(cond.get("soulGaugePercent"), 0))
        return [gauge for _ in note_counts]

    def _rate_target_total(
        self, note_count: int, cond: Dict[str, Any], song_notes: List[int]
    ) -> float:
        if note_count <= 0:
            return 0.0
        bad_raw = cond.get("badCountLessThan")
        if isinstance(bad_raw, list):
            total_bad = sum((max(0, _safe_int(item) - 1) for item in bad_raw))
        else:
            total_bad = max(0, _safe_int(bad_raw) - 1)
        if cond.get("goodCountAtLeast") is not None:
            raw = cond.get("goodCountAtLeast")
            total_good = (
                sum(self._scalar_or_list(raw, song_notes))
                if isinstance(raw, list)
                else _safe_int(raw)
            )
            total_ok = max(0, note_count - total_good - total_bad)
            value = (total_good + 0.5 * total_ok) / float(note_count) * 100.0
            return max(0.0, min(100.0, value))
        if cond.get("okCountLessThan") is not None:
            raw = cond.get("okCountLessThan")
            if isinstance(raw, list):
                total_ok = sum((max(0, _safe_int(item) - 1) for item in raw))
            else:
                total_ok = max(0, _safe_int(raw) - 1)
            total_good = max(0, note_count - total_ok - total_bad)
            value = (total_good + 0.5 * total_ok) / float(note_count) * 100.0
            return max(0.0, min(100.0, value))
        return float(_safe_int(cond.get("soulGaugePercent"), 0))

    def _allocate_proportional(self, total: int, weights: List[int]) -> List[int]:
        if total <= 0 or not weights or sum(weights) <= 0:
            return [0 for _ in weights]
        raw = [total * weight / float(sum(weights)) for weight in weights]
        ints = [int(math.floor(item)) for item in raw]
        remain = total - sum(ints)
        order = sorted(
            range(len(weights)), key=lambda idx: raw[idx] - ints[idx], reverse=True
        )
        for idx in order[:remain]:
            ints[idx] += 1
        return ints

    def _allocate_proportional_float(
        self, total: int, weights: List[float]
    ) -> List[int]:
        normalized = [max(0.0, _safe_float(weight, 0.0)) for weight in weights]
        total_weight = sum(normalized)
        if total <= 0 or not normalized or total_weight <= 0:
            return [0 for _ in normalized]
        raw = [total * weight / total_weight for weight in normalized]
        ints = [int(math.floor(item)) for item in raw]
        remain = total - sum(ints)
        order = sorted(
            range(len(normalized)),
            key=lambda idx: (raw[idx] - ints[idx], normalized[idx]),
            reverse=True,
        )
        for idx in order[:remain]:
            ints[idx] += 1
        return ints

    def _scalar_or_list(self, value: Any, weights: List[int]) -> List[int]:
        if isinstance(value, list):
            numbers = [_safe_int(item, 0) for item in value]
            if len(numbers) < len(weights):
                numbers.extend([0] * (len(weights) - len(numbers)))
            return numbers[: len(weights)]
        return self._allocate_proportional(_safe_int(value, 0), weights)

    def _scalar_or_drumroll_list(
        self, value: Any, songs: List[Dict[str, Any]], note_weights: List[int]
    ) -> List[int]:
        if isinstance(value, list):
            return self._scalar_or_list(value, note_weights)
        total = _safe_int(value, 0)
        if total <= 0:
            return [0 for _ in songs]
        roll_seconds: List[float] = []
        balloon_hits: List[int] = []
        for song in songs:
            meta = self._resolve_song_roll_meta(song) or {}
            roll_seconds.append(
                max(0.0, _safe_float(meta.get("rollTotalSeconds"), 0.0))
            )
            balloon_hits.append(max(0, _safe_int(meta.get("balloonHits"), 0)))
        balloon_total = sum(balloon_hits)
        if balloon_total >= total:
            return self._allocate_proportional(
                total, balloon_hits if balloon_total > 0 else note_weights
            )
        non_balloon_total = total - balloon_total
        roll_targets = self._allocate_proportional_float(
            non_balloon_total, roll_seconds
        )
        if sum(roll_targets) < non_balloon_total:
            roll_targets = self._allocate_proportional(non_balloon_total, note_weights)
        return [
            roll_target + balloon_hit
            for roll_target, balloon_hit in zip(roll_targets, balloon_hits)
        ]

    def _top20_weighted_average(self, values: List[float]) -> float:
        normalized = [float(value) for value in values if float(value) > 0]
        if not normalized:
            return 0.0
        top = normalized[:20]
        base_weights = [0.4 / 5] * 5 + [0.3 / 5] * 5 + [0.2 / 6] * 6 + [0.1 / 4] * 4
        weights = base_weights[: len(top)]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            return 0.0
        return sum(
            (value * (weight / weight_sum) for value, weight in zip(top, weights))
        )

    def _load_dani_dynamic_score_context(self) -> dict:
        return self.inputs.rating_context

    def _load_dani_dynamic_song_title_level_index(
        self,
    ) -> Dict[Tuple[str, int], List[Dict[str, Any]]]:
        ctx = self._load_dani_dynamic_score_context()
        mapping: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for song_key, song_info in (ctx.get("songs") or {}).items():
            level = _safe_int(song_info.get("level"), 0)
            if level <= 0:
                continue
            titles = {
                _normalize_song_title(song_key),
                _normalize_song_title(song_info.get("曲名")),
                _normalize_song_title(song_info.get("song_name_cn")),
            }
            for title in titles:
                if not title:
                    continue
                mapping.setdefault((title, level), []).append(song_info)
        return mapping

    def _resolve_dynamic_song_info(
        self, song_id: int, level: int, ctx: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        score_calc = ctx["module"]
        found = score_calc._find_song_info_for_recommend_record(
            song_id, level, ctx["idx_by_id_level"], ctx["idx_by_identity"]
        )
        if not found:
            return None
        return found[1]

    def _resolve_dynamic_song_info_by_title(
        self, title: Any, level: int, note_count: int
    ) -> Optional[Dict[str, Any]]:
        normalized = _normalize_song_title(title)
        if not normalized or level <= 0:
            return None
        candidates = list(
            self._load_dani_dynamic_song_title_level_index().get(
                (normalized, level), []
            )
        )
        if not candidates:
            return None
        if note_count > 0:
            note_matches = [
                item
                for item in candidates
                if _safe_int(item.get("combo"), -1) == note_count
            ]
            if note_matches:
                candidates = note_matches
        if len(candidates) == 1:
            return candidates[0]
        matched_ids = {
            candidate_id
            for candidate_id in (_safe_int(item.get("id"), -1) for item in candidates)
            if candidate_id > 0
        }
        if len(matched_ids) == 1 and candidates:
            return candidates[0]
        return None

    def _resolve_grade_dynamic_song_info(
        self, song: Dict[str, Any], ctx: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        level = _difficulty_level(song.get("difficulty"))
        if level not in {4, 5}:
            return None
        song_id = _safe_int(song.get("id"), -1)
        if song_id > 0:
            exact = self._resolve_dynamic_song_info(song_id, level, ctx)
            if exact is not None:
                return exact
        return self._resolve_dynamic_song_info_by_title(
            song.get("title"), level, _safe_int(song.get("noteCount"), 0)
        )

    def _resolve_grade_song_dimension_profile(
        self, song: Dict[str, Any], ctx: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        song_info = self._resolve_grade_dynamic_song_info(song, ctx)
        if not song_info:
            return None
        score_calc = ctx["module"]
        profile: Dict[str, float] = {}
        for attr, indicator_dim, _ in DANI_DYNAMIC_DIMENSION_SPECS:
            raw_indicator = score_calc._get_song_indicator_value(
                song_info, indicator_dim, ctx["const_table"]
            )
            if raw_indicator is None:
                return None
            indicator = float(raw_indicator or 0.0)
            if indicator < 0:
                return None
            profile[attr] = indicator
        return profile

    def _build_dynamic_user_dimension_profile(
        self,
        results: List[Any],
        ctx: Dict[str, Any],
        *,
        rated_results: Optional[List[Any]] = None,
    ) -> Optional[Dict[str, float]]:
        if not results:
            return None
        filtered = rated_results or [
            result
            for result in results
            if float(getattr(result, "AI_rating", 0.0) or 0.0) > 0
        ]
        if len(filtered) < DANI_DYNAMIC_PROFILE_MIN_RATED_SONGS:
            return None
        score_calc = ctx["module"]
        profile: Dict[str, float] = {}
        for attr, indicator_dim, _ in DANI_DYNAMIC_DIMENSION_SPECS:
            ranked = sorted(
                (
                    result
                    for result in filtered
                    if float(getattr(result, attr, 0.0) or 0.0) > 0
                ),
                key=lambda result: float(getattr(result, attr, 0.0) or 0.0),
                reverse=True,
            )[:20]
            indicator_values: List[float] = []
            for result in ranked:
                song_info = self._resolve_dynamic_song_info(
                    _safe_int(getattr(result, "song_id", 0), 0),
                    _safe_int(getattr(result, "level", 0), 0),
                    ctx,
                )
                if not song_info:
                    continue
                indicator = float(
                    score_calc._get_song_indicator_value(
                        song_info, indicator_dim, ctx["const_table"]
                    )
                    or 0.0
                )
                if indicator > 0:
                    indicator_values.append(indicator)
            weighted = self._top20_weighted_average(indicator_values)
            if weighted <= 0:
                return None
            profile[attr] = weighted
        return profile

    def _compute_dynamic_user_results(
        self, user_scores: List[Dict[str, Any]], ctx: Dict[str, Any]
    ) -> List[Any]:
        if not user_scores:
            return []
        score_calc = ctx["module"]
        with redirect_stdout(io.StringIO()):
            return score_calc._compute_results_from_userdata_records(
                user_scores,
                ctx["cfg"],
                ctx["const_table"],
                collapse_duplicate_versions=False,
            )

    def _dynamic_user_summary_cache_key(
        self, user_scores: List[Dict[str, Any]]
    ) -> Tuple[int, int, int, int, int, int]:
        if not user_scores:
            return (0, 0, 0, 0, 0, 0)
        first = user_scores[0] or {}
        last = user_scores[-1] or {}
        return (
            id(user_scores),
            len(user_scores),
            _safe_int(first.get("song_no", first.get("id", 0)), 0),
            _safe_int(first.get("high_score"), 0),
            _safe_int(last.get("song_no", last.get("id", 0)), 0),
            _safe_int(last.get("high_score"), 0),
        )

    def _build_dynamic_user_summary(
        self, user_scores: List[Dict[str, Any]], ctx: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if not user_scores:
            return None
        cache_key = self._dynamic_user_summary_cache_key(user_scores)
        cached = self._summary_cache.get(cache_key, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        results = self._compute_dynamic_user_results(user_scores, ctx)
        rated_results = [
            result
            for result in results
            if float(getattr(result, "AI_rating", 0.0) or 0.0) > 0
        ]
        if len(rated_results) < DANI_DYNAMIC_PROFILE_MIN_RATED_SONGS:
            summary = None
        else:
            user_profile = self._build_dynamic_user_dimension_profile(
                results, ctx, rated_results=rated_results
            )
            user_rate_profile = self._build_dynamic_user_rate_profile(results, ctx)
            user_accuracy_baseline = (
                user_rate_profile.get("accuracy_power") if user_rate_profile else None
            )
            user_structure_profile = self._build_dynamic_user_structure_profile(
                results, ctx
            )
            if (
                not user_profile
                or not user_rate_profile
                or user_accuracy_baseline is None
                or (not user_structure_profile)
            ):
                summary = None
            else:
                summary = {
                    "user_profile": user_profile,
                    "user_rate_profile": user_rate_profile,
                    "user_accuracy_baseline": user_accuracy_baseline,
                    "user_structure_profile": user_structure_profile,
                }
        if len(self._summary_cache) >= 8:
            self._summary_cache.clear()
        self._summary_cache[cache_key] = summary
        return summary

    def _build_dynamic_user_rate_profile(
        self, results: List[Any], ctx: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        if not results:
            return None
        score_calc = ctx["module"]
        columns = {
            "overall": "AI_rating",
            "accuracy_power": "精度力",
            "big_song": "大歌力",
        }
        profile: Dict[str, float] = {}
        for attr, column in columns.items():
            try:
                value = float(
                    score_calc.aggregate_topN_value(results, column, 20) or 0.0
                )
            except Exception:
                return None
            if value <= 0:
                return None
            profile[attr] = value
        return profile

    def _build_dynamic_user_structure_profile(
        self, results: List[Any], ctx: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        if not results:
            return None
        score_calc = ctx["module"]
        profile: Dict[str, float] = {}
        for attr, label in STRUCTURE_ROLE_DIMENSION_SPECS:
            try:
                value = float(
                    score_calc.aggregate_topN_value(results, label, 20) or 0.0
                )
            except Exception:
                return None
            if value <= 0:
                return None
            profile[attr] = value
        return profile

    def _required_accuracy_power_for_good_target(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        good_target: int,
        ctx: Dict[str, Any],
    ) -> float:
        return float(
            self._required_rate_profile_for_good_target(
                song_info, note_count, good_target, ctx
            ).get("accuracy_power", 0.0)
            or 0.0
        )

    def _required_rate_profile_for_good_target(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        good_target: int,
        ctx: Dict[str, Any],
    ) -> Dict[str, float]:
        total_notes = max(0, note_count or _safe_int(song_info.get("combo"), 0))
        if total_notes <= 0:
            return {"overall": 0.0, "accuracy_power": 0.0, "big_song": 0.0}
        cache_key = (
            _safe_int(song_info.get("id"), -1),
            _safe_int(song_info.get("level"), -1),
            total_notes,
            max(0, min(total_notes, _safe_int(good_target, 0))),
        )
        cached = self._rate_cache.get(cache_key)
        if cached is not None:
            return cached
        score_calc = ctx["module"]
        clamped_good = cache_key[3]
        ok_count = max(0, total_notes - clamped_good)
        accuracy = float(
            score_calc.calc_accuracy(
                total_notes=total_notes,
                great_cnt=clamped_good,
                good_cnt=ok_count,
                algorithm="comprehensive",
            )
            or 0.0
        )
        if accuracy <= 0:
            return {"overall": 0.0, "accuracy_power": 0.0, "big_song": 0.0}
        const_value = float(song_info.get("score", 0.0) or 0.0)
        M = float(score_calc.lookup_const_score(const_value, ctx["const_table"]))
        N = float(
            score_calc.calc_y(
                accuracy=accuracy, normalization_factor=15.5, algorithm="comprehensive"
            )
            or 0.0
        )
        P = float(score_calc.compute_P(M, N))
        Q = float(score_calc.compute_Q(M, N))
        AI = float(score_calc.compute_AI(M, N, P, Q))
        metrics = score_calc.compute_AD_AE_AF_AG(song_info)
        six = score_calc.compute_six_dims(AI, M, N, metrics)
        value = {
            "overall": AI,
            "accuracy_power": float(six.get("精度力", 0.0) or 0.0),
            "big_song": float(six.get("大歌力", 0.0) or 0.0),
        }
        if len(self._rate_cache) >= 16384:
            self._rate_cache.clear()
        self._rate_cache[cache_key] = value
        return value

    def _required_accuracy_power_for_ok_limit(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        ok_limit: int,
        ctx: Dict[str, Any],
    ) -> float:
        total_notes = max(0, note_count or _safe_int(song_info.get("combo"), 0))
        if total_notes <= 0:
            return 0.0
        max_ok = min(total_notes, max(0, _safe_int(ok_limit, 0) - 1))
        good_target = max(0, total_notes - max_ok)
        return self._required_accuracy_power_for_good_target(
            song_info, total_notes, good_target, ctx
        )

    def _required_rate_load_for_good_target(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        good_target: int,
        user_rate_profile: Dict[str, float],
        ctx: Dict[str, Any],
    ) -> float:
        required = self._required_rate_profile_for_good_target(
            song_info, note_count, good_target, ctx
        )
        load = 0.0
        for attr, weight in DANI_DYNAMIC_RATE_LOAD_WEIGHTS.items():
            user_value = max(float(user_rate_profile.get(attr, 0.0) or 0.0), 0.1)
            required_value = float(required.get(attr, 0.0) or 0.0)
            load += weight * max((required_value - user_value) / user_value, 0.0)
        return load

    def _find_rate_reference_good(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        user_rate_profile: Dict[str, float],
        ctx: Dict[str, Any],
    ) -> int:
        total_notes = max(0, note_count or _safe_int(song_info.get("combo"), 0))
        if total_notes <= 0:
            return 0
        lo = 0
        hi = total_notes
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            load = self._required_rate_load_for_good_target(
                song_info, total_notes, mid, user_rate_profile, ctx
            )
            if load <= DANI_DYNAMIC_RATE_LOAD_LIMIT + 1e-09:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    def _center_and_clamp_pressures(self, pressures: List[float]) -> List[float]:
        if not pressures:
            return []
        center = sum(pressures) / float(len(pressures))
        return [
            max(
                -DANI_DYNAMIC_PRESSURE_CLAMP,
                min(DANI_DYNAMIC_PRESSURE_CLAMP, pressure - center),
            )
            for pressure in pressures
        ]

    def _build_role_pressure_context(
        self,
        song_profiles: List[Dict[str, float]],
        user_structure_profile: Dict[str, float],
    ) -> Dict[str, Any]:
        if not song_profiles:
            return {
                "raw": [],
                "centered": [],
                "role_dims_per_song": [],
                "role_deltas_per_song": [],
            }
        user_best = max(
            (float(value or 0.0) for value in user_structure_profile.values())
        )
        user_weak_raw = {
            attr: max(
                user_best - float(user_structure_profile.get(attr, 0.0) or 0.0), 0.0
            )
            for attr, _ in STRUCTURE_ROLE_DIMENSION_SPECS
        }
        user_weak_total = sum(user_weak_raw.values()) if user_weak_raw else 0.0
        user_weak_norm = {
            attr: (
                user_weak_raw[attr] / user_weak_total
                if user_weak_total > 1e-09
                else 0.0
            )
            for attr in user_weak_raw
        }
        grade_stats: Dict[str, Tuple[float, float, float]] = {}
        for attr, _ in STRUCTURE_ROLE_DIMENSION_SPECS:
            values = [
                float(song_profile.get(attr, 0.0) or 0.0)
                for song_profile in song_profiles
            ]
            grade_stats[attr] = (sum(values) / len(values), min(values), max(values))
        raw_pressures: List[float] = []
        role_dims_per_song: List[List[str]] = []
        role_deltas_per_song: List[Dict[str, float]] = []
        role_strength_per_song: List[float] = []
        for song_profile in song_profiles:
            positive_deltas: List[Tuple[float, str]] = []
            all_deltas: Dict[str, float] = {}
            for attr, _ in STRUCTURE_ROLE_DIMENSION_SPECS:
                mean_value, min_value, max_value = grade_stats[attr]
                denom = max(max_value - min_value, 1.0)
                delta = (float(song_profile.get(attr, 0.0) or 0.0) - mean_value) / denom
                if delta < 0:
                    delta = 0.0
                all_deltas[attr] = delta
                if delta > 0:
                    positive_deltas.append((delta, attr))
            positive_deltas.sort(reverse=True)
            kept = positive_deltas[:2]
            kept_attrs = {attr for _, attr in kept}
            kept_deltas = {
                attr: all_deltas[attr] if attr in kept_attrs else 0.0
                for attr, _ in STRUCTURE_ROLE_DIMENSION_SPECS
            }
            role_deltas_per_song.append(kept_deltas)
            role_dims_per_song.append([attr for _, attr in kept])
            role_strength_per_song.append(sum(kept_deltas.values()))
            raw_pressures.append(
                sum(
                    (
                        kept_deltas[attr] * user_weak_norm.get(attr, 0.0)
                        for attr, _ in STRUCTURE_ROLE_DIMENSION_SPECS
                    )
                )
            )
        return {
            "raw": raw_pressures,
            "centered": self._center_and_clamp_pressures(raw_pressures),
            "role_dims_per_song": role_dims_per_song,
            "role_deltas_per_song": role_deltas_per_song,
            "role_strength_per_song": role_strength_per_song,
            "user_structure_profile": user_structure_profile,
            "user_weak_norm": user_weak_norm,
        }

    def _build_const_pressure_context(
        self, song_infos: List[Dict[str, Any]], role_strength_per_song: List[float]
    ) -> Dict[str, Any]:
        result = {
            "raw": [0.0 for _ in song_infos],
            "centered": [0.0 for _ in song_infos],
            "const_values": [0.0 for _ in song_infos],
            "const_factors": [1.0 for _ in song_infos],
        }
        if not song_infos:
            return result
        const_values = []
        for song_info in song_infos:
            const_value = float(song_info.get("score", 0.0) or 0.0)
            const_values.append(const_value if const_value > 0 else 0.0)
        positive_values = [value for value in const_values if value > 0]
        if not positive_values:
            result["const_values"] = const_values
            return result
        mean_const = sum(positive_values) / float(len(positive_values))
        const_span = max(positive_values) - min(positive_values)
        denom = max(const_span, 0.1)
        max_strength = max(role_strength_per_song) if role_strength_per_song else 0.0
        raw_pressures: List[float] = []
        const_factors: List[float] = []
        for idx, const_value in enumerate(const_values):
            if const_value <= 0:
                const_relative = 0.0
            else:
                const_relative = (const_value - mean_const) / denom
            strength = (
                float(role_strength_per_song[idx])
                if idx < len(role_strength_per_song)
                else 0.0
            )
            strength_norm = strength / max_strength if max_strength > 1e-09 else 0.0
            const_factor = DANI_DYNAMIC_CONST_MIN_FACTOR + (
                1.0 - DANI_DYNAMIC_CONST_MIN_FACTOR
            ) * (1.0 - strength_norm)
            const_factors.append(const_factor)
            raw_pressures.append(const_relative * const_factor)
        result.update(
            {
                "raw": raw_pressures,
                "centered": self._center_and_clamp_pressures(raw_pressures),
                "const_values": const_values,
                "const_factors": const_factors,
            }
        )
        return result

    def _combine_dynamic_pressures(
        self,
        role_centered: List[float],
        absolute_centered: List[float],
        const_centered: List[float],
    ) -> List[float]:
        count = max(len(role_centered), len(absolute_centered), len(const_centered))
        if count <= 0:
            return []
        combined: List[float] = []
        for idx in range(count):
            role_value = role_centered[idx] if idx < len(role_centered) else 0.0
            absolute_value = (
                absolute_centered[idx] if idx < len(absolute_centered) else 0.0
            )
            const_value = const_centered[idx] if idx < len(const_centered) else 0.0
            combined.append(
                role_value * DANI_DYNAMIC_ROLE_WEIGHT
                + absolute_value * DANI_DYNAMIC_ABSOLUTE_WEIGHT
                + const_value * DANI_DYNAMIC_CONST_WEIGHT
            )
        return self._center_and_clamp_pressures(combined)

    def _can_use_dynamic_rate_allocation(
        self, grade: Dict[str, Any], user_scores: Optional[List[Dict[str, Any]]]
    ) -> bool:
        songs = grade.get("songs") or []
        if len(songs) != 3 or not user_scores:
            return False
        if not all(
            (_difficulty_level(song.get("difficulty")) in {4, 5} for song in songs)
        ):
            return False
        pass_cond = (grade.get("conditions") or {}).get("pass") or {}
        pass_good_raw = pass_cond.get("goodCountAtLeast")
        pass_ok_raw = pass_cond.get("okCountLessThan")
        has_scalar_good = pass_good_raw is not None and (
            not isinstance(pass_good_raw, list)
        )
        has_scalar_ok = pass_ok_raw is not None and (not isinstance(pass_ok_raw, list))
        return has_scalar_good != has_scalar_ok

    def _build_dynamic_rate_context(
        self,
        grade: Dict[str, Any],
        notes: List[int],
        user_scores: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        if not self._can_use_dynamic_rate_allocation(grade, user_scores):
            return None
        ctx = self._load_dani_dynamic_score_context()
        user_summary = self._build_dynamic_user_summary(user_scores or [], ctx)
        if not user_summary:
            return None
        user_profile = user_summary["user_profile"]
        user_rate_profile = user_summary["user_rate_profile"]
        user_accuracy_baseline = user_summary["user_accuracy_baseline"]
        user_structure_profile = user_summary["user_structure_profile"]
        song_profiles: List[Dict[str, float]] = []
        song_infos: List[Dict[str, Any]] = []
        rate_reference_good: List[int] = []
        for song, note_count in zip(grade.get("songs") or [], notes):
            song_info = self._resolve_grade_dynamic_song_info(song, ctx)
            if not song_info:
                return None
            song_infos.append(song_info)
            song_profile = self._resolve_grade_song_dimension_profile(song, ctx)
            if not song_profile:
                return None
            song_profiles.append(song_profile)
            rate_reference_good.append(
                self._find_rate_reference_good(
                    song_info, note_count, user_rate_profile, ctx
                )
            )
        pressures: List[float] = []
        for song_profile in song_profiles:
            pressure = 0.0
            for attr, _, weight in DANI_DYNAMIC_DIMENSION_SPECS:
                user_indicator = max(float(user_profile.get(attr, 0.0) or 0.0), 0.1)
                song_indicator = float(song_profile.get(attr, 0.0) or 0.0)
                pressure += weight * (
                    (song_indicator - user_indicator) / user_indicator
                )
            pressures.append(pressure)
        if not pressures:
            return None
        absolute_centered = self._center_and_clamp_pressures(pressures)
        role_ctx = self._build_role_pressure_context(
            song_profiles, user_structure_profile
        )
        const_ctx = self._build_const_pressure_context(
            song_infos, list(role_ctx.get("role_strength_per_song") or [])
        )
        final_centered = self._combine_dynamic_pressures(
            role_ctx["centered"], absolute_centered, const_ctx["centered"]
        )
        return {
            "centered": final_centered,
            "absolute_centered": absolute_centered,
            "role_centered": list(role_ctx.get("centered") or []),
            "const_centered": list(const_ctx.get("centered") or []),
            "role_dims_per_song": list(role_ctx.get("role_dims_per_song") or []),
            "role_deltas_per_song": list(role_ctx.get("role_deltas_per_song") or []),
            "role_strength_per_song": list(
                role_ctx.get("role_strength_per_song") or []
            ),
            "const_values_per_song": list(const_ctx.get("const_values") or []),
            "const_factors_per_song": list(const_ctx.get("const_factors") or []),
            "user_accuracy_baseline": user_accuracy_baseline,
            "user_rate_profile": dict(user_rate_profile),
            "rate_reference_good": rate_reference_good,
            "song_infos": song_infos,
            "score_ctx": ctx,
        }

    def _good_target_to_ok_limit(self, note_count: int, good_target: int) -> int:
        total_notes = max(0, _safe_int(note_count, 0))
        clamped_good = max(0, min(total_notes, _safe_int(good_target, 0)))
        return max(1, total_notes - clamped_good + 1)

    def _ok_total_to_required_good_total(
        self, total_ok_limit: Any, notes: List[int]
    ) -> int:
        total_notes = sum((max(0, _safe_int(note, 0)) for note in notes))
        total_song_count = len(notes)
        official_ok = max(0, _safe_int(total_ok_limit, 0))
        return max(0, min(total_notes, total_notes - (official_ok - total_song_count)))

    def _good_target_delta_cost(
        self,
        song_info: Dict[str, Any],
        note_count: int,
        from_good: int,
        to_good: int,
        reference_good: int,
        centered_pressure: float,
        user_rate_profile: Dict[str, float],
        ctx: Dict[str, Any],
    ) -> float:
        if from_good == to_good:
            return 0.0
        to_load = self._required_rate_load_for_good_target(
            song_info, note_count, to_good, user_rate_profile, ctx
        )
        required_profile = self._required_rate_profile_for_good_target(
            song_info, note_count, to_good, ctx
        )
        direction = 1 if to_good > from_good else -1
        user_accuracy = max(
            float(user_rate_profile.get("accuracy_power", 0.0) or 0.0), 0.1
        )
        accuracy_over = max(
            (
                float(required_profile.get("accuracy_power", 0.0) or 0.0)
                - (user_accuracy + DANI_DYNAMIC_ACCURACY_OVER_TOLERANCE)
            )
            / user_accuracy,
            0.0,
        )
        load_penalty = to_load**DANI_DYNAMIC_RATE_LOAD_COST_POWER
        accuracy_penalty = DANI_DYNAMIC_ACCURACY_OVER_WEIGHT * accuracy_over**2
        reference_penalty = (
            abs(to_good - reference_good) / float(max(1, _safe_int(note_count, 0)))
        ) ** 2 * DANI_DYNAMIC_REFERENCE_DISTANCE_SCALE
        near_full_steps = max(
            to_good
            - (max(0, _safe_int(note_count, 0)) - DANI_DYNAMIC_SOFT_MIN_OK_LIMIT + 1),
            0,
        )
        near_full_penalty = DANI_DYNAMIC_NEAR_FULL_COST_SCALE * near_full_steps**2
        pressure_scale = (
            DANI_DYNAMIC_PRESSURE_TIGHTEN_COST_SCALE
            if direction > 0
            else DANI_DYNAMIC_PRESSURE_LOOSEN_COST_SCALE
        )
        pressure_penalty = centered_pressure * direction * pressure_scale
        return max(
            0.0,
            load_penalty
            + accuracy_penalty
            + reference_penalty
            + near_full_penalty
            + pressure_penalty,
        )

    def _allocate_capped_proportional_float(
        self, total: int, weights: List[float], capacities: List[int]
    ) -> List[int]:
        capped = [max(0, _safe_int(value, 0)) for value in capacities]
        if total <= 0 or not capped:
            return [0 for _ in capped]
        remaining = min(_safe_int(total, 0), sum(capped))
        if remaining <= 0:
            return [0 for _ in capped]
        normalized = [max(0.0, _safe_float(weight, 0.0)) for weight in weights]
        if len(normalized) < len(capped):
            normalized.extend([1.0] * (len(capped) - len(normalized)))
        normalized = normalized[: len(capped)]
        allocated = [0 for _ in capped]
        while remaining > 0:
            active = [idx for idx, cap in enumerate(capped) if allocated[idx] < cap]
            if not active:
                break
            active_weights = [
                normalized[idx] if idx in active else 0.0 for idx in range(len(capped))
            ]
            if sum(active_weights) <= 0:
                active_weights = [
                    1.0 if idx in active else 0.0 for idx in range(len(capped))
                ]
            proposal = self._allocate_proportional_float(remaining, active_weights)
            progressed = False
            for idx, proposed in enumerate(proposal):
                if proposed <= 0 or allocated[idx] >= capped[idx]:
                    continue
                add = min(proposed, capped[idx] - allocated[idx])
                if add <= 0:
                    continue
                allocated[idx] += add
                remaining -= add
                progressed = True
            if not progressed:
                picked = max(
                    active,
                    key=lambda idx: (
                        active_weights[idx],
                        capped[idx] - allocated[idx],
                        -idx,
                    ),
                )
                allocated[picked] += 1
                remaining -= 1
        return allocated

    def _allocate_smoothed_loosen_budget(
        self, total_loosen: int, centered: List[float], capacities: List[int]
    ) -> List[int]:
        capped = [max(0, _safe_int(value, 0)) for value in capacities]
        if total_loosen <= 0 or not capped:
            return [0 for _ in capped]
        loosen_total = min(_safe_int(total_loosen, 0), sum(capped))
        if loosen_total <= 0:
            return [0 for _ in capped]
        weights: List[float] = []
        for idx in range(len(capped)):
            pressure = _safe_float(centered[idx], 0.0) if idx < len(centered) else 0.0
            weight = 1.0 + pressure * DANI_DYNAMIC_LOOSEN_PRESSURE_WEIGHT
            weights.append(
                max(
                    DANI_DYNAMIC_LOOSEN_WEIGHT_MIN,
                    min(DANI_DYNAMIC_LOOSEN_WEIGHT_MAX, weight),
                )
            )
        minimum_share = int(
            math.floor(
                loosen_total
                / float(max(1, len(capped)))
                * DANI_DYNAMIC_MIN_LOOSEN_SHARE_FACTOR
            )
        )
        minimums = [
            min(capacity, minimum_share) if capacity > 0 else 0 for capacity in capped
        ]
        minimum_total = sum(minimums)
        if minimum_total >= loosen_total:
            return self._allocate_capped_proportional_float(
                loosen_total, weights, capped
            )
        extra = self._allocate_capped_proportional_float(
            loosen_total - minimum_total,
            weights,
            [capacity - minimum for capacity, minimum in zip(capped, minimums)],
        )
        return [minimum + add for minimum, add in zip(minimums, extra)]

    def _allocate_dynamic_good_targets(
        self, total_good: int, notes: List[int], dynamic_ctx: Optional[Dict[str, Any]]
    ) -> Optional[List[int]]:
        if dynamic_ctx is None:
            return None
        total_value = _safe_int(total_good, 0)
        if total_value <= 0:
            return [0 for _ in notes]
        centered = dynamic_ctx.get("centered") or []
        if len(centered) != len(notes):
            return None
        reference_targets = [
            min(max(0, note), max(0, _safe_int(value, 0)))
            for note, value in zip(
                notes, dynamic_ctx.get("rate_reference_good") or [0 for _ in notes]
            )
        ]
        if len(reference_targets) != len(notes):
            return None
        soft_max_targets = [
            max(0, _safe_int(note, 0) - DANI_DYNAMIC_SOFT_MIN_OK_LIMIT + 1)
            for note in notes
        ]
        max_targets = (
            soft_max_targets
            if sum(soft_max_targets) >= total_value
            else [max(0, _safe_int(note, 0)) for note in notes]
        )
        allocated = [
            min(reference, max_target)
            for reference, max_target in zip(reference_targets, max_targets)
        ]
        current_total = sum(allocated)
        if current_total == total_value:
            return allocated
        song_infos = dynamic_ctx.get("song_infos") or []
        if len(song_infos) != len(notes):
            return None
        ctx = dynamic_ctx.get("score_ctx")
        if not ctx:
            return None
        user_rate_profile = dynamic_ctx.get("user_rate_profile") or {}
        if not user_rate_profile:
            return None
        if current_total < total_value:
            remaining = total_value - current_total
            while remaining > 0:
                candidates: List[Tuple[float, int]] = []
                for idx, note_count in enumerate(notes):
                    if allocated[idx] >= max_targets[idx]:
                        continue
                    next_good = allocated[idx] + 1
                    cost = self._good_target_delta_cost(
                        song_infos[idx],
                        note_count,
                        allocated[idx],
                        next_good,
                        reference_targets[idx],
                        centered[idx],
                        user_rate_profile,
                        ctx,
                    )
                    candidates.append((cost, idx))
                if not candidates:
                    break
                _, picked = min(candidates, key=lambda item: (item[0], item[1]))
                allocated[picked] += 1
                remaining -= 1
        else:
            loosen_targets = self._allocate_smoothed_loosen_budget(
                current_total - total_value, centered, allocated
            )
            for idx, loosen in enumerate(loosen_targets):
                if loosen <= 0:
                    continue
                actual_loosen = min(loosen, allocated[idx])
                allocated[idx] -= actual_loosen
            remaining = sum(allocated) - total_value
            while remaining > 0:
                candidates = []
                for idx, note_count in enumerate(notes):
                    if allocated[idx] <= 0:
                        continue
                    next_good = allocated[idx] - 1
                    cost = self._good_target_delta_cost(
                        song_infos[idx],
                        note_count,
                        allocated[idx],
                        next_good,
                        reference_targets[idx],
                        centered[idx],
                        user_rate_profile,
                        ctx,
                    )
                    candidates.append((cost, idx))
                if not candidates:
                    break
                _, picked = min(candidates, key=lambda item: (item[0], item[1]))
                allocated[picked] -= 1
                remaining -= 1
        return allocated

    def _derive_song_targets(
        self, grade: Dict[str, Any], user_scores: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        songs = grade["songs"]
        notes = [self._note_count(song) for song in songs]
        formulas = [self._accuracy_formula(song) for song in songs]
        pass_cond = grade["conditions"]["pass"]
        gold_cond = self._resolved_gold_conditions(grade)
        pass_good_raw = pass_cond.get("goodCountAtLeast")
        pass_ok_raw = pass_cond.get("okCountLessThan")
        pass_bad_raw = pass_cond.get("badCountLessThan")
        pass_drumroll_raw = pass_cond.get("drumrollCountAtLeast")
        pass_hit_raw = pass_cond.get("hitCountAtLeast")
        gold_good_raw = gold_cond.get("goodCountAtLeast")
        gold_ok_raw = gold_cond.get("okCountLessThan")
        gold_bad_raw = gold_cond.get("badCountLessThan")
        gold_drumroll_raw = gold_cond.get("drumrollCountAtLeast")
        gold_hit_raw = gold_cond.get("hitCountAtLeast")
        dynamic_ctx = self._build_dynamic_rate_context(grade, notes, user_scores)
        pass_good_targets = (
            self._allocate_dynamic_good_targets(pass_good_raw, notes, dynamic_ctx)
            if pass_good_raw is not None and (not isinstance(pass_good_raw, list))
            else None
        ) or self._scalar_or_list(pass_good_raw, notes)
        gold_good_targets = (
            self._allocate_dynamic_good_targets(gold_good_raw, notes, dynamic_ctx)
            if gold_good_raw is not None and (not isinstance(gold_good_raw, list))
            else None
        ) or self._scalar_or_list(gold_good_raw, notes)
        pass_ok_good_targets = (
            self._allocate_dynamic_good_targets(
                self._ok_total_to_required_good_total(pass_ok_raw, notes),
                notes,
                dynamic_ctx,
            )
            if pass_ok_raw is not None and (not isinstance(pass_ok_raw, list))
            else None
        )
        gold_ok_good_targets = (
            self._allocate_dynamic_good_targets(
                self._ok_total_to_required_good_total(gold_ok_raw, notes),
                notes,
                dynamic_ctx,
            )
            if gold_ok_raw is not None and (not isinstance(gold_ok_raw, list))
            else None
        )
        pass_ok_targets = (
            [
                self._good_target_to_ok_limit(note_count, good_target)
                for note_count, good_target in zip(notes, pass_ok_good_targets)
            ]
            if pass_ok_good_targets is not None
            else None
        ) or self._scalar_or_list(pass_ok_raw, notes)
        gold_ok_targets = (
            [
                self._good_target_to_ok_limit(note_count, good_target)
                for note_count, good_target in zip(notes, gold_ok_good_targets)
            ]
            if gold_ok_good_targets is not None
            else None
        ) or self._scalar_or_list(gold_ok_raw, notes)
        dynamic_good_enabled = dynamic_ctx is not None and pass_good_raw is not None
        dynamic_ok_enabled = dynamic_ctx is not None and pass_ok_raw is not None
        return {
            "notes": notes,
            "formulas": formulas,
            "has_rate_target": pass_good_raw is not None or pass_ok_raw is not None,
            "rate_per_song": isinstance(pass_good_raw, list)
            or isinstance(pass_ok_raw, list),
            "good_per_song": isinstance(pass_good_raw, list) or dynamic_good_enabled,
            "ok_per_song": isinstance(pass_ok_raw, list) or dynamic_ok_enabled,
            "pass_rate": self._rate_target_list(
                notes,
                pass_cond,
                good_targets=pass_good_targets,
                ok_limits=pass_ok_targets,
            ),
            "gold_rate": self._rate_target_list(
                notes,
                gold_cond,
                good_targets=gold_good_targets,
                ok_limits=gold_ok_targets,
            ),
            "pass_good": pass_good_targets,
            "gold_good": gold_good_targets,
            "pass_ok": pass_ok_targets,
            "gold_ok": gold_ok_targets,
            "dynamic_rate_enabled": dynamic_ctx is not None,
            "dynamic_centered": (
                list(dynamic_ctx.get("centered") or []) if dynamic_ctx else []
            ),
            "dynamic_absolute_centered": (
                list(dynamic_ctx.get("absolute_centered") or []) if dynamic_ctx else []
            ),
            "dynamic_role_centered": (
                list(dynamic_ctx.get("role_centered") or []) if dynamic_ctx else []
            ),
            "dynamic_const_centered": (
                list(dynamic_ctx.get("const_centered") or []) if dynamic_ctx else []
            ),
            "dynamic_role_dims_per_song": (
                list(dynamic_ctx.get("role_dims_per_song") or []) if dynamic_ctx else []
            ),
            "dynamic_role_strength_per_song": (
                list(dynamic_ctx.get("role_strength_per_song") or [])
                if dynamic_ctx
                else []
            ),
            "dynamic_user_accuracy_baseline": (
                float(dynamic_ctx.get("user_accuracy_baseline") or 0.0)
                if dynamic_ctx
                else 0.0
            ),
            "dynamic_user_rate_profile": (
                dict(dynamic_ctx.get("user_rate_profile") or {}) if dynamic_ctx else {}
            ),
            "dynamic_rate_reference_good": (
                list(dynamic_ctx.get("rate_reference_good") or [])
                if dynamic_ctx
                else []
            ),
            "has_bad_target": pass_bad_raw is not None,
            "bad_per_song": isinstance(pass_bad_raw, list),
            "pass_bad": self._scalar_or_list(pass_bad_raw, notes),
            "gold_bad": self._scalar_or_list(gold_bad_raw, notes),
            "has_drumroll_target": pass_drumroll_raw is not None,
            "drumroll_per_song": isinstance(pass_drumroll_raw, list),
            "pass_drumroll": self._scalar_or_drumroll_list(
                pass_drumroll_raw, songs, notes
            ),
            "gold_drumroll": self._scalar_or_drumroll_list(
                gold_drumroll_raw, songs, notes
            ),
            "has_hit_target": pass_hit_raw is not None,
            "hit_per_song": isinstance(pass_hit_raw, list),
            "pass_hit": self._scalar_or_list(pass_hit_raw, notes),
            "gold_hit": self._scalar_or_list(gold_hit_raw, notes),
        }

    def _best_tier(
        self, pass_ok: bool, gold_ok: bool, full_combo: bool, all_good: bool
    ) -> int:
        if gold_ok:
            if all_good:
                return 7
            if full_combo:
                return 5
            return 3
        if pass_ok:
            if all_good:
                return 6
            if full_combo:
                return 4
            return 2
        return 1

    def _metric_pass(self, value: float, target: float) -> bool:
        return target > 0 and value >= target

    def _metric_pass_bad(self, current: int, target_raw: int) -> bool:
        return target_raw > 0 and current < target_raw

    def _metric_ratio(
        self, kind: str, current: float | int, target: float | int
    ) -> float:
        target_value = float(target)
        current_value = float(current)
        if target_value <= 0:
            return 0.0
        if kind in {"bad", "ok"}:
            if current_value <= 0:
                return 1.0
            if current_value < target_value:
                return 1.0
            return max(0.0, min(1.0, target_value / current_value))
        return max(0.0, min(1.0, current_value / target_value))

    def _metric_icon_index(
        self,
        kind: str,
        current: float | int,
        pass_target: float | int,
        gold_target: float | int,
        full_combo: bool,
        all_good: bool,
    ) -> int:
        if kind in {"bad", "ok"}:
            pass_ok = self._metric_pass_bad(int(current), int(pass_target))
            gold_ok = self._metric_pass_bad(int(current), int(gold_target))
        else:
            pass_ok = self._metric_pass(float(current), float(pass_target))
            gold_ok = self._metric_pass(float(current), float(gold_target))
        return self._best_tier(pass_ok, gold_ok, full_combo, all_good)

    def _build_primary_metric(
        self,
        grade: Dict[str, Any],
        derived: Dict[str, Any],
        idx: int,
        counts: Dict[str, int],
        accuracy: float,
        full_combo: bool,
        all_good: bool,
    ) -> Dict[str, Any]:
        pass_cond = grade["conditions"]["pass"]
        if pass_cond.get("goodCountAtLeast") is not None:
            kind = "good"
            current = counts["good"]
            pass_target = derived["pass_good"][idx]
            gold_target = derived["gold_good"][idx]
            estimated = not isinstance(pass_cond.get("goodCountAtLeast"), list)
        elif pass_cond.get("okCountLessThan") is not None:
            kind = "ok"
            current = counts["ok"]
            pass_target = derived["pass_ok"][idx]
            gold_target = derived["gold_ok"][idx]
            estimated = not isinstance(pass_cond.get("okCountLessThan"), list)
        elif pass_cond.get("hitCountAtLeast") is not None:
            kind = "hit"
            current = counts["hit"]
            pass_target = derived["pass_hit"][idx]
            gold_target = derived["gold_hit"][idx]
            estimated = not isinstance(pass_cond.get("hitCountAtLeast"), list)
        else:
            kind = "rate"
            current = accuracy
            pass_target = derived["pass_rate"][idx]
            gold_target = derived["gold_rate"][idx]
            estimated = False
        return {
            "kind": kind,
            "current": current,
            "passTarget": pass_target,
            "goldTarget": gold_target,
            "icon": self._metric_icon_index(
                kind, current, pass_target, gold_target, full_combo, all_good
            ),
            "ratio": self._metric_ratio(kind, current, pass_target),
            "estimated": estimated,
            "comparable": True,
        }

    def _build_song_runtime(
        self,
        grade: Dict[str, Any],
        best_map: Dict[Tuple[int, int], Dict[str, Any]],
        derived: Optional[Dict[str, Any]] = None,
        user_scores: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        derived = derived or self._derive_song_targets(grade, user_scores)
        pass_cond = grade["conditions"]["pass"]
        songs_runtime: List[Dict[str, Any]] = []
        totals = {
            "noteCount": 0,
            "good": 0,
            "ok": 0,
            "bad": 0,
            "drumroll": 0,
            "hit": 0,
            "score": 0,
            "soulGaugeTotal": None,
        }
        for idx, song in enumerate(grade["songs"]):
            entry = self._resolve_song_entry(song, best_map)
            counts = self._entry_counts(entry)
            note_count = derived["notes"][idx]
            formula = derived["formulas"][idx]
            accuracy = self._accuracy_percent(counts, note_count, formula)
            full_combo = entry is not None and self._full_combo(counts)
            all_good = entry is not None and self._all_good(counts, note_count)
            pass_rate = derived["pass_rate"][idx]
            gold_rate = derived["gold_rate"][idx]
            pass_bad = derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
            gold_bad = derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
            pass_drumroll = (
                derived["pass_drumroll"][idx]
                if idx < len(derived["pass_drumroll"])
                else 0
            )
            gold_drumroll = (
                derived["gold_drumroll"][idx]
                if idx < len(derived["gold_drumroll"])
                else 0
            )
            miss_comparable = bool(derived["has_bad_target"])
            drumroll_comparable = bool(derived["has_drumroll_target"])
            if entry is None:
                primary_metric = {
                    "kind": (
                        "ok"
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            "good"
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                "hit"
                                if pass_cond.get("hitCountAtLeast") is not None
                                else "rate"
                            )
                        )
                    ),
                    "current": 0,
                    "passTarget": (
                        derived["pass_ok"][idx]
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            derived["pass_good"][idx]
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                derived["pass_hit"][idx]
                                if pass_cond.get("hitCountAtLeast") is not None
                                else derived["pass_rate"][idx]
                            )
                        )
                    ),
                    "goldTarget": (
                        derived["gold_ok"][idx]
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            derived["gold_good"][idx]
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                derived["gold_hit"][idx]
                                if pass_cond.get("hitCountAtLeast") is not None
                                else derived["gold_rate"][idx]
                            )
                        )
                    ),
                    "icon": 1,
                    "ratio": 0.0,
                    "estimated": pass_cond.get("okCountLessThan") is not None
                    and (not isinstance(pass_cond.get("okCountLessThan"), list))
                    or (
                        pass_cond.get("goodCountAtLeast") is not None
                        and (not isinstance(pass_cond.get("goodCountAtLeast"), list))
                    )
                    or (
                        pass_cond.get("hitCountAtLeast") is not None
                        and (not isinstance(pass_cond.get("hitCountAtLeast"), list))
                    ),
                    "comparable": True,
                }
                miss_icon = 1
                drumroll_icon = 3 if pass_drumroll <= 0 else 1
                status_text = (
                    "未收录" if _safe_int(song.get("id"), -1) <= 0 else "未游玩"
                )
            else:
                primary_metric = self._build_primary_metric(
                    grade, derived, idx, counts, accuracy, full_combo, all_good
                )
                miss_icon = self._best_tier(
                    self._metric_pass_bad(counts["bad"], pass_bad),
                    self._metric_pass_bad(counts["bad"], gold_bad),
                    full_combo,
                    all_good,
                )
                if pass_drumroll <= 0:
                    drumroll_icon = 3
                else:
                    drumroll_icon = self._best_tier(
                        self._metric_pass(counts["drumroll"], pass_drumroll),
                        self._metric_pass(counts["drumroll"], gold_drumroll),
                        full_combo,
                        all_good,
                    )
                status_text = ""
            runtime = {
                "index": idx + 1,
                "song": song,
                "entry": entry,
                "counts": counts,
                "noteCount": note_count,
                "formula": formula,
                "accuracyPercent": accuracy,
                "primaryMetric": primary_metric,
                "missIcon": miss_icon,
                "passRateTarget": pass_rate,
                "goldRateTarget": gold_rate,
                "passBadTarget": pass_bad,
                "goldBadTarget": gold_bad,
                "passDrumrollTarget": pass_drumroll,
                "goldDrumrollTarget": gold_drumroll,
                "drumrollIcon": drumroll_icon,
                "missComparable": miss_comparable,
                "drumrollComparable": drumroll_comparable,
                "missEstimated": not bool(derived["bad_per_song"]),
                "drumrollEstimated": not bool(derived["drumroll_per_song"]),
                "statusText": status_text,
            }
            songs_runtime.append(runtime)
            totals["noteCount"] += note_count
            totals["good"] += counts["good"]
            totals["ok"] += counts["ok"]
            totals["bad"] += counts["bad"]
            totals["drumroll"] += counts["drumroll"]
            totals["hit"] += counts["hit"]
            totals["score"] += counts["score"]
        totals["allFullCombo"] = all(
            (
                item["entry"] is not None and self._full_combo(item["counts"])
                for item in songs_runtime
            )
        )
        totals["allAllGood"] = all(
            (
                item["entry"] is not None
                and self._all_good(item["counts"], item["noteCount"])
                for item in songs_runtime
            )
        )
        totals["accuracyPercent"] = 0.0
        if totals["noteCount"] > 0:
            formulas = {item["formula"] for item in songs_runtime}
            footer_formula = FORMULA_GOOD if FORMULA_GOOD in formulas else FORMULA_OK
            totals["accuracyPercent"] = self._accuracy_percent(
                {
                    "good": totals["good"],
                    "ok": totals["ok"],
                    "bad": totals["bad"],
                    "drumroll": totals["drumroll"],
                    "score": totals["score"],
                },
                totals["noteCount"],
                footer_formula,
            )
            totals["formula"] = footer_formula
        else:
            totals["formula"] = FORMULA_GOOD
        totals["derived"] = derived
        return (songs_runtime, totals)

    def _footer_rows(
        self,
        grade: Dict[str, Any],
        songs_runtime: List[Dict[str, Any]],
        totals: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        pass_cond = grade["conditions"]["pass"]
        gold_cond = self._resolved_gold_conditions(grade)
        derived = totals["derived"]
        rows: List[Dict[str, Any]] = []
        full_combo = bool(totals["allFullCombo"])
        all_good = bool(totals["allAllGood"])

        def segment_value_text(
            kind: str,
            song_runtime: Dict[str, Any],
            current: float | int,
            target: float | int,
        ) -> str:
            if kind == "drumroll" and float(target) <= 0:
                return "0/0"
            if song_runtime["entry"] is None:
                if kind == "rate":
                    return f"--/{float(target):.2f}%"
                if target:
                    return f"--/{int(target)}"
                return "--"
            if kind == "rate":
                return f"{float(current):.2f}%/{float(target):.2f}%"
            if target:
                return f"{int(current)}/{int(target)}"
            return str(int(current))

        def build_row(
            kind: str,
            label: str,
            current: float | int,
            pass_value: float | int,
            gold_value: float | int,
            pass_ok: bool,
            gold_ok: bool,
            segmented: bool = False,
            current_segments: Optional[List[float | int]] = None,
            pass_segments: Optional[List[float | int]] = None,
            gold_segments: Optional[List[float | int]] = None,
            segment_texts: Optional[List[str]] = None,
        ) -> Dict[str, Any]:
            icon_index = self._best_tier(pass_ok, gold_ok, full_combo, all_good)
            if kind in {"bad", "ok"}:
                if not pass_value:
                    ratio = 0.0
                elif current <= pass_value:
                    ratio = 1.0
                else:
                    ratio = max(0.0, min(1.0, float(pass_value) / float(current)))
            else:
                ratio = (
                    0.0
                    if not pass_value
                    else max(0.0, min(1.0, float(current) / float(pass_value)))
                )
            segment_ratios: List[float] = []
            segment_icons: List[int] = []
            if segmented and current_segments and pass_segments and gold_segments:
                for song_runtime, now, pval, gval in zip(
                    songs_runtime, current_segments, pass_segments, gold_segments
                ):
                    if kind == "drumroll" and pval <= 0:
                        seg_icon = 3
                        seg_ratio = 1.0
                    elif kind in {"bad", "ok"}:
                        song_pass = pval > 0 and now < pval
                        song_gold = gval > 0 and now < gval
                        if not pval:
                            seg_ratio = 0.0
                        elif now <= pval:
                            seg_ratio = 1.0
                        else:
                            seg_ratio = max(0.0, min(1.0, float(pval) / float(now)))
                        seg_icon = self._best_tier(
                            song_pass,
                            song_gold,
                            self._full_combo(song_runtime["counts"]),
                            self._all_good(
                                song_runtime["counts"], song_runtime["noteCount"]
                            ),
                        )
                    else:
                        song_pass = pval > 0 and now >= pval
                        song_gold = gval > 0 and now >= gval
                        seg_ratio = (
                            0.0
                            if not pval
                            else max(0.0, min(1.0, float(now) / float(pval)))
                        )
                        seg_icon = self._best_tier(
                            song_pass,
                            song_gold,
                            self._full_combo(song_runtime["counts"]),
                            self._all_good(
                                song_runtime["counts"], song_runtime["noteCount"]
                            ),
                        )
                    segment_ratios.append(seg_ratio)
                    segment_icons.append(seg_icon)
            return {
                "label": label,
                "kind": kind,
                "current": current,
                "pass": pass_value,
                "gold": gold_value,
                "ratio": ratio,
                "icon": icon_index,
                "segmented": segmented,
                "segmentRatios": segment_ratios,
                "segmentIcons": segment_icons,
                "segmentTexts": segment_texts or [],
            }

        soul_gauge = _safe_optional_int(totals.get("soulGaugeTotal"))
        if soul_gauge is not None and pass_cond.get("soulGaugePercent") is not None:
            pass_gauge = _safe_int(pass_cond.get("soulGaugePercent"))
            gold_gauge = _safe_int(gold_cond.get("soulGaugePercent"))
            rows.append(
                build_row(
                    "gauge",
                    "目标魂条",
                    soul_gauge,
                    pass_gauge,
                    gold_gauge,
                    self._metric_pass(soul_gauge, pass_gauge),
                    self._metric_pass(soul_gauge, gold_gauge),
                )
            )
        use_ok_count_footer = self._footer_uses_ok_count(grade)
        if use_ok_count_footer and pass_cond.get("okCountLessThan") is not None:
            ok_segmented = isinstance(pass_cond.get("okCountLessThan"), list)
            ok_current_segments = [
                song_runtime["counts"]["ok"] for song_runtime in songs_runtime
            ]
            ok_pass_value = (
                sum(derived["pass_ok"])
                if ok_segmented
                else _safe_int(pass_cond.get("okCountLessThan"))
            )
            ok_gold_value = (
                sum(derived["gold_ok"])
                if ok_segmented
                else _safe_int(gold_cond.get("okCountLessThan"))
            )
            ok_pass_status = (
                all(
                    (
                        self._metric_pass_bad(now, pval)
                        for now, pval in zip(ok_current_segments, derived["pass_ok"])
                    )
                )
                if ok_segmented
                else self._metric_pass_bad(totals["ok"], ok_pass_value)
            )
            ok_gold_status = (
                all(
                    (
                        self._metric_pass_bad(now, gval)
                        for now, gval in zip(ok_current_segments, derived["gold_ok"])
                    )
                )
                if ok_segmented
                else self._metric_pass_bad(totals["ok"], ok_gold_value)
            )
            rows.append(
                build_row(
                    "ok",
                    "目标可数",
                    totals["ok"],
                    ok_pass_value,
                    ok_gold_value,
                    ok_pass_status,
                    ok_gold_status,
                    segmented=ok_segmented,
                    current_segments=ok_current_segments,
                    pass_segments=derived["pass_ok"],
                    gold_segments=derived["gold_ok"],
                    segment_texts=(
                        [
                            segment_value_text("ok", song_runtime, current, target)
                            for song_runtime, current, target in zip(
                                songs_runtime, ok_current_segments, derived["pass_ok"]
                            )
                        ]
                        if ok_segmented
                        else None
                    ),
                )
            )
        else:
            has_rate_requirement = (
                pass_cond.get("goodCountAtLeast") is not None
                or pass_cond.get("okCountLessThan") is not None
            )
            if has_rate_requirement:
                total_rate_pass = self._rate_target_total(
                    totals["noteCount"], pass_cond, derived["notes"]
                )
                total_rate_gold = self._rate_target_total(
                    totals["noteCount"], gold_cond, derived["notes"]
                )
                rate_segmented = bool(derived.get("rate_per_song"))
                current_rate = float(totals["accuracyPercent"])
                rows.append(
                    build_row(
                        "rate",
                        "目标良率",
                        current_rate,
                        float(total_rate_pass),
                        float(total_rate_gold),
                        self._metric_pass(current_rate, float(total_rate_pass)),
                        self._metric_pass(current_rate, float(total_rate_gold)),
                        segmented=rate_segmented,
                        current_segments=[
                            float(item["accuracyPercent"]) for item in songs_runtime
                        ],
                        pass_segments=[float(item) for item in derived["pass_rate"]],
                        gold_segments=[float(item) for item in derived["gold_rate"]],
                    )
                )
        if pass_cond.get("hitCountAtLeast") is not None:
            rows.append(
                build_row(
                    "hit",
                    "目标击打数",
                    totals["hit"],
                    _safe_int(pass_cond.get("hitCountAtLeast")),
                    _safe_int(gold_cond.get("hitCountAtLeast")),
                    self._metric_pass(
                        totals["hit"], _safe_int(pass_cond.get("hitCountAtLeast"))
                    ),
                    self._metric_pass(
                        totals["hit"], _safe_int(gold_cond.get("hitCountAtLeast"))
                    ),
                )
            )
        if pass_cond.get("badCountLessThan") is not None:
            rows.append(
                build_row(
                    "bad",
                    "目标不可",
                    totals["bad"],
                    _safe_int(pass_cond.get("badCountLessThan")),
                    _safe_int(gold_cond.get("badCountLessThan")),
                    self._metric_pass_bad(
                        totals["bad"], _safe_int(pass_cond.get("badCountLessThan"))
                    ),
                    self._metric_pass_bad(
                        totals["bad"], _safe_int(gold_cond.get("badCountLessThan"))
                    ),
                )
            )
        if pass_cond.get("drumrollCountAtLeast") is not None:
            drumroll_segmented = isinstance(pass_cond.get("drumrollCountAtLeast"), list)
            drumroll_current_segments = [
                song_runtime["counts"]["drumroll"] for song_runtime in songs_runtime
            ]
            drumroll_pass_segments = derived["pass_drumroll"]
            drumroll_gold_segments = derived["gold_drumroll"]
            rows.append(
                build_row(
                    "drumroll",
                    "目标连打",
                    totals["drumroll"],
                    (
                        sum(derived["pass_drumroll"])
                        if drumroll_segmented
                        else _safe_int(pass_cond.get("drumrollCountAtLeast"))
                    ),
                    (
                        sum(derived["gold_drumroll"])
                        if drumroll_segmented
                        else _safe_int(gold_cond.get("drumrollCountAtLeast"))
                    ),
                    self._metric_pass(
                        totals["drumroll"],
                        (
                            sum(derived["pass_drumroll"])
                            if drumroll_segmented
                            else _safe_int(pass_cond.get("drumrollCountAtLeast"))
                        ),
                    ),
                    self._metric_pass(
                        totals["drumroll"],
                        (
                            sum(derived["gold_drumroll"])
                            if drumroll_segmented
                            else _safe_int(gold_cond.get("drumrollCountAtLeast"))
                        ),
                    ),
                    segmented=drumroll_segmented,
                    current_segments=drumroll_current_segments,
                    pass_segments=drumroll_pass_segments,
                    gold_segments=drumroll_gold_segments,
                    segment_texts=(
                        [
                            segment_value_text(
                                "drumroll", song_runtime, current, target
                            )
                            for song_runtime, current, target in zip(
                                songs_runtime,
                                drumroll_current_segments,
                                drumroll_pass_segments,
                            )
                        ]
                        if drumroll_segmented
                        else None
                    ),
                )
            )
        return rows

    def _build_dojo_counts(
        self, note_count: int, highscore: Dict[str, Any], odaibest: Dict[str, Any]
    ) -> Dict[str, int]:
        good = _safe_optional_int(highscore.get("good"))
        ok = _safe_optional_int(highscore.get("ok"))
        bad = _safe_optional_int(highscore.get("bad"))
        drumroll = _safe_optional_int(highscore.get("drumroll"))
        hit = _safe_optional_int(highscore.get("hit"))
        if good is None and (ok is not None or bad is not None):
            good = max(0, note_count - _safe_int(ok, 0) - _safe_int(bad, 0))
        if hit is None:
            hit = _safe_int(good, 0) + _safe_int(ok, 0) + _safe_int(drumroll, 0)
        score = _safe_optional_int(highscore.get("score"))
        combo = _safe_optional_int(highscore.get("combo"))
        return {
            "score": _safe_int(score, 0),
            "good": _safe_int(good, 0),
            "ok": _safe_int(ok, 0),
            "bad": _safe_int(bad, 0),
            "drumroll": _safe_int(drumroll, 0),
            "hit": _safe_int(hit, 0),
            "combo": _safe_int(combo, 0),
        }

    def _build_dojo_runtime(
        self,
        grade: Dict[str, Any],
        dojo_entry: Optional[Dict[str, Any]],
        derived: Optional[Dict[str, Any]] = None,
        user_scores: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        derived = derived or self._derive_song_targets(grade, user_scores)
        pass_cond = grade["conditions"]["pass"]
        songs_runtime: List[Dict[str, Any]] = []
        totals = {
            "noteCount": 0,
            "good": 0,
            "ok": 0,
            "bad": 0,
            "drumroll": 0,
            "hit": 0,
            "score": 0,
            "levelIcon": _safe_int((dojo_entry or {}).get("level_icon"), 1),
            "soulGaugeTotal": _safe_optional_int(
                (dojo_entry or {}).get("highscore_soul_gauge_total")
            ),
        }
        arrival_song_cnt = _safe_int((dojo_entry or {}).get("arrival_song_cnt"), 0)
        dojo_songs = (dojo_entry or {}).get("songs") or []
        for idx, song in enumerate(grade["songs"]):
            note_count = derived["notes"][idx]
            formula = derived["formulas"][idx]
            song_info = (
                dojo_songs[idx]
                if idx < len(dojo_songs) and isinstance(dojo_songs[idx], dict)
                else None
            )
            reached = bool(song_info and song_info.get("reached"))
            if reached:
                highscore = song_info.get("highscore") or {}
                odaibest = song_info.get("odaibest") or {}
                counts = self._build_dojo_counts(note_count, highscore, odaibest)
                accuracy = self._accuracy_percent(counts, note_count, formula)
                full_combo = self._full_combo(counts)
                all_good = self._all_good(counts, note_count)
                pass_rate = derived["pass_rate"][idx]
                gold_rate = derived["gold_rate"][idx]
                pass_bad = (
                    derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
                )
                gold_bad = (
                    derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
                )
                pass_drumroll = (
                    derived["pass_drumroll"][idx]
                    if idx < len(derived["pass_drumroll"])
                    else 0
                )
                gold_drumroll = (
                    derived["gold_drumroll"][idx]
                    if idx < len(derived["gold_drumroll"])
                    else 0
                )
                miss_comparable = bool(derived["has_bad_target"])
                drumroll_comparable = bool(derived["has_drumroll_target"])
                primary_metric = self._build_primary_metric(
                    grade, derived, idx, counts, accuracy, full_combo, all_good
                )
                miss_icon = self._best_tier(
                    self._metric_pass_bad(counts["bad"], pass_bad),
                    self._metric_pass_bad(counts["bad"], gold_bad),
                    full_combo,
                    all_good,
                )
                if pass_drumroll <= 0:
                    drumroll_icon = 3
                else:
                    drumroll_icon = self._best_tier(
                        self._metric_pass(counts["drumroll"], pass_drumroll),
                        self._metric_pass(counts["drumroll"], gold_drumroll),
                        full_combo,
                        all_good,
                    )
                entry: Optional[Dict[str, Any]] = song_info
                status_text = ""
                totals["noteCount"] += note_count
                totals["good"] += counts["good"]
                totals["ok"] += counts["ok"]
                totals["bad"] += counts["bad"]
                totals["drumroll"] += counts["drumroll"]
                totals["hit"] += counts["hit"]
                totals["score"] += counts["score"]
            else:
                counts = {
                    "score": 0,
                    "good": 0,
                    "ok": 0,
                    "bad": 0,
                    "drumroll": 0,
                    "hit": 0,
                    "combo": 0,
                }
                accuracy = 0.0
                pass_rate = derived["pass_rate"][idx]
                gold_rate = derived["gold_rate"][idx]
                pass_bad = (
                    derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
                )
                gold_bad = (
                    derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
                )
                pass_drumroll = (
                    derived["pass_drumroll"][idx]
                    if idx < len(derived["pass_drumroll"])
                    else 0
                )
                gold_drumroll = (
                    derived["gold_drumroll"][idx]
                    if idx < len(derived["gold_drumroll"])
                    else 0
                )
                miss_comparable = bool(derived["has_bad_target"])
                drumroll_comparable = bool(derived["has_drumroll_target"])
                primary_metric = {
                    "kind": (
                        "ok"
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            "good"
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                "hit"
                                if pass_cond.get("hitCountAtLeast") is not None
                                else "rate"
                            )
                        )
                    ),
                    "current": 0,
                    "passTarget": (
                        derived["pass_ok"][idx]
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            derived["pass_good"][idx]
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                derived["pass_hit"][idx]
                                if pass_cond.get("hitCountAtLeast") is not None
                                else derived["pass_rate"][idx]
                            )
                        )
                    ),
                    "goldTarget": (
                        derived["gold_ok"][idx]
                        if pass_cond.get("okCountLessThan") is not None
                        else (
                            derived["gold_good"][idx]
                            if pass_cond.get("goodCountAtLeast") is not None
                            else (
                                derived["gold_hit"][idx]
                                if pass_cond.get("hitCountAtLeast") is not None
                                else derived["gold_rate"][idx]
                            )
                        )
                    ),
                    "icon": 1,
                    "ratio": 0.0,
                    "estimated": pass_cond.get("okCountLessThan") is not None
                    and (not isinstance(pass_cond.get("okCountLessThan"), list))
                    or (
                        pass_cond.get("goodCountAtLeast") is not None
                        and (not isinstance(pass_cond.get("goodCountAtLeast"), list))
                    )
                    or (
                        pass_cond.get("hitCountAtLeast") is not None
                        and (not isinstance(pass_cond.get("hitCountAtLeast"), list))
                    ),
                    "comparable": True,
                }
                miss_icon = 1
                drumroll_icon = 3 if pass_drumroll <= 0 else 1
                entry = None
                status_text = (
                    "未到达"
                    if arrival_song_cnt > 0 and idx + 1 > arrival_song_cnt
                    else "未游玩"
                )
            songs_runtime.append(
                {
                    "index": idx + 1,
                    "song": song,
                    "entry": entry,
                    "counts": counts,
                    "noteCount": note_count,
                    "formula": formula,
                    "accuracyPercent": accuracy,
                    "primaryMetric": primary_metric,
                    "missIcon": miss_icon,
                    "passRateTarget": pass_rate,
                    "goldRateTarget": gold_rate,
                    "passBadTarget": pass_bad,
                    "goldBadTarget": gold_bad,
                    "passDrumrollTarget": pass_drumroll,
                    "goldDrumrollTarget": gold_drumroll,
                    "drumrollIcon": drumroll_icon,
                    "missComparable": miss_comparable,
                    "drumrollComparable": drumroll_comparable,
                    "missEstimated": not bool(derived["bad_per_song"]),
                    "drumrollEstimated": not bool(derived["drumroll_per_song"]),
                    "statusText": status_text,
                }
            )
        totals["allFullCombo"] = all(
            (
                item["entry"] is not None and self._full_combo(item["counts"])
                for item in songs_runtime
            )
        )
        totals["allAllGood"] = all(
            (
                item["entry"] is not None
                and self._all_good(item["counts"], item["noteCount"])
                for item in songs_runtime
            )
        )
        totals["accuracyPercent"] = 0.0
        if totals["noteCount"] > 0:
            formulas = {item["formula"] for item in songs_runtime}
            footer_formula = FORMULA_GOOD if FORMULA_GOOD in formulas else FORMULA_OK
            totals["accuracyPercent"] = self._accuracy_percent(
                {
                    "good": totals["good"],
                    "ok": totals["ok"],
                    "bad": totals["bad"],
                    "drumroll": totals["drumroll"],
                    "score": totals["score"],
                },
                totals["noteCount"],
                footer_formula,
            )
            totals["formula"] = footer_formula
        else:
            totals["formula"] = FORMULA_GOOD
        totals["derived"] = derived
        return (songs_runtime, totals)

    def prepare(
        self,
        user_id: int,
        grade_name: str,
        *,
        userdata: dict | None,
        dojo_payload: dict,
        dan_id: int | None,
        version: str = CURRENT_DANI_VERSION,
        explicit_version: bool = False,
    ) -> DaniProgress:
        """Build display data from an already authorized snapshot and prepared dojo input."""
        version = str(version or CURRENT_DANI_VERSION)
        try:
            grade = self._load_grade_index(version).get(str(grade_name).strip())
        except KeyError:
            return DaniProgress(
                notice=f"仅支持虹{min(SUPPORTED_DANI_VERSIONS)}-{max(SUPPORTED_DANI_VERSIONS)}段位进度。"
            )
        if not grade:
            return DaniProgress(notice="未找到对应段位。")
        if userdata is None:
            return DaniProgress(notice=f"未找到用户 {user_id} 的成绩文件。")
        canonical = str(grade["grade"])
        user_scores = userdata.get("songs", [])
        derived = self._derive_song_targets(grade, user_scores)
        best_map = self._build_best_entry_map(user_scores)
        songs, totals = self._build_song_runtime(
            grade, best_map, derived=derived, user_scores=user_scores
        )
        if not songs:
            return DaniProgress(notice="该段位暂无可用课题曲数据。")
        footer = self._footer_rows(grade, songs, totals)
        title = (
            f"虹{version}{canonical}进度"
            if version != CURRENT_DANI_VERSION or explicit_version
            else f"{canonical}进度"
        )
        sections = [DaniSection(title, songs, footer)]
        if version in {CURRENT_DANI_VERSION, DOJO_DATA_VERSION}:
            dojo_map = build_dojo_score_map(dojo_payload, grade_names={})
            entry = dojo_map.get(dan_id or -1)
            dojo_songs, dojo_totals = self._build_dojo_runtime(
                grade, entry, derived=derived, user_scores=user_scores
            )
            dojo_footer = self._footer_rows(grade, dojo_songs, dojo_totals)
            if version != DOJO_DATA_VERSION:
                for runtime in dojo_songs:
                    runtime["statusText"] = "暂无数据"
                for row in dojo_footer:
                    row.update(unavailable=True, icon=1, ratio=0.0, segmented=False)
            title_icon = _safe_int((entry or {}).get("level_icon"), 0)
            if (
                title_icon <= 0
                and dan_id
                and 0 < dan_id <= len(dojo_payload.get("levelList") or [])
            ):
                title_icon = level_mark_to_icon(
                    (dojo_payload.get("levelList") or [])[dan_id - 1]
                )
            dojo_title = (
                f"{canonical}进度（段位内，暂无本版本数据）"
                if version != DOJO_DATA_VERSION
                else f"虹{version}{canonical}进度（段位内）"
            )
            sections.append(
                DaniSection(dojo_title, dojo_songs, dojo_footer, title_icon)
            )
        for section in sections:
            for runtime in section.songs:
                runtime["star"] = self._resolve_song_star(runtime["song"])
        return DaniProgress(grade, derived, tuple(sections))
