import inspect
import sys
import ast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.action_loader import discover_actions

reg = discover_actions(Path("actions"))

print("| # | Action / Tool Name | File | Handler Function | Declared Return | Actual Return Shapes | Classification |")
print("|---|--------------------|------|------------------|-----------------|----------------------|----------------|")

for idx, (name, rec) in enumerate(sorted(reg._actions.items()), 1):
    fn = rec.handler
    sig = inspect.signature(fn)
    ret_ann = str(sig.return_annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")
    
    src = inspect.getsource(fn)
    tree = ast.parse(src)
    
    returns = [n.value for n in ast.walk(tree) if isinstance(n, ast.Return)]
    has_dict = False
    has_str = False
    has_calls = False
    call_targets = []
    
    for r in returns:
        if r is None:
            continue
        if isinstance(r, ast.Dict):
            has_dict = True
        elif isinstance(r, (ast.Constant, ast.JoinedStr)):
            has_str = True
        elif isinstance(r, ast.Call):
            has_calls = True
            call_targets.append(ast.unparse(r.func))
            
    # Also inspect called sub-functions within the module to see what they return
    mod_path = Path(f"actions/{rec.file}")
    mod_src = mod_path.read_text(encoding="utf-8")
    mod_tree = ast.parse(mod_src)
    
    # Are there sub-functions returning dicts?
    sub_returns_dict = False
    sub_returns_str = False
    for node in mod_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in [c.split(".")[-1] for c in call_targets]:
            for sn in ast.walk(node):
                if isinstance(sn, ast.Return) and sn.value:
                    if isinstance(sn.value, ast.Dict):
                        sub_returns_dict = True
                    elif isinstance(sn.value, (ast.Constant, ast.JoinedStr)):
                        sub_returns_str = True
                        
    actual_dict = has_dict or sub_returns_dict
    actual_str = has_str or sub_returns_str
    
    if actual_dict and actual_str:
        shape_desc = "Dict & String"
        category = "Inconsistent / Mixed"
    elif actual_dict:
        shape_desc = "Structured Dict (`{success, ...}`)"
        category = "Structured Dict (Phase 1/2)"
    else:
        shape_desc = "Plain String (`str`)"
        category = "Plain String"
        
    print(f"| {idx} | `{name}` | `{rec.file}` | `{fn.__name__}` | `{ret_ann}` | {shape_desc} | {category} |")
