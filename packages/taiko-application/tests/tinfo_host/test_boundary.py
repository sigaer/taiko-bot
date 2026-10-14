"""Real native provider, canonical files, frozen tinfo and real score renderer.
Only SQL results, public catalogs/v2 acquisition and platform transport are fixtures.
"""
import ast
import asyncio
import copy
from datetime import datetime
import hashlib
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import re
import runpy
import sys
import shutil
import types

import pytest
from PIL import Image
from sakura_taiko_core.rating import v1, v2
from sakura_taiko_core.dimension import v1 as dims
from taiko_application.commands.score import execute_score
from taiko_application.private_input import PreparedPrivateInput, thaw
# Load actual modules without the unrelated Bot package initializer.
for name, relative in [('plugins','plugins'),('plugins.utils','plugins/utils')]:
    package=types.ModuleType(name)
    package.__path__=[str(Path(os.environ['TINFO_SAKURA'])/relative)]
    sys.modules[name]=package
from taiko_store import PublicationStore, merge_reference, merged_materialization
from plugins.utils import tinfo_provider as provider
from plugins.utils import duplicate_versions

SOURCE = Path(os.environ['TINFO_SAKURA'])
ASSETS = Path(os.environ['TINFO_ASSETS'])
APP = Path(__file__).resolve().parents[2]
FROZEN = APP/'experiments/prepared_private_input/frozen_tinfo.py.txt'
PRINCIPAL = 'onebot_v11:12345'
ACTOR = 'onebot_v11:67890'
REPORT = []


class Clock(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 10, 13, 12)


class SQL:
    def __init__(self):
        self.rows = [(1, PRINCIPAL, '111', 1, 1, 'wahlap', 1),
                     (2, PRINCIPAL, '222', 2, 0, 'hiroba', 0)]
        self.virtual = True
        self.queries = []
        self.closed = 0

    def connect(self):
        state = self
        class Connection:
            def cursor(self):
                return Cursor()
            def commit(self):
                pass
            def close(self):
                state.closed += 1
        class Cursor:
            def execute(self, query, params):
                assert query.strip().startswith('SELECT') and 'FOR UPDATE' not in query
                assert params == (PRINCIPAL,)
                self.query = query
                state.queries.append(query)
            def fetchall(self):
                return list(state.rows)
            def fetchone(self):
                return PRINCIPAL, int(state.virtual)
            def close(self):
                pass
        return Connection()

    def revoke(self):
        self.rows = [(*r[:6], 0) for r in self.rows]


def publish(root, identity, payload):
    store = PublicationStore(root, identity)
    with store.exclusive():
        store.publish({'current': store.stage(json.dumps(payload).encode())},
                      filesystem_times={'fileMtimes': {'current': 1737000000.125}})


