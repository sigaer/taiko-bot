"""Cold/hot/update/delete rebuild parity against actual frozen Host functions."""
from importlib import import_module
writes=[]
def audit_writes(event,args):
 if event=='open' and len(args)>2 and isinstance(args[0],(str,os.PathLike)) and str(args[0]).endswith('taiko_goku_onis.json') and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):writes.append(str(args[0]))
sys.addaudithook(audit_writes)
new_data=import_module(f'taiko_bot.runtime.player.{a.host}.score_data')
new_owner=import_module('taiko_bot.runtime.player.center.recommendation_support.score_line') if a.host=='center' else new_data

def exercise(label,owner,data,points):
 root=a.work/('dataset-'+label);root.mkdir(exist_ok=True)
 for name in ('song_score.json','song_data.json','taiko_goku_all_levels_stream.json','song_data_with_roll.json'):
  shutil.copyfile(a.work/'songs'/name,root/name)
 for attr,name in [('SCORE_PATH','song_score.json'),('SONG_DATA_PATH','song_data.json'),('ALL_LEVELS_STREAM_PATH','taiko_goku_all_levels_stream.json'),('ROLL_PATH','song_data_with_roll.json'),('UNIFIED_PATH','taiko_goku_onis.json')]:
  if hasattr(owner,attr):setattr(owner,attr,root/name)
 if a.host=='client':owner.rebuild_scoreline_dataset.__defaults__=(owner.UNIFIED_PATH,)
 owner._load_scoreline_data.cache_clear();owner._build_chart_index.cache_clear()
 if label=='old':ns['JSON_PATH']=owner.UNIFIED_PATH
 else:data.JSON_PATH=owner.UNIFIED_PATH
 owner.UNIFIED_PATH.unlink(missing_ok=True)
 steps=[]
 def step(name,call):
  before=len(writes)
  try:value=call()
  except Exception as error:value={'error':type(error).__name__} # Paths differ between fixture roots.
  steps.append(dict(step=name,value=value,writes=len(writes)-before))
 def lookup():
  row=data.get_scoreline_entry(10000,4)
  return row['initial_points'] if row else None
 step('cold',lookup)
 first=owner.UNIFIED_PATH.read_bytes();assert json.loads(first) and first.endswith(b'\n')
 step('hot',lookup)
 rows=json.loads(owner.SCORE_PATH.read_text())
 for row in rows:row['initial_points']+=100
 owner.SCORE_PATH.write_text(json.dumps(rows))
 source_ns=max(owner.SCORE_PATH.stat().st_mtime_ns,owner.UNIFIED_PATH.stat().st_mtime_ns+1)
 os.utime(owner.SCORE_PATH,ns=(source_ns,source_ns))
 step('source-updated-index',lookup)
 step('source-updated-points',lambda:points(10000,500,100,20,level=4))
 step('index-after-points',lookup)
 owner._build_chart_index.cache_clear();owner._load_scoreline_data.cache_clear()
 step('cache-cleared',lookup)
 owner.UNIFIED_PATH.unlink()
 step('missing-output-hot-index',lookup)
 step('missing-output-points',lambda:points(10000,500,100,20,level=4))
 owner.SCORE_PATH.unlink()
 step('missing-source-hot-index',lookup)
 step('missing-source-points',lambda:points(10000,500,100,20,level=4))
 # A fresh process may enter through 查分 before any index lookup.
 shutil.copyfile(a.work/'songs/song_score.json',owner.SCORE_PATH)
 owner.UNIFIED_PATH.unlink(missing_ok=True)
 loader=ns['_load_score_json'] if label=='old' else data._load_score_json
 loader.cache_clear();owner._load_scoreline_data.cache_clear();owner._build_chart_index.cache_clear()
 step('points-cold',lambda:points(10000,500,100,20,level=4))
 step('points-hot',lambda:points(10000,500,100,20,level=4))
 owner.SCORE_PATH.unlink()
 step('points-hot-missing-source',lambda:points(10000,500,100,20,level=4))
 return steps,hashlib.sha256(first).hexdigest()
old=exercise('old',old_data,old_data,ns['compute_score'])
new_result=exercise('new',new_owner,new_data,new_data.compute_score)
assert old==new_result,(old,new_result)
assert old[0][0]['writes']==1 and old[0][1]['writes']==0,old
assert old[0][2]['writes']==(1 if a.host=='center' else 0),old
assert old[0][3]['writes']==(0 if a.host=='center' else 1),old
assert old[0][-3]['writes']==1 and old[0][-2]['writes']==0 and old[0][-1]['writes']==0,old
assert not violations,violations
(a.work/'datasets.json').write_text(json.dumps(dict(host=a.host,steps=old[0],cold_sha256=old[1]),ensure_ascii=False,indent=2))
print(a.host,'dataset cold/hot/update/delete/missing-source PASS',flush=True)
