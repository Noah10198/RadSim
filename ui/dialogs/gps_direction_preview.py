"""gps_direction_preview - live 3D sketch of a GeneralParticleSource.

Opened from the "3D Preview" button in the Particle Source dialog while the
GPS page is active. The window chrome is deliberately identical to the gun
preview (same translucent GDML context, same corner RGB axis marker, same
theme handling) - only the content differs, so the two views never look
"patched together".

What is drawn (all in world coordinates / mm):
  - the source position shape:
      * Point            -> a yellow dot
      * Plane Rectangle  -> a translucent "frosted-glass" pane whose size
        equals halfx/halfy, oriented in the true GPS frame: local x' = rot1,
        y' = rot2 minus its x'-component (so y' lies in the pane), and the
        pane normal z' = x' x y'. rot1/rot2 default to world X/Y (no tilt).
      * Surface Sphere   -> a translucent glass shell of the configured radius
        (rotation is invisible on a sphere, so the GPS form no longer offers
        rot1/rot2 for Surface sources and this view ignores them too)
  - a handful (never a swarm) of green emission arrows sampled on the source.
      * iso: arrows radiate within the configured theta/phi range of the
        angular frame (a default 4pi range fills the whole sphere); the arrow
        count shrinks with the covered solid angle, so narrow caps stay sparse.
      * cos: a symmetric lobe - one arrow along the emission axis plus four
        evenly spread around it.  GPS angles follow the manual convention
        (theta = 0 means travelling along -z', Eq. 2.1), so the lobe sits on
        the -z' side of the frame: a Point with default axes fills the -Z
        hemisphere, and its ang rot1/rot2 rows turn / flip the lobe
        (rot2 = (0,-1,0) sends it to +Z).
      * Plane / Surface: the emission frame comes from the position shape,
        not the angular rows.  A Plane flips its side-normal to point AWAY
        from the world origin first (G4SPSPosDistribution), so its cos lobe
        falls on the origin side of the pane; a Surface-Sphere puts z' on the
        outward radial of every point, so its cos lobe points INWARD toward
        the centre and its iso fan covers both hemispheres.
    Arrows are schematic - they show where and roughly how particles leave,
    not a statistical sampling.

The window polls the dialog's live GPS config on a timer, exactly like the gun
preview, so edits in the form show up immediately.
"""

import math
import traceback

from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkCellArray
from vtkmodules.vtkFiltersSources import vtkSphereSource
from vtkmodules.vtkCommonTransforms import vtkTransform

from ui.dialogs.gun_direction_preview import (
    GunDirectionPreview, _momentum_arrow, _solid_sphere_world, _bake)
from ui.dialogs.source_geo_preview import (
    _actor_from_poly, _polyline, _unit, _spiral_surface)

_GLASS = (0.62, 0.86, 1.0)      # frosted pane / shell tint
_GLASS_EDGE = (0.25, 0.75, 1.0)
_GREEN = (0.35, 1.0, 0.5)
_YELLOW = (1.0, 0.85, 0.2)
_GREY = (0.6, 0.6, 0.68)
_XR = (1.0, 0.4, 0.4)
_YG = (0.4, 1.0, 0.4)
_ZB = (0.45, 0.55, 1.0)


def _f(ps, key, default=0.0):
    try:
        return float(ps.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _vec(v, default=(1.0, 0.0, 0.0)):
    """Read a {'x','y','z'} vector stored in the config."""
    if not isinstance(v, dict):
        return default
    try:
        return (float(v.get("x", 0.0)), float(v.get("y", 0.0)),
                float(v.get("z", 0.0)))
    except (TypeError, ValueError):
        return default


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0])


def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _perp(u):
    """A unit vector perpendicular to u (robust for any orientation)."""
    if abs(u[0]) < 0.9:
        ref = (1.0, 0.0, 0.0)
    elif abs(u[1]) < 0.9:
        ref = (0.0, 1.0, 0.0)
    else:
        ref = (0.0, 0.0, 1.0)
    return _unit(_cross(u, ref))


