"""
VtkWidget - VTK 3D View Embedded in Qt

Matches cad2gdml/mesh/mesh_viewer.py style:
- vtkCubeAxesActor for RGB coordinate axes WITH dimension labels
- Toolbar: Transparency, Edges, Clip, X/Y/Z axis-views, Ortho, Fit All
- Clipping plane (axis selector + slider)

Design:
  - QWidget wrapper (like MeshViewer) containing QVTKRenderWindowInteractor
    + toolbar layout, rather than inheriting QVTKRenderWindowInteractor.
  - Exposes the same public API as before (get_scene, build_scene, ...).
"""

from typing import Optional, Dict, Tuple, List, Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QComboBox, QButtonGroup,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkRenderingCore import (
    vtkRenderer, vtkActor, vtkPolyDataMapper,
)
from vtkmodules.vtkRenderingAnnotation import vtkCubeAxesActor, vtkCornerAnnotation
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPlaneCollection

# Import VTK backends (needed on Windows). vtkRenderingVolumeOpenGL2 registers
# the OpenGL implementation of vtkRayCastImageDisplayHelper used by the volume
# (voxel-field) renderers; without it AddVolume() renders nothing and prints
# "Error: no override found for 'vtkRayCastImageDisplayHelper'".
import vtkmodules.vtkRenderingOpenGL2
import vtkmodules.vtkRenderingVolumeOpenGL2
import vtkmodules.vtkInteractionStyle

from vtk_engine.vtk_scene import VtkScene
from core.gdml_tree import GdmlNode

# Print GPU info only once globally (all VTK windows share the same GPU)
_GPU_INFO_PRINTED = False


def _mapper_addr(m) -> str:
    """Stable identity of the underlying C++ mapper.

    Must NOT deduplicate by id(m): VTK python does not guarantee one pooled
    wrapper per C++ mapper, so a transient wrapper may be GC'd and its id()
    recycled mid-loop, falsely marking distinct mappers as "already seen".
    An actor holds a reference to its mapper for its whole lifetime, so the
    C++ address is unique and stable while we iterate live actors.
    """
    try:
        return m.GetAddressAsString("vtkPolyDataMapper")
    except Exception:
        return str(m)


# ── VtkWidget ───────────────────────────────────────────────────────


