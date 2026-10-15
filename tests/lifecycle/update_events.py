"""Actual native writer / HTTP transport. No production connection or reader."""
from datetime import datetime as DateTime
class FixedTime(DateTime):
 @classmethod
 def now(cls,tz=None):return cls(2026,10,15,10,0,0,tzinfo=tz)
async def update_main():
 image=io.BytesIO();Image.new('RGB',(48,48),'blue').save(image,format='PNG');png=image.getvalue()
 (a.work/'config.json').write_text(json.dumps({'cookie':'synthetic-cookie'}))
 os.environ['TAIKO_WAHLAP_CONFIG_PATH']=str(a.work/'config.json')
 upstream={'version':0,'fail':False};requests=[]
 if a.host=='center':
  from taiko_bot.runtime.player.center import update_user,userdata_storage,daily_ability,draw_dress
  from taiko_bot.runtime.player.center.native_wahlap_update import update_native_wahlap
  os.environ.update(TAIKO_DB_USER='fixture',TAIKO_DB_PASSWORD='fixture',TAIKO_DB_NAME='taiko_lifecycle_test')
  userdata_storage.pymysql=types.SimpleNamespace(connect=lambda **kwargs:db.connect())
  userdata_storage.datetime=FixedTime
  userdata_storage.uuid=types.SimpleNamespace(uuid4=lambda:types.SimpleNamespace(hex='f'*32))
  def response(url,**kwargs):
   requests.append(url)
   assert kwargs['headers']['Authorization']=='synthetic-cookie'
   if upstream['fail']:return Response({},500)
   if url.endswith('/all/songs'):
    records=copy.deepcopy(payload['songs']);records[0]['good_cnt']+=upstream['version']
    return Response({'message':'','data':{'playedRecords':{'scoreInfo':records}}})
   if url.endswith('/search/player'):return Response({'data':{'players':[{**payload['profile'],'userid':'11111'}]}})
   if '/achievement/' in url:return Response({'data':payload['achievement']})
   if '/dojo/score/' in url:return Response({'data':[]})
   raise AssertionError(url)
  update_user.requests=types.SimpleNamespace(get=response,post=response)
  # Freeze original calculation/storage source independently, keeping its protocol dependencies.
  def frozen(module,name):
   env=dict(vars(module));src=(a.baseline/'plugins/utils'/name).read_text()
   tree=ast.parse(src)
   nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
   exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),'frozen-'+name,'exec'),env)
   return env
  legacy_storage=frozen(userdata_storage,'userdata_storage.py')
  legacy_update=frozen(update_user,'update_user.py');legacy_update['save_userdata']=legacy_storage['save_userdata']
  # A real image renderer is checked separately; deterministic bytes here isolate writer behavior.
  render_calls=[]
  def render(user_id,*,show_all,score_view):
   captured=json.loads(score_view.current_raw());assert captured['profile']['userid']=='11111'
   render_calls.append((user_id,show_all));return png
  original_render=draw_dress.render_update_changes_image;draw_dress.render_update_changes_image=render
  original_sync=update_user.getUserData
  def publication():
   store=PublicationStore(a.work/'userdata','11111')
   with store.shared():
    view=store.reader();return json.loads(view.current_raw()),[json.loads(view.history_raw(n)) for n in view.history_names()]
  def wipe():
   shutil.rmtree(a.work/'userdata/11111',ignore_errors=True)
   shutil.rmtree(a.work/'userdata/.taiko-publications/11111',ignore_errors=True)
  for platform in ['onebot','qq']:
   observations=[]
   for legacy in [True,False]:
    reset();wipe();requests.clear();render_calls.clear();upstream.update(version=0,fail=False)
    update_user.getUserData=legacy_update['getUserData'] if legacy else original_sync
    handler=old['update'] if legacy else updates.update
    first=await dispatch(handler,'taikoupdate',platform,target=False)
    assert not first[1] and hashlib.sha256(png).hexdigest() in str(first),first
    initial=publication();assert len(initial[1])==1 and initial[1][0]['_meta']['full']
    daily=list((a.work/'userdata/11111').glob('daily-ability-*.json'));assert len(daily)==2,daily
    prior=len(requests);hot=await dispatch(handler,'taikoupdate',platform,target=False)
    assert len(requests)==prior and not hot[0],hot
    from taiko_bot.runtime.player.center import taiko_update_cooldown
    taiko_update_cooldown._last_triggered_at.clear();upstream['version']=1
    changed=await dispatch(handler,'taikoupdate all',platform,target=False)
    current,histories=publication();assert len(histories)==2 and len(histories[-1]['songs'])==1,histories[-1].keys()
    observations.append((first,initial,changed,current,histories,copy.deepcopy(render_calls)))
    before=publication();taiko_update_cooldown._last_triggered_at.clear();upstream['fail']=True
    failed=await dispatch(handler,'taikoupdate',platform,target=False)
    assert '更新失败' in str(failed) and publication()==before,failed
   assert observations[0]==observations[1],platform
   results.append({'platform':platform,'native_current_history_first_hot_incremental_failure_parity':True})
  update_user.getUserData=original_sync;draw_dress.render_update_changes_image=original_render
  # Exercise the unchanged real update layout with captured Source inputs.
  from taiko_bot.runtime.player.center import custom_title,title_catalog
  custom_title.get_taiko_db_connection=db.connect;custom_title._schema_ready=True
  with sqlite3.connect(db.path) as connection:
   connection.execute('CREATE TABLE taiko_custom_titles(id INTEGER,title_name TEXT,title_key TEXT,song_id INTEGER,difficulty_level INTEGER,creator_type TEXT,creator_id TEXT,creator_name TEXT,source TEXT,group_id TEXT,group_name TEXT,created_at TEXT,updated_at TEXT,achievement_type TEXT)')
  title_catalog.requests=types.SimpleNamespace(post=lambda *args,**kwargs:Response({'data':{'list':[]}}))
  legacy_draw=frozen(draw_dress,'draw_dress.py')
  store=PublicationStore(a.work/'userdata','11111')
  with store.shared():
   view=store.reader()
   before=legacy_draw['render_update_changes_image'](11111,show_all=True,score_view=view)
   after=original_render(11111,show_all=True,score_view=view)
  assert isinstance(after,bytes) and len(after)>1000 and before==after
  results.append({'real_update_image':normalized(after)})

 else:
  from taiko_bot import viewer_client
  original_request=viewer_client._request_json
  def remote(method,url,**kwargs):
   requests.append((method,url,kwargs.get('json_payload')))
   return {'taikoId':'11111','source':'wahlap','userdata':copy.deepcopy(payload),'imageBase64':base64.b64encode(png).decode()}
  viewer_client._request_json=remote
  for platform in ['onebot','qq']:
   reset();before=await dispatch(old['update'],'taikoupdate all',platform,target=False)
   reset();after=await dispatch(updates.update,'taikoupdate all',platform,target=False)
   assert before==after and hashlib.sha256(png).hexdigest() in str(after),(before,after)
   results.append({'platform':platform,'remote_update_image_parity':True})
  viewer_client._request_json=original_request
 assert not violations,violations
 (a.work/'update-events.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(a.host,len(results),'update events PASS',flush=True)
asyncio.run(update_main())