def local_axes(rot):
    """GPS local frame from stored rot1/rot2 (manual Table 2.4 semantics):

    x' = unit(rot1)
    y' = unit(rot2 - (rot2.x')x')     (component of rot2 in the x'y' plane)
    z' = x' x y'

    Identity rot1/rot2 give the world frame (x',y',z') = (X,Y,Z), so "no
    rotation" is represented without any special-casing.  Returns
    (ux, uy, uz) as unit tuples."""
    r1 = _vec(rot.get("rot1") if isinstance(rot, dict) else None)
    r2 = _vec((rot.get("rot2") if isinstance(rot, dict) else None),
              default=(0.0, 1.0, 0.0))
    ux = _unit(r1)
    p2 = (r2[0] - _dot(r2, ux) * ux[0],
          r2[1] - _dot(r2, ux) * ux[1],
          r2[2] - _dot(r2, ux) * ux[2])
    uy = _unit(p2) if math.sqrt(_dot(p2, p2)) > 1e-9 else _perp(ux)
    uz = _unit(_cross(ux, uy))
    return ux, uy, uz


def _neg(v):
    return (-v[0], -v[1], -v[2])


def _sphere_dirs(n):
    """n unit directions spread evenly over the full sphere (4pi), used to
    sketch an isotropic source that radiates all around."""
    out = []
    ga = 2.3999632297286533            # golden angle (radians)
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        ph = i * ga
        out.append((r * math.cos(ph), y, r * math.sin(ph)))
    return out


def _iso_dirs(an, n_max=12):
    """Unit directions for the iso region of `an` (theta/phi ranges in deg).

    GPS iso samples theta about the angular +z' axis and phi around it, so a
    constrained range only covers a spherical cap/zone, not the whole sphere.
    Keep the sketch small: full 4pi -> n_max arrows, a narrow cap -> fewer
    (the count shrinks with the covered solid angle so the fan never gets
    denser than the full-sphere one).  A cap/zone sits on the **-z** side of
    the angular frame, matching G4SPSAngDistribution's momentum convention
    (theta = 0 -> -z).  Theta is walked in order (head-on rows first, grazing
    rows last) and each ring is split/offset in phi so arrows stay symmetric
    and never start on top of each other.
    """
    tm = _f(an, "theta_min", 0.0)
    tx = _f(an, "theta_max", 180.0)
    pm = _f(an, "phi_min", 0.0)
    px = _f(an, "phi_max", 360.0)
    t0, t1 = math.radians(min(tm, tx)), math.radians(max(tm, tx))
    p0, p1 = math.radians(min(pm, px)), math.radians(max(pm, px))
    t0 = min(max(t0, 0.0), math.pi)
    t1 = min(max(t1, 0.0), math.pi)
    p0 = min(max(p0, 0.0), math.tau)
    p1 = min(max(p1, 0.0), math.tau)
    full = (t0 < 1e-9 and t1 > math.pi - 1e-9
            and p0 < 1e-9 and p1 > math.tau - 1e-9)
    if full or t1 - t0 < 1e-9:
        return _sphere_dirs(n_max)
    # Arrow count follows the covered solid angle (never more than the
    # full-sphere one, so a narrow cap stays sparse and readable):
    # Omega/4pi = (dphi/2pi) * (cos t0 - cos t1) / 2.
    ratio = ((p1 - p0) * (math.cos(t0) - math.cos(t1))
             / (math.tau * 2.0))
    nmax = max(3, min(int(n_max), int(round(n_max * math.sqrt(ratio)))))
    # ring sizes: rows grow +2 per step; the pole arrow marks theta_min.
    ring, total, k = [], 1, 1
    while total < nmax:
        cnt = min(nmax - total, 2 * k)
        ring.append(cnt)
        total += cnt
        k += 1
    nr = len(ring)
    out = [(0.0, 0.0, 1.0)]
    for i, cnt in enumerate(ring):
        th = t0 + (t1 - t0) * (i + 1) / (nr + 1)
        st, ct = math.sin(th), math.cos(th)
        for j in range(cnt):
            ph = p0 + (p1 - p0) * (j + 0.5) / cnt
            out.append((st * math.cos(ph), st * math.sin(ph), ct))
    # G4SPSAngDistribution builds momenta as -(sinT cosP, sinT sinP, cosT):
    # theta = 0 means travelling along the angular frame's **-z** axis, so a
    # maxtheta cap is a cone toward -z (the convention the solver macros and
    # the cos lobe above already rely on).
    return [(-a[0], -a[1], -a[2]) for a in out]


