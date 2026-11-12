"""Offline benchmark of real B30 command/calculation/rendering paths.

Run under scripts/memory/run_qa.sh. Never opens a private production file or
sends a Bot event. Public catalog/assets must first be pinned by fixtures.py.
All times are raw nanoseconds; nested phases include both inclusive/exclusive.
"""
from __future__ import annotations
import argparse
import contextlib
import copy
import dataclasses
import datetime
import functools
import hashlib
import importlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time
import types
from importlib.metadata import version

MAIN = [('U05','taikob30 v1'), ('U05','taikob'), ('U08','taikob30 v1'),
        ('U08','taikob'), ('U11','taikob'), ('U12','taikob')]
CENTER = ['taikob','taikob20 v2','taikob30 v2','taikob20 v1','taikob30 v1','taikob50 v1',
          'taikob20 v2 精度','taikob30 v1 精度','taikob20 v2 体力','taikob20 v1 节奏',
          'taikob20 v2 nonsense','taikob20 v2 -r','taikob20 v1 v2']
CLIENT = ['taikob20','taikob30','taikob50','taikob20 v2','taikob20 v2 精度',
          'taikob20 v2 体力','taikob30 v2','taikob20 v2 nonsense']


class Timings:
    def __init__(self): self.rows={}; self.stack=[]
    @contextlib.contextmanager
    def phase(self,name):
        start=time.perf_counter_ns(); frame=[0,name]; parent=self.stack[-1][1] if self.stack else None; self.stack.append(frame)
        try: yield
        finally:
            elapsed=time.perf_counter_ns()-start; self.stack.pop()
            if self.stack:self.stack[-1][0]+=elapsed
            row=self.rows.setdefault(name,dict(inclusive_ns=0,exclusive_ns=0,calls=0,parents={}))
            row['inclusive_ns']+=elapsed;row['exclusive_ns']+=elapsed-frame[0];row['calls']+=1
            if parent:row['parents'][parent]=row['parents'].get(parent,0)+1
    def wrap(self,obj,name,label):
        original=getattr(obj,name)
        @functools.wraps(original)
        def measured(*a,**kw):
            with self.phase(label):return original(*a,**kw)
        setattr(obj,name,measured)


def initialize(a):
    sys.dont_write_bytecode=True
    sys.path[:0]=[str(a.source),str(a.source/'packages/taiko-application/src')]
    if a.profile=='client':
        sys.path.insert(0,str(a.fixture.parent/'core-client'))
    os.chdir(a.fixture)
    os.environ.update(TAIKO_RUNTIME_ROOT=str(a.fixture),TAIKO_BOT_ROOT=str(a.fixture),
                      TAIKO_CENTER_ROOT=str(a.fixture),TAIKO_USERDATA_DIR=str(a.fixture/'userdata'),
                      MPLBACKEND='Agg',MPLCONFIGDIR=str(a.fixture/'mplconfig'),PYTHONDONTWRITEBYTECODE='1')
    # Deny private production access, sockets, SQL; fixtures/public assets only.
    def guard(event,args):
        if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):
            raise AssertionError('benchmark external IO: '+event)
        if event=='open' and isinstance(args[0],(str,os.PathLike)):
            path=Path(args[0]).absolute()
            if str(path).startswith('/home/sigaer/taiko/') and not any(str(path).startswith('/home/sigaer/taiko/'+p+'/') for p in ('assets','songs','qa-vault')):
                raise AssertionError('private production path: '+str(path))
    sys.addaudithook(guard)
    import nonebot
    nonebot.init(driver='~fastapi',log_level='CRITICAL',taiko_song_profile=a.profile,taiko_song_public_root=str(a.fixture))
    from PIL import Image
    Image.init()
    base='taiko_bot.runtime.player.'+a.profile+'.b30_support.'
    mods={n:importlib.import_module(base+n) for n in ['parsing','score_calculator','dimension','b30_render','taikob_v2']}
    mods['history']=importlib.import_module('taiko_bot.runtime.player.'+a.profile+'.b30_history')
    if a.profile=='center':
        data=importlib.import_module('taiko_bot.runtime.player.center.taikob_v2_data')
        snapshot=data.parse_v2_dataset_csv((a.fixture/'songs/constants_id_v2.csv').read_text())
        data._snapshot=snapshot
        if hasattr(data,'_local_revision'):data._fallback_revision=data._local_revision()
        mods['snapshot']=snapshot;mods['data']=data
    return mods


