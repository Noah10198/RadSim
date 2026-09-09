"""TrajectoryViewer - non-modal 3D preview of a task's Traj.csv.

Shows the run geometry plus particle trajectories that the rad4space solver
wrote to <work>/Traj.csv. The geometry is rendered in the Particle Source 3D
preview style (translucent coloured solids, World volume as a cyan wireframe)
and - like the voxel result window - keeps the RGB CubeAxes numeric ruler
(X / Y / Z labels with mm values) plus the corner RGB XYZ marker in the
lower-right corner. One vtkPolyLine per track: a track is the set of rows
sharing the same (eventID, trackID), ordered by step.

Data format (mm per row): eventID, trackID, parentID, particle, step, x, y, z

Colouring follows the Geant4 TrajectoryDrawByParticleID defaults used by
solver/rad4space/plt_traj/plot_traj_vtk-test.py (gamma=green, e-=red, e+=blue,
pi+/-=magenta, proton=cyan, neutron=yellow, ions=orange, others=grey).

The dialog opens previewing ALL trajectories. The filter panel (eventID /
trackID / parentID ranges + a particle multi-select) only takes effect when
the user presses "Apply Filter"; editing the controls never auto-applies.
"""

import csv
import os
import re

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from vtkmodules.vtkCommonCore import vtkIntArray, vtkLookupTable, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData, vtkPolyLine
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper
from vtkmodules.vtkRenderingAnnotation import (
    vtkScalarBarActor, vtkAxesActor,
)
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
import vtkmodules.vtkRenderingFreeType  # noqa: F401  (corner-axis captions)

from core.gdml_tree import GdmlNodeType
from ui.vtk_widget import VtkWidget

# The six species exposed as checkboxes (anything else = the "other" checkbox)
KNOWN_PARTICLES = ("gamma", "e-", "e+", "proton", "alpha", "neutron")

_PARTICLE_COLOUR = {
    "gamma":   (0.0, 1.0, 0.0),   # green
    "e-":      (1.0, 0.0, 0.0),   # red
    "e+":      (0.0, 0.0, 1.0),   # blue
    "pi+":     (1.0, 0.0, 1.0),   # magenta
    "pi-":     (1.0, 0.0, 1.0),   # magenta
    "proton":  (0.0, 1.0, 1.0),   # cyan
    "neutron": (1.0, 1.0, 0.0),   # yellow
}
_ION_COLOUR = (1.0, 0.55, 0.0)     # orange
_OTHER_COLOUR = (0.6, 0.6, 0.6)    # grey
_CYAN = (0.2, 0.8, 1.0)            # World container wireframe (dark bg)

# The World container wireframe is the one element that keeps a theme split
# (bright cyan on dark, deep blue on light); the track colours themselves do
# NOT change between themes - both use the standard palette above.
_CYAN_LIGHT = (0.05, 0.36, 0.78)          # World wireframe (light bg)

_ION_NAMES = {"alpha", "deuteron", "triton", "He3", "GenericIon"}
_ION_RE = re.compile(r"[A-Z][a-z]?[0-9]+")


def _is_ion_name(name):
    n = name
    if n.startswith("anti_"):
        n = n[len("anti_"):]
    if "[" in n:  # strip excitation marks e.g. Fe56[0.0]
        n = n[:n.index("[")]
    return n in _ION_NAMES or bool(_ION_RE.fullmatch(n))


def colour_for(particle, dark=True):
    """RGB for a particle name - one standard palette for both themes.

    The Geant4 standard colours (gamma=green, e-=red, e+=blue, proton=cyan,
    neutron=yellow, ions=orange, others=grey) are used unchanged in light mode
    as well, exactly as the dark scene shows them; only the World wireframe
    and the text/labels swap colours with the theme.
    """
    if particle in _PARTICLE_COLOUR:
        return _PARTICLE_COLOUR[particle]
    if _is_ion_name(particle):
        return _ION_COLOUR
    return _OTHER_COLOUR


def world_colour(dark):
    """World-container wireframe colour - cyan pops on dark, too pale on light."""
    return _CYAN if dark else _CYAN_LIGHT


