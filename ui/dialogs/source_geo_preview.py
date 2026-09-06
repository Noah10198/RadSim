"""source_geo_preview - 3D preview of the particle source against imported
geometry / World volume.

A standalone top-level VTK window (no QSS, see vtk_view_window.py):
  geometry is rendered as translucent solids, the World volume is emphasized
  as a cyan wireframe; the source is drawn as an orange wireframe (position
  shape) + yellow dots (starting points) + green arrows (emission direction
  sketch); an on-scene info bar lists World/geometry extents, the source
  center/extent and the inside-outside verdict.
Callers lazy-import this module only after a GDML file has been imported.
"""

import math

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer

from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkTextActor
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkCellArray
from vtkmodules.vtkFiltersSources import (
    vtkSphereSource, vtkCubeSource, vtkCylinderSource, vtkArrowSource)
from vtkmodules.vtkCommonTransforms import vtkTransform
import vtkmodules.vtkRenderingFreeType  # noqa: F401
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401

from ui.vtk_widget import VtkWidget
from ui.dialogs import particle_geo as pgeo

_ORANGE = (1.0, 0.52, 0.12)
_YELLOW = (1.0, 0.85, 0.2)
_GREEN = (0.45, 1.0, 0.5)
_CYAN = (0.2, 0.8, 1.0)


def _actor_from_poly(poly, color, width=2.0, opacity=1.0, wireframe=True):
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)
    act = vtkActor()
    act.SetMapper(mapper)
    prop = act.GetProperty()
    prop.SetColor(*color)
    prop.SetLineWidth(width)
    prop.SetOpacity(opacity)
    if wireframe:
        prop.SetRepresentationToWireframe()
    return act


def _polyline(pts3):
    poly = vtkPolyData()
    pts = vtkPoints()
    for x, y, z in pts3:
        pts.InsertNextPoint(float(x), float(y), float(z))
    lines = vtkCellArray()
    lines.InsertNextCell(len(pts3))
    for i in range(len(pts3)):
        lines.InsertCellPoint(i)
    poly.SetPoints(pts)
    poly.SetLines(lines)
    return poly


