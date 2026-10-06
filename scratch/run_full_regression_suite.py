"""
scratch/run_full_regression_suite.py
====================================
Master runner executing all 16 regression test suites in isolated subprocesses.
Ensures zero cross-suite global state leakage (confirm._pending, HUD bindings, mocks).
"""

import subprocess
import sys
import time
from pathlib import Path

# UTF-8 stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_SUITES = [
    # Item 1: Centralized Observability & ActionLogger
    ("Item 1: ActionLogger Observability", [sys.executable, "-m", "pytest", "-v", "scratch/test_observability_logging.py"]),
    # Item 1: Memory Scrubbing
    ("Item 1: Memory Scrubbing", [sys.executable, "-m", "pytest", "-v", "scratch/test_memory_scrubbing.py"]),
    # Item 3: Computer Control Retry & Backoff
    ("Item 3: Computer Control Retry", [sys.executable, "-m", "pytest", "-v", "scratch/test_computer_control_retry.py"]),
    # Item 4: Live AgentContext State
    ("Item 4: AgentContext State", [sys.executable, "-m", "pytest", "-v", "scratch/test_agent_context.py"]),
    # Phase 2: Desktop Gating
    ("Phase 2: Desktop Gating", [sys.executable, "-m", "pytest", "-v", "scratch/test_desktop_control_gates.py"]),
    # Phase 2: File Controller Bulk Operations
    ("Phase 2: File Controller Bulk", [sys.executable, "-m", "pytest", "-v", "scratch/test_file_controller_bulk.py"]),
    # Phase 2: Browser Control Gates
    ("Phase 2: Browser Control Gates", [sys.executable, "-m", "pytest", "-v", "scratch/test_browser_control_gates.py"]),
    # Phase 2: Application Control Lifecycle
    ("Phase 2: Application Control", [sys.executable, "-m", "pytest", "-v", "scratch/test_application_control.py"]),
    # Phase 2: Computer Settings Status
    ("Phase 2: Computer Settings Status", [sys.executable, "-m", "pytest", "-v", "scratch/test_computer_settings_status.py"]),
    # Phase 2: Non-Browser Download Interception
    ("Phase 2: Non-Browser Download", [sys.executable, "-m", "pytest", "-v", "scratch/test_non_browser_download_gate.py"]),
    # Sub-Phase 5A: Planner Model & Schema Validation
    ("Sub-Phase 5A: Planner Model & Pre-Flight", [sys.executable, "scratch/test_planner_model.py"]),
    # Sub-Phase 5B: Pre-Dispatch Race Window Fix (500 iterations)
    ("Sub-Phase 5B: Pre-Dispatch Race Window", [sys.executable, "scratch/test_pre_dispatch_race.py"]),
    # Sub-Phase 5B: Reentrancy Token Fencing Guard
    ("Sub-Phase 5B: Reentrancy Fencing Guard", [sys.executable, "scratch/test_forced_worst_case_reentrancy.py"]),
    # Sub-Phase 5B: Multi-Pause Real-Threaded Race (100 iterations)
    ("Sub-Phase 5B: Multi-Pause Race", [sys.executable, "scratch/test_multi_pause_race.py"]),
    # Sub-Phase 5B: PlanExecutor Execution Suite
    ("Sub-Phase 5B: PlanExecutor Execution Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_orchestrator_execution.py"]),
    # Sub-Phase 5C: Live Integration & Voice Loop Wiring
    ("Sub-Phase 5C: Live Integration Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_subphase_5c_integration.py"]),
    # Section 17 Stage 1: AgentTool AST & Dual Discovery Suite
    ("Section 17: AgentTool AST & Dual Discovery", [sys.executable, "-m", "pytest", "-v", "scratch/test_agent_tool_ast_regression.py"]),
    # Audit Gap Closure: Code Helper Security Gates & AgentTool
    ("Code Helper Security Gates & AgentTool", [sys.executable, "-m", "pytest", "-v", "scratch/test_code_helper_gates.py"]),
    # Section 17: Dev Agent Smoke Suite
    ("Section 17: Dev Agent Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_dev_agent_smoke.py"]),
    # Section 17: Weather Report Smoke Suite
    ("Section 17: Weather Report Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_weather_report_smoke.py"]),
    # Section 17: YouTube Video Smoke Suite
    ("Section 17: YouTube Video Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_youtube_video_smoke.py"]),
    # Section 17: Web Search Smoke Suite
    ("Section 17: Web Search Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_web_search_smoke.py"]),
    # Section 17: Flight Finder Smoke Suite
    ("Section 17: Flight Finder Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_flight_finder_smoke.py"]),
    # Section 17: Game Updater Smoke Suite
    ("Section 17: Game Updater Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_game_updater_smoke.py"]),
    # Section 17: Send Message Smoke Suite
    ("Section 17: Send Message Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_send_message_smoke.py"]),
    # Section 17: File Processor Smoke Suite
    ("Section 17: File Processor Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_file_processor_smoke.py"]),
    # Section 17: Computer Control Smoke Suite
    ("Section 17: Computer Control Smoke Suite", [sys.executable, "-m", "pytest", "-v", "scratch/test_computer_control_smoke.py"]),
    # Task 1: Phone Audio Output & Routing
    ("Task 1: Phone Audio Output & Routing", [sys.executable, "-m", "unittest", "tests/test_phone_audio_output.py"]),
    # Task 1: Mobile Audio Client JS & Playwright UI Tests
    ("Task 1: Mobile Audio Client JS & UI", [sys.executable, "tests/verify_mobile_audio_ui.py"]),
]

def main():
    print("=" * 80)
    print("RUNNING COMPLETE MARK LIV REGRESSION SUITE ACROSS ALL PHASES & SUB-PHASES")
    print("=" * 80)

    overall_start = time.time()
    results = []

    for name, cmd in TEST_SUITES:
        print(f"\n>> Running: {name} ...")
        t0 = time.time()
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - t0
        passed = (proc.returncode == 0)

        status_str = "PASSED" if passed else "FAILED"
        print(f"  [{status_str}] in {elapsed:.2f}s")
        if not passed:
            print("  --- STDOUT ---")
            print(proc.stdout[-800:])
            print("  --- STDERR ---")
            print(proc.stderr[-800:])

        results.append((name, passed, elapsed))

    overall_elapsed = time.time() - overall_start

    total_suites = len(results)
    passed_suites = sum(1 for _, p, _ in results if p)

    print("\n" + "=" * 80)
    print(f"REGRESSION SUMMARY ACROSS ALL {total_suites} SUITES")
    print("=" * 80)

    for name, passed, elapsed in results:
        sym = "[PASS]" if passed else "[FAIL]"
        print(f"  {sym} {name:<45} ({elapsed:6.2f}s)")

    print("-" * 80)
    print(f"Total Suites: {total_suites} | Passed: {passed_suites} | Failed: {total_suites - passed_suites}")
    print(f"Total Duration: {overall_elapsed:.2f}s")
    print("=" * 80)

    if passed_suites == total_suites:
        print(f"ALL {total_suites} TEST SUITES PASSED WITH 100% SUCCESS! ZERO REGRESSIONS!")
        return 0
    else:
        print("SOME TEST SUITES FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
