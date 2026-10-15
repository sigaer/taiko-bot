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
p.add_argument('--mode',choices=['parity','security','data','updates','identity','registration','hiroba','migration'],default='parity')
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
 if event=='sqlite3.connect' and not Path(str(args[0])).resolve().is_relative_to(a.work.resolve()):raise AssertionError('nonfixture DB')
 if event in ('socket.connect','socket.getaddrinfo'):
  __import__('traceback').print_stack(limit=10)
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
from nonebot.matcher import matchers, Matcher
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
sent=[];errors=[];dispatched=[]
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
async def post(matcher:Matcher, exception:Exception|None):
 dispatched.append(type(matcher))
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
 duplicate_versions._group_cache=lambda *args,**kw:chart_identity.build_group_maps([song])
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
async def dispatch(matcher,text,platform,target=True, private=False):
 for k in list(matchers):matchers[k]=[]
 for item in (matcher if isinstance(matcher,(list,tuple)) else [matcher]):matchers[item.priority].append(item)
 sent.clear();errors.clear();dispatched.clear()
 if platform=='onebot':
  msg=Message(text+('[CQ:at,qq=12345]' if target else ''))
  e=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=67890,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':67890,'nickname':'fixture','role':state.get('role','admin')},to_me=True);b=bot
 else:
  e=GroupAtMessageCreateEvent(id='fixture',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True);b=qq
 if private and platform=='onebot':
  from nonebot.adapters.onebot.v11 import PrivateMessageEvent
  e=PrivateMessageEvent(time=1,self_id=90000,post_type='message',message_type='private',sub_type='friend',message_id=1,user_id=67890,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':67890,'nickname':'fixture'},to_me=True)
 elif private:
  from nonebot.adapters.qq import C2CMessageCreateEvent
  e=C2CMessageCreateEvent(id='fixture',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','user_openid':'fixture-user'},to_me=True)
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
from taiko_application.private_input import thaw
from nonebot import on_fullmatch
from nonebot.params import RegexGroup
newq=entry.query_cluster;newm=entry.management_cluster

from importlib import import_module
from dataclasses import replace
from sqlite_fixture import Database
import sqlite3,time,secrets
os.environ['TAIKO_ALLOW_TEST_DB_MUTATION']='1'
os.environ['TAIKO_BOT_SERVICE_TOKEN']='synthetic-service-token'
host=import_module(f'taiko_bot.runtime.player.{a.host}.lifecycle_host')
manual=entry.manual_cluster;identity=entry.identity_cluster;updates=entry.update_cluster
api=import_module('taiko_bot.runtime.player.center.manual_account' if a.host=='center' else 'taiko_bot.manual_account')
db=Database(a.work/'lifecycle_test.db')
principals=['onebot_v11:67890','qq_official:fixture-user']
manual_id='981111111111111111'
api_calls=[]
server={'fail':False,'next_id':0}
def bind_info(principal,*args,**kwargs):
 from taiko_bot.viewer_client import CenterBindSlot
 with sqlite3.connect(db.path) as conn:
  rows=conn.execute('SELECT id,slot_index,is_current,source,visible FROM bind WHERE qq=? ORDER BY slot_index,row_id',(principal,)).fetchall()
  virtual=conn.execute('SELECT current_virtual FROM taiko_bind_identity_state WHERE identity_key=?',(principal,)).fetchone()
 if not rows:return None
 selected=next((r for r in rows if r[2]),rows[0])
 return {'id':selected[0],'visible':selected[4],'currentSlot':0 if virtual and virtual[0] else selected[1],'currentSource':selected[3],
         'bindings':[CenterBindSlot(row[1],row[0],row[4],bool(row[2]),row[3]) for row in rows]}
if a.host=='center':
 entry.get_taiko_db_connection=db.connect
 host.get_taiko_db_connection=db.connect
 from taiko_bot.runtime.player.center import public_score_token as tokens
 tokens.get_taiko_db_connection=db.connect
else:
 provider.fetch_center_bind_info=bind_info;host.fetch_center_bind_info=bind_info
 host._SETTINGS=replace(host._SETTINGS,bot_service_token='synthetic-service-token',viewer_base_url='https://fixture.invalid')
 for module in [manual,identity,updates]:
  if hasattr(module,'_SETTINGS'):module._SETTINGS=host._SETTINGS

class Response:
 def __init__(self,data,status=200):self.data=data;self.status_code=status;self.is_success=status==200
 def json(self):return self.data
 def raise_for_status(self):
  if not self.is_success:raise RuntimeError('synthetic API error')

def manual_api(body):
 actor=body['identityKey'];action=body['action'];taiko_id=body.get('taikoId');result={}
 with sqlite3.connect(db.path) as conn:
  try:
   conn.execute('BEGIN')
   if taiko_id:
    row=conn.execute('SELECT nickname,bot_identity_key FROM taiko_manual_accounts WHERE taiko_id=?',(taiko_id,)).fetchone()
    if not row or row[1]!=actor:return Response({'statusMessage':'没有权限操作该手动账号'},403)
   if action=='create':
    if body.get('requestId'):
     previous=conn.execute('SELECT actor,taiko_id FROM manual_requests WHERE request_id=?',(body['requestId'],)).fetchone()
     if previous:
      assert previous[0]==actor
      return Response({'taikoId':previous[1],'nickname':body['nickname']})
    server['next_id']+=1;taiko_id='98'+str(server['next_id']).zfill(16)
    conn.execute('INSERT INTO taiko_manual_accounts VALUES(?,?,?)',(taiko_id,body['nickname'],actor))
    slot=conn.execute('SELECT COALESCE(MAX(slot_index),0)+1 FROM bind WHERE qq=?',(actor,)).fetchone()[0]
    conn.execute('UPDATE bind SET is_current=0 WHERE qq=?',(actor,))
    conn.execute('INSERT INTO bind(qq,id,slot_index,is_current,source,visible) VALUES(?,?,?,1,\'manual\',1)',(actor,taiko_id,slot))
    result={'taikoId':taiko_id,'nickname':body['nickname']}
    if body.get('requestId'):conn.execute('INSERT INTO manual_requests VALUES(?,?,?)',(body['requestId'],actor,taiko_id))
   elif action=='rename':
    conn.execute('UPDATE taiko_manual_accounts SET nickname=? WHERE taiko_id=?',(body['nickname'],taiko_id));result={'nickname':body['nickname']}
   elif action=='claim-code':
    code='SYNTHETIC-CODE';conn.execute('INSERT OR REPLACE INTO claim_codes VALUES(?,?,0,?)',(code,taiko_id,time.time()+600));result={'code':code}
   elif action=='claim':
    row=conn.execute('SELECT taiko_id,consumed,expires FROM claim_codes WHERE code=?',(body['code'],)).fetchone()
    if not row or row[1] or row[2]<time.time():return Response({'statusMessage':'认领码无效或已过期'},403)
    taiko_id=row[0];conn.execute('UPDATE claim_codes SET consumed=1 WHERE code=?',(body['code'],))
    conn.execute('UPDATE taiko_manual_accounts SET bot_identity_key=? WHERE taiko_id=?',(actor,taiko_id))
    conn.execute('DELETE FROM bind WHERE id=?',(taiko_id,));conn.execute('UPDATE bind SET is_current=0 WHERE qq=?',(actor,))
    slot=conn.execute('SELECT COALESCE(MAX(slot_index),0)+1 FROM bind WHERE qq=?',(actor,)).fetchone()[0]
    conn.execute('INSERT INTO bind(qq,id,slot_index,is_current,source) VALUES(?,?,?,1,\'manual\')',(actor,taiko_id,slot));result={'taikoId':taiko_id,'nickname':'合成鼓手'}
   elif action in ('detach','delete-account'):
    if action=='delete-account' and not body.get('confirmed'):return Response({'statusMessage':'需要确认'},409)
    conn.execute('DELETE FROM bind WHERE qq=? AND id=?',(actor,taiko_id))
    if action=='delete-account':
     conn.execute('DELETE FROM scores WHERE taiko_id=?',(taiko_id,));conn.execute('DELETE FROM taiko_manual_accounts WHERE taiko_id=?',(taiko_id,))
    else:conn.execute('UPDATE taiko_manual_accounts SET bot_identity_key=NULL WHERE taiko_id=?',(taiko_id,))
    result={'ok':True}
   elif action=='score-upsert':
    old=conn.execute('SELECT 1 FROM scores WHERE taiko_id=? AND song_no=? AND level=?',(taiko_id,body['songNo'],body['level'])).fetchone()
    conn.execute('INSERT OR REPLACE INTO scores VALUES(?,?,?,?)',(taiko_id,body['songNo'],body['level'],json.dumps(body['values'])));result={'created':not old}
   elif action=='score-get':
    row=conn.execute('SELECT payload FROM scores WHERE taiko_id=? AND song_no=? AND level=?',(taiko_id,body['songNo'],body['level'])).fetchone();result={'item':json.loads(row[0]) if row else {}}
   elif action=='score-delete':
    if not body.get('confirmed'):return Response({'statusMessage':'需要确认'},409)
    conn.execute('DELETE FROM scores WHERE taiko_id=? AND song_no=? AND level=?',(taiko_id,body['songNo'],body['level']));result={'ok':True}
   elif action=='visibility':conn.execute('UPDATE bind SET visible=? WHERE qq=? AND id=?',(int(body['visible']),actor,taiko_id));result={'ok':True}
   else:raise AssertionError(action)
   if server['fail']:raise RuntimeError('synthetic transaction rollback')
   conn.commit();return Response(result)
  except RuntimeError:
   conn.rollback();return Response({'statusMessage':'合成事务失败，已回滚'},500)

class HTTP:
 def __init__(self,**kwargs):assert kwargs.get('trust_env') is False
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def post(self,url,*,headers,json):
  assert url.endswith('/api/taiko/internal/manual') and headers['X-Taiko-Bot-Token']=='synthetic-service-token'
  api_calls.append(copy.deepcopy(json));return manual_api(json)
api.httpx=types.SimpleNamespace(AsyncClient=HTTP,HTTPError=RuntimeError)

# Real client JSON/stream decoders and retry path, backed by the isolated SQL fixture.
if a.host=='client':
 from taiko_bot import viewer_client, binding_mutation_client
 from taiko_bot.runtime.player.center import bot_binding_mutation as binding_sql
 def binding_payload(principal):
  info=bind_info(principal)
  if not info:return {'ok':True,'found':False,'identityKey':principal,'bindings':[]}
  return {'ok':True,'found':True,'identityKey':principal,'taikoId':info['id'],'currentTaikoId':info['id'],'currentSource':info['currentSource'],'visible':info['visible'],
          'currentSlot':info['currentSlot'],'currentVirtual':info['currentSlot']==0,
          'bindings':[{'taikoId':b.taiko_id,'slot':b.slot,'isCurrent':b.is_current,'source':b.source,'visible':b.visible,'displayName':'合成鼓手' if b.source=='manual' else b.taiko_id,'isManual':b.source=='manual'} for b in info['bindings']]}
 def binding_api(url,body):
  principal=body['identityKey'];action=url.rsplit('/',1)[1]
  operation=None
  if action in ('qq-code','qq-migrate'):
   from taiko_bot.runtime.player.center import bot_qq_migration as migration
   if action=='qq-code':return {'ok':True,'identityKey':principal,'qq':principal.split(':')[1],'code':migration.issue_qq_migration_code(principal,connection_factory=db.connect),'expiresInSeconds':600}
   outcome=migration.migrate_qq_bindings(body['qq'],principal,code=body['code'],connection_factory=db.connect)
   return {**binding_payload(principal),'operation':{'kind':'qq-migrate','qq':body['qq'],'sourceCurrentId':outcome.source_current_id,'firstBinding':outcome.first_binding,'replayed':outcome.replayed}}
  if action=='score-token':
   from taiko_bot.runtime.player.center import public_score_token as center_tokens
   center_tokens.get_taiko_db_connection=db.connect
   issued=center_tokens.issue_public_score_token_for_taiko_id(body['taikoId'],identity_key=principal)
   return {'ok':True,'identityKey':principal,'taikoId':issued['taiko_id'],'token':issued['token'],'tokenMask':issued['token_mask']}
  if action=='current':binding_sql.mutate_bot_binding(principal,'switch',value=body['slot'],connection_factory=db.connect)
  elif action=='bind':binding_sql.mutate_bot_binding(principal,'upsert',value=body['taikoId'],source=body.get('source','wahlap'),connection_factory=db.connect)
  elif action=='visibility':
   result=binding_sql.mutate_bot_binding(principal,'visibility',value=body['visible'],connection_factory=db.connect)
   operation={'kind':'visibility','matched':result.matched}
  elif action=='remove':
   confirm=False
   try:binding_sql.mutate_bot_binding(principal,'remove',value=body['taikoId'],force_last=body.get('forceLast',False),connection_factory=db.connect)
   except binding_sql.BotBindingMutationRejected as error:
    if error.reason!='confirm':raise
    confirm=True
   operation={'kind':'remove','removed':not confirm,'needsConfirmation':confirm,'targetTaikoId':body['taikoId']}
  else:raise AssertionError(url)
  result=binding_payload(principal)
  if operation:result['operation']=operation
  return result
 class StreamResponse(Response):
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def iter_bytes(self,**kwargs):yield json.dumps(self.data).encode()
 class Client:
  def __init__(self,**kwargs):assert kwargs.get('trust_env') is False
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def request(self,method,url,*,headers,params=None,json=None):
   return Response(binding_payload(params['identityKey']) if method=='GET' else binding_api(url,json))
  def stream(self,method,url,*,headers,json):return StreamResponse(binding_api(url,json))
 fixture_http=types.SimpleNamespace(Client=Client,Timeout=lambda *args,**kwargs:None)
 viewer_client.httpx=fixture_http;binding_mutation_client.httpx=fixture_http


# Freeze handler/helper source; unchanged SQL/API libraries are separate tested boundaries.
source=(a.baseline/'plugins/taiko.py').read_text();tree=ast.parse(source)
commands=set('qq_migration_code bind_qq bind_qq_prompt bind bind_confirm bind_switch bind_hiroba hiroba_update bind_remove bind_remove_confirm show_bind unshow_bind manual_create manual_rename manual_claim_code manual_claim manual_detach manual_delete manual_delete_confirm manual_score_upsert manual_score_get manual_score_delete manual_score_delete_confirm update update_typo public_score_token developer_userdata game_login_qr'.split())
old=dict(vars(host));old['__package__']=host.__package__
for key,value in list(old.items()):
 if key.endswith('_SESSIONS'):old[key]={}
# Host helper functions selected by the migration are frozen independently.
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in vars(host)]
for n in nodes:n.decorator_list=[]
text=ast.unparse(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])).replace('from .utils.','from .')
exec(compile(text,'frozen-lifecycle-host','exec'),old)
old['get_taiko_db_connection']=db.connect
from taiko_application.query import SongQueryContext, query_music
from taiko_bot.runtime.player.management_access import load_song_data
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity as chart_identity
old.update(SongQueryContext=SongQueryContext,application_query_music=query_music,load_song_data=load_song_data,fuzz=fuzz)
def query_groups():
 _,by_id,by_title=chart_identity.build_group_maps(json.loads((a.work/'songs/song_data.json').read_text()))
 return by_id,by_title
