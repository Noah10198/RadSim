# rad4space

A radiation solver (batch simulation) built on Geant4 11.4.2. The design follows
gorad / RE03 / exgps and relies only on native Geant4 mechanisms:

- **Geometry**: GDML import (G4GDMLParser, `/rad4space/gdml/SetGDMLFile`)
- **Parallelism**: multithreaded MT (G4RunManagerFactory, thread count defaults to the
  number of CPU cores)
- **Physics**: swappable physics lists (G4PhysListFactory + messenger, switchable at
  runtime, following gorad's GRPhysicsList approach)
- **Source**: general particle source GPS (G4GeneralParticleSource, as in exgps)
- **Scoring**: native command-based scoring (RE03-style probe/boxMesh + primitive
  scorers) plus native 1-D histogram filling (G4 Book For Application Developers
  4.9.8, `G4TScoreHistFiller<G4AnalysisManager>`)

> Chinese version: [README.zh.md](README.zh.md)

## Directory Layout

```
rad4space/
  rad4space.cc            # entry point
  src/  R4DetectorConstruction.cc  GDML import + messenger
        R4PhysicsList.cc           swappable physics list + messenger
        R4ActionInitialization.cc  user action registration
        R4RunAction.cc             analysis output + histogram filler
        R4PrimaryGeneratorAction.cc  GPS
  include/  R4*.hh
  run.mac                   batch macro (geometry / physics / source / scoring)
  vis.mac                   interactive visualisation macro
  gps_point.mac             alternative GPS macro
  simpleCone.gdml / axes.gdml  test geometries
```

## Dependencies (prebuilt Windows build)

- Geant4 11.4.2 (`target/bin` is on the system PATH)
- xerces-c 3.3.0 (GDML parsing, `target/bin` is on the system PATH)
- Qt 6.11 (Geant4's prebuilt `G4interfaces.dll` needs Qt, `bin` is on the system PATH)

## Build

```bat
cmake -S rad4space -B rad4space/build -DGeant4_DIR=D:/Application/Geant4/geant4-v11.4.2/target/lib/cmake/Geant4
cmake --build rad4space/build --config Release --parallel 8
```

> If visualisation is not needed, `-DWITH_GEANT4_UIVIS=OFF` reduces the link surface.

## Running

```bat
cd rad4space\build\Release
rad4space.exe run.mac          :: batch
rad4space.exe run.mac 8        :: run with 8 threads
rad4space.exe                  :: interactive: vis.mac is executed automatically,
                               ::   the Qt window renders the axes.gdml geometry
                               ::   plus 10 proton tracks
```

### Known environment pitfall (important)

If running from a terminal with a conda environment activated fails with `0xC0000139`,
conda's older Qt6 (e.g. `pyoccenv\Library\bin`) is being loaded before the Qt6.11 that
Geant4 was built against. Put Qt6.11 first on PATH and run again:

```bat
set PATH=D:\Application\Qt6.11\6.11.1\msvc2022_64\bin;%PATH%
cd rad4space\build\Release
rad4space.exe run.mac
```

## run.mac reference

```mac
/rad4space/gdml/SetGDMLFile axes.gdml     # geometry (PreInit)
/rad4space/physics/SetPL FTFP_BERT        # physics list, switchable (QGSP_BIC/Shielding...)
/rad4space/physics/SetGlobalCut 0.7 mm
/run/initialize                           # must come before /gps /score /analysis
/gps/particle proton                      # source (exgps style)
...
/score/create/probe Probes 5. cm          # RE03-style scoring
/score/quantity/volumeFlux volFlux
/score/fill1D 0 Probes volFlux            # native 4.9.8 histogram filling
```

Note: the histogram ids created by `/analysis/h1/create` start at **0**, and
`/score/fill1D` uses the same ids.

## Particles and physics lists

**The GPS default particle is the electron e-** (G4GeneralParticleSource's internal
default). Even when only energy/position/direction are set, an e- is fired unless
`/gps/particle` is written. Always set it explicitly:

```mac
/gps/particle proton          # any Geant4 particle name
/gps/ion 26 56 26             # ion: Z A Q (e.g. Fe-56)
/gps/energy 100 MeV
```

The default `FTFP_BERT` is Geant4's all-particle reference list and covers the
particles commonly seen in space environments: electrons/positrons, gammas, protons,
neutrons, pi/K/mu, ions (H → Fe → U including nuclear fragmentation) and the decay of
unstable particles.

Recommendations for space environments (GRAS style):

| Scenario | Recommended list | Notes |
|---|---|---|
| General analysis | `FTFP_BERT` / `QGSP_BERT` | Good high-energy coverage |
| Shielding / heavy-ion protection (NASA) | `Shielding` | QMD heavy-ion fragmentation + thermal-neutron HP |
| Activation products / residual dose | `Shielding` + `AddRDM true` | Radioactive decay |

Physics commands (PreInit, must come before `/run/initialize`):

- `/rad4space/physics/SetPL <name>`: any reference list name (FTFP_BERT, QGSP_BIC,
  QGSP_BERT, Shielding, ...)
- `/rad4space/physics/AddHP true`: append `_HP` high-precision neutrons (when not using
  Shielding)
- `/rad4space/physics/AddRDM true`: register G4RadioactiveDecayPhysics (when not using
  Shielding)
- `/rad4space/physics/SetGlobalCut <len>`: production cut for gamma / e- / e+ / proton
- `/rad4space/physics/SetMaxStep <len>`: maximum step length in every volume
  (`G4UserLimits`, the equivalent of GRAS's `StepMax`; 0 = disabled, disabled by default)

**Does an ion need its own cut? No.** The production cut mechanism only means something
for gamma / e± / proton — it sets the creation threshold for secondaries (delta
electrons, photons). An ion is not bound by a production cut as an incident particle;
the fineness of its energy deposition is governed by the **electron cut** (the
delta-ray yield). Setting cuts for those four particles is therefore sufficient (and
matches the GRAS defaults).

Complete space-environment physics setup (PreInit, before `/run/initialize`, fixed
order):

```mac
# --- geometry & physics ---
/rad4space/gdml/SetGDMLFile axes.gdml
/rad4space/physics/SetPL Shielding        # NASA space shielding: QMD heavy ions + HP thermal neutrons
/rad4space/physics/AddRDM true            # radioactive decay of activation products (optional)
/rad4space/physics/SetGlobalCut 0.7 mm    # production cut for gamma/e-/e+/proton
/rad4space/physics/SetMaxStep 1. mm       # step limit: visualisation / thin-layer dose accuracy (optional)
/run/initialize
```

## Mesh test macros

Geant4 11.4 native command-based scoring (the new `/score/` syntax), four standalone
test macros (`rad4space.exe mesh_xxx.mac [threads]`, all verified):

| Macro | Coverage | Output |
|---|---|---|
| `mesh_probe.mac` | `/score/create/probe` probe cube + `/score/fill1D` 1-D histogram | `mesh_probe.csv` + `rad4space_h1_*.csv` |
| `mesh_realworld.mac` | `/score/create/realWorldLogVol` scoring on real geometry | `mesh_realworld.csv` + `rad4space_h1_*.csv` |
| `mesh_box.mac` | `/score/create/boxMesh` Cartesian mesh | `mesh_box_eDep.csv` |
| `mesh_cylinder.mac` | `/score/create/cylinderMesh` cylindrical mesh | `mesh_cylinder_eDep.csv` |

Key points:

- `/score/fill1D <histID> <mesh> <scorer>` **only supports probe and realWorldLogVol**;
  boxMesh / cylinderMesh can only be exported with `/score/dumpQuantityToFile`
- the new syntax `/score/mesh/boxSize <Dx> <Dy> <Dz> <unit>` and
  `/score/mesh/cylinderSize <R> <Dz> <unit>` takes **no mesh name** (it applies to the
  most recently created mesh)
- for cylinders the `/score/mesh/nBin` order is `Nr Nz Nphi`
- mesh commands must come after `/run/initialize` and before `/run/beamOn`
- for `realWorldLogVol` the mesh name is the logical volume name (`TOP`, `vOrigin`, ...)
  and `/score/mesh/` commands have no effect on it

## Output

- `Probes.csv`: primitive scorer integrals (total, total², entry)
- `rad4space_h1_<name>.csv`: 1-D energy spectra
- the default output type is csv (`SetDefaultFileType("csv")` in `R4RunAction`)

## Particle trajectory data (how to connect it when re-drawing)

Trajectory output is independent of scoring / histograms: it exists so the GUI can
re-draw particle paths by position. It is **always written** (there is no switch):
`R4SteppingAction` pushes trajectory points into process-wide shared storage, and the
**master's `EndOfRunAction`** writes `Traj.csv` once (in the working directory). Writing
from the master (rather than from a worker) is the most reliable single flush point,
because thread numbering differs between the default tasking mode and classic MT.

To avoid cross-thread merging, **only one worker records**: instead of hard-coding a
thread number, the **first worker to enter stepping is atomically elected**
(`ClaimRecorder()`). Under tasking, worker ids are 0..N-1; under classic MT they are
1..N — hard-coding either would break in the other mode, hence the dynamic election.

> With the default multithreaded run, `Traj.csv` therefore only contains the events
> handled by the elected worker (roughly beamOn/nThreads). For the full data set, pin
> `/run/numberOfThreads 1` in trajectory macros (the single worker is always elected).
> In serial mode there are no worker threads, so nothing is written.

Two constants bound the output; they are **hardcoded** in `R4RunAction.cc` (change them
and recompile if needed):

- `kMaxRecordEvents`: maximum number of complete events recorded (0 = unlimited, the
  default);
- `kMaxTrajPoints`: maximum total number of points in `Traj.csv` (default about 5000).

Truncation happens on **event / trajectory boundaries**, so every written track is
complete (no half-drawn polylines).

### Data model: one row per point, with grouping keys (units: mm)

```
eventID, trackID, parentID, particle, step, x, y, z
```

- the row with `step=0` is that track's **origin (vertex)**; `step=1..N` are the end
  points of each step;
- `parentID=0` ⇒ primary; a secondary's `parentID` points at the trackID that created
  it;
- the `particle` name is kept only so the reader can **colour by particle type** (the
  "manual" colour table lives on the reader side; the solver produces no colours).

### Why only positions + grouping keys, and no vol / t / Ekin

Re-drawing cares about exactly one thing: **the polyline's geometry and its connection
order**.

- geometry: fully determined by the ordered `(x,y,z)`;
- connection order: determined by `(eventID, trackID, step)`.

`vol / t / Ekin` take no part in the polyline topology, so adding them would not change
the re-draw; if they are needed later they can be looked up in post-processing by
`(eventID, trackID, step)`, or appended as extra attribute columns, without changing
the connection rule.

### Connection rules (reader side — follow these to avoid mis-connections)

1. group by `(eventID, trackID)` — one group is one trajectory;
2. sort each group by `step` ascending;
3. connect adjacent points into segments.

Three pitfalls that are exactly why the grouping keys are required:

- a secondary is "born" at the end point of one of its parent's steps, so the two
  **share coordinates but differ in trackID**; connecting by position / nearest
  neighbour would cross-link them → grouping by trackID is mandatory;
- trackIDs restart at 1 inside every event → **the grouping key must include eventID**,
  otherwise different events get connected to each other;
- only thread 1 is sampled here: its eventIDs restart at 0 and cover only the share of
  events that thread received → use `/run/numberOfThreads 1` (thread 1 is then the only
  worker) when complete event numbers or the full data set are needed.
