#computer_settings.py
import json
import re
import sys
import time
import subprocess
import platform
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

from core import confirm
from core.undo import push_undo

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

if _OS == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_api_key() -> str:
    path = _get_base_dir() / "config" / "api_keys.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _get_macos_wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0" 

def volume_up():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumeup")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) + 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"],
            capture_output=True)

def volume_down():
    if _OS == "Windows":
        for _ in range(5): pyautogui.press("volumedown")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            "set volume output volume (output volume of (get volume settings) - 10)"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"],
            capture_output=True)

def _get_windows_volume():
    """Returns POINTER(IAudioEndpointVolume) or None."""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        speakers = AudioUtilities.GetSpeakers()
        vol = getattr(speakers, "EndpointVolume", None)
        if vol is None and hasattr(speakers, "Activate"):
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(interface, POINTER(IAudioEndpointVolume))
        return vol
    except Exception as e:
        print(f"[Settings] Windows volume lookup failed: {e}")
        return None

def volume_mute():
    if _OS == "Windows":
        vol = _get_windows_volume()
        if vol:
            vol.SetMute(1, None)
            return
        print("[Settings] Could not mute: volume control unavailable")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume with output muted"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            capture_output=True)

def volume_unmute():
    if _OS == "Windows":
        vol = _get_windows_volume()
        if vol:
            vol.SetMute(0, None)
            return
        print("[Settings] Could not unmute: volume control unavailable")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume without output muted"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
            capture_output=True)

def volume_toggle_mute():
    if _OS == "Windows":
        vol = _get_windows_volume()
        if vol:
            cur = bool(vol.GetMute())
            vol.SetMute(0 if cur else 1, None)
            return
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", "set volume output muted (not (output muted of (get volume settings)))"],
            capture_output=True)
    else:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True)

def volume_get() -> int | None:
    """Current master volume 0-100, or None if this platform will not say.

    Undo needs a "before" value, and reading one is cheap on every OS we
    support. Where it is not readable the action simply is not registered as
    undoable — a wrong undo is worse than no undo."""
    try:
        if _OS == "Windows":
            vol = _get_windows_volume()
            if vol:
                scalar = vol.GetMasterVolumeLevelScalar()
                return max(0, min(100, round(scalar * 100)))
            return None
        if _OS == "Darwin":
            r = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                               capture_output=True, text=True, timeout=5)
            return max(0, min(100, int(r.stdout.strip())))
        r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                           capture_output=True, text=True, timeout=5)
        m = re.search(r"(\d+)%", r.stdout)
        return max(0, min(100, int(m.group(1)))) if m else None
    except Exception:
        return None


def brightness_get() -> int | None:
    """Current brightness 0-100, or None where it cannot be read."""
    try:
        if _OS == "Windows":
            r = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness)"
                 ".CurrentBrightness"],
                capture_output=True, text=True, timeout=5, **_WIN_HIDE
            )
            return max(0, min(100, int(r.stdout.strip())))
        if _OS == "Linux" and subprocess.run(
                ["which", "brightnessctl"], capture_output=True).returncode == 0:
            cur = int(subprocess.run(["brightnessctl", "get"],
                                     capture_output=True, text=True, timeout=5).stdout.strip())
            mx  = int(subprocess.run(["brightnessctl", "max"],
                                     capture_output=True, text=True, timeout=5).stdout.strip())
            return max(0, min(100, round(cur * 100 / mx))) if mx else None
    except Exception:
        pass
    return None


def brightness_set(value: int) -> None:
    """Set brightness to an absolute percentage. Only used to restore a value
    captured before a change, so it is undo's counterpart to the up/down pair."""
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        subprocess.run(
            ["powershell", "-Command",
             "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
             f".WmiSetBrightness(1, {value})"],
            capture_output=True, timeout=5, **_WIN_HIDE
        )
    elif _OS == "Linux":
        subprocess.run(["brightnessctl", "set", f"{value}%"], capture_output=True)


def volume_set(value: int):
    value = max(0, min(100, int(value)))
    if _OS == "Windows":
        try:
            vol = _get_windows_volume()
            if vol:
                vol.SetMasterVolumeLevelScalar(value / 100.0, None)
                if value > 0 and vol.GetMute():
                    vol.SetMute(0, None)
                return
        except Exception as e:
            print(f"[Settings] pycaw volume_set failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {value}"],
            capture_output=True)
        return
    else:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"],
            capture_output=True)
        return

def brightness_up():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 144'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "+10%"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(min(1.0,b+0.1))")',
                shell=True, capture_output=True
            )
    else:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Min(100, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness + 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness up failed on Windows: {e}")

def brightness_down():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to key code 145'],
            capture_output=True)
    elif _OS == "Linux":
        if subprocess.run(["which", "brightnessctl"],
                capture_output=True).returncode == 0:
            subprocess.run(["brightnessctl", "set", "10%-"], capture_output=True)
        else:
            subprocess.run(
                'xrandr --output $(xrandr | grep " connected" | head -1 | cut -d " " -f1)'
                ' --brightness $(python3 -c "import subprocess; '
                'b=float(subprocess.check_output([\"xrandr\",\"--verbose\"]).decode()'
                '.split(\"Brightness:\")[1].split()[0]); print(max(0.1,b-0.1))")',
                shell=True, capture_output=True
            )
    else:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods)"
                 ".WmiSetBrightness(1, [math]::Max(0, "
                 "(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness).CurrentBrightness - 10))"],
                capture_output=True, timeout=5, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] Brightness down failed on Windows: {e}")

