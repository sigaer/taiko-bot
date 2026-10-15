"""Check transferred lock/transaction/publication algorithms against frozen source."""
import ast
import sys
from pathlib import Path
baseline,owned=map(Path,sys.argv[1:])
class NormalizePaths(ast.NodeTransformer):
 def visit_Constant(self,node):
  if isinstance(node.value,str) and node.value.startswith('/home/sigaer/taiko/'):
   return ast.Constant(value=node.value.removeprefix('/home/sigaer/taiko/'))
  return node
 def visit_Call(self,node):
  # Only deployment root configuration changed, not any persistent protocol.
  if isinstance(node.func,ast.Name) and node.func.id=='str' and len(node.args)==1:
   expr=node.args[0]
   if isinstance(expr,ast.BinOp) and isinstance(expr.left,ast.Call) and isinstance(expr.left.func,ast.Name) and expr.left.func.id=='_runtime_root':return expr.right
  return self.generic_visit(node)
count=0
for name in ['native_wahlap_update.py','bot_qq_migration.py','score_token_authority.py','source_mutation.py','userdata_storage.py','update_user.py','hiroba/native_binding.py','hiroba/private_credentials.py','hiroba/sync.py']:
 old=ast.parse((baseline/name).read_text());new=ast.parse((owned/name).read_text())
 olddefs={n.name:n for n in old.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
 for node in new.body:
  if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):continue
  assert node.name in olddefs,(name,node.name)
  before=ast.dump(NormalizePaths().visit(olddefs[node.name]),include_attributes=False)
  after=ast.dump(NormalizePaths().visit(node),include_attributes=False)
  assert before==after,(name,node.name)
  count+=1
print(count,'transferred protocol definitions unchanged PASS')
