"""
RadSim - 3D Radiation Simulation GUI

Provides a graphical front-end for the rad4space solver: GDML geometry
rendering plus configuration and result display for three analysis modes
(realworld / probe / voxel). The UI style matches gdmleditor.
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suppress Qt warnings
os.environ["QT_LOGGING_RULES"] = ("qt.qpa.windows.warning=false;"
                                  "qt.qpa.gl.warning=false;"
                                  "qt.qpa.eglfs.warning=false")

import ctypes

try:
    ctypes.windll.user32.DisableProcessWindowsGhosting()
except Exception:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import (qInstallMessageHandler, QtMsgType, QMessageLogContext,
                          Qt)
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from app.main_window import MainWindow
from utils.logger import AsyncLogger

# Taskbar identity. Windows groups every script launched by python.exe under a
# single "Python" entry, so without this the taskbar button keeps Python's icon
# and jump lists of unrelated scripts get mixed together.
_APP_USER_MODEL_ID = "RadSim.RadSim.1"
_ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "icon", "radsim.svg")

# Sizes Windows asks for: 16 px is the title bar icon at 100% scaling, 24 px
# the taskbar button, and the rest cover higher DPI settings and Alt+Tab.
_ICON_SIZES = (16, 20, 24, 32, 48, 64, 96, 128, 256)


def _qt_message_filter(_msg_type: QtMsgType, _context: QMessageLogContext,
                       message: str) -> None:
    """Silence benign Qt platform noise on Windows.

    Qt tries to give native title bars a dark border when a window's
    background is dark (preview windows / dark theme). On Windows builds
    where DwmSetWindowAttribute is unavailable or called before the native
    window exists it prints, per window/attempt:
      QWindowsWindow::setDarkBorderToWindow: Unable to set dark window border.
    It is cosmetic noise - the OS simply falls back to the normal border -
    so the line is dropped. Everything else is forwarded to stderr.
    """
    text = str(message)
    if "setDarkBorderToWindow" in text:
        return
    print(f"Qt: {text}", file=sys.stderr)


def _build_app_icon() -> QIcon:
    """Build the window / taskbar icon from icon/radsim.svg.

    The source is a vector, so it is rendered once per size Windows may ask
    for instead of being scaled down from a single raster, which keeps the
    small title bar and taskbar versions sharp.
    """
    if not os.path.exists(_ICON_FILE):
        return QIcon()

    renderer = QSvgRenderer(_ICON_FILE)
    if not renderer.isValid():
        return QIcon(_ICON_FILE)

    icon = QIcon()
    for size in _ICON_SIZES:
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(canvas)
    return icon


def main():
    # Must be set before any window exists, otherwise the taskbar entry is
    # already bound to python.exe and the icon below has no effect.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                _APP_USER_MODEL_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("RadSim")
    app.setApplicationVersion("0.1.0")
    app.setWindowIcon(_build_app_icon())
    _ = qInstallMessageHandler(_qt_message_filter)

    main_window = MainWindow()

    logger = AsyncLogger()
    logger.set_system_log_widget(main_window.get_system_log_widget())
    logger.log_system("RadSim started")
    logger.log_system(f"Python version: {sys.version}")

    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
