"""
icons.py — QIcon loader for the AGENT redesign icon set.

Usage:
    from icons import icon

    settings_btn.setIcon(icon("settings"))            # gray, default
    remote_btn.setIcon(icon("broadcast", active=True)) # green accent

Place this file alongside an `assets/icons/` folder containing the
`green/` and `gray/` subfolders extracted from icons_pyqt6_ready.zip.
"""

from pathlib import Path
from PyQt6.QtGui import QIcon

_ICON_DIR = Path(__file__).parent / "assets" / "icons"

_AVAILABLE = {
    "settings", "cpu", "microphone", "headphones", "brain", "fingerprint",
    "broadcast", "maximize", "hand-click", "layout-grid-add", "upload",
    "send", "hand-stop", "shield-check", "lock", "chevron-down", "chevron-up",
}


def icon(name: str, active: bool = False) -> QIcon:
    """
    Return a QIcon for the given icon name.

    name:   one of the names in _AVAILABLE (matches the design's icon list)
    active: True -> green accent (#4fe28c), False -> neutral gray (#c9cccb)
    """
    if name not in _AVAILABLE:
        raise ValueError(
            f"Unknown icon '{name}'. Available: {sorted(_AVAILABLE)}"
        )
    subfolder = "green" if active else "gray"
    path = _ICON_DIR / subfolder / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"Icon file missing: {path}")
    return QIcon(str(path))


# Map of design usage -> icon name, for reference while wiring buttons:
DESIGN_ICON_MAP = {
    "settings_gear":      "settings",
    "system_monitor_cpu": "cpu",
    "wake_word_toggle":   "microphone",
    "audio_devices":      "headphones",
    "memory_panel":       "brain",
    "voice_auth":         "fingerprint",
    "remote_control":     "broadcast",
    "fullscreen_toggle":  "maximize",
    "push_to_talk":       "hand-click",
    "create_shortcut":    "layout-grid-add",
    "file_drop_zone":     "upload",
    "command_send":       "send",
    "interrupt_button":   "hand-stop",
    "sec_cleared_status": "shield-check",
    "protocol_status":    "lock",
    "island_expand":      "chevron-down",
    "island_collapse":    "chevron-up",
}
