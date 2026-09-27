"""
core/permission_manager.py
Shared permission management layer for ProAssist AI / Mark LIV.

Defines a 4-level taxonomy for system operations:
- Level 0 (SAFE): Auto-execute immediately without user confirmation.
- Level 1 (CONFIRM): Standard user confirmation required (HUD ConfirmBanner).
- Level 2 (STRONG_CONFIRM): Strong confirmation required (HUD ConfirmBanner / explicit auth).
- Level 3 (BLOCKED): Prohibited destructive or unauthorized operations that cannot execute.
"""

import ast
from enum import Enum
import inspect
import re
import sys
import textwrap
from typing import Any, Callable, Dict, List, NamedTuple, Optional


class PermissionLevel(Enum):
    SAFE = "SAFE"                       # Level 0: Auto-execute immediately
    CONFIRM = "CONFIRM"                 # Level 1: Standard user confirmation required
    STRONG_CONFIRM = "STRONG_CONFIRM"   # Level 2: Strong confirmation required
    BLOCKED = "BLOCKED"                 # Level 3: Blocked / never execute autonomously


class PermissionDecision(NamedTuple):
    level: PermissionLevel
    reason: str = ""
    description: str = ""
    key: str = ""


class PolicyRule(NamedTuple):
    tool: str
    action: Optional[str]               # None matches any action for the tool
    level: PermissionLevel
    reason: str
    key: str
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None


# Patterns for blocked dangerous commands (dev_agent / shell execution)
_BLOCKED_COMMAND_PATTERNS = [
    re.compile(r"\bformat\b\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bdel\b\s+.*(/s|/q|-s|-r)", re.IGNORECASE),
    re.compile(r"\brmdir\b\s+.*(/s|/q|-s|-r)", re.IGNORECASE),
    re.compile(r"\brm\b\s+.*-(r|f|rf|fr)", re.IGNORECASE),
    re.compile(r"\breg\b\s+(delete|add)\b", re.IGNORECASE),
    re.compile(r"\bdiskpart\b", re.IGNORECASE),
    re.compile(r"\b(powershell|pwsh)\b.*-enc", re.IGNORECASE),
    re.compile(r"\bcurl\b.*\|\s*(bash|sh|cmd|powershell)", re.IGNORECASE),
    re.compile(r"\b(net\s+user|net\s+localgroup)\b", re.IGNORECASE),
    re.compile(r"\b(mkfs|dd\s+if=)\b", re.IGNORECASE),
]

# Patterns for blocked desktop generated code threats
_BLOCKED_DESKTOP_PATTERNS = [
    re.compile(r"\b(unlink|rmdir|rmtree|remove)\b", re.IGNORECASE),
    re.compile(r"\b(subprocess|os\.system|popen|spawn)\b", re.IGNORECASE),
    re.compile(r"\b(__import__|exec|eval)\b", re.IGNORECASE),
    re.compile(r"\bshutil\.(rmtree|move)\b", re.IGNORECASE),
]


def _is_blocked_command(params: Dict[str, Any]) -> bool:
    raw_args = params.get("args") or ""
    if isinstance(raw_args, list):
        raw_args = " ".join(str(a) for a in raw_args)
    cmd = str(
        params.get("command")
        or params.get("cmd")
        or params.get("description")
        or raw_args
        or params.get("file_path")
        or ""
    ).strip()
    return any(p.search(cmd) for p in _BLOCKED_COMMAND_PATTERNS)


def _is_blocked_desktop_code(params: Dict[str, Any]) -> bool:
    code = str(params.get("code") or params.get("task") or "").strip()
    return any(p.search(code) for p in _BLOCKED_DESKTOP_PATTERNS)


def _is_sensitive_browser_action(params: Dict[str, Any]) -> bool:
    """Check if a browser_control action matches sensitive purchasing, messaging, or account patterns."""
    p = params or {}
    act = str(p.get("action", "") or "click").lower().strip()
    url = str(p.get("url", "")).strip()
    text = str(p.get("text", "") or p.get("description", "")).strip()
    selector = str(p.get("selector", "")).strip()
    try:
        from actions.browser_control import _detect_sensitive_action
        is_sensitive, _, _ = _detect_sensitive_action(url=url, action=act, target_text=text, selector=selector)
        return is_sensitive
    except Exception:
        comb = f"{text} {selector}".lower()
        if any(w in comb for w in ["buy now", "place order", "pay now", "send", "post", "checkout"]):
            return True
        # Fail-closed default: if detection logic errors on an interactive consequential action,
        # require confirmation rather than silently allowing it through ungated.
        if act in ("click", "smart_click", "fill_form", "press"):
            return True
        return False


