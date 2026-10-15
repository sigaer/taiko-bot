"""Offline real OneBot/QQ dispatch, frozen handlers, real renderers and native store.
No socket, SQL connection, production file or platform send is permitted.
"""
import argparse, ast, asyncio, base64, copy, hashlib, importlib.util, io, json, os
from pathlib import Path
import runpy, sys, types, shutil, re
p=argparse.ArgumentParser()
p.add_argument('--host',choices=['center','client'],required=True)
p.add_argument('--first',action='store_true')
p.add_argument('--datasets',action='store_true')
p.add_argument('--guard-smoke',action='store_true')
p.add_argument('--history-only',action='store_true')
p.add_argument('--edges',action='store_true')
p.add_argument('--faults',action='store_true')
p.add_argument('--native',action='store_true')
p.add_argument('--archive',action='store_true')
p.add_argument('--representative',action='store_true')
p.add_argument('--mode',choices=['parity','security'],default='parity')
p.add_argument('--baseline',type=Path,required=True)
p.add_argument('--work',type=Path,required=True)
p.add_argument('--assets',type=Path,required=True)
p.add_argument('--application',type=Path,required=True)
a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
os.chdir(a.work)
os.environ.update(QQ_MARKDOWN_IMAGE_CACHE_DIR=str(a.work/"markdown-cache"),QQ_MARKDOWN_IMAGE_BASE_URL="https://fixture.invalid/images")
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
nonebot.init(driver='~fastapi+~httpx',log_level='ERROR',taiko_song_profile=a.host,taiko_song_public_root=str(a.work))
public=nonebot.load_plugin('taiko_bot.runtime.public');player=nonebot.load_plugin('taiko_bot.runtime.player.entry')
assert public and player and len(public.matcher)==9 and len(player.matcher)==(49 if a.host=='center' else 45)
assert nonebot.load_plugin("taiko_bot.runtime.community.community_entry")
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
 if isinstance(v,bytes):
  value={'sha256':hashlib.sha256(v).hexdigest()}
  try:
   with Image.open(io.BytesIO(v)) as im:value['size']=list(im.size)
  except (OSError,ValueError):pass
  return value
 if isinstance(v,io.BytesIO):return normalized(v.getvalue())
 if isinstance(v,str) and v.startswith('base64://'):return normalized(base64.b64decode(v[9:]))
 if isinstance(v,str) and 'https://fixture.invalid/images/' in v:
  import re
  def captured_image(match):
   path=a.work/'markdown-cache'/match.group(1)
   return json.dumps(normalized(path.read_bytes()),sort_keys=True)
  return re.sub(r'https://fixture.invalid/images/([^ )]+)',captured_image,v)
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

if a.host=='center' and not (a.work/'assets/name_plate_custom').exists():
 custom_plates=a.work/'assets/name_plate_custom';custom_plates.mkdir()
 for name,color in [('sliver',(180,180,190,255)),('gold',(220,180,40,255)),('rainbow',(120,190,220,255))]:
  Image.new('RGBA',(346,56),color).save(custom_plates/f'name_plate_custom_{name}.png')

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
   def execute(self,sql,params=()):
    assert not globals().get('captured_active'), 'SQL during rendering'
    assert sql.strip().startswith('SELECT') and 'FOR UPDATE' not in sql
    self.sql=sql;self.principal=params[0] if params else ''
    if state.get('showcase_error') and 'web_taiko_bindings' in sql:raise RuntimeError('fixture SQL unavailable')
    if state.get('custom_error') and 'taiko_custom_titles' in sql:raise RuntimeError('fixture custom SQL unavailable')
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def fetchall(self):
    if 'web_taiko_bindings' in self.sql:return state.get('showcase_rows',[('nickname',None)])
    if 'taiko_custom_titles' in self.sql:return state.get('custom_rows',[])
    return [] if state['unbound'] else [(i+1,self.principal,member,i+1,int(i==state['profile']),'wahlap',int(state['visible'])) for i,member in enumerate(state['members'])]
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
from taiko_bot.runtime.player import b30
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
for i,row in enumerate(payload['songs']):
 row.update(ok_cnt=i%12,ng_cnt=i%3,full_combo_cnt=int(i%7==0),dondaful_combo_cnt=int(i%11==0))
songs[1]['shelf_status']=1
songs[2]['level_4']='10+'
(a.work/'songs/song_data.json').write_text(json.dumps(songs))
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

# Public v2 model, identical frozen inputs for both implementations.
import csv, datetime
from sakura_taiko_core.models.calculation import V2SongData
header='id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,stamina,handspeed,burst,complex,rhythm'
(a.work/'songs/constants_id_v2.csv').write_text(header+'\n'+'\n'.join(f"{s['id']},{s['song_name']},oni,600,9.5,10,10.5,8,9,10,11,12" for s in songs)+'\n')
song_map={(s['id'],4):V2SongData(s['id'],4,s['song_name'],600,9.5,10,10.5,8,9,10,11,12) for s in songs}
snapshot=types.SimpleNamespace(song_map=song_map,revision='fixture')
if a.host=='center':
 from taiko_bot.runtime.player.center import taikob_v2_data
 taikob_v2_data.load_v2_snapshot=lambda:snapshot
