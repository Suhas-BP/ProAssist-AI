import ast
import inspect
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.action_loader import discover_actions

reg = discover_actions(Path("actions"))

results = []
for name, rec in sorted(reg._actions.items()):
    fn = rec.handler
    src = inspect.getsource(fn)
    tree = ast.parse(src)
    
    # Check return statements in the handler and sub-functions
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    return_types = set()
    has_dict = False
    has_str = False
    has_json = "json.dumps" in src
    
    for r in returns:
        if r.value is None:
            return_types.add("None")
        elif isinstance(r.value, ast.Dict):
            return_types.add("Dict")
            has_dict = True
        elif isinstance(r.value, (ast.Constant, ast.JoinedStr)):
            return_types.add("String")
            has_str = True
        elif isinstance(r.value, ast.Call):
            func_name = ast.unparse(r.value.func)
            return_types.add(f"Call({func_name})")
        else:
            return_types.add(type(r.value).__name__)
            
    # Check module source for sub-functions returning dicts/strings
    mod_src = Path(rec.file).read_text(encoding="utf-8") if Path(rec.file).exists() else Path(f"actions/{rec.file}").read_text(encoding="utf-8")
    
    # Check for structured dict keys
    has_success_key = '"success"' in mod_src or "'success'" in mod_src
    has_action_key = '"action"' in mod_src or "'action'" in mod_src
    has_error_key = '"error"' in mod_src or "'error'" in mod_src
    has_result_key = '"result"' in mod_src or "'result'" in mod_src
    
    # What does the top-level handler signature declare as return type?
    sig = inspect.signature(fn)
    ret_ann = sig.return_annotation
    
    results.append({
        "name": name,
        "handler": fn.__name__,
        "ret_ann": str(ret_ann),
        "return_types": sorted(list(return_types)),
        "has_dict": has_dict,
        "has_json": has_json,
        "has_structured_shape": has_success_key and (has_result_key or has_action_key),
        "src_snippet": src[:200].replace("\n", " ")
    })

print(json.dumps(results, indent=2))