# Declarative policy classification table (data, not hardcoded per-file logic)
POLICY_RULES: List[PolicyRule] = [
    # ── Item 4: file_controller.delete_file (Level 2: STRONG_CONFIRM) ──────────
    PolicyRule(
        tool="file_controller",
        action="delete",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="File deletion requires strong user confirmation",
        key="delete_file",
    ),
    PolicyRule(
        tool="file_controller",
        action="delete_file",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="File deletion requires strong user confirmation",
        key="delete_file",
    ),

    # ── Section 8: file_controller bulk operations (Level 2: STRONG_CONFIRM) ──
    PolicyRule(
        tool="file_controller",
        action="organize",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk file organization requires strong confirmation",
        key="file_organize",
    ),
    PolicyRule(
        tool="file_controller",
        action="organize_files",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk file organization requires strong confirmation",
        key="file_organize",
    ),
    PolicyRule(
        tool="file_controller",
        action="bulk_move",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk file moving requires strong confirmation",
        key="file_bulk_move",
    ),
    PolicyRule(
        tool="file_controller",
        action="bulk_rename",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk file renaming requires strong confirmation",
        key="file_bulk_rename",
    ),
    PolicyRule(
        tool="file_controller",
        action="organize_desktop",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk desktop reorganization requires strong confirmation",
        key="file_organize_desktop",
    ),

    # ── Item 3: dev_agent.install_dependencies (Level 1: CONFIRM) ─────────────
    PolicyRule(
        tool="dev_agent",
        action="install_dependencies",
        level=PermissionLevel.CONFIRM,
        reason="Package installation requires user confirmation",
        key="pip_install",
    ),

    # ── Item 2: dev_agent.run_project (BLOCKED or Level 1: CONFIRM) ───────────
    PolicyRule(
        tool="dev_agent",
        action="run_project",
        level=PermissionLevel.BLOCKED,
        reason="Prohibited dangerous command pattern detected",
        key="command_execution_blocked",
        condition=_is_blocked_command,
    ),
    PolicyRule(
        tool="dev_agent",
        action="run_project",
        level=PermissionLevel.CONFIRM,
        reason="Project command execution requires user confirmation",
        key="run_project",
    ),
    PolicyRule(
        tool="dev_agent",
        action=None,  # default dev_agent action (build_project)
        level=PermissionLevel.BLOCKED,
        reason="Prohibited dangerous command pattern detected in project description",
        key="dev_agent_blocked",
        condition=_is_blocked_command,
    ),
    PolicyRule(
        tool="dev_agent",
        action=None,
        level=PermissionLevel.CONFIRM,
        reason="Development agent autonomous build and execution requires confirmation",
        key="dev_agent_build",
    ),

    # ── Section 15: code_helper (Gated code manipulation & execution) ─────────
    PolicyRule(
        tool="code_helper",
        action="edit",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Editing and modifying existing code files requires strong confirmation",
        key="code_helper_edit",
    ),
    PolicyRule(
        tool="code_helper",
        action="screen_debug",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Applying screen-debug code fixes to files requires strong confirmation",
        key="code_helper_screen_debug",
    ),
    PolicyRule(
        tool="code_helper",
        action="optimize",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Optimizing and modifying code files requires strong confirmation",
        key="code_helper_optimize",
    ),
    PolicyRule(
        tool="code_helper",
        action="run",
        level=PermissionLevel.BLOCKED,
        reason="Prohibited dangerous command pattern detected in code execution",
        key="code_helper_run_blocked",
        condition=_is_blocked_command,
    ),
    PolicyRule(
        tool="code_helper",
        action="run",
        level=PermissionLevel.CONFIRM,
        reason="Executing code files and shell interpreters requires confirmation",
        key="code_helper_run",
    ),
    PolicyRule(
        tool="code_helper",
        action="build",
        level=PermissionLevel.BLOCKED,
        reason="Prohibited dangerous command pattern detected in build command",
        key="code_helper_build_blocked",
        condition=_is_blocked_command,
    ),
    PolicyRule(
        tool="code_helper",
        action="build",
        level=PermissionLevel.CONFIRM,
        reason="Autonomous code building, execution, and error iteration requires confirmation",
        key="code_helper_build",
    ),
    PolicyRule(
        tool="code_helper",
        action="write",
        level=PermissionLevel.SAFE,
        reason="Generating new code files on Desktop is standard",
        key="code_helper_write",
    ),
    PolicyRule(
        tool="code_helper",
        action="explain",
        level=PermissionLevel.SAFE,
        reason="Explaining code is read-only",
        key="code_helper_explain",
    ),

    # ── Item 1: desktop.execute_generated_code (BLOCKED or Level 2: STRONG_CONFIRM) ──
    PolicyRule(
        tool="desktop_control",
        action="task",
        level=PermissionLevel.BLOCKED,
        reason="Destructive operations in desktop automation code are prohibited",
        key="desktop_task_blocked",
        condition=_is_blocked_desktop_code,
    ),
    PolicyRule(
        tool="desktop_control",
        action="task",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Executing desktop automation code requires strong confirmation",
        key="desktop_code",
    ),
    PolicyRule(
        tool="desktop",
        action="execute_generated_code",
        level=PermissionLevel.BLOCKED,
        reason="Destructive operations in desktop automation code are prohibited",
        key="desktop_code_blocked",
        condition=_is_blocked_desktop_code,
    ),
    PolicyRule(
        tool="desktop",
        action="execute_generated_code",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Executing generated code requires strong confirmation",
        key="desktop_code",
    ),

    # ── desktop_control bulk / management operations ─────────────────────────
    PolicyRule(
        tool="desktop_control",
        action="organize",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk desktop reorganization requires strong confirmation",
        key="desktop_organize",
    ),
    PolicyRule(
        tool="desktop_control",
        action="clean",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Bulk desktop cleanup requires strong confirmation",
        key="desktop_clean",
    ),
    PolicyRule(
        tool="desktop_control",
        action="wallpaper",
        level=PermissionLevel.SAFE,
        reason="Changing wallpaper is safe",
        key="desktop_wallpaper",
    ),
    PolicyRule(
        tool="desktop_control",
        action="wallpaper_url",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Downloading and setting wallpaper from external URL requires strong confirmation",
        key="desktop_wallpaper_url",
    ),
    PolicyRule(
        tool="desktop_control",
        action="current_wallpaper",
        level=PermissionLevel.SAFE,
        reason="Reading wallpaper is safe",
        key="desktop_current_wallpaper",
    ),
    PolicyRule(
        tool="desktop_control",
        action="list",
        level=PermissionLevel.SAFE,
        reason="Listing desktop files is safe",
        key="desktop_list",
    ),
    PolicyRule(
        tool="desktop_control",
        action="stats",
        level=PermissionLevel.SAFE,
        reason="Reading desktop stats is safe",
        key="desktop_stats",
    ),

    # ── file_controller safe vs mutative operations ──────────────────────────
    PolicyRule(
        tool="file_controller",
        action="list",
        level=PermissionLevel.SAFE,
        reason="Listing files is safe",
        key="file_list",
    ),
    PolicyRule(
        tool="file_controller",
        action="read",
        level=PermissionLevel.SAFE,
        reason="Reading files is safe",
        key="file_read",
    ),
    PolicyRule(
        tool="file_controller",
        action="find",
        level=PermissionLevel.SAFE,
        reason="Searching files is safe",
        key="file_find",
    ),
    PolicyRule(
        tool="file_controller",
        action="disk_usage",
        level=PermissionLevel.SAFE,
        reason="Checking disk usage is safe",
        key="file_disk_usage",
    ),
    PolicyRule(
        tool="file_controller",
        action="info",
        level=PermissionLevel.SAFE,
        reason="Checking file info is safe",
        key="file_info",
    ),
    PolicyRule(
        tool="file_controller",
        action="largest",
        level=PermissionLevel.SAFE,
        reason="Finding largest files is safe",
        key="file_largest",
    ),

    # ── computer_settings safe status queries ────────────────────────────────
    PolicyRule(
        tool="computer_settings",
        action="bluetooth_status",
        level=PermissionLevel.SAFE,
        reason="Querying Bluetooth status is safe",
        key="computer_settings_bluetooth_status",
    ),
    PolicyRule(
        tool="computer_settings",
        action="battery_status",
        level=PermissionLevel.SAFE,
        reason="Querying battery status is safe",
        key="computer_settings_battery_status",
    ),
    PolicyRule(
        tool="computer_settings",
        action="wifi_status",
        level=PermissionLevel.SAFE,
        reason="Querying Wi-Fi status is safe",
        key="computer_settings_wifi_status",
    ),

    # ── system_monitor safe monitoring operations ────────────────────────────
    PolicyRule(
        tool="system_monitor",
        action="status",
        level=PermissionLevel.SAFE,
        reason="System status monitoring is safe",
        key="system_monitor_status",
    ),
    PolicyRule(
        tool="system_monitor",
        action="diagnose",
        level=PermissionLevel.SAFE,
        reason="System performance diagnostic is safe",
        key="system_monitor_diagnose",
    ),
    PolicyRule(
        tool="system_monitor",
        action="processes",
        level=PermissionLevel.SAFE,
        reason="Process resource monitoring is safe",
        key="system_monitor_processes",
    ),
    PolicyRule(
        tool="system_monitor",
        action="disk",
        level=PermissionLevel.SAFE,
        reason="Disk metrics monitoring is safe",
        key="system_monitor_disk",
    ),
    PolicyRule(
        tool="system_monitor",
        action="network",
        level=PermissionLevel.SAFE,
        reason="Network throughput monitoring is safe",
        key="system_monitor_network",
    ),
    PolicyRule(
        tool="system_monitor",
        action=None,
        level=PermissionLevel.SAFE,
        reason="System monitor read-only monitoring operations are safe",
        key="system_monitor_safe",
    ),

    # ── reminder safe CRUD operations ─────────────────────────────────────────
    PolicyRule(
        tool="reminder",
        action="create",
        level=PermissionLevel.SAFE,
        reason="Creating a scheduled reminder is safe and non-destructive",
        key="reminder_create",
    ),
    PolicyRule(
        tool="reminder",
        action="list",
        level=PermissionLevel.SAFE,
        reason="Listing scheduled reminders is a read-only query",
        key="reminder_list",
    ),
    PolicyRule(
        tool="reminder",
        action="update",
        level=PermissionLevel.SAFE,
        reason="Updating an existing reminder time or text is safe and reversible",
        key="reminder_update",
    ),
    PolicyRule(
        tool="reminder",
        action="delete",
        level=PermissionLevel.SAFE,
        reason="Deleting a reminder is low-risk, easily undoable, and non-destructive",
        key="reminder_delete",
    ),
    PolicyRule(
        tool="reminder",
        action=None,
        level=PermissionLevel.SAFE,
        reason="Reminder management operations are safe and non-destructive",
        key="reminder_safe",
    ),

    # ── open_app safe application and file launching ─────────────────────────
    PolicyRule(
        tool="open_app",
        action="open_app",
        level=PermissionLevel.SAFE,
        reason="Opening allowlisted desktop applications is safe and non-destructive",
        key="open_app_launch",
    ),
    PolicyRule(
        tool="open_app",
        action="open_file",
        level=PermissionLevel.SAFE,
        reason="Opening user files in default applications is safe and non-destructive",
        key="open_file_launch",
    ),
    PolicyRule(
        tool="open_app",
        action=None,
        level=PermissionLevel.SAFE,
        reason="Application and file launching operations are safe and non-destructive",
        key="open_app_safe",
    ),

    # ── Item 2: browser_control sensitive actions & download interception ───
    PolicyRule(
        tool="browser_control",
        action="download",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="Downloading external files via browser requires strong confirmation",
        key="browser_download",
    ),
    PolicyRule(
        tool="browser_control",
        action="click",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="High-risk browser action (purchasing, sending message, or public posting) requires strong confirmation",
        key="browser_sensitive_action",
        condition=_is_sensitive_browser_action,
    ),
    PolicyRule(
        tool="browser_control",
        action="smart_click",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="High-risk browser action (purchasing, sending message, or public posting) requires strong confirmation",
        key="browser_sensitive_action",
        condition=_is_sensitive_browser_action,
    ),
    PolicyRule(
        tool="browser_control",
        action="fill_form",
        level=PermissionLevel.STRONG_CONFIRM,
        reason="High-risk browser form submission requires strong confirmation",
        key="browser_sensitive_action",
        condition=_is_sensitive_browser_action,
    ),
    PolicyRule(
        tool="browser_control",
        action="click",
        level=PermissionLevel.SAFE,
        reason="Ordinary browser clicking and navigation is safe",
        key="browser_click_safe",
    ),
    PolicyRule(
        tool="browser_control",
        action="smart_click",
        level=PermissionLevel.SAFE,
        reason="Ordinary element clicking and navigation is safe",
        key="browser_smart_click_safe",
    ),
    PolicyRule(
        tool="browser_control",
        action="fill_form",
        level=PermissionLevel.SAFE,
        reason="Standard web form input filling is safe",
        key="browser_fill_form_safe",
    ),
    PolicyRule(
        tool="browser_control",
        action="go_to",
        level=PermissionLevel.SAFE,
        reason="Navigating to a website URL is safe",
        key="browser_go_to_safe",
    ),
    PolicyRule(
        tool="browser_control",
        action="search",
        level=PermissionLevel.SAFE,
        reason="Searching the web via search engine is safe",
        key="browser_search_safe",
    ),
    PolicyRule(
        tool="browser_control",
        action=None,
        level=PermissionLevel.SAFE,
        reason="General browser navigation, reading, and interaction are safe",
        key="browser_safe",
    ),
]


