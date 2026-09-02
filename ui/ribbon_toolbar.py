"""
RibbonToolBar - 3dRad Ribbon Toolbar

Menu order (as agreed with the user; icon style matches 1dRad/gdmleditor):
  📁 Import GDML │ 🧾 Load Project │ 💾 Save Project ┃
  🎯 Reset View │ ▶️ Run │ ⏹ Stop ┃
  🟢 Status (status indicator, click to show calculation progress) │ 🌙/☀️ Theme │ ❓ Help
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QSizePolicy, QFrame
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor


def _create_emoji_icon(emoji: str) -> QIcon:
    """Render emoji at 2x resolution for supersampled crispness."""
    pixmap = QPixmap(72, 72)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    font = QFont("Segoe UI Emoji", 48)
    painter.setFont(font)
    painter.setPen(QColor(220, 220, 220))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()
    return QIcon(pixmap)


def _ribbon_button(emoji: str, text: str) -> QToolButton:
    """Ribbon-style button: icon on top, text below (same size as in
    gdmleditor)."""
    btn = QToolButton()
    btn.setIcon(_create_emoji_icon(emoji))
    btn.setIconSize(QSize(36, 36))
    btn.setText(text)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setMinimumSize(85, 68)
    btn.setMaximumSize(120, 72)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    # Drop the focus rectangle/highlight ring so that buttons do not get an
    # outline when focused
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return btn


class RibbonToolBar(QWidget):
    """3dRad Ribbon: File / View / Run / Status / Theme / Help"""

    import_clicked = pyqtSignal()
    load_clicked = pyqtSignal()
    save_clicked = pyqtSignal()
    reset_view_clicked = pyqtSignal()
    run_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    status_clicked = pyqtSignal()
    theme_toggled = pyqtSignal()
    help_clicked = pyqtSignal()

    # Status button: emoji / main text / accent color
    STATUS_META = {
        "idle":    ("🟢", "Idle",    "#4caf50"),
        "running": ("🔄", "Running", "#0078d4"),
        "issues":  ("⚠️", "Issues",  "#ed6c00"),
        "done":    ("✅", "Done",    "#4caf50"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonToolBar")
        self._dark_theme = False
        self._status_state = "idle"
        self._build_ui()
        self._apply_theme(False)
        self.set_status("idle")

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        # -- File group --
        import_btn = _ribbon_button("📁", "Import GDML")
        import_btn.clicked.connect(self.import_clicked.emit)
        layout.addWidget(import_btn)

        load_btn = _ribbon_button("🧾", "Load Project")
        load_btn.setToolTip("Load a saved project (JSON)")
        load_btn.clicked.connect(self.load_clicked.emit)
        layout.addWidget(load_btn)

        save_btn = _ribbon_button("💾", "Save Project")
        save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(save_btn)

        layout.addWidget(self._sep())

        # -- View / Run group --
        reset_btn = _ribbon_button("🎯", "Reset View")
        reset_btn.clicked.connect(self.reset_view_clicked.emit)
        layout.addWidget(reset_btn)

        self._run_btn = _ribbon_button("▶️", "Run")
        self._run_btn.setObjectName("RunButton")
        self._run_btn.clicked.connect(self.run_clicked.emit)
        layout.addWidget(self._run_btn)

        self._stop_btn = _ribbon_button("⏹", "Stop")
        self._stop_btn.setObjectName("StopButton")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self._stop_btn)

        layout.addWidget(self._sep())

        # -- Status indicator (click to show calculation progress) --
        self._status_btn = _ribbon_button("🟢", "Idle")
        self._status_btn.setObjectName("StatusButton")
        self._status_btn.setToolTip(
            "Show task calculation status (running / issues / done)")
        self._status_btn.clicked.connect(self.status_clicked.emit)
        layout.addWidget(self._status_btn)

        layout.addStretch()

        # -- Theme / Help --
        self._theme_btn = _ribbon_button("☀️", "Light")
        self._theme_btn.setObjectName("ThemeToggle")
        self._theme_btn.clicked.connect(self.theme_toggled.emit)
        layout.addWidget(self._theme_btn)

        help_btn = _ribbon_button("❓", "Help")
        help_btn.clicked.connect(self.help_clicked.emit)
        layout.addWidget(help_btn)

    @staticmethod
    def _sep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(3)
        return sep

    # -- Run status --

    def set_running(self, running: bool):
        self._stop_btn.setEnabled(running)
        self._run_btn.setEnabled(not running)

    def set_status(self, state: str, detail: str = ""):
        """Update the status indicator button (idle / running / issues /
        done)."""
        meta = self.STATUS_META.get(state, self.STATUS_META["idle"])
        emoji, label, _color = meta
        self._status_state = state
        self._status_btn.setIcon(_create_emoji_icon(emoji))
        self._status_btn.setText(label if not detail else f"{label}·{detail}")
        self._status_btn.setProperty("statusState", state)
        self._status_btn.style().unpolish(self._status_btn)
        self._status_btn.style().polish(self._status_btn)

    def set_dark_theme(self, is_dark: bool):
        self._dark_theme = is_dark
        self._apply_theme(is_dark)
        self._theme_btn.setIcon(_create_emoji_icon("🌙" if is_dark else "☀️"))
        self._theme_btn.setText("Dark" if is_dark else "Light")

    def _apply_theme(self, dark: bool):
        if dark:
            bg, border = "#1e1e2e", "#313244"
            text, hover, hov_bd, press = "#cdd6f4", "#313244", "#45475a", "#45475a"
        else:
            bg, border = "#f5f5f5", "#d0d0d0"
            text, hover, hov_bd, press = "#2c2c2c", "#e0e0e0", "#c0c0c0", "#cccccc"

        self.setStyleSheet(f"""
            #RibbonToolBar {{
                background-color: {bg};
                border-bottom: 2px solid {border};
                min-height: 72px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 3px 10px;
                color: {text};
                font-size: 12px;
                font-family: "Segoe UI", "Arial", sans-serif;
            }}
            QToolButton:hover {{
                background-color: {hover};
                border: 1px solid {hov_bd};
            }}
            QToolButton:pressed {{
                background-color: {press};
            }}
            QToolButton:disabled {{
                color: rgba(140, 140, 140, 0.45);
            }}
            QToolButton[statusState="running"] {{ color: #0078d4; }}
            QToolButton[statusState="issues"] {{ color: #ed6c00; }}
            QToolButton[statusState="idle"],
            QToolButton[statusState="done"] {{ color: #4caf50; }}
        """)
