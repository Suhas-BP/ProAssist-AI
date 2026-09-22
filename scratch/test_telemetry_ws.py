import asyncio
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer

async def test_telemetry_and_existing_messages():
    server = DashboardServer()
    # authorize test token
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)

    from starlette.testclient import TestClient

    received_metrics = []
    received_logs = []

    with TestClient(server.app) as client:
        with client.websocket_connect(f"/ws?token={tok}") as ws:
            # Wait and receive initial messages / telemetry
            # We expect at least 1 metrics message within 2 seconds
            for _ in range(3):
                try:
                    data = ws.receive_json()
                    if data.get("type") == "metrics":
                        received_metrics.append(data)
                        print("[TEST] Received metrics:", data)
                        break
                except Exception as e:
                    print("[TEST] Receive error:", e)
                    break

            # Now broadcast a regular log message
            log_msg = {"type": "log", "speaker": "jarvis", "text": "Hello, world!"}
            # Run server broadcast
            await server.broadcast(log_msg)

            # Receive the broadcast log message
            for _ in range(3):
                try:
                    data = ws.receive_json()
                    if data.get("type") == "log":
                        received_logs.append(data)
                        print("[TEST] Received log:", data)
                        break
                    elif data.get("type") == "metrics":
                        received_metrics.append(data)
                        print("[TEST] Received additional metrics:", data)
                except Exception as e:
                    print("[TEST] Receive error:", e)
                    break

    # Assertions
    assert len(received_metrics) >= 1, f"Expected at least 1 metrics message, got {received_metrics}"
    m = received_metrics[0]
    assert "cpu" in m, "Missing 'cpu' in metrics"
    assert "mem" in m, "Missing 'mem' in metrics"
    assert "net" in m, "Missing 'net' in metrics"
    assert len(received_logs) >= 1, f"Expected at least 1 log message, got {received_logs}"
    assert received_logs[0]["text"] == "Hello, world!"

    # Verify history does not contain metrics messages
    metrics_in_history = [item for item in server._history if item.get("type") == "metrics"]
    assert len(metrics_in_history) == 0, f"History should not contain metrics messages, got {metrics_in_history}"

    print("\n>>> ALL TELEMETRY & EXISTING MESSAGE COMPATIBILITY CHECKS PASSED! <<<")

if __name__ == "__main__":
    asyncio.run(test_telemetry_and_existing_messages())