def load_functions(path, names, namespace):
    tree = ast.parse('from __future__ import annotations\n' + path.read_text())
    nodes = [tree.body[0]]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert len(nodes) == len(names) + 1
    exec(compile(ast.Module(nodes, type_ignores=[]), str(path), 'exec'), namespace)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path/'userdata'
    root.mkdir()
    monkeypatch.setenv('TAIKO_USERDATA_DIR', str(root))
    monkeypatch.setattr(merge_reference, '_SONG_COMBO_MAP_CACHE', {(278,5):541})
    monkeypatch.setattr(merged_materialization, 'datetime', Clock)
    cfg = runpy.run_path(str(APP/'tests/fixture.py'))['FIXTURE']
    record = next(x for x in cfg['userdata']['songs'] if int(x['song_no']) == 278)
    record = {**record, 'level':5, 'high_score':900000, 'good_cnt':530,'ok_cnt':11,'stage_cnt':2}
    payload = {'profile': {'name':'A'},'achievement':{},'dojo':{},'songs':[record]}
    publish(root,'111',payload)
    publish(root,'222',{**payload,'profile':{'name':'B'},'songs':[{**record,'high_score':950000}]})
    song = {'id':278,'song_name':'花漾','song_name_jp':'花漾 ～Flourishing Blossoms～','bpm':'140',
            'type':'南梦宫原创音乐', **{f'level_{i}': '9' if i==5 else '-' for i in range(1,6)}}
    (tmp_path/'songs').mkdir()
    (tmp_path/'songs/song_data.json').write_text(json.dumps([song]))
    (tmp_path/'songs/rating_structured_with_ids.json').write_text(json.dumps(cfg['rating_config']))
    (tmp_path/'assets').symlink_to(ASSETS, target_is_directory=True)
    # Real duplicate selection functions consume the synthetic public catalog.
    from sakura_taiko_core.chart import identity
    monkeypatch.setattr(duplicate_versions, '_group_cache', lambda *a, **k: identity.build_group_maps([song]))
    score = types.ModuleType('plugins.utils.score_calculator')
    for module in (v1, dims):
        for name in dir(module):
            setattr(score, name, getattr(module,name))
    monkeypatch.setitem(sys.modules, 'plugins.utils.score_calculator', score)
    upstream = types.ModuleType('plugins.utils.taikob_v2')
    upstream._calculate_v2_from_chart = lambda chart, **kw: v2._calculate_v2_from_chart(chart, profile='v2-center-20261010', **kw)
    monkeypatch.setitem(sys.modules,'plugins.utils.taikob_v2',upstream)
    ds = types.ModuleType('plugins.utils.taikob_v2_data')
    ds.V2DataSourceError = ValueError
    ds.load_v2_snapshot = lambda: types.SimpleNamespace(song_map={})
    monkeypatch.setitem(sys.modules,'plugins.utils.taikob_v2_data',ds)
    spec = importlib.util.spec_from_file_location('plugins.utils.drawinfo', SOURCE/'plugins/utils/drawinfo.py')
    draw = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, draw)
    spec.loader.exec_module(draw)
    draw.ROOT_DIR = tmp_path
    draw.USERDATA_DIR = str(root)
    draw.RATING_DB_PATH = str(tmp_path/'songs/rating_structured_with_ids.json')
    chart = next(x for x in cfg['rating_config']['songs'].values() if int(x['id'])==278 and int(x['level'])==5)
    draw._load_rating_song_index = lambda: {(278,5):chart}
    draw._load_rating_const_table = lambda: v1.build_const_table(cfg['rating_config']['const_table']['const_to_score'])
    draw._load_note_count_map = lambda: {(278,5):541}
    sql = SQL()
    return types.SimpleNamespace(sql=sql,root=root,draw=draw,payload=payload)


class Finish(BaseException):
    pass


def image_summary(raw):
    with Image.open(BytesIO(raw)) as im:
        return {'kind':'image', 'sha256':hashlib.sha256(raw).hexdigest(),
                'pixels':hashlib.sha256(im.tobytes()).hexdigest(),'size':list(im.size),'mode':im.mode}


