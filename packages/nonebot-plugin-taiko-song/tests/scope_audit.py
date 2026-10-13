from pathlib import Path
import ast,subprocess,json,hashlib
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--workspace',type=Path,required=True)
b=parser.parse_args().workspace;a=b/'application';s=b/'sakura'
def read(repo,ref,path):return subprocess.check_output(['git','show',ref+':'+path],cwd=repo,text=True)
def definitions(text):
 out={}
 for i,n in enumerate(ast.parse(text).body):
  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
   key=n.name if n.name!='_' else tuple(ast.unparse(d) for d in n.decorator_list)
   out[key]=ast.dump(n,include_attributes=False)
 return out
results={}
for host,repo,ref,path in [('center',s,'c8ed8c1','taiko/plugins/taiko.py'),('client',a,'5f8465f','plugins/taiko.py')]:
 old=definitions(read(repo,ref,path));new=definitions((repo/path).read_text())
 removed=[str(k) for k in old.keys()-new.keys()]
 changes=[str(k) for k in old.keys()&new.keys() if old[k]!=new[k]]
 assert not changes,changes
 assert not new.keys()-old.keys()
 assert len(removed)==3,removed
 results[host]={'unchanged_functions_and_classes':len(new),'removed':removed}
subprocess.run(['git','merge-base','--is-ancestor','5f8465f','HEAD'],cwd=a,check=True)
assert (a/'taiko_runtime/send_authority.py').read_text()==read(a,'5f8465f','taiko_runtime/send_authority.py')
results['client']['send_authority_helper_unchanged']=True
results['client']['send_auth_calls']=(a/'plugins/taiko.py').read_text().count('await _require_private_send_authority(')
assert results['client']['send_auth_calls']==35
files=subprocess.check_output(['git','ls-tree','-r','--name-only','44aaf656','packages/taiko-application'],cwd=a,text=True).splitlines()
for f in files:assert (a/f).read_text()==read(a,'44aaf656',f),f
results['application']={'version':'0.5.0','unchanged_files':len(files),'reference':'44aaf656'}
for host in ('center','client'):
 results[host]['reference_sha256']=hashlib.sha256((b/(host+'-reference.py')).read_bytes()).hexdigest()
print(json.dumps(results,ensure_ascii=False))
(b/'evidence/scope-audit.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
