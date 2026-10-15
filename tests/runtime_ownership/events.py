"""Offline real OneBot/QQ dispatch, frozen handlers, real renderers and native store.
No socket, SQL connection, production file or platform send is permitted.
"""
import argparse, ast, asyncio, base64, copy, hashlib, importlib.util, io, json, os
from pathlib import Path
import runpy, sys, types, shutil
p=argparse.ArgumentParser()
p.add_argument('--host',choices=['center','client'],required=True)
p.add_argument('--guard-smoke',action='store_true')
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
assert public and player and len(public.matcher)==9 and len(player.matcher)==(49 if a.host=="center" else 45)
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
if not (a.work/'assets').exists():(a.work/'assets').symlink_to(a.assets,target_is_directory=True)
(a.work/'songs').mkdir(exist_ok=True)
cfg=runpy.run_path(str(a.application/'packages/taiko-application/tests/fixture.py'))['FIXTURE']
song={'id':278,'song_name':'花漾','song_name_jp':'花漾 ～Flourishing Blossoms～','bpm':'140','type':'南梦宫原创音乐',**{f'level_{i}':'9' if i==5 else '-' for i in range(1,6)}}
(a.work/'songs/song_data.json').write_text(json.dumps([song]));(a.work/'songs/song_alias.json').write_text('[]')
(a.work/'songs/rating_structured_with_ids.json').write_text(json.dumps(cfg['rating_config']))
record=next(x for x in cfg['userdata']['songs'] if int(x['song_no'])==278)
record={**record,'level':5,'high_score':900000,'good_cnt':530,'ok_cnt':11,'stage_cnt':2}
payload={'profile':{'name':'A'},'achievement':{},'dojo':{},'songs':[record]}
state={'allowed':True,'virtual':False,'members':['111','222'],'profile':0,'generation':0}
chart=next(x for x in cfg['rating_config']['songs'].values() if int(x['id'])==278 and int(x['level'])==5)
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
   def fetchall(self):return [(i+1,self.principal,member,i+1,int(i==state['profile']),'wahlap',int(state['allowed'])) for i,member in enumerate(state['members'])]
   def fetchone(self):return self.principal,int(state['virtual'])
   def close(self):pass
  return types.SimpleNamespace(cursor=Cursor,commit=lambda:None,close=lambda:None)
 def publish(member,blob):
  store=PublicationStore(a.work/'userdata',member)
  with store.exclusive():store.publish({'current':store.stage(json.dumps(blob).encode())},filesystem_times={'fileMtimes':{'current':1737000000.125}})
 for i,member in enumerate(['111','222','333']):publish(member,{**payload,'songs':[{**record,'high_score':900000+i*20000}]})
 entry.get_taiko_db_connection=connection
else:
 from taiko_bot.runtime.player.client import provider
 from taiko_bot.viewer_client import CenterBindSlot
 from taiko_bot.private_read_client import PrivateReadReply
 from taiko_bot import userdata_provider, public_data
 def info(principal,settings=None):
  return {'id':state['members'][state['profile']],'visible':int(state['allowed']),'currentSlot':0 if state['virtual'] else 1,'currentSource':'wahlap','bindings':[CenterBindSlot(i+1,m, int(state['allowed']),i==state['profile'],'wahlap') for i,m in enumerate(state['members'])]}
 provider.fetch_center_bind_info=info
 def current():
  return {**payload,'profile':{'name':str(state['profile'])},'songs':[{**record,'high_score':900000+state['generation']*20000}]}
 def remote(kind,source,**kw):
  from taiko_bot.viewer_client import ViewerClientError
  if not state['allowed']:raise ViewerClientError('revoked',status_code=403)
  return types.SimpleNamespace(not_modified=False,payload=current(),etag=None,source_view={'kind':'fixture','generation':state['generation']})
 userdata_provider.fetch_private_read=remote
 public_data.ensure_asset_resource_available=lambda *a,**k:(True,'')
