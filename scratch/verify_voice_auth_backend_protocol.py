"""
scratch/verify_voice_auth_backend_protocol.py

Verifies the 5 requirements for the Voice Auth Backend Orchestrator:
1. Starts a fake enrollment session via the new start endpoint.
2. Sends synthetic PCM frames to /ws/phone-audio — confirm they land in
   _web_enroll_buffer and are NOT pushed to self._phone_audio_queue during this time.
3. Cancels/times out the session — confirm _web_enroll_active resets and that
   subsequent frames DO get routed to self._phone_audio_queue again (Gemini routing resumes).
4. Attempts to start a second enrollment while one is already active — confirm it's rejected.
5. Attempts to start enrollment while a live conversation flag is set — confirm it's rejected with clear reason.
"""

import asyncio
import secrets
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer
from starlette.testclient import TestClient


def run_verification():
    print("=" * 70)
    print("VOICE AUTH BACKEND PROTOCOL VERIFICATION SUITE")
    print("=" * 70)

    server = DashboardServer()
    token = secrets.token_urlsafe(32)
    server._tokens.add(token)
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(server.app) as client:
        # Open the /ws/phone-audio connection to use across tests
        with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
            time.sleep(0.05)
            # Drain any initial welcome connection frames
            server._last_phone_audio_time = 0.0

            # -------------------------------------------------------------
            # CHECK 1: Start fake enrollment session via /api/voice-auth/enroll/start
            # -------------------------------------------------------------
            print("\n[CHECK 1] Starting fake enrollment session via POST /api/voice-auth/enroll/start...")
            resp1 = client.post(
                "/api/voice-auth/enroll/start",
                json={"name": "Alice", "auto": False},
                headers=headers,
            )
            assert resp1.status_code == 200, f"Expected 200, got {resp1.status_code}: {resp1.text}"
            data1 = resp1.json()
            assert data1.get("ok") is True, "Expected ok=True"
            assert data1.get("step") == 1, "Expected step=1"
            assert "phrase" in data1, "Expected phrase in response"
            assert server._web_enroll_active is True, "Expected server._web_enroll_active to be True"
            print(f"  -> SUCCESS: Session active for 'Alice'. Step 1 Phrase: '{data1['phrase'][:45]}...'")

            # -------------------------------------------------------------
            # CHECK 2: Send synthetic PCM frames — verify they land in buffer and NOT in Gemini queue
            # -------------------------------------------------------------
            print("\n[CHECK 2] Sending synthetic PCM frames to /ws/phone-audio while enrollment is active...")
            dummy_pcm_1 = b"\xAA\x55" * 512  # 1024 bytes
            phone_ws.send_bytes(dummy_pcm_1)
            time.sleep(0.08)

            assert server._phone_audio_queue.empty(), (
                "CRITICAL ERROR: Synthetic PCM frame was pushed to self._phone_audio_queue during enrollment!"
            )
            with server._web_enroll_lock:
                buf_len = len(server._web_enroll_buffer)
                buf_content = bytes(server._web_enroll_buffer)
            assert buf_len == 1024, f"Expected 1024 bytes in _web_enroll_buffer, got {buf_len}"
            assert buf_content == dummy_pcm_1, "Buffer content does not match synthetic PCM frame sent!"
            print(f"  -> SUCCESS: Frame landed in _web_enroll_buffer ({buf_len} bytes).")
            print("  -> SUCCESS: self._phone_audio_queue is EMPTY (0 frames leaked to Gemini).")

            # -------------------------------------------------------------
            # CHECK 3: Cancel session — verify _web_enroll_active resets & Gemini routing resumes
            # -------------------------------------------------------------
            print("\n[CHECK 3] Cancelling enrollment session and checking Gemini routing resumption...")
            resp3 = client.post("/api/voice-auth/enroll/cancel", headers=headers)
            assert resp3.status_code == 200, f"Expected 200, got {resp3.status_code}"
            assert resp3.json().get("ok") is True

            assert server._web_enroll_active is False, "Expected _web_enroll_active to reset to False"
            assert len(server._web_enroll_buffer) == 0, "Expected _web_enroll_buffer to be cleared"
            print("  -> SUCCESS: _web_enroll_active reset to False, buffer cleared.")

            # Send subsequent synthetic PCM frames
            dummy_pcm_2 = b"\x12\x34" * 256  # 512 bytes
            phone_ws.send_bytes(dummy_pcm_2)
            time.sleep(0.08)

            assert not server._phone_audio_queue.empty(), (
                "CRITICAL ERROR: Frame was NOT pushed to self._phone_audio_queue after enrollment ended!"
            )
            queued_item = server._phone_audio_queue.get_nowait()
            assert queued_item["data"] == dummy_pcm_2, "Queued chunk data mismatch"
            assert queued_item["mime_type"] == "audio/pcm", "Queued chunk mime_type mismatch"
            assert len(server._web_enroll_buffer) == 0, "_web_enroll_buffer should remain empty when idle"
            print(f"  -> SUCCESS: Subsequent frame ({len(dummy_pcm_2)} bytes) routed directly to Gemini queue!")
            print("  -> SUCCESS: Gemini live audio routing genuinely resumed.")

            # -------------------------------------------------------------
            # CHECK 4: Reject duplicate enrollment while one is already active
            # -------------------------------------------------------------
            print("\n[CHECK 4] Attempting to start duplicate enrollment while one is active...")
            # Reset idle timer so phone isn't flagged as in-use from previous frame
            server._last_phone_audio_time = 0.0

            resp4_a = client.post(
                "/api/voice-auth/enroll/start",
                json={"name": "Alice", "auto": False},
                headers=headers,
            )
            assert resp4_a.status_code == 200
            assert server._web_enroll_active is True
            print("  -> First session started for 'Alice'.")

            # Try to start second enrollment
            resp4_b = client.post(
                "/api/voice-auth/enroll/start",
                json={"name": "Bob", "auto": False},
                headers=headers,
            )
            assert resp4_b.status_code == 409, f"Expected 409 Conflict, got {resp4_b.status_code}"
            err4 = resp4_b.json().get("error", "")
            assert "already in progress" in err4, f"Unexpected error message: '{err4}'"
            assert server._web_enroll_name == "Alice", "Session owner must remain 'Alice'"
            print(f"  -> SUCCESS: Duplicate enrollment rejected with HTTP 409: '{err4}'.")

            # Clean up session
            client.post("/api/voice-auth/enroll/cancel", headers=headers)
            assert server._web_enroll_active is False

            # -------------------------------------------------------------
            # CHECK 5: Reject enrollment while a live conversation flag is set
            # -------------------------------------------------------------
            print("\n[CHECK 5] Attempting to start enrollment while conversation flag is active...")
            # Simulate AgentApp conversation active signal (e.g. self._phone_active = True)
            conversation_active = True
            server.set_conversation_active_checker(lambda: conversation_active)
            assert server.is_phone_audio_in_use() is True, "Server should detect conversation is active"

            resp5 = client.post(
                "/api/voice-auth/enroll/start",
                json={"name": "Charlie", "auto": False},
                headers=headers,
            )
            assert resp5.status_code == 409, f"Expected 409 Conflict, got {resp5.status_code}"
            err5 = resp5.json().get("error", "")
            assert "currently in use" in err5, f"Unexpected error message: '{err5}'"
            assert server._web_enroll_active is False, "Enrollment must not activate when rejected"
            print(f"  -> SUCCESS: Enrollment rejected with HTTP 409: '{err5}'.")

            # Release the conversation active flag
            conversation_active = False
            assert server.is_phone_audio_in_use() is False

            resp5_retry = client.post(
                "/api/voice-auth/enroll/start",
                json={"name": "Charlie", "auto": False},
                headers=headers,
            )
            assert resp5_retry.status_code == 200, "Should succeed once conversation flag is released"
            print("  -> SUCCESS: Enrollment successfully started after conversation ended.")
            client.post("/api/voice-auth/enroll/cancel", headers=headers)

    print("\n" + "=" * 70)
    print(">>> ALL 5 BACKEND VERIFICATION CHECKS PASSED (100%) <<<")
    print("=" * 70)


if __name__ == "__main__":
    run_verification()
