# 07 · Visualization

> Source: `vtk_engine/vtk_scene.py`, `vtk_engine/vtk_solid_factory.py`, `ui/vtk_widget.py`,
> `ui/vtk_view_window.py`, `ui/voxel_result_viewer.py`, `ui/trajectory_viewer.py`,
> `ui/probe_chart_dialog.py`

## Contents

- [1. Components](#1-components)
- [2. VtkScene](#2-vtkscene)
- [3. VtkSolidFactory](#3-vtksolidfactory)
- [4. VtkWidget](#4-vtkwidget)
- [5. Voxel result viewer](#5-voxel-result-viewer)
- [6. Trajectory viewer](#6-trajectory-viewer)
- [7. Chart dialogs](#7-chart-dialogs)
- [8. Things to watch](#8-things-to-watch)

## 1. Components

| Component | Role |
|---|---|
| `VtkScene` | scene container: renderer, actor tree, picking, camera |
| `VtkSolidFactory` | `GdmlNode` → `vtkPolyData` / `vtkActor` (singleton with a geometry cache) |
| `VtkWidget` | the 3D view: QVTK interactor + toolbar + clipping panel |
| `VtkPreviewWidget` | a lightweight derivative keeping only the viewport, for in-dialog previews |
| `VoxelResultViewer` | 3D volume rendering of voxel results |
| `TrajectoryViewerDialog` | particle trajectory polylines |
| `ProbeResultChartDialog` | bar charts and spectrum step curves |

## 2. VtkScene

Public API: `build_from_tree`, `clear`, `add_node`, `remove_node`, `set_visible`, `highlight`,
`reset_camera`, `fit_all`, `set_interactor`, `set_override_provider`.

**Placement accumulation**: the factory only produces geometry in local coordinates; position and
rotation are accumulated up the parent chain by `_apply_node_placement()` and written onto the
actor:

- `PHYVOL_NODE` accumulates `placement` (which an override provider may replace);
- `GDML_FILE` accumulates `file_transform`, but **`WORLD_NODE` itself is excluded** (the world box
  stays put);
- rotations are negated: GDML uses the passive (frame) convention while VTK's `SetOrientation` is
  an active rotation, hence `SetOrientation(-rx, -ry, -rz)`.

**Picking**: an internal `vtkCellPicker` plus a left-button observer → `VtkWidget.node_picked(str)`
→ the main window locates the tree node; the reverse direction, "tree selection → 3D highlight",
goes through `highlight()`, together forming the two-way link.

## 3. VtkSolidFactory

| GDML tag | How it is built | Notes |
|---|---|---|
| `box` | `vtkCubeSource` | |
| `sphere` / `orb` | `vtkSphereSource` (Theta/Phi = 48) | **hollow spheres with `rmin > 0` are not implemented** |
| `tube` / `tubs` | `rmin <= 0` → `vtkCylinderSource`; otherwise a hand-built mesh (outer and inner wall plus caps) | caps are generated only for a full 360° |
| `cone` | equal top and bottom radii delegate to tube; otherwise a 16-segment frustum approximation merged | the inner radius takes no part |
| `torus` | `vtkParametricTorus`, boolean Difference when `rmin > 0` | the only user of boolean operations |
| `ellipsoid` | unit sphere + `vtkTransform.Scale` | `zcut` unused |
| `tessellated` | `vtkPolyData` built directly (each quad split into two triangles) | an empty vertex list returns nothing |
| `polycone` / `genericPolycone` | built segment by segment from the z-planes and merged | no boolean operations |

Unsupported tags (`trap`, `trd`, `para`, `hype`, `polyhedra`, `xtru`, `arb8`, `cutTube`, …) make
`_build_polydata` return `None` and are **skipped silently**; the main window counts them at import
time and reports them once.

**Geometry cache**: `_geometry_cache` lets several instances of the same source volume share one
polydata and mapper; the key is the tag plus `solid_params` (floats at six decimals) and
`clear_cache()` runs before every full rebuild.

**Colour**: `color_key = entry_id or name` → the first four md5 digits modulo a 20-colour palette,
stable and independent of the material name (the material preset table in `_COLORS` is legacy code
that is not wired in). `WORLD_NODE` is drawn with `Opacity 0.15` and a wireframe.

## 4. VtkWidget

Buttons: ▣ Transparency/Solid, ✕ Edges, ✂ Clip, ⌂ Fit, ◻ Ortho/Perspective, X/Y/Z views. A
`vtkCubeAxesActor` provides the axes and size annotations.

### WId re-binding (the key mechanism)

The legacy `QVTKRenderWindowInteractor` recreates its native window after a hide/show, so the WId
changes while `vtkRenderWindow` is still bound to the old HWND/HDC — which shows up as a screen
full of `wglMakeCurrent failed`. `_ensure_window_bound()`:

1. read the current `winId()`; if it equals `_bound_wid`, return;
2. if a window was bound before (`_bound_once`), call `Finalize()` first to release the old
   context;
3. `SetWindowInfo(str(wid))` lets VTK rebuild the context for the new HWND;
4. re-apply `SetSwapControl(0)` (a new context resets vsync).

`_maybe_start_interactor()` makes sure `Start()` runs exactly once and only after the first show.

### GL initialization and software fallback

- `SetMultiSamples(0)` disables MSAA;
- try the GPU first (`SetOffScreenRendering(False)`) and parse `ReportCapabilities()` to confirm
  hardware OpenGL was really obtained; if not, fall back to `SetOffScreenRendering(True)`
  (software / Mesa);
- `SetSwapControl(0)` disables vsync: a few hundred thousand triangles render offscreen in a few
  milliseconds, so vsync only drags that to 16.7 ms per frame and makes dragging stutter.

### Interaction as it stands

- rotate/pan/zoom: `vtkInteractorStyleTrackballCamera`;
- picking: single click;
- **rubber-band selection and a right-click context menu are not implemented**;
- clipping de-duplicates by mapper address via `_mapper_addr(m)` (`GetAddressAsString`) rather than
  `id(m)` — VTK for Python does not guarantee one wrapper per C++ mapper.

## 5. Voxel result viewer

- **Parsing**: CSV rows `iX,iY,iZ,value[,val2,entry]`, taking `parts[3]`; iZ varies fastest in the
  file, so the array is stored with `idx = ix + nx*(iy + ny*iz)`;
- **Grid**: `spacing = 2*half/nbin`, `origin = center - half` (mm); `_edge_boundary_lattice`
  resamples the per-cell data onto an `(nbin+1)³` boundary lattice so that the volume rendering
  covers exactly `center ± half`;
- **Rendering**: `vtkImageData` + `vtkFixedPointVolumeRayCastMapper` + `vtkVolume`, linear
  interpolation, no lighting; a five-stop blue → cyan → green → yellow → red colour scale;
- **Adjustable**: opacity slider (10–100, default 95), clip plane, Fit/Ortho/XYZ views;
- **Background geometry**: `set_geometry_ghost(True, wireframe=True)`, neutral-colour wireframe with
  `LineWidth 2.0`;
- **Refresh after a re-run**: `refresh_if_changed()` uses `(mtime_ns, size)` to decide whether a
  reload is needed;
- `WA_DeleteOnClose = True`: keeps a cached hidden window from reusing a stale HWND/HDC.

## 6. Trajectory viewer

- **Parsing**: `csv.DictReader` with the required columns `eventID, trackID, parentID, particle,
  step, x, y, z`; grouped by `(event, track)`, sorted by `step` within a group, where step 0 is the
  vertex;
- **Lines**: **one `vtkPolyLine` per track** (never joined across events), the particle type stored
  as cell data and coloured through `SetScalarModeToUseCellData()` plus a lookup table;
- **Colours**: Geant4's `TrajectoryDrawByParticleID` defaults (gamma green / e- red / e+ blue /
  π± magenta / proton cyan / neutron yellow / ions orange / anything else grey); trajectory colours
  are the same under both themes;
- **Filtering**: three ranges for event / track / parent plus particle checkboxes; only **Apply
  Filter** takes effect and **Show All** resets. **There is no animation playback.**

## 7. Chart dialogs

- `group["kind"] == "quantity"` → a bar chart, eight colours cycling, the value printed above each
  bar (`%.6g` or `%.3e`);
- `group["kind"] == "histogram"` → `ax.step(..., where="post")` step curves with a legend;
- two checkboxes, normalisation (`% of total counts`) and a logarithmic x axis, redraw immediately;
- **export to PNG** (`dpi=150`, `figsize` derived from the canvas pixels);
- when matplotlib is missing: the canvas degrades to a `QLabel` telling the user to
  `pip install matplotlib`, the normalisation / log / export controls are not created, and
  `_replot()` / `_save_png()` return immediately instead of raising.

## 8. Things to watch

| Item | Explanation |
|---|---|
| GL context | when closing the main window, **all secondary QVTK windows must be closed first**; otherwise the log is flooded with `wglMakeCurrent failed` |
| Scene rebuild | `VtkWidget` reuses one instance, so a rebuild starts with `clear_cache()` + `clear()` |
| Memory | a voxel field is an `(nbin+1)³` double array — watch memory once `nbin` grows |
| Threading | every VTK operation must happen on the main thread |
| Precision | spheres, cylinders and tori are fixed at 48 segments around the circumference, cones at 16 |
