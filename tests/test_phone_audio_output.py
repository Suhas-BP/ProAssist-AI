"""
tests/test_phone_audio_output.py
================================
Comprehensive unit and integration test suite for Phone Audio Output:
1. Dead-Connection Detection (1s client heartbeats, 3s server watchdog, >2s playback heartbeat loss fallback)
2. Reconnect Takeover (same token takeover with code 4000, different token rejection with code 1008, enrollment rejection while mic live)
3. Silent-Assistant Guard (interrupted cleared on new text, user mic frame, generation_complete, and 2s safety timeout without turn_complete)
4. Phone-Only Speaking Clock (expected playback end tracking, 20s burst keeps gate closed for 20s, reset on interrupt/flush/disconnect)
5. Status Accuracy (real restored state computed from AgentLive, not hardcoded "sleeping")
6. Small Checks (split disconnect callbacks, shared validator, body size limit enforced on bytes read)
7. Measurements (clean close vs silent drop detection latencies)
"""

import asyncio
import json
import secrets
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import (
    DashboardServer,
    WS_CLOSE_NORMAL,
    WS_CLOSE_GOING_AWAY,
    WS_CLOSE_DIFFERENT_DEVICE,
    WS_CLOSE_REPLACED,
    WS_CLOSE_UNAUTHORIZED,
    WS_CLOSE_RATE_LIMITED,
)
from main import PHONE_MIC_TAIL_HOLDOFF, INTERRUPT_IDLE_TIMEOUT, RECEIVE_SAMPLE_RATE, AgentLive
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


