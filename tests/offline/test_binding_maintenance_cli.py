"""Historical schema migration: recording SQL only; no database or real secrets."""
import json
import sys
import pytest
from taiko_bot.cli import migrate_multi_bind_to_db as cli

@pytest.mark.parametrize('apply,failure',[(False,False),(True,False),(True,True)])
def test_main_sql_transaction_backup_and_rollback(tmp_path,monkeypatch,apply,failure,capsys):
    legacy=tmp_path/'legacy.json';legacy.write_text(json.dumps({'onebot_v11:7':{'ids':['111','222'],'current_index':1,'current_slot':0}}))
    monkeypatch.setattr(cli,'LEGACY_PATH',legacy);monkeypatch.setattr(cli,'BACKUP_ROOT',tmp_path/'backups')
    calls=[]
    class DB:
        def cursor(self):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,params=None):
            calls.append(('sql',' '.join(sql.split()),params))
            if failure and sql.startswith('DELETE FROM bind'):raise RuntimeError('synthetic SQL failure')
        def fetchall(self):return []
        def commit(self):calls.append(('commit',))
        def rollback(self):calls.append(('rollback',))
        def close(self):calls.append(('close',))
    monkeypatch.setattr(cli,'connect',DB);monkeypatch.setattr(sys,'argv',['migration']+(['--apply'] if apply else []))
    if failure:
        with pytest.raises(RuntimeError,match='synthetic SQL failure'):cli.main()
        assert calls[-2:]==[('rollback',),('close',)]
    else:
        assert cli.main()==0
        assert calls[-2:]==[('commit' if apply else 'rollback',),('close',)]
    summary=json.loads(capsys.readouterr().out.splitlines()[0])
    assert summary=={'mode':'apply' if apply else 'dry-run','identities':1,'slots':2,'multiIdentities':1,'currentVirtual':1}
    assert calls[0][1].startswith('CREATE TABLE IF NOT EXISTS taiko_bind_identity_state')
    if apply:
        backup=next((tmp_path/'backups').iterdir())
        assert (backup/'legacy.json').read_bytes()==legacy.read_bytes()
        assert json.loads((backup/'migration_plan.json').read_text())['onebot_v11:7']['ids']==['111','222']
    if apply and not failure:
        inserts=[row[2] for row in calls if row[0]=='sql' and row[1].startswith('INSERT INTO bind ')]
        assert inserts==[('onebot_v11:7','111',0,1,0,'wahlap'),('onebot_v11:7','222',0,2,1,'wahlap')]