def _make_lut(pnames, dark):
    """vtkLookupTable: index == cell scalar, annotation == particle name.

    Both the polyline mapper and the scalar-bar swatches read this table, so a
    single theme-aware palette keeps lines and legend consistent.
    """
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(len(pnames))
    lut.SetRange(0, len(pnames) - 1)
    lut.Build()
    for i, name in enumerate(pnames):
        rgb = colour_for(name, dark)
        lut.SetTableValue(i, rgb[0], rgb[1], rgb[2], 1.0)
        lut.SetAnnotation(i, name)
    return lut


# ---------------------------------------------------------------------------
# CSV parsing / filtering (pure data, no Qt / VTK)
# ---------------------------------------------------------------------------

def load_tracks_from_csv(path):
    """Read Traj.csv and group rows into tracks.

    Returns a list of dicts: {"event", "track", "parent", "particle", "pts"}
    where pts is [(x, y, z), ...] ordered by ascending step (step 0 = the
    vertex). Raises OSError/ValueError on unreadable or malformed files.
    """
    groups = {}
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            event = int(row["eventID"])
            track = int(row["trackID"])
            key = (event, track)
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    "event": event,
                    "track": track,
                    "parent": int(row["parentID"]),
                    "particle": (row["particle"] or "").strip(),
                    "pts": [],
                }
            g["pts"].append((float(row["step"]),
                             float(row["x"]), float(row["y"]),
                             float(row["z"])))
    out = []
    for g in groups.values():
        g["pts"].sort(key=lambda p: p[0])  # ascending step
        g["pts"] = [p[1:] for p in g["pts"]]
        out.append(g)
    return out


def filter_tracks(tracks, event_range, track_range, parent_range, wanted,
                  other_ok):
    """Return the tracks satisfying all criteria (inclusive ranges).

    event_range/track_range/parent_range are (lo, hi) int pairs; wanted is the
    set of selected KNOWN_PARTICLES; other_ok keeps particles outside
    KNOWN_PARTICLES. Range/name checks are track-level (a track's parentID and
    particle are constant for all its rows).
    """
    elo, ehi = event_range
    tlo, thi = track_range
    plo, phi = parent_range
    out = []
    for t in tracks:
        if not (elo <= t["event"] <= ehi):
            continue
        if not (tlo <= t["track"] <= thi):
            continue
        if not (plo <= t["parent"] <= phi):
            continue
        name = t["particle"]
        if name in wanted:
            out.append(t)
        elif name not in KNOWN_PARTICLES and other_ok:
            out.append(t)
    return out


