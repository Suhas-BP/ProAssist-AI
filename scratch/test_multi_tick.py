import asyncio
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard.server import DashboardServer

async def test_multi_tick_metrics():
    server = DashboardServer()
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)

    from starlette.testclient import TestClient

    metrics_received = []

    with TestClient(server.app) as client:
        with client.websocket_connect(f"/ws?token={tok}") as ws:
            # Let it run for ~2.5 seconds, collecting ticks
            import time
            t0 = time.time()
            while time.time() - t0 < 2.5 and len(metrics_received) < 3:
                try:
                    data = ws.receive_json()
                    if data.get("type") == "metrics":
                        metrics_received.append(data)
                        print(f"[TEST tick {len(metrics_received)}] Got metrics:", data)
                except Exception as e:
                    break

    assert len(metrics_received) >= 2, f"Expected at least 2 ticks, got {len(metrics_received)}"
    print(f"\nSuccessfully collected {len(metrics_received)} periodic telemetry ticks!")

if __name__ == "__main__":
    asyncio.run(test_multi_tick_metrics())
