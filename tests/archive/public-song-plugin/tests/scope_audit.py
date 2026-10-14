"""Finite ownership/security audit against the Phase 2F-A baselines."""
from pathlib import Path
import ast, subprocess, json, hashlib, argparse
parser=argparse.ArgumentParser()
parser.add_argument('--workspace',type=Path,required=True)
b=parser.parse_args().workspace;a=b/'application';s=b/'sakura'
names={'alias_query','song_where','song_position_phrase','song_pos_by_id','diff_by_id','note_count'}
helpers={'render_alias_image','find_aliases_by_song_id','_strip_song_query_diff_prefix','_finish_song_position_by_name','_finish_song_position_by_id'}
client_orphans={'_resolve_what_song_query','_finish_fuzzy_query_with_fumen','_get_fumen_path','_finish_with_image_fallback','_send_fumen_or_hint'}
def read(repo,ref,path):return subprocess.check_output(['git','show',ref+':'+path],cwd=repo,text=True)
def definitions(text):
 out={}
 for n in ast.parse(text).body:
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
   key=n.name if n.name!='_' else tuple(ast.unparse(d) for d in n.decorator_list)
   out[key]=n
 return out
results={}
for host,repo,ref,path in [('center',s,'241a237','taiko/plugins/taiko.py'),('client',a,'c5ef227','plugins/taiko.py')]:
 before=read(repo,ref,path);after=(repo/path).read_text();old=definitions(before);new=definitions(after)
 removed=[str(k) for k in old.keys()-new.keys()]
 changes=[str(k) for k in old.keys()&new.keys() if ast.dump(old[k])!=ast.dump(new[k])]
 assert not changes,changes
 assert not new.keys()-old.keys()
 for key in old.keys()-new.keys():
  n=old[key]
  assert n.name in helpers|(client_orphans if host=='client' else set()) or any(any(x+'.handle' in ast.unparse(d) for x in names) for d in n.decorator_list),key
 assert len(removed)==(11 if host=='center' else 16),removed
 assert not (repo/Path(path).parent/'utils/song_position.py').exists()
 # utils aggregate loses only the orphaned note query; all other definitions unchanged.
 up=str(Path(path).parent/'utils/__init__.py');uo=definitions(read(repo,ref,up));un=definitions((repo/up).read_text())
 assert uo.keys()-un.keys()=={'find_by_volume'}
 assert {k:ast.dump(n) for k,n in un.items()}=={k:ast.dump(n) for k,n in uo.items() if k!='find_by_volume'}
 def regs(text):
  return {ast.unparse(n.targets[0]):ast.dump(n) for n in ast.parse(text).body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id.startswith('on_')}
 ro=regs(before);rn=regs(after)
 assert ro.keys()-rn.keys()==names
 assert {k:v for k,v in ro.items() if k not in names}==rn
 diff=subprocess.check_output(['git','diff','--numstat',ref,'--',path,up,str(Path(path).parent/'utils/song_position.py')],cwd=repo,text=True)
 results[host]={'reference':ref,'unchanged_functions_and_classes':len(new),'removed_definitions':sorted(removed),'removed_matchers':sorted(names),'remaining_matchers':sorted(rn),'code_numstat':diff,'reference_sha256':hashlib.sha256(before.encode()).hexdigest()}
subprocess.run(['git','merge-base','--is-ancestor','5f8465f','HEAD'],cwd=a,check=True)
assert (a/'taiko_runtime/send_authority.py').read_text()==read(a,'5f8465f','taiko_runtime/send_authority.py')
assert (a/'plugins/taiko.py').read_text().count('await _require_private_send_authority(')==35
results['client'].update(send_authority_helper_unchanged=True,send_auth_calls=35,private_handlers_unchanged=True)
files=subprocess.check_output(['git','ls-tree','-r','--name-only','44aaf656','packages/taiko-application'],cwd=a,text=True).splitlines()
for f in files:assert (a/f).read_text()==read(a,'44aaf656',f),f
results['application']={'version':'0.5.0','unchanged_files':len(files),'reference':'44aaf656'}
path='taiko/plugins/utils/duplicate_versions.py'
uo=definitions(read(s,'241a237',path));un=definitions((s/path).read_text())
assert uo.keys()-un.keys()=={'alias_entry_for_song_id'}
assert {k:ast.dump(n) for k,n in un.items()}=={k:ast.dump(n) for k,n in uo.items() if k!='alias_entry_for_song_id'}
results['center']['additional_orphan_removed']='duplicate_versions.alias_entry_for_song_id'

plugin=a/'packages/nonebot-plugin-taiko-song/src/nonebot_plugin_taiko_song'
for file in plugin.glob('*.py'):
 for n in ast.walk(ast.parse(file.read_text())):
  if isinstance(n,ast.Import):modules=[x.name for x in n.names]
  elif isinstance(n,ast.ImportFrom):modules=[n.module or ''] if n.level==0 else []
  else:continue
  assert not any(m=='plugins' or m.startswith('plugins.') or 'sakura_bot' in m.lower() for m in modules),(file,modules)
for f in ('center_messages.py','client_messages.py','delivery.py'):
 path=str((plugin/f).relative_to(a));assert (a/path).read_text()==read(a,'c5ef227',path),f
results['transport']={'unchanged_files':['center_messages.py','client_messages.py','delivery.py'],'new_platform_frameworks':0}
(b/'evidence/scope-audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps({'status':'PASS','center_remaining':len(results['center']['remaining_matchers']),'client_remaining':len(results['client']['remaining_matchers']),'send_auth_calls':35}))
