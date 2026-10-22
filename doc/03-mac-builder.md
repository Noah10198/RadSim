# 03 · run.mac Generation and the Solver Interface

> Source: `core/mac_builder.py` (pure Python, no Qt dependency)
> Related: `ui/dialogs/physics_config.py`, `ui/dialogs/gps_source.py`, `core/run_manager.py`

## Contents

- [1. Design principle](#1-design-principle)
- [2. Input: one RunTask](#2-input-one-runtask)
- [3. Output: the eight blocks of run.mac](#3-output-the-eight-blocks-of-runmac)
- [4. Physics and source: reusing the dialog macro builders](#4-physics-and-source-reusing-the-dialog-macro-builders)
- [5. Scoring: the three analysis modes](#5-scoring-the-three-analysis-modes)
- [6. Working directory](#6-working-directory)
- [7. Common pitfalls](#7-common-pitfalls)

## 1. Design principle

rad4space is a **Geant4 batch program** and takes exactly one argument, a macro file:

```
rad4space.exe  <workdir>/run.mac
```

Everything about a run therefore lives in the macro: thread count, event count, geometry path,
physics list, particle source, scoring meshes, histograms and output file names are all written
into `run.mac` by `mac_builder`. No switches are passed on the command line, which buys two
things:

- every run leaves a complete record that is reproducible and readable by a human;
- no custom parameter protocol is needed between the GUI and the solver — the macro *is* the
  protocol.

## 2. Input: one RunTask

`build_mac_text(gdml_full_path, task)` reads four fields of a `RunTask`
(`core/project_model.py`):

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `task.calculate` | `CalculateSetting` | calculation settings dialog | `n_threads`, `n_events` |
| `task.physics` | dict | physics dialog | physics list, HP/RDM switches, cut, maximum step |
| `task.particle` | dict | particle source dialog | the gun / gps / imported-file modes |
| `task.analysis_config` | dict | the three analysis dialogs | `realworld` / `probe` / `voxel` scoring |

`gdml_full_path` is the **absolute path** of the imported geometry; the macro references it
directly through `/rad4space/gdml/SetGDMLFile`, and the geometry is never copied into the working
directory.

## 3. Output: the eight blocks of run.mac

`build_mac_text()` concatenates the blocks in a fixed order, and that order carries meaning
(PreInit / PostInit):

| # | Block | Contents | Timing |
|---|---|---|---|
| 1 | run control | `/control/saveHistory`, optional `/run/numberOfThreads N`, `/run/verbose 1`, `/control/verbose 1`, `/event/verbose 0`, `/tracking/verbose 0` | PreInit |
| 2 | geometry | `/rad4space/gdml/SetGDMLFile <absolute path>` | PreInit |
| 3 | physics | `physics_config.macro_lines(task.physics)` | PreInit |
| 4 | initialize | `/run/initialize` (after this the run options are frozen) | the dividing line |
| 5 | source | `gps_source.macro_lines(task.particle)` | PostInit |
| 6 | scoring setup | the mesh / histogram / fill1D creation commands | PostInit, **must** precede beamOn |
| 7 | run | `/run/beamOn <N>` | — |
| 8 | scoring dump | the `/score/dump*` output commands | **must** follow beamOn |

Points worth noting:

- **the thread line is optional**: with `n_threads == 0` the whole line is omitted and the solver
  falls back to its own default;
- **event count fallback**: `n_events <= 0` becomes `DEFAULT_EVENTS = 10000` rather than an empty
  run;
- **dump must come after beamOn**: dumping before beamOn writes an all-zero file — a pitfall the
  macro comments call out repeatedly;
- **histograms must be created and bound before beamOn**: `/analysis/h1/create` and
  `/score/fill1D` both belong to the setup block, otherwise nothing accumulates during the run.

## 4. Physics and source: reusing the dialog macro builders

`mac_builder` does not assemble the physics or source commands itself; it calls the pure functions
of the two dialog modules (they live under `ui/dialogs/`, but their macro generation is plain
logic):

```python
from ui.dialogs import physics_config as pcfg   # macro_lines(cfg)
from ui.dialogs import gps_source as gps        # macro_lines(cfg)
```

### Physics block (`physics_config.macro_lines`)

```
/rad4space/physics/SetPL <physics_list>
/rad4space/physics/AddHP true        # only when add_hp and the list supports it
/rad4space/physics/AddRDM true       # only when add_rdm and the list supports it
/rad4space/physics/SetGlobalCut <mm> mm
/rad4space/physics/SetMaxStep <mm> mm # only when > 0
```

Note that the cut and the step are in **mm**, not cm — that is the convention of the solver
commands themselves.

### Source block (`gps_source.macro_lines`)

Dispatched on `cfg["mode"]`:

| mode | What is emitted |
|---|---|
| `gun` | the `/gps/*` aliases of G4ParticleGun (`/gps/particle`, `/gps/energy`, `/gps/position`, `/gps/direction`) |
| `gps` | a full GPS sequence (`/gps/pos/type`, `/gps/ang/type`, `/gps/ene/type`, …) |
| `file` (an imported raw macro) | written verbatim, neither parsed nor filtered |

**Unit conversion happens at this layer**: source position / centre / shape size / focus are
converted from mm to cm by dividing by 10; energy is always MeV and angle always deg, never
converted.

## 5. Scoring: the three analysis modes

`scoring_block(analysis_config)` returns `(setup_lines, dump_lines)` and emits in the order of
`active_kinds()`. **All three modes can be enabled at once** — each is an independent scorer mesh
and rad4space can score them together in one `/run/beamOn` instead of keeping only one.

`active_kinds()` decides on "does the configuration contain at least one scoring quantity":

| kind | Decided by |
|---|---|
| `realworld` | any logical volume has a non-empty `qs` or `hs` |
| `probe` | any probe has a non-empty `qs` or `hs` |
| `voxel` | `voxel.qs` is non-empty |

### 5.1 real world (logical-volume scoring)

```gdscript
/score/create/realWorldLogVol <LVname>
/score/quantity/<type> <qname> [unit]
/score/close
```

One mesh per logical volume with a scoring quantity, named after the logical volume.

### 5.2 probe (probe cube)

```gdscript
/score/create/probe <name> <half/10> cm
/score/probe/material <material>        # optional, omitted when material == "none"
/score/probe/locate <x/10> <y/10> <z/10> cm
/score/quantity/<type> <qname> [unit]
/score/close
```

`half` is the **half edge length** of the probe cube (mm), converted to cm.

### 5.3 voxel (rectilinear mesh)

```gdscript
/score/create/boxMesh Box
/score/mesh/boxSize <half[0]/10> <half[1]/10> <half[2]/10> cm   # half length, not full width
/score/mesh/nBin <nx> <ny> <nz>
/score/mesh/translate/xyz <cx/10> <cy/10> <cz/10> cm
/score/quantity/<type> <qname> [unit]
/score/close
```

`/score/mesh/boxSize` takes the **half length**; the macro carries a comment to that effect.

### 5.4 Scoring quantities and units

In `/score/quantity/<type> <name> [unit]`, `<type>` is the `type` key of the analysis
configuration. Only two scorers show a unit in the sample files, so only those get a unit suffix:

```python
_QUANTITY_UNIT = {"energyDeposit": "MeV", "doseDeposit": "Gy"}
```

Every other quantity is emitted in the solver's native unit, with no unit written.

The complete list of quantities (15) is in [09-data-formats.md](09-data-formats.md); its single
authority is `ui/dialogs/analysis_common.QUANTITY_TYPES`, and `mac_builder._HIST_XUNIT` is a
mirror of it on the core side (so that core need not depend on Qt).

### 5.5 One-dimensional histograms (spectra)

For quantities that support histograms, each `hs` entry produces two lines:

```gdscript
/analysis/h1/create <mesh>_<qname> <mesh>_<qname> <bins> <xmin> <xmax> <xunit> [ ! log ]
/score/fill1D <globalId> <mesh> <qname>
```

- `globalId` comes from a **single global counter** `id_state["n"]`. G4TScoreHistFiller numbers
  histograms globally in creation order, so with realworld and probe enabled together the ids must
  keep increasing — they cannot each restart at 0.
- `xunit` follows the quantity type (`_HIST_XUNIT`); quantities whose entry is `None` (such as
  `trackLength` and `cellCharge`) have no histogram and are skipped silently.
- when `log` is true, ` ! log` is appended to the line.

### 5.6 Output commands

| kind | dump command | File produced |
|---|---|---|
| realworld / probe | `/score/dumpAllQuantitiesToFile <mesh> out_<mesh>.csv` | `out_<mesh name>.csv` |
| voxel | `/score/dumpQuantityToFile Box <q> out_Box_<q>.csv` | one `out_Box_<q>.csv` per quantity |

A voxel is a 3D mesh with no `dumpAll`, so it can only be dumped quantity by quantity.

## 6. Working directory

`write_workdir(gdml_full_path, task, out_root)`:

1. sanitizes the task name into a safe directory name with
   `re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name)` (the same rule as
   `core/project_io.safe_task_name`, so that the drafts directory and a saved copy line up);
2. **deletes** `<out_root>/<safe>` entirely if it already exists — a re-run must not leave the
   previous CSV or log behind, since a shorter run would otherwise leave stale results in place;
3. recreates the directory, writes `run.mac` and returns the working directory path.

The default `out_root` is `solver/runs` (see `core/solver_config.get_results_root`) and can be
overridden through QSettings. Each task gets its own subdirectory, so concurrent runs cannot
overwrite each other.

## 7. Common pitfalls

| Pitfall | Effect |
|---|---|
| a dump before beamOn | an all-zero file |
| histogram ids restarting at 0 | `/score/fill1D` binds to the wrong target when several meshes are active |
| passing the full width to `boxSize` | the mesh is twice as large as intended (it takes the half length) |
| `n_events = 0` | falls back to 10000 rather than not running at all |
| physics or geometry commands after `/run/initialize` | silently have no effect |
| forgetting mm → cm on a source position | the source sits ten times too far away |