def _rule_specificity(rule: PolicyRule) -> tuple[int, int]:
    """
    Priority key for rule resolution order:
      1. Specific action (rule.action is not None) before wildcard action (rule.action is None)
      2. Conditional rule (rule.condition is not None) before unconditional fallback (rule.condition is None)
    """
    return (
        1 if rule.action is not None else 0,
        1 if rule.condition is not None else 0,
    )


def check_permission(
    tool_name: str,
    action: str = "",
    params: Optional[Dict[str, Any]] = None,
) -> PermissionDecision:
    """
    Check the permission level for a given tool and action with parameters.

    Returns a PermissionDecision tuple with (level, reason, description, key).
    Unclassified tools or actions default to PermissionLevel.SAFE.
    """
    if isinstance(action, dict) and params is None:
        params = action
        action = str(params.get("action") or "").strip().lower()

    p = params or {}
    t_name = str(tool_name or "").strip().lower()
    a_name = str(action or "").strip().lower()
    if not a_name and p.get("action"):
        a_name = str(p.get("action") or "").strip().lower()

    # Normalize dot-syntax (e.g. desktop.execute_generated_code -> desktop, execute_generated_code)
    if "." in t_name and not a_name:
        parts = t_name.split(".", 1)
        t_name = parts[0]
        a_name = parts[1]

    # Map aliases
    if t_name == "desktop":
        t_name = "desktop_control"

    # Prioritize specific action and conditional rules over general/unconditional fallbacks.
    # Python's sort is stable, preserving original relative declaration order among rules with equal specificity.
    sorted_rules = sorted(POLICY_RULES, key=_rule_specificity, reverse=True)

    # Match rules in priority order
    for rule in sorted_rules:
        # Match tool name
        if rule.tool.lower() != t_name and (rule.tool != "desktop" or t_name != "desktop_control"):
            continue

        # Match action (if rule specifies an action)
        if rule.action is not None and rule.action.lower() != a_name:
            continue

        # Check condition if provided
        if rule.condition is not None:
            if not rule.condition(p):
                continue

        # Match found
        desc = str(p.get("description") or p.get("task") or p.get("path") or p.get("command") or "")
        return PermissionDecision(
            level=rule.level,
            reason=rule.reason,
            description=desc,
            key=rule.key,
        )

    # Safe default for unclassified tools / actions
    return PermissionDecision(
        level=PermissionLevel.SAFE,
        reason="Safe or unmanaged tool execution",
        description="",
        key="safe_default",
    )


