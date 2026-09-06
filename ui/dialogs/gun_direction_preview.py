"""gun_direction_preview - live 3D sketch of a ParticleGun source.

Opened from the "3D Preview" button in the Particle Source dialog.

Semantics follow build_gun_macro()/the manual: the (dx, dy, dz) values are
written verbatim to /gps/direction (G4ParticleGun::SetParticleMomentumDirection
world-coordinate direction cosines) - no flip or rotation is ever applied,
only the direction of the vector matters. This window therefore draws a green
arrow along (dx, dy, dz) exactly as the macro will see it.

Layout (deliberately free of the main-view toolbar / XYZ view buttons):
  - a corner RGB axis marker (screen-fixed size, stays legible at any zoom)
  - if the main window has an imported GDML geometry it is rendered as
    translucent solids (reduced set: World + physical instances only, the
    same mode as the probe/voxel previews), the World volume as a cyan
    wireframe; without GDML only the origin axes / ruler are drawn
  - the gun position as a yellow dot plus a faint line to the origin
  - a prominent green momentum arrow (solid shaft + cone head) starting at
    the position, drawn entirely in world coordinates (no actor transform)
  - RGB world-axis lines through the origin, auto-sized to the scene

The VTK viewport background follows the same dark/light theme as the main
window (0.95 gray in light mode). The top/bottom info bars are painted with
the same theme colour so the window does not look patched together.

Coordinates are mm (the macro divides by 10 when writing cm).

The window polls the dialog's live gun config on a timer, so parameter
changes appear immediately. Only the ParticleGun page is visualised here;
the full GPS source preview is a separate feature.
"""

import math
import sys
import traceback

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor

from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersSources import vtkArrowSource, vtkSphereSource
from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (corner-axis captions)
import vtkmodules.vtkRenderingOpenGL2  # noqa: F401

from ui.vtk_widget import VtkPreviewWidget
from ui.dialogs.source_geo_preview import _actor_from_poly, _polyline, _unit

_XR = (1.0, 0.4, 0.4)
_YG = (0.4, 1.0, 0.4)
_ZB = (0.45, 0.55, 1.0)
_YELLOW = (1.0, 0.85, 0.2)
_GREEN = (0.15, 1.0, 0.35)
_GREY = (0.6, 0.6, 0.68)
_CYAN = (0.2, 0.8, 1.0)


def _bake(src, transform):
    """Apply `transform` to the source's geometry so the resulting polydata
    already lives in world coordinates.

    Actors built this way carry NO vtkActor transform and therefore use the
    exact same rendering path as the plain world-space lines (which the user
    sees reliably). An actor whose position is given by SetUserTransform can
    silently fail to draw on some VTK / OpenGL driver combinations."""
    f = vtkTransformPolyDataFilter()
    f.SetInputConnection(src.GetOutputPort())
    f.SetTransform(transform)
    f.Update()
    return f.GetOutput()


def _momentum_arrow(center, d, ln, color):
    """Chunky, clearly readable 3D arrow. vtkArrowSource ships the shaft +
    cone as one piece (default pointing along +X); it is rotated/scaled/
    translated and baked into world coordinates."""
    s = vtkArrowSource()
    s.SetTipLength(0.15)       # cone head shortened to keep a slim look
    s.SetTipRadius(0.026)      # cone base radius halved again (~0.026)
    s.SetShaftRadius(0.0068)   # shaft radius halved again (~0.007)
    s.SetShaftResolution(28)
    s.SetTipResolution(28)
    s.Update()
    u = _unit(d)
    t = vtkTransform()
    t.Translate(*center)
    t.Scale(ln, ln, ln)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, u[0]))))
    if ang > 1e-3:
        # Rotate the default +X direction onto u
        cr = (0.0, -u[2], u[1])
        nl = math.sqrt(cr[1] ** 2 + cr[2] ** 2)
        if nl < 1e-9:  # u ~ +/- X
            if u[0] < 0:
                t.RotateWXYZ(180.0, 0.0, 1.0, 0.0)
        else:
            # vtklib has no 3-arg overload: axis must be given as x,y,z
            t.RotateWXYZ(ang, 0.0, cr[1] / nl, cr[2] / nl)
    m = vtkPolyDataMapper()
    m.SetInputData(_bake(s, t))
    a = vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*color)
    p.SetAmbient(0.45)
    p.SetDiffuse(0.9)
    p.SetSpecular(0.3)
    p.SetSpecularPower(24)
    return a


