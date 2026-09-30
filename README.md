# RadSim

**Radiation simulation front-end** — configure Geant4 sources and physics, run Monte Carlo batches, and inspect dose, flux, spectra and trajectories.

> **Version 0.1.0** ｜ Last updated 2026-09-30 ｜ Chinese version: [README.zh.md](README.zh.md)

## Overview

RadSim is a graphical front-end for the radiation solver
[rad4space](solver/rad4space/README.md). It lets you inspect GDML geometry in 3D,
configure particle sources and physics interactively, run Monte Carlo simulations in
batch, and view voxel dose, probe flux, spectra and particle trajectories.

- Language: Python 3.10
- UI: PyQt6 + VTK
- Solver: `rad4space.exe`, a Geant4 11.4.2 batch executable
- Platform: Windows x64 (only Windows has been validated so far)

## Features

| Module | Description |
|---|---|
| GDML geometry | Import GDML, browse the hierarchy as a tree, render in 3D with picking, visibility and placement editing |
| Task management | A project holds multiple tasks, each with its own geometry, source, physics and analysis |
| Particle source | GPS source: mono-energetic / spectrum / ion, with visual position and direction preview |
| Physics | Switchable physics list (FTFP_BERT / Shielding, ...), production cut and max step |
| Analysis modes | real world (logical volumes), probe (probe cubes), voxel (Cartesian mesh) scoring |
| Run scheduling | Task queue with a concurrency limit of 2, live progress and logs, stop at any time |
| Result viewers | 3D voxel rendering, probe comparison charts, spectra, trajectories, run log, generic file viewer |
| Project persistence | A project is a folder (`project.json` + `geometry/` + `results/`) and can be moved as a whole |
| Live preview | The right panel renders the `run.mac` generated from the current configuration |

