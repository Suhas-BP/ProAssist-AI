import inspect
import ast
import textwrap
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import confirm

def target_worker_func(path: str):
    return confirm.request(
        key="delete_file",
        title="Delete Test File",
        detail="Remove file",
        run=lambda: "Done",
    )

class SampleAgentTool:
    def execute(self, parameters: dict, **kwargs):
        action = str(parameters.get("action") or "").lower().strip()
        if action == "delete":
            return target_worker_func(parameters.get("path"))
        return "Unknown"

# Simulate resolve_action_handler on bound method without dedent vs with dedent
tool = SampleAgentTool()
bound_method = tool.execute

print("=== 1. Without dedent (current code behavior) ===")
src_raw = inspect.getsource(bound_method)
try:
    tree = ast.parse(src_raw)
    print("Parsed without dedent: SUCCESS")
except IndentationError as e:
    print("Parsed without dedent: IndentationError caught:", e)

print("\n=== 2. With textwrap.dedent (proposed fix) ===")
src_dedented = textwrap.dedent(src_raw)
tree_dedented = ast.parse(src_dedented)
print("Parsed with dedent: SUCCESS")

# Walk the AST exactly as resolve_action_handler does
func_def = next(n for n in ast.walk(tree_dedented) if isinstance(n, ast.FunctionDef))
resolved_target = None
mod = sys.modules.get(bound_method.__module__)

for node in ast.walk(func_def):
    if isinstance(node, ast.If):
        test_src = ast.unparse(node.test)
        if '"delete"' in test_src or "'delete'" in test_src:
            for sub in node.body:
                for ret in ast.walk(sub):
                    if isinstance(ret, ast.Return) and ret.value:
                        for call in ast.walk(ret.value):
                            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                                fname = call.func.id
                                if mod and hasattr(mod, fname):
                                    resolved_target = getattr(mod, fname)

print(f"Resolved target function: {resolved_target.__name__ if resolved_target else None}")
assert resolved_target is target_worker_func, "Target function must resolve to target_worker_func!"
print("SUCCESS: ast.Name resolution works seamlessly with textwrap.dedent on bound methods!")