def _loop(radius, n=72):
    """Closed ring in the XY plane, centered at the origin."""
    return [(radius * math.cos(2 * math.pi * i / n),
             radius * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]


def _ps(cfg):
    return cfg.get("position") or {}


def _f(ps, k, d=0.0):
    try:
        return float(ps.get(k, d) or d)
    except (TypeError, ValueError):
        return d


def _unit(v):
    L = math.sqrt(sum(c * c for c in v))
    return (v[0] / L, v[1] / L, v[2] / L) if L > 1e-9 else (0.0, 0.0, 1.0)


def _spiral_surface(ax, by, cz, n=8):
    """Evenly distributed points on a sphere/ellipsoid (n points)."""
    out = []
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        phi = 2.39996323 * i
        out.append((ax * r * math.cos(phi), by * r * math.sin(phi), cz * y))
    return out


# ---------------- Position shape: wireframe actors + start-point dots ------

def _shape_overlay(ren, cfg):
    """Return (actors, anchor_points_mm); anchors is empty for unknown shapes."""
    ps = _ps(cfg)
    pt = ps.get("type", "Point")
    sh = ps.get("shape", "")
    cx, cy, cz = _f(ps, "cx"), _f(ps, "cy"), _f(ps, "cz")
    r = _f(ps, "radius")
    hx, hy, hz = _f(ps, "halfx"), _f(ps, "halfy"), _f(ps, "halfz")
    actors = []

    def add(poly, color=_ORANGE, width=2.0):
        a = _actor_from_poly(poly, color, width)
        ren.AddActor(a)
        actors.append(a)

    if pt == "Point" or not sh:
        return actors, [(cx, cy, cz)]

    if pt == "Plane":
        rings = []
        if sh in ("Circle", "Annulus"):
            ring = _loop(r or 20)
            rings.append([(px + cx, py + cy, cz) for px, py, _ in ring])
            if sh == "Annulus":
                ir = _f(ps, "inner_radius", r * 0.5)
                rings.append([(px + cx, py + cy, cz)
                              for px, py, _ in _loop(ir)])
        elif sh == "Ellipse":
            hx, hy = _f(ps, "halfx", 20), _f(ps, "halfy", 20)
            rings.append([(cx + hx * math.cos(2 * math.pi * i / 72),
                           cy + hy * math.sin(2 * math.pi * i / 72), cz)
                          for i in range(72)])
        else:  # Square / Rectangle / Para
            hx, hy = _f(ps, "halfx", 20), _f(ps, "halfy", 20)
            rings.append([(cx - hx, cy - hy, cz), (cx + hx, cy - hy, cz),
                          (cx + hx, cy + hy, cz), (cx - hx, cy + hy, cz)])
        for ring in rings:
            add(_polyline(ring))
        marks = [(cx, cy, cz)]
        if sh in ("Circle", "Annulus"):
            rr = r or 20
            for a in (0.0, math.pi / 2, math.pi, 1.5 * math.pi):
                marks.append((cx + 0.55 * rr * math.cos(a),
                              cy + 0.55 * rr * math.sin(a), cz))
        else:
            marks += [(cx - 0.5 * hx, cy - 0.5 * hy, cz),
                      (cx + 0.5 * hx, cy - 0.5 * hy, cz),
                      (cx + 0.5 * hx, cy + 0.5 * hy, cz),
                      (cx - 0.5 * hx, cy + 0.5 * hy, cz)]
        return actors, marks

    if sh == "Sphere":
        s = vtkSphereSource()
        s.SetRadius(r or 20)
        s.SetThetaResolution(26)
        s.SetPhiResolution(18)
        s.Update()
        a = _actor_from_poly(s.GetOutput(), _ORANGE, 1.8)
        t = vtkTransform()
        t.Translate(cx, cy, cz)
        a.SetUserTransform(t)
        ren.AddActor(a)
        actors.append(a)
        if pt == "Surface":
            marks = [(cx + mx, cy + my, cz + mz)
                     for mx, my, mz in _spiral_surface(r, r, r, 10)]
        else:
            marks = [(cx + mx, cy + my, cz + mz)
                     for mx, my, mz in _spiral_surface(
                         r * 0.55, r * 0.55, r * 0.55, 6)]
        return actors, marks
    if sh == "Ellipsoid":
        hx, hy, hz = hx or 20, hy or 20, hz or 20
        s = vtkSphereSource()
        s.SetRadius(1.0)
        s.SetThetaResolution(26)
        s.SetPhiResolution(18)
        s.Update()
        a = _actor_from_poly(s.GetOutput(), _ORANGE, 1.8)
        t = vtkTransform()
        t.Translate(cx, cy, cz)
        t.Scale(hx, hy, hz)
        a.SetUserTransform(t)
        ren.AddActor(a)
        actors.append(a)
        sc = 1.0 if pt == "Surface" else 0.55
        marks = [(cx + hx * sc * mx, cy + hy * sc * my, cz + hz * sc * mz)
                 for mx, my, mz in _spiral_surface(
                     1, 1, 1, 8 if pt == "Surface" else 6)]
        return actors, marks
    if sh == "Cylinder":
        s = vtkCylinderSource()
        s.SetRadius(r or 20)
        s.SetHeight(2 * (hz or 20))
        s.SetResolution(32)
        s.Update()
        a = _actor_from_poly(s.GetOutput(), _ORANGE, 1.8)
        t = vtkTransform()
        t.Translate(cx, cy, cz)
        a.SetUserTransform(t)
        ren.AddActor(a)
        actors.append(a)
        rr, hz = r or 20, hz or 20
        if pt == "Surface":
            marks = []
            for zz in (-hz, hz):
                for k in range(6):
                    a0 = 2 * math.pi * k / 6
                    marks.append((cx + rr * math.cos(a0),
                                  cy + rr * math.sin(a0), cz + zz))
        else:
            marks = [(cx, cy, cz), (cx, cy, cz + hz), (cx, cy, cz - hz)]
        return actors, marks
    if sh == "Para":
        hx, hy, hz = hx or 20, hy or 20, hz or 20
        s = vtkCubeSource()
        s.SetXLength(2 * hx)
        s.SetYLength(2 * hy)
        s.SetZLength(2 * hz)
        s.Update()
        a = _actor_from_poly(s.GetOutput(), _ORANGE, 1.8)
        t = vtkTransform()
        t.Translate(cx, cy, cz)
        a.SetUserTransform(t)
        ren.AddActor(a)
        actors.append(a)
        return actors, [(cx, cy, cz)]
    return actors, []


# ---------------- Emission direction (schematic) --------------------------

def _cone_dirs(axis, half_deg, n=5):
    axis = _unit(axis)
    if abs(axis[0]) < 0.9:
        o1 = _unit((0.0, 1.0, 0.0))
    else:
        o1 = _unit((0.0, 0.0, 1.0))
    o2 = _unit((axis[1] * o1[2] - axis[2] * o1[1],
                axis[2] * o1[0] - axis[0] * o1[2],
                axis[0] * o1[1] - axis[1] * o1[0]))
    h = math.radians(abs(half_deg))
    out = []
    for i in range(n):
        f = h * i / max(1, n - 1)
        ph = i * 2.399963
        v = [axis[k] * math.cos(f)
             + (o1[k] * math.cos(ph) + o2[k] * math.sin(ph)) * math.sin(f)
             for k in range(3)]
        out.append(_unit(v))
    return out


def _surface_normal(anchor, ps):
    """Outward normal of a Surface source at `anchor`
    (sphere/ellipsoid/cylinder approximation)."""
    sh = ps.get("shape", "")
    if sh not in ("Sphere", "Ellipsoid", "Cylinder"):
        return (0.0, 0.0, 1.0)
    cx, cy, cz = _f(ps, "cx"), _f(ps, "cy"), _f(ps, "cz")
    dx, dy, dz = anchor[0] - cx, anchor[1] - cy, anchor[2] - cz
    if sh == "Sphere":
        return _unit((dx, dy, dz))
    if sh == "Ellipsoid":
        hx, hy, hz = _f(ps, "halfx", 20), _f(ps, "halfy", 20), \
            _f(ps, "halfz", 20)
        return _unit((dx / (hx * hx), dy / (hy * hy), dz / (hz * hz)))
    if abs(dz) > 1e-6 and abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return _unit((0.0, 0.0, 1.0 if dz > 0 else -1.0))
    return _unit((dx, dy, 0.0))


def _arrow_dirs(cfg, anchors):
    """Emission directions per anchor point (schematic, not a statistical
    sampling)."""
    ps = _ps(cfg)
    an = cfg.get("angular") or {}
    t = an.get("type", "iso")
    pt = ps.get("type", "Point")
    out = []
    for a in anchors[:8]:
        if t == "iso":
            dirs = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                    (0, 0, 1), (0, 0, -1)]
        elif t == "cos":
            if pt == "Surface":
                axis = _surface_normal(a, ps)
            elif pt == "Plane":
                axis = (0.0, 0.0, 1.0)
            else:
                axis = (0.0, 0.0, -1.0)
            dirs = _cone_dirs(axis, 55, 5)
        elif t == "planar":
            dirs = _cone_dirs((0.0, 0.0, -1.0), 10, 3)
        elif t in ("beam1d", "beam2d"):
            sg = _f(an, "sigma_r", _f(an, "sigma_x", 1.0))
            dirs = _cone_dirs((0.0, 0.0, -1.0), min(28.0, abs(sg)), 4)
        elif t == "focused":
            dirs = [_unit((_f(an, "fx") - a[0],
                           _f(an, "fy") - a[1],
                           _f(an, "fz") - a[2]))]
        else:
            dirs = [(0.0, 0.0, -1.0)]
        if dirs:
            out.append((a, dirs))
    return out