# Original module, not a new fixture renderer.
spec=importlib.util.spec_from_file_location('legacy.utils.drawinfo',a.baseline/'plugins/utils/drawinfo.py')
old_draw=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old_draw;spec.loader.exec_module(old_draw)
if a.host=='client':old_draw.get_cached_userdata=lambda identity:current()
for draw in (old_draw,entry.presentation):
 draw.ROOT_DIR=a.work;draw.USERDATA_DIR=str(a.work/'userdata')
 draw._load_rating_song_index=lambda *a:{(278,5):chart}
 draw._load_rating_const_table=lambda *a:v1.build_const_table(cfg['rating_config']['const_table']['const_to_score'])
 draw._load_note_count_map=lambda:{(278,5):541}
 if a.host=='center':draw.load_v2_snapshot=lambda:types.SimpleNamespace(song_map={})
# Freeze complete old handler; register it on a real matcher for comparison.
old_matcher=on_message(rule=Rule(entry.eligible)) if a.host=='center' else on_regex(entry.PATTERN.pattern)
ns={'__name__':'frozen_tinfo','__package__':'legacy','re':__import__('re'),'music_info':old_matcher,
 'queryMusic':lambda name:entry.query_with_mode(name)[0], 'generate_score_image':old_draw.generate_score_image,
 'extract_plain_text':entry.helpers.extract_plain_text,'print':lambda *a:None}
ns.update(vars(entry.helpers))
ns['music_info']=old_matcher
from nonebot.adapters import Event
ns['MessageEvent']=Event
if a.host=='center':
 frozen=a.application/'packages/taiko-application/experiments/prepared_private_input/frozen_tinfo.py.txt'
 names={'music_info_handle','_is_fuzzy_query_result','_is_accepted_fuzzy_query_result','_is_rejected_fuzzy_query_result','_build_fuzzy_query_hint','_to_jpeg_bytes'}
 ns.update(FUZZY_ACCEPT_THRESHOLD=.75,is_accepted_similarity=lambda ratio,threshold:ratio/100>=threshold)
 ns['_extract_music_info_command_match']=lambda e:entry.PATTERN.match(entry.helpers.extract_plain_text(e))
else:
 frozen=a.baseline/'plugins/taiko.py';names={'music_info_handle','_is_fuzzy_query_result','_build_fuzzy_query_hint','_to_jpeg_bytes'}
 async def ready(*args):return True
 async def authority(*args):return None
 ns.update(_ensure_asset_resources_ready=ready,_require_private_send_authority=authority)
def legacy_resolve(event):
 actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
 principal,_=entry.helpers._resolve_requested_identity_key(event)
 prepared=entry.create_provider().prepare(actor,principal)
 return {'user_id':prepared.authorized_target.user_id}
ns['_resolve_read_bind_target_safe']=legacy_resolve
nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
for n in ast.parse(frozen.read_text()).body:
 if getattr(n,'name',None) in names:n.decorator_list=[];nodes.append(n)
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(frozen),'exec'),ns)
old_matcher.append_handler(ns['music_info_handle'])
rows={'single':[[278,'花漾']],'many':[[278,'花漾'],[7,'Other']],'none':[],'fuzzy-low':[[278,'花漾',50]],'fuzzy-high':[[278,'花漾',90]],'bad-id':[[-1,'bad']],'missing-song':[[999,'missing']],'bad-row':[['oops','bad']],'invalid-return':None}
entry.query_with_mode=lambda name:(copy.deepcopy(rows[name]),None)
async def dispatch(matcher,text,platform):
 for k in list(matchers):matchers[k]=[]
 matchers[matcher.priority]=[matcher];sent.clear();errors.clear()
 if platform=='onebot':
  msg=Message(text+'[CQ:at,qq=12345]')
  e=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=67890,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':67890,'nickname':'fixture'},to_me=True);b=bot
 else:
  e=GroupAtMessageCreateEvent(id='fixture',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True);b=qq
 await handle_event(b,e)
 return copy.deepcopy(sent),copy.deepcopy(errors)
