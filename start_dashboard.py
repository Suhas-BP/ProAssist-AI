"""
start_dashboard.py — Launch the AGENT web dashboard on http://localhost:8000.
Runs with HTTP (no SSL cert prompt) and provides an instant one-click login link.
"""
import os
import sys
import asyncio
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Disable HTTPS requirement for local HTTP access
os.environ["DASHBOARD_NO_SSL"] = "1"

from dashboard.server import DashboardServer, PORT


async def telemetry_loop(server: DashboardServer):
    """Broadcast realistic telemetry and status so the dashboard is immediately lively."""
    await asyncio.sleep(1.5)
    import psutil
    while True:
        try:
            if server._clients:
                cpu = psutil.cpu_percent()
                mem = psutil.virtual_memory().percent
                await server.broadcast({
                    "type": "telemetry",
                    "cpu": cpu,
                    "ram": mem,
                    "gpu": 12,
                    "temp": 42
                })
        except Exception:
            pass
        await asyncio.sleep(2)


async def main():
    server = DashboardServer()

    # Pre-authorize a permanent local development key
    dev_key = "123456"
    server._pending_keys[dev_key] = 9999999999.0
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)
    server._token_keys[tok] = dev_key
    server._aes_key(dev_key)

    # Route for instant 1-click auto login from local browser
    @server.app.get("/dev-login")
    async def dev_login():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"""<!DOCTYPE html><html><body>
        <script>
          sessionStorage.setItem('jarvis_token', '{tok}');
          sessionStorage.setItem('jarvis_key', '{dev_key}');
          location.replace('/');
        </script>
        <p>Connecting to dashboard...</p>
        </body></html>""")

    print("\n" + "=" * 60)
    print("  AGENT REDESIGNED DASHBOARD SERVER RUNNING")
    print("=" * 60)
    print(f"  Direct 1-Click Access: http://localhost:{PORT}/dev-login")
    print(f"  Standard Dashboard:    http://localhost:{PORT}/")
    print(f"  Dev PIN (if prompted): {dev_key}")
    print("=" * 60 + "\n")

    asyncio.create_task(telemetry_loop(server))
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
