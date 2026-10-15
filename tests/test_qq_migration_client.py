import ast
from dataclasses import replace
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from taiko_bot import qq_migration_client as client
from taiko_bot.viewer_client import ViewerClientError
from test_private_read_cache import transport
from test_viewer_access import _make_settings

PRINCIPAL='onebot_v11:12345';TARGET='qq_official:Sender_';CODE='a'*32
SOURCE=Path(__file__).resolve().parents[1]
def cfg(tmp_path):return _make_settings(tmp_path,viewer_developer_token='synthetic-qq-token')
def issue():return {'ok':True,'identityKey':PRINCIPAL,'qq':'12345','code':CODE,'expiresInSeconds':600}
def migrated():return {'ok':True,'found':False,'identityKey':TARGET,'bindings':[],
    'operation':{'kind':'qq-migrate','qq':'12345','sourceCurrentId':'111','firstBinding':True,'replayed':True}}

def test_issue_is_private_single_request_and_never_creates_local_authority(tmp_path,monkeypatch):
    settings=cfg(tmp_path);before=list(settings.runtime_data_dir.iterdir())
    calls=transport(monkeypatch,lambda request:httpx.Response(200,json=issue()))
    assert client.issue_center_qq_migration_code(PRINCIPAL,settings=settings)==CODE
    assert len(calls)==1 and calls[0].headers['authorization']=='Bearer synthetic-qq-token'
    assert json.loads(calls[0].content)=={'identityKey':PRINCIPAL}
    assert calls[0].url.path.endswith('/bind/qq-code') and list(settings.runtime_data_dir.iterdir())==before

@pytest.mark.parametrize('status',[401,403,409,429,503])
def test_issue_error_never_retries_or_displays_private_diagnostics(tmp_path,monkeypatch,status):
    calls=transport(monkeypatch,lambda request:httpx.Response(status,json={'message':'/password/secret'}))
    with pytest.raises(ViewerClientError) as e:client.issue_center_qq_migration_code(PRINCIPAL,settings=cfg(tmp_path))
    assert e.value.status_code==status and 'password' not in str(e.value) and len(calls)==1

@pytest.mark.parametrize('failure',['network','503'])
def test_consumption_retries_same_code_and_target_only(tmp_path,monkeypatch,failure):
    times=[0]
    def reply(request):
        times[0]+=1
        if times[0]==1:
            if failure=='network':raise httpx.ReadError('private secret')
            return httpx.Response(503,json={})
        return httpx.Response(200,json=migrated())
    calls=transport(monkeypatch,reply)
    result=client.migrate_center_qq_bindings('12345',TARGET,code=CODE,settings=cfg(tmp_path))
    assert result['replayed'] and result['binding'] is None and len(calls)==2
    assert calls[0].content==calls[1].content and json.loads(calls[0].content)=={'identityKey':TARGET,'qq':'12345','code':CODE}

def test_direct_self_migration_has_no_automatic_retry(tmp_path,monkeypatch):
    calls=transport(monkeypatch,lambda request:httpx.Response(503,json={}))
    with pytest.raises(ViewerClientError):client.migrate_center_qq_bindings('12345',PRINCIPAL,settings=cfg(tmp_path))
    assert len(calls)==1

@pytest.mark.parametrize('principal,qq,code',[(TARGET,'12345',''),('12345','12345',CODE),(TARGET,'01234',CODE),(TARGET,'12345','bad'),(TARGET,'12345',None)])
def test_invalid_identity_or_proof_cannot_perform_http(tmp_path,monkeypatch,principal,qq,code):
    calls=transport(monkeypatch,lambda request:pytest.fail('Invalid QQ request performed HTTP'))
    with pytest.raises(ViewerClientError):client.migrate_center_qq_bindings(qq,principal,code=code,settings=cfg(tmp_path))
    assert not calls

def test_no_token_and_redirect_cannot_forward_qq_code(tmp_path,monkeypatch):
    calls=transport(monkeypatch,lambda request:httpx.Response(307,headers={'location':'https://foreign.test/'}))
    with pytest.raises(ViewerClientError):client.issue_center_qq_migration_code(PRINCIPAL,settings=replace(cfg(tmp_path),viewer_developer_token=''))
    assert not calls
    with pytest.raises(ViewerClientError):client.migrate_center_qq_bindings('12345',TARGET,code=CODE,settings=cfg(tmp_path))
    assert len(calls)==1

