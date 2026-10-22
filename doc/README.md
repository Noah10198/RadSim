# RadSim Developer Documentation

> For developers and integrators. For end-user instructions see [README.md](../README.md) in the module root.

## Documentation Index

| Document | Contents |
|---|---|
| [01 · Architecture](01-architecture.md) | Layers, module dependency graph, the four data flows, thread model, singletons, extension points |
| [02 · GDML Pipeline](02-gdml-pipeline.md) | Parser, node tree, expression evaluator, write-back, materials library, collision detection |
| [03 · run.mac Generation](03-mac-builder.md) | The eight macro blocks, physics/source reuse, the three scoring commands, unit conversion |
| [04 · Run Execution](04-execution.md) | `RunManager` state machine, `QProcess`, log redirection, stop and cleanup |
| [05 · Analysis and Results](05-analysis.md) | `realworld` / `probe` / `voxel` configuration, the scoring quantity list, result grouping |
| [06 · Project Save and Load](06-project-io.md) | Project folder layout, `project.json`, hard save, the drafts directory |
| [07 · Visualization](07-visualization.md) | VTK scene, solid factory, WId re-binding, voxel / trajectory / curve viewers |
| [08 · UI Reference](08-ui-reference.md) | Layout, ribbon, project tree, the full list of dialogs and viewers |
| [09 · Data Formats](09-data-formats.md) | Project JSON, run.mac, every result CSV, configuration structures, QSettings |
| [10 · Environment and Troubleshooting](10-troubleshooting.md) | Dependency versions, installation, Qt DLL conflicts, symptoms, known limitations |
| [11 · Linux Porting Guide](11-linux-porting.md) | Dual-platform change list, solver rebuild, `LD_LIBRARY_PATH`, VTK/Wayland, fonts, acceptance checklist |

## Find by Topic

| I want to know… | Read |
|---|---|
| How the system is layered and which module depends on which | [01](01-architecture.md#2-layers) |
| How a GDML file becomes a tree, and which solids are supported | [02](02-gdml-pipeline.md#2-gdmlparser) |
| How a form on screen becomes a Geant4 command | [03](03-mac-builder.md) |
| How the solver is launched and where the log goes | [04](04-execution.md) |
| What each analysis mode needs and how to read its results | [05](05-analysis.md) |
| What a project is saved as, and how to move it | [06](06-project-io.md) |
| How the 3D view, voxels and trajectories are drawn | [07](07-visualization.md) |
| Where a button or dialog lives and what it is called | [08](08-ui-reference.md) |
| What the columns of a given CSV mean | [09](09-data-formats.md) |
| The app will not start / the solver exits immediately | [10](10-troubleshooting.md#3-solver-and-qt-dll-conflict-most-common-issue) |
| Moving to Ubuntu / working on both platforms | [11](11-linux-porting.md) |
| The 3D view is black under Ubuntu/Wayland (VTK and OCC both hit this) | [11 · section 8](11-linux-porting.md#8-deep-dive-solving-vtk-window-embedding-on-ubuntu) |

## Suggested Reading Paths

**Taking over the project for the first time**:
01 → 02 → 03 → 04 → 05 → 07, then 08/09 as needed.

**Changing the UI only**:
08 → 01 (section 7, signal routing) → 05 (if an analysis dialog is involved).

**Changing physics or the macro only**:
03 → 05 → 02.

**Diagnosing a field problem**:
10 → 04 (execution) → 09 (result files).

**Porting to Linux / dual-platform work**:
11 → 04 (solver launch) → 07 (VTK window) → 10 (environment).

## Conventions at a Glance

| Item | Convention |
|---|---|
| Length unit | mm in the UI and internally, cm inside the macro |
| Angle unit | deg |
| Density unit | g/cm³ |
| Task primary key | the task name (must be unique) |
| Directory name | `safe_task_name()`: illegal characters → `_` |
| Persistence | `QSettings("RadSim", "RadSim")` |
| Logging | always through `AsyncLogger.log_system(...)` |
| Threading | UI and VTK live on the main thread; only large GDML parsing and the solver process are exceptions |
