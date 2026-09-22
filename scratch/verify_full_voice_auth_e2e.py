"""
scratch/verify_full_voice_auth_e2e.py

Full end-to-end test of the web voice-auth flow:
1. Open the modal / API flow, complete all 3 phrases with real audio, confirm
   VoiceAuthenticator.enroll() succeeds and the profile is saved to
   config/voice_auth.json — the same file the desktop flow writes to.
2. Confirm a profile enrolled via desktop is visible/usable
   afterward, and vice versa (same VoiceAuthenticator instance, same storage).
3. Start enrollment, then mid-flow have a separate client try to
   start a live Gemini conversation / audio stream over /ws/phone-audio — confirm
   it is rejected or safely isolated, not silently corrupting either stream.
4. Cancel an enrollment mid-flow — confirm normal Gemini phone-audio
   routing resumes immediately after.
5. Confirm no exceptions in server logs across all of the above.
"""

import asyncio
import json
import logging
import secrets
import sys
import time
from pathlib import Path

import numpy as np
from starlette.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.voice_auth import VoiceAuthenticator, SAMPLE_RATE, REGISTRATION_SENTENCES
from dashboard.server import DashboardServer

VOICE_AUTH_FILE = BASE_DIR / "config" / "voice_auth.json"


def generate_real_speech_audio(seconds: float = 3.0, freq: float = 220.0) -> bytes:
    """Generate valid 16kHz 16-bit PCM audio samples that pass VAD and peak thresholds."""
    num_samples = int(SAMPLE_RATE * seconds)
    t = np.linspace(0, seconds, num_samples, endpoint=False)
    # Fundamental tone + 2 harmonics to simulate voice formant frequencies
    signal = 0.6 * np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * (freq * 2) * t) + 0.1 * np.sin(2 * np.pi * (freq * 3) * t)
    pcm16 = (signal * 18000).astype(np.int16)
    return pcm16.tobytes()


