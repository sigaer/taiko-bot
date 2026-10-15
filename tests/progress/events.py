"""Offline real OneBot/QQ dispatch, frozen handlers, real renderers and native store.
No socket, SQL connection, production file or platform send is permitted.
"""
import argparse, ast, asyncio, base64, copy, hashlib, importlib.util, io, json, os
from pathlib import Path
import runpy, sys, types, shutil, re
p=argparse.ArgumentParser()
p.add_argument('--host',choices=['center','client'],required=True)
p.add_argument('--guard-smoke',action='store_true')
p.add_argument('--history-only',action='store_true')
p.add_argument('--representative',action='store_true')
p.add_argument('--mode',choices=['parity','security'],default='parity')
p.add_argument('--baseline',type=Path,required=True)
p.add_argument('--work',type=Path,required=True)
p.add_argument('--assets',type=Path,required=True)
p.add_argument('--application',type=Path,required=True)
a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
os.chdir(a.work)
os.environ.update(TAIKO_BOT_ROOT=str(a.work),TAIKO_CENTER_ROOT=str(a.work),TAIKO_USERDATA_DIR=str(a.work/'userdata'),TAIKO_RUNTIME_ENV_FILE=str(a.work/'absent.env'),TAIKO_VIEWER_BASE_URL='https://fixture.invalid',TAIKO_VIEWER_DEVELOPER_TOKEN='fixture')
violations=[]
application_active=False
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):
  violations.append(event);raise AssertionError(event)
 if application_active and event=='open' and isinstance(args[0],(str,os.PathLike)):
  path=Path(args[0]).resolve()
  allowed=path.is_relative_to(a.assets.resolve()) or path.is_relative_to('/usr/share/fonts') or (path.suffix in ('.py','.pyc','.so') and (path.is_relative_to(sys.prefix) or path.is_relative_to('/usr/lib/python3.11')))
  if not allowed or args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
   violations.append('application IO');raise AssertionError('application IO')
 if event=='open' and isinstance(args[0],str) and args[0].startswith(('/home/sigaer/','/opt/','/etc/taiko')):
  violations.append(args[0]);raise AssertionError('production path')
sys.addaudithook(guard)
from PIL import Image
Image.init()
import nonebot
nonebot.init(driver='~fastapi+~httpx',log_level='CRITICAL',taiko_song_profile=a.host,taiko_song_public_root=str(a.work))
public=nonebot.load_plugin('taiko_bot.runtime.public');player=nonebot.load_plugin('taiko_bot.runtime.player.entry')
assert public and player and len(public.matcher)==9 and len(player.matcher)==6
assert nonebot.require('taiko_bot.runtime.player.entry') is player.module
entry=player.module
import builtins
original_import=builtins.__import__
def import_guard(name,*args,**kwargs):
 if application_active and any(x in name for x in ('taiko_store','merged_bind','userdata','plugins','writer')):
  violations.append('application import '+name);raise AssertionError(violations[-1])
 return original_import(name,*args,**kwargs)
builtins.__import__=import_guard
original_application_execute=entry.execute_score
def pure_execute(*args,**kwargs):
 global application_active
 application_active=True
 try:return original_application_execute(*args,**kwargs)
 finally:application_active=False
entry.execute_score=pure_execute
from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, GroupMessageEvent
from nonebot.adapters.qq import Adapter as QQAdapter, Bot as QQBot
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.matcher import matchers
from nonebot.message import handle_event, run_postprocessor
from nonebot import on_message, on_regex
from nonebot.rule import Rule
from taiko_application.commands import execute_score
from taiko_application.private_input import thaw
from taiko_bot.runtime.player.authority import TinfoDenied
from sakura_taiko_core.rating import v1,v2
from sakura_taiko_core.dimension import v1 as dims
for m in list(sys.modules.values()):
 if getattr(m,'__name__','').endswith('feature_handler.feature_handler'):
  m.is_feature_enabled=lambda *a,**k:True;m.is_group_allowed=lambda *a,**k:True
