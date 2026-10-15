"""Actual command adapters, input rejection and frozen successful copy/profile."""
import ast
import asyncio
import importlib
from pathlib import Path
import sys
import types

import pytest

SOURCE=Path(__file__).resolve().parents[2]/'taiko_bot/runtime/player/center'
for name,path in [('native_hiroba_fixture',SOURCE),('native_hiroba_fixture.hiroba',SOURCE/'hiroba')]:
    module=types.ModuleType(name);module.__path__=[str(path)];sys.modules[name]=module
native=importlib.import_module('native_hiroba_fixture.hiroba.native_binding')


@pytest.mark.parametrize('principal',[None,'12345','onebot_v11:1 ','qq_official:','onebot_v11:../private'])
def test_unqualified_sender_cannot_discover_or_connect(principal):
    def forbidden(*a,**k):pytest.fail('Invalid sender performed IO')
    with pytest.raises(native.NativeHirobaDenied):
        native.bind_native_hiroba(principal,'synthetic@example.test','synthetic',connection_factory=forbidden,discovery=forbidden)


@pytest.mark.parametrize('identity', ['../private','981234567890123456','',None])
def test_invalid_or_manual_sync_never_connects(identity):
    with pytest.raises(native.NativeHirobaDenied):
        native.sync_native_hiroba('onebot_v11:12345',identity,connection_factory=lambda:pytest.fail('Invalid Source connected'),userdata_root='/var/tmp/unused')


def namespace(names,extras,ns=None):
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    for node in ast.parse((SOURCE/'lifecycle_host.py').read_text()+'\n'+(SOURCE/'identity_cluster.py').read_text()).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list=[];nodes.append(node)
    if ns is None:ns={}
    ns.update({'_runtime_root':lambda:Path('/var/tmp/fixture'),'__package__':'taiko_bot.runtime.player.center','RegexMatched':lambda:None,**extras})
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-native-hiroba-command>','exec'),ns)
    return ns


@pytest.mark.parametrize('synced',[0,1,2])
def test_actual_bind_command_keeps_initial_notice_and_reports_committed_partial_sync(synced):
    sent=[];replies=[];calls=[]
    result=types.SimpleNamespace(taiko_ids=('222','111'),entry={'current_index':0})
    def bind(*args):calls.append(args);return result,synced
    async def send(matcher,event,text):sent.append(text)
    async def finish(matcher,event,text,**kwargs):replies.append(text)
    ns=namespace({'bind_hiroba_handle'},{'asyncio':asyncio,'_normalize_identity_key':lambda x:x,
        'get_identity_key':lambda **kwargs:'qq_official:Abc_', '_create_hiroba_progress_reporter':lambda *args:None,
        '_execute_hiroba_bind':bind,'_send_text_reply_without_finish':send,'_finish_text_reply':finish,
        '_format_bind_entry_summary_safe':lambda entry:'u1:222(JP)* / u2:111(JP)', 'bind_hiroba':object()})
    asyncio.run(ns['bind_hiroba_handle'](object(),match=types.SimpleNamespace(group=lambda i:{1:'synthetic@example.test',2:'synthetic',3:''}[i])))
    assert sent==['开始绑定 Hiroba 账号'] and len(replies)==1
    assert calls[0][:4]==('qq_official:Abc_','synthetic@example.test','synthetic','')
    assert '已切换到 u1：222' in replies[0]
    assert ('已完成 Hiroba 同步' in replies[0])==(synced==2)
    if synced<2:
        assert f'已同步 {synced}/2' in replies[0] and '账号已绑定' in replies[0]
        assert '已自动同步' not in replies[0] and '切换到失败账号' in replies[0]


def test_command_bind_exception_is_fixed_and_never_contains_private_details():
    replies=[]
    async def send(*args):pass
    async def finish(matcher,event,text,**kwargs):replies.append(text)
    def failed(*args):raise RuntimeError('/private/password')
    ns=namespace({'bind_hiroba_handle'},{'asyncio':asyncio,'_normalize_identity_key':lambda x:x,
        'get_identity_key':lambda **kwargs:'onebot_v11:12345','_create_hiroba_progress_reporter':lambda *a:None,
        '_execute_hiroba_bind':failed,'_send_text_reply_without_finish':send,'_finish_text_reply':finish,'bind_hiroba':object()})
    asyncio.run(ns['bind_hiroba_handle'](object(),match=types.SimpleNamespace(group=lambda i:{1:'synthetic@example.test',2:'synthetic',3:''}[i])))
    assert len(replies)==1 and 'password' not in replies[0]