def close_app():
    if _OS == "Darwin": pyautogui.hotkey("command", "q")
    else:               pyautogui.hotkey("alt", "f4")

def close_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def full_screen():
    if _OS == "Darwin": pyautogui.hotkey("ctrl", "command", "f")
    else:               pyautogui.press("f11")

def minimize_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "m")
    else:               pyautogui.hotkey("win", "down")

def maximize_window():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to keystroke "f" '
            'using {control down, command down}'],
            capture_output=True)
    elif _OS == "Windows":
        pyautogui.hotkey("win", "up")
    else:
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                capture_output=True)
        except Exception:
            pyautogui.hotkey("super", "up")

def snap_left():
    if _OS == "Windows":
        pyautogui.hotkey("win", "left")
    elif _OS == "Darwin":
        # macOS has no built-in snap; try Rectangle app shortcut if installed
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "left")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,0,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def snap_right():
    if _OS == "Windows":
        pyautogui.hotkey("win", "right")
    elif _OS == "Darwin":
        try:
            subprocess.run(["open", "-a", "Rectangle"], capture_output=True, timeout=1)
        except Exception:
            pass
        pyautogui.hotkey("ctrl", "option", "right")
    else:  # Linux
        try:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", "0,960,0,960,1080"],
                capture_output=True)
        except Exception:
            pass

def switch_window():
    if _OS == "Darwin": pyautogui.hotkey("command", "tab")
    else:               pyautogui.hotkey("alt", "tab")

def show_desktop():
    if _OS == "Darwin":   pyautogui.hotkey("fn", "f11")
    elif _OS == "Windows": pyautogui.hotkey("win", "d")
    else:                  pyautogui.hotkey("super", "d")

def open_task_manager():
    if _OS == "Windows":
        pyautogui.hotkey("ctrl", "shift", "esc")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "Activity Monitor"])
    else:
        for cmd in [["gnome-system-monitor"], ["xfce4-taskmanager"], ["htop"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                break


def focus_search():
    if _OS == "Darwin": pyautogui.hotkey("command", "l")
    else:               pyautogui.hotkey("ctrl", "l")

def pause_video():      pyautogui.press("space")

def refresh_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "r")
    else:               pyautogui.press("f5")

def close_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "w")
    else:               pyautogui.hotkey("ctrl", "w")

def new_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "t")
    else:               pyautogui.hotkey("ctrl", "t")

def next_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketright")
    else:               pyautogui.hotkey("ctrl", "tab")

def prev_tab():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "bracketleft")
    else:               pyautogui.hotkey("ctrl", "shift", "tab")

def go_back():
    if _OS == "Darwin": pyautogui.hotkey("command", "left")
    else:               pyautogui.hotkey("alt", "left")

def go_forward():
    if _OS == "Darwin": pyautogui.hotkey("command", "right")
    else:               pyautogui.hotkey("alt", "right")

def zoom_in():
    if _OS == "Darwin": pyautogui.hotkey("command", "equal")
    else:               pyautogui.hotkey("ctrl", "equal")

def zoom_out():
    if _OS == "Darwin": pyautogui.hotkey("command", "minus")
    else:               pyautogui.hotkey("ctrl", "minus")

def zoom_reset():
    if _OS == "Darwin": pyautogui.hotkey("command", "0")
    else:               pyautogui.hotkey("ctrl", "0")

def find_on_page():
    if _OS == "Darwin": pyautogui.hotkey("command", "f")
    else:               pyautogui.hotkey("ctrl", "f")

def reload_page_n(n: int):
    for _ in range(max(1, n)):
        refresh_page()
        time.sleep(0.8)


def scroll_up(amount: int = 500):    pyautogui.scroll(amount)
def scroll_down(amount: int = 500):  pyautogui.scroll(-amount)

def scroll_top():
    if _OS == "Darwin": pyautogui.hotkey("command", "up")
    else:               pyautogui.hotkey("ctrl", "home")

def scroll_bottom():
    if _OS == "Darwin": pyautogui.hotkey("command", "down")
    else:               pyautogui.hotkey("ctrl", "end")

def page_up():   pyautogui.press("pageup")
def page_down(): pyautogui.press("pagedown")


def copy():
    if _OS == "Darwin": pyautogui.hotkey("command", "c")
    else:               pyautogui.hotkey("ctrl", "c")

def paste():
    if _OS == "Darwin": pyautogui.hotkey("command", "v")
    else:               pyautogui.hotkey("ctrl", "v")

def cut():
    if _OS == "Darwin": pyautogui.hotkey("command", "x")
    else:               pyautogui.hotkey("ctrl", "x")

def undo():
    if _OS == "Darwin": pyautogui.hotkey("command", "z")
    else:               pyautogui.hotkey("ctrl", "z")

