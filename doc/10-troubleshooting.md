# 10 · Environment and Troubleshooting

## Contents

- [1. Runtime environment](#1-runtime-environment)
- [2. Installation](#2-installation)
- [3. Solver and Qt DLL conflict (most common issue)](#3-solver-and-qt-dll-conflict-most-common-issue)
- [4. Symptom reference table](#4-symptom-reference-table)
- [5. Logs and diagnostics](#5-logs-and-diagnostics)
- [6. Known limitations (summary)](#6-known-limitations-summary)
- [7. Performance notes](#7-performance-notes)
- [8. Related documents](#8-related-documents)

## 1. Runtime environment

| Item | Version |
|---|---|
| Python | 3.10 (3.10.19 verified) |
| OS | Windows x64 |
| PyQt6 | 6.4.2 |
| VTK | 9.3.1 (imported as `vtkmodules`) |
| numpy | 2.2.6 |
| matplotlib | 3.10.7 (optional, only for curves) |
| Solver | rad4space, built on Geant4 11.4.2 |

## 2. Installation

```bash
# recommended: the provided environment file
conda env create -f environment.yml
conda activate pyoccenv
python main.py

# or with pip
pip install -r requirements.txt
python main.py
```

Solver: the repository already contains `solver/rad4space/build/Release/rad4space.exe`; to build it
yourself see `solver/rad4space/README.md`.

## 3. Solver and Qt DLL conflict (most common issue)

**Symptom**: the task exits immediately, `run.log` is empty or holds a single line, exit code
`0xC0000135` (DLL not found) or `0xC0000139` (entry point not found).

**Cause**: rad4space links against Qt6. When the GUI is started from a conda environment, conda's
older Qt6 DLLs come first in `PATH` and are loaded instead.

**Fix**:

1. open **⚙️ Solver Setting**;
2. put the Qt6 `bin` directory the solver was built against into `solver/qt_bin_dir`;
3. run again.

Before starting the solver RadSim puts that directory at the **front** of the child process `PATH`
(`core/solver_config.runtime_dll_dirs`), which does not affect the GUI's own Qt.

## 4. Symptom reference table

| Symptom | Cause / fix |
|---|---|
| the 3D view is all white or all black | the imported solid is not renderable, or the GL context was lost (after a theme switch or a monitor change). Click **⌂ Fit** or restart |
| the log floods with `wglMakeCurrent failed` | the GL-context release order between the secondary VTK windows and the main window. A normal close shuts the secondary windows first; if it still happens, check whether a window was killed forcefully |
| the solver path shows as not configured | `solver/executable` is empty and auto-detection failed; set it by hand. While unconfigured the program runs with **simulated progress** |
| the progress bar sticks at 99 % | the real process is still running (progress is indeterminate); this is normal |
| a task is `failed` | read `run.log` first, then check whether the macro preview looks sane |
| the result tree gets no new node | only a `completed` task rebuilds its result subtree; a `failed` task only gets `run log` |
| the result file exists but the UI cannot read it | the draft directory and the project directory are not the same; see [doc 06, section 5](06-project-io.md#5-draft-directory-vs-project-directory) |
| importing a GDML file hangs | files ≥ 500 KB go to a background thread behind a modal progress dialog; for very large files simplify the geometry first |
| the dimensions are clearly wrong | the GDML expression references an undefined identifier — the evaluator silently substitutes `0` (see [doc 02](02-gdml-pipeline.md)) |
| some solids are not drawn | `trap` / `trd` / `para` / `polyhedra` / `xtru` / boolean solids are not rendered; a warning is shown at import time |
| the probe chart reports "matplotlib is not installed" | install matplotlib and reopen the dialog |
| the histogram x axes do not line up | the bins/range of one quantity type differ; the dialog warns about this in advance |
| saving is slow | saving is a hard save (the whole `results/` directory is mirrored) |
| wanting to move to another project folder | it is fixed by the first save; restart and save again |

## 5. Logs and diagnostics

- the on-screen log panel: written by `AsyncLogger`, covering import, configuration, runs and
  exceptions;
- the task log: `solver/runs/<task>/run.log` (or `<project>/results/<task>/run.log`);
- the macro file: `run.mac` in the same directory, which can be executed by hand to reproduce:

```
<qt_bin>; solver\rad4space\build\Release\rad4space.exe solver\runs\Run_001\run.mac
```

## 6. Known limitations (summary)

| Limitation | Notes |
|---|---|
| single geometry | one project supports one GDML file |
| simplified material parsing | `<materials>` records only the name and density |
| undefined identifiers | evaluation silently yields `0` |
| hollow sphere / cone | a hollow sphere is simplified to its outer shell; a cone uses 16 segments and ignores the inner radius |
| solids not rendered | `trap`, `trd`, `para`, `hype`, `polyhedra`, `xtru`, `arb8`, `cutTube`, boolean solids, … |
| rubber-band selection / context menu | neither is implemented in the 3D view |
| trajectory animation | the trajectory viewer has filtering only, no playback or timeline |
| multithreaded trajectories | `Traj.csv` holds only the events of the selected worker; use `/run/numberOfThreads 1` when the full trajectory is needed |
| progress semantics | the progress of a real run is indeterminate and only means "the process is alive" |
| units | mm in the GUI and internally, converted to cm inside the macro as the solver requires |

## 7. Performance notes

- spheres/cylinders/tori use a fixed 48-segment circumference and cones a fixed 16 segments, so the
  triangle count grows quickly with the number of solids;
- the voxel viewer needs about `(nbin+1)³ × 8` bytes, i.e. roughly 65 MB at `nbin = 200` on each
  axis;
- MSAA and vsync are already off and shared geometry is cached; if it still stutters, reduce the
  number of visible solids first.

## 8. Related documents

- [Architecture](01-architecture.md)
- [GDML pipeline](02-gdml-pipeline.md)
- [run.mac generation](03-mac-builder.md)
- [Run execution](04-execution.md)
- [Analysis and results](05-analysis.md)
- [Project save and load](06-project-io.md)
- [Visualization](07-visualization.md)
- [UI reference](08-ui-reference.md)
- [Data formats](09-data-formats.md)
