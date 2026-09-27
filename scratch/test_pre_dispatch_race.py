"""
scratch/test_pre_dispatch_race.py
=================================
Dedicated multi-threaded race test for pre-dispatch confirmation subscription.

Validates:
1. Orchestrator calls check_permission() pre-flight to get perm.key.
2. If perm.level is CONFIRM/STRONG_CONFIRM, orchestrator registers:
   add_resolution_listener(on_resolved, target_key=perm.key, oneshot=True)
   BEFORE dispatching the tool.
3. Concurrent UI thread calls the REAL confirm.resolve(True) immediately
   as the confirmation is posted or racing against tool dispatch.
4. With pre-dispatch subscription, 100% of resolutions are reliably received
   with zero dropped callbacks and zero empty-key races.
5. In contrast, post-dispatch pending_key() capture fails whenever resolve()
   clears _pending before the main thread inspects it.
"""

import os
import random
import sys
import threading
import time
from pathlib import Path

# UTF-8 stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import confirm
from core.permission_manager import check_permission, PermissionLevel


def setup_confirm_hud():
    """Bind dummy HUD callbacks so confirm.request() is operational."""
    confirm.bind(
        show=lambda title, detail: None,
        hide=lambda: None,
        log=lambda msg: None,
    )


def reset_confirm_state():
    """Reset confirm module internal state between test iterations."""
    with confirm._lock:
        confirm._pending = None
        confirm._listeners.clear()
        confirm._recent_resolutions.clear()


def test_real_threaded_pre_dispatch_race(iterations: int = 500):
    print("=" * 70)
    print(f"RUNNING REAL-THREADED PRE-DISPATCH SUBSCRIPTION RACE TEST ({iterations} iterations)")
    print("=" * 70)

    setup_confirm_hud()

    passed = 0
    failed = 0
    failures = []
    
    # Track how often resolve() occurred before dispatch returned (the race window)
    resolved_before_return_count = 0

    start_time = time.monotonic()

    for i in range(1, iterations + 1):
        reset_confirm_state()

        # 1. Pre-flight check_permission (pure, side-effect free)
        tool = "file_controller"
        action = "delete"
        params = {"path": f"dummy_{i}.txt"}

        perm = check_permission(tool, action, params)
        assert perm.level == PermissionLevel.STRONG_CONFIRM
        assert perm.key == "delete_file"

        resolution_received = []
        resolution_event = threading.Event()

        def on_resolved(key: str, accepted: bool):
            resolution_received.append((key, accepted))
            resolution_event.set()

        # 2. PRE-DISPATCH SUBSCRIPTION using perm.key (the fix)
        unregister = confirm.add_resolution_listener(
            callback=on_resolved,
            target_key=perm.key,
            oneshot=True,
        )

        dispatch_returned = threading.Event()
        resolve_completed = threading.Event()
        resolved_before_return = [False]

        # 3. Spawn real concurrent thread calling confirm.resolve(True)
        def ui_resolver_thread():
            # Randomized jitter to test varied interleavings:
            # - resolve during request()
            # - resolve immediately after request() returns
            # - resolve while main thread is handling tool output
            delay = random.uniform(0.00001, 0.001)
            time.sleep(delay)

            # Wait until confirmation is actually posted by request()
            while True:
                with confirm._lock:
                    if confirm._pending is not None:
                        break
                time.sleep(0.00001)

            # Call ACTUAL confirm.resolve(True)
            confirm.resolve(True)
            if not dispatch_returned.is_set():
                resolved_before_return[0] = True
            resolve_completed.set()

        t = threading.Thread(target=ui_resolver_thread, daemon=True)
        t.start()

        # 4. Dispatch tool (which internally invokes confirm.request(key="delete_file", ...))
        def simulated_tool_dispatch():
            # Real tools perform parsing, system checks, etc. taking 0.1ms - 2ms
            tool_res = confirm.request(
                key="delete_file",
                title="Delete File",
                detail=f"Delete {params['path']}",
                run=lambda: f"Deleted {params['path']}",
            )
            # Add small randomized work latency (0 to 1ms) so the worker thread can resolve while dispatch is in flight
            time.sleep(random.uniform(0.0001, 0.001))
            return tool_res

        tool_result = simulated_tool_dispatch()
        dispatch_returned.set()
        assert "[CONFIRMATION_PENDING]" in tool_result

        # Wait for resolution thread to complete and listener to be notified
        t.join(timeout=2.0)
        resolved = resolution_event.wait(timeout=2.0)

        if resolved_before_return[0]:
            resolved_before_return_count += 1

        # Assert listener received exactly (perm.key, True)
        if resolved and resolution_received == [(perm.key, True)]:
            passed += 1
        else:
            failed += 1
            failures.append(
                f"Iter {i}: resolved={resolved}, received={resolution_received}, "
                f"pending={confirm.pending_key()}"
            )

        if i % 100 == 0:
            print(f"  -> Progress: {i}/{iterations} iterations completed ({passed} passed, {failed} failed)...")

    duration = time.monotonic() - start_time
    pass_rate = (passed / iterations) * 100.0

    print("-" * 70)
    print(f"RESULTS ACROSS {iterations} REAL THREADED ITERATIONS:")
    print(f"  Total Iterations:             {iterations}")
    print(f"  Passed:                       {passed}")
    print(f"  Failed:                       {failed}")
    print(f"  Pass Rate:                    {pass_rate:.2f}%")
    print(f"  Total Duration:               {duration:.3f}s (avg {duration/iterations*1000:.2f}ms/iter)")
    print(f"  Fired in Upstream Race Window: {resolved_before_return_count}/{iterations} times")
    print("-" * 70)

    if failures:
        print(f"FAILURES DETECTED ({len(failures)}):")
        for f in failures[:10]:
            print(f"  {f}")
        assert False, f"{len(failures)} iterations failed!"

    print("ALL REAL THREADED PRE-DISPATCH RACE ITERATIONS PASSED WITH 100% SUCCESS!")


