"""Real postprocessor and dispatch: target integrity, private delivery, and command boundaries."""
sakura=a.application.parent/'sakura/taiko';sys.path.insert(0,str(sakura))
import taiko_runtime
taiko_runtime.__path__.append(str(sakura/'taiko_runtime'))
spec=importlib.util.spec_from_file_location('taiko_runtime.platform_adapter',sakura/'taiko_runtime/platform_adapter.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
assert nonebot.load_plugin('nonebot_plugin_method_calls')
from nonebot_plugin_method_calls import recorder,taiko_commands as registry
recorder.CONFIG=types.SimpleNamespace(enabled=True);records=[]
async def enqueue(record):records.append(dict(record))
recorder.enqueue_record=enqueue
from taiko_bot.runtime.player import query_access
cases=[]
def reset(virtual=False):state.update(virtual=virtual,visible=True,unbound=False,profile=0,members=['111','222'],role='admin')
async def checked(matcher,command,platform,*,count=1,**kwargs):
 before=len(records);out=await dispatch(matcher,command,platform,**kwargs)
 assert not out[1],(command,out)
 assert len(records)-before==count,(command,platform,count,len(records)-before,out)
 return out
async def security():
 commands={'quick_actions_panel':'快捷操作','song_rank':'歌曲排行 id10000','summary':'taiko2025','twso':'查分','city_arcade_query':'鞍山哪有鼓','tsearch_switch':'tsearch on','tset_alias':'tset 统计别名 to id10000'}
 if a.host=='center':commands.update(song_title_query='查称号 id10000',custom_title_add='加称号 统计称号 to id10000')
 for name,command in commands.items():
  matcher=getattr(newq if hasattr(newq,name) else newm,name)
  assert sum(candidate is matcher for candidate in registry._matcher_specs())==1,name
  for platform in ('onebot','qq'):
   reset();count=0 if a.host=='client' and name=='tsearch_switch' and platform=='qq' else 1
   out=await checked(matcher,command,platform,count=count,target=False)
   if count:assert out[0],(name,out)
   cases.append(dict(case='statistics',name=name,platform=platform,count=count))
 for platform in ('onebot','qq'):
  reset()
  for command,canonical in [('查分','活动查分'),('/查分','活动查分'),('查分 id10000 500 100','查分计算'),('/查分 里id10000 500 100','查分计算')]:
   out=await checked([newq.twso,entry.scoring.score_cmd],command,platform,target=False)
   assert len(out[0])==1 and records[-1]['normalized_command']==canonical,(command,out,records[-1])
   cases.append(dict(case='score-boundary',command=command,platform=platform))
 # Full target identity is rechecked after capture, rendering, and a failed send.
 for name in ('twso','summary'):
  matcher=getattr(newq,name);command=commands[name];private_marker='目前课题' if name=='twso' else 'sha256'
  for virtual in (False,True):
   for platform in ('onebot','qq'):
    reset(virtual);out=await checked(matcher,command,platform,target=False)
    assert private_marker in str(out),(name,virtual,out)
    cases.append(dict(case='authorized',name=name,virtual=virtual,platform=platform))
    reset(virtual);state['unbound']=True
    out=await checked(matcher,command,platform,target=False)
    assert '绑定' in str(out) and private_marker not in str(out),out
    cases.append(dict(case='unbound',name=name,virtual=virtual,platform=platform))
    reset(virtual);state['visible']=False
    out=await checked(matcher,command,platform,target=platform=='onebot',count=0 if platform=='onebot' else 1)
    assert ((not out[0] or '查不到' in str(out)) and private_marker not in str(out)) if platform=='onebot' else private_marker in str(out),out
    cases.append(dict(case='hidden',name=name,virtual=virtual,platform=platform))
    for point in ('prepared','calculated','member','order','profile','send'):
     reset(virtual)
     original_prepare=entry.TinfoHostProvider.prepare
     render_owner=newq if name=='summary' else query_access
     render_name='render_summary' if name=='summary' else 'score_record'
     original_render=getattr(render_owner,render_name)
     original_finish=entry.AuthorizedDelivery.finish
     original_delivery_send=entry.AuthorizedDelivery.send
     def revoke():
      if point=='member':state['members']=['111','333']
      elif point=='order':state['members']=['222','111']
      elif point=='profile':state['profile']=1
      else:state['visible']=False
     if point=='prepared':
      def prepare(self,*args,**kwargs):
       result=original_prepare(self,*args,**kwargs);revoke();return result
      entry.TinfoHostProvider.prepare=prepare
     elif point=='send':
      async def finish(*args,**kwargs):revoke();return await original_finish(*args,**kwargs)
      entry.AuthorizedDelivery.finish=finish
      async def send_delivery(*args,**kwargs):revoke();return await original_delivery_send(*args,**kwargs)
      entry.AuthorizedDelivery.send=send_delivery
     else:
      def render(*args,**kwargs):
       result=original_render(*args,**kwargs);revoke();return result
      setattr(render_owner,render_name,render)
     try:
      out=await checked(matcher,command,platform,target=False)
      assert '查不到' in str(out) and private_marker not in str(out),(name,point,out)
      cases.append(dict(case=point,name=name,virtual=virtual,platform=platform))
     finally:
      entry.TinfoHostProvider.prepare=original_prepare;setattr(render_owner,render_name,original_render);entry.AuthorizedDelivery.finish=original_finish;entry.AuthorizedDelivery.send=original_delivery_send
    reset(virtual);active=bot if platform=='onebot' else qq;original_send=active.send
    async def failed(self,event,message,**kwargs):
     if private_marker in str(normalized(message if isinstance(message,str) or hasattr(message,'type') else list(message))):
      state['visible']=False;raise RuntimeError('synthetic send failure')
     return await original_send(event,message,**kwargs)
    active.send=types.MethodType(failed,active)
    try:
     out=await checked(matcher,command,platform,target=False)
     assert '查不到' in str(out) and private_marker not in str(out),(name,out)
     cases.append(dict(case='failed-send',name=name,virtual=virtual,platform=platform))
    finally:active.send=original_send
 # A nickname embedded in a public title image is still private output.
 if a.host=='center':
  reset();render=newm.render_song_title_query
  def revoke_nickname(*args,**kwargs):
   result=render(*args,**kwargs);state['profile']=1;return result
  newm.render_song_title_query=revoke_nickname
  try:
   for platform in ('onebot','qq'):
    reset();out=await checked(newm.song_title_query,'查称号 id10000',platform,target=False)
    assert '查不到' in str(out) and 'sha256' not in str(out),out
    cases.append(dict(case='nickname-revoked',platform=platform))
  finally:newm.render_song_title_query=render
 # Group admin gate remains profile-specific, including QQ's original behavior.
 for platform in ('onebot','qq'):
  reset();state['role']='member'
  count=0 if a.host=='client' else 1
  out=await checked(newm.tsearch_switch,'tsearch off',platform,count=count,target=False)
  if a.host=='center' and platform=='onebot':assert '仅群管理员' in str(out),out
  if a.host=='client':assert not out[0],out
  cases.append(dict(case='group-permission',platform=platform))
 assert not violations,violations
 (a.work/'security.json').write_text(json.dumps({'cases':cases,'records':len(records),'io_violations':violations},ensure_ascii=False,indent=2))
 print(a.host,len(cases),'security/statistics PASS; records',len(records),flush=True)
asyncio.run(security())
