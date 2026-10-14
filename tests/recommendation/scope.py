"""Bounded static ownership and protected-scope audit, without runtime imports."""
import ast
import json
import subprocess
import sys
from pathlib import Path
bot, sakura = map(Path,sys.argv[1:])
report={}
for root,base,path in ((bot,'c11cdf7','plugins/taiko.py'),(sakura,'6ca9b1f','taiko/plugins/taiko.py')):
    before=subprocess.check_output(['git','-C',str(root),'show',f'{base}:{path}'],text=True)
    after=(root/path).read_text()
    def functions(text):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name!='taikorec_handle'}
    assert functions(before)==functions(after),'non-target handler changed'
    tree=ast.parse(after)
    assert not any(getattr(n,'name',None)=='taikorec_handle' for n in tree.body)
    assert not any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='taikorec' for t in n.targets) for n in tree.body)
    paths=subprocess.check_output(['git','-C',str(root),'diff','--name-only',base],text=True).splitlines()
    assert not any(p.startswith(('taiko_store/','taiko/taiko_store/','taiko_viewer/','taiko/taiko_viewer/','packages/sakura-taiko-core/')) or p.endswith('.sql') for p in paths)
    report[path+':'+root.name]={'old_entry_count':0,'unchanged_other_handlers':len(functions(after))}
for path in (bot/'taiko_bot/runtime/player').glob('*/recommendation_support/*.py'):
    text=path.read_text()
    tree=ast.parse(text)
    for n in ast.walk(tree):
        if isinstance(n,ast.ImportFrom):
            assert not any(word in (n.module or '') for word in ('plugins','userdata_provider','taiko_store')),str(path)
        if isinstance(n,ast.Name):
            assert n.id not in {'get_cached_userdata','read_current_json','store_measurement','score_read_view'},str(path)
report['support']='no private readers, Writer or Sakura imports'
print(json.dumps(report,ensure_ascii=False,indent=2))