def _is_frame_rotated(rot):
    """True when stored rot1/rot2 depart from the world frame.  The identity
    pair is never stored by the GUI, so their presence means a rotation."""
    if not isinstance(rot, dict):
        return False
    r1 = _vec(rot.get('rot1'))
    r2 = _vec(rot.get('rot2'), (0.0, 1.0, 0.0))
    return not (_unit(r1) == (1.0, 0.0, 0.0)
                and _unit(r2) == (0.0, 1.0, 0.0))


def _gps_emit_axis(ps, an):
    """Central axis of the GPS cos-lobe (schematic axis for the arrows).

    GPS samples its polar angle about the frame +z' axis but builds the
    momentum with the manual Eq. (2.1) convention, theta = 0 meaning the
    particle travels along -z', so the lobe is centred on **-z'** (verified
    in G4SPSAngDistribution.cc: a default Point or a Plane at the origin
    fires toward -Z in exgps).  Frame selection mirrors Geant4 v11.4:

      * explicit angular rotation -> angular frame z' (ang rot1 x rot2); the
        dialog's ang-rot rows can turn / flip the lobe (rot2 = (0,-1,0)
        sends a Point lobe to +Z);
      * Plane with no angular rotation -> the position side-normal, which
        G4SPSPosDistribution::GeneratePointsInPlane first turns AWAY from the
        world origin, so the lobe falls on the origin side of the pane;
      * otherwise (Point/Volume) -> the default angular frame, i.e. -Z.
    """
    if _is_frame_rotated(an):
        return _neg(local_axes(an)[2])
    if isinstance(ps, dict) and ps.get('type') == 'Plane':
        _ux, _uy, uz = local_axes(ps)
        cx, cy, cz = (_f(ps, 'cx'), _f(ps, 'cy'), _f(ps, 'cz'))
        if ((cx > 0.0 and uz[0] < 0.0) or (cx < 0.0 and uz[0] > 0.0)
                or (cy > 0.0 and uz[1] < 0.0) or (cy < 0.0 and uz[1] > 0.0)
                or (cz > 0.0 and uz[2] < 0.0) or (cz < 0.0 and uz[2] > 0.0)):
            uz = _neg(uz)
        return _neg(uz)
    return (0.0, 0.0, -1.0)


def _quad_polydata(p0, p1, p2, p3):
    """Two-triangle quad (filled pane) from four world-space corners."""
    poly = vtkPolyData()
    pts = vtkPoints()
    for p in (p0, p1, p2, p3):
        pts.InsertNextPoint(float(p[0]), float(p[1]), float(p[2]))
    poly.SetPoints(pts)
    cells = vtkCellArray()
    for a, b, c in ((0, 1, 2), (0, 2, 3)):
        cells.InsertNextCell(3)
        cells.InsertCellPoint(a)
        cells.InsertCellPoint(b)
        cells.InsertCellPoint(c)
    poly.SetPolys(cells)
    return poly


def _glass_quad_actor(corners):
    """Translucent frosted pane + a slim bright border around it."""
    poly = _quad_polydata(*corners)
    m = vtkPolyDataMapper()
    m.SetInputData(poly)
    a = vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*_GLASS)
    p.SetOpacity(0.30)
    p.SetAmbient(0.75)
    p.SetDiffuse(0.55)
    p.SetSpecular(0.35)
    p.SetSpecularPower(40)
    p.SetBackfaceCulling(False)
    edge = _actor_from_poly(_polyline(list(corners) + [corners[0]]),
                            _GLASS_EDGE, width=2.2, opacity=0.95)
    return [a, edge]