## UI Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ 📁 Import GDML │ 🧾 Load Project │ 💾 Save Project ┃ 🎯 Reset View ┃  │
│ ▶️ Run │ 🟢 Idle │ ⏹ Stop ┃ ⚙️ Solver Setting │ ☀️ Theme │ ❓ Help  │
├──────────────┬───────────────────────────────────┬───────────────────┤
│ Project Tree │          3D view (VTK)            │  run.mac preview  │
│              ├───────────────────────────────────┤                   │
│              │          System log               │                   │
├──────────────┴───────────────────────────────────┴───────────────────┤
│ Status bar                                                            │
└──────────────────────────────────────────────────────────────────────┘
```

| Toolbar button | Action |
|---|---|
| 📁 Import GDML | Import a GDML geometry (one geometry per project) |
| 🧾 Load Project | Open a saved project (`project.json`) |
| 💾 Save Project | Save the project; the folder is chosen on the first save |
| 🎯 Reset View | Reset the 3D camera |
| ▶️ Run | Open the run launcher and start the checked tasks |
| 🟢 Idle / 🔄 Running / ⚠️ Issues / ✅ Done | Task monitor with per-task progress and status |
| ⏹ Stop | Stop every running task |
| ⚙️ Solver Setting | Configure the solver executable and Qt runtime directory |
| 🌙 / ☀️ Theme | Toggle dark / light theme |
| ❓ Help | Help |

> The left dock is titled `Project Tree`. Its root row is named `Project of RadSim`; the
> geometry, task and result subtrees all hang under that row.

## Requirements

| Dependency | Version |
|---|---|
| Python | 3.10 (conda env `easy2rad-env`) |
| PyQt6 | == 6.4.2 |
| VTK | == 9.3.1 — imported as `vtkmodules` (PyPI package name is `vtk`) |
| numpy | == 2.2.6 |
| matplotlib | == 3.10.7 — optional, only used by the probe / real-world comparison charts |
| rad4space.exe | Prebuilt solver binary (Geant4 11.4.2 + Qt 6.11 runtime) |

## Installation

### Option 1: conda (recommended)

The project is developed in a Python 3.10 conda environment; `environment.yml` is a
full export of that environment:

```bash
conda env create -f environment.yml
conda activate easy2rad-env
python main.py
```

### Option 2: pip

```bash
pip install -r requirements.txt
python main.py
```

> `matplotlib` is only used by the probe / real-world comparison dialog and shows an
> install hint when missing.

### Solver

The GUI is only a front-end: the actual simulation is run by the Geant4 program under
`solver/rad4space/`. A prebuilt `solver/rad4space/build/Release/rad4space.exe` is
included; see [solver/rad4space/README.md](solver/rad4space/README.md) for
build instructions (Geant4 11.4.2, xerces-c, Qt 6.11).

The solver executable and its Qt runtime directory can be set in
**⚙️ Solver Setting** and are persisted through `QSettings`. When left empty the
following candidates are probed in order:

```
solver/rad4space/build/Release/rad4space.exe
solver/rad4space/build/rad4space.exe
solver/rad4space/rad4space.exe
```

> When launched from a conda environment, the solver may exit with `0xC0000135` /
> `0xC0000139` if conda's older Qt6 DLLs are picked up first. RadSim prepends the
> configured Qt bin directory to `PATH` before launching, so set it in Solver Setting.
> The Qt bin directory is also probed at one hardcoded development path
> (`D:\Application\Qt6.11\...`); on any other machine set it explicitly.

## Usage

### 1. Import geometry

Click **📁 Import GDML**. Files smaller than 500 KB are parsed synchronously, larger
ones in a background thread so the UI stays responsive. Afterwards:

- a Geometry subtree appears in the project tree (checkboxes toggle visibility);
- the 3D view renders the geometry and clicking picks / selects tree nodes;
- a default task `Run_001` is created automatically.

> One geometry per project. Importing another asks whether to replace the current one.

### 2. Configure tasks

Double-click the nodes under a task:

| Node | Configuration |
|---|---|
| Calculate Setting | Thread count, number of events |
| Particle Setting | Particle type, energy / spectrum, position, direction |
| Physics Process | Physics list, production cut, max step |
| Analysis → real world / probe / voxel | Scored entities and quantities |

The **run.mac preview** panel updates live as you edit.

Analysis modes:

- **real world**: score logical volumes, choosing which volumes and quantities;
- **probe**: place probe cubes with half size, material and quantities;
- **voxel**: Cartesian mesh with extent (whole geometry or manual), bin counts and quantities.

### 3. Run

Click **▶️ Run**, check the tasks and start. `RunManager` queues them with at most
2 concurrent tasks:

- each task gets a work directory `<results_root>/<task>/` containing `run.mac`;
- solver stdout/stderr are merged into `run.log`;
- progress and status (idle / queued / running / completed / failed / stopped) are
  mirrored to the project tree and the monitor dialog;
- **⏹ Stop** terminates all tasks (`terminate`, then `kill` after 2 s).

Without a configured solver, a simulated progress run is used so the UI flow can be tested.

### 4. View results

When a task finishes a Results subtree is attached. Double-clicking a result opens:

| Result | Viewer |
|---|---|
| Voxel mesh (`q:`) | 3D voxel rendering |
| Probe / real world scores (`pq:` / `rq:`) | Comparison chart (matplotlib) |
| Histograms (`ph:` / `rh:`) | Comparison chart |
| Trajectory | Trajectory viewer (coloured by particle) |
| run log | Log viewer |
| Other files | Generic file viewer |

## Project Structure

```
RadSim/
├── main.py                     Entry point (QApplication + main window)
├── app/
│   └── main_window.py          Layout, signal wiring, task orchestration, project I/O
├── core/                       UI-independent core logic
│   ├── gdml_parser.py          GDML parser (define/materials/solids/structure/setup)
│   ├── gdml_tree.py            GDML node tree (GdmlNode / Placement)
│   ├── gdml_evaluator.py       GDML attribute expression evaluator
│   ├── gdml_writer.py          GDML writer (multi-file merge, placement override, local material injection)
│   ├── gdml_agent.py           GDML data agent (singleton facade)
│   ├── materials_lib.py        Material library (NIST + custom elements/compounds/mixtures)
│   ├── mac_builder.py          run.mac generation and per-task work directory
│   ├── collision_detector.py   AABB collision detection
│   ├── run_manager.py          Multi-task run scheduler (QProcess)
│   ├── project_io.py           Folder-based project save / load
│   ├── project_model.py        RunTask / CalculateSetting data model
│   └── solver_config.py        Solver path and results root (QSettings)
├── vtk_engine/                 VTK scene management and solid factory
│   ├── vtk_scene.py            Render window, actor tree, picking / highlight
│   └── vtk_solid_factory.py    Build polydata / actors per GDML solid type
├── ui/                         PyQt widgets
│   ├── ribbon_toolbar.py       Ribbon toolbar
│   ├── project_tree.py         Project tree (geometry + tasks + results)
│   ├── vtk_widget.py           3D view widget
│   ├── vtk_view_window.py      Standalone VTK window for secondary views
│   ├── mac_preview.py          run.mac preview dock
│   ├── trajectory_viewer.py    Particle trajectory viewer
│   ├── voxel_result_viewer.py  Voxel result 3D viewer
│   ├── probe_result_viewer.py  Scoring result reader / grouper (no Qt)
│   ├── probe_chart_dialog.py   Probe / real world comparison charts (matplotlib)
│   └── dialogs/                Configuration and result dialogs
├── utils/logger.py             Async logger singleton
├── data/                       element.xml, nist.txt
├── doc/                        Module-level developer docs (Chinese, 01-11)
├── icon/                       Application icon (radsim.svg)
├── solver/                     rad4space sources, build output and run output
│   ├── rad4space/              The C++ / Geant4 solver
│   └── runs/                   Default results root
├── test/                       Test GDML files and sample data
├── environment.yml             Conda environment (name: easy2rad-env)
├── requirements.txt            pip fallback
├── LICENSE                     MIT license
├── README.md                   This file
└── README.zh.md                Chinese version of this file
```

## Architecture

The GUI keeps the core logic free of Qt, so the same code could be reused headless:

```
main.py
└── app/main_window.py      Layout, signal wiring, task orchestration, project I/O
├── core/                   UI-independent logic (GDML, materials, macro, project, scheduling)
│   └── gdml_agent.py       Singleton facade over the GDML parse tree + edit overlays
├── vtk_engine/             Scene management and actor factory (rendering only)
├── ui/                     Ribbon toolbar, project tree, viewers, dialogs
├── utils/logger.py         Async logger singleton
└── solver/                 rad4space (C++ / Geant4) and the run output root
```

Data flow of one task:

```
GDML file ──► core/gdml_parser ──► GdmlAgent ──► vtk_engine/vtk_scene (3D view)
                   │
        core/mac_builder ──► run.mac ──► ui/mac_preview (live preview)
                   │
                   └──► core/project_io ──► project.json + geometry/ + results/
                                               │
                              RunManager (QProcess) ──► rad4space.exe
                                               │
                                               ▼
                        results/<task>/ (out_*.csv, rad4space_h1_*.csv, Traj.csv, run.log)
                                               │
                                               ▼
                              ui viewers (voxel / probe / trajectory / log)
