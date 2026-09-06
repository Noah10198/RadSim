"""direction_preview - live 3D view of the GPS emission direction.

Opened from the Angular section of the particle-source dialog. It answers
"which way do the particles actually fly?" by drawing, in mm coordinates:
  - the source shape (orange wireframe) and sampled start points (yellow)
  - green arrows = the emission direction at those points, according to the
    GPS convention used by the dialog (theta=0 -> -Z default frame;
    Plane +cos -> +Z normal; Surface +cos -> outward surface normal)
  - a faint RGB axis triad through the source centre
  - the focus point (red) for /gps/ang/type focused

Unlike SourceGeoPreview this needs no imported GDML geometry: it renders only
the source + direction model. The window polls the dialog's live config on a
timer, so every parameter change is reflected in the 3D view immediately.
"""

import math

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer

from ui.vtk_widget import VtkWidget
from ui.dialogs import gps_source as gps
from ui.dialogs.source_geo_preview import (
    _actor_from_poly, _arrow, _arrow_dirs, _f, _polyline,
    _shape_overlay, _solid_sphere)

_XR = (1.0, 0.35, 0.35)
_YG = (0.35, 1.0, 0.35)
_ZB = (0.35, 0.45, 1.0)
_YELLOW = (1.0, 0.85, 0.2)
_GREEN = (0.45, 1.0, 0.5)
_RED = (1.0, 0.3, 0.3)


def _center(cfg):
    ps = cfg.get("position") or {}
    return (_f(ps, "cx"), _f(ps, "cy"), _f(ps, "cz"))


def _source_extent(cfg):
    """Rough source half-extent (mm) used to size arrows / axis triad."""
    ps = cfg.get("position") or {}
    r = _f(ps, "radius")
    hx, hy, hz = (_f(ps, k) for k in ("halfx", "halfy", "halfz"))
    ex = hx or r or 0.0
    ey = hy or r or 0.0
    ez = hz or r or 0.0
    if ps.get("type") == "Point":
        return 0.0
    if not (ex or ey or ez):
        ex = ey = ez = r or 30.0
    return math.sqrt(ex * ex + ey * ey + ez * ez)


def _mean_text(cfg) -> str:
    """Plain-language description of the current emission direction."""
    ps = cfg.get("position") or {}
    an = cfg.get("angular") or {}
    pt = ps.get("type", "Point")
    sh = ps.get("shape", "")
    t = an.get("type", "iso")
    surf = pt == "Surface" and sh in ("Sphere", "Ellipsoid", "Cylinder")
    if t == "iso":
        return ("Isotropic 4π: every solid angle is equally probable, there is "
                "no preferred direction (the arrows are only sample directions).")
    if t == "cos":
        if surf:
            return ("cos is measured from the local OUTWARD surface normal. "
                    "For a sphere the arrows therefore point away from the "
                    "centre, concentrated along the radius.")
        if pt == "Plane":
            return ("cos is measured from the plane normal; an unrotated "
                    "Plane faces +Z, so most momenta go toward +Z.")
        return ("cos is measured from the default reference θ=0 → −Z "
                "(momentum mostly along −Z).")
    if t == "planar":
        if pt in ("Point", "Volume"):
            return ("planar = all momenta along the reference axis θ=0 → −Z. "
                    "The solver macros override it with "
                    "/gps/direction 0 0 1 to get a +Z beam.")
        return ("planar = all momenta along the facing/reference direction "
                "of the source (see the green arrows).")
    if t in ("beam1d", "beam2d"):
        return ("A narrow beam: momenta form a Gaussian cone around the "
                "reference θ=0 → −Z; σ sets the cone width.")
    if t == "focused":
        fx, fy, fz = (_f(an, k) for k in ("fx", "fy", "fz"))
        return (f"Focused: momentum from every start point points toward the "
                f"focus (red dot) at ({fx:g}, {fy:g}, {fz:g}) mm.")
    return ""


def _angular_text(cfg) -> str:
    an = cfg.get("angular") or {}
    t = an.get("type", "iso")
    parts = [f"angular type: {t}"]
    for key, label, unit in gps.ANG_FIELDS.get(t, []):
        if key in an and an[key]:
            parts.append(f"{label}={an[key]:g}°" if unit == "deg"
                         else f"{label}={an[key]:g}{unit}")
    return "  ".join(parts)


