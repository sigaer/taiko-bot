"""Read-only ownership and forbidden-scope checks; no host initialization."""
import ast,json,subprocess,sys
from pathlib import Path
T,S=map(Path,sys.argv[1:])
for root,prefix in ((T,''),(S,'taiko/')):
 path=root/prefix/'plugins/taiko.py'
 tree=ast.parse(path.read_text())
 assert not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='taikob_handle' for n in tree.body)
 assert not any(isinstance(n,ast.Name) and n.id=='taikob' and isinstance(n.ctx,ast.Store) for n in ast.walk(tree))
 for name in ('b30_render','b30_single'):assert not (root/prefix/'plugins/utils'/f'{name}.py').exists()
 changes=subprocess.check_output(['git','diff','HEAD','--name-only'],cwd=root,text=True).splitlines()
 protected=('packages/taiko-application/','taiko_store/','taiko/taiko_store/','taiko_viewer/','taiko/taiko_runtime/','taiko_bot/domain.py','taiko_bot/userdata_provider.py')
 assert not any(path.startswith(protected) for path in changes),changes
for host in ('center','client'):
 for path in (T/f'taiko_bot/runtime/player/{host}/b30_support').glob('*.py'):
  text=path.read_text();tree=ast.parse(text)
  for node in ast.walk(tree):
   if isinstance(node,ast.ImportFrom):
    assert not (node.module or '').startswith(('plugins','taiko_runtime','taiko_store','requests','httpx','taiko_bot.userdata_provider')),path
   if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
    assert node.func.id not in {'get_cached_userdata','ensure_userdata_available','ensure_userdata_view_available','score_read_view','load_v2_snapshot','read_current_json','render_user_dress'},(path,node.func.id)
# Verify the final wheel has neither stale build copies nor missing owned source.
import zipfile
wheel=T.parent/'wheels/taiko_bot-0.6.0-py3-none-any.whl'
if wheel.exists():
 with zipfile.ZipFile(wheel) as archive:
  names=set(archive.namelist())
  assert not names & {'plugins/utils/b30_render.py','plugins/utils/b30_single.py','plugins/utils/taikob_v2.py'}
  for path in (T/'taiko_bot/runtime/player').rglob('*.py'):
   name=path.relative_to(T).as_posix()
   assert name in names and archive.read(name)==path.read_bytes(),name
print(json.dumps({'old_center_entry':0,'old_client_entry':0,'protected_changes':0,'renderer_private_loaders':0,'final_wheel_checked':wheel.exists()}))
