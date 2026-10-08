"""
tests/test_action_loader_and_qt_thread_safety.py
=================================================
Regression test suite covering:
1. ISSUE A: Action loader context dispatch with REAL context keys (including speak)
   across every action handler. OS calls for lock_screen, restart, and shutdown are mocked.
2. ISSUE B: Qt thread safety for UI mutations from worker threads. Confirms zero
   "killTimer" or "another thread" warnings are emitted.
"""

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import main
from main import AgentLive
from core.action_loader import discover_actions, _CTX_KEYS
from core import confirm

os.environ["QT_QPA_PLATFORM"] = "offscreen"


class TestActionLoaderContext(unittest.TestCase):
    """Verify that all actions execute via action_loader.run() with real context keys."""

    def setUp(self):
        self.actions_dir = REPO_ROOT / "actions"
        self.registry = discover_actions(self.actions_dir, logger=lambda _: None)

        class DummyPlayer:
            def __init__(self):
                self.logs = []
            def write_log(self, msg: str):
                self.logs.append(msg)

        def dummy_speak(text: str):
            pass

        self.player = DummyPlayer()
        self.real_ctx = {
            "player": self.player,
            "speak": dummy_speak,
            "response": "mock_response",
            "session_memory": {"session_id": "test_123"},
        }

    def test_ctx_keys_include_speak(self):
        """'speak' must remain present in _CTX_KEYS."""
        self.assertIn("speak", _CTX_KEYS)
        self.assertIn("speak", self.real_ctx)

    @patch("actions.computer_settings.pyautogui.hotkey")
    def test_computer_settings_lock_screen_mocked(self, mock_hotkey):
        """computer_settings(action='lock_screen') runs through action_loader with full ctx."""
        res = self.registry.run(
            "computer_settings",
            {"action": "lock_screen"},
            ctx=self.real_ctx,
        )
        self.assertNotIn("crashed", res.lower())
        self.assertNotIn("unexpected keyword argument", res.lower())
        if sys.platform == "win32":
            mock_hotkey.assert_called_with("win", "l")

    @patch("actions.computer_settings.subprocess.run")
    def test_computer_settings_restart_and_confirmation_mocked(self, mock_subproc):
        """computer_settings(action='restart') gates behind confirm.request without crash."""
        # Clean any prior pending confirmation
        with confirm._lock:
            confirm._pending = None

        mock_show = MagicMock()
        mock_hide = MagicMock()
        confirm.bind(mock_show, mock_hide)

        res = self.registry.run(
            "computer_settings",
            {"action": "restart"},
            ctx=self.real_ctx,
        )
        self.assertNotIn("crashed", res.lower())
        self.assertNotIn("unexpected keyword argument", res.lower())
        self.assertIn("CONFIRMATION_PENDING", res)

        # Resolve confirmation on worker thread and verify mocked OS call
        mock_subproc.return_value = MagicMock(returncode=0)
        confirm.resolve(True)

        # Wait briefly for worker thread to complete execution
        time.sleep(0.15)
        if sys.platform == "win32":
            mock_subproc.assert_called()
            args = mock_subproc.call_args[0][0]
            self.assertEqual(args[:3], ["shutdown", "/r", "/t"])

    @patch("actions.computer_settings.subprocess.run")
    def test_computer_settings_shutdown_mocked(self, mock_subproc):
        """computer_settings(action='shutdown') gates behind confirm.request without crash."""
        with confirm._lock:
            confirm._pending = None

        mock_show = MagicMock()
        mock_hide = MagicMock()
        confirm.bind(mock_show, mock_hide)

        res = self.registry.run(
            "computer_settings",
            {"action": "shutdown"},
            ctx=self.real_ctx,
        )
        self.assertNotIn("crashed", res.lower())
        self.assertNotIn("unexpected keyword argument", res.lower())
        self.assertIn("CONFIRMATION_PENDING", res)

        mock_subproc.return_value = MagicMock(returncode=0)
        confirm.resolve(True)
        time.sleep(0.15)
        if sys.platform == "win32":
            mock_subproc.assert_called()
            args = mock_subproc.call_args[0][0]
            self.assertEqual(args[:3], ["shutdown", "/s", "/t"])

    def test_all_actions_run_with_real_context(self):
        """Every discovered action handler must accept run() with full context without TypeError."""
        sample_parameters = {
            "browser_control": {"action": "status"},
            "code_helper": {"action": "explain", "code": "print(1)"},
            "computer_control": {"action": "key_combo", "keys": "ctrl+c"},
            "computer_settings": {"action": "volume_get"},
            "desktop_control": {"action": "stats"},
            "dev_agent": {"action": "status"},
            "file_controller": {"action": "list_files", "path": "."},
            "file_processor": {"action": "view_file", "path": "readme.md"},
            "flight_finder": {"origin": "SFO", "destination": "JFK"},
            "game_updater": {"action": "check_all"},
            "open_app": {"app_name": "notepad"},
            "reminder": {"action": "list"},
            "send_message": {"recipient": "Alice", "message": "Hi"},
            "system_monitor": {"action": "status"},
            "weather_report": {"location": "London"},
            "web_search": {"query": "python"},
            "youtube_video": {"action": "search", "query": "test"},
        }

        mock_launcher = MagicMock()
        mock_launcher.launch.return_value = (True, "123")
        with patch("actions.open_app._get_launcher", return_value=mock_launcher), \
             patch("actions.computer_control.pyautogui"), \
             patch("actions.web_search.web_search", return_value="results"):
            for name in self.registry.names():
                params = sample_parameters.get(name, {})
                res = self.registry.run(name, params, ctx=self.real_ctx)
                self.assertNotEqual(res, f"Action '{name}' is not available.")
                self.assertNotIn(
                    "unexpected keyword argument",
                    res.lower(),
                    f"Action '{name}' crashed with unexpected keyword argument when passed real ctx: {res}"
                )


