"""Additional real images, failure semantics and deterministic filtering boundaries."""
async def compare(command,platform='qq',image=True):
 kind='my_don' if command=='我的小咚' else 'tcloud' if 'cloud' in command else 'song_metric_query'
 before=await dispatch(old_matchers[kind],command,platform,target=False)
 after=await dispatch(getattr(new,kind),command,platform,target=False)
 assert before==after and not after[1],(command,before,after)
 assert ('sha256' in str(after))==image,(command,after)
 return after

async def showcases():
 assert a.host=='center'
 custom=[(1,'合成称号甲','合成称号甲',10000,4,'user','fixture','fixture','fixture',None,None,'2026-01-01','2026-01-01','full_combo'),
         (2,'合成称号乙','合成称号乙',10000,4,'user','fixture','fixture','fixture',None,None,'2026-01-02','2026-01-02','all_perfect')]
 state['custom_rows']=custom
 results=[];distinct=set()
 for scenario in ('nickname','full','full_gold','invalid-layout','settings-query-failed','custom-query-failed'):
  state['showcase_rows']=[(scenario,'合成称号乙'),(scenario,'合成称号甲'),(scenario,'合成称号乙')]
  state['showcase_error']=scenario=='settings-query-failed'
  state['custom_error']=scenario=='custom-query-failed'
  for virtual in (False,True):
   state['virtual']=virtual
   for platform in ('onebot','qq'):
    for command in ('我的小咚','我的单可','tcloud'):
     output=await compare(command,platform)
     if command=='我的小咚' and not virtual and platform=='onebot':distinct.add(str(output))
     results.append(dict(scenario=scenario,virtual=virtual,platform=platform,command=command,output=output))
     print(a.host,'showcase',scenario,virtual,platform,command,'PASS',flush=True)
 assert len(distinct)>=3, 'Layout changes did not affect images'
 assert not violations,violations
 (a.work/'showcases.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))

async def errors_and_metrics():
 results=[]
 # Compare exact filtering output against frozen functions on mixed difficulties,
 # malformed numbers, low-miss boundaries, FC/DF exclusion, shelf status and sort.
 metric=new._metric
 rows=[]
 for i in range(80):
  rows.append(dict(song_no=10000+i%10,level=1+i%5,ok_cnt=i%12,ng_cnt=i%3,
                   dondaful_combo_cnt=int(i%11==0),full_combo_cnt=int(i%7==0)))
 rows += [dict(song_no='bad',level=4),dict(song_no=10000,level=0),dict(song_no=10000,level=4,ok_cnt='bad',bad_cnt='1')]
 original_load=ns['_load_user_song_records'];ns['_load_user_song_records']=lambda _:rows
 try:
  for mode in ('ng','ok','single_ok','dondaful'):
   for value in (0,1,3,9,10,999,None):
    for order in ('default','asc','desc'):
     expected=ns['_collect_song_metric_matches']('fixture',mode,value,order)
     actual=metric._collect_song_metric_matches(rows,mode,value,order)
     assert expected==actual,(mode,value,order)
     assert all(r['song_no']!=10001 for r in actual)
     results.append(dict(case='metric-records',mode=mode,value=value,order=order,count=len(actual)))
 finally:ns['_load_user_song_records']=original_load
 original=copy.deepcopy(payload)
 for scenario in ('empty-songs','no-play-count','more-than-30','bad-profile'):
  payload.clear();payload.update(copy.deepcopy(original))
  if scenario=='empty-songs':payload['songs']=[]
  if scenario=='no-play-count':
   for row in payload['songs']:row.update(stage_cnt=0,play_cnt=0,play_count=0)
  if scenario=='more-than-30':
   payload['songs']=[dict(original['songs'][0],song_no=10000+i,ok_cnt=1,ng_cnt=0,full_combo_cnt=0,dondaful_combo_cnt=0) for i in range(65)]
  if scenario=='bad-profile':payload['profile']=[]
  if a.host=='center':
   for member in ('111','222','333'):publish(member,payload)
  else:state['generation']+=1
  for platform in ('onebot','qq'):
   for command in ('我的小咚','我的单可','tcloud'):
    expect=not(command=='tcloud' and scenario in ('empty-songs','no-play-count'))
    output=await compare(command,platform,image=expect)
    results.append(dict(case=scenario,platform=platform,command=command,output=output))
    print(a.host,'errors/boundaries',scenario,platform,command,'PASS',flush=True)
 payload.clear();payload.update(original)
 if a.host=='center':
  for member in ('111','222','333'):publish(member,payload)
 else:state['generation']+=1
 # Frozen handlers retain unbound text, QQ options and hidden-account routing.
 for command in ('我的小咚','我的单可','tcloud'):
  state['unbound']=True
  for platform in ('onebot','qq'):
   output=await compare(command,platform,image=False)
   results.append(dict(case='unbound-parity',platform=platform,command=command,output=output))
  state['unbound']=False;state['visible']=False
  kind='my_don' if command=='我的小咚' else 'tcloud' if command=='tcloud' else 'song_metric_query'
  before=await dispatch(old_matchers[kind],command,'onebot',target=True)
  after=await dispatch(getattr(new,kind),command,'onebot',target=True)
  assert before==after and not after[1] and 'sha256' not in str(after),(before,after)
  results.append(dict(case='hidden-other-parity',command=command,output=after))
  state['visible']=True
 # A genuinely absent current publication / remote 404 is handled through Host.
 previous_members=list(state['members'])
 state['members']=['444','555'];state['profile']=0;state['virtual']=False
 if a.host=='client':
  original_remote=userdata_provider.fetch_private_read
  def missing_remote(*args,**kwargs):
   from taiko_bot.viewer_client import ViewerClientError
   raise ViewerClientError('fixture missing current',status_code=404)
  userdata_provider.fetch_private_read=missing_remote
 try:
  for platform in ('onebot','qq'):
   for command in ('我的小咚','我的单可','tcloud'):
    output=await compare(command,platform,image=False)
    results.append(dict(case='missing-current',platform=platform,command=command,output=output))
 finally:
  state['members']=previous_members
  if a.host=='client':userdata_provider.fetch_private_read=original_remote
 # Existing renderer failure messages, successful dispatch of text (not a failed
 # image counted as successful parity).
 original_new=new.render
 old_names=['render_synced_my_don_image' if a.host=='center' else 'render_my_don_image','render_tcloud_image']
 for error in (FileNotFoundError('fixture'),RuntimeError('fixture'),ValueError('fixture')):
  def fail(*args,**kwargs):raise error
  saved={name:ns[name] for name in old_names}
  for name in old_names:ns[name]=fail
  new.render=fail
  try:
   for platform in ('onebot','qq'):
    for command in ('我的小咚','我的单可','tcloud'):
     output=await compare(command,platform,image=False)
     results.append(dict(case='render-'+type(error).__name__,platform=platform,command=command,output=output))
  finally:
   ns.update(saved);new.render=original_new
 # List rendering was outside the legacy data-error handler; retain that boundary.
 name='_render_song_metric_list_image'
 saved_old=ns[name];saved_new=getattr(new._metric,name)
 def broken_list(*args,**kwargs):raise RuntimeError('fixture list image failure')
 ns[name]=broken_list;setattr(new._metric,name,broken_list)
 try:
  for platform in ('onebot','qq'):
   before=await dispatch(old_matchers['song_metric_query'],'我的单可',platform,target=False)
   after=await dispatch(new.song_metric_query,'我的单可',platform,target=False)
   assert before==after and not after[0] and after[1]==[('RuntimeError','fixture list image failure')],(before,after)
   results.append(dict(case='list-render-error',platform=platform))
 finally:
  ns[name]=saved_old;setattr(new._metric,name,saved_new)
 # Explicitly excluded external bot mentions must not reach either handler.
 original_extract=entry.helpers.extract_plain_text
 for command in ('tcloud','太鼓词云','/词云'):
  for matcher in (old_matchers['tcloud'],new.tcloud):
   output=await dispatch(matcher,command+'[CQ:at,qq=3889003795]','onebot',target=False)
   assert not output[0] and not output[1],output
  results.append(dict(case='external-bot',command=command))
 assert not violations,violations
 (a.work/'errors-metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'filter/error cases PASS',flush=True)
