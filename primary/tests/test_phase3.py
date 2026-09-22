"""
ProAssist AI - Phase 3 Automated Test Suite
Validates Desktop & Web Action Agent:
1. Open application intent detection.
2. Calculator intent.
3. Notepad intent.
4. Chrome/browser intent.
5. File Explorer intent.
6. Google search parsing.
7. YouTube search parsing.
8. YouTube play parsing.
9. Natural language variations.
10. Calculator safe evaluation.
11. Application allowlist.
12. Arbitrary shell command rejection.
13. Unknown command safety fallback.
14. Multi-step command parsing.
15. Phase 1 authentication requirement.
16. Phase 2 integration.
17. Existing email feature preservation.
18. Safe exit behavior.
19. Failed application launch handling.
20. Failed browser action handling.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from phase3.config import ALLOWED_APPLICATIONS, ALLOWED_WEBSITES, ALLOWED_FOLDERS
from phase3.app_launcher import AppLauncher
from phase3.browser_controller import BrowserController
from phase3.web_actions import WebActions
from phase3.desktop_controller import DesktopController, SafeMathEvaluator
from phase3.phase3_router import Phase3Router
from phase2.command_router import CommandRouter


def test_1_open_app_intent():
    print("\n--- TEST 1: Open Application Intent Detection ---")
    router = Phase3Router()
    apps = [
        ("open chrome", "open_application", "Opening Chrome."),
        ("launch edge", "open_application", "Opening Microsoft Edge."),
        ("start firefox", "open_application", "Opening Firefox."),
        ("open calculator", "open_application", "Opening Calculator."),
        ("launch notepad", "open_application", "Opening Notepad."),
    ]
    for cmd, exp_intent, exp_resp in apps:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"], f"Command '{cmd}' should be handled"
        assert res["intent"] == exp_intent, f"Expected {exp_intent}, got {res['intent']}"
        assert res["response"] == exp_resp, f"Expected {exp_resp}, got {res['response']}"
        print(f"  '{cmd}' -> Intent: {res['intent']} | Response: '{res['response']}'")
    print(">> [PASS] Open application intent detection verified.")


def test_2_calculator_intent():
    print("\n--- TEST 2: Calculator Intent ---")
    router = Phase3Router()
    res = router.execute("calculate 25 times 40", dry_run=True)
    assert res["handled"]
    assert res["intent"] == "calculate"
    assert res["response"] == "The answer is 1000."
    print(f"  'calculate 25 times 40' -> Response: '{res['response']}'")
    print(">> [PASS] Calculator intent detection verified.")


def test_3_notepad_intent():
    print("\n--- TEST 3: Notepad Intent ---")
    router = Phase3Router()
    res = router.execute("type Project completed in notepad", dry_run=True)
    assert res["handled"]
    assert res["intent"] == "type_in_notepad"
    assert "Typing that into Notepad" in res["response"]
    print(f"  'type Project completed in notepad' -> Response: '{res['response']}'")
    print(">> [PASS] Notepad typing intent verified.")


def test_4_chrome_browser_intent():
    print("\n--- TEST 4: Chrome and Browser Intent ---")
    router = Phase3Router()
    res1 = router.execute("open chrome", dry_run=True)
    assert res1["handled"] and "Chrome" in res1["response"]
    res2 = router.execute("open browser", dry_run=True)
    assert res2["handled"] and "browser" in res2["response"].lower()
    print(f"  'open chrome' -> '{res1['response']}' | 'open browser' -> '{res2['response']}'")
    print(">> [PASS] Chrome and browser intent verified.")


def test_5_file_explorer_intent():
    print("\n--- TEST 5: File Explorer and Folder Intent ---")
    router = Phase3Router()
    folders = [
        ("open downloads", "Opening Downloads."),
        ("open documents", "Opening Documents."),
        ("open desktop", "Opening Desktop."),
        ("open file explorer", "Opening File explorer."),
    ]
    for cmd, exp_resp in folders:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"]
        assert res["intent"] == "open_folder"
        assert exp_resp.lower() in res["response"].lower()
        print(f"  '{cmd}' -> '{res['response']}'")
    print(">> [PASS] File Explorer and folders verified.")


def test_6_google_search_parsing():
    print("\n--- TEST 6: Google Search Parsing ---")
    router = Phase3Router()
    queries = [
        ("search google for Python tutorials", "Python tutorials"),
        ("google search Java interview questions", "Java interview questions"),
        ("search the web for weather", "weather"),
        ("look up Python decorators", "Python decorators"),
    ]
    for cmd, expected_q in queries:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"]
        assert res["intent"] == "google_search"
        assert expected_q.lower() in res["response"].lower()
        print(f"  '{cmd}' -> Response: '{res['response']}'")
    print(">> [PASS] Google search parsing verified.")


def test_7_youtube_search_parsing():
    print("\n--- TEST 7: YouTube Search Parsing ---")
    router = Phase3Router()
    queries = [
        ("search youtube for Arijit Singh", "Arijit Singh"),
        ("find Believer on youtube", "Believer"),
        ("search youtube for java tutorials", "java tutorials"),
    ]
    for cmd, expected_q in queries:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"]
        assert res["intent"] == "youtube_search"
        assert expected_q.lower() in res["response"].lower()
        print(f"  '{cmd}' -> Response: '{res['response']}'")
    print(">> [PASS] YouTube search parsing verified.")


def test_8_youtube_play_parsing():
    print("\n--- TEST 8: YouTube Play Parsing ---")
    router = Phase3Router()
    res1 = router.execute("play Believer on youtube", dry_run=True)
    assert res1["handled"]
    assert res1["intent"] == "youtube_play"
    assert "Believer" in res1["response"]
    print(f"  'play Believer on youtube' -> '{res1['response']}'")

    res2 = router.execute("play the first result", dry_run=True)
    assert res2["handled"]
    assert res2["intent"] == "youtube_play"
    assert "Playing it." in res2["response"]
    print(f"  'play the first result' -> '{res2['response']}'")
    print(">> [PASS] YouTube play parsing verified.")


def test_9_natural_language_variations():
    print("\n--- TEST 9: Natural Language Variations ---")
    router = Phase3Router()
    variations = [
        ("can you please open chrome", "Opening Chrome."),
        ("please launch calculator", "Opening Calculator."),
        ("could you calculate 10 times 5", "The answer is 50."),
        ("can you search google for machine learning", "Searching Google for machine learning."),
    ]
    for cmd, exp_resp in variations:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"]
        assert exp_resp.lower() in res["response"].lower()
        print(f"  '{cmd}' -> '{res['response']}'")
    print(">> [PASS] Natural language variations handled accurately.")


def test_10_calculator_safe_evaluation():
    print("\n--- TEST 10: Safe Mathematical Evaluation ---")
    dc = DesktopController()
    cases = [
        ("calculate 25 plus 40", "The answer is 65."),
        ("calculate 100 minus 35", "The answer is 65."),
        ("calculate 10 times 5", "The answer is 50."),
        ("calculate 100 divided by 4", "The answer is 25."),
        ("what is 25 percent of 800", "The answer is 200."),
        ("what is 2 to the power of 5", "The answer is 32."),
    ]
    for spoken, expected in cases:
        success, resp = dc.calculate(spoken)
        assert success
        assert resp == expected
        print(f"  '{spoken}' -> '{resp}'")

    # Division by zero safety
    ok_div, div_resp = dc.calculate("calculate 100 divided by 0")
    assert not ok_div
    assert "zero" in div_resp.lower()
    print("  Division by zero: safely rejected.")

    # Arbitrary code injection prevention
    expr_injection = SafeMathEvaluator.parse_spoken_math("__import__('os').system('dir')")
    assert "__import__" not in expr_injection
    print("  Code injection attempt: safely stripped.")
    print(">> [PASS] Safe mathematical evaluation verified.")


def test_11_application_allowlist():
    print("\n--- TEST 11: Application Allowlist Enforcement ---")
    launcher = AppLauncher()
    assert launcher.is_allowed("chrome")
    assert launcher.is_allowed("calculator")
    assert launcher.is_allowed("notepad")
    assert launcher.is_allowed("edge")
    assert launcher.is_allowed("explorer")

    # Disallowed applications
    assert not launcher.is_allowed("malware.exe")
    assert not launcher.is_allowed("powershell.exe")
    assert not launcher.is_allowed("cmd.exe")

    success, resp = launcher.launch("unauthorized_app", dry_run=True)
    assert not success
    assert "not on the allowed applications list" in resp
    print(">> [PASS] Application allowlist strictly enforced.")


def test_12_arbitrary_shell_command_rejection():
    print("\n--- TEST 12: Arbitrary Shell Command Rejection ---")
    router = Phase3Router()
    threats = [
        "run this powershell command remove files",
        "execute cmd.exe /c format c:",
        "delete everything on computer",
        "os.system('del *.*')",
        "run python code to delete system32",
    ]
    for threat in threats:
        res = router.execute(threat, dry_run=True)
        assert not res["handled"] or res["intent"] == "unknown"
        assert not res["executed"]
        print(f"  Threat '{threat}' -> Rejected safely: {res['status']}")
    print(">> [PASS] Arbitrary shell commands strictly rejected.")


def test_13_unknown_command_fallback():
    print("\n--- TEST 13: Unknown Command Safety Fallback ---")
    router = Phase3Router()
    res = router.execute("quantum teleportation protocol engage", dry_run=True)
    assert not res["handled"]
    assert res["intent"] == "unknown"
    assert "don't know how to handle that command yet" in res["response"]
    print(f"  Unknown command handled safely: '{res['response']}'")
    print(">> [PASS] Unknown command fallback verified.")


def test_14_multi_step_command_parsing():
    print("\n--- TEST 14: Multi-Step Command Parsing ---")
    router = Phase3Router()
    res1 = router.execute("open youtube and search for Believer", dry_run=True)
    assert res1["handled"]
    assert res1["intent"] == "youtube_search"
    assert "Believer" in res1["response"]
    print(f"  'open youtube and search for Believer' -> '{res1['response']}'")

    res2 = router.execute("open chrome and search google for python tutorials", dry_run=True)
    assert res2["handled"]
    assert res2["intent"] == "google_search"
    assert "python tutorials" in res2["response"]
    print(f"  'open chrome and search google for python tutorials' -> '{res2['response']}'")
    print(">> [PASS] Multi-step command workflows verified.")


def test_15_phase1_authentication_requirement():
    print("\n--- TEST 15: Phase 1 Authentication Requirement ---")
    import numpy as np
    from voice_auth.verifier import VoiceVerifier
    verifier = VoiceVerifier()
    created_temp = False
    if not verifier.is_enrolled():
        dummy_vp = np.zeros(256, dtype=np.float32)
        dummy_vp[0] = 1.0
        config.VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)
        np.save(config.VOICEPRINT_PATH, dummy_vp)
        verifier.load_voiceprint()
        created_temp = True
        assert verifier.is_enrolled(), "Phase 1 voiceprint must be enrolled"
        assert verifier.threshold == 0.50, "Threshold must remain 0.50"
        assert config.VOICE_SIMILARITY_THRESHOLD == 0.50, "Config threshold must remain 0.50"
    finally:
        if created_temp and config.VOICEPRINT_PATH.exists():
            os.remove(config.VOICEPRINT_PATH)
    print("  Phase 1 voiceprint and 0.50 threshold confirmed active.")
    print(">> [PASS] Phase 1 authentication requirement preserved.")




def test_16_phase2_integration():
    print("\n--- TEST 16: Phase 2 Command Router Integration ---")
    p2_router = CommandRouter()

    # Verify Phase 2 core commands still work directly
    res_time = p2_router.execute("what time is it")
    assert res_time["intent"] == "get_time"

    # Verify Phase 3 command flows seamlessly through CommandRouter
    res_chrome = p2_router.execute("open chrome", dry_run=True)
    assert res_chrome["intent"] == "open_application"
    assert "Chrome" in res_chrome["response"]

    # Verify Phase 3 calculation flows through CommandRouter
    res_calc = p2_router.execute("calculate 25 times 40", dry_run=True)
    assert res_calc["intent"] == "calculate"
    assert res_calc["response"] == "The answer is 1000."
    print("  Phase 2 commands and Phase 3 actions seamlessly routed.")
    print(">> [PASS] Phase 2 integration verified.")


def test_17_existing_email_feature():
    print("\n--- TEST 17: Existing Email Feature Preservation ---")
    p2_router = CommandRouter()
    res = p2_router.execute("write an email to Rahul", dry_run=True)
    assert res["intent"] == "email_compose"
    assert res["contact_found"]
    assert res["recipient_name"] == "Rahul"
    print("  Email routing intact: 'write an email to Rahul' -> email_compose.")
    print(">> [PASS] Email feature preserved.")


def test_18_safe_exit_behavior():
    print("\n--- TEST 18: Safe Exit Behavior ---")
    p2_router = CommandRouter()
    exits = ["stop", "go to sleep", "that's all", "exit", "bye", "goodbye", "quit"]
    for exit_cmd in exits:
        res = p2_router.execute(exit_cmd)
        assert res["intent"] == "exit"
        assert res["response"] == "Going back to wake-word listening."
    print("  All exit phrases return 'Going back to wake-word listening.'")
    print(">> [PASS] Safe exit behavior verified.")


def test_19_failed_app_launch_handling():
    print("\n--- TEST 19: Failed Application Launch Handling ---")
    launcher = AppLauncher()
    # Mock subprocess.Popen to simulate an OS-level launch failure
    with patch("subprocess.Popen", side_effect=OSError("Resource unavailable")):
        success, resp = launcher.launch("chrome", dry_run=False)
        assert not success
        assert "couldn't open" in resp.lower()
        print(f"  Simulated launch failure handled safely: '{resp}'")
    print(">> [PASS] Failed application launch handling verified.")


def test_20_failed_browser_action_handling():
    print("\n--- TEST 20: Failed Browser Action Handling ---")
    browser = BrowserController()
    with patch("webbrowser.open", side_effect=Exception("Browser not found")):
        success, resp = browser.open_website("google", dry_run=False)
        assert not success
        assert "couldn't open" in resp.lower()
        print(f"  Simulated browser failure handled safely: '{resp}'")
    print(">> [PASS] Failed browser action handling verified.")


def test_21_command_router_real_action_dispatch():
    print("\n--- TEST 21: Command Router Real Action Dispatch ---")
    p2_router = CommandRouter()

    # Track calls to AppLauncher.launch
    with patch.object(p2_router.phase3_router.launcher, "launch", wraps=p2_router.phase3_router.launcher.launch) as mock_launch:
        # 1. Notepad
        res_notepad = p2_router.execute("open notepad", dry_run=True)
        assert res_notepad["status"] == "success"
        mock_launch.assert_called_with("notepad", dry_run=True)
        print("  'open notepad' dispatched to launcher.launch('notepad')")

        # 2. Chrome
        res_chrome = p2_router.execute("can you open the chrome browser", dry_run=True)
        assert res_chrome["status"] == "success"
        mock_launch.assert_called_with("chrome", dry_run=True)
        print("  'can you open the chrome browser' dispatched to launcher.launch('chrome')")

        # 3. Calculator
        res_calc = p2_router.execute("launch calculator", dry_run=True)
        assert res_calc["status"] == "success"
        mock_launch.assert_called_with("calculator", dry_run=True)
        print("  'launch calculator' dispatched to launcher.launch('calculator')")

        # 4. File Explorer
        res_exp = p2_router.execute("open file explorer", dry_run=True)
        assert res_exp["status"] == "success"
        mock_launch.assert_called_with("explorer", dry_run=True)
        print("  'open file explorer' dispatched to launcher.launch('explorer')")

    print(">> [PASS] Command router real action dispatch verified.")



def test_22_volume_control():
    print("\n--- TEST 22: Volume Control Operations ---")
    router = Phase3Router()
    from phase3.system_controller import SystemController

    # set volume to specific level
    res = router.execute("set volume to 50", dry_run=True)
    assert res["handled"], "'set volume to 50' should be handled"
    assert res["intent"] == "volume_set", f"Expected volume_set, got {res['intent']}"
    assert "50" in res["response"], f"Expected '50' in response, got: {res['response']}"
    print(f"  'set volume to 50' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # volume up
    res = router.execute("volume up", dry_run=True)
    assert res["handled"] and res["intent"] == "volume_up", f"volume up failed: {res}"
    print(f"  'volume up' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # volume down
    res = router.execute("volume down", dry_run=True)
    assert res["handled"] and res["intent"] == "volume_down", f"volume down failed: {res}"
    print(f"  'volume down' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # mute
    res = router.execute("mute", dry_run=True)
    assert res["handled"] and res["intent"] == "volume_mute", f"mute failed: {res}"
    print(f"  'mute' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # unmute
    res = router.execute("unmute", dry_run=True)
    assert res["handled"] and res["intent"] == "volume_unmute", f"unmute failed: {res}"
    print(f"  'unmute' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # SystemController dry-run directly
    sc = SystemController()
    ok, msg = sc.set_volume(75, dry_run=True)
    assert ok and "75" in msg, f"SystemController.set_volume dry-run failed: {msg}"
    ok, msg = sc.mute(dry_run=True)
    assert ok and msg == "Muted.", f"SystemController.mute dry-run failed: {msg}"
    ok, msg = sc.unmute(dry_run=True)
    assert ok and msg == "Unmuted.", f"SystemController.unmute dry-run failed: {msg}"

    print(">> [PASS] Volume control operations verified.")


def test_23_media_key_controls():
    print("\n--- TEST 23: Media Key Controls ---")
    router = Phase3Router()
    from phase3.system_controller import SystemController

    # pause music
    res = router.execute("pause music", dry_run=True)
    assert res["handled"] and res["intent"] == "media_play_pause", f"pause music failed: {res}"
    print(f"  'pause music' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # play music
    res = router.execute("play music", dry_run=True)
    assert res["handled"] and res["intent"] == "media_play_pause", f"play music failed: {res}"
    print(f"  'play music' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # next song
    res = router.execute("next song", dry_run=True)
    assert res["handled"] and res["intent"] == "media_next", f"next song failed: {res}"
    print(f"  'next song' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # skip track
    res = router.execute("skip track", dry_run=True)
    assert res["handled"] and res["intent"] == "media_next", f"skip track failed: {res}"
    print(f"  'skip track' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # previous song
    res = router.execute("previous song", dry_run=True)
    assert res["handled"] and res["intent"] == "media_prev", f"previous song failed: {res}"
    print(f"  'previous song' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # SystemController dry-run directly
    sc = SystemController()
    ok, _ = sc.media_play_pause(dry_run=True)
    assert ok, "SystemController.media_play_pause dry-run failed"
    ok, msg = sc.media_next(dry_run=True)
    assert ok and msg == "Next track.", f"SystemController.media_next dry-run failed: {msg}"
    ok, msg = sc.media_prev(dry_run=True)
    assert ok and msg == "Previous track.", f"SystemController.media_prev dry-run failed: {msg}"

    print(">> [PASS] Media key controls verified.")


def test_24_screenshot_capture():
    print("\n--- TEST 24: Screenshot Capture ---")
    router = Phase3Router()
    from phase3.system_controller import SystemController

    commands = [
        "take a screenshot",
        "take screenshot",
        "capture the screen",
        "screenshot",
    ]
    for cmd in commands:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"] and res["intent"] == "screenshot", \
            f"'{cmd}' should route to screenshot, got: {res['intent']}"
        print(f"  '{cmd}' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # SystemController dry-run
    sc = SystemController()
    ok, msg = sc.take_screenshot(dry_run=True)
    assert ok and "screenshot" in msg.lower(), f"SystemController.take_screenshot dry-run failed: {msg}"

    print(">> [PASS] Screenshot capture verified.")


def test_25_window_management():
    print("\n--- TEST 25: Window Management ---")
    router = Phase3Router()
    from phase3.system_controller import SystemController

    # minimize
    res = router.execute("minimize window", dry_run=True)
    assert res["handled"] and res["intent"] == "window_minimize", f"minimize window failed: {res}"
    print(f"  'minimize window' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # minimize (short form)
    res = router.execute("minimize", dry_run=True)
    assert res["handled"] and res["intent"] == "window_minimize", f"minimize failed: {res}"
    print(f"  'minimize' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # maximize
    res = router.execute("maximize window", dry_run=True)
    assert res["handled"] and res["intent"] == "window_maximize", f"maximize window failed: {res}"
    print(f"  'maximize window' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # close window
    res = router.execute("close window", dry_run=True)
    assert res["handled"] and res["intent"] == "window_close", f"close window failed: {res}"
    print(f"  'close window' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # SystemController dry-run
    sc = SystemController()
    ok, msg = sc.minimize_window(dry_run=True)
    assert ok and msg == "Window minimized.", f"minimize_window dry-run failed: {msg}"
    ok, msg = sc.maximize_window(dry_run=True)
    assert ok and msg == "Window maximized.", f"maximize_window dry-run failed: {msg}"
    ok, msg = sc.close_window(dry_run=True)
    assert ok and msg == "Window closed.", f"close_window dry-run failed: {msg}"

    print(">> [PASS] Window management verified.")


def test_26_clipboard_read():
    print("\n--- TEST 26: Clipboard Read ---")
    router = Phase3Router()
    from phase3.system_controller import SystemController

    commands = [
        "what is in my clipboard",
        "read clipboard",
        "read my clipboard",
        "clipboard content",
    ]
    for cmd in commands:
        res = router.execute(cmd, dry_run=True)
        assert res["handled"] and res["intent"] == "clipboard_read", \
            f"'{cmd}' should route to clipboard_read, got: {res}"
        print(f"  '{cmd}' -> Intent: {res['intent']} | Response: '{res['response']}'")

    # SystemController dry-run
    sc = SystemController()
    ok, msg = sc.read_clipboard(dry_run=True)
    assert ok, f"SystemController.read_clipboard dry-run failed: {msg}"

    print(">> [PASS] Clipboard read verified.")


def main():
    print("=" * 70)
    print("          PROASSIST AI - PHASE 3 AUTOMATED TEST SUITE")
    print("     Desktop & Web Action Agent: Validation & Verification")
    print("=" * 70)

    test_1_open_app_intent()
    test_2_calculator_intent()
    test_3_notepad_intent()
    test_4_chrome_browser_intent()
    test_5_file_explorer_intent()
    test_6_google_search_parsing()
    test_7_youtube_search_parsing()
    test_8_youtube_play_parsing()
    test_9_natural_language_variations()
    test_10_calculator_safe_evaluation()
    test_11_application_allowlist()
    test_12_arbitrary_shell_command_rejection()
    test_13_unknown_command_fallback()
    test_14_multi_step_command_parsing()
    test_15_phase1_authentication_requirement()
    test_16_phase2_integration()
    test_17_existing_email_feature()
    test_18_safe_exit_behavior()
    test_19_failed_app_launch_handling()
    test_20_failed_browser_action_handling()
    test_21_command_router_real_action_dispatch()
    test_22_volume_control()
    test_23_media_key_controls()
    test_24_screenshot_capture()
    test_25_window_management()
    test_26_clipboard_read()

    print("\n" + "=" * 70)
    print("      ALL 26 PHASE 3 AUTOMATED TESTS COMPLETED AND PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