def redo():
    if _OS == "Darwin": pyautogui.hotkey("command", "shift", "z")
    else:               pyautogui.hotkey("ctrl", "y")

def select_all():
    if _OS == "Darwin": pyautogui.hotkey("command", "a")
    else:               pyautogui.hotkey("ctrl", "a")

def save_file():
    if _OS == "Darwin": pyautogui.hotkey("command", "s")
    else:               pyautogui.hotkey("ctrl", "s")

def press_enter():   pyautogui.press("enter")
def press_escape():  pyautogui.press("escape")
def press_key(key: str): pyautogui.press(key)

def type_text(text: str, press_enter_after: bool = False):
    if not text:
        return
    if _PYPERCLIP:
        pyperclip.copy(str(text))
        time.sleep(0.15)
        paste()
    else:
        pyautogui.write(str(text), interval=0.03)
    if press_enter_after:
        time.sleep(0.1)
        pyautogui.press("enter")

def take_screenshot():
    if _OS == "Windows":
        pyautogui.hotkey("win", "shift", "s")
    elif _OS == "Darwin":
        pyautogui.hotkey("command", "shift", "3")
    else:
        for cmd in [["scrot"], ["gnome-screenshot"], ["import", "-window", "root", "screenshot.png"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        pyautogui.hotkey("ctrl", "print_screen")

def lock_screen():
    if _OS == "Windows":
        pyautogui.hotkey("win", "l")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        for cmd in [
            ["gnome-screensaver-command", "-l"],
            ["xdg-screensaver", "lock"],
            ["loginctl", "lock-session"],
        ]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.run(cmd, capture_output=True)
                return

def open_system_settings():
    if _OS == "Windows":
        pyautogui.hotkey("win", "i")
    elif _OS == "Darwin":
        subprocess.Popen(["open", "-a", "System Preferences"])
    else:
        for cmd in [["gnome-control-center"], ["xfce4-settings-manager"], ["kcmshell5"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return

def open_file_explorer():
    if _OS == "Windows":
        pyautogui.hotkey("win", "e")
    elif _OS == "Darwin":
        subprocess.Popen(["open", str(Path.home())])
    else:
        for cmd in [["nautilus"], ["thunar"], ["dolphin"], ["nemo"]]:
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd)
                return
        subprocess.Popen(["xdg-open", str(Path.home())])

def sleep_display():
    if _OS == "Windows":
        try:
            import ctypes
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        except Exception as e:
            print(f"[Settings] sleep_display failed: {e}")
    elif _OS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"], capture_output=True)
    else:
        subprocess.run(["xset", "dpms", "force", "off"], capture_output=True)

def open_run():
    if _OS == "Windows":
        pyautogui.hotkey("win", "r")

def dark_mode():
    if _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell app "System Events" to tell appearance preferences '
            'to set dark mode to not dark mode'],
            capture_output=True)
    elif _OS == "Windows":
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            current, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 1 - current)
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[Settings] dark_mode registry failed: {e}")
    else:
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True
            )
            current = result.stdout.strip()
            new_scheme = "'default'" if "dark" in current else "'prefer-dark'"
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_scheme],
                capture_output=True
            )
        except Exception as e:
            print(f"[Settings] dark_mode Linux failed: {e}")

def toggle_wifi():
    if _OS == "Darwin":
        iface = _get_macos_wifi_interface()
        result = subprocess.run(
            ["networksetup", "-getairportpower", iface],
            capture_output=True, text=True
        )
        state = "off" if "On" in result.stdout else "on"
        subprocess.run(["networksetup", "-setairportpower", iface, state],
            capture_output=True)
    elif _OS == "Windows":
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "$adapter = Get-NetAdapter | Where-Object {$_.PhysicalMediaType -eq 'Native 802.11'};"
                 "if ($adapter.Status -eq 'Up') { Disable-NetAdapter -Name $adapter.Name -Confirm:$false }"
                 "else { Enable-NetAdapter -Name $adapter.Name -Confirm:$false }"],
                capture_output=True, timeout=10, **_WIN_HIDE
            )
        except Exception as e:
            print(f"[Settings] toggle_wifi Windows failed: {e}")
    else:
        try:
            result = subprocess.run(["nmcli", "radio", "wifi"], capture_output=True, text=True)
            state  = "off" if "enabled" in result.stdout else "on"
            subprocess.run(["nmcli", "radio", "wifi", state], capture_output=True)
        except Exception as e:
            print(f"[Settings] toggle_wifi Linux failed: {e}")

