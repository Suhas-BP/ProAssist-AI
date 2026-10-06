"""
dashboard/server.py — AGENT Local HTTP Dashboard

Plain HTTP on port 8000 (no SSL warnings, no firewall issues).
Security at the application layer: AES-256-CBC with session-key-derived key.
CryptoJS is auto-downloaded once and served locally — no CDN needed after that.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import string
import threading
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = 8000
MAX_UPLOAD_MB = 500


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "AGENT Uploads",
        Path.home() / "Documents" / "AGENT Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'AGENT-DASHBOARD-v1'


def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ── CryptoJS (auto-download once, served locally) ─────────────────────────────
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # ── Windows ──────────────────────────────────────────────────────────────
    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"AGENT Dashboard Port {port}"
        prog_rule  = "AGENT Dashboard Python"
        py_exe     = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="jarvis_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # ── Try running directly (succeeds when already admin) ────────────────
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # ── ShellExecuteW: native UAC elevation (most reliable on Windows) ────
        # ShellExecuteW with verb "runas" always shows the UAC dialog regardless
        # of UAC level settings. Non-blocking — uvicorn is already running.
        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,       # hwnd  (no parent window)
                "runas",    # verb  (request elevation)
                bat_path,   # file  (our .bat)
                None,       # params
                None,       # working dir
                0,          # SW_HIDE (run without a visible cmd window)
            )
            if int(ret) > 32:
                # ShellExecuteW returns immediately; bat finishes in ~1 second.
                # Sleep briefly so the rules are in place before the first retry.
                time.sleep(2)
                print(f"[Dashboard] Network setup complete — port {port} is open.")
                print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                print("[Dashboard] Phone connections may fail until AGENT is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # ── macOS ─────────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # ── Linux ─────────────────────────────────────────────────────────────────
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")


_ensure_crypto_js()


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _ensure_certs() -> bool:
    """
    Make sure config/certs holds a TLS key pair, generating a self-signed one the
    first time the dashboard runs.

    The pair is deliberately NOT shipped in the repository. A private key that
    every user downloads is the same as having no private key at all: anyone can
    present a certificate that matches it. Generating locally gives each install
    its own key, costs about a second, and happens exactly once.

    Returns True when a usable pair exists afterwards; False leaves the caller on
    plain HTTP, which still works — the QR code simply encodes http:// instead.
    """
    certs = BASE_DIR / "config" / "certs"
    key_p = certs / "jarvis.key"
    crt_p = certs / "jarvis.crt"
    if key_p.exists() and crt_p.exists():
        return True

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("[Dashboard] cryptography not installed — serving over plain HTTP.")
        print("[Dashboard] For HTTPS run:  pip install cryptography")
        return False

    try:
        certs.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        who = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "AGENT Dashboard"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AGENT"),
        ])

        # The SAN has to cover every address the phone might use: the LAN IP the
        # QR code encodes, plus localhost when testing on the machine itself.
        alt = [x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan = _local_ip()
            if not lan.startswith("127."):
                alt.append(x509.IPAddress(ipaddress.IPv4Address(lan)))
        except Exception:
            pass          # no LAN address resolvable — localhost entries still work

        # Timezone-aware UTC: datetime.utcnow() is deprecated from Python 3.12 on,
        # and the builder normalises aware values to UTC itself.
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(who)
            .issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        key_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        try:
            import os as _os
            _os.chmod(key_p, 0o600)   # best effort — largely a no-op on Windows
        except Exception:
            pass

        print(f"[Dashboard] Generated a self-signed certificate for this machine: {certs}")
        return True
    except Exception as e:
        print(f"[Dashboard] Certificate generation failed ({e}) — serving over plain HTTP.")
        return False


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── WebSocket Close Codes (Task 1 Patch 4) ────────────────────────────────────
WS_CLOSE_NORMAL: int = 1000
WS_CLOSE_GOING_AWAY: int = 1001
WS_CLOSE_DIFFERENT_DEVICE: int = 1008   # Another device is active / policy violation
WS_CLOSE_REPLACED: int = 4000           # Stream takeover by another session
WS_CLOSE_UNAUTHORIZED: int = 4001       # Missing or invalid authentication token
WS_CLOSE_RATE_LIMITED: int = 4008       # Takeover rate limited (< 3s between takeovers)


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}  # device_token → {session_key}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        self._login_html                  = _read("login.html")
        self._app_html                    = _read("app.html")
        self._voice_auth                  = None
        self._conversation_active_checker = None
        self._last_phone_audio_time       = 0.0
        self._web_enroll_active           = False
        self._web_enroll_lock             = threading.Lock()
        self._web_enroll_buffer           = bytearray()
        self._web_enroll_recordings: list = []
        self._web_enroll_name             = ""
        self._web_enroll_step             = 0
        self._web_enroll_task             = None
        self._web_enroll_ws               = None
        self._live_audio_clients: set     = set()
        self._live_audio_tokens: dict     = {}
        self._desktop_muted_checker       = None
        self._interrupt_callback          = None
        self._phone_mic_disconnect_callback = None
        self._phone_playback_disconnect_callback = None
        self._phone_disconnect_callback   = None
        self._status_checker              = None
        self._audio_routing: str          = "phone"
        self._pause_mic_on_reply: bool    = True
        self._pause_mic_callback          = None
        self._playback_clients: set       = set()
        self._playback_queues: dict       = {}
        self._playback_tokens: dict       = {}
        self._last_playback_hb_time: dict = {}
        self._last_playback_remaining_sec: dict = {}
        self._playback_connect_time: dict = {}
        self._replaced_websockets: set    = set()
        self._live_audio_device_tokens: dict = {}
        self._playback_device_tokens: dict = {}
        self._last_takeover_time: dict    = {}
        self.app                          = self._build_app()

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _ssl_enabled() -> bool:
        if os.environ.get("DASHBOARD_NO_SSL") == "1":
            return False
        certs = BASE_DIR / "config" / "certs"
        return (certs / "jarvis.key").exists() and (certs / "jarvis.crt").exists()

    def get_url(self) -> str:
        proto = "https" if self._ssl_enabled() else "http"
        return f"{proto}://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            return f"{self._ip}:{PORT + 1}"
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    def set_voice_auth(self, va) -> None:
        self._voice_auth = va

    def set_conversation_active_checker(self, fn) -> None:
        self._conversation_active_checker = fn

    def set_desktop_muted_checker(self, fn) -> None:
        self._desktop_muted_checker = fn

    def set_interrupt_callback(self, fn) -> None:
        self._interrupt_callback = fn

    def set_phone_mic_disconnect_callback(self, fn) -> None:
        self._phone_mic_disconnect_callback = fn

    def set_phone_playback_disconnect_callback(self, fn) -> None:
        self._phone_playback_disconnect_callback = fn

    def set_phone_disconnect_callback(self, fn) -> None:
        # Sets both for backward compatibility
        self._phone_mic_disconnect_callback = fn
        self._phone_playback_disconnect_callback = fn
        self._phone_disconnect_callback = fn

    def set_status_checker(self, fn) -> None:
        self._status_checker = fn

    def get_current_status(self) -> str:
        if self._status_checker:
            try:
                st = self._status_checker()
                if st in ("active", "sleeping"):
                    return st
            except Exception:
                pass
        return "sleeping"

    def is_playback_healthy(self, max_idle: float = 2.0) -> bool:
        if not self._playback_clients:
            return False
        now = time.time()
        for ws in list(self._playback_clients):
            conn_t = self._playback_connect_time.get(ws, 0.0)
            last_hb = self._last_playback_hb_time.get(ws, 0.0)
            # Give 2.0s grace period from initial connection
            if (now - conn_t < 2.0) or (now - last_hb <= max_idle):
                return True
        return False

    def get_phone_playback_remaining_sec(self) -> float:
        if not self._last_playback_remaining_sec:
            return 0.0
        return max(self._last_playback_remaining_sec.values(), default=0.0)

    def _is_same_paired_device(self, tok1: str, dev_tok1: str, tok2: str, dev_tok2: str) -> bool:
        """Check whether two connections belong to the same paired device/session (Item 2)."""
        # 1. Exact bearer token match
        if tok1 and tok2 and tok1 == tok2:
            return True
        # 2. Paired persistent device token match
        if dev_tok1 and dev_tok2 and dev_tok1 == dev_tok2:
            return True
        # 3. Session key match (e.g. if device-login refreshed/rotated bearer token after reconnect)
        key1 = self._token_keys.get(tok1) or (self._device_sessions.get(dev_tok1, {}).get("session_key"))
        key2 = self._token_keys.get(tok2) or (self._device_sessions.get(dev_tok2, {}).get("session_key"))
        if key1 and key2 and key1 == key2:
            return True
        return False

    @staticmethod
    def validate_audio_routing(routing_val, pause_mic_val) -> tuple[str | None, bool | None, str | None]:
        clean_routing = None
        clean_pause = None
        if routing_val is not None:
            if not isinstance(routing_val, str):
                return None, None, "routing must be a string"
            clean = routing_val.strip().lower()
            if clean not in ("phone", "laptop", "both"):
                return None, None, "Invalid routing option. Must be 'phone', 'laptop', or 'both'"
            clean_routing = clean

        if pause_mic_val is not None:
            if not isinstance(pause_mic_val, bool):
                return None, None, "pause_mic_on_reply must be a boolean"
            clean_pause = pause_mic_val

        return clean_routing, clean_pause, None

    @staticmethod
    async def _read_bounded_json(req: Request, max_bytes: int = 4096) -> tuple[dict | None, int]:
        body = bytearray()
        try:
            async for chunk in req.stream():
                body.extend(chunk)
                if len(body) > max_bytes:
                    return None, 413
            if not body:
                return {}, 200
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                return None, 400
            return data, 200
        except Exception:
            return None, 400

    def set_pause_mic_callback(self, fn) -> None:
        self._pause_mic_callback = fn

    def set_pause_mic_on_reply(self, enabled: bool) -> None:
        self._pause_mic_on_reply = bool(enabled)
        if self._pause_mic_callback:
            try:
                self._pause_mic_callback(self._pause_mic_on_reply)
            except Exception:
                pass

    def get_pause_mic_on_reply(self) -> bool:
        return self._pause_mic_on_reply

    def set_audio_routing(self, routing: str) -> None:
        r = str(routing or "").strip().lower()
        if r in ("phone", "laptop", "both"):
            self._audio_routing = r

    def get_audio_routing(self) -> str:
        return self._audio_routing

    def is_phone_mic_active(self) -> bool:
        if bool(self._live_audio_clients):
            return True
        if self._conversation_active_checker:
            try:
                return bool(self._conversation_active_checker())
            except Exception:
                pass
        return False

    def is_desktop_muted(self) -> bool:
        if self._desktop_muted_checker:
            try:
                return bool(self._desktop_muted_checker())
            except Exception:
                pass
        return False

    async def broadcast_mic_state(self) -> None:
        await self.broadcast({
            "type": "mic_state",
            "phone": self.is_phone_mic_active(),
            "desktop_muted": self.is_desktop_muted(),
        })

    def broadcast_mic_state_sync(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast_mic_state())
        except RuntimeError:
            pass

    def has_playback_clients(self) -> bool:
        return bool(self._playback_clients)

    def send_phone_playback(self, chunk: bytes) -> bool:
        """Send PCM16 chunk to phone playback clients with bounded queue drop-oldest."""
        if not self._playback_clients:
            return False
        dispatched = False
        for ws, q in list(self._playback_queues.items()):
            while q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                q.put_nowait(chunk)
                dispatched = True
            except asyncio.QueueFull:
                pass
        return dispatched

    def flush_phone_playback(self) -> None:
        """Clear queued phone playback audio and notify clients immediately."""
        for q in list(self._playback_queues.values()):
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast({"type": "audio_flush"}))
        except RuntimeError:
            pass

    def _get_voice_auth(self):
        if self._voice_auth is not None:
            return self._voice_auth
        try:
            from core.voice_auth import VoiceAuthenticator
            self._voice_auth = VoiceAuthenticator()
            return self._voice_auth
        except Exception:
            return None

    def is_phone_audio_in_use(self) -> bool:
        if bool(self._live_audio_clients):
            return True
        if self._conversation_active_checker:
            try:
                if self._conversation_active_checker():
                    return True
            except Exception:
                pass
        return (time.time() - self._last_phone_audio_time) < 2.0

    async def _run_web_enrollment_auto(self, name: str):
        import numpy as np
        from core.voice_auth import REGISTRATION_SENTENCES
        try:
            recordings = []
            for step, phrase in enumerate(REGISTRATION_SENTENCES, start=1):
                self._web_enroll_step = step
                # Step announcement: reading status (give 2 seconds to read)
                await self.broadcast({
                    "type": "voice_enroll_step",
                    "step": step,
                    "phrase": phrase,
                    "status": "reading",
                })
                with self._web_enroll_lock:
                    self._web_enroll_buffer.clear()
                await asyncio.sleep(2.0)

                # Capture status: recording for ~6 seconds
                with self._web_enroll_lock:
                    self._web_enroll_buffer.clear()
                await self.broadcast({
                    "type": "voice_enroll_step",
                    "step": step,
                    "phrase": phrase,
                    "status": "recording",
                })
                await asyncio.sleep(6.0)

                with self._web_enroll_lock:
                    raw = bytes(self._web_enroll_buffer)
                    self._web_enroll_buffer.clear()
                samples = np.frombuffer(raw, dtype=np.int16)
                recordings.append(samples)

            # All 3 captured: call VoiceAuthenticator.enroll
            va = self._get_voice_auth()
            if not va:
                raise RuntimeError("VoiceAuthenticator is not initialized")
            ok, msg = await asyncio.get_event_loop().run_in_executor(
                None, va.enroll, name, recordings, list(REGISTRATION_SENTENCES)
            )
            await self.broadcast({
                "type": "voice_enroll_done",
                "ok": ok,
                "message": msg,
            })
        except asyncio.CancelledError:
            await self.broadcast({
                "type": "voice_enroll_done",
                "ok": False,
                "message": "Enrollment was cancelled.",
            })
        except Exception as e:
            await self.broadcast({
                "type": "voice_enroll_done",
                "ok": False,
                "message": f"Enrollment failed: {e}",
            })
        finally:
            with self._web_enroll_lock:
                self._web_enroll_active = False
                self._web_enroll_buffer.clear()
                self._web_enroll_recordings.clear()
                self._web_enroll_step = 0
                self._web_enroll_task = None

    async def _safe_send_json(self, ws: WebSocket, data: dict) -> None:
        lock = getattr(ws, "_send_lock", None)
        if lock is not None:
            async with lock:
                await ws.send_json(data)
        else:
            await ws.send_json(data)

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await self._safe_send_json(ws, msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        try:
            from fastapi.staticfiles import StaticFiles
            app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        except Exception:
            pass

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in AGENT to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to AGENT…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/interrupt")
        async def interrupt_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            cl = req.headers.get("content-length")
            if cl and int(cl) > 4096:
                return JSONResponse({"error": "Payload too large"}, status_code=413)
            self.flush_phone_playback()
            if self._interrupt_callback:
                try:
                    self._interrupt_callback()
                except Exception as e:
                    print(f"[Dashboard] Interrupt error: {e}")
            return JSONResponse({"ok": True})

        @app.post("/api/audio-routing")
        async def audio_routing_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            # Enforce body size limit on bytes actually read (Item 6)
            body, code = await self._read_bounded_json(req, max_bytes=4096)
            if code == 413:
                return JSONResponse({"error": "Payload too large"}, status_code=413)
            if code != 200 or not isinstance(body, dict):
                return JSONResponse({"error": "Invalid JSON"}, status_code=400)

            routing_val = body.get("routing")
            pause_val = body.get("pause_mic_on_reply")
            if routing_val is None:
                return JSONResponse({"error": "Invalid routing option. Must be 'phone', 'laptop', or 'both'"}, status_code=400)

            clean_r, clean_p, err = self.validate_audio_routing(routing_val, pause_val)
            if err:
                return JSONResponse({"error": err}, status_code=400)

            if clean_r:
                self.set_audio_routing(clean_r)
            if clean_p is not None:
                self.set_pause_mic_on_reply(clean_p)

            await self.broadcast({
                "type": "audio_routing",
                "routing": self.get_audio_routing(),
                "pause_mic_on_reply": self.get_pause_mic_on_reply()
            })
            return JSONResponse({
                "ok": True,
                "routing": self.get_audio_routing(),
                "pause_mic_on_reply": self.get_pause_mic_on_reply()
            })

        @app.get("/api/audio-routing")
        async def audio_routing_get_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse({
                "ok": True,
                "routing": self.get_audio_routing(),
                "pause_mic_on_reply": self.get_pause_mic_on_reply()
            })

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = "", purpose: str = "", device_token: str = ""):
            tok = token.strip()
            dev_tok = device_token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Unauthorized")
                return

            is_enroll = (purpose == "enrollment")

            # Check enrollment purpose when live mic stream is already active (Item 2)
            if is_enroll and len(self._live_audio_clients) > 0:
                await websocket.accept()
                await websocket.close(
                    code=WS_CLOSE_DIFFERENT_DEVICE,
                    reason="Cannot enroll voice while a phone microphone stream is active.",
                )
                asyncio.create_task(self.broadcast({
                    "type": "sys",
                    "text": "Enrollment rejected: phone microphone stream is currently live."
                }))
                return

            # Mutual exclusion with active web enrollment:
            if self._web_enroll_active:
                if not is_enroll:
                    await websocket.accept()
                    await websocket.close(
                        code=WS_CLOSE_DIFFERENT_DEVICE,
                        reason="Voice enrollment in progress. Live conversation unavailable.",
                    )
                    return
                if self._web_enroll_ws is not None and self._web_enroll_ws is not websocket:
                    await websocket.accept()
                    await websocket.close(
                        code=WS_CLOSE_DIFFERENT_DEVICE,
                        reason="An enrollment audio stream is already active.",
                    )
                    return

            # Reconnect takeover logic keyed on paired device identity (Task 1 Final Patch Item 2):
            if not is_enroll and len(self._live_audio_clients) > 0:
                existing_ws = next(iter(self._live_audio_clients))
                existing_tok = self._live_audio_tokens.get(existing_ws, "")
                existing_dev = self._live_audio_device_tokens.get(existing_ws, "")
                if self._is_same_paired_device(tok, dev_tok, existing_tok, existing_dev):
                    dev_id = dev_tok or self._token_keys.get(tok) or tok
                    now_ts = time.time()
                    if ("audio", dev_id) in self._last_takeover_time and (now_ts - self._last_takeover_time[("audio", dev_id)] < 3.0):
                        # Task 1 Patch 4: if same device replaced stream < 3s ago, reject with 4008 (rate limited)
                        await websocket.accept()
                        await websocket.close(
                            code=WS_CLOSE_RATE_LIMITED,
                            reason="rate limited",
                        )
                        return
                    self._last_takeover_time[("audio", dev_id)] = now_ts
                    # Same paired session/device reconnecting -> takeover
                    self._replaced_websockets.add(existing_ws)
                    try:
                        await existing_ws.close(code=WS_CLOSE_REPLACED, reason="replaced")
                    except Exception:
                        pass
                    self._live_audio_clients.discard(existing_ws)
                    self._live_audio_tokens.pop(existing_ws, None)
                    self._live_audio_device_tokens.pop(existing_ws, None)
                    asyncio.create_task(self.broadcast({
                        "type": "sys",
                        "text": "Phone microphone reconnected (session takeover)."
                    }))
                else:
                    # Genuinely different device -> reject with 1008
                    await websocket.accept()
                    await websocket.close(
                        code=WS_CLOSE_DIFFERENT_DEVICE,
                        reason="A phone microphone stream is already active from another device.",
                    )
                    asyncio.create_task(self.broadcast({
                        "type": "sys",
                        "text": "Rejected incoming audio stream: a phone session is already streaming from another device."
                    }))
                    return

            await websocket.accept()
            if is_enroll:
                self._web_enroll_ws = websocket
            else:
                self._live_audio_clients.add(websocket)
                self._live_audio_tokens[websocket] = tok
                self._live_audio_device_tokens[websocket] = dev_tok
                self._last_phone_audio_time = time.time()
                await self.broadcast_mic_state()
                # Agent state: orb / status pill shows active / listening
                asyncio.create_task(self.broadcast({"type": "status", "state": "active"}))

            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))

            try:
                while True:
                    # Application-level liveness: 3s timeout with no heartbeat or audio (Item 1)
                    try:
                        msg = await asyncio.wait_for(websocket.receive(), timeout=3.0)
                    except asyncio.TimeoutError:
                        asyncio.create_task(self.broadcast({
                            "type": "sys",
                            "text": "Phone microphone silent timeout (3s no audio/heartbeat)."
                        }))
                        try:
                            await websocket.close(code=WS_CLOSE_GOING_AWAY, reason="Heartbeat timeout")
                        except Exception:
                            pass
                        break

                    if msg["type"] == "websocket.disconnect":
                        break

                    self._last_phone_audio_time = time.time()

                    if "bytes" in msg and msg["bytes"]:
                        data = msg["bytes"]
                        if is_enroll or self._web_enroll_active:
                            with self._web_enroll_lock:
                                self._web_enroll_buffer.extend(data)
                        else:
                            try:
                                self._phone_audio_queue.put_nowait(
                                    {"data": data, "mime_type": "audio/pcm"}
                                )
                            except asyncio.QueueFull:
                                pass  # drop frame rather than block
                    elif "text" in msg and msg["text"]:
                        # Heartbeat {"type": "hb"}
                        pass
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            finally:
                was_replaced = websocket in self._replaced_websockets
                self._replaced_websockets.discard(websocket)
                if is_enroll and self._web_enroll_ws is websocket:
                    self._web_enroll_ws = None
                self._live_audio_clients.discard(websocket)
                self._live_audio_tokens.pop(websocket, None)
                self._live_audio_device_tokens.pop(websocket, None)
                if not was_replaced:
                    if self._phone_mic_disconnect_callback:
                        try:
                            self._phone_mic_disconnect_callback()
                        except Exception:
                            pass
                    asyncio.create_task(self.broadcast(
                        {"type": "sys", "text": "Phone microphone stopped."}
                    ))
                    # Status accuracy: broadcast real restored state from AgentLive (Item 5)
                    restored_state = self.get_current_status()
                    asyncio.create_task(self.broadcast({"type": "status", "state": restored_state}))
                    await self.broadcast_mic_state()

        # ── Phone downstream audio playback ──────────────────────────────────
        # Behavior for multiple playback clients:
        # Deterministic broadcast fan-out. All connected playback clients receive the
        # audio chunks simultaneously. Each client maintains an independent bounded
        # queue (maxsize=100 chunks ≈ 5s). On overflow, oldest chunks are dropped for
        # that client independently without impacting other connected clients.

        @app.websocket("/ws/phone-playback")
        async def phone_playback_ws(websocket: WebSocket, token: str = "", device_token: str = ""):
            tok = token.strip()
            dev_tok = device_token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=WS_CLOSE_UNAUTHORIZED, reason="Unauthorized")
                return

            # Reconnect takeover for playback keyed on paired device identity (Item 2):
            existing_for_dev = [
                ws for ws in list(self._playback_clients)
                if self._is_same_paired_device(
                    tok, dev_tok,
                    self._playback_tokens.get(ws, ""),
                    self._playback_device_tokens.get(ws, "")
                )
            ]
            if existing_for_dev:
                dev_id = dev_tok or self._token_keys.get(tok) or tok
                now_ts = time.time()
                if ("playback", dev_id) in self._last_takeover_time and (now_ts - self._last_takeover_time[("playback", dev_id)] < 3.0):
                    # Task 1 Patch 4: if same device replaced playback stream < 3s ago, reject with 4008 (rate limited)
                    await websocket.accept()
                    await websocket.close(
                        code=WS_CLOSE_RATE_LIMITED,
                        reason="rate limited",
                    )
                    return
                self._last_takeover_time[("playback", dev_id)] = now_ts

            for old_ws in existing_for_dev:
                self._replaced_websockets.add(old_ws)
                try:
                    await old_ws.close(code=WS_CLOSE_REPLACED, reason="replaced")
                except Exception:
                    pass
                self._playback_clients.discard(old_ws)
                self._playback_queues.pop(old_ws, None)
                self._playback_tokens.pop(old_ws, None)
                self._playback_device_tokens.pop(old_ws, None)
                self._last_playback_hb_time.pop(old_ws, None)
                self._last_playback_remaining_sec.pop(old_ws, None)
                self._playback_connect_time.pop(old_ws, None)

            await websocket.accept()
            q: asyncio.Queue = asyncio.Queue(maxsize=100)
            now = time.time()
            self._playback_clients.add(websocket)
            self._playback_queues[websocket] = q
            self._playback_tokens[websocket] = tok
            self._playback_device_tokens[websocket] = dev_tok
            self._last_playback_hb_time[websocket] = now
            self._last_playback_remaining_sec[websocket] = 0.0
            self._playback_connect_time[websocket] = now

            async def _send_loop():
                while True:
                    chunk = await q.get()
                    if chunk is None:
                        break
                    await websocket.send_bytes(chunk)

            async def _recv_loop():
                while True:
                    try:
                        # 3s timeout for heartbeats from playback client (Item 1)
                        msg = await asyncio.wait_for(websocket.receive(), timeout=3.0)
                    except asyncio.TimeoutError:
                        break
                    if msg["type"] == "websocket.disconnect":
                        break
                    if "text" in msg and msg["text"]:
                        try:
                            payload = json.loads(msg["text"])
                            if payload.get("type") == "hb":
                                self._last_playback_hb_time[websocket] = time.time()
                                self._last_playback_remaining_sec[websocket] = float(payload.get("remaining_sec", 0.0))
                        except Exception:
                            pass

            send_task = asyncio.create_task(_send_loop())
            recv_task = asyncio.create_task(_recv_loop())

            try:
                done, pending = await asyncio.wait(
                    [send_task, recv_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            finally:
                send_task.cancel()
                recv_task.cancel()
                was_replaced = websocket in self._replaced_websockets
                self._replaced_websockets.discard(websocket)
                self._playback_clients.discard(websocket)
                self._playback_queues.pop(websocket, None)
                self._playback_tokens.pop(websocket, None)
                self._playback_device_tokens.pop(websocket, None)
                self._last_playback_hb_time.pop(websocket, None)
                self._last_playback_remaining_sec.pop(websocket, None)
                self._playback_connect_time.pop(websocket, None)
                if not was_replaced:
                    # Playback disconnect callback (Item 6: only changes routing, does NOT reset mic)
                    if self._phone_playback_disconnect_callback:
                        try:
                            self._phone_playback_disconnect_callback()
                        except Exception:
                            pass

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/api/memory")
        async def get_memory(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from memory.memory_manager import all_entries_for_ui
                entries = all_entries_for_ui()
            except Exception:
                entries = []
            return JSONResponse({"ok": True, "entries": entries})

        @app.get("/api/voice-auth/status")
        async def voice_auth_status(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            va = self._get_voice_auth()
            enrolled = va.is_enrolled() if va else False
            profile = va.profile() if va else {}
            return JSONResponse({
                "ok": True,
                "enrolled": enrolled,
                "name": profile.get("name", ""),
                "enrollment_active": self._web_enroll_active,
                "phone_in_use": self.is_phone_audio_in_use(),
            })

        @app.post("/api/voice-auth/enroll/start")
        async def enroll_start(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._web_enroll_active:
                return JSONResponse(
                    {"error": "An enrollment session is already in progress."},
                    status_code=409,
                )
            if self.is_phone_audio_in_use():
                return JSONResponse(
                    {"error": "Phone microphone is currently in use for an active conversation."},
                    status_code=409,
                )
            try:
                body = await req.json()
            except Exception:
                body = {}
            name = (body.get("name") or "").strip()
            if not name:
                return JSONResponse({"error": "Name is required for voice enrollment."}, status_code=400)

            from core.voice_auth import REGISTRATION_SENTENCES

            with self._web_enroll_lock:
                self._web_enroll_active = True
                self._web_enroll_name = name
                self._web_enroll_step = 1
                self._web_enroll_buffer.clear()
                self._web_enroll_recordings.clear()

            auto = body.get("auto", True)
            if auto:
                self._web_enroll_task = asyncio.create_task(self._run_web_enrollment_auto(name))
            else:
                await self.broadcast({
                    "type": "voice_enroll_step",
                    "step": 1,
                    "phrase": REGISTRATION_SENTENCES[0],
                    "status": "ready",
                })

            return JSONResponse({
                "ok": True,
                "step": 1,
                "phrase": REGISTRATION_SENTENCES[0],
                "total": len(REGISTRATION_SENTENCES),
            })

        @app.post("/api/voice-auth/enroll/next")
        async def enroll_next(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if not self._web_enroll_active:
                return JSONResponse({"error": "No enrollment session active."}, status_code=400)

            import numpy as np
            from core.voice_auth import REGISTRATION_SENTENCES

            with self._web_enroll_lock:
                raw = bytes(self._web_enroll_buffer)
                self._web_enroll_buffer.clear()
            samples = np.frombuffer(raw, dtype=np.int16)
            self._web_enroll_recordings.append(samples)
            self._web_enroll_step += 1

            if self._web_enroll_step <= len(REGISTRATION_SENTENCES):
                next_phrase = REGISTRATION_SENTENCES[self._web_enroll_step - 1]
                await self.broadcast({
                    "type": "voice_enroll_step",
                    "step": self._web_enroll_step,
                    "phrase": next_phrase,
                    "status": "recording",
                })
                return JSONResponse({
                    "ok": True,
                    "step": self._web_enroll_step,
                    "phrase": next_phrase,
                    "done": False,
                })
            else:
                # All phrases recorded
                recs_to_enroll = list(self._web_enroll_recordings)
                try:
                    va = self._get_voice_auth()
                    if not va:
                        raise RuntimeError("VoiceAuthenticator is not initialized")
                    ok, msg = await asyncio.get_event_loop().run_in_executor(
                        None, va.enroll, self._web_enroll_name, recs_to_enroll, list(REGISTRATION_SENTENCES)
                    )
                    await self.broadcast({
                        "type": "voice_enroll_done",
                        "ok": ok,
                        "message": msg,
                    })
                    return JSONResponse({"ok": ok, "done": True, "message": msg})
                except Exception as e:
                    await self.broadcast({
                        "type": "voice_enroll_done",
                        "ok": False,
                        "message": str(e),
                    })
                    return JSONResponse({"ok": False, "done": True, "message": str(e)})
                finally:
                    with self._web_enroll_lock:
                        self._web_enroll_active = False
                        self._web_enroll_buffer.clear()
                        self._web_enroll_recordings = []
                        self._web_enroll_step = 0

        @app.post("/api/voice-auth/enroll/cancel")
        async def enroll_cancel(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._web_enroll_task and not self._web_enroll_task.done():
                self._web_enroll_task.cancel()
            with self._web_enroll_lock:
                self._web_enroll_active = False
                self._web_enroll_buffer.clear()
                self._web_enroll_recordings.clear()
                self._web_enroll_step = 0
            await self.broadcast({
                "type": "voice_enroll_done",
                "ok": False,
                "message": "Enrollment cancelled.",
            })
            return JSONResponse({"ok": True})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
                return
            await websocket.accept()
            websocket._send_lock = asyncio.Lock()
            self._clients.add(websocket)
            await self._safe_send_json(websocket, {
                "type": "mic_state",
                "phone": self.is_phone_mic_active(),
                "desktop_muted": self.is_desktop_muted(),
            })
            await self._safe_send_json(websocket, {
                "type": "audio_routing",
                "routing": self.get_audio_routing(),
            })
            for entry in self._history[-50:]:
                try:
                    await self._safe_send_json(websocket, entry)
                except Exception:
                    break

            async def _send_metrics():
                try:
                    from ui import _metrics
                except ImportError:
                    return
                try:
                    while True:
                        snap = _metrics.snapshot()
                        net = snap.get("net", 0.0)
                        net_str = f"{net*1024:.0f} KB/s" if net < 1.0 else f"{net:.1f} MB/s"
                        await self._safe_send_json(websocket, {
                            "type": "metrics",
                            "cpu": snap.get("cpu", 0.0),
                            "mem": snap.get("mem", 0.0),
                            "net": net_str,
                        })
                        await asyncio.sleep(1)
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception:
                    pass

            metrics_task = asyncio.create_task(_send_metrics())
            try:
                while True:
                    try:
                        raw_msg = await websocket.receive_text()
                    except (WebSocketDisconnect, RuntimeError):
                        break
                    if len(raw_msg) > 65536:
                        continue
                    try:
                        data = json.loads(raw_msg)
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue

                    mtype = data.get("type")
                    if mtype == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
                    elif mtype == "interrupt":
                        self.flush_phone_playback()
                        if self._interrupt_callback:
                            try:
                                self._interrupt_callback()
                            except Exception:
                                pass
                    elif mtype == "audio_routing":
                        r, pause_mic, err = self.validate_audio_routing(
                            data.get("routing"), data.get("pause_mic_on_reply")
                        )
                        if err:
                            continue  # Discard invalid parameters without closing connection
                        if r is not None:
                            self.set_audio_routing(r)
                        if pause_mic is not None:
                            self.set_pause_mic_on_reply(pause_mic)
                        await self.broadcast({
                            "type": "audio_routing",
                            "routing": self.get_audio_routing(),
                            "pause_mic_on_reply": self.get_pause_mic_on_reply(),
                        })
            except WebSocketDisconnect:
                pass
            finally:
                metrics_task.cancel()
                self._clients.discard(websocket)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:8001 → Chrome tries https → self-signed cert warning → accept once → done."""
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT + 1)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT + 1, log_level="warning",
            ws_ping_interval=10.0, ws_ping_timeout=10.0,
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(f"[Dashboard] Manual entry:  {self._ip}:{PORT + 1}  (type in browser, accept cert once)")
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        # Firewall setup runs in a thread — uvicorn starts immediately,
        # no waiting for UAC dialogs or subprocess timeouts.
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

        # Generate the TLS pair on first run so no private key ships in the repo.
        _ensure_certs()

        use_ssl  = self._ssl_enabled()
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"

        if use_ssl:
            asyncio.create_task(self._serve_alias())

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT, log_level="warning",
            ws_ping_interval=10.0, ws_ping_timeout=10.0,
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)} if use_ssl else {}),
        )

        proto = "https" if use_ssl else "http"
        print(f"[Dashboard] {proto}://{self._ip}:{PORT}")
        print("[Dashboard] Press 'Remote Control' in AGENT UI to get the QR code.")
        await uvicorn.Server(cfg).serve()