def run(f, *, new, query='single', hook=None):
    outputs=[]
    class Matcher:
        async def finish(self, value=None):
            if value is not None:
                outputs.append({'kind':'text','text':value,'delivery':'direct'})
            raise Finish()
    async def reply(m,event,value):
        # Pass through the actual tinfo transport facade, not around its proof.
        if isinstance(m, provider.AuthorizedDelivery):
            m._verify()
        outputs.append({'kind':'text','text':value,'delivery':'reply'})
        raise Finish()
    async def image(m,event,value,**kw):
        if isinstance(m, provider.AuthorizedDelivery):
            m._verify()
        outputs.append({**image_summary(value),'prefix':kw.get('prefix_text','')})
        raise Finish()
    rows={'single':[[278,'花漾']], 'many':[[278,'花漾'],[7,'Other']], 'none':[],
          'fuzzy-low':[[278,'花漾',50]],'fuzzy-high':[[278,'花漾',90]],'bad-id':[[-1,'bad']],
          'missing-song':[[999,'missing']], 'bad-row':[['oops','bad']], 'invalid-return':None}
    ns={'__name__':'plugins._tinfo_test','__package__':'plugins','__file__':str(SOURCE/'plugins/taiko.py'),
        're':re,'os':os,'Path':Path,'BytesIO':BytesIO,'Image':Image,'music_info':Matcher(),
        '_get_taiko_db_connection':f.sql.connect,
        '_normalize_identity_key':lambda x:x, 'get_identity_key':lambda **k:ACTOR,
        '_resolve_requested_identity_key':lambda e:(PRINCIPAL,False),
        '_taiko_bind_usage_message':lambda e:'bind help',
        '_extract_music_info_command_match':lambda e: None if query=='format' else re.fullmatch(r'tinfo (.+)', 'tinfo '+query),
        '_finish_text_reply':reply, '_finish_image_reply':image,
        'generate_score_image':f.draw.generate_score_image, 'queryMusic':lambda name:copy.deepcopy(rows[name]),
        'print':lambda *a:None,'FUZZY_ACCEPT_THRESHOLD':0.7,'is_accepted_similarity':lambda ratio,threshold:ratio/100>=threshold,
        'execute_score':execute_score,'MergedBindError':provider.MergedBindError,
        'MergedBindMissingUserdataError': __import__('plugins.utils.merged_bind',fromlist=['MergedBindMissingUserdataError']).MergedBindMissingUserdataError}
    helpers={'_to_jpeg_bytes','_is_fuzzy_query_result','_is_accepted_fuzzy_query_result','_is_rejected_fuzzy_query_result','_build_fuzzy_query_hint'}
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == json.loads((FROZEN.parent/'provenance.json').read_text())['selected_sha256']
    load_functions(FROZEN, helpers | ({'music_info_handle'} if not new else set()), ns)
    if new:
        load_functions(SOURCE/'plugins/taiko.py', {'music_info_handle','_deliver_application_command'},ns)
        if hook:
            delivery=ns['_deliver_application_command']
            async def hooked(*args):
                hook()
                await delivery(*args)
            ns['_deliver_application_command']=hooked
    else:
        from plugins.utils.bot_binding_mutation import _entry, _Row
        def info(identity):
            if not f.sql.rows:
                return None
            selected=next((r for r in f.sql.rows if r[4]),f.sql.rows[0])
            return {'id':selected[2],'visible':selected[6],'source':selected[5]}
        ns['_get_taiko_bind_info']=info
        ns['_get_current_bind_entry']=lambda identity:_entry([_Row(*r) for r in f.sql.rows],f.sql.virtual)
        ns['materialize_merged_bind_userdata']=lambda identity,entry:provider.materialize_merged_bind_userdata(identity,entry,userdata_dir=f.root)
        provenance=json.loads(Path(__file__).with_name('provenance.json').read_text())
        frozen_resolver=Path(__file__).with_name('frozen_resolver.py.txt')
        assert hashlib.sha256(frozen_resolver.read_bytes()).hexdigest()==provenance['resolver_sha256']
        load_functions(frozen_resolver,set(provenance['functions']),ns)
    async def invoke():
        try:
            await ns['music_info_handle'](types.SimpleNamespace())
        except Finish:
            pass
    try:
        asyncio.run(invoke())
    except Exception as error:
        message=str(error)
        if type(error).__name__=='UnidentifiedImageError':
            message=re.sub(r'(?<=<_io.BytesIO object at )0x[0-9a-f]+(?=>)', '<address>', message)
        return {'error':type(error).__name__,'message':message}
    assert len(outputs)==1
    return outputs[0]


@pytest.mark.parametrize('scenario',['normal','u0-first','u0-existing','member-change','profile-change','no-history'])
@pytest.mark.parametrize('query',['single','many','none','fuzzy-low','fuzzy-high','bad-id','missing-song','bad-row','invalid-return','format'])
def test_parity(fixture, monkeypatch, scenario, query):
    f=fixture
    if scenario=='normal':
        f.sql.virtual=False
    if scenario=='u0-existing':
        provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root).prepare(ACTOR,PRINCIPAL)
    if scenario=='member-change':
        publish(f.root,'333',{**f.payload,'songs':[{**f.payload['songs'][0],'high_score':999000}]})
        f.sql.rows[1]=(3,PRINCIPAL,'333',2,0,'wahlap',0)
    if scenario=='profile-change':
        f.sql.rows=[(*r[:4],1-r[4],*r[5:6],1) for r in f.sql.rows]
    # Independent copies ensure u0-first is actually first on BOTH paths.
    new_root=f.root.parent/'new-userdata'
    shutil.copytree(f.root,new_root)
    old=run(f,new=False,query=query)
    f.root=new_root
    f.draw.USERDATA_DIR=str(new_root)
    monkeypatch.setenv('TAIKO_USERDATA_DIR',str(new_root))
    actual=run(f,new=True,query=query)
    assert actual==old
    expected='image' if query in ('single','fuzzy-low','fuzzy-high') else 'text'
    assert ('error' in actual) == (query in ('bad-row','invalid-return'))
    if query not in ('bad-row','invalid-return'):
        assert actual['kind']==expected
    REPORT.append({'scenario':scenario,'query':query,'result':actual})