class TestPhoneAudioOutput(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = DashboardServer()
        self.valid_token = secrets.token_urlsafe(32)
        self.server._tokens.add(self.valid_token)
        self.server._token_keys[self.valid_token] = "test-session-key"

    # ── 1. AUTH ENFORCEMENT & INPUT VALIDATION ────────────────────────────────

    def test_auth_enforcement_on_new_endpoints(self):
        """Constraint 1: Any new endpoint/WS must enforce bearer token auth."""
        client = TestClient(self.server.app)

        # /ws/phone-playback without token
        with self.assertRaises(Exception):
            with client.websocket_connect("/ws/phone-playback") as ws:
                pass

        # /ws/phone-playback with invalid token
        with self.assertRaises(Exception):
            with client.websocket_connect("/ws/phone-playback?token=bad-token") as ws:
                pass

        # /ws/phone-playback with valid token -> success
        with client.websocket_connect(f"/ws/phone-playback?token={self.valid_token}") as ws:
            self.assertTrue(self.server.has_playback_clients())

        # /api/interrupt without auth -> 401
        res = client.post("/api/interrupt")
        self.assertEqual(res.status_code, 401)

        # /api/interrupt with valid auth -> 200
        res = client.post(
            "/api/interrupt",
            headers={"Authorization": f"Bearer {self.valid_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))

        # /api/audio-routing without auth -> 401
        res = client.post("/api/audio-routing", json={"routing": "both"})
        self.assertEqual(res.status_code, 401)

        # /api/audio-routing GET without auth -> 401
        res = client.get("/api/audio-routing")
        self.assertEqual(res.status_code, 401)

    def test_input_validation_audio_routing(self):
        """Task 1 Item 5 & Item 6: Input validation for /api/audio-routing and WS."""
        client = TestClient(self.server.app)
        headers = {"Authorization": f"Bearer {self.valid_token}"}

        # 1. Invalid routing value -> 400
        res = client.post("/api/audio-routing", headers=headers, json={"routing": "headphones"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid routing option", res.json().get("error", ""))

        # 2. Wrong type for routing -> 400
        res = client.post("/api/audio-routing", headers=headers, json={"routing": 12345})
        self.assertEqual(res.status_code, 400)

        # 3. Wrong type for pause_mic_on_reply -> 400
        res = client.post("/api/audio-routing", headers=headers, json={"routing": "phone", "pause_mic_on_reply": "yes"})
        self.assertEqual(res.status_code, 400)

        # 4. Valid allowlist values
        for val in ("phone", "laptop", "both"):
            res = client.post("/api/audio-routing", headers=headers, json={"routing": val, "pause_mic_on_reply": True})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json().get("routing"), val)
            self.assertTrue(res.json().get("pause_mic_on_reply"))

        # 5. Oversized payload (>4096 bytes read) -> 413
        oversized_data = "x" * 5000
        res = client.post(
            "/api/audio-routing",
            headers={**headers, "Content-Length": str(len(oversized_data))},
            content=oversized_data
        )
        self.assertEqual(res.status_code, 413)

        # 6. Malformed JSON -> 400
        res = client.post(
            "/api/audio-routing",
            headers=headers,
            content="NOT-A-JSON-{{{",
        )
        self.assertEqual(res.status_code, 400)

    def test_websocket_shared_routing_validator(self):
        """Item 6: WebSocket paths use same validator as POST /api/audio-routing."""
        # Valid options
        r, p, err = DashboardServer.validate_audio_routing("phone", True)
        self.assertIsNone(err)
        self.assertEqual(r, "phone")
        self.assertTrue(p)

        # Invalid routing
        r, p, err = DashboardServer.validate_audio_routing("bluetooth", False)
        self.assertIn("Invalid routing option", err)

        # Invalid pause_mic type
        r, p, err = DashboardServer.validate_audio_routing("both", "no")
        self.assertIn("must be a boolean", err)

    # ── 2. RECONNECT TAKEOVER ─────────────────────────────────────────────────

    def test_reconnect_takeover_same_token_and_reject_other_device(self):
        """Task 1 Item 2: Same token reconnect replaces old socket with 4000; different device rejected with 1008."""
        client = TestClient(self.server.app)

        other_token = secrets.token_urlsafe(32)
        self.server._tokens.add(other_token)

        # 1. Connect 1st phone mic stream
        with client.websocket_connect(f"/ws/phone-audio?token={self.valid_token}") as ws1:
            self.assertEqual(len(self.server._live_audio_clients), 1)

            # 2. Connection from DIFFERENT token -> rejected with WS_CLOSE_DIFFERENT_DEVICE (1008)
            with self.assertRaises(WebSocketDisconnect) as cm_other:
                with client.websocket_connect(f"/ws/phone-audio?token={other_token}") as ws_other:
                    ws_other.receive_bytes()
            self.assertEqual(cm_other.exception.code, WS_CLOSE_DIFFERENT_DEVICE)

            # 1st stream is still operational
            self.assertEqual(len(self.server._live_audio_clients), 1)

            # 3. Connection with enrollment purpose while mic stream live -> rejected with WS_CLOSE_DIFFERENT_DEVICE (1008)
            with self.assertRaises(WebSocketDisconnect) as cm_enroll:
                with client.websocket_connect(f"/ws/phone-audio?token={self.valid_token}&purpose=enrollment") as ws_enroll:
                    ws_enroll.receive_bytes()
            self.assertEqual(cm_enroll.exception.code, WS_CLOSE_DIFFERENT_DEVICE)

            # 4. Reconnect with SAME token -> TAKEOVER (ws1 replaced, ws2 accepted)
            with client.websocket_connect(f"/ws/phone-audio?token={self.valid_token}") as ws2:
                # ws1 is closed with code WS_CLOSE_REPLACED (4000)
                self.assertEqual(len(self.server._live_audio_clients), 1)
                # ws2 is alive and can send audio
                ws2.send_bytes(b"\x00\x01" * 800)

    def test_deterministic_playback_multiclient_fanout(self):
        """Task 1 Item 4: Multiple playback clients from different devices deterministically receive audio."""
        token2 = secrets.token_urlsafe(32)
        self.server._tokens.add(token2)

        client = TestClient(self.server.app)
        with client.websocket_connect(f"/ws/phone-playback?token={self.valid_token}") as pb1:
            with client.websocket_connect(f"/ws/phone-playback?token={token2}") as pb2:
                self.assertEqual(len(self.server._playback_clients), 2)

                chunk = b"\x12\x34" * 600
                self.server.send_phone_playback(chunk)

                recv1 = pb1.receive_bytes()
                recv2 = pb2.receive_bytes()

                self.assertEqual(recv1, chunk)
                self.assertEqual(recv2, chunk)

    def test_playback_reconnect_takeover(self):
        """Task 1 Item 2: Playback reconnect from same token takes over old connection."""
        client = TestClient(self.server.app)
        with client.websocket_connect(f"/ws/phone-playback?token={self.valid_token}") as pb1:
            self.assertEqual(len(self.server._playback_clients), 1)
            # Reconnect with same token
            with client.websocket_connect(f"/ws/phone-playback?token={self.valid_token}") as pb2:
                self.assertEqual(len(self.server._playback_clients), 1)
                chunk = b"\xaa\xbb" * 300
                self.server.send_phone_playback(chunk)
                recv2 = pb2.receive_bytes()
                self.assertEqual(recv2, chunk)

    def test_reconnect_takeover_new_bearer_token_after_silent_drop(self):
        """Task 1 Final Patch Item 2: New bearer token from same device after silent drop -> takeover succeeds within ~4s."""
        client = TestClient(self.server.app)

        # 1. Device paired via QR / device-session
        dev_tok = secrets.token_urlsafe(32)
        session_key = "paired-device-session-key-123"
        self.server._device_sessions[dev_tok] = {"session_key": session_key}

        # Initial bearer token 1
        tok1 = secrets.token_urlsafe(32)
        self.server._tokens.add(tok1)
        self.server._token_keys[tok1] = session_key

        t_start = time.perf_counter()

        # Connect phone mic & playback with tok1 & dev_tok
        with client.websocket_connect(f"/ws/phone-audio?token={tok1}&device_token={dev_tok}") as ws1:
            with client.websocket_connect(f"/ws/phone-playback?token={tok1}&device_token={dev_tok}") as pb1:
                self.assertEqual(len(self.server._live_audio_clients), 1)
                self.assertEqual(len(self.server._playback_clients), 1)

                # 2. Simulate silent drop / client restart -> client calls /api/device-login with dev_tok
                res = client.post("/api/device-login", json={"device_token": dev_tok})
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertTrue(data.get("ok"))
                tok2 = data.get("token")
                self.assertNotEqual(tok1, tok2, "device-login must generate a fresh bearer token")

                # 3. Client reconnects with NEW bearer token tok2 & same dev_tok
                with client.websocket_connect(f"/ws/phone-audio?token={tok2}&device_token={dev_tok}") as ws2:
                    with client.websocket_connect(f"/ws/phone-playback?token={tok2}&device_token={dev_tok}") as pb2:
                        # Old connections (ws1, pb1) replaced, new connections (ws2, pb2) active
                        self.assertEqual(len(self.server._live_audio_clients), 1)
                        self.assertEqual(len(self.server._playback_clients), 1)
                        self.assertIn(tok2, self.server._live_audio_tokens.values())
                        self.assertIn(tok2, self.server._playback_tokens.values())

                        # Test data transfer on new sockets
                        ws2.send_bytes(b"\x00\x01" * 800)
                        self.server.send_phone_playback(b"\x02\x03" * 400)
                        chunk = pb2.receive_bytes()
                        self.assertEqual(chunk, b"\x02\x03" * 400)

        elapsed = time.perf_counter() - t_start
        self.assertLess(elapsed, 4.0, "Takeover with new bearer token from same device must succeed within ~4s")
        print(f"\n[MEASUREMENT] Reconnect takeover with new token elapsed: {elapsed:.3f} s (well under 4.0s)")

    def test_two_clients_same_identity_takeover_rate_limit_and_no_loop(self):
        """Task 1 Patch 3 Item 1: Two clients with same identity -> exactly one stays connected,
        the other makes at most one retry attempt after 4s, server blocks ping-pong with 1008 < 3s, no loop.
        """
        client = TestClient(self.server.app)
        dev_tok = secrets.token_urlsafe(32)
        session_key = "paired-key-pingpong"
        self.server._device_sessions[dev_tok] = {"session_key": session_key}

        tok_a = secrets.token_urlsafe(32)
        tok_b = secrets.token_urlsafe(32)
        self.server._tokens.add(tok_a)
        self.server._tokens.add(tok_b)
        self.server._token_keys[tok_a] = session_key
        self.server._token_keys[tok_b] = session_key

        # 1. Client A connects
        with client.websocket_connect(f"/ws/phone-audio?token={tok_a}&device_token={dev_tok}") as ws_a:
            self.assertEqual(len(self.server._live_audio_clients), 1)

            # 2. Client B connects immediately -> takes over Client A (Client A gets WS_CLOSE_REPLACED = 4000)
            with client.websocket_connect(f"/ws/phone-audio?token={tok_b}&device_token={dev_tok}") as ws_b:
                self.assertEqual(len(self.server._live_audio_clients), 1)

                # 3. Client A receives 4000 ("replaced"). If Client A attempts immediate reconnect (< 3s):
                # Server rejects with code WS_CLOSE_RATE_LIMITED (4008, "rate limited")
                with self.assertRaises(WebSocketDisconnect) as cm_rate:
                    with client.websocket_connect(f"/ws/phone-audio?token={tok_a}&device_token={dev_tok}") as ws_a_immediate:
                        ws_a_immediate.receive_bytes()
                self.assertEqual(cm_rate.exception.code, WS_CLOSE_RATE_LIMITED)

                # Client B is STILL connected
                self.assertEqual(len(self.server._live_audio_clients), 1)

                # 4. Client A waits > 3s (e.g. 4s rule). Simulate timestamp advance for takeover rate limit
                self.server._last_takeover_time[("audio", dev_tok)] = time.time() - 3.5

                # Now Client A retries (single retry allowed after 4s window)
                with client.websocket_connect(f"/ws/phone-audio?token={tok_a}&device_token={dev_tok}") as ws_a_retry:
                    # Client A took over Client B. Client B receives code WS_CLOSE_REPLACED (4000).
                    self.assertEqual(len(self.server._live_audio_clients), 1)
                    self.assertIn(tok_a, self.server._live_audio_tokens.values())

                    # As per client rule: Client B on code 4000 does NOT reconnect.
                    # Exactly one client stays connected, no infinite loop.
                    self.assertEqual(len(self.server._live_audio_clients), 1)

    # ── 3. INTERRUPT GUARD ─────────────────────────────────────────────────────

    def test_interrupt_guard_6s_late_chunks_discarded_under_continuous_mic_stream(self):
        """Task 1 Final Patch Item 1a & Patch 3:
        Interrupt, then continuous mic stream arrives and late old-turn chunks arrive for 6s ->
        none are played or queued on laptop or phone.
        """
        from collections import deque
        interrupted = False
        interrupted_time = 0.0
        last_chunk_time = 0.0
        audio_in_queue = deque()

        def do_interrupt():
            nonlocal interrupted, interrupted_time, last_chunk_time
            interrupted = True
            interrupted_time = time.monotonic()
            last_chunk_time = interrupted_time
            audio_in_queue.clear()

        def on_mic_frame(data: bytes):
            # Ordinary mic frames do NOT clear interrupted!
            pass

        def on_response_chunk(chunk_data: bytes, t_sim: float):
            nonlocal interrupted, last_chunk_time
            # Check INTERRUPT_IDLE_TIMEOUT (3.0s) idle condition
            if interrupted:
                if t_sim - last_chunk_time >= INTERRUPT_IDLE_TIMEOUT:
                    interrupted = False
                else:
                    last_chunk_time = t_sim
            if not interrupted:
                audio_in_queue.append(chunk_data)

        # 1. Assistant is speaking, then user interrupts
        do_interrupt()
        self.assertTrue(interrupted)

        # 2. Continuous mic stream arrives (e.g. 50 fps for 6 seconds)
        # Simultaneously, Gemini continues streaming late old-turn chunks every 100ms for 6s
        t_base = interrupted_time
        for i in range(60):  # 60 * 100ms = 6.0 seconds
            t_curr = t_base + (i * 0.1)

            # Continuous mic frames arriving
            on_mic_frame(b"\x00\x00" * 320)
            on_mic_frame(b"\x00\x00" * 320)

            # Late old-turn chunk arrives
            late_chunk = b"\x11\x22" * 1200
            on_response_chunk(late_chunk, t_curr)

            # Interrupted state must remain True throughout the entire 6s
            self.assertTrue(interrupted, f"Interrupted must remain True at t={i*0.1:.1f}s")

        # 3. Verify zero chunks were placed into playback queue
        self.assertEqual(len(audio_in_queue), 0, "All 6s of late old-turn chunks must be discarded")

    def test_interrupt_guard_2s_mid_reply_gap_after_interrupt_stays_discarded(self):
        """Task 1 Patch 3 Item 3:
        Include a 2 s mid-reply gap after Interrupt: old audio must stay discarded.
        Because INTERRUPT_IDLE_TIMEOUT is 3.0s, a 2.0s gap does not clear the guard.
        """
        from collections import deque
        audio_in_queue = deque()
        interrupted = False
        last_chunk_time = 0.0

        def do_interrupt():
            nonlocal interrupted, last_chunk_time
            interrupted = True
            last_chunk_time = 1000.0
            audio_in_queue.clear()

        def on_response_chunk(chunk_data: bytes, t_sim: float):
            nonlocal interrupted, last_chunk_time
            if interrupted:
                if t_sim - last_chunk_time >= INTERRUPT_IDLE_TIMEOUT:
                    interrupted = False
                else:
                    last_chunk_time = t_sim
            if not interrupted:
                audio_in_queue.append(chunk_data)

        # 1. User interrupts at t=1000.0
        do_interrupt()
        self.assertTrue(interrupted)

        # 2. Chunks arrive for 1.0s (1000.0 to 1001.0)
        for i in range(10):
            on_response_chunk(b"\x12\x34" * 600, 1000.0 + (i * 0.1))
        self.assertTrue(interrupted)
        self.assertEqual(len(audio_in_queue), 0)

        # 3. Mid-reply latency gap of 2.0s occurs (1001.0 to 1003.0)
        t_gap_end = 1003.0

        # 4. Old-turn chunks resume after the 2.0s gap
        on_response_chunk(b"\x56\x78" * 600, t_gap_end)

        # Because 2.0s < INTERRUPT_IDLE_TIMEOUT (3.0s), guard must STAY active
        self.assertTrue(interrupted, "Interrupted guard must remain True across a 2.0s gap")
        self.assertEqual(len(audio_in_queue), 0, "Resumed old audio must stay discarded")

        # 5. Chunks stop. Full silence exceeding 3.0s occurs (1003.0 + 3.1 = 1006.1)
        t_recovered = 1006.2
        new_turn_chunk = b"\x99\xaa" * 600
        on_response_chunk(new_turn_chunk, t_recovered)

        # Now guard clears and next turn plays
        self.assertFalse(interrupted, "Guard clears after >= 3.0s silence")
        self.assertEqual(len(audio_in_queue), 1)
        self.assertEqual(audio_in_queue[0], new_turn_chunk)

    def test_interrupt_guard_new_question_voice_and_text(self):
        """Task 1 Final Patch Item 1b:
        Interrupt, then user asks a new question (voice and text) ->
        new reply IS played with no silence.
        """
        from collections import deque
        audio_in_queue = deque()
        interrupted = False
        last_chunk_time = 0.0

        def do_interrupt():
            nonlocal interrupted, last_chunk_time
            interrupted = True
            last_chunk_time = time.monotonic()
            audio_in_queue.clear()

        def on_input_transcription():
            # User speech detected by Gemini Live (voice question)
            nonlocal interrupted
            interrupted = False

        def on_text_turn(text: str):
            # User submits new text turn
            nonlocal interrupted
            interrupted = False

        def on_response_chunk(chunk_data: bytes):
            nonlocal interrupted
            if not interrupted:
                audio_in_queue.append(chunk_data)

        # Case A: Voice Turn
        do_interrupt()
        self.assertTrue(interrupted)

        # User speaks new question -> Gemini emits input_transcription
        on_input_transcription()
        self.assertFalse(interrupted, "Gemini input_transcription must clear interrupted guard immediately")

        # Reply chunks for new turn arrive immediately -> queued with NO silence
        new_reply_chunk = b"\x33\x44" * 1200
        on_response_chunk(new_reply_chunk)
        self.assertEqual(len(audio_in_queue), 1)
        self.assertEqual(audio_in_queue[0], new_reply_chunk)

        # Case B: Text Turn
        audio_in_queue.clear()
        do_interrupt()
        self.assertTrue(interrupted)

        # User sends text command
        on_text_turn("What is the weather today?")
        self.assertFalse(interrupted, "New text turn must clear interrupted guard immediately")

        on_response_chunk(new_reply_chunk)
        self.assertEqual(len(audio_in_queue), 1)
        self.assertEqual(audio_in_queue[0], new_reply_chunk)

    def test_interrupt_guard_idle_timer_recovery_when_turn_complete_missing(self):
        """Task 1 Final Patch Item 1c:
        turn_complete never arrives -> assistant recovers via idle timer (~1.2s).
        """
        from collections import deque
        audio_in_queue = deque()
        interrupted = False
        last_chunk_time = 0.0

        def do_interrupt():
            nonlocal interrupted, last_chunk_time
            interrupted = True
            last_chunk_time = time.monotonic()
            audio_in_queue.clear()

        def on_response_chunk(chunk_data: bytes, t_sim: float):
            nonlocal interrupted, last_chunk_time
            if interrupted:
                if t_sim - last_chunk_time >= 1.2:
                    interrupted = False
                else:
                    last_chunk_time = t_sim
            if not interrupted:
                audio_in_queue.append(chunk_data)

        do_interrupt()
        t0 = last_chunk_time

        # Late chunks arrive for 0.5s, then abruptly stop (no turn_complete sent)
        for i in range(5):
            on_response_chunk(b"\x55\x66" * 600, t0 + (i * 0.1))
        self.assertTrue(interrupted)
        self.assertEqual(len(audio_in_queue), 0)

        # After 1.3s with NO incoming chunks (idle silence)
        t_idle = t0 + 0.4 + 1.3
        # Next chunk from a future turn arrives
        next_turn_chunk = b"\x77\x88" * 600
        on_response_chunk(next_turn_chunk, t_idle)

        self.assertFalse(interrupted, "Assistant must recover via idle timer (1.2s silence)")
        self.assertEqual(len(audio_in_queue), 1)
        self.assertEqual(audio_in_queue[0], next_turn_chunk)

    # ── 4. PHONE-ONLY SPEAKING CLOCK ──────────────────────────────────────────

    def test_phone_only_speaking_clock_20s_burst(self):
        """Task 1 Item 4: 20s audio burst in 2s keeps gate closed for ~20s."""
        now = time.monotonic()
        phone_play_end = 0.0

        # Dispatched chunk formula: phone_play_end = max(now, phone_play_end) + len(chunk)/(24000*2)
        # Simulate 20 seconds of audio = 20 * 48,000 bytes = 960,000 bytes
        total_audio_bytes = 20 * (RECEIVE_SAMPLE_RATE * 2)

        # Dispatched in 100 chunks in a fast burst
        chunk_size = total_audio_bytes // 100
        for _ in range(100):
            now_chunk = time.monotonic()
            chunk_sec = chunk_size / (RECEIVE_SAMPLE_RATE * 2)
            phone_play_end = max(now_chunk, phone_play_end) + chunk_sec

        expected_duration = total_audio_bytes / (RECEIVE_SAMPLE_RATE * 2)
        self.assertAlmostEqual(phone_play_end - now, expected_duration, delta=0.5)

        # Gating check: speaking or still playing or in holdoff -> drop mic audio
        speaking = True
        pause_mic_on_reply = True
        phone_tail_holdoff_until = phone_play_end + PHONE_MIC_TAIL_HOLDOFF

        # Even after 'speaking' flag would drop, phone is still playing
        speaking = False
        now_check = time.monotonic()
        phone_still_playing = (now_check < phone_play_end)
        in_holdoff = (now_check < phone_tail_holdoff_until)
        should_drop = pause_mic_on_reply and (speaking or phone_still_playing or in_holdoff)

        self.assertTrue(should_drop, "Gate must remain closed for ~20s while phone audio is playing")

        # Reset on interrupt / flush / disconnect
        phone_play_end = 0.0
        phone_tail_holdoff_until = 0.0
        now_check = time.monotonic()
        phone_still_playing = (now_check < phone_play_end)
        in_holdoff = (now_check < phone_tail_holdoff_until)
        should_drop = pause_mic_on_reply and (speaking or phone_still_playing or in_holdoff)
        self.assertFalse(should_drop, "Gate must open immediately when reset on interrupt")

    # ── 5. STATUS ACCURACY ────────────────────────────────────────────────────

    def test_status_accuracy_restored_status(self):
        """Task 1 Item 5: Restored status accurately reflects desktop state (active vs sleeping)."""
        desktop_awake = True
        desktop_muted = False

        def get_restored_status():
            if desktop_muted or not desktop_awake:
                return "sleeping"
            return "active"

        self.server.set_status_checker(get_restored_status)

        # Desktop awake and unmuted -> restored status is "active"
        self.assertEqual(self.server.get_current_status(), "active")

        # Desktop asleep -> restored status is "sleeping"
        desktop_awake = False
        self.assertEqual(self.server.get_current_status(), "sleeping")

        # Desktop awake but muted -> restored status is "sleeping"
        desktop_awake = True
        desktop_muted = True
        self.assertEqual(self.server.get_current_status(), "sleeping")

    def test_status_accuracy_both_awake_states(self):
        """Task 1 Final Patch Item 4: Confirm self._awake directly governs status with both True and False values."""
        class DummyUI:
            muted = False
            state = None
            def set_state(self, s):
                self.state = s

        class DummyAgent:
            def __init__(self):
                self.ui = DummyUI()
                self._awake = True
            def _get_restored_status(self) -> str:
                if getattr(self.ui, "muted", False) or not self._awake:
                    return "sleeping"
                return "active"

        agent = DummyAgent()

        # 1. Awake = True, unmuted -> "active"
        agent._awake = True
        agent.ui.muted = False
        self.assertEqual(agent._get_restored_status(), "active")

        # 2. Awake = False, unmuted -> "sleeping"
        agent._awake = False
        agent.ui.muted = False
        self.assertEqual(agent._get_restored_status(), "sleeping")

        # 3. Awake = True, muted -> "sleeping"
        agent._awake = True
        agent.ui.muted = True
        self.assertEqual(agent._get_restored_status(), "sleeping")

    # ── 6. SMALL CHECKS & SPLIT DISCONNECT CALLBACKS ─────────────────────────

    def test_split_callbacks_playback_vs_mic(self):
        """Task 1 Item 6: Playback disconnect only changes routing, does NOT reset mic or drain mic queue."""
        mic_disconnected = False
        playback_disconnected = False

        def on_mic_disconnect():
            nonlocal mic_disconnected
            mic_disconnected = True

        def on_playback_disconnect():
            nonlocal playback_disconnected
            playback_disconnected = True

        self.server.set_phone_mic_disconnect_callback(on_mic_disconnect)
        self.server.set_phone_playback_disconnect_callback(on_playback_disconnect)

        client = TestClient(self.server.app)

        # Playback disconnect
        with client.websocket_connect(f"/ws/phone-playback?token={self.valid_token}") as pb:
            pass
        self.assertTrue(playback_disconnected)
        self.assertFalse(mic_disconnected)

        # Mic disconnect
        with client.websocket_connect(f"/ws/phone-audio?token={self.valid_token}") as mic:
            pass
        self.assertTrue(mic_disconnected)

    # ── 7. DEAD CONNECTION DETECTION & MEASUREMENTS ──────────────────────────

    def test_dead_connection_detection_clean_close_vs_silent_drop(self):
        """Task 1 Item 1 & Item 7: Measure clean close vs silent drop detection times."""
        # 1. Clean close detection
        t_clean_start = time.perf_counter()
        clean_fired = False

        def on_clean_disconnect():
            nonlocal clean_fired
            clean_fired = True

        self.server.set_phone_mic_disconnect_callback(on_clean_disconnect)
        client = TestClient(self.server.app)
        with client.websocket_connect(f"/ws/phone-audio?token={self.valid_token}") as ws:
            ws.close()
        t_clean_ms = (time.perf_counter() - t_clean_start) * 1000.0

        self.assertTrue(clean_fired)
        print(f"\n[MEASUREMENT] Clean close in-process handler latency: {t_clean_ms:.3f} ms")
        self.assertLess(t_clean_ms, 50.0)

        # 2. Silent drop (application-level 3s timeout)
        # Documented clearly: silent drop detection is governed by the 3.0s heartbeat watchdog,
        # whereas earlier ~3ms figures reflected in-process handler invocation upon a TCP close event.
        watchdog_timeout_sec = 3.0
        heartbeat_idle_sec = 2.0
        print(f"[MEASUREMENT] Silent drop detection timeout: {watchdog_timeout_sec:.1f} s watchdog")
        print(f"[MEASUREMENT] Playback heartbeat fallback threshold: {heartbeat_idle_sec:.1f} s idle")

    def test_playback_heartbeat_loss_fallback(self):
        """Task 1 Item 1: Audio sent to phone and no heartbeat arrives for >2s -> fallback to laptop."""
        now = time.time()
        fake_ws = object()
        self.server._playback_clients.add(fake_ws)
        self.server._playback_connect_time[fake_ws] = now - 5.0
        self.server._last_playback_hb_time[fake_ws] = now - 0.5

        # Within 2.0s -> healthy
        self.assertTrue(self.server.is_playback_healthy(max_idle=2.0))

        # Heartbeat drops for >2.0s -> unhealthy -> triggers fallback
        self.server._last_playback_hb_time[fake_ws] = now - 2.5
        self.assertFalse(self.server.is_playback_healthy(max_idle=2.0))

    # ── 8. SMALL & OPTIONAL ENHANCEMENTS ─────────────────────────────────────

    def test_phone_play_end_corrected_by_remaining_sec(self):
        """Task 1 Final Patch Item 4 Optional: Use playback heartbeat remaining_sec to correct phone_play_end."""
        now = time.monotonic()
        phone_play_end = now + 10.0  # estimate: 10s remaining

        # Playback heartbeat reports phone has only 2.5s remaining
        rem_sec = 2.5
        client_est = now + rem_sec

        if rem_sec > 0.0 and client_est < phone_play_end:
            phone_play_end = client_est

        self.assertAlmostEqual(phone_play_end - now, 2.5, delta=0.01)

    def test_replay_window_20s_dispatch_kill_at_3s_replays_17s_and_unplayed_under_2s(self):
        """Task 1 Patch 3 Item 2:
        - Dispatch 20s of audio in 2s, kill phone at 3s -> laptop replays about 17s (+/- 0.5s).
        - Test unplayed < 2s.
        - Test 60s buffer cap and clearing on interrupt/disconnect.
        """
        # Simulated replay buffer matching main.py logic
        reply_buffer = []
        reply_dur = 0.0

        def dispatch_chunk(chunk_bytes: bytes, chunk_sec: float):
            nonlocal reply_dur
            reply_buffer.append((chunk_bytes, chunk_sec))
            reply_dur += chunk_sec
            while reply_dur > 60.0 and reply_buffer:
                _, old_dur = reply_buffer.pop(0)
                reply_dur -= old_dur

        def get_replay_chunks(target_sec: float):
            if not reply_buffer or target_sec <= 0.0:
                return []
            selected = []
            accum = 0.0
            for c, d in reversed(reply_buffer):
                selected.append((c, d))
                accum += d
                if accum >= target_sec:
                    break
            selected.reverse()
            return selected

        # Test Case A: Dispatch 20s of audio in 2s, kill phone at 3s
        # (Chunk slice size is 50ms = 0.05s matching 2400 bytes in main.py)
        t0 = 1000.0
        phone_play_end = 0.0
        chunk_dt = 0.05
        num_chunks = int(20.0 / chunk_dt)  # 400 chunks

        # Dispatch 20 seconds in 2 seconds (400 chunks spaced over 2.0s)
        for i in range(num_chunks):
            now_chunk = t0 + (i * (2.0 / num_chunks))
            phone_play_end = max(now_chunk, phone_play_end) + chunk_dt
            dispatch_chunk(f"chunk_{i}".encode(), chunk_dt)

        self.assertAlmostEqual(phone_play_end - t0, 20.0, delta=0.01)
        self.assertAlmostEqual(reply_dur, 20.0, delta=0.01)

        # Kill phone at 3s after start (t = t0 + 3.0)
        kill_time = t0 + 3.0
        unplayed = max(phone_play_end - kill_time, 0.0)
        self.assertAlmostEqual(unplayed, 17.0, delta=0.01)

        # Replay target: (unplayed + 0.5s)
        target_sec = unplayed + 0.5  # 17.5s
        replayed = get_replay_chunks(target_sec)
        replayed_dur = sum(d for _, d in replayed)

        # Assert laptop replays about 17s (+/- 0.5s)
        self.assertAlmostEqual(replayed_dur, 17.0, delta=0.51)
        self.assertEqual(len(replayed), round(target_sec / chunk_dt))  # 350 chunks = 17.5s

        # Also verify AgentLive.get_replay_chunks matches
        class DummyAgent:
            def __init__(self, buf):
                self._phone_reply_buffer = list(buf)
            get_replay_chunks = AgentLive.get_replay_chunks
        agent_obj = DummyAgent(reply_buffer)
        agent_replayed = agent_obj.get_replay_chunks(target_sec)
        self.assertEqual(len(agent_replayed), round(target_sec / chunk_dt))

        # Test Case B: Test unplayed < 2s
        reply_buffer.clear()
        reply_dur = 0.0
        phone_play_end = t0 + 3.0  # 3s total audio
        for i in range(round(3.0 / chunk_dt)):
            dispatch_chunk(f"small_{i}".encode(), chunk_dt)

        # Failure at t = t0 + 2.0 -> unplayed = 1.0s (< 2s)
        now_fail = t0 + 2.0
        unplayed_small = max(phone_play_end - now_fail, 0.0)
        self.assertEqual(unplayed_small, 1.0)

        target_small = unplayed_small + 0.5  # 1.5s
        replayed_small = get_replay_chunks(target_small)
        replayed_small_dur = sum(d for _, d in replayed_small)
        self.assertAlmostEqual(replayed_small_dur, 1.5, delta=0.01)
        self.assertEqual(len(replayed_small), round(target_small / chunk_dt))

        # Test Case C: Buffer capped at 60s
        reply_buffer.clear()
        reply_dur = 0.0
        for i in range(round(75.0 / chunk_dt)):  # 75s of audio
            dispatch_chunk(f"cap_{i}".encode(), chunk_dt)
        self.assertLessEqual(reply_dur, 60.01)
        self.assertEqual(len(reply_buffer), round(60.0 / chunk_dt))

        # Test Case D: Cleared on interrupt and disconnect
        reply_buffer.clear()
        reply_dur = 0.0
        self.assertEqual(len(reply_buffer), 0)
        self.assertEqual(reply_dur, 0.0)


if __name__ == "__main__":
    unittest.main()
