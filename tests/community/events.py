"""Offline real events + frozen handler parity. Run under the bounded QA runner.
Arguments: center|client frozen-legacy-source.py scratch-directory.
No database/network/process or production file access is permitted.
"""
import ast, asyncio, base64, copy, hashlib, importlib, inspect, io, json, os, sys, types
from pathlib import Path
host, baseline, scratch = sys.argv[1:4]
work=Path(scratch).resolve();work.mkdir(parents=True,exist_ok=True);os.chdir(work)
os.environ.update(TAIKO_BOT_ROOT=str(work),TAIKO_CENTER_ROOT=str(work),TAIKO_RUNTIME_ENV_FILE=str(work/'absent.env'),QQ_MARKDOWN_IMAGE_CACHE_DIR=str(work/'media'),QQ_MARKDOWN_IMAGE_BASE_URL='https://fixture.invalid/media')
violations=[]
def guard(event,args):
 if event in ('socket.connect','socket.getaddrinfo','sqlite3.connect','subprocess.Popen'):
  violations.append(event);raise AssertionError('Forbidden IO: '+event)
 if event=='open' and isinstance(args[0],str) and args[0].startswith(('/home/sigaer/','/opt/','/etc/taiko')):
  violations.append('production file');raise AssertionError('Production file')
sys.addaudithook(guard)
import nonebot
nonebot.init(driver='~fastapi+~httpx',log_level='ERROR',taiko_song_profile=host,taiko_song_public_root=str(work))
p=nonebot.load_plugin('taiko_bot.runtime.community.community_entry');assert p and len(p.matcher)==16
assert 'plugins.taiko' not in sys.modules
assert len(nonebot.get_plugin('public').matcher)==9
assert len(nonebot.get_plugin('entry').matcher)==(49 if host=='center' else 45)
count=sum(len(v) for v in nonebot.matcher.matchers.values())
assert nonebot.require('taiko_bot.runtime.community.community_entry') is p.module
assert sum(len(v) for v in nonebot.matcher.matchers.values())==count
mods={n:importlib.import_module(f'taiko_bot.runtime.community.{host}.{n}') for n in ('draw_guess','cover','compat')}
from PIL import Image
Image.init()
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.adapters.qq import Adapter as QA, Bot as QB
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher, matchers
from nonebot.message import handle_event, run_postprocessor
nonebot.get_driver().register_adapter(Adapter);nonebot.get_driver().register_adapter(QA)
bot=Bot(nonebot.get_adapter(Adapter),'90000');qq=QB(nonebot.get_adapter(QA),'90000',BotInfo(id='90000',token='fixture',secret='fixture'))
def event(text='',group=10,user=100,platform='onebot',image=False,role='member'):
 if platform=='qq':return GroupAtMessageCreateEvent(id='fixture',content=text,timestamp='2026-10-15T00:00:00+00:00',author={'id':str(user),'member_openid':str(user),'bot':False,'member_role':'member'},group_id=str(group),group_openid=str(group),to_me=True)
 msg=Message(text)
 if image:msg+=MessageSegment('image',{'file':'fixture-image','url':'https://fixture.invalid/image'})
 return GroupMessageEvent(time=1,self_id=90000,post_type='message',sub_type='normal',user_id=int(user),message_id=1,message_type='group',message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':int(user),'nickname':'fixture','role':role},group_id=int(group),to_me=True)
raw=io.BytesIO();Image.new('RGB',(33,47),(40,120,230)).save(raw,'PNG');PNG=raw.getvalue()
(work/'songs').mkdir(exist_ok=True)
(work/'songs/song_data.json').write_text(json.dumps([{'id':1,'song_name':'合成歌','song_name_jp':'合成歌'},{'id':2,'song_name':'另一首','song_name_jp':'另一首'}]))
(work/'songs/song_alias.json').write_text('[]')
class HTTP:
 fail=False; content=PNG
 def __init__(self,**kwargs):pass
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def get(self,url):
  if self.fail:raise RuntimeError('synthetic download failure')
  return types.SimpleNamespace(content=self.content,raise_for_status=lambda:None)
async def api(self,name,**kwargs):
 await asyncio.sleep(0)
 if name=='get_group_info':return {'group_name':'fixture-group'}
 if name=='get_image':return {'url':'https://fixture.invalid/image'}
 raise AssertionError(name)
bot.call_api=types.MethodType(api,bot)
def norm(v):
 if isinstance(v,io.BytesIO):v=v.getvalue()
 if isinstance(v,bytes):return hashlib.sha256(v).hexdigest()
 if isinstance(v,str) and v.startswith('base64://'):return norm(base64.b64decode(v[9:]))
 if hasattr(v,'type') and hasattr(v,'data'):return {'type':v.type,'data':norm(v.data)}
 if isinstance(v,dict):return {k:norm(x) for k,x in v.items()}
 if isinstance(v,(list,tuple,Message)):return [norm(x) for x in v]
 return v
class Capture:
 def __init__(self):self.sent=[]
 async def send(self,value=None,**kw):self.sent.append((norm(value),kw))
 async def finish(self,value=None,**kw):await self.send(value,**kw);raise FinishedException

# Compile captured baseline handlers and all still-consumed helpers. No old
# module is imported and no old matcher is registered in the live dispatcher.
source=ast.parse(Path(baseline).read_text());frozen={};handlers={}
# Registration declarations preserve matcher type, rule, priority, permission
# and block exactly; handler synchronization does not alter dispatch order.
old_assignments={t.id:n.value for n in source.body if isinstance(n,ast.Assign) for t in n.targets if isinstance(t,ast.Name)}
for module in mods.values():
 for node in ast.parse(Path(module.__file__).read_text()).body:
  if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and getattr(node.value.func,'id','') in ('on_message','on_regex','on_fullmatch'):
   name=node.targets[0].id
   assert ast.dump(node.value)==ast.dump(old_assignments[name]),name
from nonebot.message import _event_preprocessors
owned_preprocessors=[item for item in _event_preprocessors if item.call.__module__.startswith('taiko_bot.runtime.community.')]
assert len(owned_preprocessors)==(2 if host=='center' else 0)

for name,module in mods.items():
 ns=dict(vars(module));nodes=[];hs={}
 for node in source.body:
  if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  owners=[d.func.value.id for d in node.decorator_list if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and isinstance(d.func.value,ast.Name)]
  owner=next((o for o in owners if hasattr(module,o) and isinstance(getattr(module,o),type) and issubclass(getattr(module,o),Matcher)),None)
  if (node.name in ns and not owners) or owner:
   n=copy.deepcopy(node);n.decorator_list=[]
   if owner:n.name='frozen_'+owner;hs[owner]=n.name
   nodes.append(n)
 exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])), 'frozen-community','exec'),ns)
 # Query kernel already moved in prior batches; these tests freeze handlers and
 # community state, exercising the same separately tested public query owner.
 ns['_query_music_with_mode']=module._query_music_with_mode
 frozen[name]=ns;handlers[name]=hs

