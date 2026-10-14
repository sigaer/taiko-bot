"""History and archive assertions run inside the isolated event fixture."""
async def history_cases():
 for virtual in (False,True):
  state['virtual']=virtual
  original=copy.deepcopy(payload)
  first=copy.deepcopy(payload);first['_meta']={'full':True}
  first['songs'][0]['good_cnt']=450;first['songs'][0]['ok_cnt']=149
  second={'_meta':{'full':False},'songs':[dict(payload['songs'][0])]}
  histories[:]=[{'fileName':'data_20261013_120000_000000.json','historyFormat':'raw-v1','capturedAt':'2026-10-13T12:00:00','payload':first},
               {'fileName':'data_20261014_120000_000000.json','historyFormat':'raw-v1','capturedAt':'2026-10-14T12:00:00','payload':second}]
  def publish_history():
   if a.host=='center':
    for member in ('111','222','333'):
     store=PublicationStore(a.work/'userdata',member)
     with store.exclusive():
      store.publish({'current':store.stage(json.dumps(payload).encode()),**{'history/'+h['fileName']:store.stage(json.dumps(h['payload']).encode()) for h in histories}},filesystem_times={'fileMtimes':{'current':1737000000.125}})
   state['generation']+=1
  publish_history()
  commands=['taikob20 v1','taikob'] if a.host=='center' else ['taikob20']
  for stage in ('first','hot','history-change','missing-history'):
   if stage=='history-change':
    histories[-1]['fileName']='data_20261014_130000_000000.json';histories[-1]['capturedAt']='2026-10-14T13:00:00'
    histories[-1]['payload']['songs'][0]['high_score']+=100
    publish_history()
   if stage=='missing-history':histories.clear();publish_history()
   for platform in ('onebot','qq'):
    for command in commands:
     before=await dispatch(old_matcher,command,platform,target=False)
     after=await dispatch(b30.taikob,command,platform,target=False)
     assert before==after and not after[1] and 'sha256' in str(after),(stage,virtual,command,before,after)
     results.append(dict(case=stage,virtual=virtual,platform=platform,command=command,output=after))
     print(a.host,'history',stage,virtual,command,'PASS',flush=True)
  payload.clear();payload.update(original)
 if a.host=='center':archive_cases()

def archive_cases():
 from taiko_bot.runtime.player.center import b30_daily,b30_history
 from frozen_b30 import daily_ability as old_daily
 import uuid
 archive_prefix='archive-'+uuid.uuid4().hex
 old_daily.dt=clock;b30_daily.dt=clock
 b30_history.datetime=clock
 # Exercise the preserved named archive path independently of B30's custom
 # temporary daily table. Publication and daily protocols are unmodified.
 day1=copy.deepcopy(payload);day1['_meta']={'full':True}
 day2=copy.deepcopy(day1)
 snapshots=[(FrozenClock(2026,10,13,12),day1),(FrozenClock(2026,10,14,12),day2)]
 for stage in ('first','hot','today-newer','past-newer','retention'):
  if stage=='today-newer':snapshots[-1]=(FrozenClock(2026,10,14,13),day2)
  if stage=='past-newer':snapshots[0]=(FrozenClock(2026,10,13,13),day1)
  if stage=='retention':snapshots=[]
  outputs=[];archives=[];write_counts=[]
  for suffix,score in [('old',old_score),('new',b30_history)]:
   identity=archive_prefix+'-'+suffix
   store=PublicationStore(a.work/'userdata',identity)
   with store.exclusive():
    store.publish({'current':store.stage(json.dumps(payload).encode()),**{f'history/data_{dt:%Y%m%d_%H%M%S_%f}.json':store.stage(json.dumps(blob).encode()) for dt,blob in snapshots}})
   writes=[]
   store.fault=lambda point:writes.append(point)
   with store.shared():
    kwargs={'snapshots':snapshots} if suffix=='new' else {}
    outputs.append(score._build_daily_rating_points_from_view(identity,20,collapse_duplicate_versions=True,_publication_store=store,**kwargs))
   archive=a.work/'userdata'/identity/'daily-ability-v1-top20-merged.json'
   archives.append(json.loads(archive.read_text()))
   write_counts.append(writes.count("daily-archive-durable"))
  assert outputs[0]==outputs[1] and archives[0]==archives[1],stage
  assert write_counts==([1,1] if stage in ("first","today-newer") else [0,0]),(stage,write_counts)
  if stage=='first':initial=copy.deepcopy(archives[0])
  if stage=='hot':assert archives[0]==initial
  if stage=='today-newer':assert archives[0]!=initial;updated=copy.deepcopy(archives[0])
  if stage in ('past-newer','retention'):assert archives[0]==updated
  results.append(dict(case='named-archive-'+stage,archive=archives[0],durable_writes=write_counts))
  print('center named archive',stage,'PASS',flush=True)