def list_policies() -> List[Dict[str, Any]]:
    """Return a serialized list of all active policy rules as data."""
    return [
        {
            "tool": r.tool,
            "action": r.action,
            "level": r.level.value,
            "reason": r.reason,
            "key": r.key,
        }
        for r in POLICY_RULES
    ]


class SecurityPolicyError(Exception):
    """Raised at startup or test-time when a tool/action classified as
    CONFIRM or STRONG_CONFIRM lacks an internal confirm.request() gate."""
    pass


# Actions deferred to future passes (empty — all active CONFIRM/STRONG_CONFIRM tools are gated).
EXEMPT_DEFERRED_ACTIONS: set[tuple[str, Optional[str]]] = set()


def has_confirm_gate(func: Callable, visited: Optional[set] = None) -> bool:
    """
    Check whether a function (or any sub-function within the same module it
    delegates to) contains a call to confirm.request().
    """
    if visited is None:
        visited = set()
    if func in visited:
        return False
    visited.add(func)

    try:
        src = textwrap.dedent(inspect.getsource(func))
    except Exception:
        return False

    if "confirm.request(" in src:
        return True

    # Check called functions within the same module
    try:
        mod = sys.modules.get(func.__module__)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_name = node.func.id
                if mod and hasattr(mod, called_name):
                    called_obj = getattr(mod, called_name)
                    if (
                        callable(called_obj)
                        and hasattr(called_obj, "__module__")
                        and called_obj.__module__ == func.__module__
                    ):
                        if has_confirm_gate(called_obj, visited):
                            return True
    except Exception:
        pass

    return False


