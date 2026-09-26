import difflib
from pathlib import Path

# Read initial from git or compare with updated
p = Path(r"C:\Users\santh\.gemini\antigravity-ide\brain\8a51d655-10fe-4649-be6d-a4c90a685230\implementation_plan.md")
content = p.read_text(encoding="utf-8")
print(content)
