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
assert sum(m is rec.taikorec for m in registry._matcher_specs())==1

captured_active=False
private_roots=(a.work/'userdata',)
def capture_guard(event,args):
 if captured_active and event=='open' and isinstance(args[0],(str,os.PathLike)):
  path=Path(args[0]).resolve()
  assert not any(path.is_relative_to(root) for root in private_roots), 'renderer reread private data'
sys.addaudithook(capture_guard)
previous_import=builtins.__import__
def captured_import(name,*args,**kwargs):
 if captured_active and (name=='plugins' or name.startswith('plugins.')):
  raise AssertionError('recommendation imports a legacy plugin')
 return previous_import(name,*args,**kwargs)
builtins.__import__=captured_import
real_prepare_result=rec.prepare_result
real_execute=rec.execute_recommendation
def prepare_captured(*args,**kwargs):
 global captured_active
 captured_active=True
 try:return real_prepare_result(*args,**kwargs)
 finally:captured_active=False
def execute_pure(*args,**kwargs):
 global application_active
 application_active=True
 try:return real_execute(*args,**kwargs)
 finally:application_active=False
rec.prepare_result=prepare_captured
rec.execute_recommendation=execute_pure
results=[]
def reset(virtual):
 state.update(unbound=False,allowed=True,visible=True,virtual=virtual,profile=0,members=['111','222'])
async def checked(platform,command='taikorec',**kwargs):
 before=len(records)
 result=await dispatch(rec.taikorec,command,platform,**kwargs)
 assert not result[1], result[1]
 expected=0 if platform=='onebot' and kwargs.get('target',True) else 1
 assert len(records)-before==expected, (platform,command,len(records)-before,expected,result)
 if expected:
  assert records[-1]['normalized_command']=='taikorec',records[-1]
 return result
async def run_security():
 for virtual in (False,True):
  for platform in ('onebot','qq'):
   reset(virtual)
   for command in ('taikorec','推荐歌曲体力3','推荐歌曲 全连','推荐歌曲 紫雅 9星'):
    output=await checked(platform,command,target=False)
    assert output[0] and ('sha256' in json.dumps(output) or '只找到' in str(output)),output
    results.append(dict(case='stats',virtual=virtual,platform=platform,command=command))
   reset(virtual);state['visible']=False
   output=await checked(platform,target=platform=='onebot')
   if platform=='onebot':assert '查不到' in str(output) and 'sha256' not in str(output),output
   else:assert 'sha256' in str(output),output # Hidden self remains permitted.
   results.append(dict(case='hidden-other' if platform=='onebot' else 'hidden-self',virtual=virtual,platform=platform))
   reset(virtual);state['unbound']=True
   output=await checked(platform,target=False)
   assert '绑定' in str(output) and 'sha256' not in str(output),output
   results.append(dict(case='unbound',virtual=virtual,platform=platform))
   for point in ('prepared','rendered','send'):
    reset(virtual)
    original_prepare=entry.TinfoHostProvider.prepare
    original_render=rec.prepare_result
    original_deliver=entry.deliver
    def revoke():state['visible']=False
    if point=='prepared':
     def prepare(self,*args,**kwargs):
      result=original_prepare(self,*args,**kwargs);revoke();return result
     entry.TinfoHostProvider.prepare=prepare
    elif point=='rendered':
     def render(*args,**kwargs):
      result=original_render(*args,**kwargs);revoke();return result
     rec.prepare_result=render
    else:
     async def deliver(*args,**kwargs):revoke();return await original_deliver(*args,**kwargs)
     entry.deliver=deliver
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and 'sha256' not in str(output), (point,output)
     results.append(dict(case='revoke-'+point,virtual=virtual,platform=platform))
    finally:
     entry.TinfoHostProvider.prepare=original_prepare;rec.prepare_result=original_render;entry.deliver=original_deliver
   for change in ('member','order','profile'):
    reset(virtual)
    original=rec.prepare_result
    def changed(*args,**kwargs):
     result=original(*args,**kwargs)
     if change=='member':state['members']=['111','333']
     elif change=='order':state['members']=['222','111']
     else:state['profile']=1
     return result
    rec.prepare_result=changed
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and 'sha256' not in str(output),(change,output)
     results.append(dict(case='binding-'+change,virtual=virtual,platform=platform))
    finally:rec.prepare_result=original
 # Errors are still returned in their original calculation-specific branches.
 from importlib import import_module
 for target in (False,True):
  module=import_module(f'taiko_bot.runtime.player.{a.host}.recommendation_support.'+('target_recommend' if target else 'score_calculator'))
  name='compute_target_recommendations_from_userdata' if target else 'compute_recommendations_from_records'
  original=getattr(module,name)
  for error in (FileNotFoundError('fixture'),ValueError('fixture')):
   reset(False)
   def fail(*args,**kwargs):raise error
   setattr(module,name,fail)
   try:
    output=await checked('onebot','推荐歌曲 全连' if target else 'taikorec',target=False)
    expected='还未上传' if isinstance(error,FileNotFoundError) else ('目标推荐计算失败' if target else '推荐计算失败')
    assert expected in str(output) and 'sha256' not in str(output),output
    results.append(dict(case='error',target=target,error=type(error).__name__))
   finally:setattr(module,name,original)
 assert not violations,violations
 (a.work/'security.json').write_text(json.dumps({'cases':results,'statistics_records':len(records),'io_violations':violations},ensure_ascii=False,indent=2))
 print(a.host,len(results),'security/statistics cases PASS; records',len(records),flush=True)
asyncio.run(run_security())
