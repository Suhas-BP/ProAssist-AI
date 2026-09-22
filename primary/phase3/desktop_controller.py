"""
Desktop Controller for ProAssist AI Phase 3
Provides controlled application operations:
1. Safe mathematical evaluation (Calculator) without code execution.
2. Controlled Notepad text typing.
3. Safe File Explorer folder navigation.
"""

import ast
import operator
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from phase3 import config as p3_config
from phase3.app_launcher import AppLauncher


class SafeMathEvaluator:
    """Safely evaluates mathematical expressions using AST white-listing."""

    ALLOWED_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    @classmethod
    def evaluate(cls, node):
        if isinstance(node, ast.Expression):
            return cls.evaluate(node.body)
        elif isinstance(node, ast.Constant):  # Python 3.8+ numbers
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Disallowed constant type in expression")
        elif isinstance(node, ast.Num):  # Backward compatibility
            return node.n
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type in cls.ALLOWED_OPERATORS:
                operand = cls.evaluate(node.operand)
                return cls.ALLOWED_OPERATORS[op_type](operand)
            raise ValueError(f"Disallowed unary operator: {op_type}")
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in cls.ALLOWED_OPERATORS:
                left = cls.evaluate(node.left)
                right = cls.evaluate(node.right)
                if op_type is ast.Div and right == 0:
                    raise ZeroDivisionError("Cannot divide by zero.")
                if op_type is ast.Pow and right > 100:
                    raise OverflowError("Exponent too large for safety.")
                return cls.ALLOWED_OPERATORS[op_type](left, right)
            raise ValueError(f"Disallowed binary operator: {op_type}")
        else:
            raise ValueError("Arbitrary expression syntax or function call is strictly forbidden.")

    @classmethod
    def parse_spoken_math(cls, text: str) -> str:
        """Converts spoken math phrases into standard arithmetic expressions."""
        t = text.lower().strip()

        # Remove leading "calculate", "what is", "solve"
        t = re.sub(r"^(calculate|what\s+is|solve|evaluate)\s+", "", t)

        # Handle percentage: "25 percent of 800" -> "(25 / 100) * 800"
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(\d+(?:\.\d+)?)", t)
        if pct_match:
            pct_val = pct_match.group(1)
            base_val = pct_match.group(2)
            t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+(\d+(?:\.\d+)?)", f"({pct_val} / 100) * {base_val}", t)

        # Word replacements
        replacements = [
            (r"\bmultiplied\s+by\b", "*"),
            (r"\btimes\b", "*"),
            (r"\bx\b", "*"),
            (r"\binto\b", "*"),
            (r"\bdivided\s+by\b", "/"),
            (r"\bover\b", "/"),
            (r"\bplus\b", "+"),
            (r"\badd\b", "+"),
            (r"\bminus\b", "-"),
            (r"\bsubtract\b", "-"),
            (r"\bto\s+the\s+power\s+of\b", "**"),
            (r"\bpower\b", "**"),
        ]
        for pat, repl in replacements:
            t = re.sub(pat, repl, t)

        # Keep only numbers, basic operators, parens, decimal points, and spaces
        cleaned = re.sub(r"[^\d\+\-\*\/\%\.\(\)\s]", "", t).strip()
        return cleaned