class TestQtThreadSafety(unittest.TestCase):
    """Verify that UI mutations and interrupt paths from worker threads emit zero killTimer warnings."""

    def setUp(self):
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import qInstallMessageHandler

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.caught_warnings = []

        def test_msg_handler(msg_type, context, message):
            if "killTimer" in message or "another thread" in message:
                tname = threading.current_thread().name
                self.caught_warnings.append((message, tname))

        qInstallMessageHandler(test_msg_handler)

        from ui import AgentUI
        self.ui = AgentUI("face.png")
        self.ui._win._ready = True

    def test_worker_thread_mutations_emit_zero_warnings(self):
        """Worker thread executing state changes, interrupts, and phone connection triggers 0 warnings."""
        from main import AgentLive

        jarvis = AgentLive(self.ui)
        worker_errors = []

        def worker():
            try:
                # 1. State changes
                for st in ["LISTENING", "SPEAKING", "THINKING", "WORKING", "MUTED", "SLEEPING"]:
                    self.ui.set_state(st)
                    time.sleep(0.01)

                # 2. Speaking toggles
                self.ui.start_speaking()
                time.sleep(0.01)
                self.ui.stop_speaking()
                time.sleep(0.01)

                # 3. Phone mic active
                self.ui.set_phone_mic_active(True)
                time.sleep(0.01)
                self.ui.set_phone_mic_active(False)
                time.sleep(0.01)

                # 4. Viseme reset
                self.ui.reset_visemes()
                self.ui._hide_confirm_banner()

                # 5. Interrupt simulation
                jarvis.interrupt()
                time.sleep(0.01)

                # 6. Remote overlay connection
                self.ui.notify_phone_connected()
                time.sleep(0.01)

                # 7. Floating island transitions
                if hasattr(self.ui._win, "_floating_island") and self.ui._win._floating_island:
                    fi = self.ui._win._floating_island
                    fi.set_view_state("secondary")
                    time.sleep(0.02)
                    fi.set_view_state("primary")
                    time.sleep(0.02)
                    fi.on_state_changed("SPEAKING")
                    time.sleep(0.01)
                    fi.on_state_changed("LISTENING")
                    time.sleep(0.01)
            except Exception as e:
                worker_errors.append(e)

        th = threading.Thread(target=worker, name="QtWorkerTestThread")
        th.start()

        start = time.time()
        while th.is_alive() or time.time() - start < 1.0:
            self.app.processEvents()
            time.sleep(0.01)

        th.join()

        self.assertEqual(worker_errors, [], f"Worker thread encountered exceptions: {worker_errors}")
        self.assertEqual(
            self.caught_warnings,
            [],
            f"Expected 0 killTimer warnings, but caught {len(self.caught_warnings)}: {self.caught_warnings}"
        )


if __name__ == "__main__":
    unittest.main()