# Freeze the request clock; center file ctime is independently captured from the
# same synthetic publication by both versions.
real_datetime=datetime.datetime
class FrozenClock(real_datetime):
 @classmethod
 def now(cls,tz=None):
  value=cls(2026,10,14,12)
  return value.replace(tzinfo=tz) if tz else value
 datetime_compat=True
clock=types.SimpleNamespace(**{k:getattr(datetime,k) for k in dir(datetime) if k!="datetime"},datetime=FrozenClock)
sys.path.insert(0,str(a.application/'tests/recommendation'))
from freeze import extract

# Every chart and account below is synthetic. Public input shape is the unchanged
# legacy source dataset, including separate client roll metadata.
score_rows=[dict(id=song['id'],title=song['song_name_jp'],level=level,max_combo=600,initial_points=1650,goku_score=1000000,tenjo_score=990000) for song in songs for level in (1,2,3,4,5) if not (song['id']==10001 and level!=5) and not (song['id']==10002 and level!=4) and song['id']!=10004]
(a.work/'songs/song_score.json').write_text(json.dumps(score_rows))
(a.work/'songs/song_data_with_roll.json').write_text(json.dumps(songs))
(a.work/'songs/song_alias.json').write_text(json.dumps([{'id':10000,'song_name_jp':'Fixture 00','aliases':['测试曲','测试别名']}]))
# Let each frozen/new Host perform its actual cold rebuild.
(a.work/'songs/taiko_goku_onis.json').unlink(missing_ok=True)
seeds={'score_line':{'get_scoreline_entry','available_levels_for_song','parse_scoreline_request','compute_scoreline_result','format_scoreline_message'}}
if a.host=='center':
 seeds['song_rating_target']={'get_song_rating_info','compute_song_rating_target','format_song_rating_target_message'}
 seeds['score_estimator']={'estimate_user_chart_score'}
extract(a.host,a.baseline/'plugins/utils',seeds,a.work/'frozen_score')
for path in (a.work/'frozen_score').glob('*.py'):
 text=path.read_text().replace('Path(__file__).resolve().parents[2]','__import__("taiko_bot.runtime.public.config",fromlist=["root"]).root()')
 text=text.replace('Path("/home/sigaer/taiko/songs/rating_structured_with_ids.json")',repr(str(a.work/'songs/rating_structured_with_ids.json')))
 path.write_text(text)
(a.work/'frozen_score/__init__.py').touch();sys.path.insert(0,str(a.work))
from frozen_score import score_line as old_data
from taiko_bot.runtime.player import scoring as new
from nonebot.params import RegexGroup
ns=dict(vars(new.host));ns.update(vars(old_data));ns.update(__name__='frozen_score.handler',__package__='frozen_score',MessageEvent=Event,RegexGroup=RegexGroup,JSON_PATH=a.work/'songs/taiko_goku_onis.json')
if a.host=='center':
 from frozen_score import song_rating_target as old_rating, score_estimator as old_estimator
 ns.update(vars(old_rating));ns.update(vars(old_estimator))
 ns.update(__name__='frozen_score.handler',__package__='frozen_score')
 async def never():pass
 def legacy_resolve(event):
  actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
  principal,_=entry.helpers._resolve_requested_identity_key(event)
  provider=entry.create_provider()
  try:private=provider.prepare(actor,principal)
  except TinfoDenied as error:return error.status
  return {'user_id':private.authorized_target.user_id}
 ns['_resolve_read_bind_target_safe']=legacy_resolve
 ns['_taiko_bind_usage_message']=entry.helpers._taiko_bind_usage_message
 ns['_build_missing_userdata_upload_hint']=lambda _: '您还未上传数据哦~请先发送“taikoupdate”进行上传'
old_matchers={}
source=(a.baseline/'plugins/taiko.py').read_text()
for node in ast.parse(source).body:
 if isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and n.id in ('score_line_cmd','score_cmd','score_estimate_cmd') for n in node.targets):
  name=node.targets[0].id
  kwargs={k.arg:ast.literal_eval(k.value) for k in node.value.keywords if k.arg!='rule'}
  old_matchers[name]=on_regex(ast.literal_eval(node.value.args[0]),**kwargs)
ns.update(old_matchers)
for node in ast.parse((a.baseline/'plugins/utils/__init__.py').read_text()).body:
 if isinstance(node,ast.FunctionDef) and node.name in ('_load_score_json','_get_initial_points','compute_score'):
  module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
  exec(compile(ast.fix_missing_locations(module),'frozen-points','exec'),ns)
