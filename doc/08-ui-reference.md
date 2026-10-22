# 08 · UI Reference

> Source: `app/main_window.py`, `ui/ribbon_toolbar.py`, `ui/project_tree.py`,
> `ui/mac_preview.py`, `ui/dialogs/*`

## Contents

- [1. Main window layout](#1-main-window-layout)
- [2. Ribbon toolbar](#2-ribbon-toolbar)
- [3. Project tree](#3-project-tree)
- [4. Macro preview on the right](#4-macro-preview-on-the-right)
- [5. Log and status bar](#5-log-and-status-bar)
- [6. Dialog inventory](#6-dialog-inventory)
- [7. Result viewers](#7-result-viewers)
- [8. Theme](#8-theme)
- [9. Interaction rules](#9-interaction-rules)

## 1. Main window layout

```
┌───────────────────────────────────────────────────────────────────────┐
│ QToolBar ── RibbonToolBar                                              │
├──────────────┬────────────────────────────────────┬───────────────────┤
│ QDockWidget  │  QSplitter(Vertical)               │ QDockWidget       │
│ "Project"    │   ├─ QStackedWidget _center_stack  │ "Run Macro        │
│  ProjectTree │   │   0 = QLabel placeholder        │  Preview"         │
│  Widget      │   │   1 = VtkWidget 3D view         │  MacPreviewDock   │
│              │   └─ QTextEdit log panel            │                   │
├──────────────┴────────────────────────────────────┴───────────────────┤
│ status bar QLabel _status_label                                        │
└───────────────────────────────────────────────────────────────────────┘
```

Index 0 of `_center_stack` is the placeholder shown before a geometry is imported; after a
successful import it switches to index 1. The central `QSplitter` splits 3:1 (600:150 initially).

## 2. Ribbon toolbar

| Button | Signal | Main-window slot | Behaviour |
|---|---|---|---|
| 📁 Import GDML | `import_clicked` | `_on_import_gdml` | import geometry (≥ 500 KB goes to a background thread) |
| 🧾 Load Project | `load_clicked` | `_load_project` | open `project.json` |
| 💾 Save Project | `save_clicked` | `_save_project` | pick a directory the first time, then save in place |
| 🎯 Reset View | `reset_view_clicked` | `_on_reset_view` | reset the camera |
| ▶️ Run | `run_clicked` | `_on_run` | open the run launcher |
| 🟢 Idle / 🔄 / ⚠️ / ✅ | `status_clicked` | `_on_status_clicked` | open the task monitor; the icon follows the state |
| ⏹ Stop | `stop_clicked` | `_on_stop` | `RunManager.stop_all()` |
| ⚙️ Solver Setting | `solver_setting_clicked` | `_on_solver_setting` | configure the solver path |
| 🌙 / ☀️ Theme | `theme_toggled` | `_toggle_theme` | light/dark theme |
| ❓ Help | `help_clicked` | `_on_help` | about/help |

## 3. Project tree

### Hierarchy

```
Project
├── Geometry
│   └── <GDML file>            ☑ checkable
│       ├── Solids
│       │   └── <solid def>    not checkable (text carries [tag] for non-box solids)
│       └── World
│           └── <placement>    ☑ checkable (drills down to PHYSVOL, no separate node)
└── Tasks
    └── <task name>
        ├── Calculate Setting [N threads]
        ├── Particle Setting
        ├── Physics Process
        ├── Analysis
        │   ├── Real World
        │   ├── Probe
        │   └── Voxel
        └── Results
```

### Interaction

| Interaction | Effect |
|---|---|
| click a node | `node_selected(str)` → 3D highlight |
| check/uncheck | `visibility_changed(str, bool)` → scene visibility |
| click in the 3D view | `node_picked(str)` → locate in the tree (the two-way link) |
| double-click a task child | open the matching configuration dialog |
| double-click a result node | open the matching viewer |
| right-click a task node | `task_context` / `task_action` report the action back (new task, rename, duplicate, delete, run, …) |

Task nodes also show state markers: thread count, whether particle/physics/analysis are
configured, and the run status.

## 4. Macro preview on the right

`MacPreviewDock`: a drop-down at the top switches tasks, the body shows the result of
`core.mac_builder.build_mac_text(gdml_path, task)` in a monospaced font. After any configuration is
saved the main window calls `_refresh_mac_preview()` to re-render; a `task_changed(str)` signal
makes `_render_mac_preview` switch tasks.

## 5. Log and status bar

- log: a `QTextEdit` injected through `AsyncLogger.set_system_log_widget()`; read-only and
  auto-scrolling;
- status bar: `Files loaded: N`, the run state, and the most recent action.

## 6. Dialog inventory

| File | Class | Kind | Opened by | Writes |
|---|---|---|---|---|
| `calculate_setting_dialog.py` | `CalculateSettingDialog` | config | `_open_calculate_setting` | `task.calculate.n_threads` |
| `particle_dialog.py` | `ParticleDialog` | config | `_open_particle_dialog` | `task.particle` |
| `physics_dialog.py` | `PhysicsDialog` | config | `_open_physics_dialog` | `task.physics` |
| `realworld_dialog.py` | `RealWorldDialog` | config | `_open_analysis_dialog("realworld")` | `analysis_config["realworld"]` |
| `probe_dialog.py` | `ProbeDialog` | config | `_open_analysis_dialog("probe")` | `analysis_config["probe"]` |
| `voxel_dialog.py` | `VoxelDialog` | config | `_open_analysis_dialog("voxel")` | `analysis_config["voxel"]` |
| `solver_setting_dialog.py` | `SolverSettingDialog` | config | `_on_solver_setting` | QSettings |
| `run_monitor.py` | `RunMonitorDialog` / `TaskMonitorDialog` | run | `_ensure_run_launcher` / `_ensure_task_monitor` | — |
| `result_viewer.py` | — | result | generic file viewing | — |
| `analysis_common.py` | several components | shared | reused by the three analysis dialogs | — |
| `gps_source.py` / `physics_config.py` | pure functions | shared | called by `mac_builder` | — |
| `particle_geo.py` / `particle_preview.py` / `source_geo_preview.py` | previews | preview | reused by the particle/analysis dialogs | — |
| `direction_preview.py` / `gps_direction_preview.py` / `gun_direction_preview.py` | direction previews | preview | reused by the particle dialog | — |

Dialog cache keys: `_analysis_dialogs[(task, kind)]`, `_particle_dialogs[("particle", task)]`,
`_physics_dialogs[("physics", task)]`, `_calculate_dialogs[("calculate", task)]`, all cleared on
close.

## 7. Result viewers

| Viewer | Triggered by | Data source |
|---|---|---|
| `VoxelResultViewer` | double-click a `Voxel <q>` node | `out_Box_<q>.csv` |
| `TrajectoryViewerDialog` | double-click the `Trajectory` node | `Traj.csv` |
| `ProbeResultChartDialog` | double-click a quantity / histogram group | `out_<mesh>.csv` / `rad4space_h1_*.csv` |
| `ResultViewerDialog` | double-click run log / any other file | any text |

Viewers are cached per task (`_voxel_viewers[(task, qname)]`, `_traj_viewers[task]`), and after a
re-run `_refresh_open_voxel_previews()` / `_refresh_open_traj_viewers()` refresh them
automatically.

## 8. Theme

`_toggle_theme()` flips `_dark_theme` and then:

1. `_apply_global_theme()` sets the `QPalette`, the global QSS and the log widget style;
2. pushes the new theme to the run launcher, the task monitor, the solver settings dialog and each
   cached dialog and viewer (each implements `set_dark_theme(bool)`).

Trajectory colours stay the same under both themes; only backgrounds, text and the world wireframe
colour switch.

## 9. Interaction rules

- a running or queued task **cannot** open its configuration dialogs and cannot be deleted;
- only a finished task rebuilds its result subtree (checked for `completed` in `_on_task_finished`);
- when closing the main window, **close every secondary QVTK window first** and only then destroy
  the main window (`closeEvent`); a wrong GL-context release order floods the log with errors;
- saving any configuration dialog refreshes the macro preview and updates the "configured" marker
  on the tree node.