@pytest.mark.parametrize('field,value',[('identityKey',TARGET),('qq','54321'),('code','plain'),('expiresInSeconds',True)])
def test_issue_return_is_bound_to_requested_source(tmp_path,monkeypatch,field,value):
    result=issue();result[field]=value;transport(monkeypatch,lambda request:httpx.Response(200,json=result))
    with pytest.raises(ViewerClientError):client.issue_center_qq_migration_code(PRINCIPAL,settings=cfg(tmp_path))

@pytest.mark.parametrize('field,value',[('qq','54321'),('sourceCurrentId','../private'),('firstBinding',1),('replayed',1)])
def test_consume_receipt_types_are_strict(tmp_path,monkeypatch,field,value):
    result=migrated();result['operation'][field]=value;transport(monkeypatch,lambda request:httpx.Response(200,json=result))
    with pytest.raises(ViewerClientError):client.migrate_center_qq_bindings('12345',TARGET,code=CODE,settings=cfg(tmp_path))

def namespace(names,values):
    ns={'__package__':'plugins','RegexMatched':lambda:None,**values}
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    for node in ast.parse('\n'.join((SOURCE/'taiko_bot/runtime/player/client'/name).read_text().replace('from __future__ import annotations', '') for name in ('lifecycle_host.py','identity_cluster.py'))).body:
        if getattr(node,'name','') in names:node.decorator_list=[];nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-client-QQ-command>','exec'),ns);return ns

@pytest.mark.parametrize('handler',['bind_qq_handle','qq_migration_code_handle'])
def test_group_message_is_denied_before_sender_or_http(handler):
    replies=[]
    async def finish(*args,**kwargs):replies.append(args[2])
    ns=namespace({handler},{'_is_private_message_event':lambda event:False,'_finish_text_reply':finish,
        'bind_qq':object(),'qq_migration_code':object(),'get_identity_key':lambda **kw:pytest.fail('Group probed sender')})
    asyncio.run(ns[handler](object()));assert len(replies)==1 and '私聊' in replies[0]

def test_actual_command_uses_authenticated_private_sender_and_code():
    calls=[];replies=[]
    def migrate(qq,target,**kwargs):calls.append((qq,target,kwargs));return True,'已迁移'
    async def finish(*args,**kwargs):replies.append(args[2])
    ns=namespace({'bind_qq_handle'},{'asyncio':asyncio,'_is_private_message_event':lambda e:True,
        '_normalize_identity_key':lambda p:p,'get_identity_key':lambda **kw:TARGET,'_migrate_bind_from_legacy_qq':migrate,
        '_finish_text_reply':finish,'bind_qq':object(),'ViewerClientError':ViewerClientError})
    asyncio.run(ns['bind_qq_handle'](object(),match=SimpleNamespace(group=lambda i:{1:'12345',2:'A'*32}[i])))
    assert calls==[('12345',TARGET,{'code':CODE})] and replies==['已迁移']

def test_actual_migration_adapter_replay_does_not_restart_update_or_local_io(monkeypatch):
    calls=[]
    def migrate(qq,target,**kw):calls.append((qq,target,kw));return {'binding':None,'firstBinding':True,'replayed':True,'sourceCurrentId':'111'}
    monkeypatch.setattr(client,'migrate_center_qq_bindings',migrate)
    ns=namespace({'_migrate_bind_from_legacy_qq'},{'_normalize_identity_key':lambda p:p,'_SETTINGS':object(),
        '_center_bind_info_to_entry':lambda value:None,'BIND_VERIFY_SESSIONS':{},
        '_get_taiko_db_connection':lambda:pytest.fail('Migration read local DB'),
        '_build_bind_auto_update_tip':lambda *args:pytest.fail('Replay repeated update')})
    assert ns['_migrate_bind_from_legacy_qq']('12345',TARGET,code=CODE)[0] is True
    assert calls[0][:2]==('12345',TARGET)

def test_dead_local_binding_reader_is_removed_from_actual_plugin():
    names={getattr(node,'name','') for node in ast.parse('\n'.join((SOURCE/'taiko_bot/runtime/player/client'/name).read_text().replace('from __future__ import annotations', '') for name in ('lifecycle_host.py','identity_cluster.py'))).body}
    assert '_load_multi_bind_store' not in names and '_ensure_multi_bind_entry' not in names
