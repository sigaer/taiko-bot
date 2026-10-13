"""Exercise real host providers, command usecases, renderers and message payloads."""

import argparse, asyncio, base64, hashlib, io, json, os, sys, types
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("sandbox", "installed", "images", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument('--host', choices=['center','client'], required=True)
p.add_argument('--source', type=Path)
p.add_argument('--support', type=Path)
p.add_argument('--fixture', type=Path, required=True)
p.add_argument('--resources', type=Path, required=True)
p.add_argument('--revoke', action='store_true')
p.add_argument('--reference', type=Path)
p.add_argument('--failure', choices=['bind403','score403','timeout','identity','invalid-identity'], default='bind403')
a = p.parse_args()
provenance = json.loads(Path(__file__).with_name('provenance.json').read_text())
assert hashlib.sha256(a.fixture.read_bytes()).hexdigest() == provenance['fixture_sha256']
for resource, expected in provenance['files'].items():
    assert hashlib.sha256((a.resources / resource).read_bytes()).hexdigest() == expected, resource
if a.reference:
    assert hashlib.sha256(a.reference.read_bytes()).hexdigest() == provenance['references'][a.host]['sha256']
if a.host == 'center':
    sys.path[:0] = [str(a.source), str(a.support)]
    os.environ.update(PYTHON_MEMORY_RUNTIME_ROOT=str(a.support),
                      PYTHON_MEMORY_METRICS_DIR=str(a.sandbox / 'metrics'),
                      TAIKO_RUNTIME_ENV_FILE=str(a.sandbox / 'absent.env'))
a.sandbox.mkdir(parents=True, exist_ok=True)
os.chdir(a.source if a.host == 'center' else a.sandbox)
os.environ.update(
    TAIKO_BOT_ROOT=str(a.sandbox),
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
import runpy, shutil, copy
fixture = runpy.run_path(str(a.fixture))["FIXTURE"]
user = copy.deepcopy(fixture["userdata"])
user["profile"] = {"gameCostume": {"mydon_name": "Synthetic Player"}}
user["update_time"] = "2026-10-12 12:00:00"
for root in [a.sandbox] + ([a.source] if a.host == "center" else []):
    (root / "songs").mkdir(exist_ok=True)
    (root / "userdata").mkdir(exist_ok=True)
    (root / "songs/song_data.json").write_text(json.dumps(fixture["song_catalog"]))
    (root / "songs/song_alias.json").write_text("{}")
    (root / "songs/rating_structured_with_ids.json").write_text(json.dumps(fixture["rating_config"]))
    (root / "userdata/42data.json").write_text(json.dumps(user))
    shutil.copytree(a.resources, root / "assets", dirs_exist_ok=True)
os.environ.update(TAIKO_USERDATA_DIR=str(a.sandbox / "userdata"), TAIKO_VIEWER_DEVELOPER_TOKEN="synthetic-only")
sys.addaudithook(guard)
import nonebot

nonebot.init(driver="~fastapi", log_level="ERROR")
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
names = ("taikob", "music_info", "what_song", "const_query", "matcher", "taikorec")
selected = {getattr(module, n) for n in names}
assert all(m.handlers for m in selected)
# Keep actual registered matcher/rule/handler objects; exclude unrelated products.
for priority, group in list(matchers.items()):
    matchers[priority] = [m for m in group if m in selected]
nonebot.get_driver().register_adapter(Adapter)
adapter = nonebot.get_adapter(Adapter)
bot = Bot(adapter, "90000")
sent = []
calls = []
errors = []
state = {}


@run_postprocessor
async def capture_error(exception: Exception | None):
    if exception is not None:
        errors.append([type(exception).__name__, str(exception)])


def image_summary(raw):
    with Image.open(io.BytesIO(raw)) as im:
        return {
            "bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "pixels_sha256": hashlib.sha256(im.tobytes()).hexdigest(),
            "dimensions": list(im.size),
            "mode": im.mode,
        }


async def call_api(self, bot, api, **data):
    segments = []
    for seg in data.get("message", []):
        value = dict(seg.data)
        if seg.type == "image" and str(value.get("file", "")).startswith("base64://"):
            value["file"] = image_summary(base64.b64decode(value["file"][9:]))
        segments.append({"type": seg.type, "data": value})
    sent.append({"api": api, "segments": segments})
    return {"message_id": 1}


adapter._call_api = types.MethodType(call_api, adapter)


# Configure resource/data boundaries, retaining the actual implementations.
os.chdir(a.sandbox)
root_prefix = str(Path(module.__file__).parents[1])
def path_value(value):
    if isinstance(value, (str, Path)):
        raw = str(value)
        for prefix in (root_prefix, '/home/sigaer/taiko'):
            if raw == prefix or raw.startswith(prefix + '/'):
                mapped = str(a.sandbox) + raw[len(prefix):]
                return Path(mapped) if isinstance(value, Path) else mapped
    return value
for name, loaded in list(sys.modules.items()):
    if a.host != 'center' or not name.startswith(('plugins.', 'taiko_store')): continue
    for key, value in list(vars(loaded).items()):
        if key.startswith("__"): continue
        if isinstance(value, (str, Path)):
            setattr(loaded, key, path_value(value))
        if isinstance(value, types.FunctionType) and value.__module__ == name:
            if value.__defaults__: value.__defaults__ = tuple(map(path_value, value.__defaults__))
            if value.__kwdefaults__: value.__kwdefaults__ = {k:path_value(v) for k,v in value.__kwdefaults__.items()}
if a.host == 'client':
    for module_name in ('b30_render','b30_single','drawinfo','draw_dress'):
        assert sys.modules['plugins.utils.'+module_name].ROOT_DIR == a.sandbox
async def assets(*args): return True
module._ensure_asset_resources_ready = assets
trace = []
if a.host == 'center':
    # Outer authorization database response, never the application/renderer.
    module._resolve_read_bind_target = lambda event: {'user_id':'42', 'source':'wahlap', 'is_virtual':False}
else:
    import httpx
    real_http = httpx.Client
    def response(request):
        trace.append(request.url.path)
        if state.get('revoked'):
            if a.failure == 'timeout': raise httpx.ReadTimeout('synthetic send-time timeout')
            if a.failure == 'bind403' or (a.failure == 'score403' and not request.url.path.endswith('/bind')):
                return httpx.Response(403, json={'error':'synthetic revocation'})
        if request.url.path.endswith('/bind'):
            return httpx.Response(200, json={'found':True,'currentTaikoId':('../invalid' if a.failure=='invalid-identity' else '43') if state.get('revoked') and a.failure in ('identity','invalid-identity') else '42','visible':1,'currentSlot':1,'currentSource':'wahlap'})
        history = request.url.path.endswith('/history')
        return httpx.Response(200, json={'historyFormat':'raw-v1','snapshots':[]} if history else user,
            headers={'etag':'"taiko-' + ('history' if history else 'current') + '-v1-'+'a'*64+'"',
                     'x-taiko-source-view':'v1-'+'a'*32+'-1'})
    httpx.Client = lambda **kw: real_http(transport=httpx.MockTransport(response), **kw)
# Public v2 catalogue at the external dataset input; real v2 calculation remains.
from sakura_taiko_core.models.calculation import V2SongData
import plugins.utils.drawinfo as info
info.load_v2_snapshot = lambda: types.SimpleNamespace(song_map={(278,5):V2SongData(278,5,'花漾',541,8.5,9.3,9.8,35,34,37,30,25)})
for name in ('b30','score'):
    fn = getattr(module, 'execute_'+name)
    def counted(*args, _fn=fn, _name=name, **kwargs):
        calls.append(_name)
        return _fn(*args, **kwargs)
    setattr(module, 'execute_'+name, counted)
# Freeze only the wall clock; all rating and renderer functions stay real.
import datetime
real_datetime = datetime.datetime
class FixtureDateTime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026,10,12,12,0,0)
        return value if tz is None else value.replace(tzinfo=tz)
datetime.datetime = FixtureDateTime
raw_images = []
for name in ('render_b30_image','generate_score_image'):
    fn = getattr(module, name)
    def rendered(*args, _fn=fn, _name=name, **kwargs):
        raw = _fn(*args, **kwargs)
        raw_images.append({'renderer':_name, **image_summary(raw)})
        if a.revoke: state['revoked'] = True
        return raw
    setattr(module, name, rendered)
if a.reference:
    import ast
    tree = ast.parse(a.reference.read_text())
    for matcher_name, handler_name in [('taikob','taikob_handle'),('music_info','music_info_handle')]:
        node = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name == handler_name)
        node.decorator_list=[]
        namespace=dict(vars(module))
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(a.reference),'exec'),namespace)
        matcher = getattr(module,matcher_name)
        matcher.handlers.clear()
        matcher.handle()(namespace[handler_name])