results=[]
async def run():
 for scenario in (('normal',) if a.guard_smoke else ('normal','u0-first','u0-existing','member-change','profile-change','no-history')):
  state.update(allowed=True,virtual=scenario!='normal',members=['111','333'] if scenario=='member-change' else ['111','222'],profile=int(scenario=='profile-change'),generation=int(scenario=='member-change'))
  for platform in ('onebot','qq'):
   for query in (('single','none','fuzzy-low','missing-song') if a.guard_smoke else rows):
    if a.host=='center' and scenario=='u0-first' and query=='single':
     first=a.work/('first-'+platform)
     if first.exists():shutil.rmtree(first)
     first.mkdir()
     for member in state['members']:
      store=PublicationStore(first,member)
      with store.exclusive():store.publish({'current':store.stage(json.dumps(payload).encode())},filesystem_times={'fileMtimes':{'current':1737000000.125}})
     second=a.work/('second-'+platform)
     if second.exists():shutil.rmtree(second)
     shutil.copytree(first,second)
     assert not list(first.glob('u0*')) and not list(second.glob('u0*'))
     os.environ['TAIKO_USERDATA_DIR']=str(first);old_draw.USERDATA_DIR=str(first)
     before=await dispatch(old_matcher,'tinfo '+query,platform)
     os.environ['TAIKO_USERDATA_DIR']=str(second);old_draw.USERDATA_DIR=str(second)
     after=await dispatch(entry.music_info,'tinfo '+query,platform)
     assert list(first.glob('u0*data.json')) and list(second.glob('u0*data.json'))
     os.environ['TAIKO_USERDATA_DIR']=str(a.work/'userdata');old_draw.USERDATA_DIR=str(a.work/'userdata')
    else:
     before=await dispatch(old_matcher,'tinfo '+query,platform)
     after=await dispatch(entry.music_info,'tinfo '+query,platform)
    assert before==after,(a.host,scenario,platform,query,before,after)
    assert bool(after[1])==(query in ('bad-row','invalid-return')),(scenario,query,after)
    assert after[0] or after[1],(scenario,query,'no result')
    if query in ('single','fuzzy-low','fuzzy-high'):assert 'sha256' in json.dumps(after[0]),(query,after)
    results.append({'scenario':scenario,'platform':platform,'query':query,'output':after})
 # Preparation/read/render/send revocation: actual provider checks, no assertion
 # of an atomic network-send/revocation transaction.
 for point in ('before','prepared','rendered','send'):
  state.update(allowed=True,virtual=True,profile=0,members=['111','222'])
  original_prepare=entry.TinfoHostProvider.prepare;original_execute=entry.execute_score;original_deliver=entry.deliver
  if point=='before':state['allowed']=False
  elif point=='prepared':
   def prepare(self,*args,**kwargs):
    result=original_prepare(self,*args,**kwargs);state['allowed']=False;return result
   entry.TinfoHostProvider.prepare=prepare
  elif point=='rendered':
   def execute(*args,**kwargs):
    result=original_execute(*args,**kwargs);state['allowed']=False;return result
   entry.execute_score=execute
  else:
   async def deliver(*args,**kwargs):state['allowed']=False;return await original_deliver(*args,**kwargs)
   entry.deliver=deliver
  try:
   output=await dispatch(entry.music_info,'tinfo single','onebot')
   assert not output[1] and len(output[0])==1 and '查不到' in str(output[0]),(point,output)
   results.append({'revocation':point,'output':output})
  finally:entry.TinfoHostProvider.prepare=original_prepare;entry.execute_score=original_execute;entry.deliver=original_deliver
 for change in ('members','order','profile'):
  state.update(allowed=True,virtual=True,profile=0,members=['111','222'])
  host=entry.create_provider();prepared=host.prepare('onebot_v11:67890','onebot_v11:12345')
  if change=='members':state['members']=['111','333']
  elif change=='order':state['members']=['222','111']
  else:state['profile']=1
  try:host.verify(prepared)
  except TinfoDenied:pass
  else:raise AssertionError('stale '+change+' authorized')
  results.append({'stale_target':change,'rejected':True})
asyncio.run(run())
assert not violations
(a.work/'events.json').write_text(json.dumps({'host':a.host,'cases':len(results),'results':results,'io_violations':violations,'application_guard':True},ensure_ascii=False,indent=2))
print(json.dumps({'host':a.host,'cases':len(results),'status':'PASS'}))
