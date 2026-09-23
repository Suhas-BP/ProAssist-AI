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
import html
import webbrowser
from pathlib import Path
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPoint, QPointF, QTimer, QPropertyAnimation,
    QEasingCurve, pyqtSignal, QUrl, QSize
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QFontMetrics,
    QDesktopServices
)
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QStackedLayout, QFrame, QApplication, QScrollArea, QStackedWidget
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


def _island_font(size: float = 9, bold: bool = False, weight: QFont.Weight = None) -> QFont:
    f = QFont("Segoe UI", int(size))
    f.setStyleHint(QFont.StyleHint.SansSerif)
    if weight is not None:
        f.setWeight(weight)
    elif bold:
        f.setWeight(QFont.Weight.Bold)
    return f


def _open_source_link(url: str):
    """Safely open source link in default browser."""
    if not url:
        return
    qurl = QUrl(url if "://" in url else f"https://{url}")
    if not QDesktopServices.openUrl(qurl):
        webbrowser.open(str(qurl.toString()))


def _clamp_to_2_lines(text: str, font: QFont, max_width: int) -> str:
    """True 2-line clamping with QFontMetrics elision."""
    fm = QFontMetrics(font)
    words = text.split()
    if not words:
        return ""

    line1 = ""
    idx = 0
    # Line 1: fit words up to max_width
    while idx < len(words):
        test_line = (line1 + " " + words[idx]).strip()
        if fm.horizontalAdvance(test_line) <= max_width:
            line1 = test_line
            idx += 1
        else:
            break

    # If all words fit on line 1, return single line
    if idx >= len(words):
        return line1

    # Line 2: remainder of words elided with ellipsis
    rem = " ".join(words[idx:])
    line2 = fm.elidedText(rem, Qt.TextElideMode.ElideRight, max_width)
    return f"{line1}\n{line2}"


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Stacked Widget (respects current page size only)
# ─────────────────────────────────────────────────────────────────────────────
class DynamicStackedWidget(QStackedWidget):
    """QStackedWidget that reports sizeHint and minimumSizeHint of the currently active page only."""

    def minimumSizeHint(self):
        cw = self.currentWidget()
        return cw.minimumSizeHint() if cw else super().minimumSizeHint()

    def sizeHint(self):
        cw = self.currentWidget()
        return cw.sizeHint() if cw else super().sizeHint()


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline Widget for Single-Value Card
# ─────────────────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    """
    Mini sparkline graph in accent green (#2ee672) for single-value info card.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self._points = []

    def set_points(self, points: list[float] | None):
        self._points = points or []
        self.update()

    def paintEvent(self, _):
        if not self._points or len(self._points) < 2:
            return
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        h = float(self.height())
        min_v = min(self._points)
        max_v = max(self._points)
        rng = max(max_v - min_v, 1e-4)

        pen = QPen(QColor(C_PRI), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        path = QPainterPath()
        n = len(self._points)
        for i, pt in enumerate(self._points):
            x = 4.0 + (w - 8.0) * (i / (n - 1))
            y = (h - 6.0) - ((pt - min_v) / rng) * (h - 12.0)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.drawPath(path)
        p.end()


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

    COLLAPSED_W = 280
    COLLAPSED_H = 46

    EXPANDED_W = 320
    EXPANDED_H = 340

    EXPANDED_LIST_W = 460
    EXPANDED_LIST_H = 450

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._is_expanded = False
        self._drag_pos = None

        self._target_expanded_w = self.EXPANDED_W
        self._target_expanded_h = self.EXPANDED_H
        self._info_payload = None

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
        pill_lay.setContentsMargins(12, 0, 10, 0)
        pill_lay.setSpacing(7)

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

        # Interactive Microphone Toggle Button
        self._pill_mic_btn = QPushButton()
        self._pill_mic_btn.setFixedSize(28, 28)
        self._pill_mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill_mic_btn.setIcon(icon("microphone", active=True))
        self._pill_mic_btn.setToolTip("Click to Mute / Unmute Microphone")
        self._pill_mic_btn.setStyleSheet("""
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
        self._pill_mic_btn.clicked.connect(self._toggle_mic)
        pill_lay.addWidget(self._pill_mic_btn)

        # Chevron down button (Expand card)
        self._chevron_down_btn = QPushButton()
        self._chevron_down_btn.setFixedSize(28, 28)
        self._chevron_down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron_down_btn.setIcon(icon("chevron-down"))
        self._chevron_down_btn.setToolTip("Expand Quick Dashboard")
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
        self._chevron_up_btn.setToolTip("Collapse to Mini Pill")
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

        # Center Stack (Status circle default OR info-card content)
        self._content_stack = DynamicStackedWidget(self._card_widget)

        # Page 0: Default Center Status Area (Circle + Status Line)
        self._status_container = QWidget()
        center_col = QVBoxLayout(self._status_container)
        center_col.setContentsMargins(0, 4, 0, 4)
        center_col.setSpacing(8)
        center_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._status_circle = StatusCircle()
        center_col.addWidget(self._status_circle, alignment=Qt.AlignmentFlag.AlignCenter)

        self._card_status_line = QLabel('Sleeping — say "Agent" to wake')
        self._card_status_line.setFont(_island_font(8.5))
        self._card_status_line.setStyleSheet("color: #8a8f8d; background: transparent;")
        self._card_status_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_status_line.setWordWrap(True)
        center_col.addWidget(self._card_status_line)
        self._content_stack.addWidget(self._status_container)

        # Page 1: Single-Value Info Container
        self._info_value_container = QWidget()
        v_lay = QVBoxLayout(self._info_value_container)
        v_lay.setContentsMargins(2, 2, 2, 2)
        v_lay.setSpacing(6)

        v_sub = QLabel("Showing what you asked for")
        v_sub.setFont(_island_font(8))
        v_sub.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; border: none;")
        v_lay.addWidget(v_sub)

        v_hdr = QHBoxLayout()
        v_hdr.setContentsMargins(0, 0, 0, 0)
        v_hdr.setSpacing(6)
        self._val_icon_btn = QPushButton()
        self._val_icon_btn.setFixedSize(18, 18)
        self._val_icon_btn.setIcon(icon("broadcast", active=True))
        self._val_icon_btn.setStyleSheet("background: transparent; border: none;")
        v_hdr.addWidget(self._val_icon_btn)

        self._val_source_lbl = QLabel("Market • Updated")
        self._val_source_lbl.setFont(_island_font(8))
        self._val_source_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; border: none;")
        v_hdr.addWidget(self._val_source_lbl)

        self._val_name_lbl = QLabel("")
        self._val_name_lbl.setFont(_island_font(8.5, bold=True))
        self._val_name_lbl.setStyleSheet(f"color: {C_WHITE}; background: transparent; border: none;")
        v_hdr.addWidget(self._val_name_lbl)
        v_hdr.addStretch(1)
        v_lay.addLayout(v_hdr)

        val_row = QHBoxLayout()
        val_row.setContentsMargins(0, 0, 0, 0)
        val_row.setSpacing(8)
        self._val_value_lbl = QLabel("—")
        self._val_value_lbl.setFont(_island_font(18, bold=True))
        self._val_value_lbl.setStyleSheet(f"color: {C_WHITE}; background: transparent; border: none;")
        val_row.addWidget(self._val_value_lbl)

        self._val_delta_lbl = QLabel("+0.0%")
        self._val_delta_lbl.setFont(_island_font(8, bold=True))
        self._val_delta_lbl.setStyleSheet(f"""
            color: {C_PRI};
            background: #1c1e1d;
            border: 1px solid {C_TILE_BORDER};
            border-radius: 8px;
            padding: 2px 6px;
        """)
        val_row.addWidget(self._val_delta_lbl)
        val_row.addStretch(1)
        v_lay.addLayout(val_row)

        self._val_sparkline = Sparkline()
        v_lay.addWidget(self._val_sparkline)
        self._content_stack.addWidget(self._info_value_container)

        # Page 2: Multi-Item List Info Container
        self._info_list_container = QWidget()
        l_lay = QVBoxLayout(self._info_list_container)
        l_lay.setContentsMargins(2, 2, 2, 2)
        l_lay.setSpacing(6)

        l_sub = QLabel("Showing what you asked for")
        l_sub.setFont(_island_font(8))
        l_sub.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; border: none;")
        l_lay.addWidget(l_sub)

        l_hdr = QHBoxLayout()
        l_hdr.setContentsMargins(0, 0, 0, 0)
        l_hdr.setSpacing(6)
        self._list_icon_btn = QPushButton()
        self._list_icon_btn.setFixedSize(18, 18)
        self._list_icon_btn.setIcon(icon("layout-grid-add", active=True))
        self._list_icon_btn.setStyleSheet("background: transparent; border: none;")
        l_hdr.addWidget(self._list_icon_btn)

        self._list_source_lbl = QLabel("Search • Just now")
        self._list_source_lbl.setFont(_island_font(8))
        self._list_source_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; border: none;")
        l_hdr.addWidget(self._list_source_lbl)
        l_hdr.addStretch(1)
        l_lay.addLayout(l_hdr)

        # Scroll Area for List Items
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setMinimumHeight(60)
        self._list_scroll.setMaximumHeight(220)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {C_TILE_BORDER};
                min-height: 20px;
                border-radius: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {C_PRI_DIM};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
                border: none;
            }}
        """)

        self._list_items_container = QWidget()
        self._list_items_container.setStyleSheet("background: transparent;")
        self._list_items_lay = QVBoxLayout(self._list_items_container)
        self._list_items_lay.setContentsMargins(0, 0, 6, 0)
        self._list_items_lay.setSpacing(6)
        self._list_scroll.setWidget(self._list_items_container)
        l_lay.addWidget(self._list_scroll)

        self._content_stack.addWidget(self._info_list_container)
        card_lay.addWidget(self._content_stack)

        # 3 Quick-Stat Tiles (CPU / Mic / Security)
        tiles_row = QHBoxLayout()
        tiles_row.setContentsMargins(0, 0, 0, 0)
        tiles_row.setSpacing(8)

        def _make_tile(icon_name: str, active: bool, initial_val: str, on_click=None):
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

            if on_click:
                btn_ico.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_ico.clicked.connect(on_click)
                tile.setCursor(Qt.CursorShape.PointingHandCursor)
                vlbl.setCursor(Qt.CursorShape.PointingHandCursor)

                def _handle_press(e):
                    if e.button() == Qt.MouseButton.LeftButton:
                        on_click()
                        e.accept()

                tile.mousePressEvent = _handle_press
                vlbl.mousePressEvent = _handle_press

            return tile, btn_ico, vlbl

        self._tile_cpu, self._tile_cpu_ico, self._tile_cpu_lbl = _make_tile("cpu", False, "22%")
        self._tile_mic, self._tile_mic_ico, self._tile_mic_lbl = _make_tile("microphone", True, "On", on_click=self._toggle_mic)
        try:
            from core.voice_auth import VoiceAuthenticator
            _enrolled = VoiceAuthenticator().is_enrolled()
        except Exception:
            _enrolled = False
        _sec_text = "Cleared" if _enrolled else "Locked"
        self._tile_sec, self._tile_sec_ico, self._tile_sec_lbl = _make_tile("shield-check", _enrolled, _sec_text)

        tiles_row.addWidget(self._tile_cpu)
        tiles_row.addWidget(self._tile_mic)
        tiles_row.addWidget(self._tile_sec)
        card_lay.addLayout(tiles_row)

        # "Open full dashboard" Button (STATE 3 trigger)
        self._open_dash_btn = QPushButton("  Open Fullscreen / Dashboard")
        self._open_dash_btn.setFont(_island_font(9, bold=True))
        self._open_dash_btn.setFixedHeight(36)
        self._open_dash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_dash_btn.setIcon(icon("maximize"))
        self._open_dash_btn.setIconSize(QSize(16, 16))
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

        # Wire voice auth enrollment signal
        if hasattr(self._main_window, "_voice_auth_sig"):
            self._main_window._voice_auth_sig.connect(self.on_voice_auth_updated)

        # Wire mute signal
        if hasattr(self._main_window, "_mute_sig"):
            self._main_window._mute_sig.connect(self.set_mic_muted)

        # Initial mute sync
        if hasattr(self._main_window, "_muted"):
            self.set_mic_muted(bool(self._main_window._muted))

    # ── Actions & Helpers ────────────────────────────────────────────────────
    def _toggle_mic(self):
        """Toggle microphone mute/unmute state."""
        if self._main_window and hasattr(self._main_window, "_toggle_mute"):
            self._main_window._toggle_mute()
            if hasattr(self._main_window, "_muted"):
                self.set_mic_muted(self._main_window._muted)

    def set_mic_muted(self, muted: bool):
        """Update floating island microphone tile and pill button state with Off/On and color change."""
        self._mic_muted = muted
        if muted:
            self._pill_mic_btn.setIcon(icon("microphone", active=False))
            self._pill_mic_btn.setStyleSheet("""
                QPushButton {
                    background: #2b1818;
                    border: 1px solid #ff4444;
                    border-radius: 14px;
                    padding: 0;
                }
                QPushButton:hover {
                    background: #3b2020;
                }
            """)
            self._tile_mic_lbl.setText("Off")
            self._tile_mic_lbl.setStyleSheet(f"color: {C_DANGER}; background: transparent;")
            self._tile_mic_ico.setIcon(icon("microphone", active=False))
            self._tile_mic.setStyleSheet("""
                background: #2a1414;
                border: 1px solid #5a2323;
                border-radius: 10px;
            """)
        else:
            self._pill_mic_btn.setIcon(icon("microphone", active=True))
            self._pill_mic_btn.setStyleSheet("""
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
            self._tile_mic_lbl.setText("On")
            self._tile_mic_lbl.setStyleSheet(f"color: {C_WHITE}; background: transparent;")
            self._tile_mic_ico.setIcon(icon("microphone", active=True))
            self._tile_mic.setStyleSheet(f"""
                background: {C_TILE_BG};
                border: 1px solid {C_TILE_BORDER};
                border-radius: 10px;
            """)

    # ── State Updates ────────────────────────────────────────────────────────
    def on_cpu_updated(self, val: float, text: str):
        self._tile_cpu_lbl.setText(text)

    def on_voice_auth_updated(self, ok: bool, message: str):
        if ok:
            self._tile_sec_lbl.setText("Cleared")
            self._tile_sec_ico.setIcon(icon("shield-check", active=True))
        else:
            self._tile_sec_lbl.setText("Locked")
            self._tile_sec_ico.setIcon(icon("shield-check", active=False))

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

        # Update mic tile & button based on state
        if self._main_window and hasattr(self._main_window, "_muted") and self._main_window._muted:
            self.set_mic_muted(True)
        elif st == "MUTED":
            self.set_mic_muted(True)
        elif st in ("LISTENING", "SPEAKING"):
            self.set_mic_muted(False)

    # ── Info Card & Multi-Item List ──────────────────────────────────────────
    def set_info(self, payload: dict | None = None):
        """
        Extend the info-card with discriminated type:
        payload = {
            "type": "value" | "list",
            "sourceLabel": str,
            "updatedLabel": str,
            "icon": str,
            # when type == "value":
            "itemName": str,
            "value": str,
            "delta": str,
            "trend": list[float] | None,
            # when type == "list":
            "items": [
                {"title": str, "snippet": str, "sourceLink": str}
            ]
        }
        """
        self._info_payload = payload
        if not payload:
            self._content_stack.setCurrentWidget(self._status_container)
            self._target_expanded_w = self.EXPANDED_W
            self._target_expanded_h = self.EXPANDED_H
            if self._is_expanded:
                self._animate_resize(self.EXPANDED_W, self.EXPANDED_H)
            return

        start_geom = self.geometry()
        ptype = payload.get("type", "value")
        if ptype == "list":
            self._render_list_block(payload)
            self._content_stack.setCurrentWidget(self._info_list_container)
            self._target_expanded_w = self.EXPANDED_LIST_W
            self._target_expanded_h = self.EXPANDED_LIST_H
            if self._is_expanded:
                self._animate_resize(self.EXPANDED_LIST_W, self.EXPANDED_LIST_H, start_geom=start_geom)
        else:
            self._render_value_block(payload)
            self._content_stack.setCurrentWidget(self._info_value_container)
            self._target_expanded_w = self.EXPANDED_W
            self._target_expanded_h = self.EXPANDED_H
            if self._is_expanded:
                self._animate_resize(self.EXPANDED_W, self.EXPANDED_H, start_geom=start_geom)

    def _render_value_block(self, payload: dict):
        source_txt = payload.get("sourceLabel", "Market")
        updated_txt = payload.get("updatedLabel", "")
        item_name = payload.get("itemName", "")
        self._val_source_lbl.setText(f"{source_txt} • {updated_txt}" if updated_txt else source_txt)
        self._val_name_lbl.setText(item_name)

        icon_name = payload.get("icon", "broadcast")
        try:
            self._val_icon_btn.setIcon(icon(icon_name, active=True))
        except Exception:
            pass

        val_str = str(payload.get("value", "—"))
        self._val_value_lbl.setText(val_str)

        delta_str = str(payload.get("delta", "+0.0%"))
        self._val_delta_lbl.setText(delta_str)
        if delta_str.startswith("-"):
            self._val_delta_lbl.setStyleSheet(f"""
                color: {C_DANGER};
                background: #2a1414;
                border: 1px solid #5a2323;
                border-radius: 8px;
                padding: 2px 6px;
            """)
        else:
            self._val_delta_lbl.setStyleSheet(f"""
                color: {C_PRI};
                background: #1c1e1d;
                border: 1px solid {C_TILE_BORDER};
                border-radius: 8px;
                padding: 2px 6px;
            """)

        trend = payload.get("trend")
        self._val_sparkline.set_points(trend)

    def _render_list_block(self, payload: dict):
        source_txt = payload.get("sourceLabel", "Search")
        updated_txt = payload.get("updatedLabel", "Just now")
        self._list_source_lbl.setText(f"{source_txt} • {updated_txt}" if updated_txt else source_txt)

        icon_name = payload.get("icon", "layout-grid-add")
        try:
            self._list_icon_btn.setIcon(icon(icon_name, active=True))
        except Exception:
            pass

        # Clear existing items
        while self._list_items_lay.count():
            item = self._list_items_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        items = payload.get("items", [])
        vp_w = self._list_scroll.viewport().width()
        available_text_w = vp_w - 6 if vp_w > 50 else (self.EXPANDED_LIST_W - 28 - 11)

        for idx, it in enumerate(items):
            item_frame = QFrame()
            top_border = f"border-top: 1px solid {C_TILE_BORDER};" if idx > 0 else "border-top: none;"
            item_frame.setStyleSheet(f"""
                QFrame {{
                    background: transparent;
                    {top_border}
                    padding-top: {6 if idx > 0 else 0}px;
                    padding-bottom: 6px;
                }}
            """)
            ilay = QVBoxLayout(item_frame)
            ilay.setContentsMargins(0, 0, 0, 0)
            ilay.setSpacing(3)

            # Title: 13px, weight 500, primary text color #f2f2f2
            title_lbl = QLabel(it.get("title", ""))
            title_lbl.setFont(_island_font(9.5, weight=QFont.Weight.Medium))
            title_lbl.setStyleSheet(f"color: {C_WHITE}; background: transparent; border: none;")
            title_lbl.setWordWrap(True)
            ilay.addWidget(title_lbl)

            # Snippet: 12px, secondary/muted text color #8a8f8d, 2-line clamp
            snippet_font = _island_font(8.5)
            clamped_snippet = _clamp_to_2_lines(it.get("snippet", ""), snippet_font, max_width=available_text_w)
            snippet_lbl = QLabel(clamped_snippet)
            snippet_lbl.setFont(snippet_font)
            snippet_lbl.setStyleSheet(f"color: {C_TEXT_DIM}; background: transparent; border: none;")
            snippet_lbl.setWordWrap(False)
            ilay.addWidget(snippet_lbl)

            # Source link: 11px, C_PRI accent color #2ee672, linkActivated handler
            link_url = it.get("sourceLink", "")
            safe_href = html.escape(link_url, quote=True)
            safe_text = html.escape(link_url)

            link_lbl = QLabel()
            link_lbl.setText(f'<a href="{safe_href}" style="color: {C_PRI}; text-decoration: none;">{safe_text}</a>')
            link_lbl.setFont(_island_font(8))
            link_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            link_lbl.setStyleSheet(f"""
                QLabel {{
                    background: transparent;
                    border: none;
                }}
                QLabel:hover {{
                    text-decoration: underline;
                }}
            """)
            link_lbl.linkActivated.connect(_open_source_link)
            ilay.addWidget(link_lbl)

            self._list_items_lay.addWidget(item_frame)

        self._list_items_lay.addStretch(1)

    def _animate_resize(self, target_w: int, target_h: int, start_geom: QRect | None = None):
        self._target_expanded_w = target_w
        self._target_expanded_h = target_h

        if not self._is_expanded:
            return

        curr_geom = start_geom or self.geometry()
        if curr_geom.width() == target_w and curr_geom.height() == target_h:
            return

        center_x = curr_geom.center().x()
        new_x = center_x - target_w // 2
        new_y = curr_geom.y()

        screen = QApplication.primaryScreen().availableGeometry()
        target_geom = QRect(new_x, new_y, target_w, target_h)

        if target_geom.right() > screen.right():
            target_geom.moveRight(screen.right() - 8)
        if target_geom.left() < screen.left():
            target_geom.moveLeft(screen.left() + 8)
        if target_geom.bottom() > screen.bottom():
            target_geom.moveBottom(screen.bottom() - 8)
        if target_geom.top() < screen.top():
            target_geom.moveTop(screen.top() + 8)

        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setStartValue(curr_geom)
        self._anim.setEndValue(target_geom)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    # ── Transitions & Expansion ──────────────────────────────────────────────
    def expand(self):
        """Transition from STATE 1 (collapsed pill) directly to expanded card in one animation."""
        if self._is_expanded:
            return
        self._is_expanded = True

        target_w = getattr(self, "_target_expanded_w", self.EXPANDED_W)
        target_h = getattr(self, "_target_expanded_h", self.EXPANDED_H)

        curr_geom = self.geometry()
        center_x = curr_geom.center().x()
        new_x = center_x - target_w // 2
        new_y = curr_geom.y()

        screen = QApplication.primaryScreen().availableGeometry()
        target_geom = QRect(new_x, new_y, target_w, target_h)

        # Keep on screen
        if target_geom.right() > screen.right():
            target_geom.moveRight(screen.right() - 8)
        if target_geom.left() < screen.left():
            target_geom.moveLeft(screen.left() + 8)
        if target_geom.bottom() > screen.bottom():
            target_geom.moveBottom(screen.bottom() - 8)
        if target_geom.top() < screen.top():
            target_geom.moveTop(screen.top() + 8)

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
        center_x = curr_geom.center().x()
        new_x = center_x - self.COLLAPSED_W // 2
        new_y = curr_geom.y()

        screen = QApplication.primaryScreen().availableGeometry()
        target_geom = QRect(new_x, new_y, self.COLLAPSED_W, self.COLLAPSED_H)

        if target_geom.right() > screen.right():
            target_geom.moveRight(screen.right() - 8)
        if target_geom.left() < screen.left():
            target_geom.moveLeft(screen.left() + 8)
        if target_geom.bottom() > screen.bottom():
            target_geom.moveBottom(screen.bottom() - 8)
        if target_geom.top() < screen.top():
            target_geom.moveTop(screen.top() + 8)

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
        """STATE 3: Raise MainWindow in full normal/fullscreen view and collapse island back to STATE 1."""
        if self._main_window:
            self._main_window.showNormal()
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

        self.collapse()

    # ── Window Dragging & Interaction ────────────────────────────────────────
    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_dashboard()
            e.accept()

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
