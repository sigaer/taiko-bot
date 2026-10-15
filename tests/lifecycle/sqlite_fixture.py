"""Disk-backed synthetic SQL boundary; MySQL named locks are only modeled here."""
import json
import os
import re
import sqlite3
from pathlib import Path

SCHEMA = '''
CREATE TABLE bind (row_id INTEGER PRIMARY KEY AUTOINCREMENT, qq TEXT, id TEXT, slot_index INTEGER DEFAULT 1, is_current INTEGER DEFAULT 1, source TEXT DEFAULT 'wahlap', visible INTEGER DEFAULT 1, UNIQUE(qq,slot_index), UNIQUE(qq,id));
CREATE TABLE taiko_bind_identity_state(identity_key TEXT PRIMARY KEY,current_virtual INTEGER DEFAULT 0);
CREATE TABLE taiko_manual_accounts(taiko_id TEXT PRIMARY KEY,nickname TEXT,bot_identity_key TEXT);
CREATE TABLE web_hiroba_credentials(taiko_no TEXT PRIMARY KEY,configured_by_qq TEXT,email TEXT,password_encrypted TEXT,password_enc TEXT,updated_at TEXT);
CREATE TABLE public_score_tokens(id INTEGER PRIMARY KEY AUTOINCREMENT,taiko_id TEXT UNIQUE,token_hash TEXT UNIQUE,token_mask TEXT,last_used_at TEXT,created_at TEXT DEFAULT '2026-10-15 00:00:00',updated_at TEXT DEFAULT '2026-10-15 00:00:00');
CREATE TABLE taiko_qq_migration_codes(source_principal TEXT PRIMARY KEY,code_hash TEXT,source_hash TEXT,issued_at TEXT,expires_at TEXT,target_principal TEXT,consumed_at TEXT,effect_json TEXT,effect_hash TEXT);
CREATE TABLE web_song_locks(taiko_id TEXT,song_no INTEGER,level INTEGER,is_locked INTEGER);
CREATE TABLE manual_requests(request_id TEXT PRIMARY KEY,actor TEXT,taiko_id TEXT);
CREATE TABLE scores(taiko_id TEXT,song_no INTEGER,level INTEGER,payload TEXT,PRIMARY KEY(taiko_id,song_no,level));
CREATE TABLE claim_codes(code TEXT PRIMARY KEY,taiko_id TEXT,consumed INTEGER DEFAULT 0,expires REAL);
'''

class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.statements = []; self.rollbacks = 0; self.commits = 0; self.fail = None
        self.reset()

    def reset(self):
        self.path.unlink(missing_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)
        self.statements.clear(); self.rollbacks = 0; self.commits = 0

    def connect(self):
        connection = Connection(self)
        cursor = connection.cursor(); cursor.execute('SELECT DATABASE()')
        assert cursor.fetchone()[0].endswith('_test')
        assert os.environ.get('TAIKO_ALLOW_TEST_DB_MUTATION') == '1'
        return connection

    def rows(self, table):
        assert table in ('bind','taiko_bind_identity_state','taiko_manual_accounts','scores','claim_codes','public_score_tokens','taiko_qq_migration_codes')
        with sqlite3.connect(self.path) as conn:
            return conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()

    def seed(self, principal, identities=('11111','22222'), sources=None, virtual=False):
        with sqlite3.connect(self.path) as conn:
            conn.execute('DELETE FROM bind WHERE qq=?',(principal,))
            for i, identity in enumerate(identities):
                source = (sources or {}).get(identity, 'manual' if identity.startswith('98') else 'wahlap')
                conn.execute('INSERT INTO bind(qq,id,slot_index,is_current,source,visible) VALUES(?,?,?,?,?,1)',(principal,identity,i+1,int(i==0),source))
                if source=='manual':conn.execute('INSERT OR REPLACE INTO taiko_manual_accounts VALUES(?,?,?)',(identity,'合成鼓手',principal))
            conn.execute('INSERT OR REPLACE INTO taiko_bind_identity_state VALUES(?,?)',(principal,int(virtual)))

class Connection:
    def __init__(self, db):
        self.db=db; self.raw=sqlite3.connect(db.path,timeout=3,check_same_thread=False)
    def cursor(self): return Cursor(self)
    def begin(self): self.raw.execute('BEGIN')
    def commit(self): self.raw.commit(); self.db.commits+=1
    def rollback(self): self.raw.rollback(); self.db.rollbacks+=1
    def close(self): self.raw.close()

class Cursor:
    def __init__(self, connection):
        self.conn=connection; self.raw=connection.raw.cursor(); self.result=None; self.rowcount=0
    def execute(self, sql, params=()):
        self.result=None
        sql=' '.join(sql.split()); self.conn.db.statements.append((sql,tuple(params)))
        if self.conn.db.fail and self.conn.db.fail in sql:raise RuntimeError('synthetic SQL failure')
        if sql=='SELECT DATABASE()':self.result=[('taiko_lifecycle_test',)];return
        if sql.startswith(('SELECT GET_LOCK','SELECT RELEASE_LOCK')):self.result=[(1,)];return
        if sql.startswith('CREATE TABLE IF NOT EXISTS public_score_tokens'):return
        sql=sql.replace(' FOR UPDATE','').replace('%s','?')
        sql=re.sub(r'CAST\(([^()]+) AS BINARY\)',r'CAST(\1 AS TEXT)',sql,flags=re.I)
        sql=sql.replace('UTC_TIMESTAMP()-INTERVAL 60 SECOND',"datetime('2026-10-15 00:00:00','-60 seconds')")
        sql=sql.replace('UTC_TIMESTAMP()+INTERVAL 10 MINUTE',"datetime('2026-10-15 00:00:00','+10 minutes')")
        sql=sql.replace('UTC_TIMESTAMP()',"'2026-10-15 00:00:00'")
        if 'ON DUPLICATE KEY UPDATE' in sql:
            table=re.search(r'INSERT INTO (\w+)',sql,re.I)[1]
            key={'taiko_bind_identity_state':'identity_key','web_hiroba_credentials':'taiko_no','public_score_tokens':'taiko_id','taiko_qq_migration_codes':'source_principal'}[table]
            sql=sql.replace('ON DUPLICATE KEY UPDATE',f'ON CONFLICT({key}) DO UPDATE SET')
            sql=re.sub(r'VALUES\((\w+)\)',r'excluded.\1',sql)
        self.raw.execute(sql,tuple(params));self.rowcount=self.raw.rowcount
    def fetchone(self):
        if self.result is not None:return self.result.pop(0) if self.result else None
        return self.raw.fetchone()
    def fetchall(self):
        if self.result is not None:result=self.result;self.result=[];return result
        return self.raw.fetchall()
    def close(self): self.raw.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