def get_confirm_keys(func: Callable, visited: Optional[set] = None) -> set[str]:
    """
    Extract the set of confirmation keys requested via confirm.request(key=...)
    inside func and any helper functions it delegates to within the same module.
    """
    if visited is None:
        visited = set()
    if func in visited:
        return set()
    visited.add(func)

    found_keys: set[str] = set()
    try:
        src = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(src)
    except Exception:
        return found_keys

    # Find confirm.request(key=...) calls in AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            is_confirm = False
            if isinstance(node.func, ast.Attribute) and node.func.attr == "request":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "confirm":
                    is_confirm = True
            if is_confirm:
                # 1. Keyword argument: key="..."
                for kw in node.keywords:
                    if kw.arg == "key" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        found_keys.add(kw.value.value)
                # 2. Positional argument: confirm.request("...")
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    found_keys.add(node.args[0].value)

    # Walk called functions within the same module
    try:
        mod = sys.modules.get(func.__module__)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_name = node.func.id
                if mod and hasattr(mod, called_name):
                    called_obj = getattr(mod, called_name)
                    if (
                        callable(called_obj)
                        and hasattr(called_obj, "__module__")
                        and called_obj.__module__ == func.__module__
                    ):
                        found_keys.update(get_confirm_keys(called_obj, visited))
    except Exception:
        pass

    return found_keys


