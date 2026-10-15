"""Sender/current command regression and no-IO invalid/update admission cases."""
import ast
import asyncio
import json
from pathlib import Path
import re
import types
import pytest
from taiko_bot.runtime.player.center import native_wahlap_update as native
from taiko_store import PublicationError

SOURCE=Path(__file__).resolve().parents[2]/'taiko_bot/runtime/player/center'

@pytest.mark.parametrize('principal,identity',[(None,'12345'),('12345','12345'),('onebot_v11:1 ','12345'),('qq_official:','12345'),
    ('qq_official:A','../other'),('qq_official:A','981234567890123456'),('qq_official:A',None)])
def test_invalid_sender_or_source_never_connects(principal,identity):
    with pytest.raises(native.NativeWahlapDenied):native.update_native_wahlap(principal,identity,
        connection_factory=lambda:pytest.fail('Invalid update connected'),userdata_root='/var/tmp/unused')

def test_native_admission_refusal_happens_before_sql(monkeypatch):
    monkeypatch.setattr(native,'_admission',types.SimpleNamespace(acquire=lambda **kwargs:False))
    with pytest.raises(native.NativeWahlapUnavailable):native.update_native_wahlap('onebot_v11:12345','111',
        connection_factory=lambda:pytest.fail('Unadmitted update connected'),userdata_root='/var/tmp/unused')

def namespace(names,values,ns=None):
    if ns is None:ns={}
    from taiko_bot.runtime.player.lifecycle_authority import delivery_for
    ns['delivery_for']=delivery_for
    ns.update({'__package__':'taiko_bot.runtime.player.center',**values})
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    for node in ast.parse((SOURCE/'lifecycle_host.py').read_text()+'\n'+(SOURCE/'update_cluster.py').read_text()).body:
        if getattr(node,'name','') in names:node.decorator_list=[];nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-native-Wahlap>','exec'),ns);return ns

def values():return {'asyncio':asyncio,'_is_external_bot_mentioned':lambda e:False,'_is_update_command_targeting_other_account':lambda e:False,
    '_parse_update_command':lambda text:{'show_all':text.endswith(' all')},'extract_plain_text':lambda e:getattr(e,'text','更新广场'),
    '_normalize_identity_key':lambda p:p,'get_identity_key':lambda **kw:'qq_official:Sender_',
    '_get_current_bind_entry':lambda p:{'ids':['111'],'sources':{'111':'wahlap'}},'_get_current_bind_taiko_id':lambda entry:'111',
    '_get_selected_bind_slot_number':lambda entry:1,'_infer_bind_source':lambda *a:'wahlap','try_acquire_taiko_update_slot':lambda identity:True,
    '_get_taiko_bind_info':lambda *a:pytest.fail('Updated handler made a separate legacy current query'),'update':object()}

@pytest.mark.parametrize('show_all',[False,True])
def test_actual_handler_forwards_own_sender_and_captured_current_with_image_mode(show_all):
    calls=[];images=[];texts=[]
    def update(identity,**kwargs):calls.append((identity,kwargs));return {'ok':True,'image':b'synthetic-boundary'}
    async def image(*args,**kwargs):images.append(kwargs)
    async def text(*args,**kwargs):texts.append(args)
    ns=namespace({'update_handle'},{**values(),'_execute_taiko_update':update,'_finish_image_reply':image,'_finish_text_reply':text})
    asyncio.run(ns['update_handle'](types.SimpleNamespace(text='taikoupdate all' if show_all else '更新广场',mention='qq_official:Foreign')))
    assert calls==[('111',{'identity_key':'qq_official:Sender_','show_all_changes':show_all,'include_changes_image':True})]
    assert len(images)==1 and not texts and images[0]['prefer_markdown_image'] is True

def test_unqualified_adapter_never_imports_writer_or_connects():
    ns=namespace({'_execute_taiko_update'},{})
    assert ns['_execute_taiko_update']('111')['ok'] is False

def test_actual_handler_metadata_failure_has_fixed_state_copy():
    replies=[]
    def failed(*args):raise RuntimeError('/private/password')
    async def text(*args,**kwargs):replies.append(args[2])
    ns=namespace({'update_handle'},{**values(),'_get_current_bind_entry':failed,'_finish_text_reply':text})
    asyncio.run(ns['update_handle'](object()))
    assert replies==['绑定服务暂不可用，请稍后重试。']