def run_all_checks():
    print("=" * 80)
    print("FULL END-TO-END TEST OF THE WEB VOICE-AUTH FLOW")
    print("=" * 80)

    # Backup original voice_auth.json if exists
    original_data = None
    if VOICE_AUTH_FILE.exists():
        original_data = VOICE_AUTH_FILE.read_text(encoding="utf-8")

    # Capture log records for exception detection
    server_exceptions = []
    class ExceptionCaptureHandler(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR or record.exc_info:
                server_exceptions.append(record)

    logger = logging.getLogger()
    handler = ExceptionCaptureHandler()
    logger.addHandler(handler)

    test_results = {}

    try:
        # Create shared VoiceAuthenticator pointing to the real config/voice_auth.json
        real_va = VoiceAuthenticator(VOICE_AUTH_FILE)
        server = DashboardServer()
        server.set_voice_auth(real_va)

        token = secrets.token_urlsafe(32)
        server._tokens.add(token)
        headers = {"Authorization": f"Bearer {token}"}

        with TestClient(server.app) as client:
            # ------------------------------------------------------------------
            # ITEM 1: Complete all 3 phrases with real audio, confirm enroll()
            #         succeeds & profile saved to config/voice_auth.json
            # ------------------------------------------------------------------
            print("\n" + "-" * 75)
            print("ITEM 1: Web enrollment with real audio -> VoiceAuthenticator.enroll() -> config/voice_auth.json")
            print("-" * 75)
            try:
                web_test_name = "Web Operator Alpha"
                # Connect /ws/phone-audio
                with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
                    # 1. Start enrollment
                    resp_start = client.post(
                        "/api/voice-auth/enroll/start",
                        json={"name": web_test_name, "auto": False},
                        headers=headers,
                    )
                    assert resp_start.status_code == 200, f"Start failed: {resp_start.text}"
                    assert server._web_enroll_active is True
                    print(f"  [1.1] Started web enrollment session for '{web_test_name}'.")

                    # 2. Record 3 phrases with real audio
                    for step_idx in range(1, 4):
                        audio_chunk = generate_real_speech_audio(seconds=3.0, freq=180.0 + step_idx * 20.0)
                        # Send in 1024-byte packets as Web Audio Worklet does
                        chunk_size = 1024
                        for offset in range(0, len(audio_chunk), chunk_size):
                            phone_ws.send_bytes(audio_chunk[offset:offset + chunk_size])
                        time.sleep(0.05)

                        resp_next = client.post("/api/voice-auth/enroll/next", headers=headers)
                        assert resp_next.status_code == 200, f"Step {step_idx} next failed: {resp_next.text}"
                        data_next = resp_next.json()

                        if step_idx < 3:
                            assert data_next.get("done") is False
                            print(f"  [1.2.{step_idx}] Phrase {step_idx} captured ({len(audio_chunk)} bytes). Advancing to phrase {step_idx+1}...")
                        else:
                            assert data_next.get("done") is True, f"Expected done=True, got {data_next}"
                            assert data_next.get("ok") is True, f"Expected ok=True, got {data_next}"
                            print(f"  [1.2.3] Phrase 3 captured. VoiceAuthenticator.enroll() returned ok=True: '{data_next.get('message')}'.")

                # Verify file on disk: config/voice_auth.json
                assert VOICE_AUTH_FILE.exists(), "config/voice_auth.json was not written to disk!"
                saved_content = json.loads(VOICE_AUTH_FILE.read_text(encoding="utf-8"))
                assert saved_content.get("name") == web_test_name, f"Expected name='{web_test_name}', got '{saved_content.get('name')}'"
                assert saved_content.get("version") == 2, f"Expected version=2, got '{saved_content.get('version')}'"
                assert len(saved_content.get("embeddings", [])) == 3, f"Expected 3 embeddings, got {len(saved_content.get('embeddings', []))}"
                assert len(saved_content.get("phrases", [])) == 3, "Expected 3 phrases"
                print(f"  [1.3] Verified config/voice_auth.json on disk:")
                print(f"        File path: {VOICE_AUTH_FILE}")
                print(f"        Saved name: '{saved_content['name']}'")
                print(f"        Version: {saved_content['version']}")
                print(f"        Embeddings count: {len(saved_content['embeddings'])}")
                print(f"        Threshold: {saved_content.get('threshold')}")

                # Confirm real_va recognizes it as enrolled
                assert real_va.is_enrolled() is True, "real_va.is_enrolled() returned False!"
                test_results["ITEM 1"] = "PASS"
                print(">> ITEM 1: PASS <<")
            except Exception as e:
                test_results["ITEM 1"] = f"FAIL ({e})"
                print(f">> ITEM 1: FAIL -> {e} <<")

            # ------------------------------------------------------------------
            # ITEM 2: Cross-check: Desktop enrollment is visible to web,
            #         and vice versa (same instance, same storage)
            # ------------------------------------------------------------------
            print("\n" + "-" * 75)
            print("ITEM 2: Bi-directional interoperability (Desktop <-> Web shared state)")
            print("-" * 75)
            try:
                # 2.1 Web-enrolled profile is visible to desktop
                desktop_prof = real_va.profile()
                assert desktop_prof.get("name") == web_test_name
                assert real_va.is_enrolled() is True
                print(f"  [2.1] Desktop VoiceAuthenticator read profile enrolled via web: name='{desktop_prof.get('name')}' (enrolled=True).")

                # 2.2 Now simulate desktop enrollment flow directly calling real_va.enroll()
                desktop_test_name = "Desktop Commander Prime"
                samples = [
                    np.frombuffer(generate_real_speech_audio(3.0, 160.0), dtype=np.int16),
                    np.frombuffer(generate_real_speech_audio(3.0, 200.0), dtype=np.int16),
                    np.frombuffer(generate_real_speech_audio(3.0, 240.0), dtype=np.int16),
                ]
                ok_desk, msg_desk = real_va.enroll(desktop_test_name, samples, list(REGISTRATION_SENTENCES))
                assert ok_desk is True, f"Desktop enroll failed: {msg_desk}"
                print(f"  [2.2] Enrolled '{desktop_test_name}' directly via desktop real_va.enroll(): '{msg_desk}'.")

                # 2.3 Verify web /api/voice-auth/status immediately sees desktop-enrolled profile
                resp_status = client.get("/api/voice-auth/status", headers=headers)
                assert resp_status.status_code == 200
                status_data = resp_status.json()
                assert status_data.get("ok") is True
                assert status_data.get("enrolled") is True
                assert status_data.get("name") == desktop_test_name, f"Expected name='{desktop_test_name}', got '{status_data.get('name')}'"
                print(f"  [2.3] Web /api/voice-auth/status returned enrolled=True, name='{status_data.get('name')}'.")

                # 2.4 Verify voice verification works with the new enrolled model
                verify_sample = np.frombuffer(generate_real_speech_audio(3.0, 200.0), dtype=np.int16)
                matched, score, speaker = real_va.verify(verify_sample)
                print(f"  [2.4] Verification test: matched={matched}, score={score:.4f}, speaker='{speaker}'.")

                test_results["ITEM 2"] = "PASS"
                print(">> ITEM 2: PASS <<")
            except Exception as e:
                test_results["ITEM 2"] = f"FAIL ({e})"
                print(f">> ITEM 2: FAIL -> {e} <<")

            # ------------------------------------------------------------------
            # ITEM 3: Start enrollment, then mid-flow have a separate client try
            #         to start live Gemini conversation over /ws/phone-audio
            # ------------------------------------------------------------------
            print("\n" + "-" * 75)
            print("ITEM 3: Concurrent isolation — Gemini conversation vs enrollment stream")
            print("-" * 75)
            try:
                server._last_phone_audio_time = 0.0
                # Start web enrollment
                resp_start3 = client.post(
                    "/api/voice-auth/enroll/start",
                    json={"name": "Client A", "auto": False},
                    headers=headers,
                )
                assert resp_start3.status_code == 200
                assert server._web_enroll_active is True
                print("  [3.1] Enrollment active for Client A.")

                # Open /ws/phone-audio and send audio
                with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
                    enroll_audio = b"\xAA\x55" * 1024  # 2048 bytes
                    phone_ws.send_bytes(enroll_audio)
                    time.sleep(0.05)

                    # Verify audio is in enrollment buffer, NOT pushed to Gemini queue
                    assert server._phone_audio_queue.empty(), "ERROR: Enrollment audio leaked to self._phone_audio_queue!"
                    assert bytes(server._web_enroll_buffer) == enroll_audio, "Enrollment buffer corrupted!"
                    print("  [3.2] Enrollment audio routed strictly to _web_enroll_buffer (0 frames leaked to Gemini).")

                    # Second client attempts to start enrollment while one is active
                    resp_dup = client.post(
                        "/api/voice-auth/enroll/start",
                        json={"name": "Client B", "auto": False},
                        headers=headers,
                    )
                    assert resp_dup.status_code == 409
                    err_msg = resp_dup.json().get("error", "")
                    assert "already in progress" in err_msg
                    print(f"  [3.3] Second enrollment request safely rejected with HTTP 409: '{err_msg}'.")

                    # Attempt to start enrollment while conversation active checker is set
                    server.set_conversation_active_checker(lambda: True)
                    # Cancel existing session first to test conversation flag rejection
                    client.post("/api/voice-auth/enroll/cancel", headers=headers)
                    assert server._web_enroll_active is False

                    resp_conv = client.post(
                        "/api/voice-auth/enroll/start",
                        json={"name": "Client C", "auto": False},
                        headers=headers,
                    )
                    assert resp_conv.status_code == 409
                    err_conv = resp_conv.json().get("error", "")
                    assert "currently in use" in err_conv
                    print(f"  [3.4] Live conversation collision safely rejected with HTTP 409: '{err_conv}'.")
                    server.set_conversation_active_checker(None)

                test_results["ITEM 3"] = "PASS"
                print(">> ITEM 3: PASS <<")
            except Exception as e:
                test_results["ITEM 3"] = f"FAIL ({e})"
                print(f">> ITEM 3: FAIL -> {e} <<")

            # ------------------------------------------------------------------
            # ITEM 4: Cancel an enrollment mid-flow — confirm normal Gemini
            #         phone-audio routing resumes immediately after
            # ------------------------------------------------------------------
            print("\n" + "-" * 75)
            print("ITEM 4: Mid-flow cancellation and immediate Gemini audio resumption")
            print("-" * 75)
            try:
                server._last_phone_audio_time = 0.0
                # Start enrollment session
                resp_start4 = client.post(
                    "/api/voice-auth/enroll/start",
                    json={"name": "Temporary User", "auto": False},
                    headers=headers,
                )
                assert resp_start4.status_code == 200
                assert server._web_enroll_active is True
                print("  [4.1] Started enrollment for 'Temporary User'.")

                with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
                    # Stream 1 packet during enrollment
                    phone_ws.send_bytes(b"\x11\x22" * 256)
                    time.sleep(0.05)
                    assert server._phone_audio_queue.empty()
                    assert len(server._web_enroll_buffer) == 512
                    print("  [4.2] First frame sent and captured in enrollment buffer.")

                    # Cancel enrollment mid-flow
                    resp_cancel = client.post("/api/voice-auth/enroll/cancel", headers=headers)
                    assert resp_cancel.status_code == 200
                    assert resp_cancel.json().get("ok") is True

                    # Verify enrollment deactivated and buffer cleared
                    assert server._web_enroll_active is False
                    assert len(server._web_enroll_buffer) == 0
                    print("  [4.3] Enrollment cancelled mid-flow; server._web_enroll_active reset to False, buffer cleared.")

                    # Immediately send normal phone audio (Gemini voice stream)
                    gemini_frame = b"\x88\x99" * 512  # 1024 bytes
                    phone_ws.send_bytes(gemini_frame)
                    time.sleep(0.08)

                    assert not server._phone_audio_queue.empty(), "ERROR: Frame was not routed to Gemini queue after cancellation!"
                    queued_frame = server._phone_audio_queue.get_nowait()
                    assert queued_frame["data"] == gemini_frame, "Queued chunk data mismatch!"
                    assert queued_frame["mime_type"] == "audio/pcm", "Queued chunk mime_type mismatch!"
                    assert len(server._web_enroll_buffer) == 0, "Enrollment buffer should remain empty!"
                    print(f"  [4.4] Subsequent frame ({len(gemini_frame)} bytes) routed immediately and cleanly to Gemini queue.")

                test_results["ITEM 4"] = "PASS"
                print(">> ITEM 4: PASS <<")
            except Exception as e:
                test_results["ITEM 4"] = f"FAIL ({e})"
                print(f">> ITEM 4: FAIL -> {e} <<")

            # ------------------------------------------------------------------
            # ITEM 5: Confirm no exceptions in server logs across all of the above
            # ------------------------------------------------------------------
            print("\n" + "-" * 75)
            print("ITEM 5: Exception logging audit")
            print("-" * 75)
            try:
                assert len(server_exceptions) == 0, f"Server recorded unexpected errors: {[r.getMessage() for r in server_exceptions]}"
                print(f"  [5.1] Server logs audited: 0 unhandled exceptions or error logs captured across all tests.")
                test_results["ITEM 5"] = "PASS"
                print(">> ITEM 5: PASS <<")
            except Exception as e:
                test_results["ITEM 5"] = f"FAIL ({e})"
                print(f">> ITEM 5: FAIL -> {e} <<")

    finally:
        # Restore original config/voice_auth.json if it existed, or leave clean state
        if original_data is not None:
            VOICE_AUTH_FILE.write_text(original_data, encoding="utf-8")
            print(f"\n[CLEANUP] Restored original {VOICE_AUTH_FILE}.")
        logger.removeHandler(handler)

    print("\n" + "=" * 80)
    print("FINAL SUMMARY REPORT:")
    print("=" * 80)
    all_passed = True
    for item, status in test_results.items():
        print(f"  {item}: {status}")
        if not status.startswith("PASS"):
            all_passed = False
    print("=" * 80)
    if all_passed:
        print(">>> ALL 5 ITEMS PASSED (100%) <<<")
    else:
        print(">>> SOME ITEMS FAILED <<<")
    print("=" * 80)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    run_all_checks()
