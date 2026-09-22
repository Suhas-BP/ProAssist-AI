"""
floating_island.py — Floating Island companion widget for AGENT / ProAssist AI.

Flow:
  STATE 1 (Collapsed pill, ~230x46px):
    Translucent, frameless, always-on-top pill.
    Status dot, Name + Status subtitle, live animated waveform bars, chevron-down button.
  STATE 2 (Mid-expand card, ~300x316px):
    Header with status dot, title, 'agent 001' pill badge, chevron-up button.
    Center status circle (placeholder arc reflecting existing state) + status line.
    3 quick-stat tiles: CPU / Mic / Security.
    "Open full dashboard" button.
  STATE 3:
    "Open full dashboard" raises MainWindow and collapses island back to STATE 1.

Features:
  - Frameless & translucent background with rounded corners.
  - Smooth QPropertyAnimation geometry transitions with position persistence.
  - Draggable anywhere on the desktop.
  - Wired directly to MainWindow signals — zero new polling.
  - Uses icons from icons.py.
"""

import sys
import math
from pathlib import Path
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QTimer, QPropertyAnimation,
    QEasingCurve, pyqtSignal
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QStackedLayout, QFrame, QApplication
)

try:
    from icons import icon
except ImportError:
    # Fallback if run standalone from another directory
    from .icons import icon  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# Theme & Color Tokens
# ─────────────────────────────────────────────────────────────────────────────
C_BG_PILL      = "#141516"
C_BG_CARD      = "#141516"
C_BORDER       = "#262a28"
C_PRI          = "#2ee672"
C_PRI_DIM      = "#235a3f"
C_WHITE        = "#f2f2f2"
C_TEXT_DIM     = "#8a8f8d"
C_TILE_BG      = "#1c1e1d"
C_TILE_BORDER  = "#262a28"
C_DANGER       = "#ff4444"



def _island_font(size: float = 9, bold: bool = False) -> QFont:
    f = QFont("Segoe UI", int(size))
    f.setStyleHint(QFont.StyleHint.SansSerif)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


# ─────────────────────────────────────────────────────────────────────────────
# 1. Live Waveform Bars Widget
# ─────────────────────────────────────────────────────────────────────────────
class WaveformBars(QWidget):
    """
    Mini live waveform visualizer in accent green (#2ee672).
    Smooth micro-animation reflecting resting, listening, or speaking states.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 20)
        self._bars = [0.35, 0.7, 1.0, 0.65, 0.4]
        self._phase = 0.0
        self._active = False  # True when speaking or listening

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(60)

    def set_active(self, active: bool):
        self._active = active

    def _step(self):
        self._phase += 0.25 if self._active else 0.1
        count = len(self._bars)
        for i in range(count):
            base = 0.5 + 0.45 * math.sin(self._phase + i * 1.3)
            if not self._active:
                # Gentle resting pulse
                self._bars[i] = 0.25 + 0.3 * math.sin(self._phase * 0.8 + i * 0.9)
            else:
                self._bars[i] = max(0.15, min(1.0, base))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = 3.0
        spacing = 3.0
        total_w = len(self._bars) * bar_w + (len(self._bars) - 1) * spacing
        start_x = (w - total_w) / 2.0

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(C_PRI)))

        for i, val in enumerate(self._bars):
            bh = max(4.0, h * val)
            bx = start_x + i * (bar_w + spacing)
            by = (h - bh) / 2.0
            p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 1.5, 1.5)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Status Circle Widget (Placeholder Arc)
# ─────────────────────────────────────────────────────────────────────────────
class StatusCircle(QWidget):
    """
    Circular status indicator placeholder reflecting the current agent state.
    Paints an emerald ring and a glowing curved arc matching the design.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(68, 68)
        self._state = "SLEEPING"
        self._pulse = 0.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(50)

    def set_state(self, state: str):
        self._state = state.upper()
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 0.06) % (2 * math.pi)
        if self._state in ("SPEAKING", "LISTENING", "THINKING"):
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        center = QPointF(w / 2.0, h / 2.0)
        radius = min(w, h) / 2.0 - 4.0

        # Background circular disc
        p.setBrush(QBrush(QColor(16, 22, 19)))
        p.setPen(QPen(QColor(C_PRI_DIM), 1.5))
        p.drawEllipse(center, radius, radius)

        # State styling
        if self._state == "MUTED":
            arc_color = C_DANGER
        elif self._state in ("LISTENING", "SPEAKING"):
            arc_color = C_PRI
        else:
            arc_color = C_PRI

        # Subtle dynamic arc or sleeping eye curve matching reference
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(arc_color), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        if self._state == "SLEEPING":
            # Gentle sleeping arc curve
            arc_rect = QRectF(center.x() - 14, center.y() - 10, 28, 20)
            p.drawArc(arc_rect, 30 * 16, 120 * 16)
        elif self._state in ("LISTENING", "SPEAKING"):
            # Active spinning / pulsing arc
            span = int(180 + 60 * math.sin(self._pulse))
            start_ang = int(math.degrees(self._pulse * 2)) % 360
            arc_rect = QRectF(center.x() - radius + 6, center.y() - radius + 6, (radius - 6) * 2, (radius - 6) * 2)
            p.drawArc(arc_rect, start_ang * 16, span * 16)
        else:
            # Thinking / idle arc
            arc_rect = QRectF(center.x() - 14, center.y() - 10, 28, 20)
            p.drawArc(arc_rect, 20 * 16, 140 * 16)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Floating Island Main Widget
