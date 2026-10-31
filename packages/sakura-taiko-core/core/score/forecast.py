from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

FORECAST_ATTEMPTS = 3
PB_SINGLE_ATTEMPT_PROBABILITY = 1.0 - 0.5 ** (1.0 / FORECAST_ATTEMPTS)
_PB_LOGIT_DISTANCE = math.log((1.0 - PB_SINGLE_ATTEMPT_PROBABILITY) / PB_SINGLE_ATTEMPT_PROBABILITY)

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

def _sigmoid_survival(score: float, center: float, scale: float) -> float:
    x = _clamp((float(score) - float(center)) / max(1.0, float(scale)), -40.0, 40.0)
    return 1.0 / (1.0 + math.exp(x))

def probability_with_attempts(single_attempt_probability: float, attempts: int) -> float:
    probability = _clamp(single_attempt_probability, 0.0, 1.0)
    return 1.0 - (1.0 - probability) ** max(1, int(attempts))

def _apply_objective_pressure(probability: float, objective_load: float) -> float:
    """Preserve the stable/PB anchors while separating saturated easy targets."""
    probability = _clamp(probability, 0.0, 1.0)
    pressure = math.exp(-0.35 * max(0.0, float(objective_load)))
    stable_anchor = probability_with_attempts(0.5, FORECAST_ATTEMPTS)
    pb_anchor = 0.5
    if probability >= stable_anchor:
        return stable_anchor + (probability - stable_anchor) * pressure
    if probability >= pb_anchor:
        return pb_anchor + (probability - pb_anchor) * pressure
    return probability * math.exp(-0.2 * max(0.0, float(objective_load)))

@dataclass(frozen=True)
class ChartPerformanceForecast:
    """One monotonic score-survival curve shared by score estimates and targets."""
    song_id: int
    level: int
    stable_score: int
    pb_score: int
    score_ceiling: int
    confidence: float
    data_sufficiency: str
    objective_load: float = 0.0

    @property
    def is_hard_mismatch(self) -> bool:
        return self.data_sufficiency != 'ok' or self.stable_score <= 0

    @property
    def score_scale(self) -> float:
        gap = max(0.0, float(self.pb_score - self.stable_score))
        if gap > 0:
            return max(1.0, gap / _PB_LOGIT_DISTANCE)
        return max(8000.0, float(self.score_ceiling) * 0.012)

    def single_attempt_probability(self, target_score: int) -> float:
        if self.is_hard_mismatch or target_score <= 0:
            return 0.0
        if self.score_ceiling > 0 and target_score > self.score_ceiling:
            return 0.0
        return _sigmoid_survival(target_score, self.stable_score, self.score_scale)

    def reach_probability(self, target_score: int, *, attempts: int=FORECAST_ATTEMPTS, current_score: Optional[int]=None, record_freshness: float=0.0, objective_load: Optional[float]=None) -> float:
        single = self.single_attempt_probability(target_score)
        probability = probability_with_attempts(single, attempts)
        probability = _apply_objective_pressure(probability, self.objective_load if objective_load is None else objective_load)
        if current_score is None or current_score >= target_score:
            return probability
        evidence = _sigmoid_survival(target_score, float(current_score), self.score_scale * 1.5)
        delta = _clamp(evidence - probability, -0.12, 0.05)
        strength = 0.35 * _clamp(record_freshness, 0.0, 1.0)
        return _clamp(probability + strength * delta, 0.0, 1.0)

def build_chart_performance_forecast(*, song_id: int, level: int, stable_score: Optional[int], pb_score: Optional[int], score_ceiling: int, reliability: float, data_sufficiency: str, objective_load: float=0.0) -> ChartPerformanceForecast:
    stable = max(0, int(stable_score or 0))
    pb = max(stable, int(pb_score or stable))
    return ChartPerformanceForecast(song_id=int(song_id), level=int(level), stable_score=stable, pb_score=pb, score_ceiling=max(0, int(score_ceiling)), confidence=_clamp(float(reliability) / 100.0, 0.0, 1.0), data_sufficiency=str(data_sufficiency or 'insufficient_data'), objective_load=max(0.0, float(objective_load)))