def resolve_action_handler(top_handler: Callable, action_name: Optional[str]) -> Callable:
    """
    Given a top-level tool handler and an action name, resolve the exact
    sub-function or worker function that will execute for that action.
    """
    # 0. If top_handler is a delegating wrapper (e.g. AgentTool.execute -> desktop_control), unwrap it
    try:
        src = textwrap.dedent(inspect.getsource(top_handler))
        tree = ast.parse(src)
        func_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        returns = [n for n in func_def.body if isinstance(n, ast.Return)]
        if len(returns) == 1 and isinstance(returns[0].value, ast.Call) and isinstance(returns[0].value.func, ast.Name):
            fname = returns[0].value.func.id
            mod = sys.modules.get(top_handler.__module__)
            if mod and hasattr(mod, fname):
                delegated = getattr(mod, fname)
                if callable(delegated) and delegated != top_handler:
                    top_handler = delegated
    except Exception:
        pass

    if not action_name:
        # Check if the top-level handler delegates unconditionally to a worker function
        # e.g. dev_agent(parameters, ...) -> return _build_project(...)
        try:
            src = textwrap.dedent(inspect.getsource(top_handler))
            tree = ast.parse(src)
            func_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
            mod = sys.modules.get(top_handler.__module__)
            for node in ast.walk(func_def):
                if isinstance(node, ast.Return) and node.value:
                    for call in ast.walk(node.value):
                        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                            fname = call.func.id
                            if mod and hasattr(mod, fname):
                                return getattr(mod, fname)
        except Exception:
            pass
        return top_handler

    mod = sys.modules.get(top_handler.__module__)
    if not mod:
        return top_handler

    act = action_name.lower().strip()

    # 1. Inspect top_handler AST for branching on action == act
    try:
        src = textwrap.dedent(inspect.getsource(top_handler))
        tree = ast.parse(src)
        func_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        for node in ast.walk(func_def):
            if isinstance(node, ast.If):
                test_src = ast.unparse(node.test)
                if f'"{act}"' in test_src or f"'{act}'" in test_src:
                    # Check return nodes in this branch
                    for sub in node.body:
                        for ret in ast.walk(sub):
                            if isinstance(ret, ast.Return) and ret.value:
                                for call in ast.walk(ret.value):
                                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                                        fname = call.func.id
                                        if mod and hasattr(mod, fname):
                                            return getattr(mod, fname)
                    # Check any call in this branch
                    for sub in node.body:
                        for call in ast.walk(sub):
                            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                                fname = call.func.id
                                if mod and hasattr(mod, fname):
                                    return getattr(mod, fname)
    except Exception:
        pass

    # 2. Check direct function naming match in the module
    # e.g. 'delete' -> delete_file, 'install_dependencies' -> _install_dependencies
    candidates = [act, f"_{act}", f"{act}_file", f"_{act}_file", f"{act}_desktop", f"_{act}_desktop"]
    if "execute" in act or "code" in act:
        candidates.extend(["execute_generated_code", "_execute_generated_code"])
    for candidate in candidates:
        if mod and hasattr(mod, candidate) and callable(getattr(mod, candidate)):
            return getattr(mod, candidate)


    return top_handler