def _glass_shell_actor(center, radius):
    """Translucent sphere shell (Surface source), baked into world space."""
    s = vtkSphereSource()
    s.SetRadius(max(radius, 1e-6))
    s.SetThetaResolution(28)
    s.SetPhiResolution(18)
    s.Update()
    t = vtkTransform()
    t.Translate(*center)
    m = vtkPolyDataMapper()
    m.SetInputData(_bake(s, t))
    a = vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*_GLASS)
    p.SetOpacity(0.16)
    p.SetAmbient(0.8)
    p.SetDiffuse(0.6)
    p.SetSpecular(0.4)
    p.SetSpecularPower(40)
    p.SetBackfaceCulling(False)
    return a


def _cone(axis, half_deg, n):
    """n unit directions forming a narrow cone around `axis`.  The first and
    last directions straddle the axis so no two arrows share the same start
    vector (which would hide one behind the other)."""
    a = _unit(axis)
    o1 = _perp(a)
    o2 = _unit(_cross(a, o1))
    h = math.radians(abs(half_deg))
    out = []
    for i in range(n):
        f = h * (i / max(1, n - 1) - 0.5)
        ph = i * 2.399963
        out.append(_unit((a[0] * math.cos(f)
                          + (o1[0] * math.cos(ph) + o2[0] * math.sin(ph))
                          * math.sin(f),
                          a[1] * math.cos(f)
                          + (o1[1] * math.cos(ph) + o2[1] * math.sin(ph))
                          * math.sin(f),
                          a[2] * math.cos(f)
                          + (o1[2] * math.cos(ph) + o2[2] * math.sin(ph))
                          * math.sin(f))))
    return out


def _lobe_dirs(axis, tilt_deg=40.0, per=4):
    """Symmetric cos sketch: one arrow along `axis` plus `per` arrows evenly
    spread (per-fold symmetry, no two arrows stacked) around a small cone of
    half-angle `tilt_deg`.  Returns 1 + per unit directions, the axis one
    first."""
    a = _unit(axis)
    o1 = _perp(a)
    o2 = _unit(_cross(a, o1))
    h = math.radians(abs(tilt_deg))
    out = [a]
    for i in range(per):
        ph = i * math.tau / per
        c, s = math.cos(ph), math.sin(ph)
        out.append(_unit((a[0] * math.cos(h) + (o1[0] * c + o2[0] * s) * math.sin(h),
                         a[1] * math.cos(h) + (o1[1] * c + o2[1] * s) * math.sin(h),
                         a[2] * math.cos(h) + (o1[2] * c + o2[2] * s) * math.sin(h))))
    return out


def _iso_world_dirs(an, n_max=12):
    """iso arrows in world space for a Point source: the angular region from
    `an` (theta/phi in the angular frame) mapped through ang rot1/rot2 when a
    rotation is stored; an unrotated angular frame is the world frame."""
    local = _iso_dirs(an, n_max)
    if not _is_frame_rotated(an):
        return local
    ux, uy, uz = local_axes(an)
    out = []
    for d in local:
        out.append((d[0] * ux[0] + d[1] * uy[0] + d[2] * uz[0],
                    d[0] * ux[1] + d[1] * uy[1] + d[2] * uz[1],
                    d[0] * ux[2] + d[1] * uy[2] + d[2] * uz[2]))
    return out


def _rot_text(rot):
    """Short "rot1/rot2 applied" note for the info bar ("" when identity)."""
    if not isinstance(rot, dict):
        return ""
    r1 = _vec(rot.get("rot1"))
    r2 = _vec(rot.get("rot2"), (0.0, 1.0, 0.0))
    if (_unit(r1) == (1.0, 0.0, 0.0) and _unit(r2) == (0.0, 1.0, 0.0)):
        return ""
    return ("  rot1({0[0]:g},{0[1]:g},{0[2]:g}) "
            "rot2({1[0]:g},{1[1]:g},{1[2]:g})").format(r1, r2)