def instrument(t,mods):
    from PIL import Image, ImageFont
    from taiko_application.score import B30Renderer,B30SingleRenderer
    for module, names, prefix in [(mods['score_calculator'],['compute_all_from_userdata_records','_compute_results_from_userdata_records'],'C.v1'),
           (mods['taikob_v2'],['compute_all_v2_from_userdata_records'],'C.v2'),
           (mods['b30_render'],['_pick_top_entries','compute_b30_update_diff'],'C.top_diff'),
           (mods['history'],['_history_snapshot_inputs','_reconstruct_user_snapshots','_build_daily_rating_points_from_view','capture'],'B.history')]:
        for name in names:
            if hasattr(module,name):t.wrap(module,name,prefix+'.'+name)
    for cls,names in [(B30Renderer,['_render','_choose_grid_layout','_compose_resizable_template','_render_radar_image']),
                      (B30SingleRenderer,['_render'])]:
        for name in names:t.wrap(cls,name,'E.'+cls.__name__+'.'+name)
    t.wrap(ImageFont,'truetype','D.font');t.wrap(Image,'open','D.open')
    for name in ['resize','alpha_composite','convert','load']:t.wrap(Image.Image,name,'E.'+name)
    original=Image.Image.save
    def save(im,fp,format=None,**kw):
        with t.phase('E.encode.'+str(format)):return original(im,fp,format=format,**kw)
    Image.Image.save=save


def instrument_detail(t, mods):
    """Extra attribution only; do not mix its overhead into primary timings."""
    replacements = {}
    for module in mods.values():
        for name in ('aggregate_topN_value', 'compute_dim_topN_means',
                     'aggregate_topN_value_v2', 'compute_dim_topN_means_v2'):
            if callable(getattr(module, name, None)):
                original = getattr(module, name)
                t.wrap(module, name, 'C.aggregate.' + name)
                replacements[original] = getattr(module, name)
        for name in ('load_rating_config', '_load_rating_resources',
                     'build_song_index', 'build_const_table', 'build_duplicate_song_groups'):
            if callable(getattr(module, name, None)):
                t.wrap(module, name, 'D.catalog.' + name)
    # Legacy adapters bind aggregation callables in keyword defaults. Replace
    # those references too so attribution includes the unchanged default path.
    for module in mods.values():
        if not isinstance(module, types.ModuleType):
            continue
        for function in list(vars(module).values()):
            function = getattr(function, '__wrapped__', function)
            if not isinstance(function, types.FunctionType):
                continue
            def replace(value):
                return replacements.get(value, value) if callable(value) else value
            if function.__defaults__:
                function.__defaults__ = tuple(replace(v) for v in function.__defaults__)
            if function.__kwdefaults__:
                function.__kwdefaults__ = {k:replace(v) for k,v in function.__kwdefaults__.items()}
    if 'data' in mods:
        t.wrap(mods['data'], 'load_v2_snapshot', 'B.v2_snapshot')
    from taiko_store.reader import ScoreReadView
    original = ScoreReadView.decoded
    def decoded(view, key='current'):
        with t.phase('B.read_current' if key == 'current' else 'B.read_history'):
            return original(view, key)
    ScoreReadView.decoded = decoded
    from PIL.PngImagePlugin import PngImageFile
    t.wrap(PngImageFile, 'load', 'E.decode.PNG')


