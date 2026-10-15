"""Real event delivery around complete binding changes, destructive confirmations and retries."""
from taiko_bot.runtime.player import lifecycle_authority as authority
cases=[]
async def run(name,command,platform='onebot',private=False):
 out=await dispatch(current_matcher(name),command,platform,target=False,private=private)
 assert not out[1],(name,out)
 return out

def change(principal,kind):
 with sqlite3.connect(db.path) as conn:
  if kind=='visible':conn.execute('UPDATE bind SET visible=0 WHERE qq=?',(principal,))
  elif kind=='profile':
   conn.execute('UPDATE bind SET is_current=0 WHERE qq=?',(principal,));conn.execute('UPDATE bind SET is_current=1 WHERE qq=? AND slot_index=2',(principal,))
  elif kind=='members':conn.execute('UPDATE bind SET id=\'33333\' WHERE qq=? AND slot_index=2',(principal,))
  elif kind=='u0':conn.execute('UPDATE taiko_bind_identity_state SET current_virtual=1 WHERE identity_key=?',(principal,))
  elif kind=='unbound':conn.execute('DELETE FROM bind WHERE qq=?',(principal,))
  elif kind=='source':conn.execute('UPDATE bind SET source=\'hiroba\' WHERE qq=? AND slot_index=2',(principal,))
  elif kind=='order':
   conn.execute('UPDATE bind SET slot_index=slot_index+10 WHERE qq=?',(principal,))
   conn.execute('UPDATE bind SET slot_index=CASE slot_index WHEN 11 THEN 2 ELSE 1 END WHERE qq=?',(principal,))

async def security():
 for platform,principal in zip(['onebot','qq'],principals):
  for name,command,confirm_name,confirm in [
   ('manual_delete','永久删除空白账号','manual_delete_confirm','确认永久删除空白账号'),
   ('manual_score_delete','删除成绩 10000 表','manual_score_delete_confirm','确认删除成绩')]:
   for kind in ['visible','profile','members','u0','source','order','unbound']:
    reset(manual_account=True)
    out=await run(name,command,platform);assert '即将' in str(out),out
    change(principal,kind);before=len(api_calls)
    out=await run(confirm_name,confirm,platform)
    assert '绑定状态已变化' in str(out) and len(api_calls)==before,(name,kind,out,api_calls)
    cases.append({'command':name,'case':kind,'platform':platform})
   reset(manual_account=True);await run(name,command,platform)
   sessions=host.MANUAL_DELETE_CONFIRM_SESSIONS if name=='manual_delete' else host.MANUAL_SCORE_DELETE_CONFIRM_SESSIONS
   sessions[principal]['expires_at']=time.time()-1
   before=len(api_calls);out=await run(confirm_name,confirm,platform)
   assert '确认已过期' in str(out) and len(api_calls)==before,out
   cases.append({'command':name,'case':'expired','platform':platform})
   reset(manual_account=True);await run(name,command,platform)
   out=await run(confirm_name,confirm,platform);assert '已永久删除' in str(out) or '手动成绩已删除' in str(out),out
   before=len(api_calls);out=await run(confirm_name,confirm,platform)
   assert '没有待确认' in str(out) and len(api_calls)==before,out
   cases.append({'command':name,'case':'success-repeat','platform':platform})
  # Implicit u0 is never passed as a real manual identity; an explicit real uN remains valid.
  reset(manual_account=True,virtual=True)
  out=await run('manual_score_get','查看成绩 10000 表',platform)
  assert '真实的手动账号槽位' in str(out) and not api_calls,out
  out=await run('manual_claim_code','生成认领码 u1',platform)
  assert 'SYNTHETIC-CODE' in str(out),out
  cases.append({'case':'u0-explicit-real-slot','platform':platform})
  # Existing endpoint supports requestId: duplicate adapter events reuse the creation receipt.
  reset();first=await run('manual_create','新增空白账号 合成昵称',platform);count=len(db.rows('taiko_manual_accounts'))
  second=await run('manual_create','新增空白账号 合成昵称',platform)
  assert '已新增' in str(first) and '已新增' in str(second) and len(db.rows('taiko_manual_accounts'))==count
  assert api_calls[-1]['requestId']==api_calls[-2]['requestId']
  cases.append({'case':'create-duplicate-event','platform':platform})
  reset(manual_account=True);before=effects();server['fail']=True
  out=await run('manual_rename','空白账号改名 不应保存',platform)
  assert '已回滚' in str(out) and effects()==before,out
  cases.append({'case':'http-transaction-failure','platform':platform})
  for point in ['after-api','send-failure']:
   reset(manual_account=True)
   original=HTTP.post;active=bot if platform=='onebot' else qq;original_send=active.send
   if point=='after-api':
    async def post(self,*args,**kwargs):
     response=await original(self,*args,**kwargs);change(principal,'visible');return response
    HTTP.post=post
   else:
    async def failed(self,event,message,**kwargs):
     if 'SYNTHETIC-CODE' in str(message):change(principal,'visible');raise RuntimeError('synthetic send failure')
     return await original_send(event,message,**kwargs)
    active.send=types.MethodType(failed,active)
   try:
    out=await run('manual_claim_code','生成认领码',platform)
    assert '绑定状态已变化' in str(out) and 'SYNTHETIC-CODE' not in str(out),out
    cases.append({'case':point,'platform':platform})
   finally:HTTP.post=original;active.send=original_send
  # A claim transfers the real account through the same API; old owner loses it.
  reset(manual_account=True)
  out=await run('manual_claim_code','生成认领码',platform)
  assert 'SYNTHETIC-CODE' in str(out)
  other='qq' if platform=='onebot' else 'onebot'
  out=await run('manual_claim','认领空白账号 SYNTHETIC-CODE',other)
  assert '已认领' in str(out),out
  claimed=api_calls[-1]
  before=effects();out=await run('manual_claim','认领空白账号 SYNTHETIC-CODE',other)
  assert effects()==before and '认领失败' in str(out),out
  cases.append({'case':'claim-success-and-replay','platform':platform})
  # One actor cannot consume another actor's destructive confirmation.
  reset(manual_account=True);await run('manual_delete','永久删除空白账号',platform)
  other='qq' if platform=='onebot' else 'onebot';before=len(api_calls)
  out=await run('manual_delete_confirm','确认永久删除空白账号',other)
  assert '没有待确认' in str(out) and len(api_calls)==before,out
  cases.append({'case':'foreign-confirmation','platform':platform})
 assert not authority._locks,authority._locks
 assert not violations,violations
 (a.work/'security.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
 print(a.host,len(cases),'manual security/retry/rollback PASS',flush=True)
asyncio.run(security())