def test_ownerless_update_adapter_does_not_probe_cooldown_or_database():
    ns=namespace({'_execute_hiroba_update'},{'peek_hiroba_sync_cooldown':lambda *args:pytest.fail('Unqualified caller probed Source')})
    assert ns['_execute_hiroba_update']('12345')['ok'] is False


def test_retained_initial_notice_regression_runs_actual_handler_ast(monkeypatch):
    values={'asyncio':asyncio,'_normalize_identity_key':lambda x:x,'get_identity_key':lambda **k:'onebot_v11:12345',
        '_create_hiroba_progress_reporter':lambda *a:None,'_execute_hiroba_bind':lambda *a:None,
        '_send_text_reply_without_finish':lambda *a:None,'_finish_text_reply':lambda *a:None,
        '_format_bind_entry_summary_safe':lambda entry:'summary','bind_hiroba':object()}
    module=types.ModuleType('actual_native_hiroba_command')
    namespace({'bind_hiroba_handle'},values,module.__dict__)
    tree=ast.parse((Path(__file__).parent/'test_hiroba_bind_flow.py').read_text())
    nodes=[n for n in tree.body if getattr(n,'name','') in {'_DummyMatch','test_bind_hiroba_handle_keeps_running_after_initial_notice'}]
    ns={'asyncio':asyncio,'SimpleNamespace':types.SimpleNamespace,'FinishedException':RuntimeError,'_load_taiko_module':lambda:module}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-hiroba-bind-flow>','exec'),ns)
    ns['test_bind_hiroba_handle_keeps_running_after_initial_notice'](monkeypatch)


def test_retained_unreadable_credential_regression_runs_actual_update_adapter(monkeypatch):
    import taiko_bot.runtime.player.center.hiroba.native_binding
    module=types.ModuleType('actual_native_hiroba_update')
    namespace({'_execute_hiroba_update'},{'Path':Path,'os':__import__('os'),
        '_get_taiko_db_connection':lambda:pytest.fail('Synthetic unreadable adapter connected'),
        'peek_hiroba_sync_cooldown':lambda *args:None},module.__dict__)
    tree=ast.parse((Path(__file__).parent/'test_hiroba_update_mode.py').read_text())
    nodes=[n for n in tree.body if getattr(n,'name','')=='test_hiroba_update_returns_actionable_error_for_unreadable_credentials']
    ns={'_load_taiko_module':lambda:module}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-hiroba-update-mode>','exec'),ns)
    ns['test_hiroba_update_returns_actionable_error_for_unreadable_credentials'](monkeypatch)


@pytest.mark.parametrize('command',['更新hiroba','更新hiroba all'])
def test_actual_update_command_forwards_authenticated_sender_and_image_mode(command):
    calls=[];replies=[]
    def update(identity,**kwargs):calls.append((identity,kwargs));return {'ok':True,'image':None}
    async def send(*args,**kwargs):pass
    async def finish(*args,**kwargs):replies.append(args)
    ns=namespace({'hiroba_update_handle'},{'asyncio':asyncio,'re':__import__('re'),
        '_normalize_identity_key':lambda x:x,'get_identity_key':lambda **kwargs:'qq_official:Authenticated_',
        'extract_plain_text':lambda event:command,'_get_current_bind_entry':lambda principal:{'ids':['111'],'sources':{'111':'hiroba'}},
        '_get_selected_bind_slot_number':lambda entry:1,'_get_current_bind_taiko_id':lambda entry:'111',
        '_infer_bind_source':lambda *args:'hiroba','peek_hiroba_sync_cooldown':lambda *args:None,
        '_create_hiroba_progress_reporter':lambda *args:None,'_send_text_reply_without_finish':send,
        '_execute_hiroba_update':update,'_finish_hiroba_update_success_reply':finish,'hiroba_update':object()})
    asyncio.run(ns['hiroba_update_handle'](types.SimpleNamespace(mentioned_principal='qq_official:Foreign_')))
    assert len(calls)==1 and len(replies)==1
    identity,kwargs=calls[0]
    assert identity=='111' and kwargs['identity_key']=='qq_official:Authenticated_'
    assert kwargs['include_changes_image'] is True and kwargs['show_all_changes']==command.endswith(' all')
