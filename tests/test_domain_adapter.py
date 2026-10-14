from taiko_bot.runtime.player.client.recommendation_support import target_recommend
"""Host regression checks: dependency versions, lazy inputs and legacy shapes."""
from dataclasses import asdict
from datetime import datetime as RealDatetime
import pytest
from taiko_bot import domain
from plugins.utils import dojo_score, taikob_v2, score_calculator
from taiko_bot.runtime.player.client.progress_support import progress_catalog
from plugins.utils.hiroba import parser, normalize

def unavailable(*args, **kwargs):
    raise AssertionError('this operation must not read unrelated catalog inputs')

def test_domain_client_versions_and_public_models_are_core_owned(monkeypatch):
    domain.assert_domain_versions()
    for model in (parser.HirobaProfile, parser.HirobaSongRef, parser.HirobaScoreDetail,
                  taikob_v2.V2SongData, taikob_v2.V2RatingResult, score_calculator.SongStats):
        assert model.__module__.startswith('sakura_taiko_core.')
    assert asdict(parser.HirobaProfile('synthetic')) == {'taiko_no':'synthetic','nickname':'','title':''}
    assert asdict(parser.HirobaSongRef('2','Title')) == {'song_no':'2','title':'Title','levels':set()}
    monkeypatch.setattr(domain, 'version', lambda package: '0.0.0')
    with pytest.raises(RuntimeError, match='version mismatch'):
        domain.assert_domain_versions()

def test_star_queries_do_not_require_rating_or_static_dataset(monkeypatch):
    monkeypatch.setattr(progress_catalog, 'load_song_index', lambda: {2:{'id':2,'song_name':'Sample','level_4':'9','sort':1}})
    monkeypatch.setattr(progress_catalog, 'load_active_song_ids', lambda:{2})
    monkeypatch.setattr(progress_catalog, '_load_rating_entries', unavailable)
    monkeypatch.setattr(progress_catalog, '_load_static_progress_map', unavailable)
    assert [asdict(item) for item in progress_catalog.query_progress_items_by_star(9)] == [{'song_id':2,'level':4,'title':'Sample'}]

def test_empty_recommendations_do_not_load_chart_or_rating_data(monkeypatch):
    monkeypatch.setattr(domain, 'identity_inputs', unavailable)
    monkeypatch.setattr(target_recommend, '_build_user_profile', unavailable)
    monkeypatch.setattr(target_recommend, '_load_scoreline_rows', unavailable)
    result=target_recommend.compute_target_recommendations_from_userdata({'songs':[]},'ziya')
    assert result.rows == [] and result.candidate_count == 0
    assert result.message == '暂无可用成绩数据，请先更新后再试。'

def test_dojo_missing_fields_and_zero_remain_distinct(monkeypatch):
    monkeypatch.setattr(dojo_score, 'load_grade_name_map', lambda:{1:'初段'})
    payload={'ary_player_dan_score':[{'dan_id':1,'highscore_good_cnt_1':0}]}
    result=dojo_score.build_dojo_score_map(payload)[1]
    assert result['songs'][0]['highscore']['good'] == 0
    assert result['songs'][0]['highscore']['ok'] is None
    monkeypatch.setattr(dojo_score, 'load_grade_name_map', unavailable)
    assert dojo_score.normalize_dojo_scores(None) == {'scores':[],'levelList':[]}
    assert dojo_score.build_dojo_score_map({'scores':[{'dan_id':1}]}) == {1:{'dan_id':1}}

def test_hiroba_record_uses_host_clock_with_legacy_output(monkeypatch):
    class FixedDatetime:
        @staticmethod
        def now():return RealDatetime(2026,1,2,3,4,5)
    monkeypatch.setattr(normalize,'datetime',FixedDatetime)
    detail=parser.HirobaScoreDetail('2',4,score=950000,badge='pink')
    record=normalize.score_detail_to_userdata_record(detail)
    assert record['highscore_datetime'] == record['update_datetime'] == '2026-01-02 03:04:05'
    assert record['best_score_rank'] == 6 and record['high_score'] == 950000
    assert normalize.build_userdata(parser.HirobaProfile('synthetic'),[detail])['songs'] == [record]
