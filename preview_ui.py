"""
preview_ui.py — Standalone visual runner for the redesigned AGENT UI.
Allows interactive inspection of all panels, quick drawer, overlays, and color wheel retheming.
"""
import sys
from PyQt6.QtWidgets import QApplication
import ui


def main():
    app = QApplication(sys.argv)
    win = ui.MainWindow(face_path="")

    # Add sample log entries for immediate visual context
    win._log.append_log("SYS: MARK-LIV Quantum Core initialized.")
    win._log.append_log("AGENT: Audio pipeline and voice authentication ready.")
    win._log.append_log("SYS: Visual redesign loaded (Dark Cyberpunk / Minimalist).")

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