old['_query_group_maps']=query_groups
for n in tree.body:
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in commands for t in n.targets):exec(compile(ast.Module(body=[n],type_ignores=[]),'frozen-registration','exec'),old)
for n in tree.body:
 if isinstance(n,ast.AsyncFunctionDef) and any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name) and d.func.value.id in commands for d in n.decorator_list):
  for imported in ast.walk(n):
   if isinstance(imported,ast.ImportFrom) and imported.level==1 and imported.module and imported.module.startswith('utils.'):
    imported.module=imported.module.removeprefix('utils.')
  exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),n],type_ignores=[])),'frozen-handler','exec'),old)

results=[]
def reset(*,manual_account=False,virtual=False):
 db.reset();server.update(fail=False,next_id=0);api_calls.clear()
 for index,principal in enumerate(principals):db.seed(principal, (str(int(manual_id)+index),'22222') if manual_account else ('11111','22222'),virtual=virtual)
 for key,value in vars(host).items():
  if key.endswith('_SESSIONS'):value.clear();old[key].clear()
 if a.host=='center':
  from taiko_bot.runtime.player.center import taiko_update_cooldown
  taiko_update_cooldown._last_triggered_at.clear()

def current_matcher(name):return next(getattr(m,name) for m in [identity,manual,updates] if hasattr(m,name))
def effects():return {name:db.rows(name) for name in ['bind','taiko_bind_identity_state','taiko_manual_accounts','scores','claim_codes']}
async def compare(name,command,platform,required,*,manual_account=False,private=False):
 reset(manual_account=manual_account);before=await dispatch(old[name],command,platform,target=False,private=private);prior=effects();requests=copy.deepcopy(api_calls)
 reset(manual_account=manual_account);after=await dispatch(current_matcher(name),command,platform,target=False,private=private)
 assert not before[1] and not after[1],(name,before,after)
 # Claim expiry is the only non-frozen dynamic field in this HTTP fixture.
 for e in [prior,effects()]:
  e['claim_codes']=[row[:3] for row in e['claim_codes']]
 actual=effects();actual['claim_codes']=[row[:3] for row in actual['claim_codes']]
 for call in api_calls:call.pop('requestId',None)
 assert prior==actual and requests==api_calls,(name,prior,actual,requests,api_calls)
 assert before==after,(name,command,before,after)
 if required:assert required in str(after),(name,after)
 results.append({'name':name,'command':command,'platform':platform,'output':after})
 print(a.host,len(results),name,'PASS',flush=True)