def file_stamp(path):
    """(mtime_ns, size) identity used to detect a re-run rewritten the CSV."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def world_nodes_from_root(root):
    """All WORLD_NODE entries under a geometry root (cyan wireframe targets).

    Mirrors the preview windows: the World container is the only volume drawn
    as a wireframe; every other actor stays a translucent coloured solid.
    """
    out = []
    if root is None:
        return out
    try:
        for n in root.get_all_descendants():
            if n.node_type == GdmlNodeType.WORLD_NODE:
                out.append(n)
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# VTK widget
# ---------------------------------------------------------------------------

class TrajectoryViewWidget(VtkWidget):
    """VtkWidget holding the translucent geometry + the trajectory overlay."""

    def __init__(self, parent=None):
        self._is_dark = True
        self._track_actor = None
        self._track_bar = None
        self._track_polydata = None
        self._track_mapper = None
        self._track_pnames = None   # particle names of the current LUT
        self._track_lut = None
        self._world_actors = []     # world-container actors to re-tint
        self._corner_axes = None
        self._corner_axes_actor = None
        self._corner_pending = None   # QTimer scheduled to build the marker
        self._released = False        # VTK context already handed back
        super().__init__(parent)

    # -- geometry backdrop (Particle Source 3D preview style) -----------------
    def style_geometry_preview(self, world_nodes=()):
        """Render the GDML like the Particle Source 3D preview.

        Translucent coloured solids (kept at the scene's own per-volume
        colours) and the World container re-styled as a prominent cyan
        wireframe. The RGB CubeAxes numeric ruler is kept, matching the voxel
        result window (its bounds are refreshed over geometry + tracks).
        """
        ren = self._scene.renderer if self._scene else None
        if ren is None:
            return
        # Translucent solids, no edges: the tracks stay readable above them.
        for a in self._gdml_actors:
            p = a.GetProperty()
            p.SetEdgeVisibility(False)
            p.SetOpacity(0.35)
        # Emphasize the World volume(s) as a cyan wireframe (same as the
        # gun/GPS preview windows). Actors are remembered so a live theme
        # switch can swap between the bright cyan (dark bg) and the deep blue
        # (light bg) that reads on the pale scene.
        self._world_actors = []
        for node in world_nodes or ():
            try:
                eid = getattr(node, "entry_id", "")
                act = self._scene.get_actor_for_node(eid) if eid else None
            except Exception:
                act = None
            if act is None:
                continue
            self._world_actors.append(act)
            p = act.GetProperty()
            p.SetRepresentationToWireframe()
            p.SetOpacity(0.95)
            p.SetLineWidth(1.8)
        self._tint_world()
        self.render()

    def _build_corner_axes(self):
        """Screen-fixed RGB XYZ axis marker in the lower-right corner.

        The marker (vtkOrientationMarkerWidget) needs the interactor running,
        so it is built on the first showEvent instead of in the constructor.
        """
        self._corner_pending = None
        # Never enable the widget against a dead / not-yet-mapped GL context:
        # doing so makes VTK call wglMakeCurrent on an invalid HDC and it keeps
        # logging "vtkWin32OpenGLRenderWindow: wglMakeCurrent failed".
        if self._released or not self.isVisible():
            return
        if self._corner_axes is not None:
            return
        try:
            ax = vtkAxesActor()
            ax.SetTotalLength(1.0, 1.0, 1.0)
            ax.SetAxisLabels(1)
            lab = (1.0, 1.0, 1.0) if self._is_dark else (0.08, 0.08, 0.12)
            for cap in (ax.GetXAxisCaptionActor2D(),
                        ax.GetYAxisCaptionActor2D(),
                        ax.GetZAxisCaptionActor2D()):
                tp = cap.GetCaptionTextProperty()
                tp.SetColor(*lab)
                tp.SetShadow(0)
                tp.SetFontSize(24)
            omw = vtkOrientationMarkerWidget()
            omw.SetOrientationMarker(ax)
            omw.SetInteractor(self._vtk_interactor.GetRenderWindow()
                              .GetInteractor())
            omw.SetViewport(0.76, 0.01, 1.0, 0.27)
            omw.SetEnabled(1)
            omw.InteractiveOff()
            self._corner_axes = omw
            self._corner_axes_actor = ax
            self.render()
        except Exception:
            self._corner_axes = None
            self._corner_axes_actor = None

    def showEvent(self, event):
        super().showEvent(event)
        if not self._corner_axes and not self._released:
            try:
                # Keep the QTimer so cleanup() can cancel it: firing after the
                # GL context was released would re-create the marker on a dead
                # HDC (wglMakeCurrent failed).
                self._corner_pending = QTimer.singleShot(
                    0, self._build_corner_axes)
            except Exception:
                self._corner_pending = None

    def cleanup(self):
        """Cancel pending work, disable the corner marker, release VTK.

        Idempotent: closing the dialog (closeEvent -> cleanup) or the main
        window tearing every secondary window down may both reach here.
        """
        if self._released:
            return
        self._released = True
        if self._corner_pending is not None:
            try:
                self._corner_pending.stop()
            except Exception:
                pass
            self._corner_pending = None
        if self._corner_axes is not None:
            try:
                self._corner_axes.EnabledOff()
            except Exception:
                pass
            self._corner_axes = None
            self._corner_axes_actor = None
        try:
            super().cleanup()
        except Exception:
            pass

    def render(self):
        """Never touch the GL context after it was released."""
        if self._released:
            return
        super().render()

    # -- clip slicing ----------------------------------------------------------
    def _extra_clip_mappers(self):
        """The clip plane must slice the trajectory polylines too.

        The polyline actor is kept outside _gdml_actors, so without this hook
        Clip only trimmed the translucent geometry and left the tracks whole.
        """
        if self._track_mapper is not None:
            return (self._track_mapper,)
        return ()

    # -- theme-aware recolouring ----------------------------------------------
    def _tint_world(self):
        """Colour of the World wireframe follows the theme (cyan vs deep blue)."""
        for act in getattr(self, "_world_actors", ()):
            try:
                act.GetProperty().SetColor(*world_colour(self._is_dark))
            except Exception:
                pass

    def _build_colorbar(self, lut, npnames):
        bar = vtkScalarBarActor()
        bar.SetLookupTable(lut)
        bar.SetTitle("particle")
        bar.DrawAnnotationsOn()
        bar.SetMaximumNumberOfColors(npnames)
        bar.SetNumberOfLabels(0)
        # Upper right so it never overlaps the lower-right XYZ corner marker.
        bar.SetWidth(0.11)
        bar.SetHeight(0.38)
        bar.SetPosition(0.87, 0.56)
        self._track_bar = bar
        self._style_bar()
        return bar

    def _apply_track_theme(self):
        """Re-colour built polylines + legend after a theme switch.

        No rebuild needed: each track's cell scalar is its particle index into
        the LUT, so swapping the LUT recolours every polyline at render time.
        The scalar bar keeps its own colour swatches, so it is rebuilt.
        """
        pnames = self._track_pnames
        mapper = self._track_mapper
        if not pnames or mapper is None:
            return
        lut = _make_lut(pnames, self._is_dark)
        self._track_lut = lut
        mapper.SetLookupTable(lut)
        actor = self._track_actor
        if actor is not None:
            actor.GetProperty().SetLineWidth(1.3)
            actor.GetProperty().SetOpacity(0.85)
        ren = self._scene.renderer if self._scene else None
        if ren is None:
            return
        if self._track_bar is not None:
            ren.RemoveActor(self._track_bar)
        ren.AddActor(self._build_colorbar(lut, len(pnames)))

    # -- trajectory overlay ----------------------------------------------------
    def clear_tracks(self):
        ren = self._scene.renderer if self._scene else None
        if ren is None:
            return
        if self._track_actor is not None:
            ren.RemoveActor(self._track_actor)
            self._track_actor = None
        if self._track_bar is not None:
            ren.RemoveActor(self._track_bar)
            self._track_bar = None
        self._track_mapper = None
        self._track_polydata = None
        self._track_pnames = None
        self._track_lut = None

    def show_tracks(self, tracks):
        """(Re)build the polyline overlay from a filtered track list.

        Returns (ntracks, npoints, particle_names_present).
        """
        self.clear_tracks()
        npoints = 0
        if not tracks:
            return 0, 0, []

        pnames = sorted({t["particle"] for t in tracks})
        pidx = {n: i for i, n in enumerate(pnames)}
        pts = vtkPoints()
        lines = vtkCellArray()
        cell_type = vtkIntArray()
        cell_type.SetName("particleType")

        for t in tracks:
            ids = []
            for (x, y, z) in t["pts"]:
                ids.append(pts.InsertNextPoint(x, y, z))
            cell = vtkPolyLine()
            cell.GetPointIds().SetNumberOfIds(len(ids))
            for i, pid in enumerate(ids):
                cell.GetPointIds().SetId(i, pid)
            lines.InsertNextCell(cell)
            cell_type.InsertNextValue(pidx[t["particle"]])
            npoints += len(ids)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)
        poly.GetCellData().SetScalars(cell_type)
        self._track_polydata = poly

        lut = _make_lut(pnames, self._is_dark)
        self._track_pnames = pnames
        self._track_lut = lut

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly)
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(0, len(pnames) - 1)
        mapper.SetScalarModeToUseCellData()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        self._track_mapper = mapper

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetLineWidth(1.3)
        actor.GetProperty().SetOpacity(0.85)
        self._scene.renderer.AddActor(actor)
        self._track_actor = actor

        # Re-apply an active clip plane to the freshly built polyline mapper
        # (the geometry actors are clipped by the base VtkWidget machinery).
        if self._clip_active and self._clip_bounds:
            self._track_mapper.RemoveAllClippingPlanes()
            self._track_mapper.AddClippingPlane(self._clip_plane)

        self._scene.renderer.AddActor(self._build_colorbar(lut, len(pnames)))
        # Keep the RGB numeric ruler sized over geometry + tracks (the base
        # class set its bounds from the GDML actors only when build_scene ran,
        # before any polyline existed).
        try:
            self._update_cube_axes_bounds()
        except Exception:
            pass
        self.render()
        return len(tracks), npoints, pnames

    def _style_bar(self):
        bar = self._track_bar
        if bar is None:
            return
        txt = (0.92, 0.92, 0.95) if self._is_dark else (0.10, 0.10, 0.14)
        for tp in (bar.GetLabelTextProperty(),
                   bar.GetAnnotationTextProperty(),
                   bar.GetTitleTextProperty()):
            tp.SetColor(*txt)
            tp.SetShadow(0)
            tp.ItalicOff()
            tp.BoldOff()
        # Particle names are LUT annotations here, so their font is the
        # annotation text property (the label property only drives numeric
        # ticks, which are switched off via SetNumberOfLabels(0)).
        bar.GetAnnotationTextProperty().SetFontSize(13)
        # Title is deliberately smaller than the particle names (13 -> 8, a
        # >1/3 reduction) and kept apart by bold + its top position; the
        # names carry the information, the title only labels the legend.
        bar.GetTitleTextProperty().SetFontSize(8)
        bar.GetTitleTextProperty().BoldOn()
        bar.SetVerticalTitleSeparation(6)
        bar.DrawFrameOff()
        bar.DrawBackgroundOff()

    def set_dark_theme(self, is_dark):
        if self._released:
            return
        self._is_dark = is_dark
        super().set_dark_theme(is_dark)
        self._style_bar()
        self._tint_world()
        self._apply_track_theme()
        ax = self._corner_axes_actor
        if ax is not None:
            lab = (1.0, 1.0, 1.0) if is_dark else (0.08, 0.08, 0.12)
            for cap in (ax.GetXAxisCaptionActor2D(),
                        ax.GetYAxisCaptionActor2D(),
                        ax.GetZAxisCaptionActor2D()):
                cap.GetCaptionTextProperty().SetColor(*lab)
        self.render()


# ---------------------------------------------------------------------------
# Dialog: VTK view (top, with its toolbar) + filter panel (bottom)
# ---------------------------------------------------------------------------

class TrajectoryViewerDialog(QDialog):
    """Trajectory + geometry preview for one task run.

    Opens showing every track in <work>/Traj.csv. The eventID / trackID /
    parentID ranges and the particle selection only narrow the view when the
    user clicks "Apply Filter" (the panel itself never auto-applies).
    """

    # Same defaults the user asked for: event 0-99, track 1-99, parent 0-99.
    DEFAULT_EVENT = (0, 99)
    DEFAULT_TRACK = (1, 99)
    DEFAULT_PARENT = (0, 99)

    def __init__(self, title, root_node, traj_path, dark=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._traj_path = traj_path
        self._stamp = file_stamp(traj_path)
        self._all_tracks = []
        self._load_msg = ""
        self._load_msg_shown = False
        # Follow the app's current light/dark theme, exactly like the voxel
        # result viewer: the main window passes dark=self._dark_theme in, and
        # the menu toggle pushes set_dark_theme() into every open viewer. The
        # dark mode keeps the classic palette (bright Geant4 particle colours
        # from solver/rad4space/plt_traj/plot_traj_vtk-test.py).
        self._dark = dark
        self.resize(1180, 820)
        self.setMinimumSize(860, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Stack order: VTK render fills the top, its toolbar (Clip / Edges /
        # axis views ...) sits just under the view, and the filter panel is
        # docked at the bottom of the window.
        self._view = TrajectoryViewWidget(self)
        if root_node is not None:
            self._view.build_scene(root_node)
            self._view.style_geometry_preview(
                world_nodes_from_root(root_node))
        self._view.set_dark_theme(dark)   # scene + toolbar follow the app theme
        lay.addWidget(self._view, 1)

        self._build_filter_panel(lay)

        self._apply_theme(dark)   # chrome palette after all child widgets exist
        self._load()              # parse CSV -> self._all_tracks
        self._show_all()          # preview everything
        # Frame the geometry + full track cloud once on open; later "Apply
        # Filter" keeps the current viewpoint so the user can compare.
        try:
            ren = getattr(getattr(self._view, "_scene", None), "renderer", None)
            if ren is not None:
                ren.ResetCamera()
                self._view.render()
        except Exception:
            pass

    # -- data -----------------------------------------------------------------
    def _load(self):
        self._stamp = file_stamp(self._traj_path)
        self._load_msg = ""
        try:
            self._all_tracks = load_tracks_from_csv(self._traj_path)
            return True
        except OSError as exc:
            self._load_msg = f"cannot read Traj.csv: {exc}"
        except Exception as exc:  # malformed row / missing column
            self._load_msg = f"cannot parse Traj.csv: {exc}"
        self._all_tracks = []
        return False

    # -- filter panel -----------------------------------------------------------
    def _build_filter_panel(self, outer):
        panel = QWidget(self)
        panel.setObjectName("trajFilterPanel")
        box = QGridLayout(panel)
        box.setContentsMargins(6, 4, 6, 4)
        box.setHorizontalSpacing(10)
        box.setVerticalSpacing(4)

        def make_range(label, default):
            t = QLabel(label)
            lo = QSpinBox()
            hi = QSpinBox()
            for sb in (lo, hi):
                sb.setRange(0, 2_000_000_000)
                sb.setFixedWidth(92)
                sb.setKeyboardTracking(False)
            lo.setValue(default[0])
            hi.setValue(default[1])
            dash = QLabel("\u2013")  # en dash
            row = QWidget()
            r = QHBoxLayout(row)
            r.setContentsMargins(0, 0, 0, 0)
            r.setSpacing(4)
            r.addWidget(lo)
            r.addWidget(dash)
            r.addWidget(hi)
            return t, row, lo, hi

        el, erow, elo, ehi = make_range("eventID", self.DEFAULT_EVENT)
        tl, trow, tlo, thi = make_range("trackID", self.DEFAULT_TRACK)
        pl, prow, plo, phi = make_range("parentID", self.DEFAULT_PARENT)
        self._ev = (elo, ehi)
        self._tr = (tlo, thi)
        self._par = (plo, phi)

        box.addWidget(el, 0, 0, Qt.AlignmentFlag.AlignRight)
        box.addWidget(erow, 0, 1)
        box.addWidget(tl, 0, 2, Qt.AlignmentFlag.AlignRight)
        box.addWidget(trow, 0, 3)
        box.addWidget(pl, 0, 4, Qt.AlignmentFlag.AlignRight)
        box.addWidget(prow, 0, 5)

        # Particle row: one sub-row spanning exactly the same columns as the
        # three range inputs above (0..5). The checkboxes used to be dropped
        # one-per-grid-column, which interleaved them with the range-row
        # columns and pushed "All"/"None" far off to the right. Now the first
        # checkbox starts flush under "eventID" and the flexible gaps make the
        # row end exactly at the parentID box (no stray whitespace, no run-on).
        self._part_cbs = {}
        prow = QWidget(self)
        pr = QHBoxLayout(prow)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(6)
        first = True
        for name in KNOWN_PARTICLES:
            cb = QCheckBox(name)
            cb.setChecked(True)
            self._part_cbs[name] = cb
            if not first:
                pr.addStretch(1)
            first = False
            pr.addWidget(cb)
        other = QCheckBox("other")
        other.setChecked(True)
        other.setToolTip("particles not listed above (ions, pi\u00b1, muons, ...)")
        self._part_cbs["_other"] = other
        pr.addStretch(1)
        pr.addWidget(other)
        box.addWidget(prow, 1, 0, 1, 6)

        # Actions: both buttons stacked vertically in the blank area to the
        # right of parentID. The stack spans the two content rows above (its
        # total height is exactly 2 rows) and each button keeps a compact
        # width; the flexible column behind it absorbs extra width when the
        # window is dragged wider, so the buttons never drift.
        self._btn_apply = QPushButton("Apply Filter")
        self._btn_apply.setToolTip(
            "narrow the preview to the ranges / particles above")
        self._btn_apply.clicked.connect(self._apply_filter)
        self._btn_reset = QPushButton("Show All")
        self._btn_reset.setToolTip(
            "reset the panel to its defaults and preview every track again")
        self._btn_reset.clicked.connect(self._show_all)
        acol = QWidget(self)
        ac = QVBoxLayout(acol)
        ac.setContentsMargins(0, 0, 0, 0)
        ac.setSpacing(4)
        for b in (self._btn_apply, self._btn_reset):
            b.setFixedWidth(100)
            ac.addWidget(b, 1)
        box.addWidget(acol, 0, 6, 2, 1)

        box.setColumnStretch(7, 1)
        outer.addWidget(panel)

    def _set_particle_checks(self, on):
        for cb in self._part_cbs.values():
            cb.setChecked(on)

    def _particle_filter(self):
        wanted = {n for n, cb in self._part_cbs.items()
                  if n != "_other" and cb.isChecked()}
        return wanted, self._part_cbs["_other"].isChecked()

    # -- actions ---------------------------------------------------------------
    def _apply_filter(self):
        ev = tuple(sorted(sb.value() for sb in self._ev))
        tr = tuple(sorted(sb.value() for sb in self._tr))
        par = tuple(sorted(sb.value() for sb in self._par))
        wanted, other_ok = self._particle_filter()
        shown = filter_tracks(self._all_tracks, ev, tr, par, wanted, other_ok)
        self._refresh_view(shown)

    def _show_all(self):
        # Reset the panel to the defaults and preview everything.
        for lo, hi, dflt in ((self._ev[0], self._ev[1], self.DEFAULT_EVENT),
                             (self._tr[0], self._tr[1], self.DEFAULT_TRACK),
                             (self._par[0], self._par[1], self.DEFAULT_PARENT)):
            lo.setValue(dflt[0])
            hi.setValue(dflt[1])
        self._set_particle_checks(True)
        if self._load_msg:
            # The old "showing n tracks" status line is gone; surface a
            # read/parse failure once instead (later auto-refresh rewrites
            # must not spam modal dialogs).
            if not self._load_msg_shown:
                self._load_msg_shown = True
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "Trajectory CSV", self._load_msg))
            self._view.clear_tracks()
            return
        self._refresh_view(self._all_tracks)

    def _refresh_view(self, tracks):
        self._view.show_tracks(tracks)

    def refresh_if_changed(self, path):
        """Reload the CSV if the solver re-wrote it (returns True on reload)."""
        if os.path.abspath(path) != os.path.abspath(self._traj_path):
            return False
        stamp = file_stamp(path)
        if stamp is None or stamp == self._stamp:
            return False
        self._traj_path = path
        if self._load():
            self._show_all()
            return True
        return False

    # -- theme -----------------------------------------------------------------
    def _apply_theme(self, dark):
        """Style the chrome (filter panel + dialog background) for a theme.

        The dialog background is painted with a palette + autoFillBackground,
        and every child is given the same palette, so the plain rows (toolbar
        strip below the GL view, the eventID/track/parent and particle rows)
        sit flush on one flat surface - no white strips. The controls that the
        Windows native style would still paint with system colours
        (QPushButton / QSpinBox / QCheckBox) are themed by _theme_chrome() with
        widget-scoped stylesheets. A stylesheet is deliberately never applied
        to the dialog itself: see the note before _theme_chrome().
        """
        self._dark = dark
        pal = QPalette()
        if dark:
            pal.setColor(QPalette.ColorRole.Window, QColor(28, 30, 34))
            pal.setColor(QPalette.ColorRole.Base, QColor(22, 24, 28))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(34, 37, 42))
            pal.setColor(QPalette.ColorRole.Text, QColor(233, 236, 240))
            pal.setColor(QPalette.ColorRole.WindowText, QColor(233, 236, 240))
            pal.setColor(QPalette.ColorRole.Button, QColor(46, 50, 56))
            pal.setColor(QPalette.ColorRole.ButtonText, QColor(233, 236, 240))
            pal.setColor(QPalette.ColorRole.Highlight, QColor(40, 100, 180))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(48, 52, 58))
            pal.setColor(QPalette.ColorRole.ToolTipText, QColor(233, 236, 240))
            css = (
                "QSpinBox { background:#16181c; color:#e9ecf0;"
                " border:1px solid #3a3f46; border-radius:3px; }"
                "QCheckBox { color:#e9ecf0; }"
                "QPushButton { background:#3a3f46; color:#e9ecf0;"
                " border:1px solid #565c66; border-radius:3px;"
                " padding:3px 10px; }"
                "QPushButton:hover { background:#454b54; }"
                "QPushButton:pressed { background:#2f333b; }"
            )
        else:
            pal.setColor(QPalette.ColorRole.Window, QColor(242, 244, 247))
            # Base stays == Window so the whole bottom area is one flat
            # light-grey surface (spinboxes keep their explicit white
            # background from their own stylesheet).
            pal.setColor(QPalette.ColorRole.Base, QColor(242, 244, 247))
            pal.setColor(QPalette.ColorRole.Text, QColor(30, 32, 36))
            pal.setColor(QPalette.ColorRole.WindowText, QColor(30, 32, 36))
            pal.setColor(QPalette.ColorRole.Button, QColor(235, 237, 240))
            pal.setColor(QPalette.ColorRole.ButtonText, QColor(30, 32, 36))
            pal.setColor(QPalette.ColorRole.Highlight, QColor(40, 100, 180))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 230))
            pal.setColor(QPalette.ColorRole.ToolTipText, QColor(30, 32, 36))
            css = (
                "QSpinBox { background:#ffffff; color:#1e2024;"
                " border:1px solid #c8ccd2; border-radius:3px; }"
                "QCheckBox { color:#1e2024; }"
                "QPushButton { background:#e9ebee; color:#1e2024;"
                " border:1px solid #c2c6cc; border-radius:3px;"
                " padding:3px 10px; }"
                "QPushButton:hover { background:#dfe2e6; }"
                "QPushButton:pressed { background:#d3d7db; }"
            )
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        for w in self.findChildren(QWidget):
            w.setPalette(pal)
        # A stylesheet is never set on the dialog itself: setting one would
        # activate Qt's style engine across the whole subtree - including the
        # native QVTK child window - and the engine repaints every plain row /
        # toolbar strip from a hard-coded colour instead of the palette above.
        # That is exactly what painted the Edges/Clip/Fit toolbar row and the
        # eventID / particle rows as white bands in light mode (see the note
        # in VoxelResultViewer.set_dark_theme for the same reasoning). The
        # chrome controls are themed individually instead, so the stylesheet
        # engine never reaches the rows or the VTK view around them.
        self._theme_chrome(css)

    def _theme_chrome(self, css):
        """Theme the filter-panel controls with widget-scoped stylesheets.

        Each QSpinBox / QCheckBox / QPushButton in the filter panel gets the
        stylesheet on itself - it styles only that control (and its own
        children), never the rows it sits on or the VTK view. These are the
        controls the Windows native style would otherwise paint with system
        colours no matter what the palette says.
        """
        for pair in (self._ev, self._tr, self._par):
            for sb in pair:
                sb.setStyleSheet(css)
        for cb in self._part_cbs.values():
            cb.setStyleSheet(css)
        for b in (self._btn_apply, self._btn_reset):
            b.setStyleSheet(css)

    def set_dark_theme(self, is_dark):
        """Theme switch driven by the main-window light/dark toggle.

        Same contract as VoxelResultViewer: re-theme the chrome around the
        view, then ask the VTK widget to swap scene background / toolbar /
        particle LUT / colorbar text.
        """
        self._apply_theme(is_dark)
        if self._view is not None:
            self._view.set_dark_theme(is_dark)

    def closeEvent(self, event):
        """Release the corner marker / VTK context before the dialog closes."""
        try:
            self._view.cleanup()
        except Exception:
            pass
        super().closeEvent(event)