def ports_for(a,mods,fixture,prepared_inputs):
    from taiko_application.commands import B30Ports
    p,s,d,b,v=[mods[n] for n in ['parsing','score_calculator','dimension','b30_render','taikob_v2']]
    current=fixture['current'];records=current['songs']
    image_output = 'as_png_bytes' in inspect.signature(b.render_b30_image).parameters
    def summary(uid,**kw):
        if a.profile=='client':kw.pop('collapse_duplicate_versions',None)
        if image_output:kw['as_png_bytes']=False
        result=b.render_b30_image(uid,userdata=current,**prepared_inputs,**kw)
        if a.verify and a.profile=='client':
            png=b.render_b30_image(uid,userdata=current,**prepared_inputs,**dict(kw,as_png_bytes=True)) if image_output else result
            a.artifacts['default_png']=image_digest(png)
        return result
    def v2call(fn,uid,**kw):
        extra={'snapshot':mods['snapshot']} if a.profile=='center' else {}
        if a.profile=='center' and fn is v.render_b20_v2_image:
            extra.update(prepared_inputs)
            if image_output:extra['as_png_bytes']=False
        direct = 'as_png_bytes' in inspect.signature(fn).parameters
        if direct:extra['as_png_bytes']=False
        result=fn(uid,userdata=current,**extra,**kw)
        if a.verify and direct:
            a.artifacts['default_png']=image_digest(fn(uid,userdata=current,**dict(extra,as_png_bytes=True),**kw))
        return result
    def dimension(*args,**kw):
        direct = 'as_png_bytes' in inspect.signature(d.generate_dim_top_image).parameters
        extra={'as_png_bytes':False} if direct else {}
        result=d.generate_dim_top_image(*args,userdata=current,**extra,**kw)
        if a.verify:
            png=d.generate_dim_top_image(*args,userdata=current,as_png_bytes=True,**kw) if direct else result
            a.artifacts['default_png']=image_digest(png)
        return result
    def encode(image,quality=85):
        if a.verify:a.artifacts['encoder_input']=image_digest(image)
        return p._to_jpeg_bytes(image,quality=quality)
    def compute(_uid,**kw):
        calculate=lambda:(prepared_inputs['results_from_records_fn'](records) if 'results_from_records_fn' in prepared_inputs else s.compute_all_from_userdata_records(records,**kw)) if a.profile=='center' else s.compute_all_from_userdata_records(records)
        if (a.source/'taiko_bot/runtime/player/prepared_rating.py').exists():
            from taiko_bot.runtime.player.prepared_rating import prepare_v1_results
            return prepare_v1_results(calculate,profile=a.profile,collapse=bool(kw.get('collapse_duplicate_versions')) if a.profile=='center' else True,song_path=a.fixture/'songs/song_data.json',user_id=_uid,records=records)
        return calculate()
    return B30Ports(str(a.fixture/'assets/fonts/DDFont.ttf'),p.TAIKOB_V2_DIM_USAGE,
        mods['data'].V2DataSourceError if a.profile=='center' else RuntimeError,v.V2_TAIKOB_DIM_ALIASES,
        getattr(p,'_extract_rating_version',None),lambda _:records,p._parse_taikob_dim_arg,
        p._resolve_taikob_dim_arg,encode,
        compute,
        dimension,
        functools.partial(s.generate_top_N_image,observed_at='2026-11-11T12:00:00'),
        functools.partial(v2call,v.render_b20_v2_dim_image),functools.partial(v2call,v.render_b20_v2_image),summary)


def prepare_inputs(a,mods,fixture,command):
    history=fixture['history']
    if a.profile=='client':
        return dict(history_snapshots=history,daily_points=mods['history'].build_daily_rating_points(10001,command[0],history_snapshots=history),observed_at='2026-11-11T12:00:00')
    # Real PublicationStore leases, object integrity, JSON reads and reconstruction.
    # Only the identity/permission authority is a deterministic offline fixture.
    from taiko_store import PublicationStore
    store=PublicationStore(a.fixture/'native'/fixture['id']/'userdata','10001')
    provider=types.SimpleNamespace(verify_initial=lambda:None)
    with store.shared():
        view=store.reader()
        fixture['current']=view.decoded('current')
        mods['history'].capture(provider,view,store,command,fixture['current'])
    return provider.b30_inputs


def output_digest(result):
    from PIL import Image
    payload=result.payload if hasattr(result,'payload') else result.content
    if not isinstance(payload,bytes):return dict(kind='text',text=str(payload))
    with Image.open(io.BytesIO(payload)) as im:
        return dict(kind='image',sha256=hashlib.sha256(payload).hexdigest(),pixels=hashlib.sha256(im.tobytes()).hexdigest(),size=list(im.size),bytes=len(payload))


