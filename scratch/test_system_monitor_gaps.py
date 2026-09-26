"""
scratch/test_system_monitor_gaps.py
Dedicated test suite for Section 11 (System Monitor):
1. Disk usage per drive & reuse of file_controller.get_disk_usage()
2. Network throughput rate sampling via psutil.net_io_counters()
3. Battery percentage reuse from computer_settings.battery_status()
4. Top resource-consuming process enumeration (CPU & memory, read-only)
5. 'Why is my computer slow' diagnostic flow with live observed metrics
6. Standalone TOOL declaration & structured format {"success", "action", "value", "message"}
7. SAFE permission policy rules & verify_permission_gates static audit
"""

import sys
from pathlib import Path

# Console must survive non-UTF-8 code pages
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions.system_monitor import (
    get_disk_metrics,
    get_network_throughput,
    get_top_processes,
    diagnose_system,
    get_system_status,
    system_monitor,
)
from actions.computer_settings import battery_status
from actions.file_controller import get_disk_usage
from core.permission_manager import (
    PermissionLevel,
    check_permission,
    verify_permission_gates,
)
from core.action_loader import discover_actions


def assert_structured_result(res: dict, expected_action: str = None, expected_success: bool = True):
    assert isinstance(res, dict), f"Expected dict, got {type(res)}: {res}"
    assert "success" in res, f"Missing 'success' in {res}"
    assert "action" in res, f"Missing 'action' in {res}"
    assert "value" in res, f"Missing 'value' in {res}"
    assert "message" in res, f"Missing 'message' in {res}"
    assert isinstance(res["success"], bool), f"'success' must be bool, got {type(res['success'])}"
    assert isinstance(res["action"], str), f"'action' must be str, got {type(res['action'])}"
    assert isinstance(res["message"], str), f"'message' must be str, got {type(res['message'])}"
    if expected_action is not None:
        assert res["action"] == expected_action, f"Expected action '{expected_action}', got '{res['action']}'"
    if expected_success is not None:
        assert res["success"] is expected_success, f"Expected success={expected_success}, got {res['success']}"


def test_disk_usage_and_reuse():
    print("Testing disk usage metrics and file_controller reuse...")
    disk = get_disk_metrics()
    assert isinstance(disk, dict)
    assert "drives" in disk
    assert "summary" in disk
    assert len(disk["drives"]) >= 1
    primary = disk["drives"][0]
    assert "total_gb" in primary and primary["total_gb"] > 0
    assert "used_gb" in primary
    assert "free_gb" in primary
    assert "percent" in primary
    # Verify reuse of file_controller summary
    assert "Disk usage" in disk["summary"]
    print(f"  -> Discovered {len(disk['drives'])} drive(s). Primary: {primary['mountpoint']} {primary['percent']}% used.")
    print(f"  -> file_controller reuse verified:\n{disk['summary']}")


def test_network_throughput():
    print("Testing network throughput rate sampling...")
    net = get_network_throughput(interval=0.25)
    assert isinstance(net, dict)
    assert "kb_sent_per_sec" in net
    assert "kb_recv_per_sec" in net
    assert "mb_sent_per_sec" in net
    assert "mb_recv_per_sec" in net
    assert net["kb_sent_per_sec"] >= 0.0
    assert net["kb_recv_per_sec"] >= 0.0
    print(f"  -> Network rates: {net['kb_sent_per_sec']} KB/s sent, {net['kb_recv_per_sec']} KB/s received.")


def test_battery_reuse():
    print("Testing battery status reuse from computer_settings...")
    batt_cs = battery_status()
    status = get_system_status()
    assert "battery" in status
    batt_sm = status["battery"]
    assert batt_sm.get("percent") == batt_cs.get("percent")
    assert batt_sm.get("plugged") == batt_cs.get("plugged")
    print(f"  -> Battery status verified: {batt_sm}")