class VtkWidget(QWidget):
    """
    VTK 3D view with toolbar matching cad2gdml's MeshViewer.

    Features:
      - RGB CubeAxesActor with dimension labels
      - Corner orientation marker
      - Toolbar: Transparency, Edges, Clip, X/Y/Z views, Ortho, Fit All
      - Clipping plane panel (axis combo + slider)
    """

    node_picked = pyqtSignal(str)   # Node picked, emits entry_id

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── State ──
        self._transparent = False
        self._show_edges = True
        self._is_ortho = False
        self._clip_active = False
        self._clip_axis = 0
        self._clip_plane = vtkPlane()
        self._clip_plane.SetOrigin(0, 0, 0)
        self._clip_plane.SetNormal(1, 0, 0)
        self._clip_bounds: Optional[List[float]] = None
        self._original_colors: Dict[int, Tuple[float, float, float]] = {}
        self._gdml_actors: List[vtkActor] = []
        self._is_dark = True

        # ── Build UI ──
        self._build_ui()

        # ── VTK / OpenGL setup ──
        ren_win = self._vtk_interactor.GetRenderWindow()
        ren_win.SetMultiSamples(0)

        self._scene = VtkScene()
        ren_win.AddRenderer(self._scene.renderer)
        self._scene.set_render_window(ren_win)
        self._scene.set_interactor(
            self._vtk_interactor.GetRenderWindow().GetInteractor()
        )

        # Dark background
        self._scene.set_background_color(0.12, 0.12, 0.18)

        # Proxy picking signal
        self._scene.pick_handler = (
            lambda entry_id: self.node_picked.emit(entry_id)
        )

        # ── Default actors ──
        self._cube_axes: Optional[vtkCubeAxesActor] = None

        self._vtk_interactor.Initialize()

        # ── GPU / OpenGL context activation ──
        import re as _re
        ren_win.SetWindowName("Easy2Rad")
        # Try on-screen (GPU-accelerated) first; fall back to off-screen
        # (software/Mesa) if the GPU driver is missing (remote desktop,
        # headless VM, basic display adapter, etc.).
        self._gpu_active = False
        global _GPU_INFO_PRINTED
        ren_win.SetOffScreenRendering(False)
        try:
            ren_win.Render()
            raw_caps = ren_win.ReportCapabilities() or ""
            # Parse key OpenGL fields (same style as OCC's Viewer3d)
            _s = _re.search
            m_vdr = _s(r"OpenGL vendor string:\s*(.+)", raw_caps)
            m_dev = _s(r"OpenGL renderer string:\s*(.+)", raw_caps)
            m_ver = _s(r"OpenGL version string:\s*(.+)", raw_caps)
            m_glsl = _s(r"GLSL version \(if available\):\s*(.+)", raw_caps)
            if m_vdr:
                self._gpu_info = f"{m_vdr.group(1)} / {m_dev.group(1) if m_dev else '?'}"
                self._gpu_active = True
                if not _GPU_INFO_PRINTED:
                    _GPU_INFO_PRINTED = True
                    # Print GPU info in OCC style (matches cad2gdml's Viewer3d)
                    print("#" * 41, flush=True)
                    print("OpenGl information (VTK):", flush=True)
                    print(f"  GLvendor:  {m_vdr.group(1)}", flush=True)
                    print(f"  GLdevice:  {m_dev.group(1) if m_dev else '?'}", flush=True)
                    print(f"  GLversion: {m_ver.group(1) if m_ver else '?'}", flush=True)
                    print(f"  GLSL:      {m_glsl.group(1) if m_glsl else '?'}", flush=True)
                    # Also show pixel format from pixel format descriptor section
                    px_match = _s(
                        r"(depth:\s+\d+.*?double buffer:\s+\w+)",
                        raw_caps, _re.DOTALL)
                    if px_match:
                        for line in px_match.group(1).strip().split("\n"):
                            print(f"  {line.strip()}", flush=True)
                    print("#" * 41, flush=True)
            else:
                self._gpu_info = "no OpenGL renderer reported"
        except Exception:
            self._gpu_info = "OpenGL context creation failed"

        if not self._gpu_active:
            # Fallback: off-screen rendering (software / Mesa)
            ren_win.SetOffScreenRendering(True)
            try:
                ren_win.Render()
                raw_caps = ren_win.ReportCapabilities() or ""
                _s = _re.search
                m_vdr = _s(r"OpenGL vendor string:\s*(.+)", raw_caps)
                m_dev = _s(r"OpenGL renderer string:\s*(.+)", raw_caps)
                suffix = " (software)"
                if m_vdr:
                    self._gpu_info = f"{m_vdr.group(1)} / {m_dev.group(1) if m_dev else '?'}{suffix}"
                else:
                    self._gpu_info = "off-screen (software)"
                if not _GPU_INFO_PRINTED:
                    _GPU_INFO_PRINTED = True
                    print("#" * 41, flush=True)
                    print("OpenGl information (VTK, off-screen/software):", flush=True)
                    print(f"  GLvendor:  {m_vdr.group(1) if m_vdr else '?'}", flush=True)
                    print(f"  GLdevice:  {m_dev.group(1) if m_dev else '?'}", flush=True)
                    print("#" * 41, flush=True)
            except Exception:
                self._gpu_info = "off-screen (no GL)"
            ren_win.SetOffScreenRendering(True)

        # Start the interactor lazily: only after the widget has been shown
        # once. Starting it while the window is still unmapped makes VTK
        # operate on an invalid WId/geometry, and on Windows it keeps
        # printing warnings such as
        #   QWindowsWindow::setGeometry: Unable to set geometry ...
        self._interactor_started = False
        self._bound_wid = None   # WId of the native window currently bound
        self._bound_once = False
        self._scene_built = False

        self._setup_default_scene()
        self._scene.renderer.ResetCamera()
        self.render()
        # Disable vertical sync. The default vsync locks on-screen rendering
        # to 60Hz: a scene with 800k triangles renders offscreen in only
        # ~7ms/frame, but vsync stretches it to 16.7ms, which feels laggy
        # when dragging large geometry. Once disabled the GPU renders at its
        # real rate and tearing is absorbed by the Windows DWM compositor.
        # This must be re-applied after the window recreates its GL context.
        self._set_swap_control(0)

    def showEvent(self, event):
        super().showEvent(event)
        self._maybe_start_interactor()
        self._ensure_window_bound()
        # When a scene already exists, rebind the WId after hide/show and
        # schedule a delayed redraw
        if getattr(self, "_scene_built", False):
            QTimer.singleShot(0, self.render)

    def _maybe_start_interactor(self):
        if getattr(self, "_interactor_started", False):
            return
        self._interactor_started = True
        try:
            self._vtk_interactor.Start()
        except Exception:
            pass

    def _ensure_window_bound(self):
        """The legacy QVTKRenderWindowInteractor recreates its native window
        after hide/show: the WId changes while vtkRenderWindow is still bound
        to the old WId and the old GL context (HDC), which leads to
        wglMakeCurrent failed / shader compilation failures while rendering.
        Every time the widget becomes visible the WId is compared; if it
        changed, we Finalize (releasing the old context) and rebind so that
        VTK rebuilds its context for the new HWND."""
        if not self._vtk_interactor.isVisible():
            return
        try:
            wid = int(self._vtk_interactor.winId())
        except Exception:
            return
        if wid == getattr(self, "_bound_wid", None):
            return
        self._bound_wid = wid
        try:
            rw = self._vtk_interactor.GetRenderWindow()
            if getattr(self, "_bound_once", False):
                # Previously bound to a different WId: the old GL context died
                # with the hidden HWND, so we must Finalize to let VTK rebuild
                # its context for the new HWND on the next Render.
                try:
                    rw.Finalize()
                except Exception:
                    pass
            self._bound_once = True
            rw.SetWindowInfo(str(wid))
            # New WId -> VTK rebuilds the GL context and vsync resets, so it
            # has to be disabled again
            self._set_swap_control(0)
        except Exception:
            pass

    # ── UI construction ──

    def _build_ui(self):
        """Build the widget layout — matches MeshViewer pattern."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # VTK viewport
        self._vtk_interactor = QVTKRenderWindowInteractor(self)
        layout.addWidget(self._vtk_interactor, 1)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self._btn_transparency = QPushButton("▣ Transparency")
        self._btn_transparency.setCheckable(True)
        self._btn_transparency.setToolTip("Toggle mesh transparency")
        self._btn_transparency.clicked.connect(self._toggle_transparency)
        toolbar.addWidget(self._btn_transparency)

        self._btn_edges = QPushButton("✕ Edges")
        self._btn_edges.setCheckable(True)
        self._btn_edges.setChecked(True)
        self._btn_edges.setToolTip("Toggle mesh edge lines")
        self._btn_edges.clicked.connect(self._toggle_edges)
        toolbar.addWidget(self._btn_edges)

        # Clip
        self._btn_clip = QPushButton("✂ Clip")
        self._btn_clip.setCheckable(True)
        self._btn_clip.setToolTip("Enable clipping plane")
        self._btn_clip.clicked.connect(self._toggle_clip_panel)
        toolbar.addWidget(self._btn_clip)

        # Fit All
        btn_fit = QPushButton("⌂ Fit")
        btn_fit.setToolTip("Reset camera to fit all objects")
        btn_fit.clicked.connect(self._fit_all)
        toolbar.addWidget(btn_fit)

        # Ortho / Perspective toggle
        self._btn_proj = QPushButton("◻ Ortho")
        self._btn_proj.setCheckable(True)
        self._btn_proj.setToolTip("Toggle orthographic / perspective")
        self._btn_proj.clicked.connect(self._toggle_projection)
        toolbar.addWidget(self._btn_proj)

        # Axis view buttons
        self._axis_group = QButtonGroup(self)
        self._axis_group.setExclusive(True)

        self._btn_axis_x = QPushButton("X")
        self._btn_axis_x.setCheckable(True)
        self._btn_axis_x.setToolTip("View from +X axis")
        self._btn_axis_x.clicked.connect(lambda: self._set_axis_view(0))
        toolbar.addWidget(self._btn_axis_x)
        self._axis_group.addButton(self._btn_axis_x)

        self._btn_axis_y = QPushButton("Y")
        self._btn_axis_y.setCheckable(True)
        self._btn_axis_y.setToolTip("View from +Y axis")
        self._btn_axis_y.clicked.connect(lambda: self._set_axis_view(1))
        toolbar.addWidget(self._btn_axis_y)
        self._axis_group.addButton(self._btn_axis_y)

        self._btn_axis_z = QPushButton("Z")
        self._btn_axis_z.setCheckable(True)
        self._btn_axis_z.setToolTip("View from +Z axis")
        self._btn_axis_z.clicked.connect(lambda: self._set_axis_view(2))
        toolbar.addWidget(self._btn_axis_z)
        self._axis_group.addButton(self._btn_axis_z)

        layout.addLayout(toolbar)

        # Clipping controls panel (hidden by default)
        self._clip_panel = QWidget()
        clip_row = QHBoxLayout(self._clip_panel)
        clip_row.setContentsMargins(4, 0, 4, 0)
        clip_row.setSpacing(4)

        cl = QLabel("Clip →")
        cl.setStyleSheet("font-weight: bold; color: #f38ba8;")
        clip_row.addWidget(cl)

        self._clip_axis_cb = QComboBox()
        self._clip_axis_cb.addItems(["X-Axis", "Y-Axis", "Z-Axis"])
        self._clip_axis_cb.currentIndexChanged.connect(self._on_clip_changed)
        clip_row.addWidget(self._clip_axis_cb)

        self._clip_slider = QSlider(Qt.Orientation.Horizontal)
        self._clip_slider.setMinimumWidth(120)
        self._clip_slider.setRange(0, 1000)
        self._clip_slider.setValue(500)
        self._clip_slider.valueChanged.connect(self._on_clip_changed)
        clip_row.addWidget(self._clip_slider, 1)

        self._clip_label = QLabel("0.00")
        self._clip_label.setMinimumWidth(50)
        clip_row.addWidget(self._clip_label)

        cr = QPushButton("Reset")
        cr.clicked.connect(self._clip_reset)
        clip_row.addWidget(cr)

        self._clip_panel.setVisible(False)
        layout.addWidget(self._clip_panel)

        # Apply dark toolbar style
        self._apply_toolbar_style(True)

    def _apply_toolbar_style(self, dark: bool):
        """Toolbar styling — buttons, combo and the themed sliders."""
        self._is_dark = dark
        if dark:
            bg       = "#2a2a3a"
            fg       = "#e0e0e0"
            border   = "#4a4a5a"
            hover_bg = "#3a3a4e"
            checked  = "#3d59a1"
            checked_fg = "#ffffff"
            label_fg = "#b0b0c0"
            clip_bg  = "#1e1e2e"
        else:
            bg       = "#f5f5f5"
            fg       = "#2c2c2c"
            border   = "#c8c8c8"
            hover_bg = "#e8e8e8"
            checked  = "#c0d0f0"
            checked_fg = "#1a1a2a"
            label_fg = "#505050"
            clip_bg  = "#e8e8e8"

        # Buttons
        btn = f"""
        QPushButton {{
            padding: 3px 10px;
            font-size: 12px;
            border: 1px solid {border};
            border-radius: 4px;
            background: {bg};
            color: {fg};
        }}
        QPushButton:hover {{
            background: {hover_bg};
        }}
        QPushButton:checked {{
            background: {checked};
            color: {checked_fg};
            border-color: {checked};
        }}
        """
        # Combo
        combo = f"""
        QComboBox {{
            padding: 2px 6px;
            font-size: 12px;
            border: 1px solid {border};
            border-radius: 4px;
            background: {bg};
            color: {fg};
        }}
        QComboBox:hover {{
            border-color: {checked};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border: none;
        }}
        """
        # Labels
        lbl = f"""
        QLabel {{
            font-size: 12px;
            color: {label_fg};
        }}
        """

        self.setStyleSheet(btn + combo + lbl)
        self._clip_panel.setStyleSheet(f"background: {clip_bg};" + btn + combo + lbl)
        self._style_qt_sliders(dark)

    def _style_qt_sliders(self, dark: bool):
        """Theme the Clip slider (and an Opacity slider if one exists) with the
        same look the voxel result window uses: slim rounded groove with a
        coloured fill and a round-ball thumb. Keeps the control visible on the
        dark clip strip instead of the OS-native light slider."""
        groove = "#3a3a4e" if dark else "#d8d8d8"
        fill = "#7a8bd0" if dark else "#4a6aa8"
        ss = f"""
        QSlider::groove:horizontal {{ height: 4px; background: {groove};
            border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {fill}; border-radius: 2px; }}
        QSlider::add-page:horizontal {{ background: {groove}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -5px 0;
            background: {fill}; border-radius: 7px; }}
        """
        for s in (getattr(self, "_clip_slider", None),
                  getattr(self, "_opacity_slider", None)):
            if s is not None:
                s.setStyleSheet(ss)

    # ── Default scene ──

    def _setup_default_scene(self):
        """Add CubeAxesActor with dimension labels (no grid — too noisy)."""
        ren = self._scene.renderer

        # Init CubeAxes with default bounds (updated when objects loaded)
        self._init_cube_axes([-10, 10, -10, 10, -10, 10])
        ren.AddActor(self._cube_axes)

    def _init_cube_axes(self, bounds: List[float]):
        """Create CubeAxesActor with RGB colored axes and dimension labels."""
        if self._cube_axes is None:
            self._cube_axes = vtkCubeAxesActor()
        self._cube_axes.SetBounds(bounds)
        self._cube_axes.SetCamera(self._scene.renderer.GetActiveCamera())
        self._cube_axes.SetXLabelFormat("%.1f")
        self._cube_axes.SetYLabelFormat("%.1f")
        self._cube_axes.SetZLabelFormat("%.1f")
        # Axis lines — RGB
        self._cube_axes.GetXAxesLinesProperty().SetColor(1, 0.3, 0.3)
        self._cube_axes.GetYAxesLinesProperty().SetColor(0.3, 1, 0.3)
        self._cube_axes.GetZAxesLinesProperty().SetColor(0.3, 0.3, 1)
        self._cube_axes.SetFlyModeToOuterEdges()
        # Turn off default grid lines (keep only the axis lines)
        self._cube_axes.DrawXGridlinesOff()
        self._cube_axes.DrawYGridlinesOff()
        self._cube_axes.DrawZGridlinesOff()
        self._cube_axes.SetGridLineLocation(self._cube_axes.VTK_GRID_LINES_ALL)

        # ── Title text (X / Y / Z) — larger, bold, RGB ──
        for axis_idx in range(3):
            tp = self._cube_axes.GetTitleTextProperty(axis_idx)
            tp.SetFontSize(16)
            tp.BoldOn()
            tp.ItalicOff()
            tp.SetShadow(1)
        # Title colors
        self._cube_axes.GetTitleTextProperty(0).SetColor(1, 0.3, 0.3)   # X
        self._cube_axes.GetTitleTextProperty(1).SetColor(0.3, 1, 0.3)   # Y
        self._cube_axes.GetTitleTextProperty(2).SetColor(0.3, 0.3, 1)   # Z

        # ── Label text (numeric values) — larger, same RGB as axis ──
        for axis_idx in range(3):
            lp = self._cube_axes.GetLabelTextProperty(axis_idx)
            lp.SetFontSize(16)
            lp.BoldOff()
            lp.SetShadow(1)
        self._cube_axes.GetLabelTextProperty(0).SetColor(1, 0.3, 0.3)  # X labels red
        self._cube_axes.GetLabelTextProperty(1).SetColor(0.3, 1, 0.3)  # Y labels green
        self._cube_axes.GetLabelTextProperty(2).SetColor(0.3, 0.3, 1)  # Z labels blue

        # ── Axis tick marks ──
        self._cube_axes.SetXAxisLabelVisibility(1)
        self._cube_axes.SetYAxisLabelVisibility(1)
        self._cube_axes.SetZAxisLabelVisibility(1)

        # Grid lines style (faint)
        self._cube_axes.GetXAxesGridlinesProperty().SetColor(0.4, 0.4, 0.5)
        self._cube_axes.GetYAxesGridlinesProperty().SetColor(0.4, 0.4, 0.5)
        self._cube_axes.GetZAxesGridlinesProperty().SetColor(0.4, 0.4, 0.5)

    def _ensure_default_actors(self):
        """Re-add cube axes if cleared."""
        ren = self._scene.renderer
        if self._cube_axes and not ren.HasViewProp(self._cube_axes):
            ren.AddActor(self._cube_axes)

    def _update_cube_axes_bounds(self):
        """Recompute CubeAxes bounds from all GDML actors (skip cube axes itself)."""
        if not self._scene.renderer:
            return
        coll = self._scene.renderer.GetViewProps()
        bounds = [float('inf'), -float('inf'),
                  float('inf'), -float('inf'),
                  float('inf'), -float('inf')]
        has_geom = False
        for i in range(coll.GetNumberOfItems()):
            prop = coll.GetItemAsObject(i)
            if isinstance(prop, vtkActor) and prop is not self._cube_axes:
                b = prop.GetBounds()
                if b:
                    for k in range(6):
                        if k % 2 == 0:
                            bounds[k] = min(bounds[k], b[k])
                        else:
                            bounds[k] = max(bounds[k], b[k])
                    has_geom = True
        if has_geom and all(abs(v) < 1e10 for v in bounds):
            for k in range(6):
                if bounds[k] in (float('inf'), -float('inf')):
                    bounds[k] = 0.0
        else:
            # No geometry: reset to default small bounds
            bounds = [-10, 10, -10, 10, -10, 10]
        self._cube_axes.SetBounds(bounds)
        self._clip_bounds = bounds

    # ── Public API ──

    def get_scene(self) -> VtkScene:
        """Get the scene manager."""
        return self._scene

    def build_scene(self, root_node: GdmlNode, *, render_all_volumes: bool = False) -> None:
        """Build scene from GDML tree, preserving grid/axes."""
        if not self._scene:
            return
        # Capture current colors before clear
        self._gdml_actors.clear()
        self._original_colors.clear()

        self._scene.build_from_tree(root_node, render_all_volumes=render_all_volumes)
        self._ensure_default_actors()

        # After build, recollect GDML actors and update cube axes bounds
        self._collect_gdml_actors()
        self._update_cube_axes_bounds()
        self._scene_built = True
        self.render()

    def set_override_provider(
            self,
            provider: Optional[Callable[[str], Optional['Placement']]]
    ):
        """Set placement override provider on the scene (forwarded from agent)."""
        if self._scene:
            self._scene.set_override_provider(provider)

    def _collect_gdml_actors(self):
        """Collect all GDML actors (non-default) for color/opacity management."""
        self._gdml_actors.clear()
        self._original_colors.clear()
        coll = self._scene.renderer.GetViewProps()
        idx = 0
        for i in range(coll.GetNumberOfItems()):
            prop = coll.GetItemAsObject(i)
            if isinstance(prop, vtkActor) and prop is not self._cube_axes:
                self._gdml_actors.append(prop)
                c = prop.GetProperty().GetColor()
                self._original_colors[idx] = (c[0], c[1], c[2])
                idx += 1

    def render(self) -> None:
        """Force an immediate render."""
        self._ensure_window_bound()
        try:
            self._vtk_interactor.GetRenderWindow().Render()
        except Exception:
            pass

    def _set_swap_control(self, val: int) -> None:
        """Enable/disable vsync (0=off, 1=on). No-op if backend lacks support."""
        try:
            self._vtk_interactor.GetRenderWindow().SetSwapControl(val)
        except Exception:
            pass

    def refresh(self) -> None:
        """Alias for render."""
        self.render()

    def set_dark_theme(self, is_dark: bool) -> None:
        """Switch background and toolbar between dark/light."""
        if not self._scene:
            return
        if is_dark:
            self._scene.set_background_color(0.12, 0.12, 0.18)
        else:
            self._scene.set_background_color(0.95, 0.95, 0.95)
        self._apply_toolbar_style(is_dark)
        self.render()

    def cleanup(self) -> None:
        """Clean up VTK resources."""
        try:
            self._vtk_interactor.TerminateApp()
        except Exception:
            pass
        try:
            self._vtk_interactor.GetRenderWindow().Finalize()
        except Exception:
            pass

    def renderWindow(self):
        """Get the underlying vtkRenderWindow (compatibility alias)."""
        return self._vtk_interactor.GetRenderWindow()

    # ── Toolbar actions (matching MeshViewer) ──

    def _toggle_transparency(self):
        """Toggle mesh transparency for all GDML actors."""
        if not self._gdml_actors:
            self._btn_transparency.setChecked(not self._btn_transparency.isChecked())
            return
        self._transparent = self._btn_transparency.isChecked()
        for a in self._gdml_actors:
            p = a.GetProperty()
            if self._transparent:
                p.SetOpacity(0.45)
                p.SetEdgeColor(0.5, 0.8, 0.9)
            else:
                p.SetOpacity(1.0)
                p.SetEdgeColor(0.1, 0.1, 0.1)
        self._btn_transparency.setText(
            "▣ Solid" if self._transparent else "▣ Transparency"
        )
        self.render()

    def _toggle_edges(self):
        """Toggle mesh edge visibility for all GDML actors."""
        if not self._gdml_actors:
            return
        self._show_edges = self._btn_edges.isChecked()
        for a in self._gdml_actors:
            a.GetProperty().SetEdgeVisibility(self._show_edges)
        self.render()

    def _toggle_clip_panel(self):
        """Show/hide clipping controls."""
        self._clip_active = self._btn_clip.isChecked()
        self._clip_panel.setVisible(self._clip_active)
        if self._clip_active:
            self._sync_clip_plane()
        else:
            self._remove_clip_planes()
        self.render()

    def _on_clip_changed(self):
        if self._clip_active:
            self._sync_clip_plane()

    def _iter_clip_mappers(self):
        """All mappers the clip plane must cut: every GDML actor's mapper plus
        whatever a subclass reports via `_extra_clip_mappers` (e.g. the
        trajectory polyline overlay lives outside _gdml_actors)."""
        for a in self._gdml_actors:
            m = a.GetMapper()
            if m is not None:
                yield m
        for m in self._extra_clip_mappers():
            if m is not None:
                yield m

    def _extra_clip_mappers(self):
        """Subclass hook: extra mappers the clip plane should also slice.

        The scalar-volume overlay is NOT covered here - a vtkVolumeMapper
        takes a clipping-plane collection through SetClippingPlanes, which is
        handled separately by `_volume_clip_mapper`.
        """
        return ()

    def _sync_clip_plane(self):
        b = self._clip_bounds
        if not b:
            return
        axis = self._clip_axis_cb.currentIndex()
        lo, hi = b[axis * 2], b[axis * 2 + 1]
        t = self._clip_slider.value() / 1000.0
        pos = lo + t * (hi - lo)
        self._clip_label.setText(f"{pos:.2f}")

        normal = [0.0, 0.0, 0.0]
        normal[axis] = 1.0
        origin = [0.0, 0.0, 0.0]
        origin[axis] = pos
        self._clip_plane.SetOrigin(origin)
        self._clip_plane.SetNormal(normal)

        # Mappers are shared between instances with identical geometry:
        # deduplicate by mapper so the same clipping plane is not added tens
        # of thousands of times (otherwise dragging the clip slider stutters
        # on large scenes).
        # Dedup on the underlying C++ address, NOT on id(m): VTK python does
        # not guarantee one pooled wrapper per C++ mapper, so a transient
        # wrapper may be GC'd and its id() recycled mid-loop, which falsely
        # marks distinct mappers as "already seen" and leaves them without
        # the clip plane.
        seen: set = set()
        for m in self._iter_clip_mappers():
            key = _mapper_addr(m)
            if key in seen:
                continue
            seen.add(key)
            m.RemoveAllClippingPlanes()
            m.AddClippingPlane(self._clip_plane)
        self._apply_volume_clip()
        self.render()

    def _remove_clip_planes(self):
        # Mappers are shared; remove the planes deduplicated by mapper
        # (address-keyed - see _sync_clip_plane for why id(m) is unsafe)
        seen: set = set()
        for m in self._iter_clip_mappers():
            key = _mapper_addr(m)
            if key in seen:
                continue
            seen.add(key)
            m.RemoveAllClippingPlanes()
        self._clear_volume_clip()
        self.render()

    # ── Volume overlay clipping ─────────────────────────────────────────────
    # A vtkVolume (voxel field) overlay must be cut by the same plane, else
    # Slice only trims the mesh and the scalar field stays intact. Subclasses
    # that AddVolume() a scalar field return its mapper here.

    def _volume_clip_mapper(self):
        """Mapper of the vtkVolume overlay, or None if the widget has none."""
        return None

    def _apply_volume_clip(self):
        vm = self._volume_clip_mapper()
        if vm is None:
            return
        planes = vtkPlaneCollection()
        planes.AddItem(self._clip_plane)
        vm.SetClippingPlanes(planes)

    def _clear_volume_clip(self):
        vm = self._volume_clip_mapper()
        if vm is None:
            return
        # Do NOT pass None here: SetClippingPlanes is overloaded
        # (vtkPlanes / vtkPlaneCollection) so None raises
        # "TypeError: ambiguous call". An empty collection clears it.
        vm.SetClippingPlanes(vtkPlaneCollection())

    def _clip_reset(self):
        b = self._clip_bounds
        if not b:
            return
        axis = self._clip_axis_cb.currentIndex()
        mid = (b[axis * 2] + b[axis * 2 + 1]) / 2
        rng = b[axis * 2 + 1] - b[axis * 2]
        val = int((mid - b[axis * 2]) / rng * 1000) if rng > 0 else 500
        self._clip_slider.setValue(val)

    def _toggle_projection(self):
        if not self._scene:
            return
        self._is_ortho = self._btn_proj.isChecked()
        cam = self._scene.renderer.GetActiveCamera()
        cam.SetParallelProjection(self._is_ortho)
        self._btn_proj.setText("◻ Ortho" if self._is_ortho else "◻ Perspective")
        self.render()

    def _fit_all(self):
        if self._scene:
            self._scene.renderer.ResetCamera()
            cam = self._scene.renderer.GetActiveCamera()
            cam.Dolly(1.2)
            self._scene.renderer.ResetCameraClippingRange()
            self.render()

    def _set_axis_view(self, axis: int):
        if not self._scene or not self._clip_bounds:
            return
        b = self._clip_bounds
        cx = (b[0] + b[1]) / 2
        cy = (b[2] + b[3]) / 2
        cz = (b[4] + b[5]) / 2
        diag = max(b[1] - b[0], b[3] - b[2], b[5] - b[4]) * 2.0

        cam = self._scene.renderer.GetActiveCamera()
        if not self._is_ortho:
            self._is_ortho = True
            cam.SetParallelProjection(True)
            self._btn_proj.setText("◻ Ortho")
            self._btn_proj.setChecked(True)

        if axis == 0:   # +X
            cam.SetPosition(cx + diag, cy, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
        elif axis == 1:  # +Y
            cam.SetPosition(cx, cy + diag, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
        else:            # +Z
            cam.SetPosition(cx, cy, cz + diag)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 1, 0)
        self._scene.renderer.ResetCameraClippingRange()
        self.render()


# ── VtkPreviewWidget (minimal, for solid preview) ──────────────────


class VtkPreviewWidget(VtkWidget):
    """Minimal VTK preview widget — no toolbar, no clip, just the scene + CubeAxes."""

    def _build_ui(self):
        """Build minimal layout: VTK viewport only (no toolbar)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._vtk_interactor = QVTKRenderWindowInteractor(self)
        layout.addWidget(self._vtk_interactor, 1)

    def _toggle_transparency(self):
        pass

    def _toggle_edges(self):
        pass

    def _toggle_clip_panel(self):
        pass

    def _toggle_projection(self):
        pass

    def _fit_all(self):
        if self._scene:
            self._scene.renderer.ResetCamera()
            self._scene.renderer.ResetCameraClippingRange()
            self.render()

    def set_dark_theme(self, is_dark: bool) -> None:
        if not self._scene:
            return
        if is_dark:
            self._scene.set_background_color(0.12, 0.12, 0.18)
        else:
            self._scene.set_background_color(0.95, 0.95, 0.95)
        self.render()
