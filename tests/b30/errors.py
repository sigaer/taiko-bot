"""Successful error semantics comparisons, never accepting paired exceptions."""
async def error_cases():
 results=[]
 original=copy.deepcopy(payload)
 def update():
  state['generation']+=1
  if a.host=='center':
   for member in ('111','222','333'):publish(member,payload)
 for virtual in (False,True):
  state['virtual']=virtual
  for kind in ('no-scores','low-accuracy'):
   payload['songs']=[] if kind=='no-scores' else [{**r,'good_cnt':20,'ok_cnt':580,'ng_cnt':0} for r in original['songs']]
   update()
   for platform in ('onebot','qq'):
    command='taikob20 v1' if a.host=='center' else 'taikob20'
    before=await dispatch(old_matcher,command,platform,target=False)
    after=await dispatch(b30.taikob,command,platform,target=False)
    assert before==after and not after[1] and after[0],(kind,virtual,platform,before,after)
    results.append(dict(case=kind,virtual=virtual,platform=platform,output=after))
 payload.clear();payload.update(original);state['virtual']=False;update()
 if a.host=='center':
  original_new=taikob_v2_data.load_v2_snapshot;original_old=old_v2.load_v2_snapshot
  def unavailable():raise old_v2_data.V2DataSourceError('synthetic public model unavailable')
  taikob_v2_data.load_v2_snapshot=unavailable;old_v2.load_v2_snapshot=unavailable
 else:
  path=a.work/'songs/constants_id_v2.csv';saved=path.read_bytes();path.unlink()
  old_v2._load_v2_song_map.cache_clear();b30.modules()[4]._load_v2_song_map.cache_clear()
 try:
  for platform in ('onebot','qq'):
   for command in ('taikob20 v2','taikob20 v2 体力','taikob20 v2 -r'):
    before=await dispatch(old_matcher,command,platform,target=False)
    after=await dispatch(b30.taikob,command,platform,target=False)
    assert before==after and not after[1] and after[0],('public-missing',command,before,after)
    results.append(dict(case='public-missing',platform=platform,command=command,output=after))
 finally:
  if a.host=='center':taikob_v2_data.load_v2_snapshot=original_new;old_v2.load_v2_snapshot=original_old
  else:path.write_bytes(saved)
 state.update(virtual=False,members=['444'],profile=0)
 if a.host=='center':
  for platform in ('onebot','qq'):
   for command in ('taikob20 v1','taikob20 v2'):
    before=await dispatch(old_matcher,command,platform,target=False)
    after=await dispatch(b30.taikob,command,platform,target=False)
    assert before==after and not after[1] and '未上传' in str(after),('missing-current',before,after)
    results.append(dict(case='missing-current',platform=platform,command=command,output=after))
 else:
  original_remote=userdata_provider.fetch_private_read
  def missing(*args,**kwargs):
   from taiko_bot.viewer_client import ViewerClientError
   raise ViewerClientError('成绩不存在，请先上传。',status_code=404)
  userdata_provider.fetch_private_read=missing
  try:
   for platform in ('onebot','qq'):
    before=await dispatch(old_matcher,'taikob20',platform,target=False)
    after=await dispatch(b30.taikob,'taikob20',platform,target=False)
    assert before[1] and before[1][0][0]=='UserdataProviderError',before
    assert not after[1] and '成绩不存在，请先上传。' in str(after) and 'sha256' not in str(after),after
    results.append(dict(case='missing-current-authorized-host-error',platform=platform,output=after))
  finally:userdata_provider.fetch_private_read=original_remote
 assert not violations,violations
 (a.work/'errors.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'error cases PASS',flush=True)
asyncio.run(error_cases())
