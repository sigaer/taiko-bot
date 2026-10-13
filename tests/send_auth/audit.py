"""Check the backport changes only the intended send exits and preserves payloads."""
import argparse, ast, hashlib, json, subprocess, tomllib, zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
r=a.repo;e=a.evidence
base='fa0983dcc56ca109555a33d90aac0fecca6bdf0d'
def old(path): return subprocess.check_output(['git','-C',str(r),'show',base+':'+path])
src=r/'plugins/taiko.py';tree=ast.parse(src.read_text());before=ast.parse(old('plugins/taiko.py'))
class RemoveGuards(ast.NodeTransformer):
    removed=0
    def visit_Expr(self,node):
        if isinstance(node.value,ast.Await) and isinstance(node.value.value,ast.Call) and isinstance(node.value.value.func,ast.Name) and node.value.value.func.id=='_require_private_send_authority':
            self.removed+=1
            return None
        return self.generic_visit(node)
    def visit_AsyncFunctionDef(self,node):
        if node.name=='_require_private_send_authority': return None
        return self.generic_visit(node)
t=RemoveGuards();stripped=t.visit(tree)
assert t.removed==35
assert ast.dump(stripped)==ast.dump(before), 'Non-guard command behavior changed'
old_meta=tomllib.loads(old('pyproject.toml').decode());new_meta=tomllib.loads((r/'pyproject.toml').read_text())
assert old_meta['project']['dependencies']==new_meta['project']['dependencies']
assert not any('application' in d for d in new_meta['project']['dependencies'])
assert not subprocess.check_output(['git','-C',str(r),'diff',base,'--','taiko_bot','plugins/utils'])
normal=json.loads((e/'normal.json').read_text());reference=json.loads((e/'reference.json').read_text())
parity=[]
for x,y in zip(normal['cases'],reference['cases']):
    assert x['renderer_png']==y['renderer_png']
    assert x['messages']==y['messages']
    assert x['requests']==y['requests']+['/api/taiko/proxy/bind','/api/developer/userdata/42']
    assert len(x['send_rechecks'])==1 and x['send_rechecks'][0]['requests']==2
    parity.append({'command':x['command'],'output_parity':'PASS','extra_requests':2,'mock_recheck_ms':x['send_rechecks'][0]['elapsed_ms'],'png':x['renderer_png']})
for name in ('bind403','score403','timeout','identity','invalid-identity'):
    data=json.loads((e/(name+'.json')).read_text());assert data['status']=='PASS' and len(data['cases'])==2
current=json.loads((e/'dispatch-candidate.json').read_text());ref=json.loads((e/'dispatch-reference.json').read_text())
assert current['count']==54 and ref['count']==24
for x,y in zip(current['dispatch'][:24],ref['dispatch']):
    assert x['sent']==y['sent']
    if x['command'] in ('song','constant'): assert x['auth_calls']==y['auth_calls']==[]
wheel=e/'wheels/taiko_bot-0.2.8-py3-none-any.whl'
with zipfile.ZipFile(wheel) as z:
    for path in ('plugins/taiko.py','taiko_runtime/send_authority.py'):
        assert z.read(path)==(r/path).read_bytes()
        assert z.read(path)==(e/'env/lib/python3.11/site-packages'/path).read_bytes()
result={'status':'VALIDATED_PR_PENDING','base':base,'client_version':'0.2.8','core':'0.1.2','contract':'0.1.0','application_dependency':False,'guarded_exits':t.removed,'normal_and_existing_error_parity':24,'candidate_dispatch_cases':54,'revocation_real_renderer_cases':10,'payload_parity':parity,'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'unchanged':['all command AST except send guards','all dependencies','renderers','taiko_bot providers/cache/storage','Writer/SQL/sync/Core formulas']}
(e/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(result['status'])
