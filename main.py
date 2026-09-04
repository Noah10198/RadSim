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

try:
    import ctypes
    ctypes.windll.user32.DisableProcessWindowsGhosting()
except Exception:
    pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType, QMessageLogContext

from app.main_window import MainWindow
from utils.logger import AsyncLogger


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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RadSim")
    app.setApplicationVersion("0.1.0")
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