@pytest.mark.parametrize('checkpoint',['before','prepared','rendered','send'])
def test_revoke(fixture,monkeypatch,checkpoint):
    f=fixture
    if checkpoint=='before':
        f.sql.revoke()
    if checkpoint=='prepared':
        original=provider.TinfoHostProvider.prepare
        def prepare(self,*args):
            result=original(self,*args)
            f.sql.revoke()
            return result
        monkeypatch.setattr(provider.TinfoHostProvider,'prepare',prepare)
    if checkpoint=='rendered':
        from taiko_application.score.drawinfo import ScoreInfoRenderer
        original=ScoreInfoRenderer.render
        def render(self):
            result=original(self)
            f.sql.revoke()
            return result
        monkeypatch.setattr(ScoreInfoRenderer,'render',render)
    result=run(f,new=True,hook=f.sql.revoke if checkpoint=='send' else None)
    assert result=={'kind':'text','text':'查不到呢，可能不给看哦~','delivery':'direct'}


@pytest.mark.parametrize('change',['member','order','profile','visibility'])
def test_same_id_changed_snapshot(fixture,change):
    f=fixture
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    prepared=host.prepare(ACTOR,PRINCIPAL)
    before=thaw(prepared.current)
    if change=='member':
        f.sql.rows[1]=(3,PRINCIPAL,'333',2,0,'wahlap',0)
    elif change=='order':
        f.sql.rows=[(*r[:3],i,*r[4:]) for i,r in enumerate(reversed(f.sql.rows),1)]
    elif change=='profile':
        f.sql.rows=[(*r[:4],1-r[4],*r[5:6],1) for r in f.sql.rows]
    else:
        f.sql.revoke()
    with pytest.raises(provider.TinfoDenied):
        host.verify(prepared)
    assert thaw(prepared.current)==before


def test_legacy_policy_and_missing_history(fixture):
    f=fixture
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    prepared=host.prepare(ACTOR,PRINCIPAL)
    assert prepared.authorized_target.members==('111','222')
    assert f.sql.rows[1][-1]==0  # Selected-visible authorizes the whole native u0.
    assert prepared.history is None and prepared.provenance.history_view is None
    assert prepared.provenance.dependency_hash
    with pytest.raises(TypeError):
        prepared.current['songs']=[]


def test_report():
    output=os.environ.get('TINFO_REPORT')
    if output:
        Path(output).write_text(json.dumps(REPORT,ensure_ascii=False,indent=2))


@pytest.mark.parametrize('fault',['missing-current','invalid-json','invalid-songs','missing-template','missing-member'])
def test_errors(fixture,monkeypatch,fault):
    f=fixture
    if fault=='missing-member':
        f.sql.rows[1]=(3,PRINCIPAL,'333',2,0,'wahlap',0)
    elif fault=='missing-template':
        for fn in (f.draw.generate_score_image,f.draw.prepare_score_presentation):
            monkeypatch.setitem(fn.__kwdefaults__,'template_path','absent-template.png')
            monkeypatch.setitem(fn.__kwdefaults__,'assets_base',str(f.root.parent/'absent-assets'))
    else:
        f.sql.virtual=False
        # Owned unmanaged source retains legacy missing/invalid error semantics.
        f.sql.rows=[(3,PRINCIPAL,'333',1,1,'wahlap',1)]
        if fault=='invalid-json':
            (f.root/'333data.json').write_text('{')
        if fault=='invalid-songs':
            (f.root/'333data.json').write_text('{"songs":7}')
    old=run(f,new=False)
    actual=run(f,new=True)
    assert actual==old
    assert actual['kind']=='text'
    if fault=='missing-current' or fault=='missing-template':
        assert actual['delivery']=='reply' and '还未上传' in actual['text']
    # Missing normal current must not mask song-query text.
    if fault=='missing-current':
        assert run(f,new=True,query='none')==run(f,new=False,query='none')


@pytest.mark.parametrize('continuous',[False,True])
def test_publication_race_releases_before_retry(fixture,monkeypatch,continuous):
    f=fixture
    original=provider.materialize_merged_bind_userdata
    calls=[]
    def materialize(*args,**kwargs):
        result=original(*args,**kwargs)
        calls.append(1)
        if continuous or len(calls)==1:
            publish(f.root,'222',{**f.payload,'songs':[{**f.payload['songs'][0],'high_score':990000+len(calls)}]})
        return result
    monkeypatch.setattr(provider,'materialize_merged_bind_userdata',materialize)
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    if continuous:
        with pytest.raises(provider.TinfoUnavailable):
            host.prepare(ACTOR,PRINCIPAL)
    else:
        prepared=host.prepare(ACTOR,PRINCIPAL)
        assert prepared.current['songs'][0]['high_score']==990001
        store=PublicationStore(f.root,prepared.authorized_target.user_id)
        with store.shared():
            assert prepared.provenance.dependency_hash==store.view()['dependencyHash']
    assert len(calls)==2


