"""Executed with the same real-provider fixture and real event dispatch as parity."""
# Real recorder; only its queue is intercepted. No DB lifecycle/startup is run.
sakura = a.application.parent/'sakura/taiko'
sys.path.insert(0,str(sakura))
import taiko_runtime
taiko_runtime.__path__.append(str(sakura/'taiko_runtime'))
nonebot.logger.add(sys.stderr,level='ERROR',backtrace=False,diagnose=False)
spec=importlib.util.spec_from_file_location('taiko_runtime.platform_adapter',sakura/'taiko_runtime/platform_adapter.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
assert nonebot.load_plugin('nonebot_plugin_method_calls')
from nonebot_plugin_method_calls import recorder, taiko_commands as registry
recorder.CONFIG=types.SimpleNamespace(enabled=True)
records=[]
async def enqueue(record):records.append(dict(record))
recorder.enqueue_record=enqueue
assert sum(m is progress.matcher for m in registry._matcher_specs())==1

results=[]
def reset(virtual):
 state.update(unbound=False,allowed=True,visible=True,virtual=virtual,profile=0,members=['111','222'])
async def checked(platform,command='9星进度',**kwargs):
 before=len(records)
 result=await dispatch(progress.matcher,command,platform,**kwargs)
 assert not result[1], result[1]
 expected=0 if platform=='onebot' and kwargs.get('target',True) else 1
 assert len(records)-before==expected, (platform,command,len(records)-before,expected,result)
 if expected:
  assert records[-1]['normalized_command']=='进度',records[-1]
 return result
async def run_security():
 for virtual in (False,True):
  for platform in ('onebot','qq'):
   reset(virtual)
   for command in ('9星进度','9.0过关进度','SS进度 2','虹2025六段进度'):
    output=await checked(platform,command,target=False)
    assert output[0] and ('sha256' in json.dumps(output) or '只找到' in str(output)),output
    results.append(dict(case='stats',virtual=virtual,platform=platform,command=command))
   reset(virtual);state['visible']=False
   output=await checked(platform,target=platform=='onebot')
   if platform=='onebot':
    if a.host=='client':assert not output[0],output
    else:assert '查不到' in str(output) and 'sha256' not in str(output),output
   else:assert 'sha256' in str(output),output # Hidden self remains permitted.
   results.append(dict(case='hidden-other' if platform=='onebot' else 'hidden-self',virtual=virtual,platform=platform))
   reset(virtual);state['unbound']=True
   output=await checked(platform,target=False)
   assert '绑定' in str(output) and 'sha256' not in str(output),output
   results.append(dict(case='unbound',virtual=virtual,platform=platform))
   for point in ('prepared','rendered','send'):
    reset(virtual)
    original_prepare=entry.TinfoHostProvider.prepare
    original_render=progress.execute_progress
    original_deliver=entry.deliver
    def revoke():state['visible']=False
    if point=='prepared':
     def prepare(self,*args,**kwargs):
      result=original_prepare(self,*args,**kwargs);revoke();return result
     entry.TinfoHostProvider.prepare=prepare
    elif point=='rendered':
     def render(*args,**kwargs):
      result=original_render(*args,**kwargs);revoke();return result
     progress.execute_progress=render
    else:
     async def deliver(*args,**kwargs):revoke();return await original_deliver(*args,**kwargs)
     entry.deliver=deliver
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and 'sha256' not in str(output), (point,output)
     results.append(dict(case='revoke-'+point,virtual=virtual,platform=platform))
    finally:
     entry.TinfoHostProvider.prepare=original_prepare;progress.execute_progress=original_render;entry.deliver=original_deliver
   for change in ('member','order','profile'):
    reset(virtual)
    original=progress.execute_progress
    def changed(*args,**kwargs):
     result=original(*args,**kwargs)
     if change=='member':state['members']=['111','333']
     elif change=='order':state['members']=['222','111']
     else:state['profile']=1
     return result
    progress.execute_progress=changed
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and 'sha256' not in str(output),(change,output)
     results.append(dict(case='binding-'+change,virtual=virtual,platform=platform))
    finally:progress.execute_progress=original
 # Foreign progress belongs to other bots, with no response or statistics.
 for command in ('任务进度','账单进度','pjsk进度','活动进度 2'):
  reset(False)
  for platform in ('onebot','qq'):
   before=len(records)
   output=await dispatch(progress.matcher,command,platform,target=False)
   assert not output[0] and not output[1] and len(records)==before,(command,output)
   results.append(dict(case='foreign',command=command,platform=platform))
 # A current/history pair cannot cross source views, even after retry.
 if a.host=='client':
  reset(False)
  original_remote=userdata_provider.fetch_private_read
  history_reads=[]
  def mismatch(kind,*args,**kwargs):
   reply=original_remote(kind,*args,**kwargs)
   if kind=='history':
    history_reads.append(1);reply.source_view={'kind':'fixture','generation':state['generation']+1}
   return reply
  userdata_provider.fetch_private_read=mismatch
  try:
   output=await checked('qq','虹2025六段进度',target=False)
   assert len(history_reads)==2 and 'sha256' not in str(output) and '暂不可用' in str(output),output
   results.append(dict(case='reject-mixed-history-view'))
  finally:userdata_provider.fetch_private_read=original_remote
 assert not violations,violations
 (a.work/'security.json').write_text(json.dumps({'cases':results,'statistics_records':len(records),'io_violations':violations},ensure_ascii=False,indent=2))
 print(a.host,len(results),'security/statistics cases PASS; records',len(records),flush=True)
asyncio.run(run_security())