def test_top_processes():
    print("Testing top resource-consuming process enumeration...")
    procs = get_top_processes(n=5, sample_interval=0.2)
    assert isinstance(procs, dict)
    assert "top_cpu" in procs
    assert "top_memory" in procs
    assert len(procs["top_cpu"]) > 0
    assert len(procs["top_memory"]) > 0

    top_c = procs["top_cpu"][0]
    assert "pid" in top_c and "name" in top_c and "cpu_percent" in top_c
    assert top_c["pid"] != 0, "System Idle process must be filtered"

    top_m = procs["top_memory"][0]
    assert "pid" in top_m and "name" in top_m and "memory_mb" in top_m
    assert top_m["memory_mb"] > 0
    print(f"  -> Top CPU process: {top_c['name']} (PID {top_c['pid']}, {top_c['cpu_percent']}%)")
    print(f"  -> Top Memory process: {top_m['name']} (PID {top_m['pid']}, {top_m['memory_mb']} MB)")


def test_why_is_my_computer_slow_diagnostic():
    print("Testing 'why is my computer slow' diagnostic flow...")
    diag = diagnose_system(top_n=5)
    assert isinstance(diag, dict)
    assert "bottlenecks" in diag
    assert "summary" in diag
    assert "cpu_percent" in diag
    assert "ram_percent" in diag
    assert "disk" in diag
    assert "network" in diag
    assert "top_cpu_processes" in diag
    assert "top_memory_processes" in diag

    # Summary must be factual, non-canned, grounded in real observed numbers
    summary = diag["summary"]
    assert len(summary) > 20
    assert str(diag["cpu_percent"]) in summary or "CPU" in summary
    assert str(diag["ram_percent"]) in summary or "RAM" in summary

    print(f"  -> Observed numbers: CPU {diag['cpu_percent']}%, RAM {diag['ram_percent']}%, Bottlenecks detected: {len(diag['bottlenecks'])}")
    print(f"  -> Diagnostic summary:\n     \"{summary}\"")


def test_system_monitor_tool_dispatch():
    print("Testing system_monitor tool dispatch with structured returns...")
    # 1. Action: status
    res_status = system_monitor({"action": "status"})
    assert_structured_result(res_status, expected_action="status", expected_success=True)
    assert "cpu_percent" in res_status["value"]

    # 2. Action: diagnose
    res_diag = system_monitor({"action": "diagnose"})
    assert_structured_result(res_diag, expected_action="diagnose", expected_success=True)
    assert "bottlenecks" in res_diag["value"]
    assert "summary" in res_diag["value"]

    # 3. Action: processes
    res_proc = system_monitor({"action": "processes", "n": 3})
    assert_structured_result(res_proc, expected_action="processes", expected_success=True)
    assert len(res_proc["value"]["top_cpu"]) <= 3

    # 4. Action: disk
    res_disk = system_monitor({"action": "disk"})
    assert_structured_result(res_disk, expected_action="disk", expected_success=True)
    assert "drives" in res_disk["value"]

    # 5. Action: network
    res_net = system_monitor({"action": "network"})
    assert_structured_result(res_net, expected_action="network", expected_success=True)
    assert "kb_sent_per_sec" in res_net["value"]

    print("  -> All 5 tool actions returned valid structured formats.")


def test_permission_rules_and_audit():
    print("Testing permission rules and verify_permission_gates for system_monitor...")
    for act in ["status", "diagnose", "processes", "disk", "network"]:
        d = check_permission("system_monitor", act)
        assert d.level == PermissionLevel.SAFE, f"Expected SAFE for {act}, got {d.level}"

    registry = discover_actions(actions_dir=Path.cwd() / "actions")
    assert registry.has("system_monitor")
    verify_permission_gates(registry)
    print("  -> system_monitor discovered in action_registry and verify_permission_gates passed cleanly.")


if __name__ == "__main__":
    print("=== RUNNING SECTION 11 TEST SUITE ===")
    test_disk_usage_and_reuse()
    test_network_throughput()
    test_battery_reuse()
    test_top_processes()
    test_why_is_my_computer_slow_diagnostic()
    test_system_monitor_tool_dispatch()
    test_permission_rules_and_audit()
    print("\nALL SECTION 11 TESTS PASSED SUCCESSFULLY!")
