"""VoxelResultViewer - non-modal 3D preview of one voxel quantity.

Shows the imported GDML geometry plus the interpolated, color-mapped scalar
field of one quantity (out_Box_<q>.csv) as a mostly-opaque volume (no per-voxel
boxes). The bottom toolbar mirrors the main-window VTK toolbar order
(Clip / Fit All / Ortho / X / Y / Z), with a field-opacity slider on the
right (default 90% = nearly solid). The corner orientation-axis marker sits in
the lower-right corner (same viewport / letter size as the trajectory viewer's
corner axes) and the colourbar occupies the upper-right corner.

CSV rows carry (iX, iY, iZ, value) with iZ varying fastest (Geant4 score
semantics). The physical grid is built from the voxel config center / half
(mm), the same convention the mac-builder run macros use, so the overlay sits
in the geometry's own coordinate frame (mm). The field is sampled on the cell
*boundary* lattice (nbin+1 points per axis at spacing 2h/n starting at
center-half, with the edge cell value copied onto both envelope faces) so the
coloured extent spans exactly center +/- half - no half-cell inset.
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QButtonGroup, QWidget,
)
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkColorTransferFunction, vtkVolume, vtkVolumeProperty,
)
from vtkmodules.vtkCommonDataModel import vtkImageData, vtkPiecewiseFunction
from vtkmodules.vtkCommonCore import vtkDoubleArray
from vtkmodules.vtkRenderingVolume import vtkFixedPointVolumeRayCastMapper
from vtkmodules.vtkRenderingAnnotation import (
    vtkScalarBarActor, vtkAxesActor,
)
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (axis captions)

try:
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
except ImportError:  # pragma: no cover
    from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from ui.vtk_widget import VtkWidget

_TYPE_UNITS = {  # colorbar unit fallback when the quantity carries none
    "energyDeposit": "MeV",
    "doseDeposit": "Gy",
    "trackLength": "cm",
    "hitCount": "count",
}


def _edge_boundary_lattice(values, nbin):
    """Resample per-cell data onto an exact-fill *boundary* lattice.

    Geant4 cell k on an axis of n cells occupies
    [center-half + k*s, center-half + (k+1)*s] with s = 2*half/n. Sampling at
    the n cell centres (origin = center-half + s/2) draws the volume only
    between the centres - a half-cell gap at every envelope face. Instead put
    one sample on every cell *boundary*: n+1 points at the same spacing s,
    starting at center-half, each holding the value of the cell immediately to
    its right (the rightmost point repeats the last cell's value). The image
    then spans exactly center +/- half, so the coloured extent fills the whole
    envelope with no inset and no overshoot.

    values: flat per-cell data, x fastest (vtk order), len nx*ny*nz.
    nbin:   (nx, ny, nz) cell counts.
    Returns flat boundary-lattice point data, x fastest, len (nx+1)*(ny+1)*(nz+1).
    """
    nx, ny, nz = nbin
    nx2, ny2, nz2 = nx + 1, ny + 1, nz + 1
    out = [0.0] * (nx2 * ny2 * nz2)
    for oz in range(nz2):
        src_z = nx * ny * min(oz, nz - 1)
        dst_z = nx2 * ny2 * oz
        for oy in range(ny2):
            src_row = src_z + nx * min(oy, ny - 1)
            dst_row = dst_z + nx2 * oy
            for ox in range(nx2):
                out[dst_row + ox] = values[src_row + min(ox, nx - 1)]
    return out


class VoxelFieldWidget(VtkWidget):
    """VtkWidget with a translucent scalar-volume overlay and a colorbar."""

    def __init__(self, parent=None):
        self._is_dark = True          # default VTK scene bg is dark
        self._volume = None
        self._colorbar = None
        self._image = None
        self._volume_mapper = None
        self._volume_prop = None
        self._field_range = None      # (vmin, vmax) of the scalar field
        self._unit = ""
        # Opacity in % of the *field volume*; 90 means alpha ~0.9 = nearly
        # opaque at the top of the colour ramp (the scale used by the bottom
        # toolbar slider, default 95%).
        self._opacity_pct = 95
        # Relative opacity shape (value fraction, alpha fraction). The alpha of
        # every point is scaled by _opacity_pct/100, so 90% keeps low field
        # values transparent while the hot core renders nearly solid.
        self._opacity_profile = ((0.00, 0.00), (0.02, 0.06), (0.12, 0.28),
                                 (0.40, 0.62), (1.00, 1.00))
        self._axes_marker = None
        self._axes_marker_ready = False
        super().__init__(parent)

    # ── UI: toolbar subset (Slice / Ortho / Fit / X/Y/Z) ───────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._vtk_interactor = QVTKRenderWindowInteractor(self)
        layout.addWidget(self._vtk_interactor, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        # Order follows the main-window toolbar subset (Clip, Fit, Ortho,
        # then the X / Y / Z axis views) - all contiguous from the left.
        self._btn_clip = QPushButton("Clip")
        self._btn_clip.setCheckable(True)
        self._btn_clip.setToolTip("Cut geometry to reveal the field inside")
        self._btn_clip.clicked.connect(self._toggle_clip_panel)
        toolbar.addWidget(self._btn_clip, 1)

        fit = QPushButton("Fit All")
        fit.setToolTip("Fit the whole scene")
        fit.clicked.connect(self._fit_all)
        toolbar.addWidget(fit, 1)

        self._btn_proj = QPushButton("Ortho")
        self._btn_proj.setCheckable(True)
        self._btn_proj.setToolTip("Toggle orthographic / perspective")
        self._btn_proj.clicked.connect(self._toggle_projection)
        toolbar.addWidget(self._btn_proj, 1)

        self._axis_group = QButtonGroup(self)
        self._axis_group.setExclusive(True)
        for label, axis in (("X", 0), ("Y", 1), ("Z", 2)):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(f"View from +{label} axis")
            btn.clicked.connect(lambda _c, a=axis: self._set_axis_view(a))
            toolbar.addWidget(btn, 1)
            self._axis_group.addButton(btn)

        # Taller buttons; the equal stretch factors above make the left block
        # grow with the window instead of hugging the left edge.
        for w in (self._btn_clip, fit, self._btn_proj,
                  *self._axis_group.buttons()):
            w.setMinimumHeight(30)

        # Field-volume opacity (right side): 100% = fully solid, 90% = the
        # default "nearly opaque" look the result window opens with. The
        # trailing spacer matches the six button weights so the buttons take
        # about half of the window width.
        toolbar.addStretch(6)
        op_label = QLabel("Opacity")
        toolbar.addWidget(op_label)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(10, 100)
        self._opacity_slider.setValue(self._opacity_pct)
        self._opacity_slider.setMinimumWidth(120)
        self._opacity_slider.setToolTip("Field volume opacity (higher = more solid)")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        toolbar.addWidget(self._opacity_slider)
        self._opacity_label = QLabel(f"{self._opacity_pct}%")
        self._opacity_label.setMinimumWidth(34)
        toolbar.addWidget(self._opacity_label)

        layout.addLayout(toolbar)

        # slice (clip) control panel - reuses the base clip machinery
        self._clip_panel = QWidget()
        clip_row = QHBoxLayout(self._clip_panel)
        clip_row.setContentsMargins(6, 2, 6, 2)
        clip_row.setSpacing(6)

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
        self._clip_label.setMinimumWidth(56)
        clip_row.addWidget(self._clip_label)

        reset = QPushButton("Reset")
        reset.clicked.connect(self._clip_reset)
        clip_row.addWidget(reset)

        self._clip_panel.setVisible(False)
        layout.addWidget(self._clip_panel)
        self._apply_toolbar_style(True)
        self._style_sliders()

    def _style_sliders(self):
        """Theme the Opacity / Clip sliders so they stay visible on the dark
        toolbar row (the base VtkWidget applies the same round-ball slider
        style automatically; this call keeps it in place right at build)."""
        dark = self._is_dark
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
        for s in (getattr(self, "_opacity_slider", None),
                  getattr(self, "_clip_slider", None)):
            if s is not None:
                s.setStyleSheet(ss)

    def set_geometry_ghost(self, on: bool = True, opacity: float = 0.14,
                           wireframe: bool = False):
        """Make the geometry a visual backdrop behind the colored field volume.

        wireframe=True draws only the mesh grid lines in one neutral colour (no
        filled faces, no per-material colours) - exactly the "纯网格线框" style.
        The plain ghost mode keeps faint translucent faces + light edge lines;
        off restores the solid surface rendering.
        """
        for a in self._gdml_actors:
            p = a.GetProperty()
            if on and wireframe:
                p.SetRepresentationToWireframe()
                p.SetColor(0.78, 0.82, 0.86)
                p.SetOpacity(1.0)
                # 2px: 1px hairline lines alias into scattered white dots while
                # rotating (MSAA is off); a slightly wider line rasterises to a
                # continuous stroke instead of breaking into points.
                p.SetLineWidth(2.0)
                p.SetAmbient(1.0)
                p.SetDiffuse(0.0)
                p.SetSpecular(0.0)
                p.SetEdgeVisibility(False)
            elif on:
                p.SetRepresentationToSurface()
                p.SetOpacity(opacity)
                p.SetEdgeVisibility(True)
                p.SetEdgeColor(0.75, 0.78, 0.82)
                p.SetAmbient(0.05)
                p.SetDiffuse(0.05)
            else:
                p.SetRepresentationToSurface()
                p.SetOpacity(1.0)
                p.SetEdgeVisibility(False)
                p.SetAmbient(0.20)
                p.SetDiffuse(0.75)
        self.render()

    # The Slice clip plane must also cut the voxel-field volume (see the base
    # VtkWidget volume-clip hooks).
    def _volume_clip_mapper(self):
        return getattr(self, "_volume_mapper", None)

    def clear_field(self):
        ren = self._scene.renderer if self._scene else None
        if ren is None:
            return
        if self._volume is not None:
            ren.RemoveVolume(self._volume)
            self._volume = None
        if self._colorbar is not None:
            ren.RemoveActor(self._colorbar)
            self._colorbar = None
        self._volume_mapper = None
        self._image = None

    def set_field(self, values, shape, origin, spacing,
                  vmin, vmax, title, unit=""):
        """Render values as an interpolated translucent volume.

        shape=(nx,ny,nz) = sample counts per axis (the exact-fill boundary
        lattice: nbin+1 per axis); origin = mm position of the first sample,
        i.e. the low corner of the envelope (center-half); spacing = mm per
        sample; vmin/vmax = colour range.
        """
        nx, ny, nz = (int(shape[0]), int(shape[1]), int(shape[2]))
        total = nx * ny * nz
        if total == 0:
            return
        self.clear_field()
        self._unit = unit or _TYPE_UNITS.get(title, "")

        img = vtkImageData()
        img.SetDimensions(nx, ny, nz)
        img.SetSpacing(float(spacing[0]), float(spacing[1]), float(spacing[2]))
        img.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
        arr = vtkDoubleArray()
        arr.SetNumberOfComponents(1)
        arr.SetNumberOfTuples(total)
        for k in range(min(total, len(values))):
            arr.SetValue(k, float(values[k]))
        img.GetPointData().SetScalars(arr)
        self._image = img

        if vmax <= vmin:
            vmax = vmin + 1.0

        ctf = vtkColorTransferFunction()
        stops = ((0.0, (0.10, 0.15, 0.70)),
                 (0.25, (0.10, 0.60, 0.90)),
                 (0.50, (0.10, 0.85, 0.55)),
                 (0.75, (0.95, 0.85, 0.15)),
                 (1.0, (0.90, 0.15, 0.10)))
        for frac, rgb in stops:
            ctf.AddRGBPoint(vmin + frac * (vmax - vmin), *rgb)

        mapper = vtkFixedPointVolumeRayCastMapper()
        mapper.SetInputData(img)
        prop = vtkVolumeProperty()
        prop.SetInterpolationTypeToLinear()
        prop.ShadeOff()
        prop.SetColor(ctf)
        self._volume_prop = prop
        self._field_range = (float(vmin), float(vmax))
        self._apply_field_opacity()
        avg = (abs(float(spacing[0])) + abs(float(spacing[1]))
               + abs(float(spacing[2]))) / 3.0
        if avg > 0:
            prop.SetScalarOpacityUnitDistance(avg)

        vol = vtkVolume()
        vol.SetMapper(mapper)
        vol.SetProperty(prop)
        self._scene.renderer.AddVolume(vol)
        self._volume = vol
        self._volume_mapper = mapper

        bar = vtkScalarBarActor()
        bar.SetLookupTable(ctf)
        bar.SetNumberOfLabels(6)
        bar.SetWidth(0.09)
        bar.SetHeight(0.42)
        # Upper right, clear of the lower-right corner axes (same layout the
        # trajectory viewer uses: colourbar top right, axes bottom right).
        bar.SetPosition(0.87, 0.52)
        label = title if not unit else f"{title}\n[{unit}]"
        bar.SetTitle(label)
        bar.SetLabelFormat("%.3g")
        bar.DrawTickLabelsOn()
        self._scene.renderer.AddActor(bar)
        self._colorbar = bar
        self._style_colorbar()

        self._refresh_bounds()
        if self._scene and self._scene.renderer:
            self._scene.renderer.ResetCamera()
        self.render()

    # ── bounds include the volume overlay ──
    def _refresh_bounds(self):
        ren = self._scene.renderer if self._scene else None
        if ren is None:
            return
        coll = ren.GetViewProps()
        b_all = [float('inf'), -float('inf')] * 3
        ok = False
        for i in range(coll.GetNumberOfItems()):
            prop = coll.GetItemAsObject(i)
            if prop is self._cube_axes:
                continue
            if not isinstance(prop, (vtkActor, vtkVolume)):
                continue
            b = prop.GetBounds()
            if not b:
                continue
            ok = True
            for k in range(6):
                if k % 2 == 0:
                    b_all[k] = min(b_all[k], b[k])
                else:
                    b_all[k] = max(b_all[k], b[k])
        if not (ok and all(abs(v) < 1e10 for v in b_all)):
            b_all = [-10, 10, -10, 10, -10, 10]
        else:
            for k in range(6):
                if b_all[k] in (float('inf'), -float('inf')):
                    b_all[k] = 0.0
        self._cube_axes.SetBounds(b_all)
        self._clip_bounds = b_all

    # ── field-volume opacity ──────────────────────────────────────────────
    def _on_opacity_changed(self, value: int):
        """Slider: % of the opacity ramp maximum (100 = fully solid)."""
        self._opacity_pct = value
        if self._opacity_label is not None:
            self._opacity_label.setText(f"{value}%")
        if self._volume_prop is not None and self._field_range is not None:
            self._apply_field_opacity()
            self.render()

    def _apply_field_opacity(self):
        """(Re)build the scalar-opacity function from the stored field range
        and the current slider %. 90% -> peak alpha 0.90: nearly opaque, so
        the volume reads as solid while weak tails stay transparent."""
        prop = self._volume_prop
        if prop is None or self._field_range is None:
            return
        vmin, vmax = self._field_range
        if vmax <= vmin:
            vmax = vmin + 1.0
        f = self._opacity_pct / 100.0
        pw = vtkPiecewiseFunction()
        for frac, shape in self._opacity_profile:
            alpha = max(0.0, min(1.0, shape * f))
            pw.AddPoint(vmin + frac * (vmax - vmin), alpha)
        prop.SetScalarOpacity(pw)

    # ── colorbar typography ───────────────────────────────────────────────
    def _style_colorbar(self):
        """Colourbar text: inverted against the renderer background, upright
        (no italics), about the size of the window text instead of VTK's
        larger default."""
        bar = self._colorbar
        if bar is None:
            return
        txt = (0.92, 0.92, 0.95) if self._is_dark else (0.10, 0.10, 0.14)
        for tp in (bar.GetLabelTextProperty(), bar.GetTitleTextProperty()):
            tp.SetColor(*txt)
            tp.SetShadow(0)
            tp.ItalicOff()
            tp.BoldOff()
        # Tick numbers: readable but still quieter than the title above them.
        bar.GetLabelTextProperty().SetFontSize(12)
        # Quantity name gets the emphasis via bold + one step larger. Kept
        # close to the trajectory colourbar so both viewers read consistently.
        bar.GetTitleTextProperty().SetFontSize(13)
        bar.GetTitleTextProperty().BoldOn()
        bar.SetVerticalTitleSeparation(14)
        # text on the bar, no extra box/frame around it
        bar.DrawFrameOff()
        bar.DrawBackgroundOff()

    # ── corner (orientation) axis marker, bottom-right ────────────────────
    # Size and position match the trajectory viewer's corner axes exactly:
    # viewport (0.76, 0.01, 1.0, 0.27) pinned to the lower-right corner with
    # 24 pt X / Y / Z captions, so both result windows read identically.
    def showEvent(self, event):
        super().showEvent(event)
        self._enable_axes_marker()

    def _enable_axes_marker(self):
        if getattr(self, "_axes_marker_ready", False):
            return
        self._axes_marker_ready = True
        try:
            ax = vtkAxesActor()
            ax.SetTotalLength(1.0, 1.0, 1.0)
            ax.SetAxisLabels(1)
            omw = vtkOrientationMarkerWidget()
            omw.SetOrientationMarker(ax)
            omw.SetInteractor(self.renderWindow().GetInteractor())
            # Lower-right corner - the same viewport the trajectory viewer
            # uses for its corner axes, so the two windows stay consistent.
            omw.SetViewport(0.76, 0.01, 1.0, 0.27)
            omw.SetEnabled(1)
            omw.InteractiveOff()
            self._axes_marker = omw
            self._update_axes_marker()
            self.render()
        except Exception:
            self._axes_marker_ready = False

    def _update_axes_marker(self):
        """Caption letters X / Y / Z are painted in the inverse of the scene
        background (white on the dark scene, near-black on the light one), at
        the same 24 pt size as the trajectory viewer's corner axes."""
        omw = getattr(self, "_axes_marker", None)
        if omw is None:
            return
        try:
            ax = omw.GetOrientationMarker()
            lab = (1.0, 1.0, 1.0) if self._is_dark else (0.08, 0.08, 0.12)
            for cap in (ax.GetXAxisCaptionActor2D(),
                        ax.GetYAxisCaptionActor2D(),
                        ax.GetZAxisCaptionActor2D()):
                tp = cap.GetCaptionTextProperty()
                tp.SetColor(*lab)
                tp.SetShadow(0)
                tp.ItalicOff()
                tp.SetFontSize(24)
        except Exception:
            pass

    def _disable_axes_marker(self):
        omw = getattr(self, "_axes_marker", None)
        if omw is not None:
            try:
                omw.EnabledOff()
            except Exception:
                pass

    def set_dark_theme(self, is_dark: bool):
        self._is_dark = is_dark
        super().set_dark_theme(is_dark)
        self._style_sliders()
        self._update_axes_marker()
        self._style_colorbar()
        self.render()


class VoxelResultViewer(QDialog):
    """Non-modal preview window for one voxel quantity."""

    def __init__(self, title: str, root_node, vcfg: dict, csv_path: str,
                 quantity: dict, dark: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 780)
        # Delete-on-close: the legacy QVTKRenderWindowInteractor owns a native
        # window + GL context. Keeping the hidden dialog cached (WA_DeleteOnClose
        # False) and re-showing it later hits a stale HWND/HDC and spams
        # "wglMakeCurrent failed" in vtkWin32OpenGLRenderWindow. Closing now
        # destroys the VTK window, so the next open builds a fresh one.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._dark = dark
        self._quantity = quantity or {}
        # Snapshot taken at load time; refresh_if_changed() uses it to detect
        # that the task was re-run and the CSV (and/or voxel config) changed.
        self._vcfg = vcfg
        self._csv_path = csv_path
        self._csv_stamp = self._file_stamp(csv_path)
        self._view = VoxelFieldWidget(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # 0 spacing so the path bar sits flush against the 3D area: with any
        # gap the plain (unthemed) QDialog background showed through as a
        # white horizontal band in dark mode.
        lay.setSpacing(0)
        self._status = QLabel("Loading voxel result ...")
        self._status.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(self._status)
        lay.addWidget(self._view, 1)
        self.set_dark_theme(dark)

        if root_node is not None:
            self._view.build_scene(root_node)
            self._view.set_geometry_ghost(True, wireframe=True)
        else:
            self._status.setText("No GDML geometry imported - field only.")

        ok = self._load_and_show_field(vcfg, csv_path)
        if not ok:
            self._status.setText(
                f"Could not read voxel output:\n{csv_path}\n\n"
                "Check that the file exists and matches the voxel config binning.")

    # ── refresh after a re-run ──
    @staticmethod
    def _file_stamp(path: str):
        """(mtime_ns, size) identity of a CSV. Re-runs are detected even when
        the file is rewritten inside the same filesystem timestamp tick."""
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def refresh_if_changed(self, vcfg: dict, csv_path: str) -> bool:
        """Reload the field in place when the CSV or the voxel config changed
        since this window was built.

        Re-running a task overwrites out_Box_*.csv in the same run directory,
        so a preview opened before the re-run would otherwise keep showing the
        previous run's field. Returns True when a reload actually happened.
        """
        if (csv_path == self._csv_path and vcfg == self._vcfg
                and self._file_stamp(csv_path) == self._csv_stamp):
            return False
        self._vcfg = vcfg
        self._csv_path = csv_path
        self._status.setText("Reloading voxel result ...")
        ok = self._load_and_show_field(vcfg, csv_path)
        if ok:
            self._csv_stamp = self._file_stamp(csv_path)
        else:
            self._status.setText(
                f"Could not read voxel output:\n{csv_path}\n\n"
                "Check that the file exists and matches the voxel config binning.")
        return ok

    # ── data loading ──
    def _load_and_show_field(self, vcfg: dict, csv_path: str) -> bool:
        try:
            half = [float(x) for x in vcfg.get("half", [])][:3]
            center = [float(x) for x in vcfg.get("center", [])][:3]
            nbin = [int(x) for x in vcfg.get("nbin", [])][:3]
        except (TypeError, ValueError):
            return False
        if len(half) != 3 or len(center) != 3 or len(nbin) != 3:
            return False
        if any(n <= 0 for n in nbin):
            return False
        nx, ny, nz = nbin

        # read csv rows (iX,iY,iZ,value[,val2,entry])
        vals = [0.0] * (nx * ny * nz)
        vmax = 0.0
        rows = 0
        try:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(",")
                    if len(parts) < 4:
                        continue
                    ix = int(parts[0].strip())
                    iy = int(parts[1].strip())
                    iz = int(parts[2].strip())
                    if not (0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz):
                        continue
                    v = float(parts[3].strip())
                    idx = ix + nx * (iy + ny * iz)  # x fastest (vtk order)
                    vals[idx] = v
                    if v > vmax:
                        vmax = v
                    rows += 1
        except (OSError, ValueError) as exc:
            self._status.setText(f"Read error: {exc}")
            return False
        if rows == 0:
            return False

        # Field grid = the exact-fill boundary lattice: one sample per cell
        # boundary, dims = nbin+1 per axis, origin = the envelope's low corner
        # (center-half). The coloured extent then covers center +/- half
        # exactly - no half-cell inset (cell-centre sampling) nor overshoot.
        spacing = [2.0 * half[i] / nbin[i] for i in range(3)]
        origin = [center[i] - half[i] for i in range(3)]
        grid = _edge_boundary_lattice(vals, nbin)
        grid_shape = [n + 1 for n in nbin]

        qtype = str(self._quantity.get("type") or "")
        self._view.set_field(
            grid, grid_shape, origin, spacing, 0.0, vmax,
            title=qtype or "quantity", unit=_TYPE_UNITS.get(qtype, ""))
        # Re-apply the clip plane to the just-created volume mapper if the
        # Slice tool is already active.
        if getattr(self._view, "_clip_active", False):
            self._view._sync_clip_plane()
        self._status.setText(
            f"{csv_path}  |  {nx} x {ny} x {nz} cells  |  max = {vmax:.4g}")
        return True

    # ── theme ──
    def set_dark_theme(self, dark: bool):
        self._dark = dark
        bg = "#1a1a24" if dark else "#f2f2f2"
        fg = "#e0e0e0" if dark else "#222222"
        line = "#33334a" if dark else "#c8c8d0"
        # Paint every not-covered strip of the dialog (toolbar row gaps,
        # edges) with the theme colour instead of the unthemed light default.
        # A palette (not a stylesheet) is used so Qt's style engine is never
        # activated over the native VTK child window (see vtk_view_window).
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self._status.setStyleSheet(
            f"background:{bg}; color:{fg}; font-size:12px;"
            f"border-bottom:1px solid {line};")
        if hasattr(self, "_view"):
            self._view.set_dark_theme(dark)
            self._view.set_geometry_ghost(True, wireframe=True)

    def closeEvent(self, event):
        # Release the orientation marker before the GL context is destroyed
        try:
            self._view._disable_axes_marker()
        except Exception:
            pass
        # Release the VTK GL context while the widget is still alive. If this
        # dialog outlives the main window (user closes the main window first)
        # and no cleanup runs, the legacy QVTKRenderWindowInteractor keeps a
        # render loop on a destroyed HDC and spams
        # "vtkWin32OpenGLRenderWindow: wglMakeCurrent failed".
        try:
            self._view.cleanup()
        except Exception:
            pass
        super().closeEvent(event)
