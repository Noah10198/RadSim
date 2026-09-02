"""
3dRad - 3D Radiation Simulation GUI

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

from app.main_window import MainWindow
from utils.logger import AsyncLogger


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("3dRad")
    app.setApplicationVersion("0.1.0")

    main_window = MainWindow()

    logger = AsyncLogger()
    logger.set_system_log_widget(main_window.get_system_log_widget())
    logger.log_system("3dRad started")
    logger.log_system(f"Python version: {sys.version}")

    main_window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
