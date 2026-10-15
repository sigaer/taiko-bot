"""Owned native update with real SQL/common writer; synthetic four HTTP calls."""
import builtins
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import types
import subprocess
import hashlib
request=json.loads(sys.stdin.buffer.read(16385));root=Path(request['root']).resolve()
assert str(root).startswith('/var/tmp/') and root.is_dir()
os.environ.update(TAIKO_USERDATA_DIR=str(root/'userdata'),TAIKO_RUNTIME_ENV_FILE=str(root/'absent-native-env'),
    TAIKO_WAHLAP_CONFIG_PATH=str(root/'synthetic-wahlap.json'),PYTHONDONTWRITEBYTECODE='1')
(root/'synthetic-wahlap.json').write_text(json.dumps({'cookie':'synthetic-public-cookie'}))
old_open=builtins.open;old_path_open=Path.open
def guard(path,mode):
    if isinstance(path,(str,bytes,Path)):
        p=Path(path).resolve()
        if str(p).startswith(('/home/sigaer/taiko/userdata/','/home/sigaer/taiko/secrets/')) or str(p)=='/etc/taiko-runtime.env':raise PermissionError('Production personal storage prohibited')
        if any(v in mode for v in 'wax+') and root not in p.parents:raise PermissionError('Native write outside fixture')
def safe_open(path,*a,**kw):guard(path,a[0] if a else kw.get('mode','r'));return old_open(path,*a,**kw)
def safe_path_open(self,*a,**kw):guard(self,a[0] if a else kw.get('mode','r'));return old_path_open(self,*a,**kw)
builtins.open=safe_open;Path.open=safe_path_open
source=Path(__file__).resolve().parents[2]
import pymysql
import requests
from taiko_bot.runtime.player.center import native_wahlap_update as native,update_user,userdata_storage
from taiko_bot.runtime.player.center import taikob_v2_data as dataset
# Load the tracked public catalog as a fresh snapshot; no QA HTTP refresh or
# rewrite of the shared catalog. Daily computation itself remains actual.
dataset._snapshot=dataset.parse_v2_dataset_csv(dataset.V2_DATASET_FALLBACK_PATH.read_text(encoding='utf-8'))

class FixedDate(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,10,12,0,0,0,tzinfo=tz)
userdata_storage.datetime=FixedDate
fault=request.get('fault');current_cursor=[None];calls=[0];commits=[0];connections=[]
real_connect=pymysql.connect

class Cursor:
    def __init__(self,real):self.real=real
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def execute(self,sql,args=()):
        if 'GET_LOCK' in sql:print('{"event":"gate-attempt"}',flush=True)
        return self.real.execute(sql,args)
    def fetchone(self):return self.real.fetchone()
    def fetchall(self):return self.real.fetchall()
    def close(self):return self.real.close()

class Connection:
    def __init__(self,real,main):self.real=real;self.main=main
    def cursor(self):
        c=self.real.cursor()
        if self.main:current_cursor[0]=c
        return Cursor(c)
    def begin(self):return self.real.begin()
    def commit(self):
        commits[0]+=int(self.main)
        if self.main and commits[0]==2 and fault=='before-commit-exit':os._exit(45)
        if self.main and commits[0]==2 and fault=='before-commit-error':raise RuntimeError('Private readonly COMMIT')
        self.real.commit()
        if self.main and commits[0]==1:print('{"event":"capture-complete"}',flush=True)
        if self.main and commits[0]==2 and fault=='after-commit-exit':os._exit(46)
        if self.main and commits[0]==2 and fault=='after-commit-error':raise RuntimeError('Private ACK')
    def rollback(self):
        if self.main and fault=='rollback-error':raise RuntimeError('Private rollback fault')
        return self.real.rollback()
    def close(self):return self.real.close()

def connect(*,main=False,**config):
    assert os.environ.get('TAIKO_ALLOW_TEST_DB_MUTATION')=='1'
    db=real_connect(**config)
    with db.cursor() as cur:
        cur.execute('SELECT DATABASE()');name=cur.fetchone()[0]
        assert name.endswith('_test') and name==os.environ['TAIKO_DB_NAME']
    connections.append(db);return Connection(db,main)
