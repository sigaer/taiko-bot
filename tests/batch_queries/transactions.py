"""Real writes and rollback parity for legacy vs owned title transactions."""
assert a.host=='center'
transaction_results=[]
for scenario in ('create','duplicate','cooldown','cooldown-expired','audit-failure','invalid-title','invalid-level','invalid-achievement'):
 outcomes=[]
 for owner in (legacy_custom,custom_title):
  db.reset();owner._schema_ready=False
  args=dict(title_name='合成事务称号',song_id=10000,difficulty_level=4,achievement_type='full_combo',song_title='Fixture 00',creator_type='bot-user',creator_id='fixture-actor',creator_name='合成玩家',group_id='fixture-group',group_name='合成群')
  if scenario in ('duplicate','cooldown','cooldown-expired'):
   owner.create_custom_title(**args)
   if scenario=='duplicate':args['creator_id']='second-actor'
   else:args['title_name']='合成第二称号'
   if scenario=='cooldown-expired':
    with __import__('sqlite3').connect(db.path) as conn:conn.execute("UPDATE web_admin_action_logs SET created_at='2026-10-15 11:59:29'")
  if scenario=='audit-failure':db.fail_audit=True
  if scenario=='invalid-title':args['title_name']=''
  if scenario=='invalid-level':args['difficulty_level']=8
  if scenario=='invalid-achievement':args['achievement_type']='invalid'
  try:record=owner.create_custom_title(**args);result={'title':record.title_name,'id':record.id}
  except Exception as error:result={'error':type(error).__name__,'message':str(error)}
  outcomes.append(dict(result=result,titles=db.rows('taiko_custom_titles'),audit=db.rows('web_admin_action_logs'),rollbacks=db.rollbacks,sql=db.statements))
 assert outcomes[0]==outcomes[1],(scenario,outcomes)
 outcome=outcomes[1]
 if scenario=='create':assert len(outcome['titles'])==len(outcome['audit'])==1 and not outcome['rollbacks']
 if scenario=='audit-failure':assert not outcome['titles'] and not outcome['audit'] and outcome['rollbacks']==1
 if scenario in ('duplicate','cooldown'):assert len(outcome['titles'])==1 and outcome['rollbacks']==1 and 'error' in outcome['result']
 if scenario=='cooldown-expired':assert len(outcome['titles'])==2 and len(outcome['audit'])==2 and 'error' not in outcome['result']
 transaction_results.append(dict(scenario=scenario,result=outcome['result'],titles=len(outcome['titles']),audit=len(outcome['audit']),rollbacks=outcome['rollbacks'],sql_sha256=hashlib.sha256(json.dumps(outcome['sql']).encode()).hexdigest()))
 print(scenario,'transaction parity PASS',flush=True)
(a.work/'transactions.json').write_text(json.dumps(transaction_results,ensure_ascii=False,indent=2))
