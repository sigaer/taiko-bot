"""MySQL boundary adapter over a synthetic on-disk SQLite test database.
Actual INSERT/SELECT/transactions execute; only dialect/DDL translation is adapted.
"""
import sqlite3, json, re, os
from pathlib import Path

class Database:
 def __init__(self,path):
  self.path=Path(path);self.statements=[];self.commits=0;self.rollbacks=0;self.fail_audit=False
  os.environ['TAIKO_ALLOW_TEST_DB_MUTATION']='1'
 def connect(self):return Connection(self)
 def reset(self):
  self.path.unlink(missing_ok=True);self.statements.clear();self.commits=self.rollbacks=0;self.fail_audit=False
 def rows(self,table):
  with sqlite3.connect(self.path) as conn:
   try:return conn.execute('select * from '+table+' order by id').fetchall()
   except sqlite3.OperationalError:return []
class Connection:
 def __init__(self,owner):
  self.owner=owner;self.db=sqlite3.connect(owner.path);self.db.create_function('NOW',0,lambda:'2026-10-15 12:00:00')
  cursor=self.cursor();cursor.execute('SELECT DATABASE()')
  assert cursor.fetchone()[0].endswith('_test') and os.environ.get('TAIKO_ALLOW_TEST_DB_MUTATION')=='1'
 def cursor(self):return Cursor(self)
 def begin(self):self.db.execute('BEGIN')
 def commit(self):self.db.commit();self.owner.commits+=1
 def rollback(self):self.db.rollback();self.owner.rollbacks+=1
 def close(self):self.db.close()
class Cursor:
 def __init__(self,conn):self.conn=conn;self.raw=conn.db.cursor();self.result=None
 def execute(self,sql,params=()):
  self.conn.owner.statements.append((' '.join(sql.split()),tuple(params)))
  clean=' '.join(sql.split());self.result=None
  if clean=='SELECT DATABASE()':self.result=[('taiko_ownership_test',)];return
  if clean.startswith('SHOW COLUMNS'):self.result=[('achievement_type',)];return
  if clean.startswith('CREATE TABLE IF NOT EXISTS taiko_custom_titles'):
   sql='''CREATE TABLE IF NOT EXISTS taiko_custom_titles(id INTEGER PRIMARY KEY AUTOINCREMENT,title_name TEXT,title_key TEXT UNIQUE,song_id INTEGER,difficulty_level INTEGER,achievement_type TEXT DEFAULT 'full_combo',creator_type TEXT,creator_id TEXT,creator_name TEXT,source TEXT,group_id TEXT,group_name TEXT,created_at TEXT DEFAULT '2026-10-15 12:00:00',updated_at TEXT DEFAULT '2026-10-15 12:00:00')'''
  elif clean.startswith('CREATE TABLE IF NOT EXISTS web_admin_action_logs'):
   sql='''CREATE TABLE IF NOT EXISTS web_admin_action_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_type TEXT,actor_id TEXT,actor_name TEXT,source TEXT,target_type TEXT,target_key TEXT,action TEXT,before_json TEXT,after_json TEXT,extra_json TEXT,created_at TEXT DEFAULT '2026-10-15 12:00:00')'''
  if 'INSERT INTO web_admin_action_logs' in sql and self.conn.owner.fail_audit:raise RuntimeError('synthetic audit insert failure')
  sql=sql.replace('%s','?').replace(' FOR UPDATE','').replace('TIMESTAMPDIFF(SECOND, created_at, NOW())',"CAST((julianday(NOW())-julianday(created_at))*86400 AS INTEGER)")
  self.raw.execute(sql,params)
 @property
 def lastrowid(self):return self.raw.lastrowid
 def fetchone(self):return self.result.pop(0) if self.result else self.raw.fetchone()
 def fetchall(self):return self.result if self.result is not None else self.raw.fetchall()
 def close(self):self.raw.close()