def image_digest(value):
    from PIL import Image
    owned=not isinstance(value,Image.Image)
    im=Image.open(io.BytesIO(value.getvalue() if isinstance(value,io.BytesIO) else value)) if owned else value
    try:
        data=dict(size=list(im.size),pixels=hashlib.sha256(im.tobytes()).hexdigest())
        with Image.new('RGB',im.size,'white') as rgb:
            if im.mode in ('RGBA','LA'):
                with im.getchannel('A') as mask:rgb.paste(im,mask=mask)
            else:rgb.paste(im)
            data['rgb_pixels']=hashlib.sha256(rgb.tobytes()).hexdigest()
        if owned:data['sha256']=hashlib.sha256(value.getvalue() if isinstance(value,io.BytesIO) else value).hexdigest()
        return data
    finally:
        if owned:im.close()


def normalized(value):
    if dataclasses.is_dataclass(value):return {f.name:normalized(getattr(value,f.name)) for f in dataclasses.fields(value)}
    if isinstance(value,dict):return {str(k):normalized(v) for k,v in sorted(value.items(),key=lambda kv:str(kv[0]))}
    if isinstance(value,(list,tuple)):return [normalized(v) for v in value]
    if isinstance(value,set):return sorted(normalized(v) for v in value)
    return value


def digest_value(value):
    return hashlib.sha256(json.dumps(normalized(value),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def environment():
    import platform
    cgroup=Path('/proc/self/cgroup').read_text().strip().split('::')[-1]
    root=Path('/sys/fs/cgroup')/cgroup.lstrip('/')
    return dict(python=sys.version,versions={n:version(n) for n in ('Pillow','numpy','pandas','sakura-taiko-core','sakura-taiko-contract')},
                machine=platform.machine(),load=os.getloadavg(),cgroup=cgroup,
                limits={n:(root/n).read_text().strip() for n in ('cpu.max','memory.high','memory.max','memory.swap.max') if (root/n).exists()})


def run(a):
    started=time.perf_counter_ns();mods=initialize(a);startup=time.perf_counter_ns()-started
    from taiko_application.commands import CommandContext,CommandResult,prepare_b30,execute_b30
    from taiko_application.score import B30Renderer
    t=Timings();instrument(t,mods)
    if a.detail_phases:instrument_detail(t,mods)
    env=environment();a.artifacts={}
    pattern=re.compile(r'^/?taikob(?:\s*(50|[1-4]\d|[1-9]))?(?:\s*(.*))?$' if a.profile=='center' else r'^/?taikob\s*(50|[1-4]\d|[1-9])(?:\s*(.*))?$',re.I)
    rows=[]
    for uid,command in json.loads(a.cases):
        fixture=json.loads((a.fixture/'fixtures'/f'{uid}.json').read_text())
        if fixture['members']:
            from taiko_application.merged_bind import merge_song_records
            fixture['current']['songs']=merge_song_records([m['songs'] for m in fixture['members']],combo_map={})
        if a.profile=='center':
            from taiko_store import PublicationStore
            native=a.fixture/'native'/uid
            native.mkdir(parents=True,exist_ok=True)
            if not (native/'songs').exists():(native/'songs').symlink_to(a.fixture/'songs')
            store=PublicationStore(native/'userdata','10001')
            with store.exclusive():
                changes={'current':json.dumps(fixture['current']).encode(),**{'history/'+h['fileName']:json.dumps(h['payload']).encode() for h in fixture['history']}}
                staged={key:store.stage(value) for key,value in changes.items()}
                store.publish(staged,filesystem_times={'fileMtimes':{'current':1794369600},'fileCtimes':{'current':1794369600}})
        p=ports_for(a,mods,fixture,dict(history_snapshots=[],daily_points=[],observed_at='2026-11-11T12:00:00'))
        prepared=prepare_b30(CommandContext(match=pattern.match(command),profile=a.profile),p)
        inputs=prepare_inputs(a,mods,fixture,prepared) if a.scope!='query' and not isinstance(prepared,CommandResult) else dict(history_snapshots=[],daily_points=[],observed_at='2026-11-11T12:00:00')
        if a.scope!='query' and callable(inputs.get('daily_points')):
            inputs['daily_points']=inputs['daily_points']()
        p=ports_for(a,mods,fixture,inputs)
        captured=[]
        original=B30Renderer.render
        def capture(renderer,*args,**kw):
            c=renderer.context
            if a.scope=='draw':captured.append(dataclasses.replace(c,dress_image=c.dress_image.copy(),title_image=c.title_image.copy()))
            result=original(renderer,*args,**kw)
            if a.verify:
                a.artifacts['summary_algorithm']=digest_value({k:getattr(c,k) for k in ('top_entries','card_ratings','overall','dim_means','update_diff','trend_rows')})
                png=result if isinstance(result,bytes) else original(B30Renderer(c))
                a.artifacts['default_png']=image_digest(png)
            return result
        for iteration in range(-a.warmup,a.repeats):
            t.rows={};t.stack=[];a.artifacts={}
            if a.scope=='compute':
                fresh=dict(inputs)
                memo=fresh.get('results_from_records_fn')
                if memo is not None:
                    fresh_memo=type(memo)(memo.calculate,memo.revision)
                    fresh['results_from_records_fn']=fresh_memo
                    for name in ('aggregate_topn_value_fn','compute_dim_topn_means_fn'):
                        previous=fresh.get(name)
                        if previous is not None:
                            fresh[name]=fresh_memo.aggregate(previous._memo_kind,previous._memo_function)
                p=ports_for(a,mods,fixture,fresh)
            wall=time.perf_counter_ns();cpu=time.process_time_ns()
            with t.phase('F.request'):
                if a.scope=='query':
                    with t.phase('A.parse_identity_fixture'):
                        fixture=json.loads((a.fixture/'fixtures'/f'{uid}.json').read_text())
                        if fixture['members']:
                            fixture['current']['songs']=merge_song_records([m['songs'] for m in fixture['members']],combo_map={})
                        prepared=prepare_b30(CommandContext(match=pattern.match(command),profile=a.profile),p)
                    with t.phase('B.prepare'):
                        inputs=prepare_inputs(a,mods,fixture,prepared) if not isinstance(prepared,CommandResult) else {}
                        p=ports_for(a,mods,fixture,inputs)
                if a.scope=='draw' and captured:
                    payload=B30Renderer(captured[-1]).render()
                    result=CommandResult('image',p._to_jpeg_bytes(payload,quality=85))
                else:
                    if a.scope=='draw' or a.verify:B30Renderer.render=capture
                    try:result=prepared if isinstance(prepared,CommandResult) else execute_b30(CommandContext(user_id=10001,profile=a.profile),p,prepared)
                    finally:B30Renderer.render=original
            elapsed=time.perf_counter_ns()-wall; cpu=time.process_time_ns()-cpu
            if iteration>=0:
                artifacts=copy.deepcopy(a.artifacts)
                if a.verify and not isinstance(prepared,CommandResult):
                    records=fixture['current']['songs']
                    if prepared[2]:
                        v=mods['taikob_v2']
                        results=v.compute_all_v2_from_userdata_records(records,**({'song_map':mods['snapshot'].song_map} if a.profile=='center' else {}))
                    else:
                        results=mods['score_calculator'].compute_all_from_userdata_records(records,**({'collapse_duplicate_versions':True} if a.profile=='center' else {}))
                    artifacts['all_results']=digest_value(results)
                row=dict(user=uid,command=command,profile=a.profile,scope=a.scope,iteration=iteration,
                         wall_ns=elapsed,cpu_ns=cpu,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                         startup_ns=startup,stages=copy.deepcopy(t.rows),output=output_digest(result),artifacts=artifacts,
                         environment=env,fixture_manifest_sha256=hashlib.sha256((a.fixture/'fixture-manifest.json').read_bytes()).hexdigest())
                rows.append(row)
                with a.output.open('a') as out:out.write(json.dumps(row,ensure_ascii=False)+'\n')
        for c in captured:
            c.dress_image.close();c.title_image.close()
        print(uid,command,a.scope,len(rows),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True);p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--profile',default='center',choices=['center','client'])
    p.add_argument('--scope',default='query',choices=['query','compute','draw'])
    p.add_argument('--cases',default=json.dumps(MAIN));p.add_argument('--warmup',type=int,default=3)
    p.add_argument('--repeats',type=int,default=20)
    p.add_argument('--verify',action='store_true')
    p.add_argument('--detail-phases',action='store_true')
    run(p.parse_args())
