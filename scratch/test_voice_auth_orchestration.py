import asyncio
import secrets
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer
from starlette.testclient import TestClient

def test_voice_auth_orchestrator():
    server = DashboardServer()
    token = secrets.token_urlsafe(32)
    server._tokens.add(token)

    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(server.app) as client:
        # 1. Query status
        resp = client.get("/api/voice-auth/status", headers=headers)
        assert resp.status_code == 200
        status_data = resp.json()
        assert status_data["ok"] is True
        assert status_data["enrollment_active"] is False
        assert status_data["phone_in_use"] is False
        print("[PASS] 1. Initial /api/voice-auth/status OK.")

        # 2. Test phone audio normal routing to Gemini queue
        with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
            dummy_pcm = b"\x00\x01" * 512  # 1024 bytes
            phone_ws.send_bytes(dummy_pcm)
            time.sleep(0.1)

            assert not server._phone_audio_queue.empty(), "Normal audio frame should be in Gemini queue"
            item = server._phone_audio_queue.get_nowait()
            assert item["data"] == dummy_pcm
            assert len(server._web_enroll_buffer) == 0, "Web enroll buffer must remain empty"
            assert server.is_phone_audio_in_use() is True, "Phone audio should be marked in-use"
            print("[PASS] 2. Phone audio normal routing to Gemini queue OK.")

            # 3. Test rejection when phone audio is in use
            resp = client.post("/api/voice-auth/enroll/start", json={"name": "Alice"}, headers=headers)
            assert resp.status_code == 409
            assert "Phone microphone is currently in use" in resp.json()["error"]
            print("[PASS] 3. Rejection when conversation is using phone audio OK.")

            # Simulate idle phone audio by resetting last audio time
            server._last_phone_audio_time = 0.0
            assert server.is_phone_audio_in_use() is False

            # 4. Connect /ws client to monitor broadcast events
            with client.websocket_connect(f"/ws?token={token}") as ctrl_ws:
                # Start manual enrollment
                resp = client.post(
                    "/api/voice-auth/enroll/start",
                    json={"name": "TestUser", "auto": False},
                    headers=headers
                )
                assert resp.status_code == 200
                start_data = resp.json()
                assert start_data["ok"] is True
                assert start_data["step"] == 1
                assert "phrase" in start_data
                assert server._web_enroll_active is True
                print(f"[PASS] 4. Enrollment started (Step 1: '{start_data['phrase'][:30]}...').")

                # Receive WS broadcast for step 1 (skipping any prior history/metrics/sys)
                while True:
                    ws_msg = ctrl_ws.receive_json()
                    if ws_msg.get("type") == "voice_enroll_step":
                        break
                assert ws_msg["step"] == 1
                print("[PASS] 5. Received 'voice_enroll_step' WS broadcast.")

                # 5. Send phone audio while enrollment is active -> MUST append to enroll buffer and NOT to Gemini queue
                enroll_pcm = b"\x12\x34" * 1024
                phone_ws.send_bytes(enroll_pcm)
                time.sleep(0.1)

                assert server._phone_audio_queue.empty(), "Audio frame MUST NOT leak to Gemini queue during enrollment"
                assert len(server._web_enroll_buffer) == len(enroll_pcm), "Frame must be stored in _web_enroll_buffer"
                print("[PASS] 6. Mutual exclusivity verified: audio frame routed exclusively to enrollment buffer.")

                # 6. Attempt second concurrent enrollment -> MUST be rejected (409 Conflict)
                resp_dup = client.post(
                    "/api/voice-auth/enroll/start",
                    json={"name": "Bob"},
                    headers=headers
                )
                assert resp_dup.status_code == 409
                assert "already in progress" in resp_dup.json()["error"]
                print("[PASS] 7. Rejection of duplicate concurrent enrollment session OK.")

                # 7. Advance to step 2 via /api/voice-auth/enroll/next
                resp_next = client.post("/api/voice-auth/enroll/next", headers=headers)
                assert resp_next.status_code == 200
                next_data = resp_next.json()
                assert next_data["step"] == 2
                assert next_data["done"] is False
                assert len(server._web_enroll_recordings) == 1
                print(f"[PASS] 8. Advanced to Step 2 ('{next_data['phrase'][:30]}...').")

                # 8. Test cancel endpoint
                resp_cancel = client.post("/api/voice-auth/enroll/cancel", headers=headers)
                assert resp_cancel.status_code == 200
                assert resp_cancel.json()["ok"] is True
                assert server._web_enroll_active is False
                assert len(server._web_enroll_buffer) == 0
                assert len(server._web_enroll_recordings) == 0
                print("[PASS] 9. Cancelled enrollment; flag and buffers cleaned up.")

                # 9. Verify normal Gemini routing resumes immediately after cancel
                phone_ws.send_bytes(b"\x99\x88" * 256)
                time.sleep(0.1)
                assert not server._phone_audio_queue.empty(), "Audio must route back to Gemini queue after cancel"
                item2 = server._phone_audio_queue.get_nowait()
                assert item2["data"] == b"\x99\x88" * 256
                print("[PASS] 10. Normal Gemini routing successfully resumed.")

    print("\n>>> ALL VOICE AUTH ORCHESTRATOR TESTS PASSED (100%) <<<")

if __name__ == "__main__":
    test_voice_auth_orchestrator()
