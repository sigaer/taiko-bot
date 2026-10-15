"""Explicit native metadata scope, frozen DTO parity and actual command body."""
import ast
from pathlib import Path
import subprocess

import pytest

from taiko_bot.runtime.player.center.bot_binding_metadata import read_bot_binding_metadata, BotBindingMetadataUnavailable
from taiko_bot.runtime.player.center.messages import parse_identity_key

PRINCIPAL = 'qq_official:_Abc-_'
ROWS = [(PRINCIPAL,'111',1,0,'wahlap',1), (PRINCIPAL,'222',2,1,'hiroba',1),
        ('onebot_v11:123','333',1,1,'manual',0)]


class Cursor:
    def __init__(self, rows): self.rows,self.queries = rows,[]
    def execute(self, query, args=()): self.queries.append((query,args))
    def fetchall(self): return self.rows
    def close(self): pass


class Connection:
    def __init__(self, rows): self.reader,self.committed,self.rolled_back,self.closed = Cursor(rows),False,False,False
    def cursor(self): return self.reader
    def commit(self): self.committed=True
    def rollback(self): self.rolled_back=True
    def close(self): self.closed=True


def commands(text, names, namespace):
    nodes = [ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]
    nodes += [node for node in ast.parse(text).body if isinstance(node,ast.FunctionDef) and node.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])), '<native-metadata-command>', 'exec'), namespace)
    return namespace


def test_scoped_dto_matches_git_frozen_healthy_current_virtual_and_source_selection():
    source = Path(__file__).resolve().parents[1]
    frozen = (Path(__file__).parent / 'fixtures/binding_metadata_legacy.py').read_text()
    old_db=Connection(ROWS)
    old=commands(frozen,{'_load_multi_bind_store','_normalize_identity_key'},{'parse_identity_key':parse_identity_key,'_get_taiko_db_connection':lambda:old_db})
    expected=old['_load_multi_bind_store']()
    db=Connection(ROWS[:2])
    assert read_bot_binding_metadata([PRINCIPAL],connection_factory=lambda:db) == {PRINCIPAL:expected[PRINCIPAL]}
    sql,args=db.reader.queries[0]
    assert 'WHERE b.qq IN' in sql and 'CAST(b.qq AS BINARY) IN' in sql and 'LIMIT 129' in sql
    assert args == (PRINCIPAL,PRINCIPAL) and db.committed and db.closed


def test_native_command_body_requests_only_the_selected_principal():
    path=(Path(__import__('taiko_bot').__file__).parent/'runtime/player/center/lifecycle_host.py')
    db=Connection(ROWS[:2])
    current=commands(path.read_text(),{'_load_multi_bind_store','_get_current_bind_entry','_ensure_multi_bind_entry','_normalize_multi_bind_ids','_normalize_identity_key'},
                     {'__package__':'taiko_bot.runtime.player.center','parse_identity_key':parse_identity_key,'_get_taiko_db_connection':lambda:db,
                      '_get_taiko_bind_info':lambda principal:{'id':'222','visible':0}})
    assert current['_get_current_bind_entry'](PRINCIPAL)['current_slot'] == 0
    assert db.reader.queries[0][1] == (PRINCIPAL,PRINCIPAL)
    tree=ast.parse(path.read_text())
    assert not any(isinstance(node,ast.FunctionDef) and node.name=='_save_multi_bind_store' for node in tree.body)
    assert all(node.args for node in ast.walk(tree) if isinstance(node,ast.Call) and getattr(node.func,'id','')=='_load_multi_bind_store')


@pytest.mark.parametrize('rows', [[], ROWS[:2]])
def test_native_selection_never_reconstructs_a_removed_or_outdated_bind_info(rows):
    path=(Path(__import__('taiko_bot').__file__).parent/'runtime/player/center/lifecycle_host.py')
    db=Connection(rows)
    current=commands(path.read_text(),{'_load_multi_bind_store','_get_current_bind_entry','_ensure_multi_bind_entry','_normalize_multi_bind_ids','_normalize_identity_key'},
                     {'__package__':'taiko_bot.runtime.player.center','parse_identity_key':parse_identity_key,'_get_taiko_db_connection':lambda:db,
                      '_get_taiko_bind_info':lambda principal:pytest.fail('Selection consulted separate old binding info')})
    result=current['_get_current_bind_entry'](PRINCIPAL)
    if rows:
        assert result['current_index']==1 and result['current_slot']==0
    else:
        assert result is None


@pytest.mark.parametrize('keys',[None,[],['x'],[1],[' onebot_v11:123'],['onebot_v11:../../x'],['qq_official:a:b'],[PRINCIPAL]*4])
def test_bad_or_unbounded_principal_scope_is_rejected_before_sql(keys):
    with pytest.raises(BotBindingMetadataUnavailable):
        read_bot_binding_metadata(keys,connection_factory=lambda:pytest.fail('Invalid scope reached SQL'))


@pytest.mark.parametrize('rows', [
    [(PRINCIPAL.lower(),'111',1,1,'wahlap',0)],
    [(PRINCIPAL,'../other',1,1,'wahlap',0)],
    [(PRINCIPAL,'111',0,1,'wahlap',0)],
    [(PRINCIPAL,'111',1,1,'unknown',0)],
    [(PRINCIPAL,'111',1,1,'wahlap',3)],
    [(PRINCIPAL,'111',1,1,'wahlap',0),(PRINCIPAL,'222',2,1,'hiroba',0)],
    [ROWS[0]]*129,
])
def test_malformed_foreign_or_overcapacity_rows_cannot_be_a_selection_dto(rows):
    db=Connection(rows)
    with pytest.raises(BotBindingMetadataUnavailable):
        read_bot_binding_metadata([PRINCIPAL],connection_factory=lambda:db)
    assert not db.committed and db.rolled_back and db.closed


def test_raw_qq_alias_is_explicit_and_not_inferred_by_an_ordinary_read():
    db=Connection([('123','111',1,1,'wahlap',0)])
    assert read_bot_binding_metadata(['123'],connection_factory=lambda:db)['onebot_v11:123']['ids'] == ['111']
    db=Connection([])
    assert read_bot_binding_metadata(['onebot_v11:123'],connection_factory=lambda:db) == {}
    assert db.reader.queries[0][1] == ('onebot_v11:123','onebot_v11:123')


def test_database_failure_is_fixed_safe_and_closes_connection():
    db=Connection([])
    db.reader.execute=lambda *args:(_ for _ in ()).throw(RuntimeError('/private/password'))
    with pytest.raises(BotBindingMetadataUnavailable) as error:
        read_bot_binding_metadata([PRINCIPAL],connection_factory=lambda:db)
    assert 'password' not in str(error.value) and db.rolled_back and db.closed
