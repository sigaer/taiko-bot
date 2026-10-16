"""Compare successful results to an external frozen Sakura source checkout.

TAIKO_FROZEN_BASELINE_ROOT contains import/path-only adapted 790c2c7 sources.
No production fixtures, network, credentials or error/error equivalence.
"""
import hashlib
import importlib
import io
import json
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
import pytest

@pytest.fixture
def old(monkeypatch):
    root = os.getenv('TAIKO_FROZEN_BASELINE_ROOT')
    if not root:
        pytest.skip('External frozen source is required for differential QA')
    monkeypatch.syspath_prepend(root)
    return lambda name: importlib.import_module('frozen_source.' + name)

def _fixture_annual_identity(userdata, song_path, rating_path, version, algorithm):
    """Independent identity oracle for the TWO fixed, non-manual snapshots only.

    No candidate service/helper output is used to construct expected identity.
    This does not generalize snapshot selection or change business expectations.
    """
    assert algorithm in {'annual-observation-v4.5.3', 'annual-observation-v4.5.4'}
    paths = sorted((userdata / 'synthetic').glob('data_*.json'))
    assert [p.name for p in paths] == [
        'data_20260101_000000_000000.json', 'data_20260103_000000_000000.json']
    for path, day, stage in zip(paths, (1, 3), (1, 4)):
        payload = json.loads(path.read_text())
        assert payload['_meta'] == {'full': True, 'source': 'wahlap'}
        assert len(payload['songs']) == 12
        assert [song['song_no'] for song in payload['songs']] == list(range(1, 13))
        assert all(song['stage_cnt'] == stage and song['level'] == 4
                   and song['update_datetime'] == f'2026-01-0{day} 00:00:00'
                   for song in payload['songs'])
    assert version == {
        'key': 'annual_2026', 'name': '2026 太鼓年度回顾',
        'startDate': '2025-10-09', 'endDate': '2026-09-30',
        'endExclusive': '2026-10-01', 'calendarDays': 357,
        'timezone': 'Asia/Shanghai', 'reportRevision': 'annual-report-2026-r2-final-window'}
    def canonical_hash(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    start, end = date.fromisoformat(version['startDate']), date.fromisoformat(version['endDate'])
    fingerprint = canonical_hash({
        'algorithm': algorithm, 'manualCorrections': [],
        'reportingWindow': {'start': start.isoformat(), 'endInclusive': end.isoformat(),
                            'endExclusive': (end + timedelta(days=1)).isoformat(),
                            'calendarDays': (end - start).days + 1,
                            'timezone': 'Asia/Shanghai', 'revision': version['reportRevision']},
        'snapshots': [{'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
        'songData': hashlib.sha256(song_path.read_bytes()).hexdigest(),
        'ratingData': hashlib.sha256(rating_path.read_bytes()).hexdigest(),
    })
    summary_id = 'annual_' + canonical_hash({'taikoId': 'synthetic', 'version': version['key'], 'input': fingerprint})[:24]
    return fingerprint, summary_id


def test_annual_success_cache_and_fingerprint(old, tmp_path):
    import test_version_summary as fixture
    from taiko_bot.offline.annual_summary import service
    userdata = tmp_path/'userdata'
    fixture._write_json(tmp_path/'songs.json', fixture._song_data())
    fixture._write_json(tmp_path/'rating.json', fixture._rating_data())
    for day,stage in ((1,1),(3,4)):
        fixture._snapshot(userdata,'synthetic',f'2026010{day}_000000_000000',fixture._payload('wahlap',[fixture._song(i,stage=stage,updated_at=f'2026-01-0{day} 00:00:00') for i in range(1,13)]))
    args=dict(userdata_dir=userdata,song_data_path=tmp_path/'songs.json',rating_path=tmp_path/'rating.json',generated_at=datetime(2026,1,31))
    expected=old('annual_summary.service').build_annual_result('synthetic',fixture.TEST_VERSION,**args)
    assert expected['events'] and expected['summary']['schemaVersion']==4
    old_algorithm, new_algorithm = 'annual-observation-v4.5.3', 'annual-observation-v4.5.4'
    old_fingerprint, old_id = _fixture_annual_identity(userdata, tmp_path/'songs.json', tmp_path/'rating.json', fixture.TEST_VERSION, old_algorithm)
    new_fingerprint, new_id = _fixture_annual_identity(userdata, tmp_path/'songs.json', tmp_path/'rating.json', fixture.TEST_VERSION, new_algorithm)
    assert expected['summary']['provenance']['algorithmVersion'] == old_algorithm
    assert expected['summary']['provenance']['inputFingerprint'] == old_fingerprint
    assert expected['summary']['summaryId'] == expected['summary']['poster']['summaryId'] == old_id
    assert old_id != new_id and old_fingerprint != new_fingerprint
    # Approved 0.14.2/v4.5.4 identity-domain change, exactly FOUR paths.
    # Every section, event, metric and remaining DTO field stays frozen and strict.
    expected['summary']['summaryId'] = new_id
    expected['summary']['poster']['summaryId'] = new_id
    expected['summary']['provenance']['algorithmVersion'] = new_algorithm
    expected['summary']['provenance']['inputFingerprint'] = new_fingerprint
    for _ in range(2):
        actual=service.build_annual_result('synthetic',fixture.TEST_VERSION,**args)
        assert json.dumps(actual,sort_keys=True)==json.dumps(expected,sort_keys=True)

def test_tja_and_catalog_success(old):
    from taiko_bot.offline import tja_roll_parser, merge_json
    from test_tja_roll_parser import TJA_BASIC
    expected=old('tja_roll_parser').parse_tja_roll_metadata(TJA_BASIC)
    assert expected['ura']['roll_times'][0]>3
    assert tja_roll_parser.parse_tja_roll_metadata(TJA_BASIC)==expected
    songs=[{'id':7,'song_name':'Synthetic','song_name_jp':'Synthetic'}]
    payload={'songs':{'Synthetic':{'曲名':'Synthetic','x':1}}}
    assert merge_json.merge_song_id_to_structured(songs,payload)==old('merge_json').merge_song_id_to_structured(songs,payload)

def test_plate_png_sha256(old,tmp_path):
    from PIL import Image
    from taiko_bot.runtime.player.center import draw_dress
    plate=tmp_path/'plate.png';Image.new('RGBA',(500,120),(60,100,150,255)).save(plate)
    results=[]
    for module in (old('draw_dress'),draw_dress):
        image,box=module._build_title_plate_showcase_preview(-1,394,plate_path_override=plate)
        assert image.width==394 and image.height>0
        output=io.BytesIO();image.save(output,format='PNG')
        results.append((hashlib.sha256(output.getvalue()).hexdigest(),box))
    assert results[0]==results[1]

def test_scoreline_cold_hot_generated_bytes(old,tmp_path,monkeypatch):
    from taiko_bot.offline import score_line
    hashes=[]
    for index,module in enumerate((old('score_line'),score_line)):
        root=tmp_path/str(index);root.mkdir()
        for field,name,value in [('SCORE_PATH','score.json',[]),('SONG_DATA_PATH','songs.json',[]),('ALL_LEVELS_STREAM_PATH','stream.json',[{'id':1,'song_name':'synthetic','difficulty':'oni','level':4,'max_combo':100}])]:
            path=root/name;path.write_text(json.dumps(value));monkeypatch.setattr(module,field,path)
        output=root/'out.json';monkeypatch.setattr(module,'UNIFIED_PATH',output)
        count=module.rebuild_scoreline_dataset()
        assert count[0]==1
        cold=module.load_scoreline_data();hot=module.load_scoreline_data()
        assert cold==hot and len(cold)==1
        hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
    assert hashes[0]==hashes[1]

@pytest.mark.parametrize('failure',[None,'audio','mapping','oss'])
def test_update_task_network_oss_write_order(old,tmp_path,monkeypatch,failure):
    import builtins
    from types import SimpleNamespace
    from taiko_bot.offline import song_update_task
    outcomes=[]
    for number,module in enumerate((old('song_update_task'),song_update_task)):
        root=tmp_path/str(number);root.mkdir()
        trace=[]
        names=['SONG_DATA_PATH','SONG_DATA_RAW_PATH','TAIKO_SONG_DATABASE_PATH','CONFIG_PATH','BRANCH_AUDIO_MANIFEST_PATH','SONG_TJA_MAPPING_PATH']
        for name in names:
            path=root/(name+'.json');monkeypatch.setattr(module,name,path)
        song={'id':1,'song_name':'Synthetic','song_name_jp':'Synthetic','max_combo':[100,200,300,400,'-'],'level':[1,2,3,4,'-']}
        module.SONG_DATA_PATH.write_text(json.dumps([song]))
        module.CONFIG_PATH.write_text(json.dumps({'cookie':'synthetic-only'}))
        module.BRANCH_AUDIO_MANIFEST_PATH.write_text('{}')
        def opened(path,mode='r',*args,**kwargs):
            if 'w' in mode: trace.append(('write',Path(path).name))
            return builtins.open(path,mode,*args,**kwargs)
        monkeypatch.setattr(module,'open',opened,raising=False)
        def request(method,url,**kwargs):
            trace.append((method,url,kwargs.get('timeout')))
            payload={'data':{'list':[song,song]}} if method=='POST' else []
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:payload)
        monkeypatch.setattr(module.requests,'post',lambda url,**kw:request('POST',url,**kw))
        monkeypatch.setattr(module.requests,'get',lambda url,**kw:request('GET',url,**kw))
        monkeypatch.setattr(module,'_load_db_bpm_map',lambda:{})
        monkeypatch.setattr(module,'download_missing_fumen_images',lambda rows:{'downloaded_files':[]})
        monkeypatch.setattr(module,'sync_fumens_to_oss',lambda rows:trace.append(('fumens',len(rows))))
        def mapping():
            if failure=='mapping':raise RuntimeError('synthetic mapping failure')
            return {}
        monkeypatch.setattr(module,'refresh_song_tja_mapping',mapping)
        monkeypatch.setattr(module,'audit_song_data',lambda rows,**kw:{'proposedSongData':rows})
        monkeypatch.setattr(module,'write_audit_report',lambda report:trace.append(('audit',)))
        monkeypatch.setattr(module,'sync_audio_from_ese',lambda rows,**kw:{'success':failure!='audio','error':'synthetic audio failure' if failure=='audio' else None,'stats':{'failed_song_count':0}})
        monkeypatch.setattr(module,'check_missing_audio_for_song_data',lambda rows:trace.append(('audio-check',)))
        def command(args,**kw):
            trace.append(('command',args[0] if args[0]=='ossutil' else 'python',args[-1] if args[0]=='ossutil' else 'title-relations'))
            if failure=='oss' and args[0]=='ossutil':raise RuntimeError('synthetic OSS failure')
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(module.subprocess,'run',command)
        monkeypatch.setattr(module,'sync_rating_structured_with_song_data',lambda rows:trace.append(('rating',)))
        monkeypatch.setattr(module,'sync_song_score_with_wiki',lambda rows:trace.append(('score',)))
        monkeypatch.setattr(module,'rebuild_scoreline_dataset',lambda path:(trace.append(('scoreline',)) or (1,1)))
        monkeypatch.setattr(module,'refresh_title_catalog_cache',lambda:[{'subtitle':'synthetic'}])
        monkeypatch.setattr(module,'clear_song_title_showcase_caches',lambda:trace.append(('clear',)))
        if failure is None:
            module.update_taiko_music(interactive=False)
            assert trace[-1]==('clear',)
            assert len(json.loads(module.SONG_DATA_RAW_PATH.read_text()))==1
        else:
            with pytest.raises(RuntimeError) as error:
                module.update_taiko_music(interactive=False)
            assert 'synthetic' in str(error.value) or '映射刷新失败' in str(error.value)
            assert ('clear',) not in trace
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.json') if p.name!='CONFIG_PATH.json'}
        outcomes.append((trace,hashes))
    assert outcomes[0]==outcomes[1]

@pytest.mark.parametrize('kind',['cover_summary','build_achievement_bg','dani_overview'])
def test_display_generators_png_bytes(old,tmp_path,monkeypatch,kind):
    from PIL import Image, ImageFont
    results=[]
    for number,module in enumerate((old(kind),importlib.import_module('taiko_bot.offline.'+kind))):
        root=tmp_path/str(number);root.mkdir()
        font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if kind=='cover_summary':
            songs=root/'songs.json';songs.write_text(json.dumps([{'id':1,'type':'流行音乐','song_name':'Synthetic'}]))
            monkeypatch.setattr(module,'SONG_DB_PATH',str(songs));monkeypatch.setattr(module,'COVER_DIR',str(root));monkeypatch.setattr(module,'FONT_PATH',font)
            output=root/'out.png';module.generate_cover_progress_image(out_path=str(output));raw=output.read_bytes()
        elif kind=='build_achievement_bg':
            Image.new('RGBA',(353,204),(80,90,100,255)).save(root/'bg_level_1.png')
            monkeypatch.setattr(module,'TEMPLATES_DIR',root);monkeypatch.setattr(module,'RANK_DIR',root);monkeypatch.setattr(module,'CROWN_DIR',root);monkeypatch.setattr(module,'FONT_PATH',Path(font))
            raw=module.build_all([1])[0].read_bytes()
        else:
            monkeypatch.setattr(module,'_load_grade_payload',lambda version:{'grades':[{'grade':'Synthetic','songs':[],'conditions':{}}]})
            monkeypatch.setattr(module,'_load_font',lambda size:ImageFont.truetype(font,size))
            monkeypatch.setattr(module,'_load_ddfont',lambda size:ImageFont.truetype(font,size))
            monkeypatch.setattr(module,'_section_background',lambda height:Image.new('RGBA',(1280,height),(80,90,100,255)))
            raw=module.render_dani_overview_image_bytes(grade_order=['Synthetic'])
        assert raw.startswith(b'\x89PNG') and len(raw)>100
        results.append(hashlib.sha256(raw).hexdigest())
    assert results[0]==results[1]


def test_annual_identity_oracle_changes_for_input_bytes_and_rejects_unapproved_domain(tmp_path):
    import test_version_summary as fixture
    userdata = tmp_path/'userdata'
    fixture._write_json(tmp_path/'songs.json', fixture._song_data())
    fixture._write_json(tmp_path/'rating.json', fixture._rating_data())
    for day, stage in ((1, 1), (3, 4)):
        fixture._snapshot(userdata, 'synthetic', f'2026010{day}_000000_000000', fixture._payload('wahlap', [fixture._song(i, stage=stage, updated_at=f'2026-01-0{day} 00:00:00') for i in range(1, 13)]))
    args = (userdata, tmp_path/'songs.json', tmp_path/'rating.json', fixture.TEST_VERSION)
    before = _fixture_annual_identity(*args, 'annual-observation-v4.5.4')
    for path in [tmp_path/'songs.json', tmp_path/'rating.json', userdata/'synthetic/data_20260103_000000_000000.json']:
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        assert _fixture_annual_identity(*args, 'annual-observation-v4.5.4') != before
        path.write_bytes(original)
    with pytest.raises(AssertionError):
        _fixture_annual_identity(*args, 'annual-observation-unapproved')
