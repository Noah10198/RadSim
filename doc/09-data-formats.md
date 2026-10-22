# 09 · Data Formats

> Every format listed here is actually read and written by the code in this repository; field
> names follow the code.

## Contents

- [1. project.json](#1-projectjson)
- [2. run.mac](#2-runmac)
- [3. Result CSVs](#3-result-csvs)
- [4. Particle source configuration](#4-particle-source-configuration-taskparticle)
- [5. Physics configuration](#5-physics-configuration-taskphysics)
- [6. Static resources](#6-static-resources)
- [7. QSettings keys](#7-qsettings-keys)
- [8. Directory conventions](#8-directory-conventions)

## 1. project.json

```json
{
  "format": "radsim-project",
  "version": 1,
  "gdml_paths": ["geometry/model.gdml"],
  "results_root": "solver/runs",
  "tasks": [
    {
      "name": "Run_001",
      "analysis_type": "default",
      "gdml_files": ["geometry/model.gdml"],
      "calculate": {"n_threads": 8, "n_events": 10000},
      "particle": { "...": "see section 4" },
      "physics": { "...": "see section 5" },
      "analysis_config": { "...": "see [doc 05](05-analysis.md)" }
    }
  ]
}
```

- `format` also accepts the legacy value `3drad-project`;
- `gdml_paths` are **relative paths** inside a project folder;
- the runtime fields (`status` / `progress` / `run_time` / `run_log`) are not written.

## 2. run.mac

The block structure is described in [doc 03](03-mac-builder.md). Example:

```
/control/saveHistory
/run/numberOfThreads 8
/run/verbose 1
/control/verbose 1
/event/verbose 0
/tracking/verbose 0
/rad4space/gdml/SetGDMLFile /abs/path/model.gdml
/rad4space/physics/SetPL FTFP_BERT
/rad4space/physics/SetGlobalCut 1.0 mm
/run/initialize
/gps/particle gamma
/gps/energy 1.0 MeV
/gps/position 0 0 0 cm
/gps/direction 0 0 1
/score/create/boxMesh Box
/score/mesh/boxSize 10 10 10 cm
/score/mesh/nBin 50 50 50
/score/mesh/translate/xyz 0 0 0 cm
/score/quantity/doseDeposit dose Gy
/score/close
/analysis/h1/create Box_dose Box_dose 100 0.0001 1.0 Gy
/score/fill1D 0 Box dose
/run/beamOn 10000
/score/dumpQuantityToFile Box dose out_Box_dose.csv
```

## 3. Result CSVs

### 3.1 `out_<mesh>.csv` (realworld / probe)

```
# mesh name: P1
# primitive scorer name: q1
# i, i, i, total(value) [MeV], total(val^2), entry
0,0,0,1.234e-05,3.2e-11,10000
```

- every `# primitive scorer name:` line starts a new block;
- a data row contributes column 4 (value) and column 6 (entry);
- the unit is read back from the brackets in `total(value) [MeV]`, so the file describes itself.

### 3.2 `out_Box_<q>.csv` (voxel)

```
iX,iY,iZ,value[,val2,entry]
```

- **iZ varies fastest** in the file; the viewer reorders with `idx = ix + nx*(iy + ny*iz)`;
- the mesh parameters `half` / `center` / `nbin` come from `analysis_config["voxel"]`, not from the
  file.

### 3.3 `rad4space_h1_<mesh>_<q>.csv` (1D histogram)

```
#title ...
#dimension 1
#axis edges 0.001 0.01 ... 1.0
#annotation ...
#bin_number 102
entries,Sw,Sw2,Sxw0,Sx2w0
10000,...
```

- both the `tools::histo::h1d` text dump and the legacy G4 `#axis fixed/log` style are supported;
- the count is the field before the first comma on each row;
- the axis type is inferred from whether the edges are arithmetic or geometric; `rebin_log()` fixes
  builds that were configured for log but dumped as fixed.

### 3.4 `Traj.csv`

```
eventID,trackID,parentID,particle,step,x,y,z
```

- the viewer groups by `(eventID, trackID)` and connects points by ascending `step`;
- under multithreading it contains only the events of the selected worker (see the limitations).

### 3.5 `run.log`

The solver's merged stdout + stderr (`MergedChannels`), appended in binary. When a project is
loaded it is used to decide whether a task succeeded: a tail without `error` / `fatal` /
`abnormal` / `failed` counts as finished.

## 4. Particle source configuration (`task.particle`)

```python
{
  "mode": "gun" | "gps" | "file",
  "particle": "gamma",
  "energy": 1.0, "energy_unit": "MeV",
  "position": [0, 0, 0],            # mm
  "direction": [0, 0, 1],
  "pos_type": "Point" | "Beam" | ...,
  "ang_type": "iso" | "cos" | "cone" | ...,
  "spectrum": {...},
  "macro_text": "...",              # written verbatim when mode == "file"
}
```

When `mode == "file"`, `gps_source.macro_lines()` returns `macro_text` as it is, without parsing.

## 5. Physics configuration (`task.physics`)

```python
{
  "physics_list": "FTFP_BERT",
  "add_hp": False, "add_rdm": False,
  "global_cut": 1.0,     # mm
  "max_step": 0.0,       # mm; 0 means the command is not written
}
```

The resulting command sequence is in
[doc 03, section 4](03-mac-builder.md#4-physics-and-source-reusing-the-dialog-macro-builders).

## 6. Static resources

| File | Contents |
|---|---|
| `data/element.xml` | element table: symbol → (Z, atomic weight) |
| `data/nist.txt` | the NIST material list (the `G4_` prefix) with densities |

## 7. QSettings keys

| Key | Default / probing |
|---|---|
| `solver/executable` | probed in turn: `solver/rad4space/build/Release/rad4space.exe`, `build/rad4space.exe`, `rad4space.exe` |
| `solver/qt_bin_dir` | the Qt6 bin directory the solver needs; empty falls back to the built-in development-machine paths |
| `solver/results_root` | default `solver/runs` |

## 8. Directory conventions

```
solver/runs/<safe_task_name>/     # draft output (shared by all projects)
<project>/geometry/               # geometry copies
<project>/results/<safe_task_name>/  # result snapshots after saving
```

`safe_task_name()` replaces every character outside `[A-Za-z0-9_.\-]` with `_`.