def _solid_sphere(center, rad, color):
    s = vtkSphereSource()
    s.SetRadius(max(rad, 1e-6))
    s.SetThetaResolution(14)
    s.SetPhiResolution(10)
    s.Update()
    m = vtkPolyDataMapper()
    m.SetInputData(s.GetOutput())
    a = vtkActor()
    a.SetMapper(m)
    t = vtkTransform()
    t.Translate(*center)
    a.SetUserTransform(t)
    a.GetProperty().SetColor(*color)
    return a


def _arrow(center, d, ln, color, width=2.0):
    """An arrow of length `ln` starting at `center` pointing along `d`."""
    s = vtkArrowSource()
    s.SetTipLength(0.22)
    s.SetTipRadius(0.12)
    s.SetShaftRadius(0.035)
    s.Update()
    m = vtkPolyDataMapper()
    m.SetInputData(s.GetOutput())
    a = vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*color)
    p.SetSpecular(0.4)
    p.SetSpecularPower(20)
    d = _unit(d)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, d[0]))))
    t = vtkTransform()
    t.Translate(*center)
    if ang > 1e-3:
        # Rotate the default +X direction onto d
        cr = (0.0, -d[2], d[1])
        nl = math.sqrt(cr[1] ** 2 + cr[2] ** 2)
        if nl < 1e-9:  # d ~ +/- X
            if d[0] < 0:
                t.RotateWXYZ(180.0, 0.0, 1.0, 0.0)
        else:
            # vtklib has no 3-arg overload: axis must be given as x,y,z
            t.RotateWXYZ(ang, 0.0, cr[1] / nl, cr[2] / nl)
    t.Scale(ln, ln, ln)
    a.SetUserTransform(t)
    return a


