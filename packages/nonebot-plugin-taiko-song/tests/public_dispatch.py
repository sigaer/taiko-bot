"""Dispatch actual host matchers with offline provider fixtures."""

import argparse, asyncio, base64, hashlib, io, json, os, sys, types
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("sandbox", "installed", "images", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument('--host', choices=['center','client'], required=True)
p.add_argument('--source', type=Path)
p.add_argument('--support', type=Path)
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

def guard(event, args):
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
external_first = nonebot.load_plugin("nonebot_plugin_taiko_song")
assert external_first is not None and len(external_first.matcher) == 7
assert "plugins.taiko" not in sys.modules
assert not any(name.startswith("plugins.utils") for name in sys.modules)
plugin = nonebot.load_plugin("plugins.taiko")
assert plugin is not None, "Installed plugin failed to load"
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
assert len(external.matcher)==7
assert new.what_song.priority == 10 and new.what_song.block
assert Path(new.__file__).is_relative_to(a.installed)
# Host source ownership: no other registration was removed or changed.
reference = (a.source.parent/(a.host+'-reference.py')).read_text()
old_tree=ast.parse(reference)
new_tree=ast.parse(Path(module.__file__).read_text())
def registrations(tree):
 return {ast.unparse(n.targets[0]):ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id.startswith('on_')}
names = {'alias_query','song_where','song_position_phrase','song_pos_by_id','diff_by_id','note_count'}
r=registrations(old_tree)
for name in names:
 assert r.pop(name)
 assert not hasattr(module,name)
assert r == registrations(new_tree)
public=new.public_commands
assert {getattr(public,n) for n in names} | {new.what_song} == external.matcher
# Rehydrate complete untouched old handlers and removed helpers, not rewritten models.
ns=dict(module.__dict__)
restored=[]
helpers={'render_alias_image','find_aliases_by_song_id','_strip_song_query_diff_prefix','_finish_song_position_by_name','_finish_song_position_by_id'}
constants={'ALIAS_QUERY_REGEX','SONG_WHERE_REGEX','SONG_POSITION_REGEX','SONG_POS_BY_ID_REGEX','DIFF_BY_ID_REGEX','DIFF_MAP'}
for n in old_tree.body:
 name=getattr(n,'name',None)
 if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name):name=n.targets[0].id
 handler=isinstance(n,ast.AsyncFunctionDef) and any(any(x+'.handle' in ast.unparse(d) for x in names) for d in n.decorator_list)
 if name in names|helpers|constants or (a.host=='client' and name in {'_get_fumen_path', '_resolve_what_song_query', '_finish_with_image_fallback', '_finish_fuzzy_query_with_fumen', 'DIFF_MAP_REVERSE', '_send_fumen_or_hint'}) or handler:restored.append(n)
utils_ref=ast.parse((a.source.parent/(a.host+'-utils-__init__.py')).read_text())
restored.insert(0,next(n for n in utils_ref.body if getattr(n,'name',None)=='find_by_volume'))
position_ns={'__name__':'plugins.utils.frozen_position','__package__':'plugins.utils','__file__':str(a.source/'plugins/utils/song_position.py')}
exec(compile((a.source.parent/(a.host+'-utils-song_position.py')).read_text(),'<frozen-position>','exec'),position_ns)
position_ns['SONG_DATA_PATH']=a.source/'songs/song_data.json'
ns.update({n:position_ns[n] for n in ('format_position_reply','get_song_position_by_id')})
if a.host=='center':
 alias_ns={'__name__':'frozen_duplicate_versions'}
 exec(compile((a.source.parent/'center-utils-duplicate_versions.py').read_text(),'<frozen-alias-provider>','exec'),alias_ns)
 ns['alias_entry_for_song_id']=alias_ns['alias_entry_for_song_id']
