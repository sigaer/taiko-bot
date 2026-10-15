"""Owned native Hiroba SQL/publication child; synthetic upstream, private stdin."""
import builtins
from dataclasses import asdict
from functools import wraps
import json
import os
from pathlib import Path
import sys
import types

request=json.loads(sys.stdin.buffer.read(32769))
root=Path(request['root']).resolve()
assert str(root).startswith('/var/tmp/') and root.is_dir()
os.environ['TAIKO_RUNTIME_ENV_FILE']=str(root/'absent-native-runtime.env')
os.environ['HIROBA_CRED_KEY']='owned-synthetic-native-credential-key'
os.environ['PYTHONDONTWRITEBYTECODE']='1'

def guard(path,mode='r'):
    if isinstance(path,(str,bytes,Path)):
        resolved=Path(path).resolve()
        if str(resolved).startswith(('/home/sigaer/taiko/userdata/','/home/sigaer/taiko/secrets/')) or str(resolved)=='/etc/taiko-runtime.env':
            raise PermissionError('Production personal storage prohibited')
        if any(flag in mode for flag in 'wax+') and root not in resolved.parents:
            raise PermissionError('Native QA write outside owned root')
old_open=builtins.open
@wraps(old_open)
def safe_open(path,*args,**kwargs):guard(path,args[0] if args else kwargs.get('mode','r'));return old_open(path,*args,**kwargs)
builtins.open=safe_open
old_path_open=Path.open
@wraps(old_path_open)
def safe_path_open(self,*args,**kwargs):guard(self,args[0] if args else kwargs.get('mode','r'));return old_path_open(self,*args,**kwargs)
Path.open=safe_path_open

from taiko_bot.runtime.player.center.hiroba.native_binding import bind_native_hiroba,sync_native_hiroba,NativeHirobaDenied,NativeHirobaUnavailable
import pymysql
import requests
def forbidden_http(*args,**kwargs):raise PermissionError('Official HTTP prohibited')
requests.sessions.Session.send=forbidden_http
fault=request.get('fault');connections=[];current_cursor=[None];commits=[0];synced=[False]

class Cursor:
    def __init__(self,real):self.real=real
    def execute(self,sql,args=()):
        if 'GET_LOCK' in sql:print('{"event":"gate-attempt"}',flush=True)
        result=self.real.execute(sql,args)
        if sql.startswith('UPDATE bind SET source') and fault=='late-bind':raise RuntimeError('Private synthetic SQL fault')
        if sql.startswith('INSERT INTO web_hiroba_credentials') and fault=='late-credential':raise RuntimeError('Private synthetic credential fault')
        return result
    def fetchone(self):return self.real.fetchone()
    def fetchall(self):return self.real.fetchall()
    def close(self):return self.real.close()

class Connection:
    def __init__(self,real):self.real=real
    def cursor(self):
        current_cursor[0]=self.real.cursor();return Cursor(current_cursor[0])
    def begin(self):return self.real.begin()
    def commit(self):
        commits[0]+=1
        target=2 if request.get('action')=='sync' else 1
        if commits[0]==target:
            if fault=='before-commit-exit':os._exit(45)
            if fault=='before-commit-error':raise RuntimeError('Private uncertain COMMIT')
        self.real.commit()
        if commits[0]==target:
            if fault=='after-commit-exit':os._exit(46)
            if fault=='after-commit-error':raise RuntimeError('Private lost ACK')
    def rollback(self):
        if fault=='rollback-error':raise RuntimeError('Private failed rollback')
        return self.real.rollback()
    def close(self):return self.real.close()

def factory():
    assert os.environ.get('TAIKO_ALLOW_TEST_DB_MUTATION')=='1'
    db=pymysql.connect(host=os.environ['TAIKO_DB_HOST'],port=int(os.environ.get('TAIKO_DB_PORT',3306)),
        user=os.environ['TAIKO_DB_USER'],password=os.environ['TAIKO_DB_PASSWORD'],database=os.environ['TAIKO_DB_NAME'],
        charset='utf8mb4',autocommit=False,connect_timeout=5,read_timeout=10,write_timeout=10)
    with db.cursor() as cursor:
        cursor.execute('SELECT DATABASE()');database=cursor.fetchone()[0]
        assert database.endswith('_test') and database==os.environ['TAIKO_DB_NAME']
    connections.append(db);return Connection(db)

def mutate_owner():
    current_cursor[0].execute("UPDATE web_hiroba_credentials SET configured_by_qq=%s WHERE taiko_no=%s",('qq_official:foreign',request['identity']))

def sync(identity,**kwargs):
    synced[0]=True;store=kwargs['publication_store'];store._require_lock(write=True)
    owned=kwargs['email'] is not None and kwargs['password'] is not None
    assert owned==request.get('expectOwned',True)
    if fault in {'late-owner','rollback-error'}:
        mutate_owner()
        if fault=='rollback-error':raise RuntimeError('Private failed SQL proof')
    if fault=='upstream':raise RuntimeError('Private upstream fault')
    if fault=='before-publish-exit':os._exit(47)
    payload=json.dumps({'profile':{'userid':identity},'songs':[],'ownedSyntheticUpdate':True},separators=(',',':')).encode()
    reference=store.stage(payload)
    store.publish({'current':reference,'history/data_20261012000000.json':reference})
    if fault=='after-publish-exit':os._exit(48)
    if fault=='after-publish-owner':mutate_owner()
    return identity

def render(identity,*,show_all,score_view):
    assert str(identity)==request['identity'] and json.loads(score_view.current_raw())['ownedSyntheticUpdate'] is True
    if fault=='render-owner':mutate_owner()
    if fault=='render-error':raise RuntimeError('Private render failure')
    return b'owned-small-render-boundary'

try:
    if request.get('action')=='sync':
        result=sync_native_hiroba(request['principal'],request['identity'],connection_factory=factory,userdata_root=root/'userdata',
            current_only=request.get('currentOnly',True),include_image=request.get('image',False),sync=sync,render=render)
        result={**result,'image':None if result['image'] is None else len(result['image']),'upstreamCalled':synced[0]}
    else:
        cards=[types.SimpleNamespace(taiko_no=value) for value in request['ids']]
        result=asdict(bind_native_hiroba(request['principal'],'synthetic@example.test','synthetic-password',target=request.get('target',''),
            connection_factory=factory,discovery=lambda *args:cards))
    print(json.dumps({'ok':True,'result':result},separators=(',',':')),flush=True)
except (NativeHirobaDenied,NativeHirobaUnavailable) as error:
    print(json.dumps({'ok':False,'reason':'denied' if isinstance(error,NativeHirobaDenied) else 'unavailable','message':str(error),'upstreamCalled':synced[0]},separators=(',',':')),flush=True)
finally:
    for db in connections:
        try:db.close()
        except Exception:pass