# ─────────────────────────────────────────────────────────────────────────────
class FloatingIsland(QWidget):
    """
    Floating Island widget companion.
    Manages State 1 (collapsed pill) and State 2 (mid-expand card),
    and on State 3 raises MainWindow and collapses back.
    """

    COLLAPSED_W = 260
    COLLAPSED_H = 46

    EXPANDED_W = 300
    EXPANDED_H = 316

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._is_expanded = False
        self._drag_pos = None

        # Frameless, translucent, always-on-top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._assistant_name = "ProAssist AI"
        if main_window and hasattr(main_window, "_assistant_name"):
            self._assistant_name = (main_window._assistant_name.strip() or "ProAssist AI")

        # Initial size and screen positioning
        self.resize(self.COLLAPSED_W, self.COLLAPSED_H)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - self.COLLAPSED_W) // 2,
            max(24, screen.top() + 32)
        )

        self._build_ui()
        self._wire_signals()

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Root layout holding the stacked pill and card
        self._root_lay = QVBoxLayout(self)
        self._root_lay.setContentsMargins(0, 0, 0, 0)
        self._root_lay.setSpacing(0)

        # ── STATE 1: Collapsed Pill Container ──
        self._pill_widget = QFrame(self)
        self._pill_widget.setObjectName("IslandPill")
        self._pill_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pill_widget.setStyleSheet(f"""
            #IslandPill {{
                background-color: #141516;
                border: 1px solid #262a28;
                border-radius: {self.COLLAPSED_H // 2}px;
            }}
        """)
        pill_lay = QHBoxLayout(self._pill_widget)
        pill_lay.setContentsMargins(14, 0, 10, 0)
        pill_lay.setSpacing(8)

        # Status Dot
        self._pill_dot = QLabel("●")
        self._pill_dot.setFont(_island_font(9, bold=True))
        self._pill_dot.setStyleSheet("color: #2ee672; background: transparent;")
        pill_lay.addWidget(self._pill_dot)

        # Name + Subtitle stack
        name_col = QVBoxLayout()
        name_col.setContentsMargins(0, 5, 0, 5)
        name_col.setSpacing(0)

        self._pill_title = QLabel(self._assistant_name)
        self._pill_title.setFont(_island_font(9.5, bold=True))
        self._pill_title.setStyleSheet("color: #f2f2f2; background: transparent;")

        self._pill_sub = QLabel("Sleeping")
        self._pill_sub.setFont(_island_font(8))
        self._pill_sub.setStyleSheet("color: #8a8f8d; background: transparent;")

        name_col.addWidget(self._pill_title)
        name_col.addWidget(self._pill_sub)
        pill_lay.addLayout(name_col)

        pill_lay.addStretch(1)

        # Waveform visualizer
        self._waveform = WaveformBars()
        pill_lay.addWidget(self._waveform)

        # Chevron down button
        self._chevron_down_btn = QPushButton()
        self._chevron_down_btn.setFixedSize(28, 28)
        self._chevron_down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron_down_btn.setIcon(icon("chevron-down"))
        self._chevron_down_btn.setStyleSheet("""
            QPushButton {
                background: #1c1e1d;
                border: 1px solid #2a2c2b;
                border-radius: 14px;
                padding: 0;
            }
            QPushButton:hover {
                background: #242725;
                border-color: #4fe28c;
            }
        """)
        self._chevron_down_btn.clicked.connect(self.expand)
        pill_lay.addWidget(self._chevron_down_btn)

        self._root_lay.addWidget(self._pill_widget)

        # ── STATE 2: Mid-expand Card Container ──
        self._card_widget = QFrame(self)
        self._card_widget.setObjectName("IslandCard")
        self._card_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card_widget.setStyleSheet("""
            #IslandCard {
                background-color: #141516;
                border: 1px solid #262a28;
                border-radius: 18px;
            }
        """)
        card_lay = QVBoxLayout(self._card_widget)
        card_lay.setContentsMargins(14, 12, 14, 14)
        card_lay.setSpacing(12)

        # Header Row
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(7)

        self._card_dot = QLabel("●")
        self._card_dot.setFont(_island_font(9.5, bold=True))
        self._card_dot.setStyleSheet("color: #2ee672; background: transparent;")
        hdr_row.addWidget(self._card_dot)

        self._card_title = QLabel(self._assistant_name)
        self._card_title.setFont(_island_font(10, bold=True))
        self._card_title.setStyleSheet("color: #f2f2f2; background: transparent;")
        hdr_row.addWidget(self._card_title)

        card_pill_badge = QLabel("agent 001")
        card_pill_badge.setFont(_island_font(7.5, bold=True))
        card_pill_badge.setStyleSheet("""
            background: #1c1e1d;
            border: 1px solid #2a2c2b;
            border-radius: 9px;
            color: #8a8f8d;
            padding: 1px 7px;
        """)
        hdr_row.addWidget(card_pill_badge)

        hdr_row.addStretch(1)

        # Chevron up button
        self._chevron_up_btn = QPushButton()
        self._chevron_up_btn.setFixedSize(28, 28)
        self._chevron_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron_up_btn.setIcon(icon("chevron-up"))
        self._chevron_up_btn.setStyleSheet("""
            QPushButton {
                background: #1c1e1d;
                border: 1px solid #2a2c2b;
                border-radius: 14px;
                padding: 0;
            }
            QPushButton:hover {
                background: #242725;
                border-color: #4fe28c;
            }
        """)
        self._chevron_up_btn.clicked.connect(self.collapse)
        hdr_row.addWidget(self._chevron_up_btn)
        card_lay.addLayout(hdr_row)

        # Center Status Area (Circle + Status Line)
        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 4, 0, 4)
        center_col.setSpacing(8)
        center_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._status_circle = StatusCircle()
        center_col.addWidget(self._status_circle, alignment=Qt.AlignmentFlag.AlignCenter)

        self._card_status_line = QLabel('Sleeping — say "Agent" to wake')
        self._card_status_line.setFont(_island_font(8.5))
        self._card_status_line.setStyleSheet("color: #8a8f8d; background: transparent;")
        self._card_status_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_col.addWidget(self._card_status_line)
        card_lay.addLayout(center_col)

        # 3 Quick-Stat Tiles (CPU / Mic / Security)
        tiles_row = QHBoxLayout()
        tiles_row.setContentsMargins(0, 0, 0, 0)
        tiles_row.setSpacing(8)

        def _make_tile(icon_name: str, active: bool, initial_val: str):
            tile = QFrame()
            tile.setStyleSheet(f"""
                background: {C_TILE_BG};
                border: 1px solid {C_TILE_BORDER};
                border-radius: 10px;
            """)
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(4, 8, 4, 8)
            tlay.setSpacing(4)
            tlay.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn_ico = QPushButton()
            btn_ico.setFixedSize(20, 20)
            btn_ico.setIcon(icon(icon_name, active=active))
            btn_ico.setStyleSheet("background: transparent; border: none;")
            tlay.addWidget(btn_ico, alignment=Qt.AlignmentFlag.AlignCenter)

            vlbl = QLabel(initial_val)
            vlbl.setFont(_island_font(8.5, bold=True))
            vlbl.setStyleSheet("color: #f2f2f2; background: transparent;")
            vlbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tlay.addWidget(vlbl)

            return tile, btn_ico, vlbl

        self._tile_cpu, self._tile_cpu_ico, self._tile_cpu_lbl = _make_tile("cpu", False, "22%")
        self._tile_mic, self._tile_mic_ico, self._tile_mic_lbl = _make_tile("microphone", True, "On")
        self._tile_sec, self._tile_sec_ico, self._tile_sec_lbl = _make_tile("shield-check", True, "Cleared")

        tiles_row.addWidget(self._tile_cpu)
        tiles_row.addWidget(self._tile_mic)
        tiles_row.addWidget(self._tile_sec)
        card_lay.addLayout(tiles_row)

        # "Open full dashboard" Button (STATE 3 trigger)
        self._open_dash_btn = QPushButton("  Open full dashboard")
        self._open_dash_btn.setFont(_island_font(9, bold=True))
        self._open_dash_btn.setFixedHeight(36)
        self._open_dash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_dash_btn.setIcon(icon("maximize"))
        self._open_dash_btn.setStyleSheet("""
            QPushButton {
                background: #1c1e1d;
                border: 1px solid #2a2c2b;
                border-radius: 10px;
                color: #f2f2f2;
                font-weight: bold;
                padding: 0 12px;
            }
            QPushButton:hover {
                background: #242725;
                border: 1px solid #4fe28c;
                color: #ffffff;
            }
            QPushButton:pressed {
                background: #0e2a20;
            }
        """)
        self._open_dash_btn.clicked.connect(self.open_dashboard)
        card_lay.addWidget(self._open_dash_btn)

        self._root_lay.addWidget(self._card_widget)
        self._card_widget.hide()

    # ── Signal Wiring ────────────────────────────────────────────────────────
    def _wire_signals(self):
        if not self._main_window:
            return

        # Wire state signal
        if hasattr(self._main_window, "_state_sig"):
            self._main_window._state_sig.connect(self.on_state_changed)

        # Wire MetricBar value_changed (CPU)
        if hasattr(self._main_window, "_bar_cpu") and hasattr(self._main_window._bar_cpu, "value_changed"):
            self._main_window._bar_cpu.value_changed.connect(self.on_cpu_updated)
        elif hasattr(self._main_window, "_bar_cpu"):
            # Set initial value
            self._tile_cpu_lbl.setText(self._main_window._bar_cpu._text)

    # ── State Updates ────────────────────────────────────────────────────────
    def on_cpu_updated(self, val: float, text: str):
        self._tile_cpu_lbl.setText(text)

    def on_state_changed(self, state: str):
        st = state.upper()
        self._status_circle.set_state(st)

        # Waveform active in listening/speaking
        self._waveform.set_active(st in ("LISTENING", "SPEAKING"))

        # Format status text
        aname = self._assistant_name.capitalize()
        status_map = {
            "LISTENING": ("Listening", "Listening — speak now", "#2ee672", True),
            "THINKING":  ("Thinking", "Thinking…", "#ffaa00", True),
            "PROCESSING":("Processing", "Processing…", "#ffaa00", True),
            "SPEAKING":  ("Speaking", "Speaking…", "#2ee672", True),
            "MUTED":     ("Muted", "Microphone muted", "#ff4444", False),
            "SLEEPING":  ("Sleeping", f'Sleeping — say "{aname}" to wake', "#4fe28c", True),
        }
        sub, line, dot_col, mic_on = status_map.get(
            st, (st.capitalize(), f'{st.capitalize()} — say "{aname}" to wake', "#2ee672", True)
        )

        self._pill_sub.setText(sub)
        self._card_status_line.setText(line)
        self._pill_dot.setStyleSheet(f"color: {dot_col}; background: transparent;")
        self._card_dot.setStyleSheet(f"color: {dot_col}; background: transparent;")

        # Mic tile
        if not mic_on:
            self._tile_mic_lbl.setText("Muted")
            self._tile_mic_ico.setIcon(icon("microphone", active=False))
        else:
            self._tile_mic_lbl.setText("On")
            self._tile_mic_ico.setIcon(icon("microphone", active=True))

    # ── Transitions & Expansion ──────────────────────────────────────────────
    def expand(self):
        """Transition from STATE 1 (collapsed pill) to STATE 2 (mid-expand card)."""
        if self._is_expanded:
            return
        self._is_expanded = True

        curr_geom = self.geometry()
        target_geom = QRect(curr_geom.x(), curr_geom.y(), self.EXPANDED_W, self.EXPANDED_H)

        # Keep on screen
        screen = QApplication.primaryScreen().availableGeometry()
        if target_geom.right() > screen.right():
            target_geom.moveRight(screen.right() - 8)
        if target_geom.bottom() > screen.bottom():
            target_geom.moveBottom(screen.bottom() - 8)

        self._pill_widget.hide()
        self._card_widget.show()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setStartValue(curr_geom)
        self._anim.setEndValue(target_geom)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def collapse(self):
        """Transition from STATE 2 (mid-expand card) to STATE 1 (collapsed pill)."""
        if not self._is_expanded:
            return
        self._is_expanded = False

        curr_geom = self.geometry()
        target_geom = QRect(curr_geom.x(), curr_geom.y(), self.COLLAPSED_W, self.COLLAPSED_H)

        # Switch containers immediately so layout minimum height drops to pill height
        self._card_widget.hide()
        self._pill_widget.show()

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(180)
        self._anim.setStartValue(curr_geom)
        self._anim.setEndValue(target_geom)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def open_dashboard(self):
        """STATE 3: Raise MainWindow and collapse island back to STATE 1."""
        if self._main_window:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

        self.collapse()

    # ── Window Dragging & Position Persistence ────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        e.accept()