pymysql.connect=connect
def factory():
    return connect(main=True,host=os.environ['TAIKO_DB_HOST'],port=int(os.environ.get('TAIKO_DB_PORT',3306)),
        user=os.environ['TAIKO_DB_USER'],password=os.environ['TAIKO_DB_PASSWORD'],database=os.environ['TAIKO_DB_NAME'],
        charset='utf8mb4',autocommit=False,connect_timeout=5,read_timeout=10,write_timeout=10)

def response(url,**kwargs):
    calls[0]+=1
    if fault=='upstream-error':raise RuntimeError('Private upstream diagnostic')
    if '/all/songs' in url:
        value={'message':'用户不存在'} if fault=='not-found' else {'message':'ok','data':{'playedRecords':{'scoreInfo':[]}}}
    elif '/search/player' in url:value={'data':{'players':[{'userid':'foreign' if fault=='wrong-profile' else request['identity'],'mydon_name':'Owned synthetic'}]}}
    else:value={'data':{}}
    return types.SimpleNamespace(status_code=500 if fault=='upstream-status' else 200,json=lambda:value)
requests.post=response;requests.get=response
def blocked_http(*a,**kw):raise PermissionError('Actual upstream forbidden')
requests.sessions.Session.send=blocked_http
def change_owner():current_cursor[0].execute('UPDATE bind SET visible=1-visible WHERE qq=%s',(request['principal'],))
real_save=update_user.save_userdata
def save(*args,**kwargs):
    if fault in {'before-publish-owner','rollback-error'}:change_owner()
    if fault=='before-publish-exit':os._exit(47)
    result=real_save(*args,**kwargs)
    if fault=='after-publish-exit':os._exit(48)
    if fault=='after-publish-owner':change_owner()
    return result
update_user.save_userdata=save
def render(identity,*,show_all,score_view):
    assert str(identity)==request['identity'] and json.loads(score_view.current_raw())['profile']['userid']==request['identity']
    if fault=='render-owner':change_owner()
    if fault=='render-error':raise RuntimeError('Private renderer failure')
    if fault=='oversize-image':return b'x'*(16*1024**2+1)
    return b'owned-small-render-boundary'

try:
    sync=None
    if request.get('frozen'):
        reference=Path(request['baseline']).resolve()
        assert str(reference).startswith('/var/tmp/')
        code=(reference/'plugins/utils/update_user.py').read_text()
        old={'__package__':'taiko_bot.runtime.player.center'}
        exec(compile(code,'<frozen-native-wahlap-acquisition>','exec'),old)
        old['save_userdata']=save;sync=old['getUserData']
    result=native.update_native_wahlap(request['principal'],request['identity'],connection_factory=factory,
        userdata_root=root/'userdata',include_image=request.get('image',True),show_all=request.get('showAll',False),sync=sync,render=render)
    hashes=None
    if request.get('hashes'):
        from taiko_store import PublicationStore
        store=PublicationStore(root/'userdata',request['identity'])
        with store.shared():
            reader=store.reader();hashes={'current':hashlib.sha256(reader.current_raw()).hexdigest(),
                'history':{name:hashlib.sha256(reader.history_raw(name)).hexdigest() for name in reader.history_names()}}
    print(json.dumps({'ok':True,'result':{**result,'image':None if result['image'] is None else len(result['image'])},'upstreamCalls':calls[0],'hashes':hashes},ensure_ascii=False),flush=True)
except (native.NativeWahlapDenied,native.NativeWahlapUnavailable) as error:
    print(json.dumps({'ok':False,'reason':'denied' if isinstance(error,native.NativeWahlapDenied) else 'unavailable','message':str(error),'upstreamCalls':calls[0]},ensure_ascii=False),flush=True)
finally:
    for db in connections:
        try:db.close()
        except Exception:pass
