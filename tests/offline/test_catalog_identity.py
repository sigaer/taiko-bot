from copy import deepcopy
import json
import pytest

from taiko_bot.catalog_identity import identity_map, normalize_score_payload
from taiko_bot.offline.catalog_reconcile import reconcile_catalog
from taiko_bot.offline.catalog_references import migrate_references
from taiko_bot.offline.ourtaiko_catalog import merge_catalog


def test_score_identity_preserves_raw_and_keeps_best_real_attempt():
    payload = {'songs': [{'song_no':100138,'level':4,'high_score':90,'play_cnt':8},
                         {'song_no':1530,'level':4,'high_score':100,'play_cnt':2},
                         {'song_no':100138,'level':5,'high_score':70}],
               'songs_removed': [[100138,3], {'song_no':100138,'level':2}, '100138:1']}
    raw = json.dumps(payload)
    result = normalize_score_payload(payload, {100138:1530})
    assert json.dumps(payload) == raw
    assert result['songs'] == [{'song_no':1530,'level':4,'high_score':100,'play_cnt':2},
                               {'song_no':1530,'level':5,'high_score':70}]
    assert result['songs_removed'] == [[1530,3],{'song_no':1530,'level':2},'1530:1']
    assert normalize_score_payload(result,{100138:1530}) is result


def test_unchanged_scores_keep_object_ownership_and_reject_identity_conflicts():
    payload = {'songs':[{'song_no':1,'level':4}]}
    assert normalize_score_payload(payload,{100138:1530}) is payload
    with pytest.raises(ValueError): identity_map([{'id':1,'legacy_ids':[2]},{'id':2}])
    with pytest.raises(ValueError): identity_map([{'id':1,'legacy_ids':[3]},{'id':2,'legacy_ids':[3]}])


def test_other_to_arcade_reconciliation_and_repeat_import():
    old = {'id':100138,'song_name_jp':'Nivalis*Anima','songNo':'temp_1','shelf_status':2,
           'level_1':'-','level_2':'-','level_3':'-','level_4':10,'level_5':'-', 'bpm':'180','tja_path':'game/niv.tja'}
    chart = {'id':'source','numberId':1,'nijiiroId':1530,'title':'Nivalis*Anima',
             'difficulties':[{'course':'Oni','level':10,'side':'single'}]}
    songs, assignments, _ = merge_catalog([old],[chart])
    next(s for s in songs if s['id']==1530)['tja_path']='game/niv.tja'
    frozen = deepcopy(songs)
    catalog, report = reconcile_catalog(songs,[chart],assignments,mainland_ids=set())
    assert songs == frozen and report['redirects']=={100138:1530}
    assert len(catalog)==1 and catalog[0]['shelf_status']==1 and catalog[0]['bpm']=='180'
    assert catalog[0]['legacy_ids']==[100138] and catalog[0]['wiki_song_nos']==['temp_1']
    assert 'songNo' not in catalog[0]
    assert reconcile_catalog(catalog,[chart],assignments,mainland_ids=set())[0]==catalog


def test_same_basename_different_resources_are_not_conflated():
    songs=[{'id':1,'tja_path':'game/love.tja'},{'id':100001,'tja_path':'pop/love.tja'},
           {'id':100002,'tja_path':'pop/love.tja'}]
    charts=[{'id':'game','nijiiroId':1},{'id':'pop','nijiiroId':None}]
    catalog,report=reconcile_catalog(songs,charts,{'game':1,'pop':100002},mainland_ids=set())
    assert report['redirects']=={100001:100002}
    assert {s['id'] for s in catalog}=={1,100002}


def test_arcade_removal_moves_source_identity_to_platform_namespace():
    old=[{'id':7,'shelf_status':1,'song_name':'Song','ourtaiko_ids':['source']}]
    charts=[{'id':'source','numberId':1,'nijiiroId':None,'title':'Song'}]
    songs,assignments,_=merge_catalog(old,charts)
    for s in songs: s['tja_path']='song.tja'
    catalog,report=reconcile_catalog(songs,charts,assignments,mainland_ids=set())
    assert len(catalog)==1 and catalog[0]['id']==100000 and catalog[0]['shelf_status']==2
    assert report['redirects']=={7:100000}


