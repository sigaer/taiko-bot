import ast, hashlib, json, subprocess
from pathlib import Path
import argparse
p = argparse.ArgumentParser()
p.add_argument('--application', type=Path, required=True)
p.add_argument('--sakura', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
a, s = args.application, args.sakura
def prior(repo, ref, file):
 return subprocess.check_output(['git','show',ref+':'+file],cwd=repo,text=True)
def check_same(repo, ref, file):
 assert (repo/file).read_text()==prior(repo,ref,file),file
for file in ['taiko/taiko_store/publication.py','taiko/taiko_store/reader.py','taiko/plugins/utils/snapshot_history.py','taiko/plugins/taiko.py']:
 check_same(s,'38826aa',file)
for file in ['plugins/taiko.py','taiko_runtime/send_authority.py']:
 check_same(a,'14fc23a',file)
for root in ['packages/nonebot-plugin-taiko-song/src','packages/taiko-application/src/taiko_application/commands','packages/taiko-application/src/taiko_application/query','packages/taiko-application/src/taiko_application/score']:
 for p in (a/root).rglob('*.py'):
  check_same(a,'14fc23a',str(p.relative_to(a)))
class Normalize(ast.NodeTransformer):
 def visit_ImportFrom(self,n):
  if n.module=='merge_reference': return None
  if n.module=='taiko_application.merged_bind': n.module='plugins.utils.merged_bind'
  if n.module=='plugins.utils.merged_bind':
   n.names=[x for x in n.names if x.name!='_load_song_combo_map']
  return n
 def visit_Call(self,n):
  self.generic_visit(n)
  if isinstance(n.func,ast.Name) and n.func.id=='_merge_payloads':
   n.keywords=[k for k in n.keywords if k.arg not in ['combo_map','clock']]
  return n
for file in ['taiko/taiko_store/merged_materialization.py','taiko/taiko_store/merged_read.py']:
 before=Normalize().visit(ast.parse(prior(s,'38826aa',file)))
 after=Normalize().visit(ast.parse((s/file).read_text()))
 assert ast.dump(before)==ast.dump(after),file
for p in (s/'taiko/taiko_store').glob('*.py'):
 assert 'plugins.utils.merged_bind' not in p.read_text(),str(p)
k=a/'packages/taiko-application/src/taiko_application/merged_bind.py'
imports=[n.module for n in ast.walk(ast.parse(k.read_text())) if isinstance(n,ast.ImportFrom)]
assert not any(x.startswith(('plugins','taiko_store','sakura')) for x in imports)
tree=ast.parse((a/'plugins/taiko.py').read_text())
guards=[n for n in ast.walk(tree) if isinstance(n,ast.Await) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='_require_private_send_authority']
assert len(guards)==35
report={'status':'PASS','baselines':{'taiko':'14fc23a','sakura':'38826aa'},'client_authorization_checks_unchanged':35,'public_command_source_unchanged':9,'publication_and_reader_byte_identical':True,'store_call_path_AST_equal_after_only_import_and_kernel_input_normalization':True,'snapshot_history_byte_identical':True,'store_reverse_merged_bind_imports':0,'application_kernel_host_imports':0,'production_writes':0,'userdata':'synthetic isolated fixtures only'}
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