def wifi_status() -> dict:
    """Query Wi-Fi status, connection state, SSID, and signal."""
    if _OS == "Windows":
        try:
            res = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5, **_WIN_HIDE
            )
            data = {}
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip().lower()] = v.strip()
            state = data.get("state", "disconnected").lower()
            adapter = data.get("description", "Wi-Fi Adapter")
            if state == "connected":
                ssid = data.get("ssid", "Unknown")
                signal = data.get("signal", "Unknown")
                radio = data.get("radio type", "")
                return {
                    "connected": True,
                    "state": state,
                    "ssid": ssid,
                    "signal": signal,
                    "adapter": adapter,
                    "radio_type": radio,
                    "message": f"Wi-Fi is connected to '{ssid}' with {signal} signal strength.",
                }
            elif state == "disconnected":
                return {
                    "connected": False,
                    "state": state,
                    "ssid": None,
                    "signal": None,
                    "adapter": adapter,
                    "radio_type": None,
                    "message": "Wi-Fi is enabled but disconnected from any network.",
                }
            else:
                return {
                    "connected": False,
                    "state": state,
                    "ssid": None,
                    "signal": None,
                    "adapter": adapter,
                    "radio_type": None,
                    "message": f"Wi-Fi interface state: {state}.",
                }
        except Exception as e:
            return {
                "connected": False,
                "state": "error",
                "ssid": None,
                "signal": None,
                "adapter": None,
                "radio_type": None,
                "message": f"Could not query Wi-Fi status on Windows: {e}",
            }
    elif _OS == "Darwin":
        try:
            iface = _get_macos_wifi_interface()
            res = subprocess.run(
                ["networksetup", "-getairportnetwork", iface],
                capture_output=True, text=True, timeout=5
            )
            out = res.stdout.strip()
            if "Current Wi-Fi Network:" in out:
                ssid = out.split("Current Wi-Fi Network:", 1)[1].strip()
                return {
                    "connected": True,
                    "state": "connected",
                    "ssid": ssid,
                    "signal": None,
                    "adapter": iface,
                    "radio_type": None,
                    "message": f"Wi-Fi is connected to '{ssid}'.",
                }
            return {
                "connected": False,
                "state": "disconnected",
                "ssid": None,
                "signal": None,
                "adapter": iface,
                "radio_type": None,
                "message": "Wi-Fi is not connected to any network.",
            }
        except Exception as e:
            return {
                "connected": False,
                "state": "error",
                "ssid": None,
                "signal": None,
                "adapter": None,
                "radio_type": None,
                "message": f"Could not query Wi-Fi status on macOS: {e}",
            }
    else:  # Linux
        try:
            res = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid,signal,device", "wifi"],
                capture_output=True, text=True, timeout=5
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split(":")
                if len(parts) >= 4 and parts[0] == "yes":
                    ssid = parts[1]
                    signal = parts[2]
                    dev = parts[3]
                    return {
                        "connected": True,
                        "state": "connected",
                        "ssid": ssid,
                        "signal": f"{signal}%",
                        "adapter": dev,
                        "radio_type": None,
                        "message": f"Wi-Fi is connected to '{ssid}' ({signal}% signal).",
                    }
            return {
                "connected": False,
                "state": "disconnected",
                "ssid": None,
                "signal": None,
                "adapter": None,
                "radio_type": None,
                "message": "Wi-Fi is not connected.",
            }
        except Exception as e:
            return {
                "connected": False,
                "state": "error",
                "ssid": None,
                "signal": None,
                "adapter": None,
                "radio_type": None,
                "message": f"Could not query Wi-Fi status on Linux: {e}",
            }


def battery_status() -> dict:
    """Query battery percentage, charging state, and remaining runtime."""
    try:
        if _PSUTIL:
            b = psutil.sensors_battery()
            if b is not None:
                pct = round(b.percent)
                plugged = bool(b.power_plugged)
                secs = b.secsleft
                stat = "Plugged in / Charging" if plugged else "On battery (discharging)"
                t_rem = ""
                if secs > 0 and not plugged:
                    hrs = secs // 3600
                    mins = (secs % 3600) // 60
                    t_rem = f" (~{hrs}h {mins}m remaining)"
                return {
                    "percent": pct,
                    "plugged": plugged,
                    "secs_left": secs if secs > 0 else None,
                    "has_battery": True,
                    "message": f"Battery is at {pct}%, {stat}{t_rem}."
                }
        return {
            "percent": None,
            "plugged": True,
            "secs_left": None,
            "has_battery": False,
            "message": "No battery detected (desktop or AC-only power system)."
        }
    except Exception as e:
        return {
            "percent": None,
            "plugged": None,
            "secs_left": None,
            "has_battery": False,
            "message": f"Could not query battery status: {e}"
        }


