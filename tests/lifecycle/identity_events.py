"""Binding title proof and full-target confirmation using real dispatch/SQL transport."""
async def identity_main():
 title={'value':'旧称号'}
 def profile():return {'userid':'33333','mydon_name':'合成玩家','province':'合成省','gameCostume':{'title':title['value'],'titleplate_id':1}}
 if a.host=='center':
  (a.work/'config.json').write_text(json.dumps({'cookie':'synthetic-cookie'}))
  os.environ['TAIKO_WAHLAP_CONFIG_PATH']=str(a.work/'config.json')
  class ProfileHTTP:
   def __init__(self,*args,**kwargs):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def post(self,url,*,json,headers):
    assert json['keyword']=='33333';return Response({'data':{'players':[profile()]}})
  host.httpx=types.SimpleNamespace(AsyncClient=ProfileHTTP);old['httpx']=host.httpx
 else:
  host.fetch_wahlap_player_profile=lambda uid:profile();old['fetch_wahlap_player_profile']=host.fetch_wahlap_player_profile
 for platform,principal in zip(['onebot','qq'],principals):
  observations=[]
  for legacy in [True,False]:
   reset();title['value']='旧称号'
   start=await dispatch(old['bind'] if legacy else identity.bind,'绑定33333',platform,target=False)
   assert not start[1] and '合成玩家' in str(start),start
   same=await dispatch(old['bind_confirm'] if legacy else identity.bind_confirm,'确认绑定',platform,target=False)
   assert '尚未变化' in str(same),same
   title['value']='新称号'
   confirmed=await dispatch(old['bind_confirm'] if legacy else identity.bind_confirm,'确认绑定',platform,target=False)
   assert not confirmed[1] and '已通过称号变更验证' in str(confirmed),confirmed
   assert any(row[2]=='33333' for row in db.rows('bind'))
   observations.append((start,same,confirmed,effects()))
  assert observations[0]==observations[1],observations
  results.append({'platform':platform,'title_verification_write_parity':True})
  for kind in ['visible','profile','members','u0','source','order','unbound']:
   reset();title['value']='旧称号'
   await dispatch(identity.bind,'绑定33333',platform,target=False)
   with sqlite3.connect(db.path) as conn:
    if kind=='visible':conn.execute('UPDATE bind SET visible=0 WHERE qq=?',(principal,))
    elif kind=='profile':conn.execute('UPDATE bind SET is_current=1-is_current WHERE qq=?',(principal,))
    elif kind=='members':conn.execute("UPDATE bind SET id='44444' WHERE qq=? AND slot_index=2",(principal,))
    elif kind=='u0':conn.execute('UPDATE taiko_bind_identity_state SET current_virtual=1 WHERE identity_key=?',(principal,))
    elif kind=='source':conn.execute("UPDATE bind SET source='hiroba' WHERE qq=? AND slot_index=2",(principal,))
    elif kind=='unbound':conn.execute('DELETE FROM bind WHERE qq=?',(principal,))
    else:
     conn.execute('UPDATE bind SET slot_index=slot_index+10 WHERE qq=?',(principal,));conn.execute('UPDATE bind SET slot_index=13-slot_index WHERE qq=?',(principal,))
   title['value']='新称号';before=effects()
   result=await dispatch(identity.bind_confirm,'确认绑定',platform,target=False)
   assert '绑定状态已变化' in str(result) and before==effects(),result
   results.append({'platform':platform,'confirmation_target_change':kind})
 assert not violations,violations
 (a.work/'identity-events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'identity event PASS',flush=True)
asyncio.run(identity_main())