def setup(ns,tag):
 root=work/tag
 import shutil
 if root.exists():shutil.rmtree(root)
 root.mkdir()
 if 'DRAW_GUESS_DATA_DIR' in ns:
  ns.update(DRAW_GUESS_DATA_DIR=root,DRAW_GUESS_DB_PATH=root/'records.json',DRAW_GUESS_IMAGE_DIR=root/'images',DRAW_GUESS_TEMPLATE_PATH=root/'template.png',DRAW_GUESS_DB_LOCK=asyncio.Lock(),DRAW_GUESS_MAKE_SESSIONS={},DRAW_GUESS_GROUP_SESSIONS={})
  (root/'template.png').write_bytes(PNG)
 if 'COVER_DIR' in ns:ns['COVER_DIR']=root
 ns['httpx']=types.SimpleNamespace(AsyncClient=HTTP)
 ns['_now_ts']=lambda:1000
 ns['apply_switch']=lambda *args:True
 ns['_upload_cover_to_oss']=lambda path:(True,'oss://synthetic/'+path.name)
 ns['write_admin_action_log']=lambda **kwargs:None
 # Stable rasterizer output still covers list construction in handlers.
 ns['render_draw_guess_list_image']=lambda *args:PNG
 return root
async def invoke(name,owner,text='',groups=(),group=10,user=100,image=False,old=False,platform='onebot',role='member'):
 module=mods[name];ns=frozen[name] if old else vars(module)
 fn=ns[handlers[name][owner]] if old else getattr(module,owner).handlers[0].call
 cap=Capture();e=event(text,group,user,platform,image,role)
 supplied={'matcher':cap,'event':e,'bot':bot,'groups':groups,'reg_group':groups}
 original=ns.get(owner);ns[owner]=cap
 try:
  try:await fn(**{k:supplied[k] for k in inspect.signature(fn).parameters})
  except FinishedException:pass
 finally:ns[owner]=original
 return cap.sent
