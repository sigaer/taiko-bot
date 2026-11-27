from copy import deepcopy
from pathlib import Path

from taiko_bot.offline.catalog_chart_policy import normalize_courses, single_profiles
from taiko_bot.offline.catalog_chart_sync import reconcile_charts
from taiko_bot.offline.ourtaiko_catalog import merge_catalog


def tja(path, *, level=8, notes='1234', course='Oni'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'TITLE:Test\nBPM:120\nWAVE:test.ogg\nCOURSE:{course}\nLEVEL:{level}\n#START\n{notes},\n#END\n')
    return path


def song(**fields):
    return {'id':7, 'song_name':'Test', 'shelf_status':1, 'level_4':8,
            'max_combo':['-']*3+[4,'-'], **fields}


def test_existing_song_gains_ura_without_changing_mainland_status():
    old = song(level_5='-')
    charts = [{'id':'a','nijiiroId':7,'title':'Test','difficulties':[
        {'course':'Oni','level':8,'side':'single'}, {'course':'Edit','level':10,'side':'single'}]}]
    result, _, _ = merge_catalog([old], charts)
    assert result[0]['level_5'] == 10
    assert result[0]['shelf_status'] == 1
    assert old.get('level_5') == '-'
    assert merge_catalog(result, charts)[0] == result


def test_master_branch_and_player_sides_are_unambiguous():
    text = '''BPM:120
COURSE:3
LEVEL:8
#START
1,
#BRANCHSTART p,50,80
#N
111111,
#E
1111,
#M
12,
#BRANCHEND
3,
#END
STYLE:Double
#START P1
11111111,
#END
#START P2
22222222,
#END
COURSE:4
LEVEL:10
#START
1234,
#END
'''
    parsed = single_profiles(text)
    assert parsed[4]['notes'] == 4  # M, not the longest branch and not P1/P2.
    assert parsed[5]['notes'] == 4
    assert 'COURSE:Oni' in normalize_courses(text)
    assert 'COURSE:Edit' in normalize_courses(text)


def test_latest_arcade_file_replaces_older_mapping_and_populates_easy(tmp_path):
    old = tja(tmp_path/'song/old.tja', notes='12')
    newest = tja(tmp_path/'song/new AC16.tja')
    with newest.open('a') as f:
        f.write('COURSE:0\nLEVEL:2\n#START\n111,\n#END\n')
    data = [song(tja_path='song/old.tja', level_1=2)]
    db = [{'songNo':'7','courses':{'oni':{'level':8,'maxCombo':4},'easy':{'level':2,'maxCombo':3}}}]
    mapping = {7:'song/old.tja'}
    result = reconcile_charts(data, database=db, root=tmp_path, ese_root=tmp_path, mapping=mapping)
    assert not result['issues']
    assert data[0]['tja_path'] == 'song/new AC16.tja'
    assert mapping[7] == 'song/new AC16.tja'
    assert data[0]['max_combo'][0] == 3
    assert data[0]['balloon_num'][0] == 0
    assert not reconcile_charts(data, database=db, root=tmp_path, ese_root=tmp_path, mapping=mapping)['changed']


def test_metadata_does_not_depend_on_missing_constants_and_recovers_zero_placeholder(tmp_path):
    tja(tmp_path/'test.tja', course='Easy', level=2, notes='1234')
    data = [song(tja_path='test.tja',level_1=2,level_4='-',max_combo=[0,'-','-','-','-'])]
    db = [{'songNo':'7','courses':{'easy':{'level':2,'maxCombo':0}}}]
    reconcile_charts(data, database=db, root=tmp_path, ese_root=tmp_path, mapping={})
    assert data[0]['max_combo'][0] == 4