from sakura_taiko_core.score.points import compute_score_from_points
ns['compute_score_from_points']=compute_score_from_points
for node in ast.parse(source).body:
 if not isinstance(node,ast.AsyncFunctionDef):continue
 owner=next((d.func.value.id for d in node.decorator_list if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name)),None)
 if owner not in old_matchers:continue
 node.decorator_list=[]
 module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
 exec(compile(ast.fix_missing_locations(module),'frozen-handler','exec'),ns)
 old_matchers[owner].append_handler(ns[node.name])
if a.host=='center':
 from taiko_bot.runtime.player.center import score_estimate as estimate_host
 original_calculate=estimate_host.calculate
 calculation_active=False
 def calculation_guard(event,args):
  if calculation_active and event in ('open','socket.connect','socket.getaddrinfo'):
   violations.append('calculation IO');raise AssertionError('calculation IO')
 sys.addaudithook(calculation_guard)
 def calculate(*args,**kwargs):
  global calculation_active
  calculation_active=True
  try:return original_calculate(*args,**kwargs)
  finally:calculation_active=False
 estimate_host.calculate=calculate
 original_prepare_estimate=new.host.prepare_estimate
 preparing_estimate=False
 def record_guard(event,args):
  if preparing_estimate and event=='open' and isinstance(args[0],(str,os.PathLike)) and Path(args[0]).resolve().is_relative_to(a.work/'userdata'):
   violations.append('estimate private reread');raise AssertionError('estimate private reread')
 sys.addaudithook(record_guard)
 def prepared_estimate(*args,**kwargs):
  global preparing_estimate
  preparing_estimate=True
  try:return original_prepare_estimate(*args,**kwargs)
  finally:preparing_estimate=False
 new.host.prepare_estimate=prepared_estimate
if a.mode=='security':
 exec(compile((Path(__file__).parent/'security.py').read_text(),'scoring-security.py','exec'),globals())
 raise SystemExit(0)
if a.datasets:
 exec(compile((Path(__file__).parent/'datasets.py').read_text(),'datasets.py','exec'),globals())
 raise SystemExit(0)
results=[]
async def compare(command,platform='onebot',required=None):
 kind='score_line_cmd' if command.startswith('分数线') else 'score_estimate_cmd' if '估分' in command else 'score_cmd'
 before=await dispatch(old_matchers[kind],command,platform,target=False)
 after=await dispatch(getattr(new,kind),command,platform,target=False)
 assert before==after and not after[1],(command,before,after)
 if required:assert required in str(after),(command,after)
 if command=='查分 测试别名 500 100 0':assert '总分：907000' in str(after) and '匹配度' not in str(after),after
 if command=='分数线 id10000 8' and a.host=='center':assert '最低良数：' in str(after),after
 if command=='估分 id10000':assert '稳定分：953000' in str(after) and '冲分：958000' in str(after),after
 results.append(dict(command=command,platform=platform,virtual=state['virtual'],output=after))
 print(a.host,len(results),command,'PASS',flush=True)
async def main():
 commands=['查分 id10000 500 100 20','分数线 极 id10000 30']
 if a.host=='center':commands+=['估分 id10000']
 if not a.first:
  commands += ['查分 表id10000 600 0','/查分 里id10000 0 600 30','查分 测试别名 500 100 0','查分 id10004 1 2','查分 不存在的歌曲 1 2','查分 Fixture 1 2','查分 Fixtur00 1 2', '查分 id10000 0 0','查分 id10000 999999 999999 999999']
  from sakura_taiko_core.score.scoreline import _RATING_ALIAS_TO_KEY
  commands += [f'分数线 {alias} id10000 30' for alias in _RATING_ALIAS_TO_KEY]
  commands += [f'分数线 {diff}id10000 极 {speed}' for diff in ('里','表','松','困难','竹','梅') for speed in (0,60,30.5)]
  commands += ['分数线 极 id10000','分数线','分数线 极','分数线 极 里','分数线 极 id10000 -1','分数线 极 id10000 61','分数线 id10000 8','分数线 id10000 11','分数线 id10000 30','分数线 id10000 0','分数线 id10000 31','分数线 id10001 极','分数线 里id10002 极','分数线 松id10002 极','分数线 id10004 极','分数线 不存在的歌曲 极','分数线 Fixture 极','分数线 Fixtur00 极']
  if a.host=='center':commands += ['估分','/估分 里id10000','估分表谱id10000','估分 id10001','估分 里id10002','估分 id10004','估分 Fixture','估分 不存在的歌曲','估分 Fixtur00']
 for virtual in ((False,) if a.first else (False,True)):
  state['virtual']=virtual
  for platform in ('onebot','qq'):
   for command in commands:
    required='总分：' if command=='查分 id10000 500 100 20' else '目标分：' if command=='分数线 极 id10000 30' else '稳定分：' if command=='估分 id10000' else None
    await compare(command,platform,required)
 assert not violations,violations
 (a.work/'parity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
asyncio.run(main())
