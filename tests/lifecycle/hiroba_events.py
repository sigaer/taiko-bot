"""Hiroba discovery boundary synthetic; native binding SQL and publication are real."""
async def hiroba_main():
 from taiko_bot.runtime.player.center.hiroba import native_binding as native, credentials, sync
 from taiko_bot.runtime.player.center import userdata_storage, draw_dress
 from taiko_store import PublicationStore
 os.environ.update(TAIKO_DB_USER='fixture',TAIKO_DB_PASSWORD='fixture',HIROBA_CRED_KEY='synthetic-only')
 userdata_storage.pymysql=types.SimpleNamespace(connect=lambda **kwargs:db.connect())
 hiroba_id='123456789012';secret=credentials.encrypt_password('synthetic-password')
 native.run_private_credentials=lambda request,**kwargs:{'taikoIds':[hiroba_id],'passwordEnc':secret}
 sample={'profile':{'userid':hiroba_id,'mydon_name':'合成日服玩家'},'songs':[],'achievement':{},'dojo':{}}
 image=io.BytesIO();Image.new('RGB',(48,48),'green').save(image,format='PNG');png=image.getvalue()
 def synchronize(identity,*,email,password,progress=None,publication_store):
  assert identity==hiroba_id and email=='synthetic@example.test' and password=='synthetic-password'
  userdata_storage.save_userdata(identity,copy.deepcopy(sample),source='hiroba',publication_store=publication_store)
  return identity
 sync.sync_bound_hiroba_userdata=synchronize
 draw_dress.render_update_changes_image=lambda *args,**kwargs:png
 if a.host=='client':
  from taiko_bot import viewer_client
  request=viewer_client._request_json
  def remote(method,url,**kwargs):
   body=kwargs.get('json_payload',{})
   if url.endswith('/hiroba/bind'):
    actor=body['configuredByQq']
    result=native.bind_native_hiroba(actor,body['email'],body['password'],target=body['targetTaikoNo'],connection_factory=db.connect)
    return {'taikoIds':list(result.taiko_ids),'bind':binding_payload(actor)}
   if url.endswith('/sync-hiroba'):
    return {'taikoId':hiroba_id,'source':'hiroba','userdata':copy.deepcopy(sample),'imageBase64':base64.b64encode(png).decode(),'message':'Hiroba 更新成功！'}
   return request(method,url,**kwargs)
  viewer_client._request_json=remote
 for platform,principal in zip(['onebot','qq'],principals):
  observed=[]
  for legacy in [True,False]:
   reset()
   command='绑定hiroba synthetic@example.test synthetic-password '+hiroba_id
   response=await dispatch(old['bind_hiroba'] if legacy else identity.bind_hiroba,command,platform,target=False)
   assert not response[1] and '已按指定太鼓番绑定' in str(response),response
   assert bind_info(principal)['id']==hiroba_id
   updated=await dispatch(old['hiroba_update'] if legacy else identity.hiroba_update,'更新hiroba all',platform,target=False)
   assert not updated[1] and hashlib.sha256(png).hexdigest() in str(updated),updated
   if a.host=='center':
    with PublicationStore(a.work/'userdata',hiroba_id).shared() as lease:
     # Reader is constructed from the actual store lease, not a private file.
     pass
    store=PublicationStore(a.work/'userdata',hiroba_id)
    with store.shared():assert json.loads(store.reader().current_raw())['profile']['userid']==hiroba_id
   observed.append((response,updated,effects()))
  assert observed[0]==observed[1],observed
  results.append({'platform':platform,'hiroba_bind_update_parity':True})
 assert not violations,violations
 (a.work/'hiroba-events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'Hiroba event PASS',flush=True)
asyncio.run(hiroba_main())
