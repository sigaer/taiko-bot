"""Dispatch actual host matchers with offline provider fixtures."""

import argparse, asyncio, base64, hashlib, io, json, os, sys, types
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("sandbox", "installed", "images", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument('--host', choices=['center','client'], required=True)
p.add_argument('--source', type=Path)
p.add_argument('--support', type=Path)
p.add_argument('--load-only', action='store_true')
a = p.parse_args()
if a.host == 'center':
    sys.path[:0] = [str(a.source), str(a.support)]
    os.environ.update(PYTHON_MEMORY_RUNTIME_ROOT=str(a.support),
                      PYTHON_MEMORY_METRICS_DIR=str(a.sandbox / 'metrics'),
                      TAIKO_RUNTIME_ENV_FILE=str(a.sandbox / 'absent.env'))
a.sandbox.mkdir(parents=True, exist_ok=True)
os.chdir(a.source)
os.environ.update(
    TAIKO_BOT_ROOT=str(a.source),
    TAIKO_VIEWER_BASE_URL="https://fixture.invalid",
    TAIKO_PUBLIC_DATA_BASE_URL="https://fixture.invalid",
    MPLCONFIGDIR=str(a.sandbox / "mpl"),
)


io_violations = []
in_dispatch = False

def guard(event, args):
    if in_dispatch and event == 'open' and len(args)>2 and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        io_violations.append('dispatch-file-write')
        raise AssertionError('Command attempted a file write')
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        io_violations.append(event)
        raise AssertionError("Forbidden integration IO: " + event)
    if (
        event == "open"
        and isinstance(args[0], str)
        and args[0].startswith(("/home/sigaer/", "/opt/", "/etc/taiko"))
    ):
        io_violations.append(str(args[0]))
        raise AssertionError("Forbidden checkout/private file")


# Redirect only outer filesystem inputs, never application functions. Physical
# opens are still subject to the production-path audit guard below.
redirected = set()
if a.host == "center":
    import builtins
    original_open, original_io_open, original_stat = builtins.open, io.open, os.stat
    def fixture_path(path):
        if isinstance(path, (str, os.PathLike)):
            raw = os.fspath(path)
            prefix = "/home/sigaer/taiko/"
            if raw.startswith(prefix):
                redirected.add(raw)
                return str(a.source / raw[len(prefix):])
        return path
    builtins.open = lambda file, *args, **kwargs: original_open(fixture_path(file), *args, **kwargs)
    io.open = lambda file, *args, **kwargs: original_io_open(fixture_path(file), *args, **kwargs)
    os.stat = lambda path, *args, **kwargs: original_stat(fixture_path(path), *args, **kwargs)
sys.addaudithook(guard)
import nonebot

nonebot.init(driver="~fastapi+~httpx", log_level="ERROR", taiko_song_profile=a.host, taiko_song_public_root=str(a.source))
external_first = nonebot.load_plugin("taiko_bot.runtime.public")
assert external_first is not None and len(external_first.matcher) == 9
assert "plugins.taiko" not in sys.modules
assert not any(name.startswith("plugins.utils") for name in sys.modules)
player = nonebot.load_plugin("taiko_bot.runtime.player.entry")
assert player is not None and len(player.matcher) == 6
plugin = nonebot.load_plugin("plugins.taiko")
assert plugin is not None, "Installed plugin failed to load"
assert not hasattr(plugin.module, 'taikorec')
assert not hasattr(plugin.module, 'matcher')
assert not hasattr(plugin.module, 'taikob')
assert not hasattr(plugin.module, 'trend')
assert not hasattr(plugin.module, 'playtrend')
assert player.module.b30.taikob in player.matcher
assert player.module.trend.trend in player.matcher
assert player.module.trend.playtrend in player.matcher
assert player.module.progress.matcher in player.matcher
assert player.module.recommendation.taikorec in player.matcher
if a.load_only:
    print(a.host, 'full host load PASS; six owned player matchers, zero migrated legacy entries')
    raise SystemExit(0)
module = plugin.module
from importlib.metadata import version
from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent, Message
from nonebot.message import handle_event, run_postprocessor
from nonebot.matcher import matchers
from taiko_application import commands as app
from PIL import Image

assert Path(module.__file__).is_relative_to(a.source if a.host == 'center' else a.installed)
assert Path(app.__file__).is_relative_to(a.installed)
assert version("sakura-taiko-core") == ("0.1.1" if a.host == "center" else "0.1.2")
assert version("sakura-taiko-contract") == "0.1.0"
assert all("/home/sigaer/git/Sakura_bot" not in x for x in sys.path)
import ast, copy
from nonebot import on_regex
from nonebot.rule import Rule
from nonebot.adapters.qq import Adapter as QQAdapter, Bot as QQBot
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.adapters.onebot.v11 import GroupMessageEvent
external = external_first
assert external is not None
new = external.module
assert not hasattr(module,'what_song')
assert len(external.matcher)==9
assert new.what_song.priority == 10 and new.what_song.block
assert Path(new.__file__).is_relative_to(a.installed)
# Host source ownership: no other registration was removed or changed.
reference = (a.source.parent/(a.host+'-reference.py')).read_text()
old_tree=ast.parse(reference)
new_tree=ast.parse(Path(module.__file__).read_text())
def registrations(tree):
 return {ast.unparse(n.targets[0]):ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id.startswith('on_')}
names={'const_query','patterns'}
public=new.catalog_commands
r=registrations(old_tree)
for name in names:
 assert r.pop(name)
 assert not hasattr(module,name)
r.pop('music_info')
r.pop('taikorec')
r.pop('matcher')
r.pop('taikob')
assert r==registrations(new_tree)
assert len(external.matcher)==9
ns=dict(module.__dict__)
# Full frozen original drawing/query module, no replacement calculation or PNG.
frozen=types.ModuleType('plugins.utils.frozen_constant');frozen.__package__='plugins.utils'
sys.modules[frozen.__name__]=frozen
exec(compile((a.source.parent/(a.host+'-constant.py')).read_text(),'<frozen-constant>','exec'),frozen.__dict__)
frozen.BASE=a.source;frozen.RATING_PATH=a.source/'songs/rating_structured_with_ids.json';frozen.SONG_DATA_PATH=a.source/'songs/song_data.json';frozen.FONT_PATH=a.source/'assets/fonts/DDFont.ttf';frozen.PROGRESS_BG_PATH=a.source/'assets/templates/progress_bg.png'
for name in ('DEFAULT_PAGE_SIZE','paginate_rows','query_charts_by_const','render_const_query_image','render_const_query_notice'):ns[name]=getattr(frozen,name)
ns.update(ConstantPorts=app.ConstantPorts,execute_constant=app.execute_constant)
restored=[]
for n in old_tree.body:
 name=getattr(n,'name','')
 if isinstance(n,ast.Assign):name=ast.unparse(n.targets[0])
 handler=isinstance(n,ast.AsyncFunctionDef) and any(any(x+'.handle' in ast.unparse(d) for x in names) for d in n.decorator_list)
 if name in names or name.startswith(('_CHART_CONFIG_','_parse_chart_config_','_collect_chart_config_','_resolve_chart_config_','_sample_chart_config_')) or handler:restored.append(n)
exec(compile(ast.Module(body=restored,type_ignores=[]),'<frozen-catalog-entries>','exec'),ns)
for name in names:
 before,after=ns[name],getattr(public,name)
 assert (before.priority,before.block)==(after.priority,after.block)
# score_cmd and its regex remain untouched in host; no new score matcher.
assert hasattr(module,'score_cmd') and not hasattr(public,'score_cmd')
# Only boundary feature storage and platform sends are substituted.
state={'enabled':True,'tsearch':True};errors=[];sent=[];calls=[]
for m in list(sys.modules.values()):
 if m and getattr(m,'__name__','').endswith('feature_handler.feature_handler'):
  m.is_feature_enabled=lambda *args,**kwargs:state['enabled'] and (state['tsearch'] if 'tsearch' in args or 'tsearch' in kwargs.values() else True)
  m.is_group_allowed=lambda *args,**kwargs:True
# Resource readiness is the outer resource manager, not song matching or fumen selection.
async def ready(*args):return True
ns['_ensure_asset_resources_ready']=ready
new.provider.asset_ready=lambda:(True,'')
new.provider.alias_assets_ready=lambda:(True,'')
orig=app.execute_song
def execute(*args,**kwargs):
 calls.append('execute_song');return orig(*args,**kwargs)
app.execute_song=execute
constant_original=public.execute_constant
def tracked_constant(*args,**kwargs):
 calls.append('execute_constant');return constant_original(*args,**kwargs)
public.execute_constant=tracked_constant
@run_postprocessor
async def capture(exception: Exception|None):
 if exception is not None:errors.append([type(exception).__name__,str(exception)])
nonebot.get_driver().register_adapter(Adapter)
nonebot.get_driver().register_adapter(QQAdapter)
bot=Bot(nonebot.get_adapter(Adapter),'90000')
from nonebot.adapters.qq.config import BotInfo
qq=QQBot(nonebot.get_adapter(QQAdapter),'90000',BotInfo(id='90000',token='synthetic',secret='synthetic'))
def normalized(value):
 if isinstance(value,bytes):
  result={'sha256':hashlib.sha256(value).hexdigest()}
  if value.startswith(b'\x89PNG'):
   with Image.open(io.BytesIO(value)) as im:
    result.update(pixels=hashlib.sha256(im.tobytes()).hexdigest(),dimensions=list(im.size),mode=im.mode)
  return result
 if isinstance(value,io.BytesIO):return normalized(value.getvalue())
 if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
 if isinstance(value,(tuple,list)):return [normalized(v) for v in value]
 if hasattr(value,'model_dump'):return normalized(value.model_dump())
 if hasattr(value,'dict'):return normalized(value.dict())
 if isinstance(value,str) and value.startswith('base64://'):return normalized(base64.b64decode(value[9:]))
 return value
async def send(self,event,message,**kwargs):
 segments = [message] if hasattr(message, 'type') and hasattr(message, 'data') else message if not isinstance(message,str) else [{'text':message}]
 out=[]
 for seg in segments:
  out.append({'type':seg.type,'data':normalized(seg.data)} if hasattr(seg,'type') else seg)
 sent.append({'message':out,'options':normalized(kwargs)})
 return {'message_id':1}
bot.send=types.MethodType(send,bot);qq.send=types.MethodType(send,qq)
results=[]
async def dispatch(matcher,text,platform,enabled=True,mention=False,tsearch=True,expected_error=False):
 for priority,items in list(matchers.items()):matchers[priority]=[]
 matchers[matcher.priority]=[matcher]
 __import__('random').seed(73013);state['enabled']=enabled;state['tsearch']=tsearch;sent.clear();errors.clear();calls.clear()
 if platform=='onebot':
  msg=Message(text)
  if mention:msg=Message('[CQ:at,qq=3889003795]')+msg
  event=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=10001,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':10001,'nickname':'Fixture'},to_me=True)
  target=bot
 else:
  event=GroupAtMessageCreateEvent(id='fixture-message',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True)
  target=qq
 global in_dispatch
 in_dispatch=True
 try:
  await handle_event(target,event)
 finally:in_dispatch=False
 assert not errors or expected_error,(text,platform,errors)
 return copy.deepcopy(sent),list(calls),copy.deepcopy(errors)
def clear_caches():
 for value in list(vars(frozen).values())+list(vars(new.catalog_commands.catalog_provider).values()):
  if callable(getattr(value,'cache_clear',None)):value.cache_clear()

async def compare(name,text,platform,expected_error=False,**options):
 clear_caches()
 before,_,old_errors=await dispatch(ns[name],text,platform,expected_error=expected_error,**options)
 clear_caches()
 after,called,new_errors=await dispatch(getattr(public,name),text,platform,expected_error=expected_error,**options)
 assert before==after,(name,text,platform,before,after)
 assert old_errors==new_errors,(name,text,old_errors,new_errors)
 if expected_error:assert old_errors
 results.append({'command':name,'text':text,'platform':platform,'sent':after,'errors':new_errors,'options':options,'application_calls':called})
 return after

async def run():
 cases={
 'const_query':['查定数6.6','查定数6.6 2','查定数6.6 含下架','查定数6.6 2 含下架','查定数8.5','查定数8.5 含下架','查定数9.9','查定数6.6 99','查定数6.6 0','查定数6.6 abc','查定数invalid'],
 'patterns':['查配置180','查配置200-180','查配置180 鬼10','查配置鬼10 180','查配置ox','查配置16 oxoxox','查配置oxoxox 180 鬼10','查配置180 梅1','查配置999','查配置xxxxx','查配置ox 999','查配置','查配置bad','查配置16 oxoxox 180 鬼10 extra']}
 for platform in ('onebot','qq'):
  for name,texts in cases.items():
   for i,text in enumerate(texts):
    output=await compare(name,text,platform)
    if i==0:
     assert output
     if name=='const_query':assert results[-1]['application_calls']==['execute_constant']
   assert not await compare(name,texts[0],platform,enabled=False)
  # The bare activity command cannot match or enter score simulation.
  for name in ('const_query','patterns'):
   assert not await compare(name,'查分',platform)
  old_score=ns['score_cmd']
  output,_,errors=await dispatch(old_score,'查分',platform)
  assert not output and not errors
 # Missing optional background falls back to each original renderer's drawing.
 path=a.source/'assets/templates/progress_bg.png';saved=path.read_bytes() if path.exists() else None
 try:
  if path.exists():path.unlink()
  for platform in ('onebot','qq'):await compare('const_query','查定数6.6',platform)
 finally:
  if saved is not None:path.write_bytes(saved)
 # Missing public inputs: capture same framework error rather than falsely PASS.
 for name,filename,text in [('patterns','analyze_result_filtered.json','查配置180'),('const_query','rating_structured_with_ids.json','查定数6.6')]:
  path=a.source/'songs'/filename;saved=path.read_bytes()
  try:
   path.unlink()
   for platform in ('onebot','qq'):await compare(name,text,platform,expected_error=True)
  finally:path.write_bytes(saved)
 if a.host=='client':
  async def denied(matcher,event,*args):
   await ns['_finish_text_reply'](matcher,event,'公开资源暂不可用')
   return False
  ns['_ensure_asset_resources_ready']=denied
  new.provider.alias_assets_ready=lambda:(False,'公开资源暂不可用')
  try:
   for platform in ('onebot','qq'):await compare('const_query','查定数6.6',platform)
  finally:
   ns['_ensure_asset_resources_ready']=ready
   new.provider.alias_assets_ready=lambda:(True,'')
 # No mutation/network may hide behind a private Provider.
 # Existing seven-entry regression uses the exact prior public vector and outputs.
 path=a.source/'songs/song_data.json';saved=path.read_bytes()
 try:
  path.write_bytes((a.source.parent/(a.host+'-songs-reference.json')).read_bytes())
  baseline=json.loads((a.source.parent/(a.host+'-public-reference.json')).read_text())['cases']
  seven={'alias_query','song_where','song_position_phrase','song_pos_by_id','diff_by_id','note_count','what_song'}
  for platform in ('onebot','qq'):
   for name in sorted(seven):
    ref=next(c for c in baseline if c['command']==name and c['platform']==platform and c.get('sent') and not c.get('options'))
    matcher=new.what_song if name=='what_song' else getattr(new.public_commands,name)
    text=ref.get('text', 'id1367是什么歌' if platform=='onebot' else 'taiko id1367是什么歌')
    sent_now,_,errs=await dispatch(matcher,text,platform)
    assert sent_now==ref['sent'] and not errs,(name,platform,'seven-entry regression')
    results.append({'command':name,'platform':platform,'regression':True,'sent':sent_now})
 finally:path.write_bytes(saved)

asyncio.run(run())
assert not io_violations,io_violations
out={'host':a.host,'status':'PASS','random_seed':73013,'python_hash_seed':os.environ.get('PYTHONHASHSEED'),'command_file_writes':0,'cases':results,'old_matchers':{n:0 for n in names|{'what_song'}},'new_matchers':{n:1 for n in names|{'what_song'}},'blocked_score_matcher_retained':True,'other_registrations_unchanged':len(r),'plugin_source':new.__file__,'core':version('sakura-taiko-core'),'contract':version('sakura-taiko-contract')}
a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'host':a.host,'cases':len(results),'status':'PASS'}))
