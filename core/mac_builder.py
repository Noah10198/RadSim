"""
mac_builder - assemble the rad4space run.mac for one RunTask.

Pure Python (no Qt). Reuses the physics and particle-source writers:
    - ui.dialogs.physics_config.macro_lines(cfg)   -> /rad4space/physics/* PreInit block
    - ui.dialogs.gps_source.macro_lines(cfg)       -> /gps/* source block (gun / gps / file)

and adds the analysis scoring block built from task.analysis_config. The three
analysis kinds map onto Geant4 command-based scoring:

    realworld (CONFIG_KEY "realworld"):
        analysis_config["realworld"]["volumes"] = { LVname: {"qs":[...], "hs":[...]} }
        -> one /score/create/realWorldLogVol <LVname> per configured logical volume
    probe     (CONFIG_KEY "probe"):
        analysis_config["probe"]["probes"] = [ {name,half,x,y,z,material,qs,hs}, ... ]
        -> one /score/create/probe <name> per probe
    voxel     (CONFIG_KEY "voxel"):
        analysis_config["voxel"] = {mode,half[],nbin[],center[],selected,qs[],unit,bbox}
        -> a single /score/create/boxMesh

Histogram binding (1-D energy spectra) uses G4TScoreHistFiller: every
/analysis/h1/create gets the NEXT global id (ids are assigned in creation order
across the whole run), then /score/fill1D <id> <mesh> <quantity> links it to a
scorer mesh + quantity by NAME (config stores histograms per-mesh whose
"q" field is the quantity name inside that mesh).

Units: the GUI stores lengths in mm; the solver expects cm (/10 everywhere).
"""

import os


# analysis_config key (CONFIG_KEY) -> human label, in precedence order used by
# active_kind() for a canonical label. Run.mac generation emits EVERY
# configured kind (active_kinds()), so several analyses can be scored together
# in the same /run/beamOn.
KINDS = [
    ("realworld", "real world"),
    ("probe", "probe"),
    ("voxel", "voxel"),
]

# Primitive-scorer name used by the /score/quantity command is the same as the
# analysis "type" key.  A unit suffix is appended only for the two scorers that
# sample files write a unit for; all others are left unit-less (native units).
_QUANTITY_UNIT = {"energyDeposit": "MeV", "doseDeposit": "Gy"}

# Quantity type -> 1-D histogram x-axis unit (None = no energy-spectrum / fill1D
# support). Mirrors analysis_common.QUANTITY_TYPES hx column without pulling the
# Qt UI module into core.
_HIST_XUNIT = {
    "energyDeposit": "MeV", "doseDeposit": "Gy", "volumeFlux": "MeV",
    "nOfStep": "mm", "nOfTrack": "MeV", "nOfSecondary": "MeV",
    "cellFlux": "MeV", "passageCellFlux": "MeV", "passageCellCurrent": "MeV",
    "passageTrackLength": "mm", "trackLength": None, "cellCharge": None,
    "nOfCollision": None, "nOfTerminatedTrack": None, "population": None,
}

# Beam events used when CalculateSetting.n_events is unset (0). 10000 matches
# the rad4space example macro, giving a small but non-trivial result per run.
DEFAULT_EVENTS = 10000

# "active" means the config carries at least one configured quantity.
def _kind_is_active(analysis_config, key) -> bool:
    cfg = analysis_config.get(key) or {}
    if key == "realworld":
        vols = cfg.get("volumes") or {}
        return any(q or h for q, h in vols.values())
    if key == "probe":
        probes = cfg.get("probes") or []
        return any(p.get("qs") or p.get("hs") for p in probes)
    if key == "voxel":
        return bool(cfg.get("qs"))
    return False


def active_kinds(analysis_config) -> list:
    """Every analysis kind that carries at least one configured quantity, in
    KINDS order (realworld > probe > voxel).

    A task may configure several analyses at once - probe and voxel, for
    example. Each such mesh is an independent scorer, so rad4space can score
    them all inside the SAME /run/beamOn: this list drives scoring_block() to
    emit every configured mesh instead of silently keeping only one."""
    return [key for key, _label in KINDS
            if _kind_is_active(analysis_config, key)]