exec(compile(ast.Module(body=restored,type_ignores=[]),'<frozen-public-entries>','exec'),ns)
for name in names:
 before,after=ns[name],getattr(public,name)
 assert (before.priority,before.block)==(after.priority,after.block)
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
# Real public catalog and fixed tracked fumen assets, with no private score inputs.
songs=json.loads((a.source/'songs/song_data.json').read_text())
rows=[x for x in songs if str(x.get('id','')).isdigit() and (a.source/'assets/fumens/Oni'/f'{x["id"]}.png').exists()]
row=rows[0];title=row.get('song_name_jp') or row.get('song_name');sid=row['id']
aliases=json.loads((a.source/'songs/song_alias.json').read_text())
alias=next((v for x in aliases if str(x.get('id'))==str(sid) for v in x.get('aliases',[]) if isinstance(v,str)),title)
results=[]
async def dispatch(matcher,text,platform,enabled=True,mention=False,tsearch=True,expected_error=False):
 for priority,items in list(matchers.items()):matchers[priority]=[]
 matchers[matcher.priority]=[matcher]
 state['enabled']=enabled;state['tsearch']=tsearch;sent.clear();errors.clear();calls.clear()
 if platform=='onebot':
  msg=Message(text)
  if mention:msg=Message('[CQ:at,qq=3889003795]')+msg
  event=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=10001,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':10001,'nickname':'Fixture'},to_me=True)
  target=bot
 else:
  event=GroupAtMessageCreateEvent(id='fixture-message',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True)
  target=qq
 await handle_event(target,event)
 assert not errors or expected_error,(text,platform,errors)
 return copy.deepcopy(sent),list(calls),copy.deepcopy(errors)
# No fake rendering or query results: catalog/alias/note files are the public IO boundary.
def clear_caches():
 for mod in list(sys.modules.values()):
  if mod and getattr(mod,'__name__','').startswith('plugins.utils'):
   for value in list(vars(mod).values()):
    if callable(getattr(value,'cache_clear',None)):value.cache_clear()
 position_ns['_load_song_catalog'].cache_clear()
 if a.host=='center':
  for value in alias_ns.values():
   if callable(getattr(value,'cache_clear',None)):value.cache_clear()

async def compare(name,text,platform,**options):
 clear_caches()
 before,_,old_errors=await dispatch(ns[name],text,platform,**options)
 clear_caches()
 after,called,new_errors=await dispatch(getattr(public,name),text,platform,**options)
 assert before==after,(name,platform,text,before,after)
 assert old_errors==new_errors,(name,text,old_errors,new_errors)
 if options.get('expected_error'):assert old_errors,(name,text,'expected captured failure')
 results.append({'command':name,'platform':platform,'text':text,'options':options,'sent':after,'errors':new_errors})
 return after

