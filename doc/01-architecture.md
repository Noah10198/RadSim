# 01 · Architecture

> Code covered: `main.py`, `app/`, `core/`, `vtk_engine/`, `ui/`, `utils/`

## Contents

- [1. What RadSim is](#1-what-radsim-is)
- [2. Layers](#2-layers)
- [3. Module dependency graph](#3-module-dependency-graph)
- [4. The four key data flows](#4-the-four-key-data-flows)
- [5. Process and thread model](#5-process-and-thread-model)
- [6. Singletons and long-lived objects](#6-singletons-and-long-lived-objects)
- [7. Signal routing](#7-signal-routing)
- [8. Global conventions](#8-global-conventions)
- [9. Extension points](#9-extension-points)
- [10. Related documents](#10-related-documents)

## 1. What RadSim is

RadSim is the **graphical front end for rad4space (a Geant4 batch solver)**. It performs no
physics of its own; its job comes down to three things:

1. **Understand the geometry**: parse GDML, rebuild Geant4's two-level *logical volume /
   physical placement* model and render it in 3D.
2. **Translate the configuration**: turn the forms on screen into a single `run.mac`.
3. **Dispatch and present**: run the solver as a child process, then collect its console output
   and result CSVs into visualization views.

The system boundary is therefore crisp: **the solver is a black box and the macro file is the
only interface** (see [03-mac-builder.md](03-mac-builder.md)).

## 2. Layers

| Layer | Directory | Responsibility | May depend on |
|---|---|---|---|
| Entry | `main.py` | Create `QApplication`, assemble the main window | `app` |
| Orchestration | `app/main_window.py` | Layout, signal wiring, task orchestration, project I/O, thread management | every layer below |
| Domain | `core/` | GDML parse/write-back, materials library, macro generation, run dispatch, project I/O | only `PyQt6.QtCore` (`QObject`/`pyqtSignal`/`QSettings`/`QProcess`) |
| Rendering | `vtk_engine/` | VTK scene and solid factory | `vtkmodules`, `core` |
| Presentation | `ui/`, `ui/dialogs/` | Widgets and dialogs | `core`, `vtk_engine` |
| Infrastructure | `utils/logger.py` | Asynchronous logging singleton | none |
| Resources | `data/` | `element.xml`, `nist.txt` | — |
| External | `solver/` | rad4space source, build output, run output | — |

**Dependencies point one way**: `ui → core / vtk_engine → core`. Apart from a few infrastructure
classes from `PyQt6.QtCore`, `core` references no UI at all, so the domain logic can be tested
without a window.

`ui/dialogs/physics_config.py` and `ui/dialogs/gps_source.py` physically live in the UI folder,
yet their `macro_lines(cfg)` helpers are **pure functions** called back by
`core/mac_builder.py`. That is the only `core → ui` reference in the code base, a deliberate
trade-off so that the knowledge of a macro command exists in exactly one place.

## 3. Module dependency graph

```
                          main.py
                             │
                     app/main_window.py ─────────────────┐
                        │        │        │               │
          ┌─────────────┤        │        │               │
          ▼             ▼        ▼        ▼               ▼
     ui/*.py     ui/dialogs/*.py  core/*.py        utils/logger.py
          │             │             │
          │             └──► (macro_lines, pure functions)
          ▼                           ▼
     vtk_engine/*.py  ◄──────── GdmlAgent / GdmlParser / GdmlWriter
          │                           │
          ▼                           ▼
      vtkmodules                 data/element.xml
                                 data/nist.txt

     core/run_manager.py ──QProcess──► solver/rad4space/build/Release/rad4space.exe
                                                      │
                                                      ▼
                                          solver/runs/<task>/*.csv
```

## 4. The four key data flows

### 4.1 Geometry flow (import)

```
.gdml ─► GdmIParser.parse_file ─► GdmlNode tree ─► GdmlAgent (singleton)
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                  ▼
            ProjectTreeWidget   VtkScene.build_from_tree   MacPreview
              (left tree)          (centre, 3D)         (right, macro preview)
```

For large files (≥ 500 KB) `parse_file` runs on the `_ImportWorker` thread and hands the result
back to the main thread through a queued signal, where the tree and the scene are rebuilt **in
one pass**.

### 4.2 Configuration flow (editing)

```
dialog form ─► RunTask.{particle, physics, calculate, analysis_config}
                    │
                    └─► MacPreviewDock live preview via build_mac_text(...)
```

The settings are written straight onto the `RunTask` object (the dialog holds the same
reference) and serialized into `project.json` on save.

### 4.3 Execution flow (running)

```
Run launcher ─► MainWindow._start_selected_tasks ─► RunManager.start(names)
                                                       │
                          ┌────────────────────────────┘
                          ▼
       write_workdir() → run.mac → QProcess(rad4space run.mac)
                          │                    │
                          ▼                    ▼
                   run.log (redirected)   out_*.csv / h1_*.csv
```

### 4.4 Result flow (presentation)

```
out_*.csv ─► probe_result_viewer.build_result_groups ─► Results subtree in the project tree
rad4space_h1_*.csv ─┘                                      │
                                                           ├─► ProbeResultChartDialog (curves)
Traj.csv ──────────────────────────────────────────────────┴─► TrajectoryViewerDialog (trajectory)
```

`probe_result_viewer.py` deliberately imports neither Qt nor matplotlib so that building the
project tree stays cheap.

## 5. Process and thread model

| Scenario | Mechanism | Notes |
|---|---|---|
| All UI / VTK rendering | main thread | neither VTK nor Qt is thread-safe, so every scene operation stays on the main thread |
| Large GDML parse (≥ 500 KB) | `QThread` + `_ImportWorker` (`moveToThread`) | calls only the thread-safe `parse_file_only`; the result waits in `_pending_gdml_node` and replaces the model back on the main thread |
| Solver run | `QProcess` child process | occupies no Python thread; a `QTimer` heartbeat advances the progress every 300 ms |
| Logging | `AsyncLogger` singleton | written from a background queue, consumed by the widget injected through `set_system_log_widget` |
| Tree / scene build | main thread + throttled `processEvents` | on large models `_make_rebuild_flusher` repaints the progress dialog every 0.1 s so the window does not appear frozen |

**No mutable state is shared between threads**: a worker thread only produces a *parse result*
and never touches UI or `GdmlAgent` state. `GdmlAgent` reuses a single `GdmIParser` instance whose
mutable state is likewise only ever touched on the main thread.

## 6. Singletons and long-lived objects

| Object | Location | Lifetime |
|---|---|---|
| `GdmlAgent` | `core/gdml_agent.py` | process-wide singleton, owns all geometry data and overrides |
| `AsyncLogger` | `utils/logger.py` | process-wide singleton |
| `VtkSolidFactory` | `vtk_engine/vtk_solid_factory.py` | singleton with an internal `_geometry_cache` |
| `RunManager` | `MainWindow.__init__` | lives as long as the main window, `max_concurrent=2` |
| Run launcher / task monitor | created lazily by `MainWindow` | built on first open, reused afterwards |
| Configuration dialogs | cached per task | `_analysis_dialogs` / `_particle_dialogs` / `_physics_dialogs` / `_calculate_dialogs`, cache cleared on close |
| Result viewers | cached per task | `_voxel_viewers` / `_traj_viewers` |

## 7. Signal routing

There is no central event bus; connections are made **where the two ends are known**, along three
main paths:

| Source | Signal | Destination |
|---|---|---|
| `RibbonToolBar` | `import_clicked` / `load_clicked` / `save_clicked` / `run_clicked` / `stop_clicked` / `reset_view_clicked` / `status_clicked` / `solver_setting_clicked` / `theme_toggled` / `help_clicked` | `MainWindow._on_*` |
| `ProjectTreeWidget` | `node_selected` / `visibility_changed` / `task_action` / `task_context` | `MainWindow._on_node_selected` / `_on_visibility_changed` / `_on_task_action` / `_on_task_context` |
| `VtkWidget` | `node_picked` | `MainWindow._on_node_picked` (tree and 3D selection follow each other) |
| `RunManager` | `task_started` / `task_progress` / `task_finished` / `all_finished` / `task_added` | the main window plus the two monitor windows |
| `GdmlNode` | `data_changed` | triggers a scene/tree refresh |

## 8. Global conventions

| Item | Convention |
|---|---|
| Length unit | **mm** everywhere in the UI and internally; converted to cm inside the macro as the solver requires (see doc 03) |
| Angle unit | **deg** |
| Density | g/cm³ |
| Task directory name | `safe_task_name()`: any character outside `[A-Za-z0-9_.\-]` becomes `_` |
| Task identity | the task name is the dictionary key (`RunManager._tasks: name → RunTask`), so **names must be unique** |
| Persistence | `QSettings("RadSim", "RadSim")`, keys `solver/executable`, `solver/qt_bin_dir`, `solver/results_root` |
| Logging | always `AsyncLogger.log_system(...)`, never a bare `print` |
| Exceptions | caught in the UI layer, reported with `QMessageBox.warning` and logged; never re-raised |

## 9. Extension points

| To add | Change |
|---|---|
| A new GDML solid type | add `_parse_xxx` in `core/gdml_parser.py`; add a dispatch branch in `_build_polydata` of `vtk_engine/vtk_solid_factory.py`; extend `collision_detector.compute_half_size` |
| A new scoring quantity | `ui/dialogs/analysis_common.QUANTITY_TYPES` (the authority); keep `core/mac_builder._HIST_XUNIT` and `_QUANTITY_UNIT` in step |
| A new analysis mode | a new dialog + a branch in `core/mac_builder.scoring_block()` + grouping in `probe_result_viewer` + a result node in the project tree + `main_window._refresh_task_results` |
| A new result viewer | a new dialog under `ui/`, dispatched by file type in `result_viewer.py` or `main_window` |
| A new toolbar button | a signal and button in `ui/ribbon_toolbar.py`, connected in `main_window._connect_signals()` |

## 10. Related documents

- [02 · GDML Pipeline](02-gdml-pipeline.md)
- [03 · run.mac Generation](03-mac-builder.md)
- [04 · Run Execution](04-execution.md)
- [05 · Analysis and Results](05-analysis.md)
- [06 · Project Save and Load](06-project-io.md)
- [07 · Visualization](07-visualization.md)
- [08 · UI Reference](08-ui-reference.md)
- [09 · Data Formats](09-data-formats.md)
- [10 · Environment and Troubleshooting](10-troubleshooting.md)
