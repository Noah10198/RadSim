"""
VoxelDialog - voxel analysis configuration (3D grid preview on the left,
form on the right)

Follows doc/GUI_Design.md section 6:
  Type Box; extent all_geo / manual; nBin xyz; quantity (no energy spectrum).
Grid box: dark thick outer frame + subdivision lines thinned out by density
(to avoid a "black blob", see section 6.1).
Non-modal dialog - the user can keep operating the main window while
configuring; the 3D view is built lazily.
"""

import math

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox,
    QGroupBox, QGridLayout, QWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import (
    vtkPolyData, vtkCellArray, vtkLine,
)
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkFiltersSources import vtkCubeSource

from ui.vtk_widget import VtkPreviewWidget
from ui.dialogs.analysis_common import (
    QuantityListPanel, DIALOG_STYLE,
)


class VoxelDialog(QDialog):
    """voxel analysis: Box grid + quantity (no energy spectrum)."""

    # On close, notify the main window to drop the cache (synchronously) so
    # that reopening cannot reuse objects that were already finalized
    close_requested = pyqtSignal()

    CONFIG_KEY = "voxel"

    def __init__(self, parent=None, task=None, gdml_agent=None):
        super().__init__(parent)
        self._task = task
        self._agent = gdml_agent
        self._dark = False

        self.setWindowTitle("Voxel Analysis Settings")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._mesh_actor = None
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(120)
        self._rebuild_timer.timeout.connect(self._rebuild_mesh)

        self._load_existing()
        self._build_ui()
        self._apply_theme()
        # Same default size as the probe dialog, forced back after the first
        # show (on first activation the layout shrinks the window to its
        # sizeHint, overriding the resize done before build_ui)
        self._default_size = (1080, 680)
        self._size_applied = False

        # Lazy 3D: build the scene only after the window is really mapped
        # (showEvent)
        self._preview_built = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._preview_built and self.isVisible():
            self._preview_built = True
            QTimer.singleShot(0, self._build_preview)
        # Restore the default size after the first show (the window is mapped
        # now, so the layout will not shrink again)
        if not getattr(self, "_size_applied", False) and self.isVisible():
            self._size_applied = True
            QTimer.singleShot(
                0, lambda: self.resize(*self._default_size))

    # -- Data --

    def _load_existing(self):
        cfg = (self._task.analysis_config or {}).get(self.CONFIG_KEY, {})
        self._cfg = dict(cfg) if cfg else {
            "mode": "all_geo", "half": [30.0, 30.0, 30.0],
            "nbin": [10, 10, 10], "center": [0.0, 0.0, 0.0],
            "selected": "", "qs": [],
        }
        for k in ("half", "nbin", "center"):
            if k not in self._cfg:
                self._cfg[k] = [10.0, 10.0, 10.0] if k == "nbin" else \
                               ([30.0] * 3 if k == "half" else [0.0] * 3)
        if "qs" not in self._cfg:
            self._cfg["qs"] = []

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(
            "Voxel analysis: Box mesh preview (outer frame + subdivision lines thinned by density)."
            "Non-modal; you can adjust settings while interacting with the main window.")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # Left: 3D preview
        self._preview = VtkPreviewWidget()
        split.addWidget(self._preview)

        # Right: form
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(8)

        # Extent mode
        mode_box = QGroupBox("Range")
        mv = QVBoxLayout(mode_box)
        self._mode_group = QButtonGroup(self)
        self._radio_all = QRadioButton("Enclose all geometry (excluding the world volume)")
        self._radio_all.toggled.connect(self._on_mode_changed)
        self._radio_manual = QRadioButton("Manual (half-size + offset)")
        self._radio_manual.toggled.connect(self._on_mode_changed)
        self._mode_group.addButton(self._radio_all)
        self._mode_group.addButton(self._radio_manual)
        mv.addWidget(self._radio_all)
        mv.addWidget(self._radio_manual)
        rv.addWidget(mode_box)

        # Half-size / center / nBin
        grid = QGridLayout()
        grid.setSpacing(6)
        self._half_spins = []
        self._nbin_spins = []
        self._center_spins = []
        for axis, label in enumerate(("X", "Y", "Z")):
            grid.addWidget(QLabel(f"{label} half-size:"), 0, axis * 2)
            s = QDoubleSpinBox()
            s.setRange(0.01, 1e5)
            s.setDecimals(2)
            s.valueChanged.connect(self._schedule_rebuild)
            self._half_spins.append(s)
            grid.addWidget(s, 0, axis * 2 + 1)

            grid.addWidget(QLabel(f"{label} center:"), 1, axis * 2)
            c = QDoubleSpinBox()
            c.setRange(-1e6, 1e6)
            c.setDecimals(2)
            c.valueChanged.connect(self._schedule_rebuild)
            self._center_spins.append(c)
            grid.addWidget(c, 1, axis * 2 + 1)

            grid.addWidget(QLabel(f"{label} nBin:"), 2, axis * 2)
            n = QSpinBox()
            n.setRange(1, 512)
            n.valueChanged.connect(self._schedule_rebuild)
            self._nbin_spins.append(n)
            grid.addWidget(n, 2, axis * 2 + 1)
        rv.addLayout(grid)

        self._density_label = QLabel("")
        self._density_label.setStyleSheet(
            "color: #888888; font-size: 11px;")
        rv.addWidget(self._density_label)

        auto_btn = QPushButton("🔄 Recompute bounding box of all geometry")
        auto_btn.clicked.connect(self._apply_auto_bbox)
        rv.addWidget(auto_btn)

        self._q_panel = QuantityListPanel()
        rv.addWidget(self._q_panel, 1)

        split.addWidget(right)
        split.setSizes([560, 500])
        # The 3D preview takes the stretch priority (keeps the form from
        # squeezing it away)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        save_btn = QPushButton("✅ Save config")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

        # Load an existing configuration
        self._radio_all.setChecked(self._cfg.get("mode") != "manual")
        self._radio_manual.setChecked(self._cfg.get("mode") == "manual")
        for i in range(3):
            self._half_spins[i].setValue(self._cfg["half"][i])
            self._nbin_spins[i].setValue(self._cfg["nbin"][i])
            self._center_spins[i].setValue(self._cfg["center"][i])
        self._q_panel.set_quantities(self._cfg.get("qs", []))
        self._update_mode_controls()
        self._update_density()

    # -- Mode sync --

    def _on_mode_changed(self):
        self._update_mode_controls()
        if self._radio_all.isChecked():
            self._apply_auto_bbox()
        else:
            self._schedule_rebuild()

    def _update_mode_controls(self):
        manual = self._radio_manual.isChecked()
        for w in (*self._half_spins, *self._center_spins):
            w.setEnabled(manual)

    def _apply_auto_bbox(self):
        bbox = self._agent.compute_scene_bbox()
        if not bbox or all(abs(v) < 1e-9 for v in bbox):
            return
        xmin, xmax, ymin, ymax, zmin, zmax = bbox
        half = [(xmax - xmin) / 2, (ymax - ymin) / 2, (zmax - zmin) / 2]
        center = [(xmax + xmin) / 2, (ymax + ymin) / 2, (zmax + zmin) / 2]
        for i in range(3):
            self._half_spins[i].setValue(max(half[i], 0.01))
            self._center_spins[i].setValue(center[i])
        self._cfg["mode"] = "all_geo"
        self._schedule_rebuild()

    def _update_density(self):
        nx, ny, nz = (s.value() for s in self._nbin_spins)
        total = nx * ny * nz
        half = [s.value() for s in self._half_spins]
        cell = (2 * half[0] / nx) * (2 * half[1] / ny) * (2 * half[2] / nz)
        dens = "sparse/moderate" if max(nx, ny, nz) <= 25 else \
               "medium" if max(nx, ny, nz) <= 50 else "dense (>50^3, watch Geant4 memory)"
        self._density_label.setText(
            f"total cells: {total:,}  per-cell: {cell:.4g} cm^3  density: {dens}")

    def _schedule_rebuild(self):
        self._update_density()
        self._rebuild_timer.start()

    # -- 3D preview --

    def _build_preview(self):
        try:
            root = self._agent.get_root_node()
            # Consistent with the main window: render World + physical
            # instances only, to avoid overlapping logical-volume definitions
            self._preview.build_scene(root, render_all_volumes=False)
            # Geometry is displayed as a wireframe
            from vtkmodules.vtkRenderingCore import vtkActor
            for i in range(self._preview.get_scene().renderer.GetViewProps()
                           .GetNumberOfItems()):
                prop = self._preview.get_scene().renderer.GetViewProps().GetItemAsObject(i)
                if isinstance(prop, vtkActor):
                    prop.GetProperty().SetRepresentationToWireframe()
                    prop.GetProperty().SetOpacity(0.6)
            self._rebuild_mesh()
        except Exception as e:
            print(f"[VoxelDialog] preview build failed: {e}")

    def _build_mesh_polydata(self, half, center, nbin):
        """Outer frame + subdivision lines (thinned out by density); returns a
        vtkPolyData."""
        hx, hy, hz = half
        cx, cy, cz = center
        nx, ny, nz = nbin

        x0, x1 = cx - hx, cx + hx
        y0, y1 = cy - hy, cy + hy
        z0, z1 = cz - hz, cz + hz

        pts = vtkPoints()
        lines = vtkCellArray()

        def add_pt(x, y, z):
            return pts.InsertNextPoint(x, y, z)

        def add_line(a, b):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(a)
            lines.InsertCellPoint(b)

        # 12 edges of the outer frame
        corners = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        ids = [add_pt(*c) for c in corners]
        for e in ((0, 1), (1, 2), (2, 3), (3, 0),
                  (4, 5), (5, 6), (6, 7), (7, 4),
                  (0, 4), (1, 5), (2, 6), (3, 7)):
            add_line(ids[e[0]], ids[e[1]])

        # Thin out the subdivision lines: target at most 25 per axis
        step_x = max(1, math.ceil(nx / 25))
        step_y = max(1, math.ceil(ny / 25))
        step_z = max(1, math.ceil(nz / 25))

        # X direction (grid lines with fixed y,z)
        for iy in range(0, ny + 1, step_y):
            yy = y0 + (y1 - y0) * iy / ny
            for iz in range(0, nz + 1, step_z):
                zz = z0 + (z1 - z0) * iz / nz
                add_line(add_pt(x0, yy, zz), add_pt(x1, yy, zz))
        # Y direction
        for ix in range(0, nx + 1, step_x):
            xx = x0 + (x1 - x0) * ix / nx
            for iz in range(0, nz + 1, step_z):
                zz = z0 + (z1 - z0) * iz / nz
                add_line(add_pt(xx, y0, zz), add_pt(xx, y1, zz))
        # Z direction
        for ix in range(0, nx + 1, step_x):
            xx = x0 + (x1 - x0) * ix / nx
            for iy in range(0, ny + 1, step_y):
                yy = y0 + (y1 - y0) * iy / ny
                add_line(add_pt(xx, yy, z0), add_pt(xx, yy, z1))

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)
        return poly

    def _rebuild_mesh(self):
        scene = self._preview.get_scene()
        if scene is None:
            return
        if self._mesh_actor:
            scene.renderer.RemoveActor(self._mesh_actor)
            self._mesh_actor = None

        half = [s.value() for s in self._half_spins]
        center = [s.value() for s in self._center_spins]
        nbin = [s.value() for s in self._nbin_spins]

        poly = self._build_mesh_polydata(half, center, nbin)
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.1, 0.1, 0.1)   # subdivision lines in dark gray
        actor.GetProperty().SetOpacity(0.45)
        actor.GetProperty().SetLineWidth(1)
        scene.renderer.AddActor(actor)
        self._mesh_actor = actor

        # Thick outer-frame lines
        cube = vtkCubeSource()
        cube.SetXLength(half[0] * 2)
        cube.SetYLength(half[1] * 2)
        cube.SetZLength(half[2] * 2)
        cube.Update()
        cm = vtkPolyDataMapper()
        cm.SetInputData(cube.GetOutput())
        frame = vtkActor()
        frame.SetMapper(cm)
        frame.GetProperty().SetRepresentationToWireframe()
        frame.GetProperty().SetColor(0.0, 0.35, 0.7)
        frame.GetProperty().SetLineWidth(2.5)
        frame.SetPosition(center[0], center[1], center[2])
        scene.renderer.AddActor(frame)
        self._mesh_actor_frame = frame

        scene.renderer.ResetCameraClippingRange()
        self._preview.render()

    # -- Save --

    def _save(self):
        self._cfg = {
            "mode": "manual" if self._radio_manual.isChecked() else "all_geo",
            "half": [s.value() for s in self._half_spins],
            "nbin": [s.value() for s in self._nbin_spins],
            "center": [s.value() for s in self._center_spins],
            "selected": "",
            "qs": self._q_panel.get_quantities(),
        }
        if self._task is not None:
            cfg = self._task.analysis_config or {}
            cfg[self.CONFIG_KEY] = self._cfg
            self._task.analysis_config = cfg
        configured = bool(self._cfg["qs"])
        parent = self.parent()
        from app.main_window import MainWindow
        if isinstance(parent, MainWindow):
            parent.on_analysis_saved(self._task.name, self.CONFIG_KEY,
                                     configured)

    def closeEvent(self, event):
        super().closeEvent(event)
        # Closing destroys everything: Finalize the VTK render window, call
        # deleteLater, and tell the main window to drop the cache. The next
        # open builds from scratch. At most 2 VTK windows exist at a time,
        # which avoids the wglMakeCurrent failed / shader compilation failures
        # caused by the legacy QVTKRenderWindowInteractor leaving stale
        # windows behind on hide under PyQt6.
        try:
            self._preview.cleanup()
        except Exception:
            pass
        self.close_requested.emit()
        self.deleteLater()

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(DIALOG_STYLE(self._dark))
        try:
            self._preview.set_dark_theme(self._dark)
        except Exception:
            pass