def active_kind(analysis_config) -> str | None:
    """The single analysis kind a run would be described by (the highest in
    precedence among the configured ones), or None if none is configured.
    Kept for callers that need one canonical label; macro generation uses
    active_kinds() so several analyses are never dropped."""
    kinds = active_kinds(analysis_config)
    return kinds[0] if kinds else None


# ----------------------------------------------------------------------
# per-mesh scoring text
# ----------------------------------------------------------------------

def _num(v):
    return ("%g" % v) if isinstance(v, float) else str(v)


def _quantity_lines(qs):
    """/score/quantity lines for a mesh."""
    out = []
    for q in qs or []:
        name = q.get("name", "q")
        typ = q.get("type", "energyDeposit")
        unit = _QUANTITY_UNIT.get(typ)
        out.append(f"/score/quantity/{typ} {name}"
                   + (f" {unit}" if unit else ""))
    return out


def _histogram_lines(mesh, qs, hs, id_state):
    """Return ([/analysis/h1/create ...], [fill1D ...]) for one mesh's hs.

    /analysis/h1/create <name> <title> <nbins> <xmin> <xmax> <unit> <scheme>
    /score/fill1D <globalId> <mesh> <quantityName>
    """
    qmeta = {q.get("name", "q"): q for q in qs or []}
    h1_lines, fill_lines = [], []
    for h in hs or []:
        qname = h.get("q", "")
        q = qmeta.get(qname)
        if q is None:
            continue
        hx = _HIST_XUNIT.get(q.get("type", "energyDeposit"))
        if hx is None:
            continue  # quantity does not support a 1-D histogram
        hid = id_state["n"]
        id_state["n"] += 1
        h1 = (f"/analysis/h1/create {mesh}_{qname} {mesh}_{qname} "
              f"{int(h.get('bins', 100))} {_num(h['rng'][0])} "
              f"{_num(h['rng'][1])} {hx or ''}".rstrip())
        if h.get("log"):
            h1 += " ! log"
        h1_lines.append(h1)
        fill_lines.append(f"/score/fill1D {hid} {mesh} {qname}")
    return h1_lines, fill_lines


def _dump_line(kind, mesh, qs):
    """Final dump command for one mesh (name must match the created mesh)."""
    fname = f"out_{mesh}.csv"
    if kind == "voxel":
        # 3-D box grid: one csv per quantity (no dumpAll for grids)
        return [f"/score/dumpQuantityToFile {mesh} {q.get('name', 'q')} "
                f"out_{mesh}_{q.get('name', 'q')}.csv" for q in (qs or [])]
    return [f"/score/dumpAllQuantitiesToFile {mesh} {fname}"]


# ----------------------------------------------------------------------
# scoring block for each kind
# ----------------------------------------------------------------------
# Each scoring builder returns (setup, dumps):
#   - setup  : mesh / histogram creation, must be issued BEFORE /run/beamOn
#              (mesh + h1 must exist and fill1D must be bound when the run
#              starts, otherwise there is nothing to accumulate into)
#   - dumps  : /score/dump* output commands, must be issued AFTER /run/beamOn
#              - dumping before the run writes an all-zero file
# build_mac_text() emits setup -> /run/beamOn -> dumps in that order.

def _scoring_realworld(volumes, id_state):
    """volumes: { LVname : {"qs":[...], "hs":[...]} }
    Returns (setup_lines, dump_lines). setup_lines is a FLAT list of macro
    lines: each configured logical volume opens with a blank line + a
    '# ...' comment and is immediately followed by its OWN 1-D histogram /
    fill1D lines, so every scoring block stays readable on its own.
    id_state is the shared 1-D histogram id counter across the whole run
    (ids are global for G4TScoreHistFiller)."""
    setup, dumps = [], []
    for lv, cfg in (volumes or {}).items():
        if not (cfg.get("qs") or cfg.get("hs")):
            continue
        mesh = lv  # mesh name == logical volume name for realWorldLogVol
        setup.append("")
        setup.append(f"# real world volume scorer: {mesh}")
        setup.append(f"/score/create/realWorldLogVol {mesh}")
        setup += _quantity_lines(cfg.get("qs"))
        setup.append("/score/close")
        h1, fill = _histogram_lines(mesh, cfg.get("qs"), cfg.get("hs"),
                                    id_state)
        setup += h1
        setup += fill
        dumps += _dump_line("realworld", mesh, cfg.get("qs"))
    return setup, dumps


