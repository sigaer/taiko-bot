"""Batch error/parameter parity plus actual persistence and cached-summary boundaries."""
async def edge_cases():
 for platform in ('onebot','qq'):
  for name,command,required in [
   ('tset_alias','tset wrong','格式'),('tset_alias','tset 测试别名 to id10000','无需重复'),
   ('tset_alias','tset 另一个 to Fixture','可能是'),('tset_alias','tset 另一个 to 不存在歌曲','可能是'),
   ('tsearch_switch','tsearch on','开启' if a.host=='center' or platform=='onebot' else None),
   ('quick_actions_panel','taiko帮助','快捷操作' if a.host=='center' else None),
   ('song_rank','歌曲排名 id10000 难度=4 地区=广东','sha256'),
   ('song_rank','排行歌曲 id10000 鬼 44','sha256'),
   ('song_rank','歌曲排行 id10000 广东 表','sha256'),
   ('song_rank','歌曲排行 id10000 松','没有该难度')]:
   await compare(name,command,platform,required)
  for kind in ('api_error','map_error'):
   state[kind]=True
   try:
    await compare('song_rank' if kind=='api_error' else 'city_arcade_query','歌曲排行 id10000' if kind=='api_error' else '鞍山哪有鼓',platform)
   finally:state[kind]=False
  if a.host=='center':
   for command in ('加称号','加称号 测试 to 里id10000','添加称号 测试 to id10000','查称号','查称号 不存在称号','查称号 Fixture'):
    await compare('song_title_query' if command.startswith('查称号') else 'custom_title_add',command,platform)
  # Write failures retain the old ordering: a failed alias save never emits audit writes.
  for operation in ('save_alias_data','append_alias_log'):
   original=getattr(newm,operation);old=old_ns['tset_alias'][operation]
   def failure(*args,**kwargs):raise OSError('synthetic write failure')
   setattr(newm,operation,failure);old_ns['tset_alias'][operation]=failure
   try:await compare('tset_alias','tset 失败别名 to id10000',platform,'保存失败' if operation=='save_alias_data' else '已添加')
   finally:setattr(newm,operation,original);old_ns['tset_alias'][operation]=old
  if a.host=='center':
   original=newm.write_admin_action_log;old=old_ns['tset_alias']['write_admin_action_log']
   newm.write_admin_action_log=failure;old_ns['tset_alias']['write_admin_action_log']=failure
   try:await compare('tset_alias','tset 审计失败别名 to id10000',platform,'已添加')
   finally:newm.write_admin_action_log=original;old_ns['tset_alias']['write_admin_action_log']=old
 # The real summary cache persists once, then hits without rewriting PNG.
 from taiko_bot.runtime.player import query_access
 summary_host=import_module(f'taiko_bot.runtime.player.{a.host}.summary_host')
 writes=[]
 def count_write(event,args):
  if event=='open' and isinstance(args[0],str) and args[0].endswith('_taiko_2025_summary.png') and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):writes.append(args[0])
 sys.addaudithook(count_write)
 state.update(virtual=True,visible=True,profile=0,members=['111','222'])
 for path in (a.work/'output').glob('*taiko_2025_summary*'):path.unlink()
 out=await dispatch(newq.summary,'taiko2025','onebot',target=False)
 assert not out[1] and 'sha256' in str(out),out
 assert len(writes)==1,writes
 again=await dispatch(newq.summary,'taiko2025','onebot',target=False)
 assert out==again and len(writes)==1,(out,again,writes)
 state['members']=['111','333']
 changed=await dispatch(newq.summary,'taiko2025','onebot',target=False)
 assert not changed[1] and 'sha256' in str(changed) and len(writes)==2,(changed,writes)
 results.append(dict(case='summary-cold-hot-binding-cache',writes=len(writes)))
 assert not violations,violations
 (a.work/'edges.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'parameter/API/write/cache edges PASS',flush=True)
asyncio.run(edge_cases())