class DirectionPreview(QWidget):
    """Standalone top-level window; VTK content must not sit under a QSS
    stylesheet (see SourceGeoPreview for the same constraint)."""

    def __init__(self, dialog, dark=False, parent=None):
        super().__init__(parent)
        self._dlg = dialog
        self._dark = bool(dark)
        self._closed = False
        self._first_cam = True
        self._last_sig = None
        self._cam_prev = None
        self._owned = []

        self.setWindowTitle("Emission Direction 3D Preview")
        self.resize(1080, 800)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._lbl_cfg = QLabel()
        self._lbl_cfg.setWordWrap(True)
        self._lbl_cfg.setContentsMargins(10, 6, 10, 2)
        lay.addWidget(self._lbl_cfg)

        self._lbl_mean = QLabel()
        self._lbl_mean.setWordWrap(True)
        self._lbl_mean.setContentsMargins(10, 0, 10, 2)
        lay.addWidget(self._lbl_mean)

        self._vtk_widget = VtkWidget(self)
        lay.addWidget(self._vtk_widget, 1)

        self._lbl_hint = QLabel(
            "Orange wireframe = source extent; yellow dots = sampled start "
            "points; green arrows = emission direction there; red dot = "
            "focus point. R/G/B triad through the source centre marks the "
            "X/Y/Z axes (θ=0 → −Z, an unrotated Plane faces +Z). "
            "LMB rotate / MMB pan / wheel zoom; X / Y / Z buttons give "
            "axis-aligned views.")
        self._lbl_hint.setContentsMargins(10, 4, 10, 6)
        self._lbl_hint.setWordWrap(True)
        lay.addWidget(self._lbl_hint)

        # VTK must start only after the window is shown (ui/vtk_widget.py)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._init_view)

    # ---------------- lifecycle ----------------

    def _init_view(self):
        try:
            self._tick()
        except Exception:
            pass
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(300)

    def _own(self, ren, actor):
        self._owned.append(actor)
        ren.AddActor(actor)

    def closeEvent(self, event):
        self._closed = True
        try:
            if getattr(self, "_timer", None) is not None:
                self._timer.stop()
        except Exception:
            pass
        try:
            self._vtk_widget.cleanup()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- live refresh ----------------

    def _tick(self):
        if self._closed:
            return
        try:
            cfg = self._dlg._collect()
        except RuntimeError:
            self._closed = True
            return
        sig = repr(sorted((k, v) for k, v in cfg.items()))
        if sig == self._last_sig:
            return
        self._last_sig = sig
        try:
            self._rebuild(cfg)
        except Exception:
            # Stop polling on a persistent failure instead of spamming errors
            timer = getattr(self, "_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    def _rebuild(self, cfg):
        vtk = self._vtk_widget
        ren = vtk.get_scene().renderer
        for a in self._owned:
            try:
                ren.RemoveActor(a)
            except Exception:
                pass
        self._owned = []
        actors, marks = _shape_overlay(ren, cfg)
        self._owned += actors

        cx, cy, cz = _center(cfg)
        ext = _source_extent(cfg)
        triad = max(60.0, ext * 1.6)
        rad = max(1.2, triad * 0.035)
        ax_cols = (_XR, _YG, _ZB)
        for i, col in enumerate(ax_cols):
            p2 = [cx, cy, cz]
            p2[i] += triad
            p1 = [cx, cy, cz]
            p1[i] -= triad
            self._own(ren, _actor_from_poly(
                _polyline([(p1[0], p1[1], p1[2]),
                           (p2[0], p2[1], p2[2])]),
                col, width=1.4, opacity=0.55))

        for m in marks[:12]:
            self._own(ren, _solid_sphere(m, rad, _YELLOW))

        ln = max(rad * 7.0, triad * 0.35)
        for anchor, dirs in _arrow_dirs(cfg, marks):
            for d in dirs[:6]:
                self._own(ren, _arrow(anchor, d, ln, _GREEN, 2.2))

        an = cfg.get("angular") or {}
        if an.get("type") == "focused":
            fp = (_f(an, "fx"), _f(an, "fy"), _f(an, "fz"))
            self._own(ren, _solid_sphere(fp, rad * 1.7, _RED))

        vtk._ensure_default_actors()
        vtk._update_cube_axes_bounds()
        self._set_text(cfg)
        cam_key = (cx, cy, cz, triad)
        prev = self._cam_prev
        moved = (self._first_cam or prev is None
                 or math.hypot(cx - prev[0], cy - prev[1], cz - prev[2])
                 > (triad + prev[3]) * 0.5)
        self._cam_prev = cam_key
        if moved:
            ren.ResetCamera()
            ren.ResetCameraClippingRange()
            self._first_cam = False
        vtk.set_dark_theme(self._dark)
        vtk.render()

    def _set_text(self, cfg):
        ps = cfg.get("position") or {}
        pt = ps.get("type", "Point")
        sh = ps.get("shape", "")
        cx, cy, cz = _center(cfg)
        meta = (f"Source: {pt}" + (f" / {sh}" if sh else "")
                + f"   centre ({cx:g}, {cy:g}, {cz:g}) mm    "
                + _angular_text(cfg))
        self._lbl_cfg.setText(meta)
        self._lbl_mean.setText("Emission: " + _mean_text(cfg))