def test_actual_update_adapter_hides_private_driver_details(monkeypatch):
    def failed(*args,**kwargs):raise RuntimeError('/private/password')
    monkeypatch.setattr(native,'update_native_wahlap',failed)
    ns=namespace({'_execute_taiko_update'},{'Path':Path,'os':__import__('os'),'_get_taiko_db_connection':object()})
    result=ns['_execute_taiko_update']('111',identity_key='onebot_v11:12345')
    assert result['ok'] is False and 'password' not in result['message']

def test_first_bind_auto_update_carries_owner_and_retains_existing_success_copy():
    calls=[]
    def update(identity,**kwargs):calls.append((identity,kwargs));return {'ok':True,'image':None}
    ns=namespace({'_build_bind_auto_update_result'},{'_execute_taiko_update':update})
    assert ns['_build_bind_auto_update_result']('onebot_v11:12345','111',False) is None
    result=ns['_build_bind_auto_update_result']('onebot_v11:12345','111',True)
    assert result['message']=='首次绑定已自动执行一次 taikoupdate。'
    assert calls==[('111',{'identity_key':'onebot_v11:12345','include_changes_image':True})]

def test_selected_retained_official_and_cooldown_commands(monkeypatch):
    module=types.ModuleType('actual_native_wahlap_commands')
    async def finish(*args,**kwargs):pass
    namespace({'update_handle'},{**values(),'_execute_taiko_update':lambda *a,**kw:None,'_finish_text_reply':finish,
        'resolve_target_identity_key':lambda **kw:'qq_official:Foreign'},module.__dict__)
    class Group:
        def __init__(self,**kwargs):self.text='更新广场'
    class Segment:
        def __init__(self,*args):pass
    tree=ast.parse((Path(__file__).parent/'test_official_update_behavior.py').read_text())
    nodes=[node for node in tree.body if getattr(node,'name','') in {'test_update_handle_ignores_mentioned_user_for_official_group','test_update_handle_stays_silent_and_skips_fetch_during_id_cooldown'}]
    ns={'asyncio':asyncio,'_load_taiko_module':lambda:module,'FakeQQGroupEvent':Group,'FakeSegment':Segment}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-official-update-tests>','exec'),ns)
    for node in nodes:ns[node.name](monkeypatch)

def test_retained_bind_image_reply_runs_actual_adapter(monkeypatch):
    module=types.ModuleType('actual_bind_success_reply')
    async def finish(*args,**kwargs):pass
    namespace({'_finish_bind_success_reply'},{'_finish_image_reply':finish,'_finish_text_reply':finish,
        '_is_qq_official_event':lambda event:True,'MatcherException':RuntimeError},module.__dict__)
    tree=ast.parse((Path(__file__).parent/'test_bind_auto_update_reply.py').read_text())
    nodes=[node for node in tree.body if getattr(node,'name','') in {'_FakeQQGroupEvent','test_finish_bind_success_reply_prefers_image_when_auto_update_has_result'}]
    ns={'asyncio':asyncio,'_load_taiko_module':lambda:module}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-bind-auto-update-image>','exec'),ns)
    ns['test_finish_bind_success_reply_prefers_image_when_auto_update_has_result'](monkeypatch)

def test_actual_owned_upstream_rejects_fuzzy_profile_before_writer(monkeypatch,tmp_path):
    import taiko_bot.runtime.player.center.update_user as update
    config=tmp_path/'synthetic-public-config.json';config.write_text(json.dumps({'cookie':'synthetic-public-cookie'}));monkeypatch.setenv('TAIKO_WAHLAP_CONFIG_PATH',str(config))
    def post(url,**kwargs):
        return types.SimpleNamespace(status_code=200,json=lambda:{'message':'ok','data':{'players':[{'userid':'foreign'}]}} if '/search/player' in url else {'message':'ok','data':{'playedRecords':{'scoreInfo':[]}}})
    monkeypatch.setattr(update.requests,'post',post);monkeypatch.setattr(update.requests,'get',lambda *a,**kw:types.SimpleNamespace(status_code=200,json=lambda:{'data':{}}))
    monkeypatch.setattr(update,'save_userdata',lambda *a,**kw:pytest.fail('Foreign profile reached writer'))
    with pytest.raises(PublicationError):update.getUserData('12345',publication_store=object())
    assert update._select_search_player([{'userid':'foreign'}],'12345')=={'userid':'foreign'}