class GPSDirectionPreview(GunDirectionPreview):
    """GPS variant of the gun preview: same frame, GPS content.

    The window frame / chrome / geometry context / corner axes are inherited
    from GunDirectionPreview; only the live rebuild differs (see _tick and
    _rebuild_gps)."""

    def __init__(self, dialog, dark=False, parent=None):
        super().__init__(dialog, dark=dark, parent=parent)
        self.setWindowTitle("GeneralParticleSource 3D Preview")
        self._lbl_hint.setText(
            "Glass pane/shell = source position shape (pane size follows "
            "halfx/halfy, its tilt uses rot1/rot2; sphere = Surface, rot not "
            "offered there). Green arrows = emission directions (schematic, "
            "arrows only): iso fills its theta/phi range (a narrow cap "
            "shows fewer arrows); cos = one arrow along the emission axis "
            "plus four around it, on the -z' side of the angular frame "
            "(a Point defaults to -Z, facing its +Z axis). The ang rot1/rot2 "
            "rows re-aim / flip the lobe. "
            "LMB rotate / MMB pan / wheel zoom.")

    # --------------------------------------------------- live refresh ------

    def _tick(self):
        if self._closed:
            return
        try:
            cfg = self._dlg._collect()
        except RuntimeError:
            self._closed = True
            return
        if not cfg or cfg.get("mode") != "gps":
            return
        if self._maybe_build_geometry():
            self._last_sig = None    # force the overlay to refresh
        ps = cfg.get("position") or {}
        an = cfg.get("angular") or {}
        sig = (repr(sorted((k, v) for k, v in ps.items()))
               + "|" + repr(sorted((k, v) for k, v in an.items())))
        if sig == self._last_sig:
            return
        self._last_sig = sig
        try:
            self._rebuild_gps(cfg)
        except Exception:
            traceback.print_exc()
            timer = getattr(self, "_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    # ----------------------------------------------------------- rebuild ----

    def _rebuild_gps(self, cfg):
        vtk = self._vtk_widget
        ren = vtk.get_scene().renderer
        for a in self._owned:
            try:
                ren.RemoveActor(a)
            except Exception:
                pass
        self._owned = []

        ps = cfg.get("position") or {}
        an = cfg.get("angular") or {}
        pt = ps.get("type", "Point")
        sh = ps.get("shape", "")
        cx, cy, cz = (_f(ps, "cx"), _f(ps, "cy"), _f(ps, "cz"))
        centre = (cx, cy, cz)
        radius = _f(ps, "radius", 0.0)
        hx = _f(ps, "halfx", 0.0)
        hy = _f(ps, "halfy", 0.0)
        # Drawing fallbacks so an incomplete form never draws a zero-size
        # object; values follow the live config whenever they are set.
        if radius <= 0.0:
            radius = 10.0
        if hx <= 0.0:
            hx = 30.0
        if hy <= 0.0:
            hy = 30.0
        if pt == "Plane":
            ext = math.hypot(hx, hy)
        elif pt == "Surface":
            ext = radius
        else:
            ext = 0.0

        # Geometry context + scene sizing (same rules as the gun preview).
        bbox = self._scene_box()
        span = 0.0
        if bbox:
            span = max(bbox[1] - bbox[0], bbox[3] - bbox[2],
                       bbox[5] - bbox[4])
        base = max(90.0, math.hypot(cx, cy, cz) * 1.1)
        if span > 1e-6:
            axhalf = max(span * 0.045, base * 0.4)
            size_ref = max(span, ext * 2.0)
        else:
            axhalf = max(base, ext * 0.5)
            size_ref = max(base, ext * 2.0)
        # Arrow length / dot radius follow the gun preview rules exactly
        # (geometry span when GDML is loaded, otherwise the position-distance
        # scale), so both windows draw the same arrow and dot sizes for one
        # scene.  A plane/shell larger than the scene reference only raises a
        # floor so its own arrows never shrink out of sight.
        if span > 1e-6:
            arrow_ln = max(span / 3.0, 120.0)
            dot_rad = max(4.0, span * 0.006)
        else:
            arrow_ln = max(base * 1.15, 120.0)
            dot_rad = max(3.0, base * 0.03)
        if ext > 0.0:
            arrow_ln = max(arrow_ln, ext * 0.25)
            dot_rad = max(dot_rad, min(16.0, ext * 0.008))

        # RGB world axes through the origin (ruler when no GDML).
        for i, col in enumerate((_XR, _YG, _ZB)):
            p1 = [0.0, 0.0, 0.0]
            p2 = [0.0, 0.0, 0.0]
            p1[i] = -axhalf
            p2[i] = axhalf
            self._own(ren, _actor_from_poly(
                _polyline([(p1[0], p1[1], p1[2]),
                           (p2[0], p2[1], p2[2])]),
                col, width=1.5, opacity=0.75))
        if math.hypot(cx, cy, cz) > 1e-6:
            self._own(ren, _actor_from_poly(
                _polyline([(0.0, 0.0, 0.0), centre]),
                _GREY, width=1.2, opacity=0.45))

        ang_t = an.get("type", "iso")

        # ---- position shape + emission anchors ----
        if pt == "Surface" and sh == "Sphere":
            # The translucent shell is the focal element of this scene.  When
            # the configured radius is small it would be dwarfed by the arrow
            # overlay and the inward lobes would pile onto each other around
            # the centre, so the drawn shell gets a minimum radius derived
            # from the arrow scale: the glass sphere always reads at least as
            # large as the arrows, and the inward arrow tips (sized below off
            # dr) stay inside the shell instead of crossing out the far side.
            dr = max(radius, arrow_ln * 0.9)
            self._own(ren, _glass_shell_actor(centre, dr))
            shell = [(v[0] + cx, v[1] + cy, v[2] + cz)
                     for v in _spiral_surface(dr, dr, dr, 6)]
            # Surface-Sphere anchors sit ON the shell, so a full-size marker
            # would crowd it: draw them clearly smaller here.
            dot_s = max(dot_rad * 0.45, 2.0)
            for s in shell:
                self._own(ren, _solid_sphere_world(s, dot_s, _YELLOW))
            if ang_t == "cos":
                # GPS frames every surface point with z' = the outward radial
                # (sphere branch of G4SPSPosDistribution), and cos theta = 0
                # means -z', so each lobe points INWARD toward the centre -
                # not outward along the radials.  Length dr * 0.9 stops the
                # petals around the centre before they cross each other.
                for s in shell[:4]:
                    axis = _unit((cx - s[0], cy - s[1], cz - s[2]))
                    for d in _lobe_dirs(axis, 40.0):
                        self._own(ren, _momentum_arrow(s, d, dr * 0.9,
                                                       _GREEN))
            else:
                # iso = full 4pi at every point: arrows leave both OUTWARD and
                # INWARD.  Draw the outer fan on every anchor and the inner
                # rays on alternating anchors, shortened so their tips stop
                # around the centre instead of crossing every other arrow.
                for i, s in enumerate(shell):
                    out = _unit((s[0] - cx, s[1] - cy, s[2] - cz))
                    self._own(ren, _momentum_arrow(s, out, arrow_ln * 0.7,
                                                   _GREEN))
                    if i % 2 == 0:
                        self._own(ren, _momentum_arrow(
                            s, _neg(out), dr * 0.9, _GREEN))

        elif pt == "Plane" and sh == "Rectangle":
            ux, uy, _nz = local_axes(ps)

            def at(sx, sy):
                return (centre[0] + sx * hx * ux[0] + sy * hy * uy[0],
                        centre[1] + sx * hx * ux[1] + sy * hy * uy[1],
                        centre[2] + sx * hx * ux[2] + sy * hy * uy[2])

            corners = [at(-1.0, -1.0), at(1.0, -1.0),
                       at(1.0, 1.0), at(-1.0, 1.0)]
            for a in _glass_quad_actor(corners):
                self._own(ren, a)
            anchors = [at(0.0, 0.0)]
            for sx, sy in ((0.5, 0.5), (-0.5, 0.5), (-0.5, -0.5),
                           (0.5, -0.5)):
                anchors.append(at(sx, sy))
            for a in anchors:
                self._own(ren, _solid_sphere_world(a, dot_rad, _YELLOW))
            if ang_t == "iso":
                # Fan from the pane centre (no dominant direction).
                for d in _cone(_nz, 90, 8):
                    self._own(ren, _momentum_arrow(anchors[0], d,
                                                   arrow_ln * 0.9, _GREEN))
            else:
                # Parallel arrows leave along the emission axis.  GPS first
                # flips the pane side-normal to point AWAY from the world
                # origin, then fires along -z' (cos theta = 0), so the lobe
                # falls on the origin side of the pane - the raw normal _nz
                # would aim the wrong way for every off-origin plane.
                axis = _gps_emit_axis(ps, an)
                for a in anchors:
                    self._own(ren, _momentum_arrow(a, axis, arrow_ln, _GREEN))

        else:  # Point (or anything unsupported collapses to a dot)
            self._own(ren, _solid_sphere_world(centre, dot_rad,
                                               _YELLOW))
            if ang_t == "iso":
                # iso arrows stay inside the configured theta/phi region of
                # the angular frame; a default 4pi range fills the sphere.
                for d in _iso_world_dirs(an, 12):
                    self._own(ren, _momentum_arrow(centre, d, arrow_ln * 0.8,
                                                   _GREEN))
            else:
                # Point + cos: symmetric lobe, one arrow along the emission
                # axis plus four evenly around it.  The axis is opposite the
                # angular +z' (default -Z) unless /gps/ang/rot* is set.
                axis = _gps_emit_axis(ps, an)
                for d in _lobe_dirs(axis, 40.0):
                    self._own(ren, _momentum_arrow(centre, d, arrow_ln,
                                                   _GREEN))

        # ---- info bar ----
        geo_txt = "no geometry loaded"
        try:
            if self._agent is not None and self._agent.get_all_file_nodes():
                geo_txt = "GDML loaded (translucent)"
        except Exception:
            pass
        if pt == "Plane" and sh == "Rectangle":
            pos_txt = ("Plane Rectangle 2\u00d7{0:g}\u00d7{1:g} mm @ "
                       "({2:g},{3:g},{4:g})").format(
                           _f(ps, "halfx"), _f(ps, "halfy"), cx, cy, cz)
            pos_txt += _rot_text(ps)
        elif pt == "Surface" and sh == "Sphere":
            pos_txt = f"Surface Sphere r={radius:g} mm @ ({cx:g},{cy:g},{cz:g})"
        else:
            pos_txt = f"Point @ ({cx:g},{cy:g},{cz:g}) mm"
        ang_txt = ang_t
        if ang_t == "iso":
            tm, tx = _f(an, "theta_min"), _f(an, "theta_max")
            pm, px = _f(an, "phi_min"), _f(an, "phi_max")
            if an.get("theta_min") is not None:
                ang_txt += (f"  \u03b8 {tm:g}\u2013{tx:g}\u00b0  "
                            f"\u03c6 {pm:g}\u2013{px:g}\u00b0")
        else:
            ang_txt += _rot_text(an)
        self._lbl_cfg.setText(f"position: {pos_txt}   |   angular: {ang_txt}"
                              f"   |   {geo_txt}")

        # Camera: refit when the source jumps far (same rule as the gun view).
        cam_key = (cx, cy, cz)
        prev = self._cam_prev
        moved = (self._first_cam or prev is None
                 or math.hypot(cx - prev[0], cy - prev[1], cz - prev[2])
                 > max(200.0, size_ref) * 0.4)
        self._cam_prev = cam_key
        if moved:
            self._fit_view(ren)
            self._first_cam = False
        vtk.set_dark_theme(self._dark)
        vtk.render()