def test_other_id_allocator_never_reuses_merged_historical_ids():
    old=[{'id':1530,'shelf_status':1,'legacy_ids':[101999]}]
    songs,assignments,_=merge_catalog(old,[{'id':'new','numberId':1,'nijiiroId':None,'title':'New'}])
    assert assignments['new']==102000
    assert identity_map(songs)=={101999:1530}


def test_public_reference_migration_preserves_canonical_values_and_is_idempotent(tmp_path):
    songs=tmp_path/'songs'; songs.mkdir()
    payloads={'song_alias.json':[{'id':100138,'aliases':['niv']}],
              'song_score.json':[{'id':100138,'level':4,'score':3},{'id':1530,'level':4,'score':5}],
              'cn_song_positions.json':{'categories':{'1':{'ordered':[100138,1530],'pending':[100138]}}},
              'analyze_result_filtered.json':{'song_meta':{'niv@@100138':{'id':100138},'niv@@1530':{'id':1530}},
                  'by_bpm':{'180':['niv@@100138||Oni','niv@@1530||Oni']},'by_level':{},'by_tag':{}}}
    for name,value in payloads.items(): (songs/name).write_text(json.dumps(value))
    catalog=[{'id':1530,'legacy_ids':[100138],'shelf_status':1}]
    report=migrate_references(tmp_path,catalog,persist=False)
    assert len(report['updated'])==4
    assert json.loads((songs/'song_score.json').read_text())==payloads['song_score.json']
    migrate_references(tmp_path,catalog)
    assert json.loads((songs/'song_score.json').read_text())==[{'id':1530,'level':4,'score':5}]
    assert json.loads((songs/'cn_song_positions.json').read_text())['categories']['1']=={'ordered':[1530],'pending':[]}
    assert json.loads((songs/'analyze_result_filtered.json').read_text())['by_bpm']['180']==['niv@@1530||Oni']
    assert migrate_references(tmp_path,catalog)['updated']==[]


def test_wiki_outage_keeps_supplement_and_never_blocks_primary_catalog(tmp_path, monkeypatch):
    from taiko_bot.offline import song_update_task as task
    import requests
    path=tmp_path/'wiki.json'; cached=[{'songNo':'1540','title':'New song'}]
    path.write_text(json.dumps(cached))
    monkeypatch.setattr(task,'TAIKO_SONG_DATABASE_PATH',path)
    def fail(*args,**kwargs): raise requests.ConnectionError('offline')
    monkeypatch.setattr(task.requests,'get',fail)
    assert task._load_optional_wiki_database()==cached
    path.unlink()
    assert task._load_optional_wiki_database()==[]


def test_publication_decoding_resolves_ids_without_changing_verified_bytes(tmp_path):
    from taiko_store import PublicationStore
    from taiko_store.reader import score_read_view
    (tmp_path/'songs').mkdir()
    (tmp_path/'songs/song_data.json').write_text(json.dumps([{'id':1530,'legacy_ids':[100138]}]))
    root=tmp_path/'userdata'
    raw=b'{"songs":[{"song_no":100138,"level":4,"high_score":123}]}'
    store=PublicationStore(root,'synthetic')
    with store.exclusive():
        store.commit({'current':raw,'history/data_20261112_100000.json':raw})
        original=store.view()['commitId']
    with score_read_view(root,'synthetic') as view:
        assert view.current_raw()==raw
        assert view.decoded()['songs'][0]['song_no']==1530
        assert view.decoded('history/data_20261112_100000.json')['songs'][0]['song_no']==1530
        assert view.history_raw('data_20261112_100000.json')==raw
        assert view.publication['commitId']==original