def _solid_sphere_world(center, rad, color):
    """Solid sphere baked into world coordinates (no actor transform)."""
    s = vtkSphereSource()
    s.SetRadius(max(rad, 1e-6))
    s.SetThetaResolution(24)
    s.SetPhiResolution(16)
    s.Update()
    t = vtkTransform()
    t.Translate(*center)
    m = vtkPolyDataMapper()
    m.SetInputData(_bake(s, t))
    a = vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*color)
    p.SetAmbient(0.45)
    p.SetDiffuse(0.9)
    return a


class GunDirectionPreview(QWidget):
    """Standalone top-level window; VTK content must not sit under a QSS
    stylesheet (same constraint as the other VTK previews)."""

    def __init__(self, dialog, dark=False, parent=None):
        super().__init__(parent)
        self._dlg = dialog
        # The Particle Source dialog holds the agent of the main window's
        # imported GDML; None -> no geometry to render.
        self._agent = getattr(dialog, "_gdml_agent", None)
        self._dark = bool(dark)
        self._closed = False
        self._first_cam = True
        self._last_sig = None
        self._cam_prev = None
        self._owned = []
        self._corner_axes = None
        self._geo_built = False
        self._geo_failed = False
        self._geo_files = ()
        self._bbox_key = None
        self._bbox_val = None

        self.setWindowTitle("ParticleGun 3D Preview")
        self.resize(820, 700)
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

        # Lightweight VTK view: no toolbar / no XYZ view buttons, just the
        # scene. The default CubeAxes numeric ruler is removed as well.
        self._vtk_widget = VtkPreviewWidget(self)
        lay.addWidget(self._vtk_widget, 1)

        self._lbl_hint = QLabel(
            "Green arrow = momentum direction: (dx, dy, dz) is written "
            "verbatim to /gps/direction, no flip is applied (macro line "
            "above). Yellow dot = position (mm). If a GDML geometry is "
            "loaded in the main window it is shown translucent for context; "
            "otherwise red/green/blue origin lines act as a ruler. "
            "LMB rotate / MMB pan / wheel zoom.")
        self._lbl_hint.setContentsMargins(10, 4, 10, 6)
        self._lbl_hint.setWordWrap(True)
        lay.addWidget(self._lbl_hint)

        # Theme the chrome BEFORE the first VTK render so the window never
        # flashes in the wrong colour.
        self._apply_chrome()

        # VTK must start only after the window is shown (ui/vtk_widget.py)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._init_view)

    # ---------------- lifecycle / chrome ----------------

    def _apply_chrome(self):
        """Colour the top/bottom bars to match the main-window theme.

        Only the non-VTK labels are styled + a widget palette; no QSS is
        applied to the wrapper that hosts QVTK (that would break the VTK
        OpenGL compositing - see ui/vtk_view_window.py).
        """
        dark = self._dark
        if dark:
            bg = "#1e1e2e"
            fg = "#cdd6f4"
        else:
            bg = "#f5f5f5"
            fg = "#2c2c2c"

        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(fg))
        pal.setColor(QPalette.ColorRole.Base,
                     QColor("#181825" if dark else "#ffffff"))
        pal.setColor(QPalette.ColorRole.Text, QColor(fg))
        pal.setColor(QPalette.ColorRole.Button, QColor(bg))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(fg))
        self.setPalette(pal)

        # The widget background role drives the two text bars.
        sheet = (f"background:{bg}; color:{fg}; "
                 f"font-size:12px; font-weight:normal;")
        self._lbl_cfg.setStyleSheet(sheet)
        self._lbl_hint.setStyleSheet(sheet)

        self._vtk_widget.set_dark_theme(dark)

    def _init_view(self):
        self._vtk_widget.set_dark_theme(self._dark)
        try:
            self._build_corner_axes()
        except Exception as e:
            print(f"[GunPreview] corner axes error: {e}", file=sys.stderr)
        try:
            self._tick()
        except Exception:
            traceback.print_exc()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(300)

    def _drop_cube_axes(self):
        """The preview uses the corner marker instead of the numeric CubeAxes
        ruler; build_scene() re-adds CubeAxes, so drop it after every build."""
        ren = self._vtk_widget.get_scene().renderer
        cube = getattr(self._vtk_widget, "_cube_axes", None)
        if cube is not None:
            try:
                ren.RemoveActor(cube)
            except Exception:
                pass

    def _build_corner_axes(self):
        """Fixed-size RGB axis marker in the viewport corner (the ruler)."""
        self._drop_cube_axes()

        ax = vtkAxesActor()
        ax.SetTotalLength(1.0, 1.0, 1.0)
        ax.SetAxisLabels(1)
        # The caption text is painted in the inverse of the renderer
        # background (white on the dark scene, near-black on the light one)
        # so the X / Y / Z letters stay readable in either theme.  A larger
        # font matches the bigger corner marker below.
        lab = (1.0, 1.0, 1.0) if self._dark else (0.08, 0.08, 0.12)
        for cap in (ax.GetXAxisCaptionActor2D(),
                    ax.GetYAxisCaptionActor2D(),
                    ax.GetZAxisCaptionActor2D()):
            tp = cap.GetCaptionTextProperty()
            tp.SetColor(*lab)
            tp.SetShadow(0)
            tp.SetFontSize(24)

        omw = vtkOrientationMarkerWidget()
        omw.SetOrientationMarker(ax)
        omw.SetInteractor(self._vtk_widget.renderWindow().GetInteractor())
        # Lower-right corner marker: enlarged viewport region so the axis
        # trihedron reads clearly (was 0.84..1.0 x 0.02..0.2).
        omw.SetViewport(0.76, 0.01, 1.0, 0.27)
        # Order matters: "Enabled" must come before changing the
        # interactivity flag, otherwise VTK prints
        #   "Set interactor and Enabled before changing interaction."
        omw.SetEnabled(1)
        omw.InteractiveOff()
        self._corner_axes = omw

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
            if self._corner_axes is not None:
                self._corner_axes.EnabledOff()
        except Exception:
            pass
        try:
            self._vtk_widget.cleanup()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- GDML context (reduced) ----------------

    def _scene_box(self):
        """Union AABB (xmin..zmax, mm) of the placed geometry - the same box
        the voxel dialog computes with compute_scene_bbox(); None when there
        is none. Cached per geometry set."""
        key = self._geo_files
        if getattr(self, "_bbox_key", object()) == key:
            return self._bbox_val
        val = None
        if self._agent is not None:
            try:
                b = self._agent.compute_scene_bbox()
            except Exception:
                b = None
            if b and any(abs(v) > 1e-9 for v in b):
                val = b
        self._bbox_key = key
        self._bbox_val = val
        return val

    def _maybe_build_geometry(self):
        """Render the imported GDML (World + physical instances only, i.e.
        the reduced set used by the probe/voxel previews) once it exists.
        Never raises and never blocks the arrow overlay: a failure is logged
        once and the overlay keeps working."""
        if self._geo_built or self._geo_failed or self._agent is None:
            return False
        try:
            files = self._agent.get_all_file_nodes()
        except Exception:
            return False
        if not files:
            return False
        key = tuple(getattr(n, "name", "") for n in files)
        if key == self._geo_files:
            return False
        self._geo_files = key

        try:
            root = self._agent.get_root_node()
            if root is None:
                return False
            vtk = self._vtk_widget
            vtk.build_scene(root, render_all_volumes=False)
            self._drop_cube_axes()
            ren = vtk.get_scene().renderer

            # Translucent solids, no edges: the source stays readable and the
            # fill cost stays low.
            for a in list(getattr(vtk, "_gdml_actors", [])):
                p = a.GetProperty()
                p.SetEdgeVisibility(False)
                p.SetOpacity(0.35)
            # Emphasize the World container as a cyan wireframe (cheap)
            for w in self._agent.get_world_nodes():
                act = vtk.get_scene().get_actor_for_node(
                    getattr(w, "entry_id", ""))
                if act is None:
                    continue
                p = act.GetProperty()
                p.SetRepresentationToWireframe()
                p.SetColor(*_CYAN)
                p.SetOpacity(0.95)
                p.SetLineWidth(1.8)
            ren.ResetCamera()
            self._geo_built = True
            self._first_cam = True   # re-fit once the overlay rebuilds
            return True
        except Exception as e:
            self._geo_failed = True
            print(f"[GunPreview] GDML context render failed: {e}",
                  file=sys.stderr)
            return False

    # ---------------- live refresh ----------------

    def _tick(self):
        if self._closed:
            return
        try:
            cfg = self._dlg._collect()
        except RuntimeError:
            self._closed = True
            return
        gun = (cfg or {}).get("gun") if (cfg or {}).get("mode") == "gun" \
            else None
        if gun is None:
            return
        if self._maybe_build_geometry():
            self._last_sig = None    # force the overlay to refresh
        sig = repr(sorted((k, v) for k, v in gun.items()))
        if sig == self._last_sig:
            return
        self._last_sig = sig
        try:
            self._rebuild(gun)
        except Exception:
            traceback.print_exc()
            timer = getattr(self, "_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    def _rebuild(self, gun):
        vtk = self._vtk_widget
        ren = vtk.get_scene().renderer
        for a in self._owned:
            try:
                ren.RemoveActor(a)
            except Exception:
                pass
        self._owned = []

        ps = gun.get("position") or {}
        d = gun.get("direction") or {}
        x, y, z = (float(ps.get(k, 0.0) or 0.0) for k in ("x", "y", "z"))
        dx, dy, dz = (float(d.get(k, 0.0) or 0.0) for k in ("x", "y", "z"))
        if dx == dy == dz == 0.0:
            dx, dy, dz = 0.0, 0.0, 1.0

        # Union AABB of the imported geometry in mm - the same bounding box
        # the voxel dialog computes ("Enclose all geometry"). span == 0 means
        # no geometry is loaded, so the origin axes act as the ruler instead.
        bbox = self._scene_box()
        span = 0.0
        if bbox:
            span = max(bbox[1] - bbox[0], bbox[3] - bbox[2],
                       bbox[5] - bbox[4])
        base = max(90.0, math.hypot(x, y, z) * 1.1)   # no-geometry ruler size
        if span > 1e-6:
            axhalf = max(span * 0.045, base * 0.4)    # compact origin marker
            ln = max(span / 3.0, 120.0)               # arrow ~ 1/3 of bbox
            dot_rad = max(4.0, span * 0.006)
        else:
            axhalf = base                             # axes are the ruler
            ln = max(base * 1.15, 120.0)
            dot_rad = max(3.0, base * 0.03)
        fit = max(base, span)                         # scene size for camera

        # RGB world-axis lines through the origin (the ruler when no GDML).
        ax_cols = (_XR, _YG, _ZB)
        for i, col in enumerate(ax_cols):
            p1 = [0.0, 0.0, 0.0]
            p2 = [0.0, 0.0, 0.0]
            p1[i] = -axhalf
            p2[i] = axhalf
            self._own(ren, _actor_from_poly(
                _polyline([(p1[0], p1[1], p1[2]),
                           (p2[0], p2[1], p2[2])]),
                col, width=1.5, opacity=0.75))

        if math.hypot(x, y, z) > 1e-6:
            self._own(ren, _actor_from_poly(
                _polyline([(0.0, 0.0, 0.0), (x, y, z)]),
                _GREY, width=1.2, opacity=0.45))

        self._own(ren, _solid_sphere_world((x, y, z), dot_rad, _YELLOW))

        # Momentum arrow: one slim solid actor ~ 1/3 of the geometry bbox.
        # Deliberately no extra overlay line - two actors on the same
        # geometry z-fight and the dark underlay wins the depth test.
        u = _unit((dx, dy, dz))
        self._own(ren, _momentum_arrow((x, y, z), u, ln, _GREEN))

        geo_txt = "no geometry loaded"
        try:
            if self._agent is not None and self._agent.get_all_file_nodes():
                geo_txt = "GDML loaded (translucent)"
        except Exception:
            pass
        self._lbl_cfg.setText(
            f"/gps/direction {dx:g} {dy:g} {dz:g}   (no flip)   "
            f"|   position ({x:g}, {y:g}, {z:g}) mm   |   {geo_txt}")

        cam_key = (x, y, z)
        prev = self._cam_prev
        moved = (self._first_cam or prev is None
                 or math.hypot(x - prev[0], y - prev[1], z - prev[2])
                 > max(200.0, fit) * 0.4)
        self._cam_prev = cam_key
        if moved:
            self._fit_view(ren)
            self._first_cam = False
        self._vtk_widget.set_dark_theme(self._dark)
        vtk.render()

    def _fit_view(self, ren):
        """Reset the camera to fit the whole scene, then look at it from an
        oblique direction. Looking straight along the +Z arrow would make it
        appear as a point, so never look down an axis."""
        ren.ResetCamera()
        ren.ResetCameraClippingRange()
        try:
            cam = ren.GetActiveCamera()
            d0 = cam.GetDistance()
            if d0 > 1e-6:
                f = cam.GetFocalPoint()
                u = (0.6, 0.7, 0.4)
                n = math.sqrt(sum(c * c for c in u))
                cam.SetPosition(f[0] + u[0] / n * d0,
                                f[1] + u[1] / n * d0,
                                f[2] + u[2] / n * d0)
                cam.SetViewUp(0.0, 0.0, 1.0)
                cam.OrthogonalizeViewUp()
            ren.ResetCameraClippingRange()
        except Exception:
            pass
