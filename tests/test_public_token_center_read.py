"""Center-owned issuer transport and actual command sender, no local authority."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from plugins.utils import public_score_token as adapter
from taiko_bot import score_token_client as client
from taiko_bot.viewer_client import ViewerClientError
from test_private_read_cache import cfg, transport

PRINCIPAL='qq_official:Abc_123'
TOKEN='a'*48


def result(**extra):
    return {'ok':True,'identityKey':PRINCIPAL,'taikoId':'1001','token':TOKEN,'tokenMask':TOKEN[:8]+'...'+TOKEN[-8:],**extra}


def test_issue_uses_private_center_and_exact_sender_without_local_storage(cfg,monkeypatch):
    calls=transport(monkeypatch,lambda request:httpx.Response(200,json=result()))
    before=list(cfg.runtime_data_dir.iterdir())
    value=client.issue_center_score_token('1001',PRINCIPAL,settings=cfg)
    assert value['token']==TOKEN and value['owner_identity']==PRINCIPAL
    assert len(calls)==1 and calls[0].url.path=='/api/taiko/proxy/bind/score-token'
    assert json.loads(calls[0].content)=={'identityKey':PRINCIPAL,'taikoId':'1001'}
    assert calls[0].headers['authorization']=='Bearer synthetic-private-token'
    assert list(cfg.runtime_data_dir.iterdir())==before and not cfg.userdata_dir.exists()


@pytest.mark.parametrize('status',[400,401,403,404,409,429,500,503])
def test_token_mint_never_retries_or_exposes_private_error_body(cfg,monkeypatch,status):
    calls=transport(monkeypatch,lambda request:httpx.Response(status,text='/private/password'))
    with pytest.raises(ViewerClientError) as error:client.issue_center_score_token('1001',PRINCIPAL,settings=cfg)
    assert error.value.status_code==status and 'password' not in str(error.value) and len(calls)==1


def test_unknown_network_outcome_is_not_replayed(cfg,monkeypatch):
    def answer(request):raise httpx.ReadError('/private/password')
    calls=transport(monkeypatch,answer)
    with pytest.raises(ViewerClientError) as error:client.issue_center_score_token('1001',PRINCIPAL,settings=cfg)
    assert error.value.status_code==502 and len(calls)==1


@pytest.mark.parametrize('extra',[{'identityKey':'onebot_v11:foreign'},{'taikoId':'2001'},{'token':'secret'},{'tokenMask':'mismatch'}])
def test_wrong_identity_source_or_secret_format_is_not_issued(cfg,monkeypatch,extra):
    transport(monkeypatch,lambda request:httpx.Response(200,json=result(**extra)))
    with pytest.raises(ViewerClientError):client.issue_center_score_token('1001',PRINCIPAL,settings=cfg)


@pytest.mark.parametrize('principal,source',[(None,'1001'),('12345','1001'),(PRINCIPAL,'981234567890123456')])
def test_unqualified_owner_or_manual_never_sends_http(cfg,monkeypatch,principal,source):
    calls=transport(monkeypatch,lambda request:pytest.fail('Invalid authority sent HTTP'))
    with pytest.raises(ViewerClientError) as error:client.issue_center_score_token(source,principal,settings=cfg)
    assert error.value.status_code==403 and calls==[]


def test_ownerless_compat_adapter_and_legacy_bearer_fail_before_any_io(monkeypatch):
    monkeypatch.setattr(client,'post_center_binding_operation',lambda *a,**k:pytest.fail('Retired authority sent HTTP'))
    with pytest.raises(adapter.PublicScoreTokenError) as error:adapter.issue_public_score_token_for_taiko_id('1001')
    assert error.value.status_code==403
    with pytest.raises(adapter.PublicScoreTokenError) as error:adapter.fetch_latest_userdata_by_token(TOKEN)
    assert error.value.status_code==410


@pytest.mark.parametrize('mode',['hidden','empty','manual','virtual','group','denied'])
def test_actual_command_only_mints_private_sender_current_real_binding(mode):
    source=Path(__file__).resolve().parents[1]/'plugins/taiko.py'
    fn=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='public_score_token_handle')
    fn.decorator_list=[]
    replies=[];issued=[]
    class Finished(Exception):pass
    class Matcher:
        async def finish(self,message,**kwargs):replies.append(message);raise Finished()
    info={'id':'1001','currentSource':'manual' if mode=='manual' else 'wahlap','currentVirtual':mode=='virtual','visible':0}
    def fetch(principal,cfg):
        assert principal==PRINCIPAL
        if mode=='denied':raise ViewerClientError('denied',status_code=403)
        return None if mode=='empty' else info
    def mint(taiko_id,*,identity_key):
        issued.append((taiko_id,identity_key))
        return {'token':TOKEN,'taiko_id':taiko_id,'owner_display':identity_key}
    ns={'public_score_token':Matcher(),'_is_private_message_event':lambda event:mode!='group',
        '_normalize_identity_key':lambda principal:principal,'get_identity_key':lambda **kw:PRINCIPAL,
        'fetch_center_bind_info':fetch,'_SETTINGS':SimpleNamespace(),'issue_public_score_token_for_taiko_id':mint,
        'PublicScoreTokenError':adapter.PublicScoreTokenError,'ViewerClientError':ViewerClientError,
        '_taiko_bind_usage_message':lambda event:'usage'}
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),fn]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<owned-token-command>','exec'),ns)
    with pytest.raises(Finished):asyncio.run(ns['public_score_token_handle'](object()))
    assert len(replies)==1
    assert issued==([('1001',PRINCIPAL)] if mode=='hidden' else [])
    assert (TOKEN in replies[0])==(mode=='hidden')
