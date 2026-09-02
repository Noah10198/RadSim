"""
VtkViewWindow - Standalone 3D View Window

A plain QWidget shown as a top-level window, hosting VtkWidget.
CRITICAL: NO stylesheet/QSS anywhere near this window — even a single
rule on the wrapper activates Qt's style engine and can break VTK's
OpenGL compositing, producing a white/blank viewport.

Usage:
    window = VtkViewWindow()
    window.set_dark_theme(True)
    window.build_scene(root_node)
    window.show()
"""

from typing import Optional

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal

from ui.vtk_widget import VtkWidget, VtkPreviewWidget
from vtk_engine.vtk_scene import VtkScene
from core.gdml_tree import GdmlNode


class VtkViewWindow(QWidget):
    """
    Stand-alone 3D view window.

    This is a plain QWidget shown as a top-level window (via WindowFlags).
    It wraps VtkWidget (or VtkPreviewWidget) and forwards API calls.
    Absolutely NO stylesheet is set — the dark background comes from VTK's
    renderer background colour, NOT from Qt styling.
    """

    node_picked = pyqtSignal(str)  # Forwarded from VtkWidget

    def __init__(self, preview_mode: bool = False):
        super().__init__()
        widget_class = VtkPreviewWidget if preview_mode else VtkWidget
        self._vtk_widget = widget_class(self)
        self._vtk_widget.setMinimumSize(100, 100)

        self.setWindowTitle("3D View")
        self.resize(1000, 700)

        # ------------------------------------------------------------------
        # CRITICAL: Prevent ANY Qt background painting on this window.
        # Without these flags, Qt paints a solid (usually white) background
        # on top of the VTK OpenGL surface, making the 3D view blank.
        # ------------------------------------------------------------------
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        # Layout — VtkWidget fills the whole window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._vtk_widget)

        # Window flags: native window with standard decorations but
        # completely independent from MainWindow.
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMinimizeButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Forward picking signal
        self._vtk_widget.node_picked.connect(self.node_picked)

    # ------------------------------------------------------------------
    # Forwarded VtkWidget API
    # ------------------------------------------------------------------

    def build_scene(self, root_node: GdmlNode, *, render_all_volumes: bool = False):
        """Build/rebuild the full scene from the GDML tree."""
        self._vtk_widget.build_scene(root_node, render_all_volumes=render_all_volumes)

    def get_scene(self) -> VtkScene:
        """Get the underlying VtkScene."""
        return self._vtk_widget.get_scene()

    def refresh(self):
        """Force a render refresh."""
        self._vtk_widget.refresh()

    def set_dark_theme(self, dark: bool):
        """Switch between dark / light background."""
        self._vtk_widget.set_dark_theme(dark)

    def set_all_opacity(self, opacity: float):
        """Set opacity for all GDML actors (e.g. 0.45 for transparent preview)."""
        for a in self._vtk_widget._gdml_actors:
            p = a.GetProperty()
            p.SetOpacity(opacity)
            p.SetEdgeColor(0.5, 0.8, 0.9)
        self.refresh()

    def cleanup(self):
        """Release VTK resources."""
        self._vtk_widget.cleanup()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """Override close to also clean up VTK resources."""
        self._vtk_widget.cleanup()
        super().closeEvent(event)
