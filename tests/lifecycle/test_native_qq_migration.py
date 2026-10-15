"""Actual private command adapters; unsafe identity/code never reaches SQL."""
import ast
import asyncio
import re
import types
from pathlib import Path
import pytest
from taiko_bot.runtime.player.center import bot_qq_migration as native

SOURCE=Path(__file__).resolve().parents[2]/'taiko_bot/runtime/player/center'


@pytest.mark.parametrize('principal',[None,'12345','qq_official:A','onebot_v11:12345 ','onebot_v11:01234','onebot_v11:1','onebot_v11:../1'])
def test_code_issuance_needs_actual_onebot_qq_sender(principal):
    with pytest.raises(native.QqMigrationDenied):
        native.issue_qq_migration_code(principal,connection_factory=lambda:pytest.fail('Unsafe code issue performed SQL'))


@pytest.mark.parametrize('qq,target,code',[
    ('12345','qq_official:A',''),('12345','12345','a'*32),('12345','onebot_v11:54321',''),
    ('12345','qq_official:A','secret'),('12345','qq_official:A',None),
    ('01234','qq_official:A','a'*32),('../1','qq_official:A','a'*32),
    ('12345','qq_official:A ','a'*32),('12345','qq_official:A','A'*32),
])
def test_unsafe_or_unproved_migration_never_connects(qq,target,code):
    with pytest.raises(native.QqMigrationDenied):
        native.migrate_qq_bindings(qq,target,code=code,connection_factory=lambda:pytest.fail('Unsafe migration performed SQL'))


def namespace(names,values,ns=None):
    if ns is None:ns={}
    ns.update({'__package__':'taiko_bot.runtime.player.center','RegexMatched':lambda:None,**values})
    nodes=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    for node in ast.parse((SOURCE/'lifecycle_host.py').read_text()+'\n'+(SOURCE/'identity_cluster.py').read_text()).body:
        if getattr(node,'name','') in names:node.decorator_list=[];nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-private-QQ-command>','exec'),ns)
    return ns


@pytest.mark.parametrize('handler',['qq_migration_code_handle','bind_qq_handle'])
def test_group_command_refuses_before_sender_or_sql(handler):
    replies=[]
    async def finish(*args,**kwargs):replies.append(args[2])
    ns=namespace({handler},{'_is_private_message_event':lambda event:False,'_finish_text_reply':finish,
        'qq_migration_code':object(),'bind_qq':object(),'get_identity_key':lambda **kwargs:pytest.fail('Group probed private identity')})
    asyncio.run(ns[handler](object()))
    assert len(replies)==1 and '私聊' in replies[0]


def test_command_migration_uses_private_sender_and_supplied_code():
    calls=[];replies=[]
    async def finish(*args,**kwargs):replies.append(args)
    def migrate(qq,target,**kwargs):calls.append((qq,target,kwargs));return True,'已迁移',None
    ns=namespace({'bind_qq_handle'},{'asyncio':asyncio,'_is_private_message_event':lambda event:True,
        '_normalize_identity_key':lambda x:x,'get_identity_key':lambda **kwargs:'qq_official:Sender_',
        '_extract_bind_qq_input':lambda text:'12345','_migrate_bind_from_legacy_qq_detail':migrate,
        '_finish_bind_success_reply':finish,'_finish_text_reply':finish,'bind_qq':object()})
    asyncio.run(ns['bind_qq_handle'](object(),match=types.SimpleNamespace(string='绑定QQ 12345 '+ 'A'*32,group=lambda i:'A'*32)))
    assert calls==[('12345','qq_official:Sender_',{'code':'a'*32})] and len(replies)==1


def test_code_issuance_reply_uses_onebot_sender_private_only(monkeypatch):
    calls=[];replies=[]
    def issue(principal,**kwargs):calls.append(principal);return 'a'*32
    monkeypatch.setattr(native,'issue_qq_migration_code',issue)
    async def finish(*args,**kwargs):replies.append(args[2])
    ns=namespace({'qq_migration_code_handle'},{'asyncio':asyncio,'_is_private_message_event':lambda event:True,
        '_normalize_identity_key':lambda x:x,'get_identity_key':lambda **kwargs:'onebot_v11:12345',
        '_get_taiko_db_connection':object(),'_finish_text_reply':finish,'qq_migration_code':object()})
    asyncio.run(ns['qq_migration_code_handle'](object()))
    assert calls==['onebot_v11:12345'] and len(replies)==1
    assert '绑定QQ 12345 '+ 'a'*32 in replies[0] and '十分钟' in replies[0]


def test_selected_retained_migration_tests_run_actual_adapter_namespace(monkeypatch):
    values={'_get_taiko_db_connection':lambda:pytest.fail('Adapter reopened SQL'),
        '_build_bind_auto_update_result':lambda *args:None,'_record_bind_qq_action':lambda **kwargs:None,
        '_format_bind_entry_summary_safe':lambda entry:'summary','BIND_VERIFY_SESSIONS':{}}
    module=types.ModuleType('actual_native_qq_adapter')
    namespace({'_migrate_bind_from_legacy_qq_detail','_migrate_bind_from_legacy_qq'},values,module.__dict__)
    tree=ast.parse((Path(__file__).parent/'test_u0_bind_slots.py').read_text())
    nodes=[node for node in tree.body if getattr(node,'name','') in {'test_migrate_bind_from_legacy_qq_records_success_action','test_migrate_bind_from_legacy_qq_records_not_found_action'}]
    tests={'_load_taiko_module':lambda:module}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-QQ-tests>','exec'),tests)
    for name in [n.name for n in nodes]:tests[name](monkeypatch)


def test_legacy_input_forms_still_parse_and_new_code_is_optional():
    tree=ast.parse((SOURCE/'lifecycle_host.py').read_text()+'\n'+(SOURCE/'identity_cluster.py').read_text());statement=next(node for node in tree.body if isinstance(node,ast.Assign) and any(getattr(t,'id','')=='BIND_QQ_INPUT_REGEX' for t in node.targets))
    ns=namespace({'_extract_bind_qq_input'},{'re':re,'BIND_QQ_INPUT_REGEX':ast.literal_eval(statement.value)})
    for text in ['绑定QQ 12345','绑定qq你的qq号12345','/绑定 qq 12345','绑定QQ 12345 '+ 'a'*32]:
        assert ns['_extract_bind_qq_input'](text)=='12345'


def test_retained_usage_and_actual_markdown_show_verified_private_migration():
    module=types.ModuleType('actual_native_qq_usage')
    namespace({'_taiko_bind_usage_message','_taiko_bind_usage_markdown_message'},{'is_qq_official_event':lambda event:True},module.__dict__)
    tree=ast.parse((Path(__file__).parent/'test_bind_usage_message.py').read_text())
    nodes=[node for node in tree.body if getattr(node,'name','') in {'_FakeQQOfficialEvent','test_bind_usage_message_explains_private_verified_qq_migration'}]
    ns={'_load_taiko_module':lambda:module}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<retained-QQ-usage>','exec'),ns)
    ns['test_bind_usage_message_explains_private_verified_qq_migration']()
    text=module._taiko_bind_usage_markdown_message(object())
    assert '迁移验证码' in text and '绑定QQ QQ号 验证码' in text and '旧绑定迁移' in text
    assert '冒绑' not in text
