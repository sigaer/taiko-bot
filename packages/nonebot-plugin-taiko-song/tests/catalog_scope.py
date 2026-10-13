import ast,subprocess,json,argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);b=p.parse_args().workspace
out={}
def read(repo,ref,path):return subprocess.check_output(['git','show',ref+':'+path],cwd=repo,text=True)
def funcs(s):
 return {(n.name,tuple(ast.unparse(d) for d in getattr(n,'decorator_list',[]))):ast.dump(n) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
def regs(s):
 return {ast.unparse(n.targets[0]):ast.dump(n) for n in ast.parse(s).body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id.startswith('on_')}
for host,repo,ref,prefix in [('center',b/'sakura','05437bd','taiko/'),('client',b/'application','091a6ab','')]:
 path=prefix+'plugins/taiko.py';before=read(repo,ref,path);after=(repo/path).read_text();old=funcs(before);new=funcs(after)
 removed=old.keys()-new.keys();assert len(removed)==8,removed
 assert {k:v for k,v in old.items() if k not in removed}==new
 ro=regs(before);rn=regs(after);assert ro.keys()-rn.keys()=={'const_query','patterns'}
 assert {k:v for k,v in ro.items() if k not in {'const_query','patterns'}}==rn
 assert ro['score_cmd']==rn['score_cmd']
 for f in ['plugins/utils/__init__.py','plugins/utils/score_line.py']:
  assert (repo/(prefix+f)).read_text()==read(repo,ref,prefix+f)
 assert not (repo/(prefix+'plugins/utils/const_query.py')).exists()
 out[host]={'removed':sorted(removed),'remaining_matchers':sorted(rn),'unchanged_functions':len(new),'score_cmd_and_refresh_chain_unchanged':True,'diff_numstat':subprocess.check_output(['git','diff','--numstat',ref,'--',path,prefix+'plugins/utils/const_query.py'],cwd=repo,text=True)}
a=b/'application';assert (a/'plugins/taiko.py').read_text().count('await _require_private_send_authority(')==35
assert (a/'taiko_runtime/send_authority.py').read_text()==read(a,'091a6ab','taiko_runtime/send_authority.py')
files=subprocess.check_output(['git','ls-tree','-r','--name-only','091a6ab','packages/taiko-application'],cwd=a,text=True).splitlines()
for f in files:assert (a/f).read_text()==read(a,'091a6ab',f)
plugin='packages/nonebot-plugin-taiko-song/src/nonebot_plugin_taiko_song/'
files=subprocess.check_output(['git','ls-tree','-r','--name-only','091a6ab',plugin],cwd=a,text=True).splitlines()
for f in files:
 if not f.endswith('/__init__.py'):assert (a/f).read_text()==read(a,'091a6ab',f)
for f in (a/plugin).glob('*.py'):
 for n in ast.walk(ast.parse(f.read_text())):
  if isinstance(n,ast.ImportFrom) and n.level==0:assert not (n.module or '').startswith('plugins'),f
out['guards']=35;out['old_plugin_modules_unchanged_except_registration_import']=True;out['application_unchanged']=True
(b/'evidence/catalog-scope.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print('scope PASS')