async def run():
 cases={
 'alias_query':['id900001有什么别名',f'id{sid}有什么别名',title+'有什么别名',alias+'有什么别名',title[:-1]+'X有什么别名','???有什么别名',' 有什么别名','有什么别名'],
 'song_where':[f'id{sid}歌在哪',title+'歌在哪',alias+'歌在哪',f'里id{sid}歌在哪','???歌在哪',' 歌在哪','歌在哪'],
 'song_position_phrase':[f'id{sid}在什么位置',title+'在什么位置','???在什么位置',' 在什么位置','在什么位置'],
 'song_pos_by_id':[f'位置 id{sid}','位置 id999999999','位置 idINVALID'],
 'diff_by_id':[f'{d} id{sid}' for d in ('里','鬼','表','松','竹','梅','简单','一般','困难','魔王')]+['鬼 id999999999','鬼 idINVALID'],
 'note_count':['太鼓查物量123','太鼓查物量777','太鼓查物量999','太鼓查物量INVALID','太鼓查物量123 tail'],
 }
 for platform in ('onebot','qq'):
  for name,texts in cases.items():
   for index,text in enumerate(texts):
    output=await compare(name,text,platform)
    if index==0:assert output,(name,platform,'normal dispatch produced nothing')
   for options in ({'enabled':False},{'mention':True},{'tsearch':False}):
    output=await compare(name,texts[0],platform,**options)
    blocked=(options.get('enabled') is False or (options.get('tsearch') is False and name in {'alias_query','diff_by_id'}) or (options.get('mention') and platform=='onebot'))
    assert bool(output)!=blocked,(name,platform,options,output)
  # Existing Application-owned song entry still registers once and executes once.
  text=f'id{sid}是什么歌' if platform=='onebot' else f'taiko id{sid}是什么歌'
  sent_song,called,errs=await dispatch(new.what_song,text,platform)
  assert sent_song and called==['execute_song'] and not errs
  results.append({'command':'what_song','platform':platform,'sent':sent_song,'application_calls':called})
 # Retain the former center position unit vectors, now through real entries.
 path=a.source/'songs/song_data.json';saved=path.read_bytes()
 try:
  payload=json.loads((Path(__file__).parent/'fixtures/position.json').read_text())
  path.write_text(json.dumps(payload))
  for platform in ('onebot','qq'):
   for identifier in (1,2,3,4,5,9999):
    output=await compare('song_pos_by_id',f'位置 id{identifier}',platform)
    if a.host=='center' and platform=='onebot':
     text=json.dumps(output,ensure_ascii=False)
     if identifier==1:assert '第 3 / 3' in text and 'sort：20' in text
     if identifier==2:assert '第 1 / 3' in text
     if identifier==3:assert '第 2 / 3' in text
     if identifier==4:assert '已下架' in text and '共 3 首' in text
 finally:path.write_bytes(saved)
 # Visibility/profile differences: test the same rows against each host's own reference.
 path=a.source/'songs/song_data.json';saved=path.read_bytes()
 try:
  base=json.loads(saved)
  for mode,extra in [('down',{'id':900002,'song_name_jp':'Fixture Off Shelf','sort':999,'shelf_status':1}),('hidden',{'id':1429,'song_name_jp':'Fixture Hidden','sort':1000}),('double',{'id':900003,'song_name_jp':'【双打】Fixture','song_name':'【双打】Fixture','sort':1001})]:
   row=dict(base[0]);row.update(extra);path.write_text(json.dumps(base+[row]))
   for platform in ('onebot','qq'):
    await compare('song_pos_by_id',f'位置 id{row["id"]}',platform)
    await compare('alias_query',f'id{row["id"]}有什么别名',platform)
 finally:path.write_bytes(saved)
 for mode in ('empty','provider_error'):
  paths=[a.source/'songs/song_data.json',a.source/'songs/song_alias.json'];saved=[p.read_bytes() for p in paths]
  try:
   for path in paths:path.write_text('[]' if mode=='empty' else '{invalid')
   for platform in ('onebot','qq'):
    for name,text in [('alias_query',title+'有什么别名'),('song_where',title+'歌在哪'),('song_position_phrase',title+'在什么位置')]:
     await compare(name,text,platform)
  finally:
   for path,data in zip(paths,saved):path.write_bytes(data)
 # Client public resource manager refuses; never starts rendering or file delivery.
 if a.host=='client':
  async def denied(matcher,event,*resources):
   await ns['_finish_text_reply'](matcher,event,'公开资源暂不可用')
   return False
  ns['_ensure_asset_resources_ready']=denied
  new.provider.asset_ready=lambda:(False,'公开资源暂不可用')
  new.provider.alias_assets_ready=lambda:(False,'公开资源暂不可用')
  try:
   for platform in ('onebot','qq'):
    await compare('alias_query',f'id{sid}有什么别名',platform)
    await compare('diff_by_id',f'鬼 id{sid}',platform)
  finally:
   ns['_ensure_asset_resources_ready']=ready
   new.provider.asset_ready=lambda:(True,'')
   new.provider.alias_assets_ready=lambda:(True,'')
 # Framework exceptions must be captured, not silently counted as normal PASS.
 path=a.source/'songs/tja_note_counts.json';saved=path.read_bytes()
 try:
  path.write_text('{invalid')
  for platform in ('onebot','qq'):await compare('note_count','太鼓查物量123',platform,expected_error=True)
 finally:path.write_bytes(saved)

asyncio.run(run())
assert not io_violations,io_violations
out={'host':a.host,'status':'PASS','cases':results,'old_matchers':{n:0 for n in names|{'what_song'}},'new_matchers':{n:1 for n in names|{'what_song'}},'other_registrations_unchanged':len(r),'plugin_source':new.__file__,'core':version('sakura-taiko-core'),'contract':version('sakura-taiko-contract')}
a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'host':a.host,'cases':len(results),'status':'PASS'}))
