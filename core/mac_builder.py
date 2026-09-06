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


# analysis_config key (CONFIG_KEY) -> human label, in precedence order when the
# user has configured more than one (normally only one is active per task).
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

# Beam events used when CalculateSetting.n_events is unset (0). 4000 matches
# the rad4space example macro, giving a small but non-trivial result per run.
DEFAULT_EVENTS = 4000

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


def active_kind(analysis_config) -> str | None:
    """The analysis kind that is actually configured, or None if none is.  If
    several are configured we take the first (realworld > probe > voxel) so the
    run still works, mirroring the analysis-type precedence used by the tree."""
    for key, _label in KINDS:
        if _kind_is_active(analysis_config, key):
            return key
    return None


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

def _scoring_realworld(volumes):
    """volumes: { LVname : {"qs":[...], "hs":[...]} }"""
    h1, fill, dumps = [], [], []
    id_state = {"n": 0}
    for lv, cfg in (volumes or {}).items():
        if not (cfg.get("qs") or cfg.get("hs")):
            continue
        mesh = lv  # mesh name == logical volume name for realWorldLogVol
        block = [f"/score/create/realWorldLogVol {mesh}"]
        block += _quantity_lines(cfg.get("qs"))
        block.append("/score/close")
        _h1, _f = _histogram_lines(mesh, cfg.get("qs"), cfg.get("hs"), id_state)
        h1 += _h1
        fill += _f
        dumps += _dump_line("realworld", mesh, cfg.get("qs"))
        yield "\n".join(block)
    yield from h1
    yield from fill
    yield from dumps


def _scoring_probe(probes):
    h1, fill, dumps = [], [], []
    id_state = {"n": 0}
    for p in (probes or []):
        if not (p.get("qs") or p.get("hs")):
            continue
        name = p.get("name", "P")
        block = [f"/score/create/probe {name} {_num(p.get('half', 50.0) / 10)} cm"]
        block.append(f"/score/probe/locate {_num(p.get('x', 0) / 10)} "
                     f"{_num(p.get('y', 0) / 10)} {_num(p.get('z', 0) / 10)} cm")
        block += _quantity_lines(p.get("qs"))
        block.append("/score/close")
        _h1, _f = _histogram_lines(name, p.get("qs"), p.get("hs"), id_state)
        h1 += _h1
        fill += _f
        dumps += _dump_line("probe", name, p.get("qs"))
        yield "\n".join(block)
    yield from h1
    yield from fill
    yield from dumps


def _scoring_voxel(vcfg):
    half = vcfg.get("half", [50.0, 50.0, 50.0])
    nbin = vcfg.get("nbin", [10, 10, 10])
    center = vcfg.get("center", [0.0, 0.0, 0.0])
    qs = vcfg.get("qs", [])
    mesh = "Box"
    yield (f"/score/create/boxMesh {mesh}\n"
           f"/score/mesh/boxSize {_num(2 * half[0] / 10)} "
           f"{_num(2 * half[1] / 10)} {_num(2 * half[2] / 10)} cm\n"
           f"/score/mesh/nBin {int(nbin[0])} {int(nbin[1])} {int(nbin[2])}\n"
           f"/score/mesh/translate/xyz {_num(center[0] / 10)} "
           f"{_num(center[1] / 10)} {_num(center[2] / 10)} cm\n"
           + "\n".join(_quantity_lines(qs))
           + "\n/score/close")
    # boxMesh has no 1-D histogram support; dump each quantity to its own csv
    for q in qs or []:
        yield f"/score/dumpQuantityToFile {mesh} {q.get('name', 'q')} " \
              f"out_{mesh}_{q.get('name', 'q')}.csv"


# ----------------------------------------------------------------------
# top-level assembly
# ----------------------------------------------------------------------

def scoring_block(analysis_config):
    """The scoring macro text appended after initialize for the active kind
    (or a small comment if nothing is configured)."""
    kind = active_kind(analysis_config)
    if kind is None:
        return ["# (no analysis configured for this task - no scoring mesh)"]
    cfg = analysis_config.get(kind) or {}
    lines = []
    if kind == "realworld":
        lines += list(_scoring_realworld(cfg.get("volumes") or {}))
    elif kind == "probe":
        lines += list(_scoring_probe(cfg.get("probes") or []))
    elif kind == "voxel":
        lines += list(_scoring_voxel(cfg))
    return lines


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
    lines = ["/control/saveHistory"]
    if n_threads > 0:
        lines.append(f"/run/numberOfThreads {n_threads}")
    lines += [
        "/run/verbose 1",
        "/control/verbose 1",
        "/event/verbose 0",
        "/tracking/verbose 0",
    ]
    # 2. geometry (PreInit)
    lines.append("")
    lines.append(f"/rad4space/gdml/SetGDMLFile {gdml_full_path}")
    # 3. physics (PreInit)
    lines.append("")
    lines += pcfg.macro_lines(task.physics)
    # 4. initialize (options freeze here)
    lines.append("")
    lines.append("/rad4space/initialize")
    # 5. primary source
    lines.append("")
    src_lines = gps.macro_lines(task.particle or {})
    lines += (src_lines if src_lines else ["# (no particle source configured)"])
    # 6. scoring
    lines.append("")
    lines += scoring_block(task.analysis_config)
    # 7. run (event count is reserved in CalculateSetting; fall back to a
    # reasonable default so the run actually produces a non-trivial result)
    lines.append("")
    nevents = int(getattr(task.calculate, "n_events", 0) or 0)
    if nevents <= 0:
        nevents = DEFAULT_EVENTS
    lines.append(f"/run/beamOn {nevents}")
    return "\n".join(lines) + "\n"


def write_workdir(gdml_full_path: str, task, out_root: str):
    """Prepare a per-task working directory under out_root and write the
    run.mac there. Returns the work dir path. The gdml is referenced by its
    absolute path (SetGDMLFile), so it does not need copying.

    out_root is created if missing; a per-task subdir avoids collisions when
    several tasks run concurrently (results land in out_root/<task>/)."""
    import re
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name) or "task"
    work = os.path.join(out_root, safe)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "run.mac"), "w", encoding="utf-8") as f:
        f.write(build_mac_text(gdml_full_path, task))
    return work