async def scenario(old):
 ns=frozen['draw_guess'] if old else vars(mods['draw_guess']);setup(ns,'draw-old' if old else 'draw-new')
 results=[]
 async def call(owner,text='',groups=(),**kwargs):
  out=await invoke('draw_guess',owner,text,groups,old=old,**kwargs);results.append(out);return out
 out=await call('draw_guess_start','猜太鼓歌名');assert '暂无可用' in str(out)
 await call('draw_guess_make_start','画太鼓歌名',('',))
 await call('draw_guess_make_router','1')
 await call('draw_guess_make_router','绘图')
 out=await call('draw_guess_make_router','',image=True);assert '图片已上传' in str(out),out
 assert not ns['DRAW_GUESS_MAKE_SESSIONS']
 record=await ns['_get_draw_guess_record'](1);assert record['song_ids']==[1] and record['active']
 if not old:
  viewed=await invoke('draw_guess','draw_guess_view','查看你画我猜id1',('1',));assert viewed and 'image' in str(viewed)
 elif host=='center':
  try:await invoke('draw_guess','draw_guess_view','查看你画我猜id1',('1',),old=True)
  except NameError as error:assert "event" in str(error)
  else:raise AssertionError('Frozen baseline defect unexpectedly absent')
 await call('draw_guess_mine','我的你画我猜')
 await call('draw_guess_start','猜太鼓歌名')
 out=await call('draw_guess_start','猜太鼓歌名');assert '尚有' in str(out)
 await call('draw_guess_start','猜太鼓歌名',group=11)
 assert len(ns['DRAW_GUESS_GROUP_SESSIONS'])==2
 await call('draw_guess_answer','猜2',('2',))
 out=await call('draw_guess_answer','猜1',('1',));assert '恭喜' in str(out)
 assert len(ns['DRAW_GUESS_GROUP_SESSIONS'])==1
 for _ in range(5):await call('draw_guess_answer','猜2',('2',),group=11)
 assert not ns['DRAW_GUESS_GROUP_SESSIONS']
 rec=await ns['_get_draw_guess_record'](1);assert rec['guess_correct_count']==1 and rec['guess_wrong_count']==6
 await call('draw_guess_rank','你画我猜排行')
 await call('draw_guess_rank','你画我猜排行 -a')
 await call('draw_guess_rank','你画我猜排行 invalid')
 await call('draw_guess_like','',('1',));await call('draw_guess_like','',('99',))
 for _ in range(5):await call('draw_guess_report','',('1',))
 rec=await ns['_get_draw_guess_record'](1);assert rec['report_count']==5 and not rec['active']
 await call('draw_guess_make_start','画太鼓歌名',('',));await call('draw_guess_make_router','0')
 assert not ns['DRAW_GUESS_MAKE_SESSIONS']
 await call('draw_guess_make_start','画太鼓歌名',('',))
 for session in ns['DRAW_GUESS_MAKE_SESSIONS'].values():session['updated_at']=-1000
 out=await call('draw_guess_make_router','1');assert '流程已结束' in str(out)
 await call('draw_guess_manual_exit','0')
 # Atomic JSON increments under concurrent calls, no lost updates.
 await asyncio.gather(*(ns['_update_draw_guess_record_counters'](1,like_delta=1) for _ in range(12)))
 assert (await ns['_get_draw_guess_record'](1))['like_count']==13
 data=json.loads(ns['DRAW_GUESS_DB_PATH'].read_text())
 for item in data['records']:item.pop('created_at',None)
 return results,data
