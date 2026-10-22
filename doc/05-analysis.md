# 05 · Analysis and Results

> Source: `ui/dialogs/analysis_common.py`, `ui/dialogs/{realworld,probe,voxel}_dialog.py`,
> `core/mac_builder.py`, `ui/probe_result_viewer.py`

## Contents

- [1. The three analysis modes](#1-the-three-analysis-modes)
- [2. Configuration data structure](#2-configuration-data-structure)
- [3. Scoring quantity list](#3-scoring-quantity-list)
- [4. Filters and particle options](#4-filters-and-particle-options)
- [5. 1D histogram rules](#5-1d-histogram-rules)
- [6. Result parsing and grouping](#6-result-parsing-and-grouping)
- [7. Result nodes in the project tree](#7-result-nodes-in-the-project-tree)
- [8. Common pitfalls](#8-common-pitfalls)

## 1. The three analysis modes

| kind | What is scored | Mesh | Output | Viewer |
|---|---|---|---|---|
| `realworld` | logical volumes | one scorer per volume | `out_<LV>.csv` | bar chart / spectrum |
| `probe` | probe cubes | one scorer per probe | `out_<probe>.csv` | bar chart / spectrum |
| `voxel` | a rectilinear mesh | a single `boxMesh` | `out_Box_<q>.csv` | 3D volume rendering |

The three modes **can be enabled together**; the test is "does this mode have at least one scoring
quantity configured" (`mac_builder._kind_is_active`).

## 2. Configuration data structure

```python
task.analysis_config = {
    "realworld": {"volumes": {<LVname>: (qs, hs)}},
    "probe":     {"probes": [{"name","half","x","y","z","material","qs","hs"}]},
    "voxel":     {"mode","center","half","nbin","selected","qs","hs"},
}
```

- `qs`: the scoring quantity list, each entry `{"name": str, "type": str, "filter": str | None}`
- `hs`: the 1D histogram list, each entry `{"q": <quantity name>, "bins": int, "rng": [lo, hi], "log": bool}`
- `half` / `x,y,z` / `center` are all in **mm** (divided by 10 when written to the macro)
- `voxel.mode`: `all_geo` (take the bounding box of the whole geometry) or `manual` (enter
  centre/half by hand)

## 3. Scoring quantity list

The authority is `analysis_common.QUANTITY_TYPES` (`type, label, unit, histogram x unit`):

| type | Unit | Histogram x unit |
|---|---|---|
| `energyDeposit` | MeV | MeV |
| `doseDeposit` | Gy | Gy |
| `volumeFlux` | — | MeV |
| `nOfStep` | — | mm |
| `nOfTrack` | — | MeV |
| `nOfSecondary` | — | MeV |
| `cellFlux` | cm⁻² | MeV |
| `passageCellFlux` | cm⁻² | MeV |
| `passageCellCurrent` | — | MeV |
| `passageTrackLength` | mm | mm |
| `trackLength` | mm | not supported |
| `cellCharge` | e⁺ | not supported |
| `nOfCollision` | — | not supported |
| `nOfTerminatedTrack` | — | not supported |
| `population` | — | not supported |

An empty unit column is shown as `[count]` in the UI. Only `energyDeposit` / `doseDeposit` carry a
unit inside the macro; everything else is emitted in the solver's native unit (see
`mac_builder._QUANTITY_UNIT`).

## 4. Filters and particle options

`FILTER_TYPES` (the only five Geant4 implements): `particle`, `kineticEnergy`,
`particleWithEnergy`, `charged`, `neutral`.

`PARTICLE_CHOICES`: gamma, e-, e+, proton, neutron, alpha, He3, deuteron, triton, mu-, mu+, pi-,
pi+.

`ENERGY_UNITS`: MeV, keV, GeV.
`MATERIAL_CHOICES` (probes): none, G4_WATER, G4_AIR, G4_Al, G4_Cu, G4_Fe, G4_Pb.

## 5. 1D histogram rules

1. supported only when `quantity_meta(type)[1] is not None`; otherwise the row is skipped
   silently;
2. the default range follows the quantity type (`HISTOGRAM_DEFAULT_RANGES`), e.g.
   `energyDeposit (0.001, 10)` and `doseDeposit (0.0001, 1)`; an unknown type falls back to
   `(0.001, 1000)`;
3. **every series of the same quantity type must share bins / range / log**, otherwise the x axes
   do not line up once they are overlaid. `histogram_parameter_conflicts()` warns about this while
   the user is still editing the form;
4. histogram ids are handed out by a **single global counter** in `mac_builder`
   (`/score/fill1D <id> <mesh> <q>`), and must keep increasing when several meshes are active.

## 6. Result parsing and grouping

`probe_result_viewer.py` is a pure data module (it imports neither Qt nor matplotlib):

| Function | Input | Output |
|---|---|---|
| `parse_out_csv` | `out_*.csv` | `{"mesh", "blocks": [{name, unit, value, entry}]}`, the unit read back from a `# ... [MeV]` legend line |
| `parse_h1_csv` | `rad4space_h1_*.csv` | `{nbins, lo, hi, log, edges, centers, counts, total, underflow, overflow, title}` |
| `rebin_log` | a linear histogram | some builds write `#axis fixed` even when configured for log, so the histogram is rebuilt on a log10 axis with the same lo/hi/nbins |
| `build_result_groups` | `entities` (name/qs/hs) + work_dir | `{"quantity": [...], "histogram": [...]}` |
| `build_probe_result_groups` | probe list + work_dir | as above |
| `find_group` | groups + kind + label | one group |

**The grouping key is the quantity type, not the quantity name** — so `doseDeposit` from P1, P2 and
P3 lands in the same group for comparison, labelled `doseDeposit [Gy]`. Series whose file is
missing are dropped and empty groups are removed.

## 7. Result nodes in the project tree

When a task finishes, `_refresh_task_results()` clears and rebuilds from disk:

```
<task>
└── Results
    ├── <type [unit]>          ← quantity group, double-click opens a bar chart
    │   ├── <probe1>: <qname>
    │   └── <probe2>: <qname>
    ├── <type [xunit]>         ← histogram group, double-click opens a step curve
    ├── Voxel <qname>          ← double-click opens 3D volume rendering
    ├── Trajectory             ← double-click opens the trajectory viewer
    └── run log
```

## 8. Common pitfalls

| Pitfall | Explanation |
|---|---|
| duplicate quantity names | a repeated name inside one mesh makes the dump files overwrite each other |
| an `hs` without a matching `qs` | the quantity is never created, so the histogram has no data |
| probe material set to `none` | no `/score/probe/material` is written and the solver default applies |
| a hand-entered voxel `half` that is too large | volume rendering memory grows as `(nbin+1)³` |
| inconsistent histogram bins | curve comparison is skewed; the dialog warns in advance |
| changing the quantity type but not the name | grouping follows the type, the name is display only |
