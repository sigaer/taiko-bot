"""Data/token/QR real-dispatch tests; API and SQL isolation are explicit."""
async def data_main():
 from taiko_bot.runtime.player.center import public_score_token as tokens
 tokens.get_taiko_db_connection=db.connect
 for platform,principal in zip(['onebot','qq'],principals):
  tokens.secrets=types.SimpleNamespace(token_hex=lambda n:'a'*48)
  await compare('public_score_token','网页成绩token',platform,'已生成新的',private=True)
  from taiko_bot.runtime.player.center.score_token_authority import manage_bot_score_token
  assert db.rows('public_score_tokens')[0][2]==hashlib.sha256(b'a'*48).hexdigest()
  tokens.secrets=types.SimpleNamespace(token_hex=lambda n:'b'*48)
  out=await dispatch(updates.public_score_token,'网页成绩token 重置',platform,target=False,private=True)
  assert not out[1] and 'b'*48 in str(out),out
  assert db.rows('public_score_tokens')[0][2]==hashlib.sha256(b'b'*48).hexdigest()
  assert manage_bot_score_token('11111',principal,'revoke')['revoked']
  assert not db.rows('public_score_tokens')
  reset(virtual=True)
  out=await dispatch(updates.public_score_token,'网页成绩token',platform,target=False,private=True)
  assert not db.rows('public_score_tokens') and ('u0' in str(out) if a.host=='center' else '实账号' in str(out)),out
  reset()
  original=updates.issue_public_score_token_for_taiko_id
  def revoke_after(*args,**kwargs):
   result=original(*args,**kwargs)
   with sqlite3.connect(db.path) as conn:conn.execute('UPDATE bind SET visible=0 WHERE qq=?',(principal,))
   return result
  updates.issue_public_score_token_for_taiko_id=revoke_after
  out=await dispatch(updates.public_score_token,'网页成绩token',platform,target=False,private=True)
  assert 'b'*48 not in str(out) and not out[1],out
  updates.issue_public_score_token_for_taiko_id=original
  results.append({'platform':platform,'token_rotation_revoke_send_guard':True})
  # Developer token remains the authority; a second GET checks it before upload/fallback.
  reset(); calls=[]; upstream={'revoke':False}
  class DeveloperHTTP:
   def __init__(self,*args,**kwargs):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def get(self,url,headers):
    assert url.endswith('/api/developer/userdata/11111') and headers['Authorization']=='Bearer '+'T'*24
    calls.append(url)
    return Response({'message':'revoked'},403) if upstream['revoke'] and len(calls)>1 else Response({'profile':{'name':'PRIVATE-FIXTURE'},'songs':[]})
  original_http=host.httpx;host.httpx=types.SimpleNamespace(AsyncClient=DeveloperHTTP)
  old['httpx']=host.httpx
  async def upload(self,api_name,**kwargs):
   assert api_name in ('upload_group_file','upload_private_file')
   sent.append({'file':normalized(Path(kwargs['file']).read_bytes())})
   return {'file_id':'fixture'}
  bot.call_api=types.MethodType(upload,bot)
  command='开发者数据 '+'T'*24+' 11111'
  before=await dispatch(old['developer_userdata'],command,platform,target=False)
  calls.clear()
  after=await dispatch(updates.developer_userdata,command,platform,target=False)
  assert before==after and not after[1],(before,after)
  assert '已发送' in str(after) if platform=='onebot' else 'PRIVATE-FIXTURE' in str(after),after
  assert len(calls)==(2 if platform=='onebot' else 3),calls
  calls.clear();upstream['revoke']=True
  out=await dispatch(updates.developer_userdata,command,platform,target=False)
  assert 'PRIVATE-FIXTURE' not in str(out) and 'file' not in str(out) and '失效' in str(out),out
  host.httpx=original_http;old['httpx']=original_http
  results.append({'platform':platform,'developer_success_parity_and_revocation':True})
  if a.host=='center':
   from taiko_bot.runtime.player.center import game_login_qr as qr
   (a.work/'config.json').write_text(json.dumps({'cookie':'synthetic-cookie'}))
   image=io.BytesIO();Image.new('RGB',(48,48),'black').save(image,format='PNG');png=image.getvalue()
   allowed=frozenset(principals);host.GAME_LOGIN_QR_ALLOWED_IDENTITIES=allowed;old['GAME_LOGIN_QR_ALLOWED_IDENTITIES']=allowed
   class QrHTTP:
    def __init__(self,*args,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def get(self,url,headers):
     assert headers['Authorization']=='synthetic-cookie'
     return Response({'status':0,'data':{'qrContent':base64.b64encode(png).decode()}})
   qr.httpx=types.SimpleNamespace(AsyncClient=QrHTTP,HTTPError=RuntimeError)
   before=await dispatch(old['game_login_qr'],'码来',platform,target=False)
   after=await dispatch(updates.game_login_qr,'码来',platform,target=False)
   assert before==after and hashlib.sha256(png).hexdigest() in str(after),(before,after)
   results.append({'platform':platform,'qr_success_sha256':hashlib.sha256(png).hexdigest()})
 assert not violations,violations
 (a.work/'data-events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'data event PASS',flush=True)
asyncio.run(data_main())