```

## Project Format

A project is a folder:

```
MyProject/
├── project.json          Config: geometry reference + task list
├── geometry/*.gdml       Copy of the imported GDML
└── results/<task>/       Snapshot of each task's run output
```

`project.json` fields:

| Field | Description |
|---|---|
| `format` | `radsim-project` (the legacy `3drad-project` is accepted) |
| `version` | Currently `1` |
| `gdml_paths` | Geometry paths, stored **relative** to the project folder after copying into `geometry/` |
| `tasks` | Task list with `name`, `analysis_type`, `particle`, `physics`, `calculate`, `analysis_config`, ... |

Saving is a "hard save": geometry and `results/` are mirrored, and deleting a task also
deletes its saved results. Loading clears the shared draft output folders first, then
rebuilds tasks and the results tree.

> After the first save the project folder is fixed; later saves update it in place.

## Output Files

Task output lives in `<results_root>/<task>/` (default `solver/runs/<task>/`):

| File | Description |
|---|---|
| `run.mac` | Macro used for this run |
| `run.log` | Solver stdout / stderr |
| `out_*.csv` | Integrated values per scoring mesh |
| `rad4space_h1_*.csv` | 1-D spectra |
| `Traj.csv` | Trajectory points (`eventID, trackID, parentID, particle, step, x, y, z`) |

## Persisted Settings

Stored through `QSettings` (`RadSim/RadSim`):

| Key | Description |
|---|---|
| `solver/executable` | Solver executable path |
| `solver/qt_bin_dir` | Qt runtime bin directory required by the solver |
| `solver/results_root` | Results root (default `solver/runs`) |

## Known Limitations

- GDML `<materials>` parsing is simplified: only name and density are recorded;
- Some solid types (`polyhedra`, `xtru`, booleans, `multiUnion`, `scaledSolid`, ...)
  are not rendered in 3D and are only written back verbatim; a warning is shown on import;
- Undefined identifiers in expressions evaluate to `0`;
- Hollow spheres (`rmin > 0`) are previewed with their outer sphere only and `cone` is
  approximated with 16 segments;
- The run log viewer loads at most the last 2 MB of `run.log`;
- One GDML geometry per project;
- GUI lengths are in **mm** and converted to **cm** when writing the macro;
- With multiple threads `Traj.csv` only contains events of the single elected worker
  thread; use `/run/numberOfThreads 1` for complete trajectories.

## Development Notes

- **Threading**: only large GDML files (>= 500 KB) are parsed in a `QThread`, calling
  the thread-safe `parse_file_only`; the result is handed back to the main thread by a
  queued signal. All other UI work happens on the main thread.
- **Run scheduling**: `RunManager` is fully non-blocking (`QProcess` + `QTimer`
  heartbeat), with only `waitForStarted(3000)` and `waitForFinished(2000)` blocking.
- **VTK windows**: `QVTKRenderWindowInteractor` recreates the native window on
  hide/show, changing the `WId`; `VtkWidget` rebinds when it changes. The main window
  closes all secondary windows first to release their GL contexts.
- **Singletons**: `GdmlAgent` and `AsyncLogger`.

## Related Documents

- **Module-level developer docs (Chinese)**: [`doc/`](doc/README.md)
  - [Architecture](doc/01-architecture.md) ｜ [GDML pipeline](doc/02-gdml-pipeline.md) ｜ [run.mac generation](doc/03-mac-builder.md)
  - [Execution](doc/04-execution.md) ｜ [Analysis and results](doc/05-analysis.md) ｜ [Project I/O](doc/06-project-io.md)
  - [Visualization](doc/07-visualization.md) ｜ [UI reference](doc/08-ui-reference.md) ｜ [Data formats](doc/09-data-formats.md) ｜ [Troubleshooting](doc/10-troubleshooting.md) ｜ [Linux porting](doc/11-linux-porting.md)
- **Solver documentation**: [solver/rad4space/README.md](solver/rad4space/README.md)
- Chinese version of this file: [README.zh.md](README.zh.md)

## License

[MIT](LICENSE) © ready2run

## Acknowledgments

- [OpenCASCADE Technology](https://dev.opencascade.org/) — CAD kernel
- [GMSH](https://gmsh.info/) — Finite element mesh generator
- [VTK](https://vtk.org/) — Visualization Toolkit
- [PythonOCC](https://github.com/tpaviot/pythonocc-core) — Python bindings for OCC
- [Geant4](https://geant4.web.cern.ch/) — GDML geometry format
- [CodeBuddy](https://www.codebuddy.ai/) & [DeepSeek](https://deepseek.com/) — AI-assisted development throughout this project