async def main():
 for platform in ['onebot','qq']:
  for name,command,required in [
   ('manual_create','新增空白账号 合成昵称','已新增'),('manual_rename','空白账号改名 新名字','已改名'),
   ('manual_claim_code','生成认领码','SYNTHETIC-CODE'),('manual_claim','认领空白账号 INVALID','认领失败'),
   ('manual_score_upsert','录入成绩 10000 表 999000 500 0 0 连打=20','已新增'),
   ('manual_score_get','查看成绩 10000 表','来源：手动录入'),
   ('manual_delete','永久删除空白账号','即将永久删除'),('manual_delete_confirm','确认永久删除空白账号','没有待确认'),
   ('manual_score_delete','删除成绩 10000 表','即将删除'),('manual_score_delete_confirm','确认删除成绩','没有待确认'),
   ('manual_detach','解绑空白账号','已从当前 bot 身份解绑'),
   ('manual_score_upsert','录入成绩 wrong','格式：')]:
   await compare(name,command,platform,required,manual_account=True)
  for name,command,required in [('bind_switch','u0','u0'),('bind_switch','u2','u2'),('show_bind','给看',None),('unshow_bind','不给看',None),('bind_qq_prompt','绑定QQ','迁移验证码'),('bind_remove','删除绑定 u2',None),('bind_confirm','确认绑定',None),('bind_remove_confirm','确认删除绑定',None),('update_typo','taikoupdat',None),('public_score_token','网页成绩token','请私聊'),('qq_migration_code','迁移验证码','请私聊')]:
   await compare(name,command,platform,required)
 assert not violations,violations
 (a.work/'parity.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'lifecycle parity PASS',flush=True)
if a.mode=='migration':
 exec(compile((Path(__file__).parent/'migration_events.py').read_text(),'lifecycle-migration','exec'),globals())
elif a.mode=='hiroba':
 exec(compile((Path(__file__).parent/'hiroba_events.py').read_text(),'lifecycle-hiroba','exec'),globals())
elif a.mode=='registration':
 exec(compile((Path(__file__).parent/'registration_events.py').read_text(),'lifecycle-registration','exec'),globals())
elif a.mode=='identity':
 exec(compile((Path(__file__).parent/'identity_events.py').read_text(),'lifecycle-identity','exec'),globals())
elif a.mode=='updates':
 exec(compile((Path(__file__).parent/'update_events.py').read_text(),'lifecycle-updates','exec'),globals())
elif a.mode=='data':
 exec(compile((Path(__file__).parent/'data_events.py').read_text(),'lifecycle-data','exec'),globals())
elif a.mode=='security':
 exec(compile((Path(__file__).parent/'security.py').read_text(),'lifecycle-security','exec'),globals())
else:asyncio.run(main())
