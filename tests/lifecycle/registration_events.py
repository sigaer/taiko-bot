"""All owned matchers together: no second response and every lifecycle owner in stats."""
async def registration_main():
 full=list(player.matcher)+list(public.matcher)
 for platform in ['onebot','qq']:
  for name,command in [
   ('manual_create','新增空白账号 合成名字'),('manual_rename','空白账号改名 新名字'),('manual_claim_code','生成认领码'),
   ('manual_claim','认领空白账号 INVALID'),('manual_detach','解绑空白账号'),('manual_delete','永久删除空白账号'),
   ('manual_delete_confirm','确认永久删除空白账号'),('manual_score_upsert','录入成绩 wrong'),('manual_score_get','查看成绩 10000 表'),
   ('manual_score_delete','删除成绩 10000 表'),('manual_score_delete_confirm','确认删除成绩'),
   ('qq_migration_code','迁移验证码'),('bind_qq','绑定QQ 12345 '+'a'*32),('bind_qq_prompt','绑定QQ'),('bind_confirm','确认绑定'),
   ('bind_switch','u0'),('bind_remove','删除绑定 u2'),('bind_remove_confirm','确认删除绑定'),('show_bind','给看'),('unshow_bind','不给看'),
   ('update_typo','taikoupdat'),('public_score_token','网页成绩token')]:
   reset(manual_account=True)
   out=await dispatch(full,command,platform,target=False)
   assert not out[1],(name,out)
   recorded=[m for m in dispatched if m is not updates.update_typo or updates._normalize_update_command_text(command) in updates.UPDATE_TYPO_VARIANTS]
   assert recorded==[current_matcher(name)],(name,[x.module_name for x in dispatched])
   results.append({'platform':platform,'single_owner':name})
 assert not violations,violations
 (a.work/'registration-events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'registration events PASS',flush=True)
asyncio.run(registration_main())
