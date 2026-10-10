"""Offline client regressions with isolated storage and network/read guards.

Run through the Viewer's scripts/memory/run_qa.sh maintenance boundary.
"""
import ast
import builtins
from functools import wraps
import os
from pathlib import Path
import tempfile
import sys
import shutil

SOURCE=Path(__file__).resolve().parents[1]
ROOT=Path(tempfile.mkdtemp(prefix='taiko-domain-client-',dir='/var/tmp'))
(ROOT/'songs').mkdir()
settings=ast.parse((SOURCE/'taiko_bot/settings.py').read_text())
datasets=ast.literal_eval(next(n.value for n in settings.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='PUBLIC_DATA_FILES' for t in n.targets)))
for name in datasets.values():
    candidate=SOURCE/('city.json' if name=='city.json' else 'songs/'+name)
    if candidate.exists():(ROOT/('city.json' if name=='city.json' else 'songs/'+name)).symlink_to(candidate.resolve())
if (SOURCE/'assets').exists():(ROOT/'assets').symlink_to((SOURCE/'assets').resolve())
os.environ['TAIKO_BOT_ROOT']=str(ROOT)
os.environ['TAIKO_STORAGE_DIR']=str(ROOT/'storage')
os.environ['TAIKO_USERDATA_DIR']=str(ROOT/'storage/cache/userdata')
os.environ['TAIKO_SQLITE_PATH']=str(ROOT/'storage/data/taiko_test.sqlite3')
os.environ['TAIKO_VIEWER_DEVELOPER_TOKEN']=''
os.environ['TAIKO_BOT_SERVICE_TOKEN']=''
os.environ['TAIKO_VIEWER_BASE_URL']='http://127.0.0.1:1'
os.chdir(ROOT)
sys.path.insert(0,str(SOURCE))

BLOCKED_READS=('/home/sigaer/taiko/userdata','/home/sigaer/taiko-bot/storage',
               '/home/sigaer/git/Sakura_bot/taiko/userdata')
def guard(file,mode='r'):
    if not isinstance(file,(str,bytes,Path)):return
    path=str(Path(file.decode() if isinstance(file,bytes) else file).resolve())
    if any(path==root or path.startswith(root+'/') for root in BLOCKED_READS):
        raise PermissionError('Client domain QA must not read production personal storage')
    if path==str(SOURCE/'.env'):
        raise PermissionError('Client domain QA must not load production settings')
    if path.startswith(('/home/sigaer/taiko/','/home/sigaer/taiko-bot/')) and any(c in mode for c in ('w','a','x','+')):
        raise PermissionError('Client domain QA must not mutate production or source trees')
original_open=builtins.open
@wraps(original_open)
def offline_open(file,*args,**kwargs):
    guard(file,args[0] if args else kwargs.get('mode','r'))
    return original_open(file,*args,**kwargs)
original_path_open=Path.open
@wraps(original_path_open)
def offline_path_open(self,*args,**kwargs):
    guard(self,args[0] if args else kwargs.get('mode','r'))
    return original_path_open(self,*args,**kwargs)
builtins.open=offline_open
Path.open=offline_path_open

import requests
import httpx
def no_network(*args,**kwargs):raise PermissionError('Client domain QA must not send HTTP')
async def no_async_network(*args,**kwargs):raise PermissionError('Client domain QA must not send HTTP')
requests.sessions.Session.send=no_network
httpx.Client.send=no_network
httpx.AsyncClient.send=no_async_network

import pytest
try:
    result=pytest.main([str(SOURCE/'tests'),'-q','-p','no:cacheprovider',
                       '--disable-warnings','--maxfail=3',*sys.argv[1:]])
finally:
    shutil.rmtree(ROOT)
raise SystemExit(result)
