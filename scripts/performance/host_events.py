"""Real matcher/provider dispatch with synthetic SQL/remote authority and no sends."""
import argparse
import asyncio
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import types
import time
import resource

p=argparse.ArgumentParser()
p.add_argument('--fixture',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
p.add_argument('--profile',choices=['center','client'],default='center')
p.add_argument('--benchmark-output',type=Path)
a=p.parse_args();a.work.mkdir(parents=True,exist_ok=False)
sys.dont_write_bytecode=True
os.chdir(a.work)
os.environ.update(TAIKO_RUNTIME_ROOT=str(a.work),TAIKO_BOT_ROOT=str(a.work),TAIKO_CENTER_ROOT=str(a.work),
 TAIKO_OFFLINE_ROOT=str(a.work),TAIKO_USERDATA_DIR=str(a.work/'userdata'),TAIKO_RUNTIME_ENV_FILE=str(a.work/'absent.env'),
 FEATURE_SWITCH_DATA_DIR=str(a.work/'feature'),BOT_GROUP_WHITELIST_PATH=str(a.work/'whitelist.json'),
 TAIKO_VIEWER_BASE_URL='https://fixture.invalid',TAIKO_VIEWER_DEVELOPER_TOKEN='fixture')
os.environ.update(MPLBACKEND='Agg',MPLCONFIGDIR=str(a.fixture/'mplconfig'))
os.environ['TAIKO_SONG_PROFILE']=a.profile
for name in ('songs','assets'):(a.work/name).symlink_to(a.fixture/name,target_is_directory=True)
main_thread=threading.get_ident();violations=[]
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect'):
  violations.append(event);raise AssertionError(event)
 if event=='open' and isinstance(args[0],(str,os.PathLike)):
  path=Path(args[0]).absolute()
  if any(str(path).startswith(prefix) for prefix in ('/home/sigaer/taiko/','/etc/taiko','/home/sigaer/config/')):
   violations.append(str(path));raise AssertionError('private production read')
sys.addaudithook(guard)
import nonebot
nonebot.init(driver='~fastapi+~httpx',log_level='CRITICAL',taiko_song_profile=a.profile,taiko_song_public_root=str(a.work))
assert nonebot.load_plugin('taiko_bot.runtime.public')
assert nonebot.load_plugin('taiko_bot.runtime.player.entry')
from taiko_bot.runtime.player import entry,b30
try:
 from taiko_bot.runtime.player.render_executor import executor
except ModuleNotFoundError as error:
 if error.name!='taiko_bot.runtime.player.render_executor':raise
 executor=None
from nonebot.adapters.onebot.v11 import Adapter,Bot,Message,GroupMessageEvent
from nonebot.adapters.qq import Adapter as QQAdapter,Bot as QQBot
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.matcher import matchers
from nonebot.message import handle_event,run_postprocessor
from taiko_store import PublicationStore
for module in list(sys.modules.values()):
 if getattr(module,'__name__','').endswith('feature_handler.feature_handler'):
  module.is_feature_enabled=lambda *a,**k:True;module.is_group_allowed=lambda *a,**k:True
nonebot.get_driver().register_adapter(Adapter);nonebot.get_driver().register_adapter(QQAdapter)
bot=Bot(nonebot.get_adapter(Adapter),'90000')
qq=QQBot(nonebot.get_adapter(QQAdapter),'90000',BotInfo(id='90000',token='fixture',secret='fixture'))
sent=[];errors=[];cases=[]
def normalized(value):
 if isinstance(value,bytes):return {'sha256':hashlib.sha256(value).hexdigest()}
 if isinstance(value,str) and value.startswith('base64://'):return normalized(base64.b64decode(value[9:]))
 if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
 if isinstance(value,(tuple,list)):return [normalized(v) for v in value]
 if hasattr(value,'type') and hasattr(value,'data'):return {'type':value.type,'data':normalized(value.data)}
 return str(value)
async def send(self,event,message,**kwargs):
 sent.append(normalized(message if isinstance(message,str) or hasattr(message,'type') else list(message)))
 return {'message_id':1}
bot.send=types.MethodType(send,bot);qq.send=types.MethodType(send,qq)
@run_postprocessor
async def post(exception:Exception|None):
 if exception:errors.append((type(exception).__name__,str(exception)))
payload=json.loads((a.fixture/'fixtures/U05.json').read_text())['current']
state=dict(unbound=False,visible=True,allowed=True,virtual=False,members=['111','222'],profile=0,generation=0)
if a.profile=='center':
 class Cursor:
  def execute(self,sql,params):
   assert threading.get_ident()==main_thread and sql.strip().startswith('SELECT') and 'FOR UPDATE' not in sql
   self.principal=params[0]
  def fetchall(self):return [] if state['unbound'] else [(i+1,self.principal,member,i+1,int(i==state['profile']),'wahlap',int(state['visible'])) for i,member in enumerate(state['members'])]
  def fetchone(self):return self.principal,int(state['virtual'])
  def close(self):pass
 def connection():return types.SimpleNamespace(cursor=Cursor,commit=lambda:None,close=lambda:None)
 entry.get_taiko_db_connection=connection
 for member in ('111','222','333'):
  store=PublicationStore(a.work/'userdata',member)
  with store.exclusive():store.commit({'current':json.dumps(payload).encode()})
 original_require=PublicationStore._require_lock
 def require_main(self,*args,**kwargs):
  assert threading.get_ident()==main_thread,'PublicationStore lease reached a render worker'
  return original_require(self,*args,**kwargs)
 PublicationStore._require_lock=require_main
 from taiko_bot.runtime.player.center import taikob_v2_data
 snapshot=taikob_v2_data.parse_v2_dataset_csv((a.fixture/'songs/constants_id_v2.csv').read_text())
 taikob_v2_data._snapshot=snapshot
 if hasattr(taikob_v2_data,'_local_revision'):taikob_v2_data._fallback_revision=taikob_v2_data._local_revision()
else:
 from taiko_bot.runtime.player.client import provider
 from taiko_bot.viewer_client import CenterBindSlot,ViewerClientError
 from taiko_bot import userdata_provider,public_data
 def bind_info(principal,settings=None):
  if state['unbound']:return None
  return dict(id=state['members'][state['profile']],visible=int(state['visible']),currentSlot=0 if state['virtual'] else 1,
              currentSource='wahlap',bindings=[CenterBindSlot(i+1,m,int(state['visible']),i==state['profile'],'wahlap') for i,m in enumerate(state['members'])])
 provider.fetch_center_bind_info=bind_info
 def remote(kind,source,**kwargs):
  assert threading.get_ident()==main_thread
  if not state['allowed']:raise ViewerClientError('revoked',status_code=403)
  return types.SimpleNamespace(not_modified=False,payload=payload if kind=='current' else {'historyFormat':'raw-v1','snapshots':[]},etag=None,
                               source_view={'kind':'fixture','generation':state['generation']})
 userdata_provider.fetch_private_read=remote
 public_data.ensure_asset_resource_available=lambda *a,**k:(True,'')

async def dispatch(platform,command,*,target=False):
 for key in list(matchers):matchers[key]=[]
 matchers[b30.taikob.priority]=[b30.taikob];sent.clear();errors.clear()
 if platform=='onebot':
  message=Message(command+('[CQ:at,qq=12345]' if target else ''))
  event=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,
   user_id=67890,group_id=123,message=message,original_message=message,raw_message=str(message),font=0,
   sender={'user_id':67890,'nickname':'fixture'},to_me=True);active_bot=bot
 else:
  event=GroupAtMessageCreateEvent(id='fixture',content=command,timestamp='2026-11-11T00:00:00+00:00',
   author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},
   group_id='fixture-group',group_openid='fixture-group',to_me=True);active_bot=qq
 await handle_event(active_bot,event)
 assert not errors,errors
 return copy.deepcopy(sent)

