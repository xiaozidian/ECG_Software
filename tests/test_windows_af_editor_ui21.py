"""The asynchronous current dialog guard adds readiness without removing prior checks."""
import ast
import copy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_current_AF_helper_preserves_all_original_clinician_and_undo_assertions():
    old=ast.parse((ROOT/'scripts/verify_windows_af_editor_ui19.py').read_text())
    new=ast.parse((ROOT/'scripts/verify_windows_af_editor_ui21.py').read_text())
    old_fn=next(n for n in old.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='verify_af_editor')
    new_fn=copy.deepcopy(next(n for n in new.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='verify_af_editor'))
    removed=[]
    class RemoveReadiness(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Await) and isinstance(node.value.value,ast.Call):
                call=node.value.value
                if call.args and isinstance(call.args[0],ast.Constant) and str(call.args[0].value).startswith('duration=>'):
                    removed.append(call.args[0].value)
                    return None
            return self.generic_visit(node)
    new_fn=RemoveReadiness().visit(new_fn)
    assert len(removed)==1
    assert "!b.disabled" in removed[0] and "includes('整段候选')" in removed[0] and 'includes(duration)' in removed[0]
    assert ast.dump(new_fn,include_attributes=False)==ast.dump(old_fn,include_attributes=False)
