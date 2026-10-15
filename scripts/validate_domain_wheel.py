"""Validate an installed client/Core wheel using isolated settings, no network."""
import ast
import builtins
from functools import wraps
from importlib.metadata import version
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(TARGET))
root = Path(tempfile.mkdtemp(prefix='taiko-client-wheel-', dir='/var/tmp'))
os.environ.update(TAIKO_BOT_ROOT=str(root), TAIKO_STORAGE_DIR=str(root/'storage'),
                  TAIKO_USERDATA_DIR=str(root/'storage/cache/userdata'),
                  TAIKO_SQLITE_PATH=str(root/'storage/data/taiko_test.sqlite3'),
                  TAIKO_VIEWER_DEVELOPER_TOKEN='', TAIKO_BOT_SERVICE_TOKEN='',
                  TAIKO_VIEWER_BASE_URL='http://127.0.0.1:1')
os.chdir(root)
def guard(file, mode='r'):
    if not isinstance(file, (str, bytes, Path)): return
    path=str(Path(file.decode() if isinstance(file, bytes) else file).resolve())
    blocked=('/home/sigaer/taiko/userdata','/home/sigaer/taiko-bot/storage','/home/sigaer/git/Sakura_bot/taiko/userdata')
    if any(path==item or path.startswith(item+'/') for item in blocked) or path==str(SOURCE/'.env'):
        raise PermissionError('wheel QA cannot read production personal data or settings')
    if path.startswith(('/home/sigaer/taiko/','/home/sigaer/taiko-bot/')) and any(c in mode for c in ('w','a','x','+')):
        raise PermissionError('wheel QA cannot mutate production or source trees')
original_open=builtins.open
@wraps(original_open)
def safe_open(file,*args,**kwargs):
    guard(file,args[0] if args else kwargs.get('mode','r'))
    return original_open(file,*args,**kwargs)
original_path_open=Path.open
@wraps(original_path_open)
def safe_path_open(self,*args,**kwargs):
    guard(self,args[0] if args else kwargs.get('mode','r'))
    return original_path_open(self,*args,**kwargs)
builtins.open=safe_open
Path.open=safe_path_open
import requests
import httpx
def unavailable(*args, **kwargs): raise PermissionError('wheel QA cannot send HTTP')
async def unavailable_async(*args, **kwargs): raise PermissionError('wheel QA cannot send HTTP')
requests.sessions.Session.send = unavailable
httpx.Client.send = unavailable
httpx.AsyncClient.send = unavailable_async
try:
    for package, expected in (('taiko-bot','0.12.0'),('sakura-taiko-core','0.1.2'),('sakura-taiko-contract','0.1.0')):
        assert version(package) == expected
    manifest = json.loads((SOURCE/'docs/taiko-domain-extraction/phase4-adapter-manifest.json').read_text())
    modules = sorted({row['file'].removesuffix('.py').replace('/','.') for row in manifest})
    for name in modules:
        module = importlib.import_module(name)
        assert Path(module.__file__).is_relative_to(TARGET), name
        assert Path(module.__file__).read_bytes() == (SOURCE/(name.replace('.','/')+'.py')).read_bytes(), name
    from plugins.utils.hiroba.parser import HirobaProfile, HirobaScoreDetail
    from plugins.utils.hiroba.normalize import build_userdata
    payload = build_userdata(HirobaProfile('synthetic'), [HirobaScoreDetail('2',4,score=950000)])
    assert payload['songs'][0]['high_score'] == 950000
    import nonebot
    nonebot.init(taiko_song_profile="client")
    nonebot.require('taiko_bot.runtime.community.community_entry')
    command = importlib.import_module('taiko_bot.runtime.player.client.lifecycle_host')
    assert Path(command.__file__).is_relative_to(TARGET)
    assert command._normalize_bind_input('12345') == '12345'
    evidence = {'gate':'INSTALLED_CLIENT_PASS','client':'0.12.0','core':'0.1.2','contract':'0.1.0',
                'delegatedModules':len(modules),'wheelCodeMatchesSource':True,'commandImport':True,
                'personalDataReads':0,'networkRequests':0,'productionWrites':0}
    Path(sys.argv[2]).write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(evidence))
finally:
    shutil.rmtree(root)
