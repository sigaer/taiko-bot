import ast
import shutil
import symtable
from pathlib import Path

# Source slicing is performed offline; generated modules are ordinary Python.
def extract(profile, source, seeds, dest):
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(exist_ok=True)
    trees={}; selected={}; imports={}; pending=list(seeds.items())
    def parse(mod):
        if mod not in trees:
            path=source/(mod.replace('.', '/')+'.py')
            text=path.read_text(); nodes=ast.parse(text).body
            index={}
            for i,node in enumerate(nodes):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    names=[node.name]
                elif isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=[x.asname or x.name.split('.')[0] for x in node.names]
                else:
                    names=[x.id for x in ast.walk(node) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Store)]
                names += [a.asname or a.name.split(".")[0] for sub in ast.walk(node) if isinstance(sub,(ast.Import,ast.ImportFrom)) for a in sub.names]
                for name in names: index.setdefault(name,[]).append(i)
            trees[mod]=(text,nodes,index)
        return trees[mod]
    missing=set()
    while pending:
        mod,wanted=pending.pop()
        text,nodes,index=parse(mod)
        keep=selected.setdefault(mod,set())
        for name in wanted:
            for i in index.get(name,[]):
                node=nodes[i]
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    aliases=imports.setdefault((mod,i),set())
                    if name in aliases: continue
                    aliases.add(name)
                    keep.add(i)
                    if isinstance(node,ast.ImportFrom) and node.level:
                        pending.append((node.module or "__init__",{a.name for a in node.names if (a.asname or a.name.split(".")[0])==name}))
                    continue
                if i in keep: continue
                keep.add(i)
                pending.append((mod,{n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}))
                for sub in ast.walk(node):
                    if isinstance(sub,ast.ImportFrom) and sub.level:
                        dep=sub.module or '__init__'
                        if not (source/(dep.replace('.','/')+'.py')).exists():
                            missing.add((mod,dep)); continue
                        pending.append((dep,{n.name for n in sub.names}))
    for mod,keep in selected.items():
        text,nodes,_=trees[mod]
        chunks=['from __future__ import annotations\n']
        for i,node in enumerate(nodes):
            if i not in keep: continue
            if isinstance(node,ast.ImportFrom) and node.module=='__future__': continue
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                node.names=[a for a in node.names if (a.asname or a.name.split('.')[0]) in imports[(mod,i)]]
                chunks.append(ast.unparse(node)); continue
            start=min([node.lineno]+[d.lineno for d in getattr(node,'decorator_list',[])])-1
            chunks.append('\n'.join(text.splitlines()[start:node.end_lineno]))
        result='\n\n'.join(chunks)+'\n'
        result=result.replace('Path("/home/sigaer/taiko")','__import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()')
        target=dest/(mod+'.py'); target.write_text(result)
    # Frozen slicing does not change the function bodies.
    print(profile, len(selected), 'modules', sum(len((dest/(m+'.py')).read_text().splitlines()) for m in selected), 'lines', 'missing',sorted(missing))
    print(sorted(selected))

def freeze(profile, baseline, dest):
    seeds={'score_calculator': {'compute_recommendations_for_user','generate_recommend_image'},
           'target_recommend': {'compute_target_recommendations_for_user','parse_target_recommendation_request','target_recommendation_displays'}}
    if profile=='center':
        seeds.update(recommend_image={'render_recommend_image_bytes'}, __init__={'render_target_recommendation_image_bytes'})
    else:
        seeds.update(target_recommend_render={'render_target_recommendation_image_bytes'})
    extract(profile, baseline/'plugins/utils', seeds, dest)
    if profile=='center':
        (dest/'__init__.py').rename(dest/'target_render.py')
    else:
        (dest/'target_recommend_render.py').rename(dest/'target_render.py')
    (dest/'__init__.py').write_text('')
    for path in dest.glob('*.py'):
        text=path.read_text().replace('Path(__file__).resolve().parents[2]', '__import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()')
        # Public-root relocation only. Private reads are separately supplied at
        # the SQL/HTTP/filesystem boundary by the synthetic fixtures.
        import re
        text=re.sub(r'(["\'])/home/sigaer/taiko/([^"\']*)\1', lambda m: 'str(_ROOT / '+repr(m[2])+')',text)
        text=text.replace('from __future__ import annotations\n','from __future__ import annotations\nfrom taiko_bot.runtime.public.config import root\n_ROOT = root()\n',1)
        path.write_text(text)