async def run():
 if a.benchmark_output:
  assert a.profile=='center'
  from importlib.metadata import version
  env=dict(python=sys.version,versions={n:version(n) for n in ('Pillow','numpy','pandas','sakura-taiko-core','sakura-taiko-contract')},load=os.getloadavg())
  for uid,command in [('U05','taikob30 v1'),('U05','taikob'),('U08','taikob'),('U12','taikob')]:
   fixture=json.loads((a.fixture/'fixtures'/f'{uid}.json').read_text())
   state.update(unbound=False,visible=True,allowed=True,virtual=False,members=['111','222'],profile=0)
   for member in ('111','222'):
    store=PublicationStore(a.work/'userdata',member)
    with store.exclusive():
     changes={'current':store.stage(json.dumps(fixture['current']).encode())}
     changes.update({'history/'+h['fileName']:store.stage(json.dumps(h['payload']).encode()) for h in fixture['history']})
     store.publish(changes,replace_history=True,filesystem_times={'fileCtimes':{'current':1794369600},'fileMtimes':{'current':1794369600}})
   expected=None
   for iteration in range(-3,20):
    started=time.perf_counter_ns();cpu=time.process_time_ns()
    output=await dispatch('onebot',command)
    elapsed=time.perf_counter_ns()-started;cpu=time.process_time_ns()-cpu
    assert 'sha256' in str(output),output
    if expected is not None:assert expected==output,(uid,command,'unstable handler output')
    expected=output
    if iteration>=0:
     row=dict(user=uid,command=command,profile='center',scope='handler',iteration=iteration,wall_ns=elapsed,cpu_ns=cpu,
              peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,environment=env,output=output,
              stages={'F.matcher':dict(inclusive_ns=elapsed,exclusive_ns=elapsed,calls=1)})
     with a.benchmark_output.open('a') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
   print('real handler',uid,command,'20 measured requests PASS',flush=True)
  if executor:await executor.shutdown()
  assert not violations
  return
 for virtual in (False,True):
  for platform in ('onebot','qq'):
   state.update(unbound=False,visible=True,allowed=True,virtual=virtual,members=['111','222'],profile=0)
   commands=['taikob30 v1','taikob','taikob20 v2 精度'] if a.profile=='center' else ['taikob30','taikob20 v2','taikob20 v2 精度']
   for command in commands:
    output=await dispatch(platform,command)
    assert 'sha256' in str(output) or 'base64://' in str(output),output
    cases.append(dict(case='successful-render',platform=platform,virtual=virtual,command=command,output=output))
   for point in ('prepared','rendered','send','members','order','profile'):
    state.update(unbound=False,visible=True,allowed=True,members=['111','222'],profile=0)
    original_prepare=entry.TinfoHostProvider.prepare
    original_render=b30.execute_b30;original_deliver=entry.deliver
    def revoke():
     state['visible']=False;state['allowed']=False
    if point=='prepared':
     def prepare(self,*args,**kwargs):
      result=original_prepare(self,*args,**kwargs);revoke();return result
     entry.TinfoHostProvider.prepare=prepare
    elif point in ('rendered','members','order','profile'):
     def render(*args,**kwargs):
      result=original_render(*args,**kwargs)
      if point=='members':state['members']=['111','333']
      elif point=='order':state['members']=['222','111']
      elif point=='profile':state['profile']=1
      else:revoke()
      return result
     b30.execute_b30=render
    else:
     async def deliver(*args,**kwargs):revoke();return await original_deliver(*args,**kwargs)
     entry.deliver=deliver
    try:
     output=await dispatch(platform,commands[0])
     assert output and 'sha256' not in str(output) and 'base64://' not in str(output), (point,output)
     assert any(text in str(output) for text in ('查不到','授权已失效')),output
     cases.append(dict(case='revoke-'+point,platform=platform,virtual=virtual,output=output))
    finally:
     entry.TinfoHostProvider.prepare=original_prepare;b30.execute_b30=original_render;entry.deliver=original_deliver
   state.update(unbound=True,visible=True,allowed=True,members=['111','222'],profile=0)
   output=await dispatch(platform,commands[0]);assert '绑定' in str(output) and 'sha256' not in str(output),output
   cases.append(dict(case='unbound',platform=platform,virtual=virtual,output=output))
 if executor:await executor.shutdown()
 assert not violations,violations
 (a.work/'host-events.json').write_text(json.dumps(dict(status='PASS',profile=a.profile,cases=cases,io_violations=violations,
  sql_and_publication_thread='main',executor_closed=not executor._active if executor else True),ensure_ascii=False,indent=2))
 print(a.profile,len(cases),'real matcher/authority cases PASS',flush=True)

asyncio.run(run())
