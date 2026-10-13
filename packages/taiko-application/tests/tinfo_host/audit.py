"""Audit reachable owned imports, including package initializers, not all modules on disk."""
import ast
import hashlib
import importlib.util
from pathlib import Path


def forbidden(name):
    return any(part in {'taiko_store','merged_bind','plugins','host_fixture','oracle'}
               or 'userdata' in part.lower() or 'writer' in part.lower()
               for part in name.split('.'))


def audit_graph(sources):
    pending=['taiko_application.commands.score', 'taiko_application.private_input']
    visited=set()
    edges=[]
    while pending:
        name=pending.pop()
        if name in visited: continue
        visited.add(name)
        text,is_package=sources[name]
        for i in range(1,len(name.split('.'))):
            parent='.'.join(name.split('.')[:i])
            if parent in sources and parent not in visited: pending.append(parent)
        package=name if is_package else name.rpartition('.')[0]
        for n in ast.walk(ast.parse(text)):
            targets=[]
            if isinstance(n,ast.Import): targets=[a.name for a in n.names]
            elif isinstance(n,ast.ImportFrom):
                module=importlib.util.resolve_name('.'*n.level+(n.module or ''),package) if n.level else (n.module or '')
                targets=[module]+[module+'.'+a.name for a in n.names]
            elif isinstance(n,ast.Call) and (
                isinstance(n.func,ast.Name) and n.func.id in {'__import__','eval','exec'}
                or isinstance(n.func,ast.Attribute) and n.func.attr=='import_module'):
                raise AssertionError('Unresolved dynamic import/execution in '+name)
            for target in targets:
                if forbidden(target): raise AssertionError('Forbidden import: '+target)
                edges.append([name,target])
                if target in sources and target not in visited: pending.append(target)
    return {'modules':sorted(visited),'edges':edges}



def main():
    import argparse, json, subprocess
    parser=argparse.ArgumentParser()
    parser.add_argument('--application',type=Path,required=True)
    parser.add_argument('--sakura',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    app=args.application/'packages/taiko-application/src/taiko_application'
    sources={}
    paths={}
    for path in app.rglob('*.py'):
        parts=list(path.relative_to(app).with_suffix('').parts)
        package=parts[-1]=='__init__'
        if package: parts.pop()
        name='.'.join(['taiko_application']+parts)
        sources[name]=(path.read_text(),package)
        paths[name]=path
    graph=audit_graph(sources)
    poisoned=dict(sources)
    poisoned['taiko_application.commands.prepared_score']=('from bridge import execute',False)
    poisoned['bridge']=('from taiko_store import PublicationStore',False)
    try: audit_graph(poisoned)
    except AssertionError: pass
    else: raise AssertionError('Negative control failed')
    graph['negative_control']='PASS'
    graph['sha256']={name:hashlib.sha256(paths[name].read_bytes()).hexdigest() for name in graph['modules']}
    untouched={}
    old_files=subprocess.check_output(['git','ls-tree','-r','--name-only','e90fafd','taiko/taiko_store','taiko/plugins/utils/bot_binding_mutation.py','taiko/plugins/utils/bot_binding_authority.py','taiko/taiko_runtime/platform_adapter.py'],cwd=args.sakura,text=True).splitlines()
    for name in old_files:
        old=subprocess.check_output(['git','show','e90fafd:'+name],cwd=args.sakura)
        actual=(args.sakura/name).read_bytes()
        assert actual==old, name
        untouched[name]=hashlib.sha256(actual).hexdigest()
    ast_counts={}
    for name,allowed in [('taiko/plugins/taiko.py',{'music_info_handle'}),('taiko/plugins/utils/drawinfo.py',set())]:
        old=subprocess.check_output(['git','show','e90fafd:'+name],cwd=args.sakura,text=True)
        def nodes(text):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(text).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        before,after=nodes(old),nodes((args.sakura/name).read_text())
        for key,value in before.items():
            if key not in allowed: assert after[key]==value,key
        ast_counts[name]=len(before)-len(allowed)
    # Original client command/authority files remain byte-identical.
    for name in ('plugins/taiko.py','taiko_runtime/send_authority.py'):
        old=subprocess.check_output(['git','show','a7ddece:'+name],cwd=args.application)
        assert (args.application/name).read_bytes()==old
        untouched['client/'+name]=hashlib.sha256(old).hexdigest()
    score_path='packages/taiko-application/src/taiko_application/commands/score.py'
    previous=subprocess.check_output(['git','show','a7ddece:'+score_path],cwd=args.application,text=True)
    def score_nodes(text):
        return {node.name:node for node in ast.parse(text).body if isinstance(node,(ast.ClassDef,ast.FunctionDef))}
    before=score_nodes(previous)
    after=score_nodes((args.application/score_path).read_text())
    assert ast.dump(before['ScorePorts'])==ast.dump(after['ScorePorts'])
    assert [ast.dump(node) for node in before['execute_score'].body]==[ast.dump(node) for node in after['execute_score'].body[2:]]
    # Public implementation and all other Application implementations remain frozen.
    names=subprocess.check_output(['git','ls-tree','-r','--name-only','a7ddece','packages/taiko-application/src','packages/nonebot-plugin-taiko-song/src'],cwd=args.application,text=True).splitlines()
    count=0
    for name in names:
        if name in (score_path,'packages/taiko-application/src/taiko_application/__init__.py'):
            continue
        expected=subprocess.check_output(['git','show','a7ddece:'+name],cwd=args.application)
        assert (args.application/name).read_bytes()==expected,name
        count+=1
    ast_counts['application_legacy_score_branch']='unchanged'
    ast_counts['application_and_public_unchanged_files']=count
    data={'graph':graph,'untouched':untouched,'unchanged_ast_counts':ast_counts}
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'modules':len(graph['modules']),'untouched_files':len(untouched),'unchanged_ast':ast_counts}))

if __name__=='__main__':
    main()
