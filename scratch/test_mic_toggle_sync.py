"""
scratch/test_mic_toggle_sync.py — Verification of microphone toggle sync between
MainWindow and FloatingIsland.
"""

import sys
import os
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from ui import MainWindow
from floating_island import FloatingIsland, C_DANGER, C_WHITE, C_TILE_BG, C_TILE_BORDER

print("=" * 80)
print("TEST: MICROPHONE TOGGLE & FLOATING ISLAND SYNC")
print("=" * 80)

face_path = root_dir / "config" / "face.obj"
win = MainWindow(face_path)
island = win._floating_island
assert island is not None, "FloatingIsland must be attached to MainWindow"

# Expand island card
island.expand()
island._anim.setCurrentTime(island._anim.duration())
island.setGeometry(island._anim.endValue())
app.processEvents()

# Initial state check
print(f"[INITIAL STATE] win._muted={win._muted}")
print(f"  Island mic text: '{island._tile_mic_lbl.text()}'")
print(f"  Island mic tile sheet: {island._tile_mic.styleSheet().strip()}")
assert island._tile_mic_lbl.text() == "On", "Initial mic label should be 'On'"

# 1. Toggle mute from MainWindow
print("\n[STEP 1] Toggling mute from MainWindow...")
win._toggle_mute()
app.processEvents()

print(f"  win._muted: {win._muted}")
print(f"  win._mute_btn text: '{win._mute_btn.text().strip()}'")
print(f"  island._tile_mic_lbl text: '{island._tile_mic_lbl.text()}'")
print(f"  island._tile_mic_lbl sheet: {island._tile_mic_lbl.styleSheet().strip()}")
print(f"  island._tile_mic tile sheet: {island._tile_mic.styleSheet().strip()}")

assert win._muted is True, "MainWindow must be muted"
assert island._tile_mic_lbl.text() == "Off", f"Expected 'Off', got '{island._tile_mic_lbl.text()}'"
assert C_DANGER in island._tile_mic_lbl.styleSheet() or "#ff4444" in island._tile_mic_lbl.styleSheet()
assert "#2a1414" in island._tile_mic.styleSheet()
assert "#5a2323" in island._tile_mic.styleSheet()
print("  [OK] Off label and red danger styling verified on floating island.")

# 2. Toggle unmute from MainWindow
print("\n[STEP 2] Toggling unmute from MainWindow...")
win._toggle_mute()
app.processEvents()

print(f"  win._muted: {win._muted}")
print(f"  win._mute_btn text: '{win._mute_btn.text().strip()}'")
print(f"  island._tile_mic_lbl text: '{island._tile_mic_lbl.text()}'")
print(f"  island._tile_mic tile sheet: {island._tile_mic.styleSheet().strip()}")

assert win._muted is False, "MainWindow must be unmuted"
assert island._tile_mic_lbl.text() == "On", f"Expected 'On', got '{island._tile_mic_lbl.text()}'"
assert C_WHITE in island._tile_mic_lbl.styleSheet() or "#f2f2f2" in island._tile_mic_lbl.styleSheet()
assert C_TILE_BG in island._tile_mic.styleSheet() or "#1c1e1d" in island._tile_mic.styleSheet()
print("  [OK] On label and normal emerald/white styling verified on floating island.")

# 3. Toggle mute from Floating Island's mic action
print("\n[STEP 3] Toggling mute from FloatingIsland._toggle_mic()...")
island._toggle_mic()
app.processEvents()

print(f"  win._muted: {win._muted}")
print(f"  win._mute_btn text: '{win._mute_btn.text().strip()}'")
print(f"  island._tile_mic_lbl text: '{island._tile_mic_lbl.text()}'")

assert win._muted is True, "MainWindow must be muted"
assert win._mute_btn.text().strip() == "Mic muted"
assert island._tile_mic_lbl.text() == "Off", f"Expected 'Off', got '{island._tile_mic_lbl.text()}'"
print("  [OK] Bi-directional sync verified from FloatingIsland to MainWindow.")

# 4. Toggle unmute from Floating Island's mic action
print("\n[STEP 4] Toggling unmute from FloatingIsland._toggle_mic()...")
island._toggle_mic()
app.processEvents()

print(f"  win._muted: {win._muted}")
print(f"  win._mute_btn text: '{win._mute_btn.text().strip()}'")
print(f"  island._tile_mic_lbl text: '{island._tile_mic_lbl.text()}'")

assert win._muted is False, "MainWindow must be unmuted"
assert win._mute_btn.text().strip() == "Mic active"
assert island._tile_mic_lbl.text() == "On", f"Expected 'On', got '{island._tile_mic_lbl.text()}'"
print("  [OK] Bi-directional unmute sync verified.")

# 5. Test clicking directly on tile frame and label via mousePressEvent
print("\n[STEP 5] Testing click directly on tile frame...")
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import QPointF, Qt
press_ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
island._tile_mic.mousePressEvent(press_ev)
app.processEvents()
assert win._muted is True, "Clicking tile frame must toggle mute"
assert island._tile_mic_lbl.text() == "Off", "Label must be 'Off'"
print("  [OK] Direct tile frame click toggled mic to muted ('Off').")

print("\n[STEP 6] Testing click directly on tile label...")
island._tile_mic_lbl.mousePressEvent(press_ev)
app.processEvents()
assert win._muted is False, "Clicking tile label must toggle unmute"
assert island._tile_mic_lbl.text() == "On", "Label must be 'On'"
print("  [OK] Direct tile label click toggled mic to unmuted ('On').")

# Save visual captures of muted and unmuted island
island.set_mic_muted(True)
app.processEvents()
island.grab().save(str(root_dir / "scratch" / "island_mic_off.png"))
print(f"\nSaved mic off visual render to: scratch/island_mic_off.png")

island.set_mic_muted(False)
app.processEvents()
island.grab().save(str(root_dir / "scratch" / "island_mic_on.png"))
print(f"Saved mic on visual render to: scratch/island_mic_on.png")

print("\n" + "=" * 80)
print("ALL MIC TOGGLE & SYNC TESTS PASSED!")
print("=" * 80)
