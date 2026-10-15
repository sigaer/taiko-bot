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
assert all(sum(m is candidate for m in registry._matcher_specs())==1 for candidate in (new.score_cmd,new.score_line_cmd))

results=[]
def reset(virtual):
 state.update(unbound=False,allowed=True,visible=True,virtual=virtual,profile=0,members=['111','222'])
async def checked(platform,command=None,**kwargs):
 if command is None:command=command_name
 before=len(records)
 result=await dispatch(active_matcher,command,platform,**kwargs)
 assert not result[1], result[1]
 expected=0 if platform=='onebot' and kwargs.get('target',True) else 1
 assert len(records)-before==expected, (platform,command,len(records)-before,expected,result)
 if expected:
  assert records[-1]['normalized_command']==canonical,records[-1]
 return result
async def run_security():
 for virtual in (False,True):
  for platform in ('onebot','qq'):
   reset(virtual)
   for command in [command_name]:
    output=await checked(platform,command,target=False)
    assert output[0] and '稳定分：' in str(output),output
    results.append(dict(case='stats',virtual=virtual,platform=platform,command=command))
   reset(virtual);state['visible']=False
   output=await checked(platform,target=platform=='onebot')
   if platform=='onebot':
    assert '查不到' in str(output) and '稳定分：' not in str(output),output
   else:assert '稳定分：' in str(output),output # Hidden self remains permitted.
   results.append(dict(case='hidden-other' if platform=='onebot' else 'hidden-self',virtual=virtual,platform=platform))
   reset(virtual);state['unbound']=True
   output=await checked(platform,target=False)
   assert '绑定' in str(output) and '稳定分：' not in str(output),output
   results.append(dict(case='unbound',virtual=virtual,platform=platform))
   for point in ('prepared','rendered','send'):
    reset(virtual)
    original_prepare=entry.TinfoHostProvider.prepare
    original_render=new.host.prepare_estimate
    original_deliver=entry.AuthorizedDelivery.finish
    def revoke():state['visible']=False
    if point=='prepared':
     def prepare(self,*args,**kwargs):
      result=original_prepare(self,*args,**kwargs);revoke();return result
     entry.TinfoHostProvider.prepare=prepare
    elif point=='rendered':
     def render(*args,**kwargs):
      result=original_render(*args,**kwargs);revoke();return result
     new.host.prepare_estimate=render
    else:
     async def deliver(*args,**kwargs):revoke();return await original_deliver(*args,**kwargs)
     entry.AuthorizedDelivery.finish=deliver
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and '稳定分：' not in str(output), (point,output)
     results.append(dict(case='revoke-'+point,virtual=virtual,platform=platform))
    finally:
     entry.TinfoHostProvider.prepare=original_prepare;new.host.prepare_estimate=original_render;entry.AuthorizedDelivery.finish=original_deliver
   reset(virtual)
   active_bot=bot if platform=='onebot' else qq
   original_send=active_bot.send
   async def failed_send(self,event,message,**kwargs):
    if '稳定分：' in str(normalized(message if isinstance(message,str) or hasattr(message,'type') else list(message))):
     state['visible']=False
     raise RuntimeError('isolated transport failure')
    return await original_send(event,message,**kwargs)
   active_bot.send=types.MethodType(failed_send,active_bot)
   try:
    output=await checked(platform,target=False)
    assert '稳定分：' not in str(output) and ('查不到' if a.host=='center' else '授权已失效') in str(output),output
    results.append(dict(case='revoke-on-send-failure',virtual=virtual,platform=platform))
   finally:active_bot.send=original_send
   for change in ('member','order','profile'):
    reset(virtual)
    original=new.host.prepare_estimate
    def changed(*args,**kwargs):
     result=original(*args,**kwargs)
     if change=='member':state['members']=['111','333']
     elif change=='order':state['members']=['222','111']
     else:state['profile']=1
     return result
    new.host.prepare_estimate=changed
    try:
     output=await checked(platform,target=False)
     assert ('查不到' if a.host=='center' else '授权已失效') in str(output) and '稳定分：' not in str(output),(change,output)
     results.append(dict(case='binding-'+change,virtual=virtual,platform=platform))
    finally:new.host.prepare_estimate=original
 from dataclasses import replace
 from taiko_application.private_input import ReadFailure
 for virtual in (False,True):
  for platform in ('onebot','qq'):
   for missing in (False,True):
    reset(virtual)
    original=entry.TinfoHostProvider.prepare
    expected_hint=[]
    def failed_current(self,*args,**kwargs):
     private=original(self,*args,**kwargs)
     expected_hint.append(self.recommendation_missing_hint)
     return replace(private,current=None,current_failure=ReadFailure(missing,'isolated invalid current'))
    entry.TinfoHostProvider.prepare=failed_current
    try:
     output=await checked(platform,target=False)
     expected=expected_hint[-1] if missing else '估分计算失败，请检查曲库/数据匹配是否正常'
     assert expected in str(output) and '稳定分：' not in str(output),output
     results.append(dict(case='missing-current' if missing else 'invalid-current',virtual=virtual,platform=platform))
    finally:entry.TinfoHostProvider.prepare=original
 # Unrelated commands produce neither a response nor a statistics record.
 for command in ('任务进度','账单进度','pjsk进度','活动进度 2'):
  reset(False)
  for platform in ('onebot','qq'):
   before=len(records)
   output=await dispatch(active_matcher,command,platform,target=False)
   assert not output[0] and not output[1] and len(records)==before,(command,output)
   results.append(dict(case='foreign',command=command,platform=platform))
 assert not violations,violations
 (a.work/(command_name+'-security.json')).write_text(json.dumps({'cases':results,'statistics_records':len(records),'io_violations':violations},ensure_ascii=False,indent=2))
 print(a.host,len(results),'security/statistics cases PASS; records',len(records),flush=True)
# Actual public and private recording, with unchanged display names.
async def public_statistics():
 for command,matcher,canonical_name in [('查分 id10000 500 100',new.score_cmd,'查分计算'),('分数线 极 id10000 30',new.score_line_cmd,'分数线')]:
  for platform in ('onebot','qq'):
   before=len(records)
   output=await dispatch(matcher,command,platform,target=False)
   assert not output[1] and output[0] and len(records)==before+1,(command,output,records)
   assert records[-1]['normalized_command']==canonical_name
 print(a.host,'public score statistics 4 PASS',flush=True)
asyncio.run(public_statistics())
if a.host=='center':
 command_name='估分 id10000';active_matcher=new.score_estimate_cmd;canonical='估分'
 results=[];records.clear();asyncio.run(run_security())
else:
 assert not hasattr(new,'score_estimate_cmd')
 print('client estimate matcher absent PASS',flush=True)
