import ast
from dataclasses import replace
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from taiko_bot import binding_mutation_client as client
from taiko_bot.viewer_client import ViewerClientError,CenterBindSlot
from test_private_read_cache import transport
from test_viewer_access import _make_settings

NONCE='a'*32
PRINCIPAL='onebot_v11:12345'


def response(kind='remove',**effect):
    operation={'kind':kind,'removed':True,'needsConfirmation':False,'targetTaikoId':'111'} if kind=='remove' else {'kind':'visibility','matched':2}
    return {'ok':True,'found':False,'identityKey':PRINCIPAL,'bindings':[],'operation':{**operation,**effect}}


def cfg(tmp_path):return _make_settings(tmp_path,viewer_developer_token='synthetic-binding-token')


def test_mutation_headers_nonce_and_response_with_no_authoritative_local_files(tmp_path,monkeypatch):
    settings=cfg(tmp_path)
    before=list(settings.runtime_data_dir.iterdir())
    calls=transport(monkeypatch,lambda request:httpx.Response(200,json=response()))
    result=client.remove_center_bind(PRINCIPAL,'111',force_last=True,request_id=NONCE,settings=settings)
    assert result['removed'] and result['binding'] is None and result['targetTaikoId']=='111'
    assert len(calls)==1 and calls[0].headers['authorization']=='Bearer synthetic-binding-token'
    assert json.loads(calls[0].content)=={'identityKey':PRINCIPAL,'taikoId':'111','forceLast':True,'requestId':NONCE}
    assert list(settings.runtime_data_dir.iterdir())==before


@pytest.mark.parametrize('failure',['network','503'])
def test_retry_uses_exact_same_concrete_id_and_nonce(tmp_path,monkeypatch,failure):
    count=[0]
    def reply(request):
        count[0]+=1
        if count[0]==1:
            if failure=='network':raise httpx.ReadError('/private/password')
            return httpx.Response(503,json={'message':'/private/password'})
        return httpx.Response(200,json=response())
    calls=transport(monkeypatch,reply)
    assert client.remove_center_bind(PRINCIPAL,'111',settings=cfg(tmp_path))['removed']
    assert len(calls)==2 and calls[0].content==calls[1].content
    assert len(json.loads(calls[0].content)['requestId'])==32


@pytest.mark.parametrize('status',[400,401,403,404,409,429,500,503])
def test_fail_closed_preserves_status_and_never_exposes_server_diagnostics(tmp_path,monkeypatch,status):
    calls=transport(monkeypatch,lambda request:httpx.Response(status,json={'message':'/private/password'}))
    with pytest.raises(ViewerClientError) as error:client.set_center_bind_visibility(PRINCIPAL,0,settings=cfg(tmp_path))
    assert error.value.status_code==status and 'password' not in str(error.value)
    assert len(calls)==(2 if status==503 else 1)


def test_no_redirect_can_forward_principal_or_nonce(tmp_path,monkeypatch):
    calls=transport(monkeypatch,lambda request:httpx.Response(307,headers={'location':'https://foreign.example.test/'}))
    with pytest.raises(ViewerClientError) as error:client.remove_center_bind(PRINCIPAL,'111',settings=cfg(tmp_path))
    assert error.value.status_code==502 and len(calls)==1


def test_streamed_metadata_is_bounded_before_json_decode(tmp_path,monkeypatch):
    pulled=[0]
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(128):pulled[0]+=1;yield b'x'*16384
    transport(monkeypatch,lambda request:httpx.Response(200,stream=Body()))
    with pytest.raises(ViewerClientError):client.remove_center_bind(PRINCIPAL,'111',settings=cfg(tmp_path))
    assert pulled[0]<=17


@pytest.mark.parametrize('effect',[{'removed':False,'needsConfirmation':False},{'removed':True,'needsConfirmation':True},{'targetTaikoId':'222'},{'removed':1}])
def test_invalid_operation_cannot_be_reported_as_a_delete(tmp_path,monkeypatch,effect):
    transport(monkeypatch,lambda request:httpx.Response(200,json=response(**effect)))
    with pytest.raises(ViewerClientError):client.remove_center_bind(PRINCIPAL,'111',settings=cfg(tmp_path))