def test_double_song_excluded_and_wiki_conflict_is_reported(tmp_path):
    tja(tmp_path/'test.tja', notes='12')
    data = [song(tja_path='test.tja'),song(id=8,song_name='【双打】 Test')]
    double = deepcopy(data[1])
    result = reconcile_charts(data, database=[{'songNo':'7','courses':{'oni':{'level':8,'maxCombo':4}}}], root=tmp_path, ese_root=tmp_path, mapping={})
    assert data[0]['max_combo'][3] == 4
    assert data[1] == double
    assert result['excludedDoubleSongs'] == 1
    assert result['issues'][0]['reason'] == 'latest_wiki_tja_conflict'


def test_star_reassessment_uses_latest_rating_with_same_notes(tmp_path):
    from taiko_bot.offline.catalog_chart_policy import canonical_single_text
    path=tja(tmp_path/'test.tja',level=9)
    data=[song(tja_path='test.tja')]
    db=[{'songNo':'7','courses':{'oni':{'level':8,'maxCombo':4}}}]
    report=reconcile_charts(data,database=db,root=tmp_path,ese_root=tmp_path,mapping={})
    assert not report['issues']
    assert data[0]['level_4']==8
    text=canonical_single_text(data[0],path.read_text())
    assert single_profiles(text)[4]['level']==8
    assert single_profiles(text)[4]['notes']==4


def test_image_refresh_queue_tracks_changed_courses_without_removing_old_image(tmp_path):
    import json
    from taiko_bot.offline.catalog_images import queue_chart_images,image_plan,REFRESH_PENDING
    path=tja(tmp_path/'test.tja')
    image=tmp_path/'assets/fumens/Oni/7.png';image.parent.mkdir(parents=True);image.write_bytes(b'old')
    data=[song(tja_path='test.tja')]
    queue_chart_images(tmp_path,{'changed':[{'id':7,'fields':{'level_4':{'before':9,'after':8}}}]})
    assert json.loads((tmp_path/REFRESH_PENDING).read_text())==['7:4']
    plan=image_plan(data,root=tmp_path,ese_root=tmp_path)
    assert len(plan['jobs'])==1 and plan['jobs'][0]['refresh']
    assert image.read_bytes()==b'old'


def test_wiki_branch_aggregate_does_not_override_master_notes(tmp_path):
    path=tja(tmp_path/'test.tja',notes='')
    path.write_text('BPM:120\nTITLE:Test\nCOURSE:Oni\nLEVEL:8\n#START\n#BRANCHSTART p,50,80\n#N\n111111,\n#E\n1111,\n#M\n12,\n#BRANCHEND\n#END\n')
    data=[song(tja_path='test.tja')]
    report=reconcile_charts(data,database=[{'songNo':'7','courses':{'oni':{'level':8,'maxCombo':6}}}],root=tmp_path,ese_root=tmp_path,mapping={})
    assert data[0]['max_combo'][3]==2
    assert not report['issues']


def test_repair_publish_rejects_concurrent_catalog_edit(tmp_path, monkeypatch):
    import json
    import pytest
    from taiko_bot.offline import catalog_repair as repair
    root=tmp_path/'root';stage=tmp_path/'stage'
    (root/'songs').mkdir(parents=True);stage.mkdir()
    path=root/'songs/song_data.json';path.write_text('old')
    (stage/'original.json').write_text(json.dumps({'song_data.json':repair.digest(path)}))
    path.write_text('concurrent edit')
    monkeypatch.setattr(repair,'FILES',('song_data.json',))
    with pytest.raises(ValueError,match='changed during staging'):
        repair.publish(root,stage)
    assert path.read_text()=='concurrent edit' and not (stage/'before').exists()


def test_zero_difficulty_is_absent_but_zero_note_chart_is_valid(tmp_path):
    tja(tmp_path/'test.tja',course='Easy',level=1,notes='0000')
    data=[song(tja_path='test.tja',level_1=1,level_4=0,level_5='0',max_combo=[0,'-','-','-','-'])]
    reconcile_charts(data,database=[],root=tmp_path,ese_root=tmp_path,mapping={})
    assert data[0]['level_4']==data[0]['level_5']=='-'
    assert data[0]['level_1']==1 and data[0]['max_combo'][0]==0