nonebot.get_driver().register_adapter(Adapter);nonebot.get_driver().register_adapter(QQAdapter)
bot=Bot(nonebot.get_adapter(Adapter),'90000')
qq=QQBot(nonebot.get_adapter(QQAdapter),'90000',BotInfo(id='90000',token='fixture',secret='fixture'))
sent=[];errors=[]
def normalized(v):
 if hasattr(v,'type') and hasattr(v,'data'):return {'type':v.type,'data':normalized(v.data)}
 if isinstance(v,bytes):return {'sha256':hashlib.sha256(v).hexdigest()}
 if isinstance(v,io.BytesIO):return normalized(v.getvalue())
 if isinstance(v,str) and v.startswith('base64://'):return normalized(base64.b64decode(v[9:]))
 if isinstance(v,dict):return {k:normalized(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [normalized(x) for x in v]
 if hasattr(v,'model_dump'):return normalized(v.model_dump())
 return v
async def send(self,event,message,**kwargs):
 sent.append({'message':normalized(message if isinstance(message,str) or hasattr(message,'type') else list(message)),'options':normalized(kwargs)})
 return {'message_id':1}
bot.send=types.MethodType(send,bot);qq.send=types.MethodType(send,qq)
@run_postprocessor
async def post(exception:Exception|None):
 if exception:errors.append((type(exception).__name__,str(exception)))
# Real production-size templates and public fixture, never private data.
if not (a.work/'assets').exists():
 (a.work/'assets').mkdir()
 for asset in a.assets.iterdir():
  if asset.name!='dress':(a.work/'assets'/asset.name).symlink_to(asset,target_is_directory=asset.is_dir())
 # Synthetic non-transparent dress layers exercise the captured private profile.
 for name,color in [('line/line_290.png',(30,40,50,160)),('body/body_290_000.png',(220,40,50,255)),('skin/skin_290_000.png',(40,180,200,255)),('face/face_290_000.png',(230,210,150,255))]:
  path=a.work/'assets/dress/common'/name;path.parent.mkdir(parents=True,exist_ok=True)
  Image.new('RGBA',(160,160),color).save(path)

(a.work/'songs').mkdir(exist_ok=True)
cfg=runpy.run_path(str(a.application/'packages/taiko-application/tests/fixture.py'))['FIXTURE']
song={'id':278,'song_name':'花漾','song_name_jp':'花漾 ～Flourishing Blossoms～','bpm':'140','type':'南梦宫原创音乐',**{f'level_{i}':'9' if i==5 else '-' for i in range(1,6)}}
(a.work/'songs/song_data.json').write_text(json.dumps([song]));(a.work/'songs/song_alias.json').write_text('[]')
(a.work/'songs/rating_structured_with_ids.json').write_text(json.dumps(cfg['rating_config']))
record=next(x for x in cfg['userdata']['songs'] if int(x['song_no'])==278)
record={**record,'level':5,'high_score':900000,'good_cnt':530,'ok_cnt':11,'stage_cnt':2}
payload={'profile':{'name':'A'},'achievement':{},'dojo':{},'songs':[record]}
state={'unbound':False,'visible':True,'allowed':True,'virtual':False,'members':['111','222'],'profile':0,'generation':0}
chart=next(x for x in cfg['rating_config']['songs'].values() if int(x['id'])==278 and int(x['level'])==5)
# Expand only the public chart vectors and synthetic scores.
base_chart=copy.deepcopy(next(iter(cfg['rating_config']['songs'].values())))
base_roll=copy.deepcopy(cfg['roll_catalog'][0])
charts={}; songs=[]; rolls=[]; records=[]
for i in range(65):
 sid=10000+i; title=f'Fixture {i:02}'
 chart={**base_chart, 'id':sid, 'level':4, 'title':title, 'song_name':title, 'song_name_jp':title}
 charts[str(sid)]=chart
 songs.append({'id':sid,'song_name':title,'song_name_jp':title,'level_1':'-','level_2':'-','level_3':'-','level_4':'9','level_5':'-','max_combo':[0,0,0,600,0],'bpm':'140','type':'南梦宫原创音乐'})
 rolls.append({**base_roll,'id':sid,'level':4,'title':title,'title_jp':title,'title_cn':title,'song_name':title,'max_combo':600})
 if i<25: records.append({**record,'song_no':sid,'level':4,'high_score':945000+i*100,'good_cnt':590,'ok_cnt':9,'ng_cnt':1,'full_combo_cnt':0,'dondaful_combo_cnt':0})
cfg['rating_config']['songs']=charts
payload={**payload,'songs':records}
(a.work/'songs/song_data.json').write_text(json.dumps(songs))
(a.work/'songs/rating_structured_with_ids.json').write_text(json.dumps(cfg['rating_config']))
for name in ('song_score.json','taiko_goku_all_levels_stream.json'):
 (a.work/'songs'/name).write_text('[]')
(a.work/'songs/taiko_goku_onis.json').write_text(json.dumps(rolls))
# Freeze original renderer module while substituting only its upstream public imports.
for name in ('legacy','legacy.utils'):
 m=types.ModuleType(name);m.__path__=[];sys.modules[name]=m
metrics=types.ModuleType('legacy.utils.score_calculator')
for module in (v1,dims):
 for name in dir(module):setattr(metrics,name,getattr(module,name))
sys.modules['legacy.utils.score_calculator']=metrics
if a.host=='center':
 from taiko_bot.runtime.player.center import tinfo_provider as provider, duplicate_versions
 from taiko_store import PublicationStore,merge_reference,merged_materialization
 from datetime import datetime
 class Clock(datetime):
  @classmethod
  def now(cls):return cls(2026,10,13,12)
 merged_materialization.datetime=Clock
 merge_reference._SONG_COMBO_MAP_CACHE={(278,5):541}
 from sakura_taiko_core.chart import identity
 duplicate_versions._group_cache=lambda *args,**kw:identity.build_group_maps([song])
 sys.modules['legacy.utils.duplicate_versions']=duplicate_versions
 m=types.ModuleType('legacy.utils.taikob_v2');m._calculate_v2_from_chart=lambda chart,**kw:v2._calculate_v2_from_chart(chart,profile='v2-center-20261010',**kw);sys.modules[m.__name__]=m
 m=types.ModuleType('legacy.utils.taikob_v2_data');m.V2DataSourceError=ValueError;m.load_v2_snapshot=lambda:types.SimpleNamespace(song_map={});sys.modules[m.__name__]=m
 def connection():
  class Cursor:
   def execute(self,sql,params):
    assert sql.strip().startswith('SELECT') and 'FOR UPDATE' not in sql
    self.principal=params[0]
   def fetchall(self):return [] if state['unbound'] else [(i+1,self.principal,member,i+1,int(i==state['profile']),'wahlap',int(state['visible'])) for i,member in enumerate(state['members'])]
   def fetchone(self):return self.principal,int(state['virtual'])
   def close(self):pass
  return types.SimpleNamespace(cursor=Cursor,commit=lambda:None,close=lambda:None)
 def publish(member,blob):
  store=PublicationStore(a.work/'userdata',member)
  with store.exclusive():store.publish({'current':store.stage(json.dumps(blob).encode())},filesystem_times={'fileMtimes':{'current':1737000000.125}})
 for i,member in enumerate(['111','222','333']):publish(member,payload)
 entry.get_taiko_db_connection=connection
else:
 from taiko_bot.runtime.player.client import provider
 from taiko_bot.viewer_client import CenterBindSlot
 from taiko_bot.private_read_client import PrivateReadReply
 from taiko_bot import userdata_provider, public_data
 def info(principal,settings=None):
  if state['unbound']:return None
  return {'id':state['members'][state['profile']],'visible':int(state['visible']),'currentSlot':0 if state['virtual'] else 1,'currentSource':'wahlap','bindings':[CenterBindSlot(i+1,m, int(state['visible']),i==state['profile'],'wahlap') for i,m in enumerate(state['members'])]}
 provider.fetch_center_bind_info=info
 def current():
  return {**payload,'profile':{'name':str(state['profile'])}}
 def remote(kind,source,**kw):
  from taiko_bot.viewer_client import ViewerClientError
  if not state['allowed']:raise ViewerClientError('revoked',status_code=403)
  return types.SimpleNamespace(not_modified=False,payload=current(),etag=None,source_view={'kind':'fixture','generation':state['generation']})
 userdata_provider.fetch_private_read=remote
 public_data.ensure_asset_resource_available=lambda *a,**k:(True,'')
async def dispatch(matcher,text,platform,target=True):
 for k in list(matchers):matchers[k]=[]
 matchers[matcher.priority]=[matcher];sent.clear();errors.clear()
 if platform=='onebot':
  msg=Message(text+('[CQ:at,qq=12345]' if target else ''))
  e=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=67890,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':67890,'nickname':'fixture'},to_me=True);b=bot
 else:
  e=GroupAtMessageCreateEvent(id='fixture',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True);b=qq
 await handle_event(b,e)
 return copy.deepcopy(sent),copy.deepcopy(errors)
from nonebot.adapters import Event
from taiko_bot.runtime.player import progress as progress
# Public synthetic progress tables; current data has independent dress and dojo fields.
(a.work/'songs/song_difficulty.json').write_text(json.dumps({'9.0':[song['id'] for song in songs]}))
(a.work/'songs/music_donda_list.json').write_text(json.dumps({'SS':[{'id':song['id'],'song_name':song['song_name']} for song in songs]}))
for chart in charts.values(): chart['score']=9.0
(a.work/'songs/rating_structured_with_ids.json').write_text(json.dumps(cfg['rating_config']))
songs += cfg['song_catalog']
songs[-1]['shelf_status']='已下架'
(a.work/'songs/song_data.json').write_text(json.dumps(songs))
for year in ('2025','2026'):
 (a.work/f'songs/grade_dojo_nijiiro_{year}_simple.json').write_text(json.dumps({**cfg['grade_payload'],'year':year}))
(a.work/'songs/grade_dojo_nijiiro_history_simple.json').write_text(json.dumps({'versions':{'2024':cfg['grade_payload']}}))
payload['profile']['gameCostume']={'color_limb':0,'color_body':0,'color_face':0}
payload['songs'] += cfg['userdata']['songs']
histories=[]
native_history_reads=[]
if a.host=='center':
 original_store=provider.TinfoHostProvider._store
 def tracked_store(self,*args,**kwargs):
  store=original_store(self,*args,**kwargs);reader=store.reader
  def tracked_reader():
   view=reader();read=view.history_raw
   def tracked_read(name):native_history_reads.append(name);return read(name)
   view.history_raw=tracked_read
   return view
  store.reader=tracked_reader
  return store
 provider.TinfoHostProvider._store=tracked_store
 original_prepare=provider.TinfoHostProvider.prepare
 def bounded_prepare(self,*args,**kwargs):
  result=original_prepare(self,*args,**kwargs)
  if kwargs.get('include_history'):assert len(result.history)<=1,'unrelated history retained'
  return result
 provider.TinfoHostProvider.prepare=bounded_prepare
if a.host=='center':
 for member in ('111','222','333'): publish(member,payload)
else:
 def current(): return payload
 def remote(kind,source,**kw):
  from taiko_bot.viewer_client import ViewerClientError
  if not state['allowed']:raise ViewerClientError('revoked',status_code=403)
  data = {'historyFormat':'raw-v1','snapshots':histories} if kind=='history' else current()
  return types.SimpleNamespace(not_modified=False,payload=data,etag=None,source_view={'kind':'fixture','generation':state['generation']})
 userdata_provider.fetch_private_read=remote
# Independent old source closure, without loading the former NoneBot plugin.
sys.path.insert(0,str(a.application/'tests/recommendation'))
from freeze import extract
seeds={'__init__':{'render_pass_progress_image_bytes','render_progress_image_bytes','render_progress_image_bytes_by_list','render_star_progress_image_bytes'},
 'dani_progress':{'parse_dani_progress_request','render_dani_progress_image_bytes'},
 'progress_catalog':{'available_const_progress_keys','available_pass_progress_keys','available_star_progress_values'}}
extract(a.host,a.baseline/'plugins/utils',seeds,a.work/'frozen_progress')
for path in (a.work/'frozen_progress').glob('*.py'):
 text=path.read_text().replace('Path(__file__).resolve().parents[2]', '__import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()')
 text=re.sub(r'(["\'])/home/sigaer/taiko/([^"\']*)\1',lambda m: 'str(_ROOT / '+repr(m[2])+')',text)
 text=text.replace('from __future__ import annotations\n','from __future__ import annotations\nfrom taiko_bot.runtime.public.config import root\n_ROOT=root()\n',1)
 path.write_text(text)
sys.path.insert(0,str(a.work))
import frozen_progress as old_render
from frozen_progress import dani_progress as old_dani, progress_catalog as old_catalog
from taiko_application.commands.progress import ProgressPorts,execute_progress,prepare_progress
from taiko_application.commands import CommandContext,CommandResult
from nonebot import on_message
from nonebot.rule import Rule
old_matcher=on_message(rule=Rule(progress.eligible)) if a.host=='center' else on_regex(r'^.+进度(?:\s+\d+)?$')
ns=dict(vars(entry.helpers));ns.update(vars(old_render));ns.update(vars(old_dani))
ns.update(__name__='frozen_progress_handler',__package__='frozen_progress',re=re,MessageEvent=Event,
 matcher=old_matcher,ProgressPorts=ProgressPorts,CommandContext=CommandContext,CommandResult=CommandResult,
 execute_progress=execute_progress,prepare_progress=prepare_progress,
 PROGRESS_WITH_PAGE_REGEX=progress.PROGRESS_WITH_PAGE_REGEX,STAR_PROGRESS_REGEX=progress.STAR_PROGRESS_REGEX,
 _load_decimal_progress_set=old_catalog.available_const_progress_keys,_load_pass_progress_set=old_catalog.available_pass_progress_keys,
 _load_star_progress_set=old_catalog.available_star_progress_values,_parse_star_progress_value=lambda v:int(v) if v.isdigit() else progress.STAR_PROGRESS_VALUE_MAP.get(v),
 _load_progress_name_set=lambda:{'SS'},_extract_progress_command_match=progress.extract_match,
 _deliver_application_command=entry.deliver,ASSETS_DIR=a.work/'assets',_SETTINGS=__import__('taiko_bot.settings',fromlist=['get_settings']).get_settings())
async def ready(*args):return True
async def authority(*args):return None
async def legacy_deliver(matcher,event,result):
 if result is not None:return await entry.deliver(matcher,event,result)
ns['_deliver_application_command']=legacy_deliver
ns.update(_ensure_asset_resources_ready=ready,_require_private_send_authority=authority)
if a.host=='client':ns['ensure_userdata_available']=userdata_provider.ensure_userdata_available
last_provider=None
def legacy_resolve(event):
 global last_provider
 actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
 principal,_=entry.helpers._resolve_requested_identity_key(event)
 last_provider=entry.create_provider();private=last_provider.prepare(actor,principal)
 return {'user_id':private.authorized_target.user_id}
ns['_resolve_read_bind_target_safe']=legacy_resolve
for n in ast.parse((a.baseline/'plugins/taiko.py').read_text()).body:
 if isinstance(n,ast.AsyncFunctionDef) and any(ast.unparse(d)=='matcher.handle()' for d in n.decorator_list):
  n.decorator_list=[]
  for constant in ast.walk(n):
   if isinstance(constant,ast.Constant) and constant.value=='/home/sigaer/taiko/assets':constant.value=str(a.work/'assets')
  module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),n],type_ignores=[])
  exec(compile(ast.fix_missing_locations(module),'frozen-handler','exec'),ns)
  old_matcher.append_handler(ns[n.name]);break