def test_token_and_bad_nonce_fail_before_http(tmp_path,monkeypatch):
    calls=transport(monkeypatch,lambda request:pytest.fail('Invalid request sent HTTP'))
    with pytest.raises(ViewerClientError):client.remove_center_bind(PRINCIPAL,'111',request_id='not-a-nonce',settings=cfg(tmp_path))
    with pytest.raises(ViewerClientError):client.set_center_bind_visibility(PRINCIPAL,1,settings=replace(cfg(tmp_path),viewer_developer_token=''))
    assert not calls


@pytest.mark.parametrize('field,value',[('identityKey','qq_official:foreign'),('found',True),('bindings','invalid')])
def test_foreign_or_malformed_metadata_is_never_a_success(tmp_path,monkeypatch,field,value):
    payload=response();payload[field]=value
    transport(monkeypatch,lambda request:httpx.Response(200,json=payload))
    with pytest.raises(ViewerClientError):client.remove_center_bind(PRINCIPAL,'111',settings=cfg(tmp_path))


def test_framework_redelivery_uses_a_stable_scope_specific_nonce():
    event=SimpleNamespace(message_id=123,time=456)
    same=SimpleNamespace(message_id=123,time=456)
    assert client.command_request_id(event,PRINCIPAL,'remove')==client.command_request_id(same,PRINCIPAL,'remove')
    assert client.command_request_id(event,PRINCIPAL,'remove')!=client.command_request_id(event,PRINCIPAL,'visibility')
    assert client.command_request_id(event,PRINCIPAL,'remove')!=client.command_request_id(event,'qq_official:Other','remove')


def commands(text,names,namespace):
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    nodes += [node for node in ast.parse(text).body if isinstance(node,ast.FunctionDef) and node.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<client-binding-command>','exec'),namespace)
    return namespace


def test_actual_visibility_command_never_upserts_or_opens_sql(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(client,'set_center_bind_visibility',lambda principal,visible,**kwargs:calls.append((principal,visible,kwargs)) or {'matched':2})
    from taiko_runtime.platform_adapter import parse_identity_key
    ns=commands((Path(__file__).resolve().parents[1]/'plugins/taiko.py').read_text(),{'_set_taiko_bind_visibility','_normalize_identity_key'},
        {'parse_identity_key':parse_identity_key,'_SETTINGS':cfg(tmp_path)})
    assert ns['_set_taiko_bind_visibility'](PRINCIPAL,0)==2
    assert calls[0][:2]==(PRINCIPAL,0)


@pytest.mark.parametrize('current,target,expected',[(0,'111','222'),(1,'222','333'),(2,'333','222'),(1,'111','222'),(1,'333','222')])
def test_frozen_client_deletion_selection_oracle(current,target,expected):
    root=Path(__file__).resolve().parents[1]
    frozen=subprocess.check_output(['git','show','47bf5c1:plugins/taiko.py'],cwd=root,text=True)
    entry={'ids':['111','222','333'],'current_index':current,'current_slot':current+1,'sources':{key:'wahlap' for key in ['111','222','333']}}
    saved={}
    class Cursor:
        def execute(self,query,args=()):
            if query.startswith('update bind set id='):saved['current']=args[0]
        def fetchone(self):return (entry['ids'][current],)
        def close(self):pass
    db=SimpleNamespace(cursor=lambda:Cursor(),commit=lambda:None,close=lambda:None)
    ns=commands(frozen,{'_remove_bind_record','_resolve_bind_remove_target'},
        {'re':__import__('re'),'_get_current_bind_entry':lambda key:entry,'_infer_bind_source':lambda identity,sources:'wahlap',
         '_normalize_identity_key':lambda key:key,'_get_taiko_db_connection':lambda:db,
         '_load_multi_bind_store':lambda:{PRINCIPAL:entry},'_ensure_multi_bind_entry':lambda store,key,fallback:store[key],
         '_save_multi_bind_store':lambda store:saved.update(store),'_format_multi_bind_summary':lambda value:'summary',
         'BIND_DELETE_CONFIRM_SESSIONS':{}})
    assert ns['_remove_bind_record'](PRINCIPAL,target)[0]
    assert saved['current']==expected and saved[PRINCIPAL]['ids']==[key for key in entry['ids'] if key!=target]
