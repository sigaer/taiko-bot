"""Native adapter scope and frozen deletion input behavior, without Bot boot."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import importlib.util

import pytest

from taiko_bot.runtime.player.center.bot_binding_mutation import (
    BotBindingMutationRejected, BotBindingMutationUnavailable,
    BotBindingMutationResult, mutate_bot_binding, principal_lock_name,
    resolve_remove_target,
)
from taiko_runtime.platform_adapter import parse_identity_key

SOURCE = Path(__file__).resolve().parents[2]/'taiko_bot/runtime/player/center'
PRINCIPAL = 'qq_official:_Abc-_'


def function_namespace(text, names, **values):
    nodes = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
    nodes += [node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name in names]
    values['__package__'] = 'taiko_bot.runtime.player.center'
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<native-binding>', 'exec'), values)
    return values


@pytest.mark.parametrize('principal', ['onebot_v11:123', PRINCIPAL])
def test_gate_hash_is_exact_json_string_used_by_node(principal):
    expected = hashlib.sha256(json.dumps(principal, separators=(',', ':')).encode()).hexdigest()[:52]
    assert principal_lock_name(principal) == 'taiko-bind-'+expected


@pytest.mark.parametrize('principal,action,value,source', [
    ('123','visibility',1,None), (' '+PRINCIPAL,'switch',0,None),
    (PRINCIPAL,'unknown',None,None), (PRINCIPAL,'switch',True,None),
    (PRINCIPAL,'switch',-1,None), (PRINCIPAL,'visibility',3,None),
    (PRINCIPAL,'upsert','../other','wahlap'), (PRINCIPAL,'upsert','111','manual'),
    (PRINCIPAL,'upsert','981234567890123456','wahlap'), (PRINCIPAL,'remove','a'*129,None),
])
def test_invalid_scope_and_intent_never_open_sql(principal, action, value, source):
    with pytest.raises((BotBindingMutationRejected, BotBindingMutationUnavailable)):
        mutate_bot_binding(principal, action, value=value, source=source,
                           connection_factory=lambda: pytest.fail('Invalid native intent opened SQL'))


@pytest.mark.parametrize('target', ['', 'u1', 'U2', 'u5', '111', '222', '333', 'word', '0', 'u0'])
def test_remove_target_matches_frozen_command_oracle(target):
    frozen = (Path(__file__).parent/'fixtures/remove_target.py').read_text()
    old = function_namespace(frozen, {'_resolve_bind_remove_target'}, re=__import__('re'))['_resolve_bind_remove_target']
    entry = {'ids':['111','222'], 'current_index':1}
    def result(fn):
        try: return ('ok', fn(entry, target))
        except ValueError as error: return ('error', str(error))
    assert result(resolve_remove_target) == result(old)


def test_actual_native_wrappers_use_one_transaction_outcome_and_canonical_sender(monkeypatch):
    import taiko_bot.runtime.player.center.bot_binding_mutation as module
    entry = {'ids':['111','222'],'current_index':1,'current_slot':2,'sources':{'111':'wahlap','222':'hiroba'}}
    calls = []
    def mutation(principal, action, **kwargs):
        calls.append((principal, action, kwargs))
        return BotBindingMutationResult(entry, '222', False, True, 2)
    monkeypatch.setattr(module, 'mutate_bot_binding', mutation)
    factory = object()
    ns = function_namespace((SOURCE/'lifecycle_host.py').read_text(),
        {'_normalize_identity_key','_upsert_bind_record','_switch_bind_record','_remove_bind_record','_set_taiko_bind_visibility','_format_bind_entry_summary_safe'},
        parse_identity_key=parse_identity_key, _get_taiko_db_connection=factory,
        _format_multi_bind_summary=lambda got: 'summary' if got is entry else pytest.fail('Lost transaction DTO'),
        _load_multi_bind_store=lambda *args: pytest.fail('Mutation reread through a second connection'),
        BIND_DELETE_CONFIRM_SESSIONS={PRINCIPAL: {'taiko_id':'222'}})
    assert ns['_upsert_bind_record'](PRINCIPAL, '222', source='hiroba') == ('新增绑定成功！已设为 u2。\n当前绑定：summary', False)
    assert ns['_switch_bind_record'](PRINCIPAL, 2) == (True, '已切换到 u2：222\n当前绑定：summary')
    assert ns['_remove_bind_record'](PRINCIPAL, 'u2') == (True, '已删除绑定：222\n当前绑定：summary', False)
    assert ns['_set_taiko_bind_visibility'](PRINCIPAL, 1) == 2
    assert all(principal==PRINCIPAL and kwargs['connection_factory'] is factory for principal, action, kwargs in calls)
    assert [action for _,action,_ in calls] == ['upsert','switch','remove','visibility']
    assert not ns['BIND_DELETE_CONFIRM_SESSIONS']


def test_visibility_failure_is_not_reported_as_missing_binding(monkeypatch):
    import taiko_bot.runtime.player.center.bot_binding_mutation as module
    monkeypatch.setattr(module, 'mutate_bot_binding', lambda *args, **kwargs: (_ for _ in ()).throw(BotBindingMutationUnavailable()))
    ns = function_namespace((SOURCE/'lifecycle_host.py').read_text(), {'_normalize_identity_key','_set_taiko_bind_visibility'},
        parse_identity_key=parse_identity_key, _get_taiko_db_connection=object())
    with pytest.raises(BotBindingMutationUnavailable):
        ns['_set_taiko_bind_visibility'](PRINCIPAL, 0)


def test_retained_u0_command_regressions_run_actual_adapters_without_bot_registration(monkeypatch):
    spec=importlib.util.spec_from_file_location('owned_legacy_u0_tests', Path(__file__).parent/'test_u0_bind_slots.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    names={'_normalize_identity_key','_switch_bind_record','_remove_bind_record',
           '_format_multi_bind_summary','_get_bind_ids','_get_selected_bind_slot_number',
           '_has_virtual_bind_slot','_infer_bind_source','_bind_source_label','_format_bind_entry_summary_safe'}
    ns=function_namespace((SOURCE/'lifecycle_host.py').read_text(), names,
        parse_identity_key=parse_identity_key,_get_taiko_db_connection=object(),BIND_DELETE_CONFIRM_SESSIONS={})
    monkeypatch.setattr(legacy,'_load_taiko_module',lambda:SimpleNamespace(**ns))
    legacy.test_switch_bind_record_supports_u0_and_real_slots(monkeypatch)
    legacy.test_remove_bind_record_disables_u0_after_falling_back_to_single_bind(monkeypatch)
    legacy.test_manual_binding_also_enables_virtual_slot()


def test_last_confirmation_captures_the_locked_target_without_a_second_metadata_read(monkeypatch):
    import taiko_bot.runtime.player.center.bot_binding_mutation as module
    monkeypatch.setattr(module, 'mutate_bot_binding', lambda *args, **kwargs: (_ for _ in ()).throw(BotBindingMutationRejected('confirm','111')))
    ns=function_namespace((SOURCE/'lifecycle_host.py').read_text(), {'_normalize_identity_key','_remove_bind_record'},
        parse_identity_key=parse_identity_key,_get_taiko_db_connection=object(),BIND_DELETE_CONFIRM_SESSIONS={},
        BIND_DELETE_CONFIRM_TIMEOUT_SECONDS=300,_now_ts=lambda:1000)
    result=ns['_remove_bind_record'](PRINCIPAL)
    assert result[2] is True
    assert ns['BIND_DELETE_CONFIRM_SESSIONS'] == {PRINCIPAL:{'taiko_id':'111','expires_at':1300}}


@pytest.mark.parametrize('target',['','u1'])
def test_last_confirmation_requires_the_captured_numeric_identity(target):
    with pytest.raises(BotBindingMutationRejected):
        mutate_bot_binding(PRINCIPAL,'remove',value=target,force_last=True,
                           connection_factory=lambda:pytest.fail('Invalid confirmation opened SQL'))


def test_committed_action_still_succeeds_when_manual_nickname_formatting_fails(monkeypatch):
    import taiko_bot.runtime.player.center.bot_binding_mutation as module
    entry={'ids':['111'],'current_index':0,'current_slot':1,'sources':{'111':'wahlap'}}
    monkeypatch.setattr(module,'mutate_bot_binding',lambda *args, **kwargs:BotBindingMutationResult(entry,'111',True,True))
    warnings=[]
    ns=function_namespace((SOURCE/'lifecycle_host.py').read_text(),
        {'_normalize_identity_key','_upsert_bind_record','_format_bind_entry_summary_safe'},
        parse_identity_key=parse_identity_key,_get_taiko_db_connection=object(),logger=SimpleNamespace(warning=warnings.append),
        _format_multi_bind_summary=lambda entry:(_ for _ in ()).throw(RuntimeError('private SQL nickname diagnostic')))
    message,first=ns['_upsert_bind_record'](PRINCIPAL,'111',source='wahlap')
    assert first and message.startswith('绑定成功！') and '绑定摘要暂时不可用' in message
    assert warnings and all('private' not in value for value in warnings)