# Prevent calculation/rendering from re-reading private files or calling a private provider.
captured_active=False
original_execute=progress.execute_progress
captured_original_import=builtins.__import__
def guarded_import(name,*args,**kwargs):
 if captured_active and (name.startswith('plugins') or 'userdata_provider' in name):raise AssertionError('private/legacy render import')
 return captured_original_import(name,*args,**kwargs)
builtins.__import__=guarded_import
def capture_guard(event,args):
 if captured_active and event=='open' and isinstance(args[0],(str,os.PathLike)):
  if Path(args[0]).resolve().is_relative_to(a.work/'userdata'):
   violations.append('render re-read private data');raise AssertionError(violations[-1])
sys.addaudithook(capture_guard)
def execute(*args,**kwargs):
 global captured_active
 captured_active=True
 try:return original_execute(*args,**kwargs)
 finally:captured_active=False
progress.execute_progress=execute
if a.mode=='security':
 exec(compile((Path(__file__).parent/'security.py').read_text(),'security.py','exec'),globals())
 raise SystemExit(0)
commands=['9星进度','九☆进度 2','9星进度 999','9.0进度','9.0综合进度 2','9.0定数进度','9.0过关进度',
 '8.0综合进度','8.0过关进度','SS进度','ss进度 2','9星进度 0','未知进度','六段进度','虹2025六段进度','虹2024六段进度','虹2026六段进度']