def _text_actor(msg, color, x, y, size=15, bg=(0.05, 0.07, 0.1, 0.55)):
    a = vtkTextActor()
    a.SetInput(msg)
    a.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    a.SetPosition(x, y)
    tp = a.GetTextProperty()
    tp.SetColor(*color)
    tp.SetFontSize(size)
    tp.SetBackgroundColor(bg[0], bg[1], bg[2])
    tp.SetBackgroundOpacity(bg[3])
    return a


# ---------------- Preview window -----------------------------------------

def _fmt_axis(bb, i0, i1, tag):
    if not bb:
        return f"{tag} -"
    return f"{tag}[{bb[i0]:g},{bb[i1]:g}]"


def _shape_text(ps):
    ps = ps or {}
    bits = []
    for k, u in (("halfx", "x2"), ("halfy", "x2"), ("halfz", "x2"),
                 ("radius", ""), ("inner_radius", "")):
        v = ps.get(k)
        if v:
            bits.append(f"{k}={v:g}{u}")
    return " ".join(bits)


class SourceGeoPreview(QWidget):
    """Standalone top-level 3D preview: geometry + World + particle source
    (shape / start points / emission directions)."""

    def __init__(self, agent, cfg, dark=False, parent=None):
        super().__init__(parent)
        self._agent = agent
        self._cfg = cfg
        self._dark = bool(dark)

        self.setWindowTitle("Source vs Geometry / World Preview")
        self.resize(1240, 820)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint)
        # VTK compositing constraint: the window itself must not use QSS or a
        # custom-painted background
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._lbl_meta = QLabel()
        self._lbl_meta.setWordWrap(True)
        self._lbl_meta.setContentsMargins(10, 6, 10, 2)
        self._lbl_verdict = QLabel()
        self._lbl_verdict.setContentsMargins(10, 0, 10, 6)
        self._lbl_verdict.setWordWrap(True)
        lay.addWidget(self._lbl_meta)
        lay.addWidget(self._lbl_verdict)

        self._vtk_widget = VtkWidget(self)
        lay.addWidget(self._vtk_widget, 1)

        self._lbl_hint = QLabel(
            "Green arrows = emission direction (schematic); yellow dots = "
            "start points; orange wireframe = source extent. "
            "LMB rotate / MMB pan / wheel zoom; the toolbar switches view "
            "directions and perspective. A source outside the World volume "
            "is marked in red.")
        self._lbl_hint.setContentsMargins(10, 4, 10, 4)
        self._lbl_hint.setWordWrap(True)
        lay.addWidget(self._lbl_hint)

        # VTK: the interactor must be started after the window is shown,
        # otherwise the WId is invalid (see showEvent comments in
        # ui/vtk_widget.py); therefore build the scene one frame later.
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._start_build)

    def _start_build(self):
        try:
            self._build()
        except RuntimeError:
            pass  # the window was closed before the build ran

    # ---- helpers ----
    def _scene(self):
        return self._vtk_widget.get_scene()

    def _build(self):
        vtk = self._vtk_widget
        vtk.build_scene(self._agent.get_root_node(),
                        render_all_volumes=False)
        ren = self._scene().renderer

        # Translucent geometry so the source inside is visible
        for a in list(getattr(vtk, "_gdml_actors", [])):
            a.GetProperty().SetOpacity(0.55)
        # Emphasize the World container with a cyan wireframe
        for w in self._agent.get_world_nodes():
            act = self._scene().get_actor_for_node(getattr(w, "entry_id", ""))
            if act is None:
                continue
            act.GetProperty().SetRepresentationToWireframe()
            act.GetProperty().SetColor(*_CYAN)
            act.GetProperty().SetOpacity(0.95)
            act.GetProperty().SetLineWidth(2.0)

        self._add_source_overlay(ren)
        self._set_info_text()

        ren.ResetCamera()
        ren.ResetCameraClippingRange()
        vtk.set_dark_theme(self._dark)
        vtk.render()

    def _diag(self):
        wb = pgeo.world_bbox_mm(self._agent)
        if wb:
            d = max((wb[1] - wb[0]), (wb[3] - wb[2]), (wb[5] - wb[4]))
            return max(d, 1.0)
        gb = pgeo.geometry_bbox_mm(self._agent)
        if gb:
            return max((gb[1] - gb[0]), (gb[3] - gb[2]), (gb[5] - gb[4]))
        return 100.0

    def _add_source_overlay(self, ren):
        actors, marks = _shape_overlay(ren, self._cfg)
        self._overlay = actors
        diag = self._diag()
        rad = max(0.6, diag * 0.006)
        for m in marks[:12]:
            ren.AddActor(_solid_sphere(m, rad, _YELLOW))
        ln = max(rad * 5, diag * 0.12)
        for anchor, dirs in _arrow_dirs(self._cfg, marks):
            for d in dirs:
                ren.AddActor(_arrow(anchor, d, ln, _GREEN, 2.0))

    def _set_info_text(self):
        agent, cfg = self._agent, self._cfg
        ps = cfg.get("position") or {}
        names = [n.name for n in agent.get_all_file_nodes()]
        fname = names[0] if len(names) == 1 else \
            f"{len(names)} files: {', '.join(names[:3])}"
        wb = pgeo.world_bbox_mm(agent)
        gb = pgeo.geometry_bbox_mm(agent)
        meta = (
            f"GDML: {fname}\n"
            f"World: {_fmt_axis(wb, 0, 1, 'x')} "
            f"{_fmt_axis(wb, 2, 3, 'y')} {_fmt_axis(wb, 4, 5, 'z')} mm\n"
            f"Geometry extent: {pgeo.fmt_bbox(gb) or '-'}\n"
            f"Source: {ps.get('type', 'Point')} / {ps.get('shape', '-')} "
            f"{_shape_text(ps)} center {pgeo.source_center_text(ps)}")
        self._lbl_meta.setText(meta)
        res = pgeo.check_source_world(cfg, wb)
        color = {"inside": "#4caf50", "partial": "#f0a94e",
                 "outside": "#f0566c", "no_world": "#f0a94e"}.get(
                     res["status"], "#8a8d9a")
        self._lbl_verdict.setStyleSheet(
            f"color:{color};font-size:12px;font-weight:bold;")
        self._lbl_verdict.setText(
            f"World check: {res['msg']}   "
            f"Source extent {pgeo.fmt_bbox(res['src_aabb'])}")

    def closeEvent(self, event):
        try:
            self._vtk_widget.cleanup()
        except Exception:
            pass
        super().closeEvent(event)


def open_source_preview(agent, cfg, dark=False, parent=None):
    """Create and show the preview window (caller must keep the return value
    to avoid it being garbage-collected)."""
    return SourceGeoPreview(agent, cfg, dark=dark, parent=parent)
