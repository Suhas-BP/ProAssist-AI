import asyncio
import secrets
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer
from core.voice_auth import REGISTRATION_SENTENCES
from starlette.testclient import TestClient

def test_full_enrollment_cycle():
    server = DashboardServer()
    token = secrets.token_urlsafe(32)
    server._tokens.add(token)
    headers = {"Authorization": f"Bearer {token}"}

    # Attach mock VoiceAuthenticator instance to test the call without rewriting real JSON profile
    mock_va = MagicMock()
    mock_va.enroll.return_value = (True, "Voice enrollment complete for UnitTester.")
    server.set_voice_auth(mock_va)

    with TestClient(server.app) as client:
        # Start enrollment (manual progression mode for fast deterministic testing)
        resp_start = client.post(
            "/api/voice-auth/enroll/start",
            json={"name": "UnitTester", "auto": False},
            headers=headers,
        )
        assert resp_start.status_code == 200
        assert resp_start.json()["step"] == 1

        with client.websocket_connect(f"/ws/phone-audio?token={token}") as phone_ws:
            # Step 1: feed audio
            phone_ws.send_bytes(b"\x01\x00" * 32000)
            time.sleep(0.05)
            # Advance to step 2
            resp_s2 = client.post("/api/voice-auth/enroll/next", headers=headers)
            assert resp_s2.status_code == 200
            assert resp_s2.json()["step"] == 2
            assert resp_s2.json()["done"] is False

            # Step 2: feed audio
            phone_ws.send_bytes(b"\x02\x00" * 32000)
            time.sleep(0.05)
            # Advance to step 3
            resp_s3 = client.post("/api/voice-auth/enroll/next", headers=headers)
            assert resp_s3.status_code == 200
            assert resp_s3.json()["step"] == 3
            assert resp_s3.json()["done"] is False

            # Step 3: feed audio
            phone_ws.send_bytes(b"\x03\x00" * 32000)
            time.sleep(0.05)
            # Complete enrollment
            resp_s4 = client.post("/api/voice-auth/enroll/next", headers=headers)
            assert resp_s4.status_code == 200
            data4 = resp_s4.json()
            assert data4["ok"] is True
            assert data4["done"] is True
            assert "Voice enrollment complete" in data4["message"]

        # Verify VoiceAuthenticator.enroll was called with exact name, 3 recordings, and REGISTRATION_SENTENCES
        assert mock_va.enroll.called
        call_args = mock_va.enroll.call_args[0]
        assert call_args[0] == "UnitTester"
        recordings = call_args[1]
        assert len(recordings) == 3
        assert len(recordings[0]) == 32000
        assert call_args[2] == list(REGISTRATION_SENTENCES)
        print(f"[PASS] VoiceAuthenticator.enroll was invoked with 3 recordings of length {len(recordings[0])}!")

        # Verify clean post-completion state
        assert server._web_enroll_active is False
        assert len(server._web_enroll_buffer) == 0
        assert len(server._web_enroll_recordings) == 0

    print("\n>>> FULL 3-STEP ENROLLMENT CYCLE TEST PASSED (100%) <<<")

if __name__ == "__main__":
    test_full_enrollment_cycle()
