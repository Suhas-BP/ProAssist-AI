import sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PyQt6.QtWidgets import QApplication
from ui import AgentUI

app = QApplication.instance() or QApplication(sys.argv)
ui = AgentUI("face.png")

# Also show the main window so the user definitely has a visible window on screen
ui._win.show()
ui._win.raise_()
ui._win.activateWindow()

if hasattr(ui._win, "_floating_island") and ui._win._floating_island:
    ui._win._floating_island.show()
    ui._win._floating_island.raise_()
    ui._win._floating_island.activateWindow()

print("MainWindow visible:", ui._win.isVisible(), "geometry:", ui._win.geometry())
if hasattr(ui._win, "_floating_island"):
    print("FloatingIsland visible:", ui._win._floating_island.isVisible(), "geometry:", ui._win._floating_island.geometry())

print("Starting Qt event loop for 10 seconds...")
from PyQt6.QtCore import QTimer
QTimer.singleShot(10000, app.quit)
app.exec()
print("Exited cleanly.")