if a.history_only:commands=[]
if a.representative:commands=['9星进度','9.0过关进度','SS进度 2','六段进度']
results=[]
async def main():
 for virtual in (False,True):
  state['virtual']=virtual
  for platform in ('onebot','qq'):
   for command in commands:
    before=await dispatch(old_matcher,command,platform,target=False)
    after=await dispatch(progress.matcher,command,platform,target=False)
    assert before==after,(virtual,platform,command,before,after)
    assert not after[1],(command,after[1])
    if command in ('9星进度','9.0综合进度 2','SS进度','六段进度'):assert 'sha256' in str(after),(command,after)
    results.append(dict(virtual=virtual,platform=platform,command=command,output=after))
    if len(results)%20==0:print(a.host,len(results),'cases checked',flush=True)
 # Historical fallback: lexical file order, irrelevant dojo rows, current precedence,
 # and explicit version boundaries, with exact old/new images and timestamps.
 for virtual in (() if a.representative else (False,True)):
  state['virtual']=virtual
  history_dojo=copy.deepcopy(cfg['userdata']['dojo'])
  history_dojo['scores'][0]['highscore_datetime']='2025-09-01 12:34:56'
  histories[:]=[{'fileName':'data_20250901_123456_000000.json','historyFormat':'raw-v1','capturedAt':'2025-09-01T12:34:56','payload':{'dojo':history_dojo}},
   {'fileName':'data_20250902_000000_000000.json','historyFormat':'raw-v1','capturedAt':'2025-09-02T00:00:00','payload':{'dojo':{'scores':[],'levelList':[]}}}]
  for has_current in (False,True):
   payload['dojo']=copy.deepcopy(cfg['userdata']['dojo']) if has_current else {}
   if a.host=='center':
    for member in ('111','222'):
     store=PublicationStore(a.work/'userdata',member)
     with store.exclusive():
      store.publish({'current':store.stage(json.dumps(payload).encode()),**{'history/'+h['fileName']:store.stage(json.dumps(h['payload']).encode()) for h in histories}})
   state['generation']+=1
   for platform in ('onebot','qq'):
    for command in ('虹2025六段进度','虹2024六段进度','六段进度'):
     before=await dispatch(old_matcher,command,platform,target=False)
     native_history_reads.clear()
     after=await dispatch(progress.matcher,command,platform,target=False)
     if a.host=='center' and has_current:assert not native_history_reads,'current dojo must avoid history reads'
     assert before==after and not after[1],('history',virtual,has_current,platform,command,before,after)
     assert 'sha256' in str(after),(command,after)
     if not a.history_only and not virtual and not has_current and command=='虹2025六段进度':
      baseline=next(r['output'] for r in results if r.get('case') is None and not r['virtual'] and r['platform']==platform and r['command']==command)
      assert baseline!=after,'history fixture must change the rendered dojo section'
     results.append(dict(case='history',virtual=virtual,current_dojo=has_current,platform=platform,command=command,output=after))
 assert not violations,violations
 (a.work/'events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'progress parity PASS',flush=True)
asyncio.run(main())