class DesktopController:
    """Controls desktop applications: Calculator, Notepad typing, and File Explorer folders."""

    def __init__(self, launcher: AppLauncher = None):
        self.launcher = launcher or AppLauncher()
        self.allowed_folders = p3_config.ALLOWED_FOLDERS

    # =========================================================================
    # CALCULATOR OPERATIONS
    # =========================================================================
    def calculate(self, spoken_text: str) -> tuple[bool, str]:
        """
        Safely evaluates a spoken mathematical problem.
        Example: '25 times 40' -> 'The answer is 1000.'
        """
        expr = SafeMathEvaluator.parse_spoken_math(spoken_text)
        if not expr:
            return False, "I couldn't identify a valid mathematical expression to calculate."

        try:
            tree = ast.parse(expr, mode="eval")
            result = SafeMathEvaluator.evaluate(tree)
            # Format integer cleanly (e.g. 1000 instead of 1000.0)
            if isinstance(result, float) and result.is_integer():
                result_str = str(int(result))
            else:
                result_str = f"{result:.4g}"
            return True, f"The answer is {result_str}."
        except ZeroDivisionError:
            return False, "Cannot divide by zero."
        except Exception as e:
            print(f"[DesktopController] Math parsing error on '{spoken_text}' (expr: '{expr}'): {e}")
            return False, "I couldn't compute that mathematical expression."

    # =========================================================================
    # NOTEPAD OPERATIONS
    # =========================================================================
    def type_in_notepad(self, text_to_type: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Types given text into Notepad using controlled keyboard automation.
        """
        clean_text = text_to_type.strip().strip('"\'')
        # Strip common dictation preambles: "write down that ...", "write: ..."
        clean_text = re.sub(r"^(?:down\s+(?:that\s+)?|that\s+|this:?\s*)", "", clean_text, flags=re.IGNORECASE).strip()

        if not clean_text:
            return False, "There is no text specified to type into Notepad."

        if dry_run:
            try:
                print(f"[DesktopController DRY-RUN] Verified typing into Notepad: '{clean_text}'")
            except UnicodeEncodeError:
                safe_t = clean_text.encode("ascii", "backslashreplace").decode("ascii")
                print(f"[DesktopController DRY-RUN] Verified typing into Notepad: '{safe_t}'")
            return True, "Typing that into Notepad."

        # Launch or ensure Notepad is open
        self.launcher.launch("notepad", dry_run=False)
        time.sleep(0.8)  # Wait for window focus

        # Ensure Notepad window has foreground focus on Windows
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "$w = New-Object -ComObject WScript.Shell; $w.AppActivate('Notepad')"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=2
                )
                time.sleep(0.3)
            except Exception:
                pass

        try:
            # Fast, accurate clipboard paste handles any symbols, Unicode, and punctuation instantly
            import pyperclip
            import pyautogui
            pyperclip.copy(clean_text)
            pyautogui.hotkey("ctrl", "v")
            pyautogui.press("enter")
            return True, "Typing that into Notepad."
        except Exception:
            try:
                import pyautogui
                pyautogui.write(clean_text, interval=0.01)
                pyautogui.press("enter")
                return True, "Typing that into Notepad."
            except ImportError:
                # Fallback using safe Windows powershell SendKeys
                try:
                    escaped = clean_text.replace("'", "''")
                    cmd = f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}{{ENTER}}')"
                    subprocess.run(["powershell", "-Command", f"Add-Type -AssemblyName System.Windows.Forms; {cmd}"],
                                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                   timeout=3)
                    return True, "Typing that into Notepad."
                except Exception as e:
                    print(f"[DesktopController ERROR] Notepad typing automation error: {e}")
                    return False, "I couldn't type into Notepad."

    # =========================================================================
    # FILE EXPLORER OPERATIONS
    # =========================================================================
    def open_folder(self, folder_name: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Safely opens an allowlisted system folder in File Explorer.
        """
        key = folder_name.lower().strip()
        target_path = None

        if key in self.allowed_folders:
            target_path = self.allowed_folders[key]
        else:
            for k, p in self.allowed_folders.items():
                if k in key:
                    target_path = p
                    key = k
                    break

        if not target_path:
            if "explorer" in key or "file explorer" in key:
                target_path = p3_config.USER_HOME
                key = "File Explorer"
            else:
                print(f"[DesktopController SECURITY] Blocked unauthorized folder request: '{folder_name}'")
                return False, f"I cannot open {folder_name} because it is not an allowed folder."

        if key.lower() in ["explorer", "file explorer"]:
            display_name = "File Explorer"
        else:
            display_name = key.capitalize()

        if dry_run:
            print(f"[DesktopController DRY-RUN] Verified opening folder: {display_name} ({target_path})")
            return True, f"Opening {display_name}."

        try:
            if not target_path.exists():
                target_path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(target_path))
            else:
                subprocess.Popen(["xdg-open", str(target_path)])
            return True, f"Opening {display_name}."
        except Exception as e:
            print(f"[DesktopController ERROR] Failed to open folder {display_name}: {e}")
            return False, f"I couldn't open {display_name}."

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    def open_file(self, file_query: str, dry_run: bool = False) -> tuple[bool, str]:
        """
        Safely locates and opens a user file (e.g. PDF, docx, txt) matching file_query.
        """
        clean_q = file_query.strip()
        if not clean_q or clean_q.lower() in ["file", "a file", "the file", "file explorer", "the file explorer"]:
            return self.open_folder("explorer", dry_run=dry_run)

        try:
            from rag.document_loader import DocumentLoader
            loader = DocumentLoader()
            matches = loader.find_user_documents(clean_q)
        except Exception as e:
            print(f"[DesktopController ERROR] Error searching files: {e}")
            matches = []

        if not matches:
            return False, f"I couldn't find any file matching '{clean_q}' in your files."

        target_file = matches[0]
        display_name = target_file.name

        if dry_run:
            print(f"[DesktopController DRY-RUN] Verified opening file: {display_name} ({target_file})")
            return True, f"Opening file {display_name}."

        try:
            if sys.platform == "win32":
                os.startfile(str(target_file))
            else:
                subprocess.Popen(["xdg-open", str(target_file)])
            return True, f"Opening file {display_name}."
        except Exception as e:
            print(f"[DesktopController ERROR] Failed to open file {display_name}: {e}")
            return False, f"I couldn't open {display_name}."