def verify_permission_gates(
    action_registry=None,
    rules: Optional[List[PolicyRule]] = None,
    exempt_unmigrated: Optional[set] = None,
) -> None:
    """
    Startup & test-time static verification audit.
    For every (tool, action) classified as CONFIRM or STRONG_CONFIRM in POLICY_RULES,
    resolves the exact handler function that action_loader dispatches to at runtime,
    inspects its source via inspect.getsource(), and confirms it contains a
    confirm.request() call.

    Raises SecurityPolicyError if any classified action lacks an internal confirmation gate.
    """
    if exempt_unmigrated is None:
        exempt_unmigrated = EXEMPT_DEFERRED_ACTIONS

    rules_to_check = rules if rules is not None else POLICY_RULES

    # If action_registry is not provided, discover actions from default path
    if action_registry is None:
        from pathlib import Path
        from core.action_loader import discover_actions
        base_dir = Path(__file__).resolve().parent.parent
        action_registry = discover_actions(actions_dir=base_dir / "actions")

    for r in rules_to_check:
        if r.level not in (PermissionLevel.CONFIRM, PermissionLevel.STRONG_CONFIRM):
            continue

        tool_key = r.tool.lower().strip()
        act_key = r.action.lower().strip() if r.action is not None else None

        # Check exemption for explicitly out-of-scope actions
        if (tool_key, act_key) in exempt_unmigrated:
            continue

        # Look up tool in action_registry (handling desktop -> desktop_control alias)
        lookup_name = "desktop_control" if tool_key == "desktop" else tool_key
        rec = action_registry._actions.get(lookup_name) if hasattr(action_registry, "_actions") else None
        if rec is None or rec.handler is None:
            raise SecurityPolicyError(
                f"Security Policy Violation: Tool '{r.tool}' is classified as {r.level.value}, "
                f"but is not registered in action_registry!"
            )

        # Resolve the exact action handler function
        target_func = resolve_action_handler(rec.handler, r.action)

        # Check if the resolved handler contains confirm.request()
        if not has_confirm_gate(target_func):
            func_name = getattr(target_func, "__name__", str(target_func))
            mod_name = getattr(target_func, "__module__", "unknown")
            raise SecurityPolicyError(
                f"Security Policy Violation: Tool '{r.tool}' (action '{r.action}') is classified "
                f"as {r.level.value}, but its resolved implementation function '{func_name}' in "
                f"module '{mod_name}' lacks a required 'confirm.request()' gate!"
            )

        # Invariant enforcement: verify confirm.request() key matches POLICY_RULES key
        confirm_keys = get_confirm_keys(target_func)
        if confirm_keys and r.key not in confirm_keys:
            func_name = getattr(target_func, "__name__", str(target_func))
            mod_name = getattr(target_func, "__module__", "unknown")
            raise SecurityPolicyError(
                f"Security Policy Violation: Tool '{r.tool}' (action '{r.action}') has policy key "
                f"'{r.key}', but implementation function '{func_name}' in module '{mod_name}' "
                f"requests confirmation with key(s) {sorted(confirm_keys)} — key-alignment invariant violated!"
            )