def _scoring_probe(probes, id_state):
    """Returns (setup_lines, dump_lines). setup_lines is a FLAT list of macro
    lines: each configured probe opens with a blank line + a '# ...' comment
    and is immediately followed by its OWN 1-D histogram / fill1D lines.
    id_state is the shared 1-D histogram id counter across the whole run (ids
    are global for G4TScoreHistFiller)."""
    setup, dumps = [], []
    for p in (probes or []):
        if not (p.get("qs") or p.get("hs")):
            continue
        name = p.get("name", "P")
        setup.append("")
        setup.append(f"# probe scorer: {name}")
        setup.append(
            f"/score/create/probe {name} {_num(p.get('half', 50.0) / 10)} cm")
        mat = p.get("material")
        if mat and mat != "none":
            # Material override: overwrites the geometry material inside the
            # probe cube (manual 4.9.4, listing 4.31).
            setup.append(f"/score/probe/material {mat}")
        setup.append(f"/score/probe/locate {_num(p.get('x', 0) / 10)} "
                     f"{_num(p.get('y', 0) / 10)} {_num(p.get('z', 0) / 10)} cm")
        setup += _quantity_lines(p.get("qs"))
        setup.append("/score/close")
        h1, fill = _histogram_lines(name, p.get("qs"), p.get("hs"), id_state)
        setup += h1
        setup += fill
        dumps += _dump_line("probe", name, p.get("qs"))
    return setup, dumps


def _scoring_voxel(vcfg):
    """Returns (setup_lines, dump_lines). setup_lines is a FLAT list of macro
    lines opening with a blank line + a '# ...' comment (boxMesh has no 1-D
    histogram support; each quantity is dumped to its own csv)."""
    half = vcfg.get("half", [50.0, 50.0, 50.0])
    nbin = vcfg.get("nbin", [10, 10, 10])
    center = vcfg.get("center", [0.0, 0.0, 0.0])
    qs = vcfg.get("qs", [])
    mesh = "Box"
    setup = [
        "",
        "# voxel (boxMesh) scoring: 3-D grid over the scored geometry",
        f"/score/create/boxMesh {mesh}",
        # Geant4 /score/mesh/boxSize takes the HALF lengths of the box mesh,
        # not the full width; half[] is the true half extent in mm -> /10 cm.
        "# /score/mesh/boxSize takes the HALF extents of the box (mm -> cm)",
        f"/score/mesh/boxSize {_num(half[0] / 10)} "
        f"{_num(half[1] / 10)} {_num(half[2] / 10)} cm",
        f"/score/mesh/nBin {int(nbin[0])} {int(nbin[1])} {int(nbin[2])}",
        f"/score/mesh/translate/xyz {_num(center[0] / 10)} "
        f"{_num(center[1] / 10)} {_num(center[2] / 10)} cm",
    ]
    setup += _quantity_lines(qs)
    setup.append("/score/close")
    dumps = [f"/score/dumpQuantityToFile {mesh} {q.get('name', 'q')} "
             f"out_{mesh}_{q.get('name', 'q')}.csv" for q in (qs or [])]
    return setup, dumps


# ----------------------------------------------------------------------
# top-level assembly
# ----------------------------------------------------------------------

def scoring_block(analysis_config):
    """Scoring macro for ALL configured analysis kinds, one scorer mesh block
    per kind (realworld volumes, probes and/or the voxel boxMesh) so e.g. a
    probe + voxel run scores both meshes in the same /run/beamOn.

    Returns (setup_lines, dump_lines): setup goes before /run/beamOn (mesh +
    histogram creation), dumps go after it (see header comment above). Returns
    a comment + empty dumps when no analysis is configured. Histogram ids are
    assigned from ONE shared counter because G4TScoreHistFiller numbers h1
    meshes globally in creation order across the whole run."""
    kinds = active_kinds(analysis_config)
    if not kinds:
        # Blank line + comment so the source section above stays separated.
        return (["", "# (no analysis configured for this task - no scoring "
                     "mesh)"],
                [])
    setup, dumps, id_state = [], [], {"n": 0}
    labels = dict(KINDS)
    for kind in kinds:
        cfg = analysis_config.get(kind) or {}
        if kind == "realworld":
            s, d = _scoring_realworld(cfg.get("volumes") or {}, id_state)
        elif kind == "probe":
            s, d = _scoring_probe(cfg.get("probes") or [], id_state)
        else:
            s, d = _scoring_voxel(cfg)
        setup += s
        if d:
            # A '#' comment before each analysis kind's dump block, so the
            # outputs of several analyses are easy to tell apart.
            dumps.append(f"# {labels.get(kind, kind)} output")
            dumps += d
    return setup, dumps


