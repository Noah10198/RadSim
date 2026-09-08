"""
VoxelDialog - voxel analysis configuration (form on the left, 3D grid preview
on the right)

Follows doc/GUI_Design.md section 6:
  Type Box; extent all_geo / manual; nBin xyz; quantity (no energy spectrum).
Grid box: dark thick outer frame + subdivision lines thinned out by density
(to avoid a "black blob", see section 6.1).
Non-modal dialog - the user can keep operating the main window while
configuring; the 3D view is built lazily.
"""

import math
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox,
    QGroupBox, QGridLayout, QWidget, QComboBox,
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
    QuantityListPanel, DIALOG_STYLE, fit_size_to_screen,
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
        # Final default size: a left column sized to the widest quantity row
        # (or a reasonable minimum) plus a large 3D preview. Requested while
        # the dialog is still hidden so its native window is born at this size
        # (avoids a deferred resize, after the VTK preview appears, that makes
        # the window visibly grow to the right/bottom and briefly leaves the
        # newly exposed lower-right corner blank). Re-applied in showEvent
        # before the first paint in case the first layout activation overrides
        # it.
        self._default_size = (
            min(1600, max(1120, self._form_col_width() + 640)), 700)
        self._size_applied = False
        self.resize(*fit_size_to_screen(self, *self._default_size))

        # Lazy 3D: build the scene only after the window is really mapped
        # (showEvent)
        self._preview_built = False
        self._closed = False

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_size_applied", False) and self.isVisible():
            self._size_applied = True
            # Default width keeps a column sized to the widest quantity row
            # (or a reasonable minimum) plus a large 3D preview. Applied here,
            # before the first paint, so the dialog opens at its final size
            # instead of growing once the VTK preview is created.
            self._default_size = (
                min(1600, max(1120, self._form_col_width() + 640)), 700)
            self.resize(*fit_size_to_screen(self, *self._default_size))
            # Normalize the left column to its widest row already for the
            # first paint (same call the preview builder runs later).
            self._apply_form_width()
        if not self._preview_built and self.isVisible():
            self._preview_built = True
            # Create the VTK widget only after the dialog is really mapped
            # (see _ensure_preview) - never during __init__/build_ui.
            QTimer.singleShot(0, self._ensure_preview)

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
        self._split = split

        # ---- Left: form (extent mode / grid density / quantity) ----
        form = QWidget()
        fv = QVBoxLayout(form)
        fv.setContentsMargins(0, 0, 4, 0)
        fv.setSpacing(6)

        # Extent mode - three mutually exclusive options. Only one voxel box
        # is ever displayed; switching modes rebuilds it from scratch (the
        # previous actors are removed first, see _rebuild_mesh).
        mode_box = QGroupBox("Voxel extent")
        mv = QVBoxLayout(mode_box)
        mv.setSpacing(6)
        self._mode_group = QButtonGroup(self)

        self._radio_all = QRadioButton(
            "Enclose all geometry (auto bounding box, world excluded)")
        self._radio_all.toggled.connect(self._on_mode_changed)
        mv.addWidget(self._radio_all)

        self._radio_volume = QRadioButton(
            "Bounding box of a selected volume")
        self._radio_volume.toggled.connect(self._on_mode_changed)
        mv.addWidget(self._radio_volume)

        # Volume picker (visible only in volume mode)
        self._vol_row = QWidget()
        vr = QHBoxLayout(self._vol_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(6)
        vr.addSpacing(22)
        vr.addWidget(QLabel("Volume:"))
        self._vol_cb = QComboBox()
        self._vol_cb.currentIndexChanged.connect(self._on_volume_changed)
        vr.addWidget(self._vol_cb, 1)
        mv.addWidget(self._vol_row)

        self._radio_manual = QRadioButton(
            "Manual (type half-size and offset yourself)")
        self._radio_manual.toggled.connect(self._on_mode_changed)
        mv.addWidget(self._radio_manual)

        self._mode_group.addButton(self._radio_all)
        self._mode_group.addButton(self._radio_volume)
        self._mode_group.addButton(self._radio_manual)

        # Auto-extent summary (all_geo / volume mode)
        self._auto_label = QLabel("")
        self._auto_label.setWordWrap(True)
        self._auto_label.setStyleSheet("color: #888888; font-size: 11px;")
        mv.addWidget(self._auto_label)

        # Manual half-size / center inputs (only in manual mode)
        self._manual_widget = QWidget()
        mg = QGridLayout(self._manual_widget)
        mg.setSpacing(6)
        mg.addWidget(QLabel(""), 0, 0)
        for axis in range(3):
            mg.addWidget(QLabel(("X", "Y", "Z")[axis]), 0, axis + 1)
        mg.addWidget(QLabel("Half-size:"), 1, 0)
        self._half_spins = []
        for axis in range(3):
            s = QDoubleSpinBox()
            s.setRange(0.01, 1e5)
            s.setDecimals(2)
            s.setSuffix(" mm")
            s.setSingleStep(5.0)
            s.setValue(30.0)
            s.valueChanged.connect(self._schedule_rebuild)
            self._half_spins.append(s)
            mg.addWidget(s, 1, axis + 1)
        mg.addWidget(QLabel("Center:"), 2, 0)
        self._center_spins = []
        for axis in range(3):
            c = QDoubleSpinBox()
            c.setRange(-1e6, 1e6)
            c.setDecimals(2)
            c.setSuffix(" mm")
            c.setSingleStep(5.0)
            c.setValue(0.0)
            c.valueChanged.connect(self._schedule_rebuild)
            self._center_spins.append(c)
            mg.addWidget(c, 2, axis + 1)
        mv.addWidget(self._manual_widget)

        # nBin stays visible in every mode (the grid density is always needed)
        nb = QHBoxLayout()
        nb.setSpacing(6)
        nb.addWidget(QLabel("Cells per axis (nBin):"))
        self._nbin_spins = []
        for axis in range(3):
            n = QSpinBox()
            n.setRange(1, 512)
            n.setValue(10)
            n.valueChanged.connect(self._schedule_rebuild)
            self._nbin_spins.append(n)
            nb.addWidget(n)
            nb.addSpacing(4)
        nb.addStretch()
        mv.addLayout(nb)
        fv.addWidget(mode_box)

        self._density_label = QLabel("")
        self._density_label.setStyleSheet(
            "color: #888888; font-size: 11px;")
        fv.addWidget(self._density_label)

        # Elastic quantity list: it stretches with the left column so its
        # bottom edge lines up with the 3D preview on the right (no dead gap
        # under the rows). The empty remainder is transparent, so it does not
        # show as a separate "box" in either theme.
        self._q_panel = QuantityListPanel(stretchable=True,
                                          scroll_min_height=150)
        self._q_panel.changed.connect(self._apply_form_width)
        fv.addWidget(self._q_panel, 1)

        # Volume picker contents = logical volumes physically placed in world
        if self._agent is not None:
            names = self._agent.get_renderable_volume_names()
            if names:
                for nm in names:
                    self._vol_cb.addItem(nm, nm)
            else:
                self._vol_cb.addItem("— (no placed volumes) —", None)

        split.addWidget(form)

        # ---- Right: 3D preview column ----
        # The VTK widget is intentionally NOT created here: the legacy
        # QVTKRenderWindowInteractor forces a native window the moment it is
        # constructed (winId() inside its __init__). Doing that while the
        # dialog is still unmapped creates stray top-level native windows that
        # are re-parented on first show, which on Windows prints
        #   QWindowsWindow::setGeometry: Unable to set geometry ...
        # and misplaces the QComboBox popups. It is also important NOT to let
        # the preview become a direct child of the QSplitter while unmapped:
        # QSplitterLayout would auto-insert it as an extra pane and the split
        # would jump around once the placeholder is swapped. The widget is
        # therefore created only after the dialog is mapped and sized, and is
        # inserted into a plain QVBoxLayout (see _ensure_preview).
        self._preview = None
        self._preview_host = QWidget()
        pv = QVBoxLayout(self._preview_host)
        pv.setContentsMargins(4, 0, 0, 0)
        pv.setSpacing(0)
        self._preview_ph = QLabel("Initializing 3D view…")
        self._preview_ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_ph.setStyleSheet(
            "border: 1px dashed #888888; color: #888888; font-size: 12px;")
        self._preview_ph.setMinimumSize(280, 160)
        pv.addWidget(self._preview_ph, 1)
        self._pv_layout = pv
        split.addWidget(self._preview_host)

        # The 3D preview takes the stretch priority (keeps the form column at
        # its content-driven width and sends any extra window width to the
        # preview). The actual pane widths are set by _apply_form_width once
        # the quantity rows are known.
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        save_btn = QPushButton("✅ Save config")
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)
        # Enter must never trigger a button in this dialog (the forms are
        # typed with the keyboard); saving happens only via a mouse click.
        for _btn in self.findChildren(QPushButton):
            _btn.setAutoDefault(False)

        # Load an existing configuration
        for i in range(3):
            self._half_spins[i].setValue(self._cfg["half"][i])
            self._nbin_spins[i].setValue(self._cfg["nbin"][i])
            self._center_spins[i].setValue(self._cfg["center"][i])
        self._q_panel.set_quantities(self._cfg.get("qs", []))

        mode = self._cfg.get("mode", "all_geo")
        if mode == "volume":
            sel = self._cfg.get("selected", "") or ""
            idx = self._vol_cb.findData(sel) if sel else -1
            if idx >= 0:
                self._vol_cb.setCurrentIndex(idx)
            self._radio_volume.setChecked(True)
        elif mode == "manual":
            self._radio_manual.setChecked(True)
        else:
            self._radio_all.setChecked(True)
        self._update_density()
        # Size the left column to the widest quantity row that was just loaded
        # (real geometry widths are reapplied in _ensure_preview).
        self._apply_form_width()

    # -- Column widths / sizing --

    def _form_col_width(self) -> int:
        """Width the left column needs so the widest quantity row (name +
        type + unit + particle filter + ✕) is fully visible - no horizontal
        scroll bar. +38px reserves room for the vertical scroll bar that
        appears once several rows overflow the panel."""
        w = 0
        for row in self._q_panel._rows:
            w = max(w, row.sizeHint().width())
        return max(560, w + 38)

    def _apply_form_width(self):
        if not getattr(self, "_split", None):
            return  # splitter not built yet (early signal from panel rows)
        left = self._form_col_width()
        avail = self._split.width()
        if avail > 0:
            self._split.setSizes(
                [min(left, max(320, avail - 380)),
                 max(380, avail - left)])
        else:
            self._split.setSizes([left, left * 2])

    # -- Mode sync --

    def _mode(self) -> str:
        """all_geo | volume | manual"""
        if self._radio_manual.isChecked():
            return "manual"
        if self._radio_volume.isChecked():
            return "volume"
        return "all_geo"

    def _on_mode_changed(self):
        mode = self._mode()
        self._vol_row.setVisible(mode == "volume")
        self._manual_widget.setVisible(mode == "manual")
        self._auto_label.setVisible(mode != "manual")
        if mode == "all_geo":
            bbox = (self._agent.compute_scene_bbox()
                    if self._agent is not None else None)
            self._refresh_auto_bbox(bbox)
        elif mode == "volume":
            name = self._vol_cb.currentData() or ""
            bbox = (self._agent.compute_volume_bbox(name)
                    if name and self._agent is not None else None)
            self._refresh_auto_bbox(bbox, name)
        else:
            self._refresh_auto_bbox(None)
        self._schedule_rebuild()

    def _on_volume_changed(self):
        if self._mode() != "volume":
            return
        name = self._vol_cb.currentData() or ""
        bbox = (self._agent.compute_volume_bbox(name)
                if name and self._agent is not None else None)
        self._refresh_auto_bbox(bbox, name)
        self._schedule_rebuild()

    def _refresh_auto_bbox(self, bbox, name: str = ""):
        """Remember the derived box + refresh the summary line. The resolved
        half-size/center is what gets persisted, so the CSV (index-only) can
        later be mapped back to world coordinates even in auto modes."""
        self._auto_bbox = None
        if not bbox or all(abs(v) < 1e-9 for v in bbox):
            self._auto_label.setText(
                f"Volume “{name}” contributes no box." if name
                else "No placed geometry found yet.")
            return
        self._auto_bbox = bbox
        xmin, xmax, ymin, ymax, zmin, zmax = bbox
        self._derived_half = [max((xmax - xmin) / 2, 0.01),
                              max((ymax - ymin) / 2, 0.01),
                              max((zmax - zmin) / 2, 0.01)]
        self._derived_center = [(xmax + xmin) / 2,
                                (ymax + ymin) / 2,
                                (zmax + zmin) / 2]
        head = f"Volume “{name}”" if name else "All geometry"
        self._auto_label.setText(
            f"{head}: X [{xmin:.2f}, {xmax:.2f}]  "
            f"Y [{ymin:.2f}, {ymax:.2f}]  "
            f"Z [{zmin:.2f}, {zmax:.2f}] mm\n"
            f"Box: {(xmax - xmin):.2f} × {(ymax - ymin):.2f} × "
            f"{(zmax - zmin):.2f} mm")

    def _effective_box(self):
        """(half, center) currently driving the mesh/preview. In auto modes
        the derived box is used (manual inputs are hidden and irrelevant)."""
        if self._mode() != "manual" and getattr(self, "_derived_half", None):
            return (self._derived_half, self._derived_center)
        return ([s.value() for s in self._half_spins],
                [s.value() for s in self._center_spins])

    def _update_density(self):
        nx, ny, nz = (s.value() for s in self._nbin_spins)
        total = nx * ny * nz
        half, _ = self._effective_box()
        cell = (2 * half[0] / nx) * (2 * half[1] / ny) * (2 * half[2] / nz)
        dens = "sparse/moderate" if max(nx, ny, nz) <= 25 else \
               "medium" if max(nx, ny, nz) <= 50 else "dense (>50^3, watch Geant4 memory)"
        self._density_label.setText(
            f"total cells: {total:,}  per-cell: {cell:.4g} mm^3  density: {dens}")

    def _schedule_rebuild(self):
        self._update_density()
        self._rebuild_timer.start()

    # -- 3D preview --

    def _ensure_preview(self):
        """Create the VTK preview now that the dialog is mapped + sized.

        Run once on the first show. The real widget replaces the placeholder
        in the right-hand column and is constructed with its final parent
        already visible, so the interactor's native window is born inside the
        shown dialog (no stray top-level native window -> no re-parent on show
        -> no Windows geometry-clamp warnings / combo-popup misplacement).
        """
        if getattr(self, "_closed", False):
            return
        # The window size was fixed in showEvent (before the first paint); here
        # the left column is fitted to its widest quantity row and the preview
        # column receives all the remaining width.
        self._apply_form_width()
        if os.environ.get("EASY2RAD_NO_VTK"):
            # Debug switch: keep the placeholder, never build a VTK widget
            self._preview_ph.setText(
                "VTK preview disabled (EASY2RAD_NO_VTK) - debugging")
            return
        if self._preview is not None:
            QTimer.singleShot(0, self._build_preview)
            return
        idx = self._pv_layout.indexOf(self._preview_ph)
        self._preview = VtkPreviewWidget(self._preview_host)
        self._pv_layout.removeWidget(self._preview_ph)
        self._preview_ph.deleteLater()
        self._pv_layout.insertWidget(idx, self._preview, 1)
        self._preview.show()
        self._preview.set_dark_theme(self._dark)
        QTimer.singleShot(0, self._build_preview)

    def _build_preview(self):
        if getattr(self, "_closed", False):
            return
        if self._preview is None:
            self._preview_built = True
            return
        try:
            root = self._agent.get_root_node()
            # Consistent with the main window: render World + physical
            # instances only, to avoid overlapping logical-volume definitions
            self._preview.build_scene(root, render_all_volumes=False)
            # Geometry as a translucent solid - same look as the probe dialog,
            # only a bit more transparent (0.25 vs 0.35) so the volume
            # structure is readable while the voxel overlay stays the visual
            # focus. World is still a thin wireframe (factory default).
            from vtkmodules.vtkRenderingCore import vtkActor
            for i in range(self._preview.get_scene().renderer.GetViewProps()
                           .GetNumberOfItems()):
                prop = self._preview.get_scene().renderer.GetViewProps().GetItemAsObject(i)
                if isinstance(prop, vtkActor):
                    prop.GetProperty().SetOpacity(0.25)
            self._rebuild_mesh()
        except Exception as e:
            print(f"[VoxelDialog] preview build failed: {e}")

    def _subdiv_color(self):
        """Subdivision-line color: light in dark mode, dark in light mode, so
        the grid stays readable over the translucent geometry bodies."""
        return (0.78, 0.78, 0.82) if self._dark else (0.18, 0.18, 0.18)

    def _recolor_overlay(self):
        """Re-tint the voxel overlay when the theme flips."""
        if self._mesh_actor is not None and self._preview is not None:
            p = self._mesh_actor.GetProperty()
            p.SetColor(*self._subdiv_color())
            p.SetOpacity(0.8)
            self._preview.render()

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
        if self._preview is None:
            return
        scene = self._preview.get_scene()
        if scene is None:
            return
        # Modes are exclusive: first drop the whole previous overlay (the
        # subdivision actor AND the outer frame), then draw the current box.
        if self._mesh_actor:
            scene.renderer.RemoveActor(self._mesh_actor)
            self._mesh_actor = None
        if getattr(self, "_mesh_actor_frame", None):
            scene.renderer.RemoveActor(self._mesh_actor_frame)
            self._mesh_actor_frame = None

        half, center = self._effective_box()
        nbin = [s.value() for s in self._nbin_spins]

        poly = self._build_mesh_polydata(half, center, nbin)
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*self._subdiv_color())
        actor.GetProperty().SetOpacity(0.8)
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
        mode = self._mode()
        half, center = self._effective_box()
        # Persist the *resolved* box (half/center) and the mode/volume name.
        # The solver CSV only stores voxel indices — no coordinates — so this
        # snapshot is what later maps index -> world coordinate (see
        # doc/result_coupling_design.md §3.1). Lengths are stored in the same
        # unit the geometry is rendered in ("unit": mm).
        self._cfg = {
            "mode": mode,
            "half": list(half),
            "nbin": [s.value() for s in self._nbin_spins],
            "center": list(center),
            "selected": (self._vol_cb.currentData() or "")
                        if mode == "volume" else "",
            "qs": self._q_panel.get_quantities(),
            "unit": "mm",
            "bbox": list(self._auto_bbox)
                    if mode != "manual"
                    and getattr(self, "_auto_bbox", None) else None,
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
        # Close as soon as saving is done (same as the realworld dialog)
        self.close()

    def closeEvent(self, event):
        self._closed = True
        super().closeEvent(event)
        # Closing destroys everything: Finalize the VTK render window, call
        # deleteLater, and tell the main window to drop the cache. The next
        # open builds from scratch. At most 2 VTK windows exist at a time,
        # which avoids the wglMakeCurrent failed / shader compilation failures
        # caused by the legacy QVTKRenderWindowInteractor leaving stale
        # windows behind on hide under PyQt6.
        if self._preview is not None:
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
            self._recolor_overlay()
        except Exception:
            pass
