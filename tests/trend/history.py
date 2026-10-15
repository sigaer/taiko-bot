"""Real command archive writes and history-only semantics, isolated sources."""
async def archive_cases():
 assert a.host=='center'
 import uuid
 original_init=PublicationStore.__init__
 writes=[]
 def instrument(self,*args,**kwargs):
  original_init(self,*args,**kwargs)
  self.fault=lambda point:writes.append((self.identity,point))
 PublicationStore.__init__=instrument
 try:
  for version in ('v1','v2'):
   ids=[str(int(uuid.uuid4().hex[:12],16)) for _ in range(2)]
   base=copy.deepcopy(payload);base['_meta']={'full':True}
   snapshots=[(FrozenClock(2026,10,13,12),base),(FrozenClock(2026,10,14,12),base)]
   for stage in ('first','hot','today-newer','past-newer','retention'):
    if stage=='today-newer':snapshots[-1]=(FrozenClock(2026,10,14,13),base)
    if stage=='past-newer':snapshots[0]=(FrozenClock(2026,10,13,13),base)
    if stage=='retention':snapshots=[]
    outputs=[];archives=[];counts=[]
    for identity,matcher in zip(ids,[old_matchers[False],new.trend]):
     state.update(virtual=False,members=[identity],profile=0,visible=True,allowed=True)
     store=PublicationStore(a.work/'userdata',identity)
     with store.exclusive():
      store.publish({'current':store.stage(json.dumps(payload).encode()),**{f'history/data_{dt:%Y%m%d_%H%M%S_%f}.json':store.stage(json.dumps(blob).encode()) for dt,blob in snapshots}})
     writes.clear()
     output=await dispatch(matcher,'taikotrend '+version,'qq',target=False)
     assert not output[1] and 'sha256' in str(output),(version,stage,output)
     outputs.append(output)
     archives.append(json.loads((a.work/'userdata'/identity/f'daily-ability-{version}-top20.json').read_text()))
     counts.append(sum(point=='daily-archive-durable' for _,point in writes))
    assert outputs[0]==outputs[1] and archives[0]==archives[1],(version,stage,outputs)
    assert counts==([1,1] if stage in ('first','today-newer') else [0,0]),(version,stage,counts)
    if stage=='first':initial=copy.deepcopy(archives[0])
    if stage=='hot':assert archives[0]==initial
    if stage=='today-newer':assert archives[0]!=initial;updated=copy.deepcopy(archives[0])
    if stage in ('past-newer','retention'):assert archives[0]==updated
    results.append(dict(version=version,stage=stage,writes=counts,archive=archives[0],output=outputs[1]))
    print('center command archive',version,stage,counts,'PASS',flush=True)
 finally:PublicationStore.__init__=original_init
 (a.work/'archive.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))

async def history_cases():
 original=copy.deepcopy(histories)
 for case in ('empty','low-accuracy','no-oni','same-count','count-regression','day-window'):
  histories[:]=copy.deepcopy(original)
  if case=='empty':histories.clear()
  if case in ('low-accuracy','no-oni'):
   for h in histories:
    for row in h['payload']['songs']:
     if case=='no-oni':row['level']=1
     else:row.update(good_cnt=0,ok_cnt=0,ng_cnt=600)
  if case=='same-count':histories[-1]['payload']['songs'][0]['stage_cnt']=histories[0]['payload']['songs'][0]['stage_cnt']
  if case=='count-regression':histories[-1]['payload']['songs'][0]['stage_cnt']=0
  if case=='day-window':
   histories[0].update(fileName='data_20260901_120000_000000.json',capturedAt='2026-09-01T12:00:00')
  publish_history()
  # Unique N avoids archived measurements from preceding scenarios.
  number=31+['empty','low-accuracy','no-oni','same-count','count-regression','day-window'].index(case)
  for platform in ('onebot','qq'):
   for play,version in [(p,v) for p in (False,True) for v in (('v1','v2') if a.host=='center' else ('',))]:
    command=('taikoplaytrend' if play else 'taikotrend')+f' {version} {number}'
    before=await dispatch(old_matchers[play],command,platform,target=False)
    after=await dispatch(new.playtrend if play else new.trend,command,platform,target=False)
    assert before==after and not after[1],(case,command,before,after)
    if case in ('same-count','count-regression','day-window'):assert 'sha256' in str(after),(case,after)
    else:assert after[0],(case,after)
    results.append(dict(case=case,platform=platform,command=command,output=after))
    print(a.host,'history',case,command,'PASS',flush=True)
 assert not violations,violations
 (a.work/'history.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
