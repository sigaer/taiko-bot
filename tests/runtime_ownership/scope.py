"""Mechanical storage and non-target source scope checks; no runtime IO."""
import ast, hashlib, json, subprocess, sys
from pathlib import Path
A,S=map(Path,sys.argv[1:3]);report={}
def old(root,commit,path):return subprocess.check_output(['git','show',commit+':'+path],cwd=root)
def digest(b):return hashlib.sha256(b).hexdigest()
for name in ('publication','reader','merged_materialization','backup','bridge','daily','__init__'):
 before=old(S,'86a308c','taiko/taiko_store/'+name+'.py');after=(A/'taiko_store'/ (name+'.py')).read_bytes()
 assert before==after,name
 report['storage/'+name]=digest(after)
for name in ('merged_read','merge_reference'):
 def body(b):return [ast.dump(n,include_attributes=False) for n in ast.parse(b).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
 assert body(old(S,'86a308c','taiko/taiko_store/'+name+'.py'))==body((A/'taiko_store'/ (name+'.py')).read_bytes())
 report['storage/'+name]='functions/classes unchanged; imports/reference root only'
assert old(S,'86a308c','taiko/plugins/utils/snapshot_history.py')==(A/'taiko_store/snapshot_history.py').read_bytes()
for root,commit,prefix in [(A,'1e7d0f9',''),(S,'86a308c','taiko/')]:
 def nodes(b):
  out={}
  for n in ast.parse(b).body:
   name=getattr(n,'name',None)
   if isinstance(n,ast.Assign):name=ast.unparse(n.targets[0])
   if name:out[name]=ast.dump(n,include_attributes=False)
  return out
 before=nodes(old(root,commit,prefix+'plugins/taiko.py'));after=nodes((root/(prefix+'plugins/taiko.py')).read_bytes())
 removed={'music_info','music_info_handle','_extract_music_info_command_match','_music_info_command_rule','MUSIC_INFO_COMMAND_RE'}
 assert not removed & after.keys()
 assert {k:v for k,v in before.items() if k not in removed}==after
 def sequence(b):
  return [ast.dump(n,include_attributes=False) for n in ast.parse(b).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name not in removed]
 assert sequence(old(root,commit,prefix+'plugins/taiko.py'))==sequence((root/(prefix+'plugins/taiko.py')).read_bytes())
 report[('client' if root==A else 'center')+'/non-target']=len(after)
assert not (S/'taiko/plugins/utils/tinfo_provider.py').exists()
assert not (S/'taiko/taiko_store').exists()
assert not (A/'packages/nonebot-plugin-taiko-song/pyproject.toml').exists()
for path in (A/'taiko_bot/runtime').rglob('*.py'):
 for n in ast.walk(ast.parse(path.read_text())):
  if isinstance(n,ast.ImportFrom):assert not (n.module or '').startswith('plugins'),path
  if isinstance(n,ast.Import):assert not any(x.name.startswith('plugins') for x in n.names),path
for name in ('_read','_entry','_Row','BotBindingMutationUnavailable'):
 def item(text,name):return next(ast.dump(n,include_attributes=False) for n in ast.parse(text).body if getattr(n,'name',None)==name)
 assert item(old(S,'86a308c','taiko/plugins/utils/bot_binding_mutation.py'),name)==item((A/'taiko_bot/runtime/player/center/bot_binding_mutation.py').read_bytes(),name)
assert item(old(S,'86a308c','taiko/plugins/utils/tinfo_provider.py'),'TinfoHostProvider')==item((A/'taiko_bot/runtime/player/center/tinfo_provider.py').read_bytes(),'TinfoHostProvider')
assert item(old(S,'86a308c','taiko/plugins/utils/tinfo_provider.py'),'AuthorizedDelivery')==item((A/'taiko_bot/runtime/player/authority.py').read_bytes(),'AuthorizedDelivery')
report['native_provider_and_sql_read_ast']='unchanged'
for path in (A/'taiko_bot/runtime/public').glob('*.py'):
 assert path.read_bytes()==old(A,'1e7d0f9','packages/nonebot-plugin-taiko-song/src/nonebot_plugin_taiko_song/'+path.name)
report['public_modules']='all byte-identical moves'
report['reverse_sakura_imports']=0
print(json.dumps(report,indent=2))
