"""
ProbeDialog - probe analysis configuration (form on the left, 3D preview on
the right)

UI per user feedback:
  - The dialog (themed UI) is shown FIRST; the 3D geometry is rendered after
    that with an animated "Rendering geometry…" indicator, so opening the
    dialog on a large geometry never looks frozen.
  - Left column: probe chips at the top (Add / Delete to their right), then
    the form, one property per stacked line (mm):
      Name:      [ ...... ]
      Half-size: [ .... ] mm
      Material:  [ .... v ]
      Position:  x [ ] y [ ] z [ ]   mm
  - Right column: the 3D scene (VTK) only - the rendered geometry fills it.
  - The quantity list and the 1D histogram list belong to the probe selected
    in the chip bar (each probe has its own settings and chip state sync).
Non-modal dialog - the user can keep operating the main window while configuring.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListView, QSplitter, QLineEdit, QComboBox, QDoubleSpinBox,
    QWidget, QApplication, QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
import os
import time

from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkFiltersSources import vtkCubeSource

from ui.vtk_widget import VtkPreviewWidget
from ui.dialogs.analysis_common import (
    QuantityListPanel, HistogramListPanel, DIALOG_STYLE,
    quantity_meta, supports_histogram, MATERIAL_CHOICES,
    fit_size_to_screen,
)

PROBE_COLORS = [
    (0.9, 0.3, 0.3), (0.3, 0.7, 1.0), (0.3, 0.9, 0.4),
    (1.0, 0.7, 0.2), (0.8, 0.4, 1.0),
]


class ProbeDialog(QDialog):
    """probe analysis: multiple probes (position / half-size / material) +
    quantities + histograms."""

    CONFIG_KEY = "probe"

    # Measured minimum width (px) of one histogram row (Quantity combo + bins
    # + Range min/max + unit + log + ✕ ≈ 632-650 px, see HistogramRowWidget).
    # The form column is sized to this so "log" and "✕" are visible on open
    # without dragging the splitter; +36 px covers the vertical scroll bar
    # that appears once several histogram rows overflow the panel.
    _FORM_COL_DEFAULT_W = 688

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
        # Debounce the live UI updates (actor rebuild + render, chip text
        # refresh) while the user types in the form. Without it, every digit
        # typed into half-size / x / y / z triggers a synchronous VTK rebuild,
        # which stalls input on large scenes and makes typing feel broken.
        self._ui_timer = QTimer(self)
        self._ui_timer.setSingleShot(True)
        self._ui_timer.setInterval(150)
        self._ui_timer.timeout.connect(self._apply_form_changed)
        # The default size is applied after the UI is built (on first
        # activation the layout shrinks the window to its sizeHint, overriding
        # the resize done before build_ui) and forced once more when the
        # preview is created. The width leaves room for a form column that
        # fits a full histogram row (~668 px) plus a large 3D preview.
        self._default_size = (1360, 780)
        self._size_applied = False

        # Lazy 3D: build the scene only after the window is really mapped
        # (showEvent), so that building large GDML or rendering into an
        # unmapped window cannot stall the main window or emit warnings.
        self._preview_built = False
        self._closed = False
        self._refresh_probe_list()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._preview_built and self.isVisible():
            self._preview_built = True
            # Create the VTK widget only after the dialog is really mapped
            # (see _ensure_preview) - never during __init__/build_ui.
            QTimer.singleShot(0, self._ensure_preview)

    # -- Data --

    def _load_existing(self):
        cfg = (self._task.analysis_config or {}).get(self.CONFIG_KEY, {})
        self._probes = list(cfg.get("probes", [])) if cfg else []
        if not self._probes:
            self._probes = [{
                "name": "P1", "half": 50.0, "x": 0.0, "y": 0.0, "z": 0.0,
                "material": "none", "qs": [], "hs": [],
            }]

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(
            "Probe analysis: 3D read-only preview (rotate/zoom); probe parameters are entered in the form on the left,"
            "changes refresh live. Non-modal; adjust while interacting with the main window.")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self._split = split

        # ---- Left: form column ----
        form_col = QWidget()
        rv = QVBoxLayout(form_col)
        rv.setContentsMargins(0, 0, 4, 0)
        rv.setSpacing(6)

        # Probe chips at the top (mockup .pr-bar), above the Name field;
        # Add / Delete sit on the right of the chip list.
        probe_bar = QHBoxLayout()
        probe_bar.setSpacing(6)
        probe_bar.addWidget(QLabel("Probes:"))
        self._chip_list = QListWidget()
        self._chip_list.setFlow(QListView.Flow.LeftToRight)
        self._chip_list.setWrapping(True)
        self._chip_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._chip_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._chip_list.setFixedHeight(72)
        self._chip_list.currentRowChanged.connect(self._on_probe_selected)
        probe_bar.addWidget(self._chip_list, 1)
        add_btn = QPushButton("➕ Add probe")
        add_btn.clicked.connect(self._add_probe)
        probe_bar.addWidget(add_btn)
        del_btn = QPushButton("🗑 Delete probe")
        del_btn.clicked.connect(self._delete_probe)
        probe_bar.addWidget(del_btn)
        rv.addLayout(probe_bar)

        # Probe property form (mockup .col-form / .attr). Each property is on
        # its own row; every length is in mm.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("Name:"), 0, 0)
        self._name_edit = QLineEdit()
        self._name_edit.setFixedWidth(170)
        self._name_edit.textChanged.connect(self._on_form_changed)
        grid.addWidget(self._name_edit, 0, 1)

        grid.addWidget(QLabel("Half-size (mm):"), 1, 0)
        self._half_spin = QDoubleSpinBox()
        self._half_spin.setRange(0.1, 1e5)
        self._half_spin.setDecimals(2)
        self._half_spin.setValue(50.0)
        self._half_spin.setFixedWidth(110)
        self._half_spin.valueChanged.connect(self._on_form_changed)
        grid.addWidget(self._half_spin, 1, 1)

        grid.addWidget(QLabel("Material:"), 2, 0)
        self._mat_cb = QComboBox()
        self._mat_cb.addItems(MATERIAL_CHOICES)
        self._mat_cb.setFixedWidth(170)
        self._mat_cb.currentIndexChanged.connect(self._on_form_changed)
        grid.addWidget(self._mat_cb, 2, 1)

        # Position (single stacked line; x/y/z sub-fields)
        pos_hint = QLabel("Position (mm):")
        grid.addWidget(pos_hint, 3, 0)
        self._pos_spins = []
        pos_row = QWidget()
        ph = QHBoxLayout(pos_row)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(4)
        for axis in ("x", "y", "z"):
            ph.addWidget(QLabel(axis.upper()))
            s = QDoubleSpinBox()
            s.setRange(-1e6, 1e6)
            s.setDecimals(2)
            s.setValue(0.0)
            s.setFixedWidth(96)
            s.valueChanged.connect(self._on_form_changed)
            self._pos_spins.append(s)
            ph.addWidget(s)
        ph.addStretch()
        grid.addWidget(pos_row, 3, 1)
        rv.addLayout(grid)

        # Material override tip (mockup .ovTip): none -> geometry material
        self._mat_hint = QLabel("")
        self._mat_hint.setStyleSheet("color: #f0a94e; font-size: 11px;")
        self._mat_hint.setWordWrap(True)
        rv.addWidget(self._mat_hint)

        # Elastic quantity/histogram lists of the currently selected probe,
        # following the realworld-dialog stretch conventions (5 : 3).
        self._q_panel = QuantityListPanel(stretchable=True,
                                          scroll_min_height=150)
        self._q_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._q_panel, 5)

        self._h_panel = HistogramListPanel(stretchable=True,
                                           scroll_min_height=110)
        self._h_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._h_panel, 3)

        split.addWidget(form_col)

        # ---- Right: 3D rendering column (rendering only) ----
        scene_col = QWidget()
        lv = QVBoxLayout(scene_col)
        lv.setContentsMargins(4, 0, 0, 0)
        lv.setSpacing(6)

        # "Rendering geometry…" busy row (hidden by default; shown while the
        # large GDML scene is being built on the main thread)
        self._busy_widget = QWidget()
        bw = QHBoxLayout(self._busy_widget)
        bw.setContentsMargins(0, 0, 0, 0)
        bw.setSpacing(8)
        self._busy_lbl = QLabel("Rendering geometry…")
        self._busy_lbl.setStyleSheet("font-weight: bold;")
        bw.addWidget(self._busy_lbl)
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)          # indeterminate
        self._busy_bar.setFixedHeight(12)
        bw.addWidget(self._busy_bar, 1)
        self._busy_widget.setVisible(False)
        lv.addWidget(self._busy_widget)

        # The 3D preview widget is intentionally NOT created here. The legacy
        # QVTKRenderWindowInteractor forces a native window the moment it is
        # constructed (winId() is called inside its __init__). Creating it
        # while the dialog is still unmapped makes Qt give the widget chain
        # stray top-level native windows that must be re-parented on first
        # show; on Windows that prints
        #   QWindowsWindow::setGeometry: Unable to set geometry ...
        # and, until that re-parent settles, Qt's idea of the dialog's global
        # position is wrong - which is what makes QComboBox popups appear
        # detached ("dropdown outside"). The widget is therefore created only
        # after the dialog is mapped and sized (see _ensure_preview).
        self._preview = None
        self._preview_host = scene_col     # parent widget of the preview
        self._lv = lv                      # layout the preview is inserted in
        self._preview_ph = QLabel("Initializing 3D view…")
        self._preview_ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_ph.setStyleSheet(
            "border: 1px dashed #888888; color: #888888; font-size: 12px;")
        self._preview_ph.setMinimumSize(280, 160)
        lv.addWidget(self._preview_ph, 1)

        split.addWidget(scene_col)
        # The form column defaults to _FORM_COL_DEFAULT_W so the histogram
        # rows (log / ✕ included) are fully visible without horizontal
        # scrolling; the 3D column keeps the remaining width. Finalised once
        # more in _ensure_preview, after the window is really sized.
        split.setSizes([self._FORM_COL_DEFAULT_W, 640])
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 5)
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

        # The form is edited heavily with the keyboard, so Enter must never
        # activate any button here (especially Save). Saving happens only via
        # an explicit mouse click on the Save button: no default button, and
        # no button reacts to Enter when focused either.
        for _btn in self.findChildren(QPushButton):
            _btn.setAutoDefault(False)

    # -- 3D preview (lazy) --

    def _set_rendering_busy(self, busy: bool, note: str = ""):
        """Show/hide the "Rendering geometry…" row that sits above the 3D
        preview in the right-hand column.

        The row appears immediately when the window is mapped, and the build
        is chunked through VtkScene's build-progress callback, so opening the
        dialog on a large geometry never looks frozen.
        """
        if not getattr(self, "_busy_widget", None):
            return
        self._busy_widget.setVisible(busy)
        self._busy_lbl.setText("Rendering geometry…" +
                               (f"  ({note})" if note else ""))
        if busy:
            self._busy_bar.setRange(0, 0)
            QApplication.processEvents()
        else:
            self._busy_bar.setRange(0, 1)
            self._busy_bar.setValue(1)

    def _ensure_preview(self):
        """Create the VTK preview now that the dialog is mapped + sized.

        Run once on the first show. The real widget replaces the placeholder
        added by _build_ui; it is constructed with its final parent already
        visible, so the interactor's native window is born inside the shown
        dialog (no stray top-level native window -> no re-parent on show ->
        no Windows geometry-clamp warnings / combo-popup misplacement).
        """
        if getattr(self, "_closed", False):
            return
        # The default size was deferred because on first activation the layout
        # shrinks the window to its sizeHint; apply it before laying out the
        # preview so the interactor never sees a transient geometry.
        if not getattr(self, "_size_applied", False):
            self._size_applied = True
            self.resize(*fit_size_to_screen(self, *self._default_size))
        # Give the form column its content-driven default width now that the
        # window has its final size; the 3D column takes all the rest.
        if hasattr(self, "_split"):
            left = self._FORM_COL_DEFAULT_W
            avail = self._split.width()
            self._split.setSizes(
                [left, max(300, avail - left - 8)])
        if os.environ.get("EASY2RAD_NO_VTK"):
            # Debug switch: keep the placeholder, never build a VTK widget
            self._preview_ph.setText(
                "VTK preview disabled (EASY2RAD_NO_VTK) - debugging")
            return
        if self._preview is not None:
            QTimer.singleShot(0, self._build_preview)
            return
        self._set_rendering_busy(True)
        self._preview = VtkPreviewWidget(self._preview_host)
        idx = self._lv.indexOf(self._preview_ph)
        self._lv.removeWidget(self._preview_ph)
        self._preview_ph.deleteLater()
        self._lv.insertWidget(idx, self._preview, 1)
        self._preview.show()
        self._preview.set_dark_theme(self._dark)
        QTimer.singleShot(0, self._build_preview)

    def _build_preview(self):
        if getattr(self, "_closed", False):
            return
        if self._preview is None:
            self._preview_built = True
            return
        self._set_rendering_busy(True)
        scene = self._preview.get_scene()
        throttle = {"last": 0.0}

        def on_progress(done: int):
            now = time.monotonic()
            if now - throttle["last"] >= 0.1:
                throttle["last"] = now
                self._busy_lbl.setText(
                    f"Rendering geometry…  ({done} nodes)")
                QApplication.processEvents()

        try:
            root = self._agent.get_root_node()
            if scene is not None:
                scene.set_build_progress_callback(on_progress)
            # Consistent with the main window: render World + physical
            # instances only, to avoid overlapping logical-volume definitions
            self._preview.build_scene(root, render_all_volumes=False)
            # Geometry is semi-transparent
            for i in range(scene.renderer.GetViewProps()
                           .GetNumberOfItems()):
                prop = scene.renderer.GetViewProps().GetItemAsObject(i)
                if isinstance(prop, vtkActor):
                    prop.GetProperty().SetOpacity(0.35)
            self._update_all_probe_actors()
        except Exception as e:
            print(f"[ProbeDialog] preview build failed: {e}")
        finally:
            if scene is not None:
                scene.set_build_progress_callback(None)
            self._set_rendering_busy(False)

    def _rebuild_probe_actor(self, idx: int):
        if idx < 0 or idx >= len(self._probes) or self._preview is None:
            return
        scene = self._preview.get_scene()
        old = self._probe_actors.pop(idx, None)
        if old:
            scene.renderer.RemoveActor(old)
        p = self._probes[idx]
        half = max(p.get("half", 50.0), 0.1)
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
        if self._preview is None:
            return
        # Clear every probe actor first: after delete the remaining probes
        # shift index, so rebuilding incrementally would leave stale actors
        # behind.
        scene = self._preview.get_scene()
        for a in self._probe_actors.values():
            scene.renderer.RemoveActor(a)
        self._probe_actors = {}
        for i in range(len(self._probes)):
            self._rebuild_probe_actor(i)
        scene.renderer.ResetCamera()
        self._preview.render()

    # -- Probe list sync --

    def _refresh_probe_list(self):
        self._chip_list.clear()
        for i in range(len(self._probes)):
            self._chip_list.addItem(self._chip_label(i))
            self._chip_list.item(i).setToolTip(self._probe_tooltip(i))
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
        # Fill the whole form atomically: populating the widgets one by one
        # fires per-field change -> rebuild/render cycles that briefly show the
        # previous probe at the new position. Blocking the signals during the
        # population keeps the switch clean; _on_probe_selected already saved
        # the previously selected probe before calling this method.
        widgets = (self._name_edit, self._half_spin, self._mat_cb,
                   *self._pos_spins, self._q_panel, self._h_panel)
        for w in widgets:
            w.blockSignals(True)
        try:
            self._name_edit.setText(p.get("name", f"P{idx+1}"))
            self._half_spin.setValue(p.get("half", 50.0))
            self._mat_cb.setCurrentText(p.get("material", "none"))
            for k, s in zip(("x", "y", "z"), self._pos_spins):
                s.setValue(p.get(k, 0.0))
            self._q_panel.set_quantities(p.get("qs", []))
            # Histogram targets must follow the quantities just loaded,
            # otherwise histogram rows would be dropped when no qname matched.
            self._sync_qnames()
            self._h_panel.set_histograms(p.get("hs", []))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._set_form_enabled(True)
        self._update_mat_hint(p.get("material", "none"))

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

    def _update_mat_hint(self, mat: str = None):
        """Material override tip (mockup .ovTip): 'none' means the geometry's
        own material is used for dose calculation."""
        if mat is None:
            mat = self._mat_cb.currentText()
        if mat == "none":
            self._mat_hint.setText(
                "Material override off - uses the geometry's own material.")
        else:
            self._mat_hint.setText(f"Material override: dose uses {mat}.")

    def _chip_label(self, idx: int) -> str:
        p = self._probes[idx]
        configured = bool(p.get("qs")) or bool(p.get("hs"))
        name = p.get("name") or f"P{idx+1}"
        half = p.get("half", 50.0)
        return (f"{'✓ ' if configured else ''}{name}  "
                f"h={half:.0f}mm  "
                f"({p.get('x',0):.0f},{p.get('y',0):.0f},{p.get('z',0):.0f})")

    def _on_form_changed(self, *args):
        if self._active_idx < 0:
            return
        # Debounced: applies ~150 ms after the last edit (see _ui_timer).
        self._ui_timer.start()

    def _on_config_changed(self):
        if self._active_idx < 0:
            return
        self._ui_timer.start()

    def _apply_form_changed(self):
        """Debounced live update: called shortly after the last form edit."""
        if self._active_idx < 0 or self._active_idx >= len(self._probes):
            return
        self._save_form()
        self._rebuild_probe_actor(self._active_idx)
        self._refresh_chip_text(self._active_idx)
        self._sync_qnames()
        self._update_mat_hint()

    def _probe_tooltip(self, idx: int) -> str:
        p = self._probes[idx]
        qs = p.get("qs", [])
        hs = p.get("hs", [])
        lines = [
            f"{p.get('name', f'P{idx+1}')}",
            f"half-size = {p.get('half', 50.0):g} mm",
            f"position = ({p.get('x',0):g}, {p.get('y',0):g}, "
            f"{p.get('z',0):g}) mm",
            f"material = {p.get('material', 'none')}",
        ]
        if qs:
            lines.append("quantities: " +
                         ", ".join(q.get("name", "?") for q in qs))
        if hs:
            lines.append("histograms: " +
                         ", ".join(str(h.get("q", "?")) for h in hs))
        return "\n".join(lines)

    def _refresh_chip_text(self, idx: int):
        if idx < 0 or idx >= self._chip_list.count():
            return
        self._chip_list.item(idx).setText(self._chip_label(idx))
        self._chip_list.item(idx).setToolTip(self._probe_tooltip(idx))

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
            "name": f"P{idx}", "half": 50.0, "x": 0.0, "y": 0.0, "z": 0.0,
            "material": "none", "qs": [], "hs": [],
        })
        new_idx = len(self._probes) - 1
        self._active_idx = new_idx
        # Rebuild the chips AND set the current row with signals blocked:
        # firing _on_probe_selected here would call _save_form() into
        # _probes[_active_idx], which is already the new probe -> its form
        # (the previously selected probe's values) would overwrite it.
        self._chip_list.blockSignals(True)
        try:
            self._refresh_probe_list()
            self._chip_list.setCurrentRow(new_idx)
        finally:
            self._chip_list.blockSignals(False)
        # Load the freshly-created empty probe into the form (all signals are
        # quiet inside _load_form, so no _save_form can run here).
        self._load_form(new_idx)
        self._sync_qnames()
        self._rebuild_probe_actor(new_idx)
        self._refresh_highlight()

    def _delete_probe(self):
        if self._active_idx < 0 or len(self._probes) <= 1:
            return
        self._probes.pop(self._active_idx)
        actor = self._probe_actors.pop(self._active_idx, None)
        if actor and self._preview is not None:
            self._preview.get_scene().renderer.RemoveActor(actor)
        self._active_idx = max(0, self._active_idx - 1)
        # Rebuild the chips AND set the current row with signals blocked:
        # _on_probe_selected would call _save_form() using the still-loaded
        # form (the deleted probe's values) and overwrite the neighbour probe.
        self._chip_list.blockSignals(True)
        try:
            self._refresh_probe_list()
            self._chip_list.setCurrentRow(self._active_idx)
        finally:
            self._chip_list.blockSignals(False)
        self._load_form(self._active_idx)
        self._sync_qnames()
        self._update_all_probe_actors()

    def _sync_qnames(self):
        qs = self._q_panel.get_quantities()
        usable = []
        units = {}
        for q in qs:
            if supports_histogram(q["type"]):
                usable.append(q["name"])
                _, hx = quantity_meta(q["type"])
                units[q["name"]] = hx or ""
        self._h_panel.set_qnames(usable, units)

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
        # Close as soon as saving is done (same as the realworld dialog)
        self.close()

    def closeEvent(self, event):
        self._closed = True
        self._save_form()
        super().closeEvent(event)
        # Closing destroys everything: Finalize the VTK render window, call
        # deleteLater, and tell the main window to drop the cache. The next
        # open builds from scratch. At most 2 VTK windows exist at a time
        # (main window + this dialog), which avoids the
        #   wglMakeCurrent failed / Could not create shader object
        # errors caused by the legacy QVTKRenderWindowInteractor leaving stale
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
        except Exception:
            pass