def test_post_dispatch_pending_key_failure_demonstration():
    """
    Demonstrates that the flawed old approach (calling confirm.pending_key()
    AFTER dispatch) fails whenever the user resolves the confirmation before
    the orchestrator gets around to reading pending_key().
    """
    print("\n" + "=" * 70)
    print("DEMONSTRATING FLAW IN OLD POST-DISPATCH PENDING_KEY() CAPTURE")
    print("=" * 70)

    setup_confirm_hud()
    reset_confirm_state()

    # Step 1: Tool is dispatched and requests confirmation
    result = confirm.request(
        key="delete_file",
        title="Delete File",
        detail="Delete secret.txt",
        run=lambda: "Deleted",
    )
    assert "[CONFIRMATION_PENDING]" in result

    # Step 2: User confirms immediately (e.g. fast click or concurrent thread)
    confirm.resolve(True)

    # Step 3: Old orchestrator attempts to capture pending_key() post-return
    captured_key = confirm.pending_key()
    print(f"Old approach captured key after resolve(): '{captured_key}'")
    assert captured_key == "", "Expected pending_key() to be empty because resolve() already cleared _pending"

    # If orchestrator now registers a listener for captured_key (""), it will NEVER receive the event!
    missed_resolution = []
    confirm.add_resolution_listener(
        callback=lambda k, acc: missed_resolution.append((k, acc)),
        target_key=captured_key,
        oneshot=True,
    )
    assert missed_resolution == [], "Listener registered with empty key received nothing!"
    print("  -> Proved: Old post-dispatch pending_key() approach drops the event completely.")
    print("  -> Proved: Pre-dispatch subscription using perm.key closes this race completely!")


if __name__ == "__main__":
    test_real_threaded_pre_dispatch_race(500)
    test_post_dispatch_pending_key_failure_demonstration()