def bluetooth_status() -> dict:
    """Query Bluetooth service status, availability, and active connected devices."""
    if _OS == "Windows":
        ps_cmd = (
            "$svc = Get-Service bthserv -ErrorAction SilentlyContinue; "
            "$svc_status = if ($svc) { $svc.Status.ToString() } else { 'Unavailable' }; "
            "$devs = @(Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Present -eq $true } | Select-Object -ExpandProperty FriendlyName); "
            "$obj = [PSCustomObject]@{ "
            "  service = $svc_status; "
            "  enabled = ($svc_status -eq 'Running'); "
            "  devices = $devs "
            "}; "
            "$obj | ConvertTo-Json -Compress"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=8, **_WIN_HIDE
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout.strip())
                raw_devs = data.get("devices") or []
                if isinstance(raw_devs, str):
                    raw_devs = [raw_devs]
                ignored_keywords = [
                    "generic", "enumerator", "protocol tdi", "gateway service",
                    "avrcp transport", "push service", "access service",
                    "pse service", "pan service", "area network"
                ]
                meaningful_devs = []
                for d in raw_devs:
                    d_low = d.lower()
                    if not any(k in d_low for k in ignored_keywords):
                        if d not in meaningful_devs:
                            meaningful_devs.append(d)

                enabled = bool(data.get("enabled", False))
                service_status = data.get("service", "Unknown")
                if enabled:
                    if meaningful_devs:
                        dev_str = ", ".join(meaningful_devs[:5])
                        msg = f"Bluetooth is enabled (Service: {service_status}). Active devices: {dev_str}."
                    else:
                        msg = f"Bluetooth is enabled (Service: {service_status}), with no active paired devices connected."
                else:
                    msg = f"Bluetooth service is {service_status}."

                return {
                    "enabled": enabled,
                    "service": service_status,
                    "devices": meaningful_devs,
                    "message": msg
                }
        except Exception as e:
            return {"enabled": False, "service": "Error", "devices": [], "message": f"Could not query Bluetooth: {e}"}

    elif _OS == "Darwin":
        try:
            res = subprocess.run(
                ["defaults", "read", "/Library/Preferences/com.apple.Bluetooth", "ControllerPowerState"],
                capture_output=True, text=True, timeout=5
            )
            enabled = res.stdout.strip() == "1"
            return {
                "enabled": enabled,
                "service": "Running" if enabled else "Off",
                "devices": [],
                "message": f"Bluetooth is {'enabled' if enabled else 'disabled'}."
            }
        except Exception as e:
            return {"enabled": False, "service": "Error", "devices": [], "message": f"Bluetooth query failed: {e}"}

    else:  # Linux
        try:
            res = subprocess.run(["rfkill", "list", "bluetooth"], capture_output=True, text=True, timeout=5)
            blocked = "Soft blocked: yes" in res.stdout or "Hard blocked: yes" in res.stdout
            return {
                "enabled": not blocked,
                "service": "Blocked" if blocked else "Running",
                "devices": [],
                "message": f"Bluetooth is {'disabled / blocked' if blocked else 'enabled'}."
            }
        except Exception as e:
            return {"enabled": False, "service": "Error", "devices": [], "message": f"Bluetooth query failed: {e}"}


def restart_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/r", "/t", "10"], capture_output=True, **_WIN_HIDE)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to restart'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "reboot"], capture_output=True)

def shutdown_computer():
    if _OS == "Windows":
        subprocess.run(["shutdown", "/s", "/t", "10"], capture_output=True)
    elif _OS == "Darwin":
        subprocess.run(["osascript", "-e",
            'tell application "System Events" to shut down'],
            capture_output=True)
    else:
        subprocess.run(["systemctl", "poweroff"], capture_output=True)

ACTION_MAP: dict[str, callable] = {
    "volume_up":           volume_up,
    "volume_down":         volume_down,
    "mute":                volume_mute,
    "unmute":              volume_unmute,
    "toggle_mute":         volume_toggle_mute,
    "brightness_up":       brightness_up,
    "brightness_down":     brightness_down,
    "sleep_display":       sleep_display,
    "screen_off":          sleep_display,
    "pause_video":         pause_video,
    "play_pause":          pause_video,
    "close_app":           close_app,
    "close_window":        close_window,
    "full_screen":         full_screen,
    "fullscreen":          full_screen,
    "minimize":            minimize_window,
    "maximize":            maximize_window,
    "snap_left":           snap_left,
    "snap_right":          snap_right,
    "switch_window":       switch_window,
    "show_desktop":        show_desktop,
    "task_manager":        open_task_manager,
    "focus_search":        focus_search,
    "refresh_page":        refresh_page,
    "reload":              refresh_page,
    "close_tab":           close_tab,
    "new_tab":             new_tab,
    "next_tab":            next_tab,
    "prev_tab":            prev_tab,
    "go_back":             go_back,
    "go_forward":          go_forward,
    "zoom_in":             zoom_in,
    "zoom_out":            zoom_out,
    "zoom_reset":          zoom_reset,
    "find_on_page":        find_on_page,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "scroll_top":          scroll_top,
    "scroll_bottom":       scroll_bottom,
    "page_up":             page_up,
    "page_down":           page_down,
    "copy":                copy,
    "paste":               paste,
    "cut":                 cut,
    "undo":                undo,
    "redo":                redo,
    "select_all":          select_all,
    "save":                save_file,
    "enter":               press_enter,
    "escape":              press_escape,
    "screenshot":          take_screenshot,
    "lock_screen":         lock_screen,
    "open_settings":       open_system_settings,
    "file_explorer":       open_file_explorer,
    "open_run":            open_run,
    "dark_mode":           dark_mode,
    "toggle_wifi":         toggle_wifi,
    "wifi_status":         wifi_status,
    "battery_status":      battery_status,
    "power_status":        battery_status,
    "bluetooth_status":    bluetooth_status,
    "volume_get":          volume_get,
    "get_volume":          volume_get,
    "brightness_get":      brightness_get,
    "get_brightness":      brightness_get,
    "restart":             restart_computer,
    "shutdown":            shutdown_computer,
}