@pytest.mark.parametrize('change',['member','profile'])
def test_reprepare_changes_receipt(fixture,change):
    f=fixture
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    before=host.prepare(ACTOR,PRINCIPAL)
    if change=='member':
        publish(f.root,'333',{**f.payload,'songs':[{**f.payload['songs'][0],'high_score':999000}]})
        f.sql.rows[1]=(3,PRINCIPAL,'333',2,0,'wahlap',0)
    else:
        f.sql.rows=[(*r[:4],1-r[4],*r[5:6],1) for r in f.sql.rows]
    after=host.prepare(ACTOR,PRINCIPAL)
    assert before.provenance.dependency_hash!=after.provenance.dependency_hash
    assert before.authorized_target.user_id==after.authorized_target.user_id
    if change=='profile':
        assert after.current['profile']['name']=='B'
    else:
        assert after.current['songs'][0]['high_score']==999000


def test_send_fallback_rechecks(fixture):
    f=fixture
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    prepared=host.prepare(ACTOR,PRINCIPAL)
    class Matcher:
        async def send(self,*args,**kwargs):
            f.sql.revoke()
            raise RuntimeError('40034128')
    facade=provider.AuthorizedDelivery(Matcher(),host,prepared)
    with pytest.raises(provider.TinfoDenied):
        asyncio.run(facade.send('private result'))


def test_no_provider_reentry_during_application(fixture,monkeypatch):
    f=fixture
    from taiko_application.commands.prepared_score import PreparedScoreCommand, ScoreSelection
    host=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root)
    prepared=host.prepare(ACTOR,PRINCIPAL)
    presentation=f.draw.prepare_score_presentation(278,thaw(prepared.current),prefer_best_in_group=True)
    def denied(*args,**kwargs):
        raise AssertionError('Private capability reentry')
    monkeypatch.setattr(host,'prepare',denied)
    monkeypatch.setattr(provider.TinfoHostProvider,'_snapshot',denied)
    monkeypatch.setattr(PublicationStore,'reader',denied)
    result=execute_score(PreparedScoreCommand(prepared,ScoreSelection(278),presentation))
    assert result.kind=='image'


def test_reject_capabilities(fixture):
    from dataclasses import replace
    f=fixture
    prepared=provider.TinfoHostProvider(connection_factory=f.sql.connect,userdata_root=f.root).prepare(ACTOR,PRINCIPAL)
    for capability in (lambda:None, f.root, object(), b'raw'):
        with pytest.raises(TypeError):
            replace(prepared,current={'capability':capability})
    with pytest.raises(ValueError):
        replace(prepared,provenance=replace(prepared.provenance,profile_source='222'))
    with pytest.raises(TypeError):
        replace(prepared.provenance,dependency_hash=lambda:None)


@pytest.mark.parametrize('fault',['runtime','type','jpeg'])
def test_renderer_error_mapping(fixture,monkeypatch,fault):
    from taiko_application.score.drawinfo import ScoreInfoRenderer
    def render(self):
        if fault=='jpeg':
            return b'not-an-image'
        if fault=='runtime':
            raise RuntimeError('synthetic renderer failure')
        raise TypeError('synthetic invalid record')
    monkeypatch.setattr(ScoreInfoRenderer,'render',render)
    old=run(fixture,new=False)
    actual=run(fixture,new=True)
    assert actual==old
    if fault=='jpeg':
        assert actual['error']=='UnidentifiedImageError'
    else:
        assert actual['kind']=='text' and actual['delivery']=='direct'


def test_revoked_preparation_error_is_not_sent(fixture,monkeypatch):
    def fail(*args,**kwargs):
        fixture.sql.revoke()
        raise provider.MergedBindError('private member detail')
    monkeypatch.setattr(provider,'materialize_merged_bind_userdata',fail)
    assert run(fixture,new=True)=={'kind':'text','text':'查不到呢，可能不给看哦~','delivery':'direct'}
