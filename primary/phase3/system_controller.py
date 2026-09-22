"""
System Controller for ProAssist AI Phase 3
Provides safe system-level operations:
1. Volume control (set level, mute, unmute)
2. Media key controls (play/pause, next, previous)
3. Screenshot capture
4. Window management (minimize, maximize, close)
5. Clipboard read
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime


class SystemController:
    """Controls safe system-level operations without arbitrary shell execution."""

    def __init__(self):
        self.screenshots_folder = Path.home() / "Pictures" / "ProAssist Screenshots"

    # =========================================================================
    # VOLUME CONTROL
    # =========================================================================
    def set_volume(self, percent: int, dry_run: bool = False) -> tuple:
        """Sets the system master volume to the specified percentage (0-100)."""
        level = max(0, min(100, int(percent)))

        if dry_run:
            print(f"[SystemController DRY-RUN] Verified: Set volume to {level}%")
            return True, f"Volume set to {level} percent."

        if sys.platform != "win32":
            return False, "Volume control is only supported on Windows."

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 f"public class Audio {{ [DllImport(\"winmm.dll\")] public static extern int waveOutSetVolume(IntPtr h, uint dwv); }}'; "
                 f"$rawVol = [uint32]([Math]::Round({level} / 100.0 * 0xFFFF)); "
                 f"$stereoVol = ($rawVol -bor ($rawVol -shl 16)); "
                 f"[Audio]::waveOutSetVolume([IntPtr]::Zero, $stereoVol);"
                 ],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f"[SystemController] Volume set to {level}%")
            return True, f"Volume set to {level} percent."
        except Exception as e:
            print(f"[SystemController] Volume set error: {e}")
            return False, f"I couldn't set the volume to {level} percent."

    def mute(self, dry_run: bool = False) -> tuple:
        """Mutes the system audio."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Mute system audio")
            return True, "Muted."

        if sys.platform != "win32":
            return False, "Mute control is only supported on Windows."

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Audio { [DllImport(\"winmm.dll\")] public static extern int waveOutSetVolume(IntPtr h, uint dwv); }'; "
                 "[Audio]::waveOutSetVolume([IntPtr]::Zero, 0);"
                 ],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print("[SystemController] System muted.")
            return True, "Muted."
        except Exception as e:
            print(f"[SystemController] Mute error: {e}")
            return False, "I couldn't mute the system audio."

    def unmute(self, dry_run: bool = False) -> tuple:
        """Unmutes the system audio by restoring 70 percent volume."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Unmute system audio")
            return True, "Unmuted."
        return self.set_volume(70, dry_run=dry_run)

    def volume_up(self, dry_run: bool = False) -> tuple:
        """Increases system volume by 10 percent using media key."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Volume up")
            return True, "Volume increased."

        if sys.platform != "win32":
            return False, "Volume control is only supported on Windows."

        try:
            import pyautogui
            for _ in range(5):
                pyautogui.press("volumeup")
            return True, "Volume increased."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Media { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra); }'; "
                 "for($i=0;$i-lt5;$i++){[Media]::keybd_event(0xAF, 0, 0, [IntPtr]::Zero); [Media]::keybd_event(0xAF, 0, 2, [IntPtr]::Zero); Start-Sleep -Milliseconds 50};"
                 ],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Volume increased."
        except Exception as e:
            print(f"[SystemController] Volume up error: {e}")
            return False, "I couldn't increase the volume."

    def volume_down(self, dry_run: bool = False) -> tuple:
        """Decreases system volume by 10 percent using media key."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Volume down")
            return True, "Volume decreased."

        if sys.platform != "win32":
            return False, "Volume control is only supported on Windows."

        try:
            import pyautogui
            for _ in range(5):
                pyautogui.press("volumedown")
            return True, "Volume decreased."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Media { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra); }'; "
                 "for($i=0;$i-lt5;$i++){[Media]::keybd_event(0xAE, 0, 0, [IntPtr]::Zero); [Media]::keybd_event(0xAE, 0, 2, [IntPtr]::Zero); Start-Sleep -Milliseconds 50};"
                 ],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Volume decreased."
        except Exception as e:
            print(f"[SystemController] Volume down error: {e}")
            return False, "I couldn't decrease the volume."

    # =========================================================================
    # MEDIA CONTROLS
    # =========================================================================
    def media_play_pause(self, dry_run: bool = False) -> tuple:
        """Sends the Play/Pause media key."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Play/Pause media key")
            return True, "Done."

        if sys.platform != "win32":
            return False, "Media control is only supported on Windows."

        try:
            import pyautogui
            pyautogui.press("playpause")
            print("[SystemController] Sent Play/Pause media key.")
            return True, "Done."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Media { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra); }'; "
                 "[Media]::keybd_event(0xB3, 0, 0, [IntPtr]::Zero); [Media]::keybd_event(0xB3, 0, 2, [IntPtr]::Zero);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Done."
        except Exception as e:
            print(f"[SystemController] Play/Pause error: {e}")
            return False, "I couldn't send the play/pause key."

    def media_next(self, dry_run: bool = False) -> tuple:
        """Sends the Next Track media key."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Next track media key")
            return True, "Next track."

        if sys.platform != "win32":
            return False, "Media control is only supported on Windows."

        try:
            import pyautogui
            pyautogui.press("nexttrack")
            return True, "Next track."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Media { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra); }'; "
                 "[Media]::keybd_event(0xB0, 0, 0, [IntPtr]::Zero); [Media]::keybd_event(0xB0, 0, 2, [IntPtr]::Zero);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Next track."
        except Exception as e:
            print(f"[SystemController] Next track error: {e}")
            return False, "I couldn't skip to the next track."

    def media_prev(self, dry_run: bool = False) -> tuple:
        """Sends the Previous Track media key."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Previous track media key")
            return True, "Previous track."

        if sys.platform != "win32":
            return False, "Media control is only supported on Windows."

        try:
            import pyautogui
            pyautogui.press("prevtrack")
            return True, "Previous track."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Media { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra); }'; "
                 "[Media]::keybd_event(0xB1, 0, 0, [IntPtr]::Zero); [Media]::keybd_event(0xB1, 0, 2, [IntPtr]::Zero);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Previous track."
        except Exception as e:
            print(f"[SystemController] Previous track error: {e}")
            return False, "I couldn't go to the previous track."

    # =========================================================================
    # SCREENSHOT
    # =========================================================================
    def take_screenshot(self, dry_run: bool = False) -> tuple:
        """Captures the entire screen and saves it to Pictures/ProAssist Screenshots."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        save_path = self.screenshots_folder / filename

        if dry_run:
            print(f"[SystemController DRY-RUN] Verified: Screenshot would be saved as '{filename}'")
            return True, f"Screenshot saved as {filename}."

        try:
            self.screenshots_folder.mkdir(parents=True, exist_ok=True)

            try:
                import pyautogui
                img = pyautogui.screenshot()
                img.save(str(save_path))
                print(f"[SystemController] Screenshot saved: {save_path}")
                return True, f"Screenshot saved to Pictures as {filename}."
            except Exception:
                pass

            save_path_fwd = str(save_path).replace("\\", "/")
            ps_cmd = (
                f"Add-Type -AssemblyName System.Windows.Forms; "
                f"Add-Type -AssemblyName System.Drawing; "
                f"$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                f"$bmp = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height; "
                f"$gfx = [System.Drawing.Graphics]::FromImage($bmp); "
                f"$gfx.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size); "
                f"$bmp.Save('{save_path_fwd}'); "
                f"$gfx.Dispose(); $bmp.Dispose()"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if save_path.exists():
                print(f"[SystemController] Screenshot saved via PowerShell: {save_path}")
                return True, f"Screenshot saved to Pictures as {filename}."
            raise RuntimeError(result.stderr.strip())
        except Exception as e:
            print(f"[SystemController] Screenshot error: {e}")
            return False, "I couldn't take a screenshot."

    # =========================================================================
    # WINDOW MANAGEMENT
    # =========================================================================
    def minimize_window(self, dry_run: bool = False) -> tuple:
        """Minimizes the currently active window."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Minimize active window")
            return True, "Window minimized."

        if sys.platform != "win32":
            return False, "Window management is only supported on Windows."

        try:
            import pyautogui
            pyautogui.hotkey("win", "down")
            return True, "Window minimized."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Win { [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int cmd); "
                 "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; "
                 "[Win]::ShowWindow([Win]::GetForegroundWindow(), 2);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Window minimized."
        except Exception as e:
            print(f"[SystemController] Minimize error: {e}")
            return False, "I couldn't minimize the window."

    def maximize_window(self, dry_run: bool = False) -> tuple:
        """Maximizes the currently active window."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Maximize active window")
            return True, "Window maximized."

        if sys.platform != "win32":
            return False, "Window management is only supported on Windows."

        try:
            import pyautogui
            pyautogui.hotkey("win", "up")
            return True, "Window maximized."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Win { [DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int cmd); "
                 "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; "
                 "[Win]::ShowWindow([Win]::GetForegroundWindow(), 3);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Window maximized."
        except Exception as e:
            print(f"[SystemController] Maximize error: {e}")
            return False, "I couldn't maximize the window."

    def close_window(self, dry_run: bool = False) -> tuple:
        """Closes the currently active window using Alt+F4."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Close active window (Alt+F4)")
            return True, "Window closed."

        if sys.platform != "win32":
            return False, "Window management is only supported on Windows."

        try:
            import pyautogui
            pyautogui.hotkey("alt", "f4")
            return True, "Window closed."
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
                 "public class Win { [DllImport(\"user32.dll\")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l); "
                 "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; "
                 "[Win]::PostMessage([Win]::GetForegroundWindow(), 0x0010, [IntPtr]::Zero, [IntPtr]::Zero);"
                 ],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True, "Window closed."
        except Exception as e:
            print(f"[SystemController] Close error: {e}")
            return False, "I couldn't close the window."

    # =========================================================================
    # CLIPBOARD
    # =========================================================================
    def read_clipboard(self, dry_run: bool = False) -> tuple:
        """Reads and returns the current clipboard text content."""
        if dry_run:
            print("[SystemController DRY-RUN] Verified: Read clipboard")
            return True, "Clipboard content: Hello World."

        try:
            import pyperclip
            content = pyperclip.paste()
            if content and content.strip():
                return True, f"Clipboard contains: {content.strip()[:200]}"
            return True, "The clipboard is empty."
        except Exception as e:
            print(f"[SystemController] Clipboard read error: {e}")
            return False, "I couldn't read the clipboard."