# ── What needs a human, and what just needs an undo ──────────────────────────
#
# The old gate was `_DANGEROUS_ACTIONS = {"restart", "shutdown"}` checked against
# a `confirmed` parameter the MODEL filled in — so the model confirmed its own
# shutdowns, and everything else (switching off the WiFi this assistant is
# talking over) had no gate at all.
#
# Two lists now, and the split is about reversibility, not about how alarming
# the word sounds:
#
#   _IRREVERSIBLE — a human presses a button on the HUD. Nothing else.
#   everything else — done immediately, with an undo pushed if it can be undone.
#
# Asking before every action is what makes an assistant unusable, and every
# question costs a round trip. Undo is both faster and safer than a prompt.
_IRREVERSIBLE = {
    "restart":     ("Restart this computer",
                    "Anything unsaved will be lost. The computer restarts in 10 seconds."),
    "shutdown":    ("Shut this computer down",
                    "Anything unsaved will be lost. The computer powers off in 10 seconds."),
    # Not obviously destructive, and that is exactly why it was missed: turning
    # the WiFi off cuts the assistant's own connection to the Live API, so it
    # cannot be asked to turn it back on.
    "toggle_wifi": ("Switch WiFi off or on",
                    "If this switches WiFi off, AGENT loses its connection and "
                    "cannot switch it back on by voice."),
}

# Kept so anything still importing the old name keeps working.
_DANGEROUS_ACTIONS = set(_IRREVERSIBLE)


# ── Local intent resolution ──────────────────────────────────────────────────
#
# This used to be an entire extra Gemini call, made INSIDE the tool: the Live
# model called computer_settings, and computer_settings then asked a second
# model which action was meant. Every "turn the volume down" paid for two round
# trips — and when that second call failed, the fallback was
# `description.lower().replace(" ", "_")`, which turns the Turkish for "turn it
# down" into `sesi_kis`, i.e. straight to "Unknown action".
#
# Nothing here needs a language model. The Live model already understands the
# sentence; it only needed the vocabulary, which the tool declaration now spells
# out in full. What is left is spelling tolerance, and difflib does that in
# microseconds instead of ~600 ms and a quota unit.
_ALIASES = {
    "volume_up":       ("louder", "raise volume", "turn it up", "increase volume"),
    "volume_down":     ("quieter", "lower volume", "turn it down", "decrease volume"),
    "mute":            ("silence", "sound off", "no sound"),
    "brightness_up":   ("brighter", "raise brightness", "increase brightness"),
    "brightness_down": ("dimmer", "dim", "lower brightness", "decrease brightness"),
    "close_window":    ("close this", "close it"),
    "full_screen":     ("fullscreen", "maximise screen"),
    "show_desktop":    ("minimise everything", "go to desktop"),
    "lock_screen":     ("lock", "lock the pc", "lock computer"),
    "sleep_display":   ("screen off", "turn off the screen", "display off"),
    "dark_mode":       ("night mode", "light mode", "toggle theme"),
    "toggle_wifi":     ("wifi", "wi-fi", "internet off", "internet on"),
    "wifi_status":     ("wifi status", "wifi info", "check wifi", "network status", "is wifi connected"),
    "battery_status":  ("battery", "battery status", "power status", "battery percentage", "check battery", "how much battery"),
    "bluetooth_status":("bluetooth", "bluetooth status", "check bluetooth", "is bluetooth on"),
    "volume_get":      ("get volume", "current volume", "what is the volume", "volume level"),
    "brightness_get":  ("get brightness", "current brightness", "what is the brightness", "brightness level"),
    "task_manager":    ("processes", "task list"),
    "screenshot":      ("capture screen", "take a screenshot", "snip"),
    "refresh_page":    ("refresh", "reload page"),
    "new_tab":         ("open a tab", "open new tab"),
    "shutdown":        ("power off", "turn off the computer", "switch off the pc"),
    "restart":         ("reboot", "restart the pc"),
}

_VALUE_ACTIONS = {
    "volume_set", "type_text", "press_key", "reload_n",
    "scroll_up", "scroll_down", "wifi_status", "battery_status",
    "power_status", "bluetooth_status", "volume_get", "get_volume",
    "brightness_get", "get_brightness",
}


def _normalise(text: str) -> str:
    return (text or "").strip().lower().replace("-", "_").replace(" ", "_")


