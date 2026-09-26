"""
scratch/monitor_assistant.py — Comprehensive live activity monitor for Mark-LIV.
"""
import psutil
import socket
import ssl
import urllib.request
import time
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta

def get_process_info():
    for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'cpu_percent', 'create_time', 'num_threads']):
        try:
            cmd = " ".join(p.info['cmdline'] or [])
            if "main.py" in cmd and "python" in p.info['name'].lower():
                mem_mb = p.info['memory_info'].rss / (1024 * 1024)
                vms_mb = p.info['memory_info'].vms / (1024 * 1024)
                create_dt = datetime.fromtimestamp(p.info['create_time'])
                uptime = timedelta(seconds=int(time.time() - p.info['create_time']))
                return {
                    "pid": p.info['pid'],
                    "name": p.info['name'],
                    "memory_rss_mb": round(mem_mb, 2),
                    "memory_vms_mb": round(vms_mb, 2),
                    "cpu_percent": p.cpu_percent(interval=0.1),
                    "status": p.status(),
                    "threads": p.info['num_threads'],
                    "started_at": create_dt.strftime("%H:%M:%S"),
                    "uptime": str(uptime),
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

def get_windows(pid):
    user32 = ctypes.windll.user32
    h_desk = user32.OpenDesktopW('Default', 0, False, 0x01FF)
    if not h_desk:
        return []
    windows = []
    def enum_cb(hwnd, lparam):
        w_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
        if w_pid.value == pid:
            visible = user32.IsWindowVisible(hwnd)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if visible and w > 0 and h > 0:
                windows.append({
                    "hwnd": hex(hwnd),
                    "title": buff.value or "(Frameless Widget)",
                    "geometry": f"{w}x{h} at ({rect.left}, {rect.top})",
                    "visible": visible,
                })
        return True

    DESKENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumDesktopWindows(h_desk, DESKENUMPROC(enum_cb), 0)
    user32.CloseDesktop(h_desk)
    return windows

def check_dashboard():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        t0 = time.monotonic()
        req = urllib.request.urlopen("https://127.0.0.1:8000", context=ctx, timeout=2)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"status": "ONLINE", "code": req.status, "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "OFFLINE", "error": str(e), "latency_ms": None}

def run_monitor():
    p_info = get_process_info()
    dash = check_dashboard()
    
    print("=" * 65)
    print("MARK-LIV LIVE ACTIVITY MONITOR")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    if not p_info:
        print("[!] Mark-LIV process not detected.")
        return

    print(f"Process:       PID {p_info['pid']} ({p_info['name']}) — Status: {p_info['status'].upper()}")
    print(f"Uptime:        {p_info['uptime']} (Started at {p_info['started_at']})")
    print(f"CPU Load:      {p_info['cpu_percent']:.1f}%")
    print(f"Memory:        {p_info['memory_rss_mb']} MB (RSS) | {p_info['memory_vms_mb']} MB (VMS)")
    print(f"Active Threads:{p_info['threads']}")
    print("-" * 65)

    windows = get_windows(p_info['pid'])
    print(f"Visible GUI Windows ({len(windows)} active on desktop):")
    for w in windows:
        print(f"  • {w['title']:<24} Geometry: {w['geometry']} [HWND: {w['hwnd']}]")
    print("-" * 65)

    print(f"Web Dashboard: {dash['status']} (Port 8000)")
    if dash['status'] == "ONLINE":
        print(f"  • Local Endpoint: https://127.0.0.1:8000 (HTTP {dash['code']}, {dash['latency_ms']}ms response)")
    else:
        print(f"  • Error: {dash.get('error')}")
    print("=" * 65)

if __name__ == "__main__":
    run_monitor()
