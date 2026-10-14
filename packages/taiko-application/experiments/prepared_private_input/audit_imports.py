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
    pending=['prepared_private_input.application_adapter','taiko_application.commands.score']
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


def audit():
    import taiko_application
    app=Path(taiko_application.__file__).parent
    own=Path(__file__).parent
    sources={}
    paths={}
    for root, prefix in [(app,'taiko_application'),(own,'prepared_private_input')]:
        for path in root.rglob('*.py'):
            parts=list(path.relative_to(root).with_suffix('').parts)
            package=parts[-1]=='__init__'
            if package: parts.pop()
            name='.'.join([prefix]+parts)
            sources[name]=(path.read_text(),package)
            paths[name]=path
    graph=audit_graph(sources)
    # Negative control: a forbidden dependency hidden one edge behind the renderer.
    poisoned=dict(sources)
    poisoned['prepared_private_input.render_fixture']=('from bridge_fixture import value',False)
    poisoned['bridge_fixture']=('from taiko_store import PublicationStore',False)
    try: audit_graph(poisoned)
    except AssertionError: pass
    else: raise AssertionError('Transitive negative control did not fail')
    graph['negative_control']='PASS'
    graph['sha256']={name:hashlib.sha256(paths[name].read_bytes()).hexdigest() for name in graph['modules']}
    graph['scope']='Reachable Application 0.6.0 + experiment adapter/DTO/fixture renderer, including parent __init__. Third-party imports are runtime-guarded.'
    return graph
