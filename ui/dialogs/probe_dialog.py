"""
ProbeDialog - probe analysis configuration (3D preview on the left, form on
the right)

Follows doc/probe_ui_design.md:
  The 3D view is read-only (rotate/zoom); probe position and size are entered
  in the form and every change refreshes the 3D view live.
Non-modal dialog - the user can keep operating the main window while configuring.
The 3D scene is built lazily (deferred with a QTimer) so that opening the
dialog does not freeze the main window.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QSplitter, QLineEdit, QComboBox, QDoubleSpinBox,
    QWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkFiltersSources import vtkCubeSource

from ui.vtk_widget import VtkPreviewWidget
from ui.dialogs.analysis_common import (
    QuantityListPanel, HistogramListPanel, DIALOG_STYLE,
    supports_histogram, MATERIAL_CHOICES,
)

PROBE_COLORS = [
    (0.9, 0.3, 0.3), (0.3, 0.7, 1.0), (0.3, 0.9, 0.4),
    (1.0, 0.7, 0.2), (0.8, 0.4, 1.0),
]


class ProbeDialog(QDialog):
    """probe analysis: multiple probes (position / half-size / material) +
    quantities + histograms."""

    CONFIG_KEY = "probe"

    # On close, notify the main window to drop the cache (synchronously) so
    # that reopening cannot reuse objects that were already finalized
    close_requested = pyqtSignal()

    def __init__(self, parent=None, task=None, gdml_agent=None):
        super().__init__(parent)
        self._task = task
        self._agent = gdml_agent
        self._dark = False
        self._probes: list = []
        self._active_idx = -1
        self._probe_actors = {}

        self.setWindowTitle("Probe Analysis Settings")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._load_existing()
        self._build_ui()
        self._apply_theme()
        # The default size is applied after the UI is built (on first
        # activation the layout shrinks the window to its sizeHint, overriding
        # the resize done before build_ui) and forced once more in showEvent.
        self._default_size = (1080, 680)
        self._size_applied = False

        # Lazy 3D: build the scene only after the window is really mapped
        # (showEvent), so that building large GDML or rendering into an
        # unmapped window cannot stall the main window or emit warnings.
        self._preview_built = False
        self._refresh_probe_list()

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
        self._probes = list(cfg.get("probes", [])) if cfg else []
        if not self._probes:
            self._probes = [{
                "name": "P1", "half": 5.0, "x": 0.0, "y": 0.0, "z": 0.0,
                "material": "none", "qs": [], "hs": [],
            }]

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(
            "Probe analysis: 3D read-only preview (rotate/zoom); probe parameters are entered in the form on the right,"
            "changes refresh live. Non-modal; adjust while interacting with the main window.")
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
        rv.setSpacing(6)

        chip_row = QHBoxLayout()
        self._chip_list = QListWidget()
        self._chip_list.setFixedHeight(90)
        self._chip_list.currentRowChanged.connect(self._on_probe_selected)
        chip_row.addWidget(self._chip_list, 1)
        rv.addLayout(chip_row)

        # Probe property form
        prop = QHBoxLayout()
        prop.setSpacing(6)
        prop.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setFixedWidth(70)
        self._name_edit.textChanged.connect(self._on_form_changed)
        prop.addWidget(self._name_edit)
        prop.addWidget(QLabel("Half-size:"))
        self._half_spin = QDoubleSpinBox()
        self._half_spin.setRange(0.01, 1e5)
        self._half_spin.setDecimals(2)
        self._half_spin.setValue(5.0)
        self._half_spin.valueChanged.connect(self._on_form_changed)
        prop.addWidget(self._half_spin)
        prop.addWidget(QLabel("Material:"))
        self._mat_cb = QComboBox()
        self._mat_cb.addItems(MATERIAL_CHOICES)
        self._mat_cb.currentIndexChanged.connect(self._on_form_changed)
        prop.addWidget(self._mat_cb)
        rv.addLayout(prop)

        pos = QHBoxLayout()
        pos.setSpacing(6)
        pos.addWidget(QLabel("Position:"))
        self._pos_spins = []
        for axis in ("x", "y", "z"):
            pos.addWidget(QLabel(axis.upper()))
            s = QDoubleSpinBox()
            s.setRange(-1e6, 1e6)
            s.setDecimals(2)
            s.setValue(0.0)
            s.valueChanged.connect(self._on_form_changed)
            self._pos_spins.append(s)
            pos.addWidget(s)
        rv.addLayout(pos)

        self._q_panel = QuantityListPanel()
        self._q_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._q_panel)

        self._h_panel = HistogramListPanel()
        self._h_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._h_panel)

        split.addWidget(right)
        split.setSizes([560, 520])
        # The 3D preview takes the stretch priority (keeps the form from
        # squeezing it away when the GDML is large)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        add_btn = QPushButton("➕ Add probe")
        add_btn.clicked.connect(self._add_probe)
        btns.addWidget(add_btn)
        del_btn = QPushButton("🗑 Delete probe")
        del_btn.clicked.connect(self._delete_probe)
        btns.addWidget(del_btn)
        btns.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        save_btn = QPushButton("✅ Save config")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    # -- 3D preview (lazy) --

    def _build_preview(self):
        try:
            root = self._agent.get_root_node()
            # Consistent with the main window: render World + physical
            # instances only, to avoid overlapping logical-volume definitions
            self._preview.build_scene(root, render_all_volumes=False)
            # Geometry is semi-transparent
            for i in range(self._preview.get_scene().renderer.GetViewProps()
                           .GetNumberOfItems()):
                prop = self._preview.get_scene().renderer.GetViewProps().GetItemAsObject(i)
                if isinstance(prop, vtkActor):
                    prop.GetProperty().SetOpacity(0.35)
            self._update_all_probe_actors()
        except Exception as e:
            print(f"[ProbeDialog] preview build failed: {e}")

    def _rebuild_probe_actor(self, idx: int):
        if idx < 0 or idx >= len(self._probes):
            return
        scene = self._preview.get_scene()
        old = self._probe_actors.pop(idx, None)
        if old:
            scene.renderer.RemoveActor(old)
        p = self._probes[idx]
        half = max(p.get("half", 5.0), 0.01)
        cube = vtkCubeSource()
        cube.SetXLength(half * 2)
        cube.SetYLength(half * 2)
        cube.SetZLength(half * 2)
        cube.Update()
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(cube.GetOutput())
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetRepresentationToWireframe()
        color = PROBE_COLORS[idx % len(PROBE_COLORS)]
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(3 if idx == self._active_idx else 2)
        actor.SetPosition(p.get("x", 0), p.get("y", 0), p.get("z", 0))
        scene.renderer.AddActor(actor)
        self._probe_actors[idx] = actor
        scene.renderer.ResetCameraClippingRange()
        self._preview.render()

    def _update_all_probe_actors(self):
        for i in range(len(self._probes)):
            self._rebuild_probe_actor(i)
        self._preview.get_scene().renderer.ResetCamera()
        self._preview.render()

    # -- Probe list sync --

    def _refresh_probe_list(self):
        self._chip_list.clear()
        for i, p in enumerate(self._probes):
            cfg = "·".join([q["name"] for q in p.get("qs", [])])
            label = f"{p.get('name', f'P{i+1}')}  "
            label += f"h={p.get('half', 5)} "
            label += f"({p.get('x',0)},{p.get('y',0)},{p.get('z',0)})"
            if cfg:
                label += f"  [{cfg}]"
            self._chip_list.addItem(label)
        if self._probes:
            self._chip_list.setCurrentRow(min(self._active_idx, len(self._probes) - 1)
                                          if self._active_idx >= 0 else 0)
        else:
            self._active_idx = -1
            self._set_form_enabled(False)

    def _on_probe_selected(self, row: int):
        if row < 0 or row >= len(self._probes):
            return
        self._save_form()
        self._active_idx = row
        self._load_form(row)
        self._refresh_highlight()
        self._sync_qnames()

    def _load_form(self, idx: int):
        p = self._probes[idx]
        self._name_edit.setText(p.get("name", f"P{idx+1}"))
        self._half_spin.setValue(p.get("half", 5.0))
        self._mat_cb.setCurrentText(p.get("material", "none"))
        for k, s in zip(("x", "y", "z"), self._pos_spins):
            s.setValue(p.get(k, 0.0))
        self._q_panel.set_quantities(p.get("qs", []))
        self._h_panel.set_histograms(p.get("hs", []))
        self._set_form_enabled(True)

    def _save_form(self):
        if self._active_idx < 0 or self._active_idx >= len(self._probes):
            return
        p = self._probes[self._active_idx]
        p["name"] = self._name_edit.text().strip() or f"P{self._active_idx+1}"
        p["half"] = self._half_spin.value()
        p["material"] = self._mat_cb.currentText()
        p["x"], p["y"], p["z"] = (s.value() for s in self._pos_spins)
        p["qs"] = self._q_panel.get_quantities()
        p["hs"] = self._h_panel.get_histograms()

    def _on_form_changed(self, *args):
        if self._active_idx < 0:
            return
        self._save_form()
        self._rebuild_probe_actor(self._active_idx)
        self._refresh_chip_text(self._active_idx)
        self._sync_qnames()

    def _on_config_changed(self):
        self._on_form_changed()

    def _refresh_chip_text(self, idx: int):
        if idx < 0 or idx >= self._chip_list.count():
            return
        p = self._probes[idx]
        cfg = "·".join([q["name"] for q in p.get("qs", [])])
        label = f"{p.get('name', f'P{idx+1}')}  h={p.get('half', 5)} "
        label += f"({p.get('x',0)},{p.get('y',0)},{p.get('z',0)})"
        if cfg:
            label += f"  [{cfg}]"
        self._chip_list.item(idx).setText(label)

    def _refresh_highlight(self):
        for i in range(len(self._probes)):
            actor = self._probe_actors.get(i)
            if actor:
                actor.GetProperty().SetLineWidth(
                    3 if i == self._active_idx else 2)

    def _set_form_enabled(self, enabled: bool):
        for w in (self._name_edit, self._half_spin, self._mat_cb,
                  *self._pos_spins):
            w.setEnabled(enabled)
        self._q_panel.setEnabled(enabled)
        self._h_panel.setEnabled(enabled)

    def _add_probe(self):
        self._save_form()
        idx = len(self._probes) + 1
        self._probes.append({
            "name": f"P{idx}", "half": 5.0, "x": 0.0, "y": 0.0, "z": 0.0,
            "material": "none", "qs": [], "hs": [],
        })
        self._active_idx = len(self._probes) - 1
        self._refresh_probe_list()
        self._rebuild_probe_actor(self._active_idx)
        self._chip_list.setCurrentRow(self._active_idx)

    def _delete_probe(self):
        if self._active_idx < 0 or len(self._probes) <= 1:
            return
        self._probes.pop(self._active_idx)
        actor = self._probe_actors.pop(self._active_idx, None)
        if actor:
            self._preview.get_scene().renderer.RemoveActor(actor)
        self._active_idx = max(0, self._active_idx - 1)
        self._refresh_probe_list()
        self._update_all_probe_actors()

    def _sync_qnames(self):
        qs = self._q_panel.get_quantities()
        usable = [q["name"] for q in qs if supports_histogram(q["type"])]
        self._h_panel.set_qnames(usable)

    # -- Save --

    def _save(self):
        self._save_form()
        if self._task is not None:
            cfg = self._task.analysis_config or {}
            cfg[self.CONFIG_KEY] = {"probes": self._probes}
            self._task.analysis_config = cfg
        configured = any(p.get("qs") or p.get("hs") for p in self._probes)
        parent = self.parent()
        from app.main_window import MainWindow
        if isinstance(parent, MainWindow):
            parent.on_analysis_saved(self._task.name, self.CONFIG_KEY,
                                     configured)

    def closeEvent(self, event):
        self._save_form()
        super().closeEvent(event)
        # Closing destroys everything: Finalize the VTK render window, call
        # deleteLater, and tell the main window to drop the cache. The next
        # open builds from scratch. At most 2 VTK windows exist at a time
        # (main window + this dialog), which avoids the
        #   wglMakeCurrent failed / Could not create shader object
        # errors caused by the legacy QVTKRenderWindowInteractor leaving stale
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