async def cover_scenario(old):
 ns=frozen['cover'] if old else vars(mods['cover']);root=setup(ns,'cover-old' if old else 'cover-new');audits=[];ns['write_admin_action_log']=lambda **kw:audits.append(kw)
 results=[]
 async def call(sid='1',image=True):
  value=await invoke('cover','cover_cmd','cover'+sid,(sid,),image=image,old=old);results.append(value);return value
 assert '不存在' in str(await call('999'))
 assert '附带' in str(await call(image=False))
 HTTP.fail=True;assert '下载图片失败' in str(await call());HTTP.fail=False
 HTTP.content=b'not image';assert '处理或保存' in str(await call());HTTP.content=PNG
 value=await call();assert '上传成功，并已同步' in str(value)
 path=root/'1.png'
 with Image.open(path) as im:assert im.size==(400,400) and im.format=='PNG'
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 assert '已存在' in str(await call())
 ns['_upload_cover_to_oss']=lambda path:(False,'synthetic OSS failure')
 assert '同步到OSS失败' in str(await call('2'))
 if host=='center':assert len(audits)==2 and [a['extra']['oss_synced'] for a in audits]==[True,False]
 return results,digest,audits

sent=[];errors=[];recorded=[]
async def send(self,event,message,**kwargs):sent.append(norm(message));return {'message_id':1}
bot.send=types.MethodType(send,bot);qq.send=types.MethodType(send,qq)
@run_postprocessor
async def post(matcher:Matcher,exception:Exception|None):
 if exception:errors.append(type(exception).__name__+':'+str(exception))
for module in list(sys.modules.values()):
 if getattr(module,'__name__','').endswith('feature_handler.feature_handler'):
  module.is_feature_enabled=lambda *args,**kw:True;module.is_group_allowed=lambda *args,**kw:True
assert nonebot.load_plugin('nonebot_plugin_method_calls')
from nonebot_plugin_method_calls import recorder
async def enqueue(value):recorded.append(value)
recorder.enqueue_record=enqueue
async def dispatch(text,platform='onebot',**kw):
 sent.clear();errors.clear();recorded.clear()
 e=event(text,platform=platform,**kw)
 await handle_event(qq if platform=='qq' else bot,e)
 assert not errors,errors
 return copy.deepcopy(sent),copy.deepcopy(recorded)