def _detect_action(description: str) -> dict:
    """Resolve a free-text description to an action name, locally.

    Returns {"action": name, "value": ...}; `action` is "" when nothing matched,
    which the caller turns into a message naming real candidates — one round
    trip, and only in the case that used to cost one anyway."""
    raw  = (description or "").strip()
    norm = _normalise(raw)
    if not norm:
        return {"action": "", "value": None}

    known = set(ACTION_MAP) | _VALUE_ACTIONS

    # 1. Already an action name.
    if norm in known:
        return {"action": norm, "value": None}

    low = raw.lower()

    # 2. "set volume to 30", "sesi 30 yap" — a number next to a volume word.
    num = re.search(r"(\d{1,3})\s*%?", low)
    if num and any(w in low for w in ("volume", "ses", "sound", "lautstark", "громкость")):
        return {"action": "volume_set", "value": max(0, min(100, int(num.group(1))))}

    # 3. Alias phrases.
    for action, phrases in _ALIASES.items():
        if any(_normalise(p) == norm or p in low for p in phrases):
            return {"action": action, "value": None}

    # 4. Fuzzy match on the action names — catches "fullscren", "volumeup".
    import difflib
    close = difflib.get_close_matches(norm, sorted(known), n=1, cutoff=0.72)
    if close:
        return {"action": close[0], "value": None}

    # 5. Substring: "increase_the_brightness" contains "brightness".
    for action in sorted(known, key=len, reverse=True):
        if len(action) > 4 and (action in norm or norm in action):
            return {"action": action, "value": None}

    return {"action": "", "value": None}


def _suggest(description: str) -> str:
    """What to tell the model when nothing matched. Names real actions so its
    retry lands, instead of the old 'Unknown action' dead end."""
    import difflib
    near = difflib.get_close_matches(_normalise(description),
                                     sorted(ACTION_MAP), n=5, cutoff=0.3)
    hint = ", ".join(near) if near else ", ".join(sorted(ACTION_MAP)[:12])
    return (f"I could not match '{description}' to a computer action. "
            f"Call computer_settings again with an exact `action` from: {hint}.")

