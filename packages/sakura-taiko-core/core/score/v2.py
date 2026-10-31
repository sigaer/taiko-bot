"""Versioned record policies feeding one shared v2 calculation kernel."""
from dataclasses import replace
from typing import Any, Mapping, Callable
from ..models.calculation import V2SongData, V2RatingResult
from ..rating.v2 import _safe_int, _calculate_v2_from_chart, DONDARU_EXCEPTIONS
from ..chart.catalog import _get_recommend_identity_key

PROFILES = frozenset({'v2-center-20261010','v2-client-20261010'})

def result_from_entry(entry: dict[str, Any], song_map: Mapping[tuple[int,int],V2SongData], *, profile: str,
                      calculate: Callable[..., V2RatingResult] | None = None) -> V2RatingResult | None:
    if profile not in PROFILES:
        raise ValueError('unknown v2 algorithm profile')
    center = profile == 'v2-center-20261010'
    if center:
        try:
            song_id=int(entry.get('song_no',0)); level=int(entry.get('level',0))
        except Exception:
            return None
    else:
        song_id=_safe_int(entry.get('song_no')); level=_safe_int(entry.get('level'))
    chart=song_map.get((song_id,level))
    if chart is None or (center and chart.total_notes <= 0):
        return None
    great=_safe_int(entry.get('good_cnt'));good=_safe_int(entry.get('ok_cnt'));bad=_safe_int(entry.get('ng_cnt'))
    is_dondaful=(int(entry.get('dondaful_combo_cnt',0) or 0)>0 and (song_id,level) not in DONDARU_EXCEPTIONS) if center else _safe_int(entry.get('dondaful_combo_cnt'))>0
    if is_dondaful:
        accuracy=1.0; bad_rate=0.0
    else:
        if center and great+good+bad>chart.total_notes:
            return None
        notes=max(chart.total_notes,1)
        accuracy=(great+good*0.5)/notes
        if center and accuracy<0.75:
            return None
        bad_rate=bad/notes
    # A host may memoize the same profile's pure kernel. Cache ownership stays
    # outside Core; the default path remains fully value-based.
    result=calculate(chart,accuracy_per=accuracy,bad_per=bad_rate) if calculate else _calculate_v2_from_chart(chart,accuracy_per=accuracy,bad_per=bad_rate,profile=profile)
    return replace(result,high_score=_safe_int(entry.get('high_score')))

def compute_all_v2_from_userdata_records(records: list[dict[str,Any]], *, song_map: Mapping[tuple[int,int],V2SongData],
                                       profile: str, default_ids: Mapping[int,int] | None = None,
                                       calculate: Callable[..., V2RatingResult] | None = None) -> list[V2RatingResult]:
    if profile not in PROFILES:
        raise ValueError('unknown v2 algorithm profile')
    deduped={}
    for entry in records:
        result=result_from_entry(entry,song_map,profile=profile,calculate=calculate)
        if result is None or result.level<3 or result.AI_rating<=0:
            continue
        identity=_get_recommend_identity_key(int(result.song_id),int(result.level),default_ids)
        current=deduped.get(identity)
        if current is None or (float(result.AI_rating),int(result.high_score))>(float(current.AI_rating),int(current.high_score)):
            deduped[identity]=result
    return list(deduped.values())