def build_mac_text(gdml_full_path: str, task) -> str:
    """Full run.mac for a task. task.physics / task.particle /
    task.analysis_config / task.calculate drive the physics, source, scoring
    and event sections. gdml_full_path is the absolute path to the geometry."""
    from ui.dialogs import physics_config as pcfg
    from ui.dialogs import gps_source as gps

    # Thread block, right after /control/saveHistory as the macro spec asks:
    # the whole run configuration lives in the macro, so the solver is started
    # with run.mac as its ONLY argument. When the task carries an assigned
    # thread count it is written here; a task without one (n_threads == 0)
    # simply omits the line and the solver falls back to its own default.
    n_threads = int(getattr(task.calculate, "n_threads", 0) or 0)

    # 1. verbosity
    lines = ["# run control and verbosity", "/control/saveHistory"]
    if n_threads > 0:
        lines.append(f"/run/numberOfThreads {n_threads}")
    lines += [
        "/run/verbose 1",
        "/control/verbose 1",
        "/event/verbose 0",
        "/tracking/verbose 0",
    ]
    # 2. geometry (PreInit)
    lines += ["", "# geometry setting",
              f"/rad4space/gdml/SetGDMLFile {gdml_full_path}"]
    # 3. physics (PreInit)
    lines += ["", "# physics setting"]
    lines += pcfg.macro_lines(task.physics)
    # 4. initialize (options freeze here)
    lines += ["", "# initialize (run options are frozen from this point)",
              "/run/initialize"]
    # 5. primary source
    lines += ["", "# primary particle source"]
    src_lines = gps.macro_lines(task.particle or {})
    lines += (src_lines if src_lines else ["# (no particle source configured)"])
    # 6. scoring - only the mesh / histogram setup goes here; the dump
    # commands must follow /run/beamOn (section 8) or they write zero files.
    # scoring_block() already starts each analysis block with a blank line +
    # a '#' comment of its own.
    scoring_setup, scoring_dumps = scoring_block(task.analysis_config)
    lines += scoring_setup
    # 7. run (event count is reserved in CalculateSetting; fall back to a
    # reasonable default so the run actually produces a non-trivial result)
    nevents = int(getattr(task.calculate, "n_events", 0) or 0)
    if nevents <= 0:
        nevents = DEFAULT_EVENTS
    lines += ["", "# run", f"/run/beamOn {nevents}"]
    # 8. dump results AFTER the run: dumping before beamOn writes an
    # all-zero file. scoring_block() already labels each kind's dump block.
    if scoring_dumps:
        lines += ["", "# scoring output (dumped AFTER /run/beamOn - dumping "
                       "before the run writes an all-zero file)"]
        lines += scoring_dumps
    return "\n".join(lines) + "\n"


def write_workdir(gdml_full_path: str, task, out_root: str):
    """Prepare a per-task working directory under out_root and write the
    run.mac there. Returns the work dir path. The gdml is referenced by its
    absolute path (SetGDMLFile), so it does not need copying.

    out_root is created if missing; a per-task subdir avoids collisions when
    several tasks run concurrently (results land in out_root/<task>/).

    The per-task directory is wiped first: a re-run must never mix the previous
    run's csv/log files with the new ones (a shorter run would otherwise leave
    stale dumps behind)."""
    import re
    import shutil
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name) or "task"
    work = os.path.join(out_root, safe)
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "run.mac"), "w", encoding="utf-8") as f:
        f.write(build_mac_text(gdml_full_path, task))
    return work
