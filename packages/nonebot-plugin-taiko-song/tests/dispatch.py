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
assert external_first is not None and len(external_first.matcher) == 1
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
assert len(external.matcher)==1
assert new.what_song.priority == 10 and new.what_song.block
assert Path(new.__file__).is_relative_to(a.installed)
# Host source ownership: no other registration was removed or changed.
reference = (a.source.parent/(a.host+'-reference.py')).read_text()
old_tree=ast.parse(reference)
new_tree=ast.parse(Path(module.__file__).read_text())
def registrations(tree):
 return {ast.unparse(n.targets[0]):ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id.startswith('on_')}
r=registrations(old_tree); assert r.pop('what_song')
assert r == registrations(new_tree)
# Rehydrate only the frozen command entry into a separate reference namespace.
ns=dict(module.__dict__)
restored=[]
for n in old_tree.body:
 name=getattr(n,'name',None)
 if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name):name=n.targets[0].id
 if name in {'WHAT_SONG_REGEX','WHAT_SONG_OFFICIAL_PATTERNS','_extract_what_song_query','_extract_official_what_song_query','_should_handle_what_song','what_song'}:
  restored.append(n)
 if isinstance(n,ast.AsyncFunctionDef) and any('what_song.handle' in ast.unparse(d) for d in n.decorator_list):restored.append(n)
ns.update(SongPorts=app.SongPorts,execute_song=app.execute_song)
exec(compile(ast.Module(body=restored,type_ignores=[]),'<frozen-song-entry>','exec'),ns)
old=ns['what_song']
# Only boundary feature storage and platform sends are substituted.
state={'enabled':True};errors=[];sent=[];calls=[]
for m in list(sys.modules.values()):
 if m and getattr(m,'__name__','').endswith('feature_handler.feature_handler'):
  m.is_feature_enabled=lambda *args,**kwargs:state['enabled']
  m.is_group_allowed=lambda *args,**kwargs:True
# Resource readiness is the outer resource manager, not song matching or fumen selection.
async def ready(*args):return True
ns['_ensure_asset_resources_ready']=ready
new.provider.asset_ready=lambda:(True,'')
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
 segments = message if not isinstance(message,str) else [{'text':message}]
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
cases=[title+'是什么歌',f'id{sid}是什么歌',alias+'是什么歌',title[:-1]+'X是什么歌',f'里id{sid}是什么歌',f'简单id{sid}是什么歌','是什么歌','???是什么歌','not a command','taiko '+title+'是什么歌','太鼓 什么歌 '+title,'   是什么歌',f'id999999999是什么歌']
results=[]
async def dispatch(matcher,text,platform,enabled=True,mention=False):
 for priority,items in list(matchers.items()):matchers[priority]=[]
 matchers[10]=[matcher]
 state['enabled']=enabled;sent.clear();errors.clear();calls.clear()
 if platform=='onebot':
  msg=Message(text)
  if mention:msg=Message('[CQ:at,qq=3889003795]')+msg
  event=GroupMessageEvent(time=1,self_id=90000,post_type='message',message_type='group',sub_type='normal',message_id=1,user_id=10001,group_id=123,message=msg,original_message=msg,raw_message=str(msg),font=0,sender={'user_id':10001,'nickname':'Fixture'},to_me=True)
  target=bot
 else:
  event=GroupAtMessageCreateEvent(id='fixture-message',content=text,timestamp='2026-10-13T00:00:00+00:00',author={'id':'fixture-user','member_openid':'fixture-user','bot':False,'member_role':'member'},group_id='fixture-group',group_openid='fixture-group',to_me=True)
  target=qq
 await handle_event(target,event)
 assert not errors,(text,platform,errors)
 return copy.deepcopy(sent),list(calls)
async def run():
 for platform in ('onebot','qq'):
  for text in cases:
   before,_=await dispatch(old,text,platform)
   after,called=await dispatch(new.what_song,text,platform)
   assert before==after,(platform,text,before,after)
   assert len(called)<=1
   if (platform == "onebot" and text in cases[:6]) or (platform == "qq" and text == "taiko "+title+"是什么歌"):
    assert before and called == ["execute_song"], (platform,text,before,called)
   results.append({'platform':platform,'text':text,'sent':after,'application_calls':called})
  for enabled,mention in [(False,False),(True,True)]:
   text=title+'是什么歌' if platform=='onebot' else 'taiko '+title+'是什么歌'
   before,_=await dispatch(old,text,platform,enabled,mention)
   after,called=await dispatch(new.what_song,text,platform,enabled,mention)
   assert before==after,(platform,enabled,mention,before,after)
   if not enabled or (mention and platform=='onebot'):assert not after and not called
   results.append({'platform':platform,'enabled':enabled,'mention':mention,'sent':after,'application_calls':called})
 # Empty public dataset and malformed outer Provider input.
 for mode in ('empty', 'provider_error'):
  paths=[a.source/'songs/song_data.json', a.source/'songs/song_alias.json']
  saved=[path.read_bytes() for path in paths]
  try:
   for path in paths:path.write_text('[]' if mode=='empty' else '{invalid')
   for platform in ('onebot','qq'):
    text = title+'是什么歌' if platform=='onebot' else 'taiko '+title+'是什么歌'
    before,_=await dispatch(old,text,platform)
    after,called=await dispatch(new.what_song,text,platform)
    assert before == after and before and called == ['execute_song'],(mode,platform,before,after,called)
    results.append({'platform':platform,'mode':mode,'sent':after,'application_calls':called})
  finally:
   for path,data in zip(paths,saved):path.write_bytes(data)

asyncio.run(run())
assert not io_violations,io_violations
out={'host':a.host,'status':'PASS','cases':results,'old_matchers':0,'new_matchers':1,'other_registrations_unchanged':len(r),'plugin_source':new.__file__,'core':version('sakura-taiko-core'),'contract':version('sakura-taiko-contract')}
a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'host':a.host,'cases':len(results),'status':'PASS'}))
