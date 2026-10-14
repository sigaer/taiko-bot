"""Offline real OneBot/QQ dispatch, frozen handlers, real renderers and native store.
No socket, SQL connection, production file or platform send is permitted.
"""
import argparse, ast, asyncio, base64, copy, hashlib, importlib.util, io, json, os
from pathlib import Path
import runpy, sys, types, shutil, re
p=argparse.ArgumentParser()
p.add_argument('--host',choices=['center','client'],required=True)
p.add_argument('--guard-smoke',action='store_true')
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
assert public and player and len(public.matcher)==9 and len(player.matcher)==4
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
state={'unbound':False,'visible':True,'allowed':True,'virtual':False,'members':['111','222'],'profile':0,'generation':0}
chart=next(x for x in cfg['rating_config']['songs'].values() if int(x['id'])==278 and int(x['level'])==5)
# Expand only the public chart vectors and synthetic scores.
base_chart=copy.deepcopy(next(iter(cfg['rating_config']['songs'].values())))
base_roll=copy.deepcopy(cfg['roll_catalog'][0])
charts={}; songs=[]; rolls=[]; records=[]
for i in range(45):
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
from taiko_bot.runtime.player import recommendation as rec
if a.mode=='security':
 exec(compile((Path(__file__).parent/'security.py').read_text(),'security.py','exec'),globals())
 raise SystemExit(0)
from freeze import freeze
freeze(a.host,a.baseline,a.work/'frozen_rec')
sys.path.insert(0,str(a.work))
import frozen_rec.score_calculator as old_calc
import frozen_rec.target_recommend as old_target
import frozen_rec.target_render as old_render
old_matcher=on_regex(rec.taikorec.__dict__.get('pattern',rf'^(?:{rec.ALIASES}).*$'),flags=re.IGNORECASE)
from taiko_application.commands import RecommendationPorts, CommandContext, CommandResult
# Freeze the old Application executor as well, independently of the new parser.
old_application=a.application/'tests/recommendation/frozen_application.py.txt'
app_ns={'__name__':'frozen_recommendation_application','__package__':'taiko_application.commands'}
sys.modules[app_ns['__name__']]=types.ModuleType(app_ns['__name__'])
sys.modules[app_ns['__name__']].__dict__.update(app_ns)
exec(compile(old_application.read_text(),str(old_application),'exec'),sys.modules[app_ns['__name__']].__dict__)
old_execute=sys.modules[app_ns['__name__']].execute_recommendation
ns=dict(vars(entry.helpers))
ns.update(__name__='frozen_recommendation',__package__='frozen_rec',re=re,MessageEvent=Event,
    taikorec=old_matcher,RecommendationPorts=RecommendationPorts,CommandContext=CommandContext,
    execute_recommendation=old_execute,DIM_MAP=__import__(f'taiko_bot.runtime.player.{a.host}.recommendation_support.aliases',fromlist=['DIM_MAP']).DIM_MAP,
    FONT_PATH='assets/fonts/DDFont.ttf',ASSETS_DIR=a.work/'assets',_SETTINGS=__import__('taiko_bot.settings',fromlist=['get_settings']).get_settings(),
    TAIKOREC_COMMAND_EXTRACT_RE=re.compile(rf'^(?:{rec.ALIASES})\s*(.*)$',re.IGNORECASE),
    compute_recommendations_for_user=old_calc.compute_recommendations_for_user,
    generate_recommend_image=old_calc.generate_recommend_image,
    compute_target_recommendations_for_user=old_target.compute_target_recommendations_for_user,
    parse_target_recommendation_request=old_target.parse_target_recommendation_request,
    target_recommendation_displays=old_target.target_recommendation_displays,
    render_target_recommendation_image_bytes=old_render.render_target_recommendation_image_bytes,
    _deliver_application_command=entry.deliver,logger=nonebot.logger)
async def ready(*args):return True
async def authority(*args):return None
ns.update(_ensure_asset_resources_ready=ready,_require_private_send_authority=authority)
if a.host=='client':ns['ensure_userdata_available']=userdata_provider.ensure_userdata_available
last_provider=None
def legacy_resolve(event):
 global last_provider
 actor=entry.helpers._normalize_identity_key(entry.helpers.get_identity_key(event=event))
 principal,_=entry.helpers._resolve_requested_identity_key(event)
 last_provider=entry.create_provider()
 prepared=last_provider.prepare(actor,principal)
 return {'user_id':prepared.authorized_target.user_id}
ns['_resolve_read_bind_target_safe']=legacy_resolve
ns['_build_missing_userdata_upload_hint']=lambda target:getattr(last_provider,'recommendation_missing_hint','您还未上传数据哦~请先发送“taikoupdate”进行上传')
nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
for n in ast.parse((a.baseline/'plugins/taiko.py').read_text()).body:
 if getattr(n,'name',None)=='taikorec_handle':n.decorator_list=[];nodes.append(n)
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'frozen-handler','exec'),ns)
old_matcher.append_handler(ns['taikorec_handle'])
results=[]
commands=['taikorec',*[f'推荐歌曲 {dim} 3' for dim in ('大歌力','体力','高速处理','精度力','节奏处理','复合处理')],
 '推荐歌曲体力30','taikorec 0','taikorec 51','taikorec 错误维度','推荐歌曲 紫雅 abc','推荐歌曲 紫雅 9星 20',
 '推荐歌曲 全连','推荐歌曲 全良','推荐歌曲 紫雅','推荐歌曲 紫雅 9星','推荐歌曲 粉雅','推荐歌曲 金雅','推荐歌曲 极',
 '推荐歌曲 紫雅 1星']
if a.host=='center':commands+=['歌曲推荐 体力 3']
if a.representative:commands=['taikorec','推荐歌曲体力30','推荐歌曲 全连','推荐歌曲 紫雅 9星']
async def run():
 for virtual in (False, True):
  state['virtual']=virtual
  for platform in ('onebot','qq'):
   for command in commands:
    before=await dispatch(old_matcher,command,platform)
    after=await dispatch(rec.taikorec,command,platform)
    request=rec.parse(command)
    repaired=a.host=='center' and virtual and not isinstance(request,CommandResult) and not request.target_key
    if repaired:
     assert before[1] and before[1][0][0]=='ValueError', (command,before)
     assert not after[1] and 'sha256' in json.dumps(after[0]), (command,after)
    else:
     assert before==after, (a.host,virtual,platform,command,before,after)
     assert not after[1], (command,after[1])
    assert after[0], (command,'no reply')
    assert '计算失败' not in json.dumps(after[0],ensure_ascii=False), (command,after)
    if command in ('taikorec','推荐歌曲体力30','推荐歌曲 全连'):
     assert 'sha256' in json.dumps(after[0]), (command,after)
    results.append(dict(virtual=virtual,platform=platform,command=command,repaired_u0=repaired,output=after))
 print(a.host,len(results),'parity cases PASS',flush=True)
 (a.work/'events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
asyncio.run(run())