async def main():
 before,data=await scenario(True);after,newdata=await scenario(False)
 assert before==after,'draw message parity';assert data==newdata,'draw JSON parity'
 before=await cover_scenario(True);after=await cover_scenario(False)
 # Pillow decoding failures include object addresses; assert that failure state
 # independently above and compare every deterministic branch and image hash.
 assert before[0][:3]==after[0][:3] and before[0][4:]==after[0][4:]
 assert before[1:]==after[1:],'cover PNG/audit parity'
 setup(vars(mods['draw_guess']),'dispatch-draw')
 # The router precedes ordinary commands and consumes exactly one reply.
 out,counts=await dispatch('画太鼓歌名');assert len(out)==1 and len(counts)==1,(out,counts)
 out,counts=await dispatch('ping');assert len(out)==1 and not counts,(out,counts)
 await dispatch('0')
 out,counts=await dispatch('猜太鼓歌名');assert len(out)==1 and len(counts)==1
 out,counts=await dispatch('开发者数据 token 1','qq');assert len(out)==1 and not counts
 if host=='center':
  annual=importlib.import_module('taiko_bot.runtime.community.center.annual_report_command')
  async def card(identity):return PNG
  annual.fetch_annual_card=card
  annual.cache_markdown_image_url=lambda *args,**kw:'https://fixture.invalid/annual.png'
  for i,alias in enumerate(sorted(annual.COMMANDS)):
   out,counts=await dispatch(alias,'qq',user='annual-'+str(i))
   assert len(out)==1 and len(counts)==1 and 'keyboard' in str(out) and 'markdown' in str(out),(out,counts)
  out,counts=await dispatch('/ping','qq');assert len(out)==1 and len(counts)==1,(out,counts)
  out,counts=await dispatch('@Sakura 猜太鼓歌名','qq');assert len(out)==1 and len(counts)==1
  out,counts=await dispatch('@Sakura 猜太鼓歌名','qq',user='E866D95E2836EE873E8D168039ABABE0');assert not out and not counts
  out,counts=await dispatch('关闭太鼓你画我猜功能',role='member');assert len(out)==1 and '仅群管理员' in str(out)
 else:
  out,counts=await dispatch('猜太鼓歌名','qq');assert len(out)==1 and not counts
  out,counts=await dispatch('@菌菌 test');assert len(out)==1 and not counts,(out,counts)
  out,counts=await dispatch('关闭太鼓你画我猜功能',role='member');assert not out and not counts
 out,counts=await dispatch('关闭太鼓你画我猜功能',role='admin');assert len(out)==1 and len(counts)==1,(out,counts)
 # Concurrent real dispatch must not create duplicate sessions, awards or OSS
 # writes. Scheduling yields in the mock transport expose the legacy races.
 draw=mods['draw_guess'];setup(vars(draw),'race-draw')
 rid,err=await draw._create_draw_guess_record(song_title='合成歌',song_ids=[1],uploader={'qq':'100','nickname':'fixture','group_id':'10','group_name':'fixture-group'},image_bytes=PNG)
 assert rid==1 and err is None
 sent.clear();errors.clear();recorded.clear()
 await asyncio.gather(*(handle_event(bot,event('猜太鼓歌名')) for _ in range(2)))
 assert not errors and len(sent)==2 and sum('尚有' in str(v) for v in sent)==1,(sent,errors)
 sent.clear();recorded.clear()
 await asyncio.gather(*(handle_event(bot,event('猜1',user=u)) for u in (100,101)))
 assert not errors and sum('恭喜' in str(v) for v in sent)==1,(sent,errors)
 assert (await draw._get_draw_guess_record(1))['guess_correct_count']==1
 cover=mods['cover'];setup(vars(cover),'race-cover');uploads=[]
 cover._upload_cover_to_oss=lambda path:(uploads.append(path.name) or True,'synthetic')
 sent.clear();errors.clear();recorded.clear()
 await asyncio.gather(*(handle_event(bot,event('cover1',image=True)) for _ in range(2)))
 assert not errors and uploads==['1.png'],(errors,uploads)
 assert len(sent)==2 and sum('已存在' in str(v) for v in sent)==1,sent
 # Preserve non-command diagnostics without adding a second bot response.
 sent.clear();errors.clear();recorded.clear()
 if host=='client':
  from contextlib import redirect_stdout
  e=event('');e.message.append(MessageSegment.json('{"synthetic":true}'))
  capture=io.StringIO()
  with redirect_stdout(capture):await handle_event(bot,e)
  assert 'synthetic' in capture.getvalue()
 else:
  from nonebot.adapters.qq import MessageSegment as QS
  e=event('',platform='qq');e.get_message().append(QS.markdown('synthetic-markdown'))
  assert mods['compat']._markdown_message_rule(e)
  assert mods['compat']._extract_markdown_payloads(e.get_message())
  await handle_event(qq,e)
 assert not sent and not errors and not recorded,(sent,errors,recorded)
 from taiko_bot.runtime.community.concurrency import _pending
 assert not _pending
 assert not violations,violations
 print('PASS',host,'16 registrations; frozen draw/cover messages, JSON, PNG SHA256, OSS/audit; real dispatch, priority, permission, silence, statistics; concurrent JSON increments')
asyncio.run(main())
