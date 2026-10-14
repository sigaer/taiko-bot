"""Static ownership and protected-scope check, without private data access."""
import ast,json,subprocess,sys
from pathlib import Path
bot,sakura=map(Path,sys.argv[1:])
removed={'_extract_progress_command_match','_progress_command_rule','_load_progress_name_set','_load_decimal_progress_set','_load_pass_progress_set','_load_star_progress_set','_parse_star_progress_value'}
report={}
for root,base,path in ((bot,'66b60ee','plugins/taiko.py'),(sakura,'f49b205','taiko/plugins/taiko.py')):
 before=subprocess.check_output(['git','-C',str(root),'show',f'{base}:{path}'],text=True)
 after=(root/path).read_text()
 def functions(text):
  return [ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name not in removed and not any(ast.unparse(d)=='matcher.handle()' for d in n.decorator_list)]
 assert functions(before)==functions(after),'unrelated handler changed'
 tree=ast.parse(after)
 assert not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='matcher' for t in n.targets) for n in tree.body)
 assert not any(isinstance(n,ast.AsyncFunctionDef) and any(ast.unparse(d)=='matcher.handle()' for d in n.decorator_list) for n in tree.body)
 paths=subprocess.check_output(['git','-C',str(root),'diff','--name-only',base],text=True).splitlines()
 assert not any(p.startswith(('taiko_store/','taiko/taiko_store/','taiko_viewer/','taiko/taiko_viewer/','packages/sakura-taiko-core/','packages/sakura-taiko-contract/')) or p.endswith('.sql') for p in paths)
 report[root.name]={'old_matcher_count':0,'unchanged_other_functions':len(functions(after))}
for path in (bot/'taiko_bot/runtime/player').glob('*/progress_support/*.py'):
 for n in ast.walk(ast.parse(path.read_text())):
  if isinstance(n,ast.ImportFrom):assert not any(x in (n.module or '') for x in ('plugins','userdata_provider','taiko_store')),str(path)
  if isinstance(n,ast.Name):assert n.id not in {'get_cached_userdata','ensure_userdata_view_available','read_current_json','USERDATA_DIR'},str(path)
report['private_reads']='Host Provider only; no private or legacy imports in render support'
print(json.dumps(report,ensure_ascii=False,indent=2))