async def main():
    rows = []
    for i,(name,text) in enumerate([('b30','taikob30 v1' if a.host=='center' else 'taikob30'),('score','tinfo 278')]):
        calls.clear(); sent.clear(); errors.clear(); trace.clear(); raw_images.clear(); state.clear()
        event = PrivateMessageEvent(time=1,self_id=90000,post_type='message',message_type='private',sub_type='friend',message_id=i+1,user_id=10001,message=Message(text),original_message=Message(text),raw_message=text,font=0,sender={'user_id':10001,'nickname':'Fixture'},to_me=True)
        await handle_event(bot,event)
        assert not errors, errors
        assert calls == ([] if a.reference else [name]), (name,calls,sent)
        assert len(raw_images)==1, (name,raw_images,sent)
        assert len(sent)==1, (name,sent)
        image_sent = any(s['type']=='image' for msg in sent for s in msg['segments'])
        if a.revoke: assert not image_sent, ('PRIVATE_IMAGE_SENT_AFTER_REVOCATION', name, trace)
        else: assert image_sent, (name,sent)
        if a.revoke and a.failure == 'score403':
            from taiko_bot import userdata_provider
            from taiko_bot.private_read_cache import private_cache_key
            assert userdata_provider._PRIVATE_READ_CACHE.get(private_cache_key('current','42',module._SETTINGS)) is None

        rows.append({'command':name,'application_calls':list(calls),'renderer_png':list(raw_images),'messages':list(sent),'requests':list(trace)})
    assert not io_violations, io_violations
    a.output.write_text(json.dumps({'status':'PASS','host':a.host,'core':version('sakura-taiko-core'),'revocation':a.revoke,'failure':a.failure if a.revoke else None,'reference':str(a.reference) if a.reference else None,'cases':rows},ensure_ascii=False,indent=2))
    print('REAL_CHAIN_PASS',a.host,len(rows))
asyncio.run(main())