def computer_settings(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> dict:
    if not _PYAUTOGUI:
        return {
            "success": False,
            "action": "unknown",
            "value": None,
            "message": "pyautogui is not installed. Run: pip install pyautogui",
        }

    params      = parameters or {}
    raw_action  = params.get("action", "").strip()
    description = params.get("description", "").strip()
    value       = params.get("value", None)

    if not raw_action and description:
        detected   = _detect_action(description)
        raw_action = detected.get("action", "")
        if value is None:
            value = detected.get("value")

    action = raw_action.lower().strip().replace(" ", "_").replace("-", "_")

    if not action:
        return {
            "success": False,
            "action": raw_action or "unknown",
            "value": None,
            "message": _suggest(description or raw_action),
        }

    print(f"[Settings] Action: {action}  Value: {value}  OS: {_OS}")
    if player:
        player.write_log(f"[Settings] {action}")

    # ── The gate ─────────────────────────────────────────────────────────────
    # A human presses a button, or this does not happen. The model can no longer
    # write its own permission slip, and the action itself is handed to the UI
    # rather than performed here — so returning early is not "declining", it is
    # "parked until someone says yes".
    if action in _IRREVERSIBLE:
        title, detail = _IRREVERSIBLE[action]
        func = ACTION_MAP.get(action)
        if func is None:
            return {
                "success": False,
                "action": action,
                "value": None,
                "message": f"Unknown action: '{raw_action}'.",
            }
        if confirm.pending_title():
            return {
                "success": False,
                "action": action,
                "value": None,
                "message": "There is already a confirmation waiting on screen. Ask the user to answer that one first.",
            }
        req_msg = confirm.request(
            key=action, title=title, detail=detail,
            run=lambda f=func, a=action: (f(), f"{a} done.")[1],
        )
        return {
            "success": True,
            "action": action,
            "value": "confirmation_pending",
            "message": req_msg,
        }

    if action == "volume_set":
        try:
            target = int(value if value is not None else 50)
            before = volume_get()
            volume_set(target)
            if before is not None:
                push_undo(f"volume {before}% → {target}%",
                          lambda b=before: (volume_set(b), f"Back to {b}%.")[1])
            return {
                "success": True,
                "action": "volume_set",
                "value": target,
                "message": f"Volume set to {target}%.",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "volume_set",
                "value": None,
                "message": f"Could not set volume: {e}",
            }

    if action in ("volume_get", "get_volume"):
        cur = volume_get()
        return {
            "success": True,
            "action": "volume_get",
            "value": cur,
            "message": f"Master volume is at {cur}%." if cur is not None else "Could not determine current volume.",
        }

    if action in ("brightness_get", "get_brightness"):
        cur = brightness_get()
        return {
            "success": True,
            "action": "brightness_get",
            "value": cur,
            "message": f"Screen brightness is at {cur}%." if cur is not None else "Could not determine current brightness.",
        }

    if action in ("wifi_status", "get_wifi", "check_wifi"):
        st = wifi_status()
        return {
            "success": True,
            "action": "wifi_status",
            "value": st,
            "message": st.get("message", "Wi-Fi status retrieved."),
        }

    if action in ("battery_status", "power_status", "get_battery"):
        st = battery_status()
        return {
            "success": True,
            "action": "battery_status",
            "value": st,
            "message": st.get("message", "Battery status retrieved."),
        }

    if action in ("bluetooth_status", "get_bluetooth", "check_bluetooth"):
        st = bluetooth_status()
        return {
            "success": True,
            "action": "bluetooth_status",
            "value": st,
            "message": st.get("message", "Bluetooth status retrieved."),
        }

    if action in ("type_text", "write_on_screen", "type", "write"):
        text = str(value or params.get("text", "")).strip()
        if not text:
            return {
                "success": False,
                "action": "type_text",
                "value": None,
                "message": "No text provided to type.",
            }
        enter_after = str(params.get("press_enter", "false")).lower() in ("true", "1", "yes")
        type_text(text, press_enter_after=enter_after)
        return {
            "success": True,
            "action": "type_text",
            "value": text,
            "message": f"Typed: {text[:80]}",
        }

    if action == "press_key":
        key = str(value or params.get("key", "")).strip()
        if not key:
            return {
                "success": False,
                "action": "press_key",
                "value": None,
                "message": "No key specified.",
            }
        press_key(key)
        return {
            "success": True,
            "action": "press_key",
            "value": key,
            "message": f"Pressed: {key}",
        }

    if action in ("reload_n", "refresh_n", "reload_page_n"):
        try:
            n = int(value or 1)
            reload_page_n(n)
            return {
                "success": True,
                "action": "reload_page_n",
                "value": n,
                "message": f"Reloaded {n} time(s).",
            }
        except Exception as e:
            return {
                "success": False,
                "action": "reload_page_n",
                "value": None,
                "message": f"Reload failed: {e}",
            }

    if action == "scroll_up":
        amt = int(value or 500)
        scroll_up(amt)
        return {
            "success": True,
            "action": "scroll_up",
            "value": amt,
            "message": "Scrolled up.",
        }

    if action == "scroll_down":
        amt = int(value or 500)
        scroll_down(amt)
        return {
            "success": True,
            "action": "scroll_down",
            "value": amt,
            "message": "Scrolled down.",
        }

    func = ACTION_MAP.get(action)
    if not func:
        return {
            "success": False,
            "action": action,
            "value": None,
            "message": _suggest(raw_action or description),
        }

    # ── Capture "before" so the change can be taken back ─────────────────────
    # Read-then-write is the whole mechanism for settings: there is no clever
    # inverse to compute, just a value to remember. Where the platform will not
    # tell us the current value, nothing is registered — an undo that restores
    # a guess is worse than no undo at all.
    _before = None
    if action in ("volume_up", "volume_down", "mute", "unmute", "toggle_mute"):
        _before = ("volume", volume_get())
    elif action in ("brightness_up", "brightness_down"):
        _before = ("brightness", brightness_get())

    try:
        res_val = func()
    except Exception as e:
        print(f"[Settings] Action failed ({action}): {e}")
        return {
            "success": False,
            "action": action,
            "value": None,
            "message": f"Action failed ({action}): {e}",
        }

    if _before:
        kind, old = _before
        if old is not None:
            if kind == "volume":
                push_undo(f"volume ({action})",
                          lambda b=old: (volume_set(b), f"Volume back to {b}%.")[1])
            elif kind == "brightness":
                push_undo(f"brightness ({action})",
                          lambda b=old: (brightness_set(b), f"Brightness back to {b}%.")[1])
    elif action == "dark_mode":
        # A pure toggle: calling it again is the undo.
        push_undo("dark mode toggled",
                  lambda: (dark_mode(), "Theme switched back.")[1])

    val = res_val
    if val is None:
        if action in ("volume_up", "volume_down", "mute", "unmute", "toggle_mute"):
            val = volume_get()
        elif action in ("brightness_up", "brightness_down"):
            val = brightness_get()

    return {
        "success": True,
        "action": action,
        "value": val,
        "message": f"Done: {action}.",
    }


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_settings",
    "description": "Controls and inspects the computer: volume, brightness, battery/power status, Wi-Fi status, Bluetooth status, window management, keyboard shortcuts, typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. Use for ANY single computer control or settings query. restart, shutdown and toggle_wifi put a confirmation on the user's screen and do NOT happen until they press it — never claim they are done. Volume, brightness and dark mode can be reversed with the `undo` tool.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "The exact action. Prefer this over `description` — pick one of: "
                    "volume_up | volume_down | volume_set | volume_get | mute | "
                    "brightness_up | brightness_down | brightness_get | sleep_display | "
                    "battery_status | wifi_status | bluetooth_status | "
                    "pause_video | close_app | close_window | full_screen | "
                    "minimize | maximize | snap_left | snap_right | "
                    "switch_window | show_desktop | task_manager | focus_search | "
                    "refresh_page | close_tab | new_tab | next_tab | prev_tab | "
                    "go_back | go_forward | zoom_in | zoom_out | zoom_reset | "
                    "find_on_page | scroll_up | scroll_down | scroll_top | "
                    "scroll_bottom | page_up | page_down | copy | paste | cut | "
                    "undo | redo | select_all | save | enter | escape | press_key | "
                    "type_text | screenshot | lock_screen | open_settings | "
                    "file_explorer | open_run | dark_mode | toggle_wifi | "
                    "restart | shutdown"
                )
            },
            "description": {
                "type": "STRING",
                "description": (
                    "Fallback only, when no action name above fits. "
                    "Resolved locally — no extra model call."
                )
            },
            "value": {
                "type": "STRING",
                "description": "Optional value: volume level 0-100, text to type, key name, etc."
            }
        },
        "required": []
    },
    "handler": computer_settings,
}

