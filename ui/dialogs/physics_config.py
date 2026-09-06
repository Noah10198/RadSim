"""
physics_config - physics process metadata + run.mac writer (pure Python, no Qt).

Mirrors solver/rad4space/src/R4PhysicsList.cc - the whole physics surface is
five PreInit commands written before /run/initialize:

    /rad4space/physics/SetPL <name>    select Geant4 reference physics list
    /rad4space/physics/AddHP true      append _HP high-precision neutrons
    /rad4space/physics/AddRDM true     register G4RadioactiveDecayPhysics
    /rad4space/physics/SetGlobalCut x mm   production cut gamma/e-/e+/proton
    /rad4space/physics/SetMaxStep x mm     G4UserLimits max step (0 = off)

RunTask.physics keys: physics_list, add_hp, add_rdm, global_cut_mm, max_step_mm.
"""

# Lists that already include the high-precision neutron treatment: AddHP would
# append a second "_HP" to the name, so it must stay off.
HP_BUILTIN = {"Shielding", "ShieldingLEND"}
# rad4space registers G4RadioactiveDecayPhysics unless the base name is exactly
# "Shielding" (R4PhysicsList::GeneratePL()).
RDM_BUILTIN = {"Shielding"}

# Curated, space-relevant reference lists. Anything accepted by
# G4PhysListFactory is valid; this is the shortlist the dialog offers.
# Each item: (key, one-line model set, extra note)
REFERENCE_LISTS = [
    ("FTFP_BERT",
     "FTFP string + Bertini cascade",
     "rad4space default and best general-purpose choice: Fritiof string model "
     "for the high-energy tail, Bertini cascade below ~10 GeV."),
    ("QGSP_BERT",
     "Quark-Gluon string + Bertini cascade + precompound",
     "Classic full list; QGS above ~20 GeV, BERT below. Matches many published "
     "Geant4 benchmarks."),
    ("QGSP_BIC",
     "Quark-Gluon string + Binary cascade",
     "BIC intra-nuclear transport below ~10 GeV, popular for proton / ion "
     "therapy and low-energy hadron studies."),
    ("QGSP_FTFP_BERT",
     "QGS + FTF forward region + Bertini cascade",
     "QGS in the central region, FTF for the forward / diffractive part, BERT "
     "at low energy."),
    ("FTF_BIC",
     "FTFP string + Binary cascade",
     "FTF at high energy plus the more detailed BIC at low energy."),
    ("QBBC",
     "Quark-Gluon precompound + string models",
     "Custom full reference list used in medical-physics work."),
    ("QGSP_INCLXX",
     "Quark-Gluon string + INCL++ cascade",
     "CEA INCL++ intra-nuclear cascade, used for p / n / light-ion spallation "
     "benchmarks."),
    ("Shielding",
     "FTFP_BERT + QMD ion fragmentation + HP neutrons",
     "NASA space-radiation list: QMD heavy-ion fragmentation (H-Fe-U) and "
     "high-precision thermal neutrons. Best for shielding / SPE / heavy-ion "
     "transport. Already includes HP; rad4space skips AddRDM on it."),
    ("ShieldingLEND",
     "Shielding with LEND low-energy neutron data",
     "Shielding whose low-energy neutrons use ENDF-driven LEND models instead "
     "of the native HP tables."),
]

COVERAGE_TEXT = (
    "Particle types handled: gamma, e-/e+, mu, pi, K, proton, neutron "
    "(thermal-to-high with HP / Shielding), light ions d/t/alpha/He3 and "
    "heavy ions up to U (fragmentation detail depends on the list). AddRDM "
    "additionally decays activation products via beta/alpha chains."
)

# (range, unit text, decimal digits, hint) used by the dialog spin boxes
CUT = ("global_cut_mm", 0.0, 100.0, 4,
       "Production threshold for gamma / e- / e+ / proton - it sets how finely "
       "secondary delta-electrons and photons are generated. Ions are never "
       "cut directly; their energy-deposit detail is governed by the e- cut.")
STEP = ("max_step_mm", 0.0, 100000.0, 3,
        "Maximum step length applied to every volume (G4UserLimits, GRAS "
        "StepMax). 0 = no limit. A limit improves thin-layer energy-deposit "
        "accuracy and visibility of tracks.")


def default_config():
    return {"physics_list": "FTFP_BERT", "add_hp": False, "add_rdm": False,
            "global_cut_mm": 0.7, "max_step_mm": 0.0}


def sanitize(config):
    cfg = default_config()
    if isinstance(config, dict):
        for k in cfg:
            if k in config and config[k] is not None:
                cfg[k] = config[k]
        if cfg["physics_list"] not in [e[0] for e in REFERENCE_LISTS]:
            cfg["physics_list"] = "FTFP_BERT"
    return cfg


def supports_hp(key):
    return key not in HP_BUILTIN


def supports_rdm(key):
    return key not in RDM_BUILTIN


def info(key):
    """(model-set text, note) for a reference list key."""
    for k, models, note in REFERENCE_LISTS:
        if k == key:
            return models, note
    return REFERENCE_LISTS[0][1], REFERENCE_LISTS[0][2]


def summary_text(key):
    """Multiline human summary: model set + coverage + note."""
    models, note = info(key)
    return (f"{key}: {models}\n\n{COVERAGE_TEXT}\n\nNote: {note}")


def _num(v):
    return ("%g" % v) if isinstance(v, float) else str(v)


def macro_lines(cfg):
    """Command lines only (no comments) in macro order."""
    c = sanitize(cfg)
    out = [f"/rad4space/physics/SetPL {c['physics_list']}"]
    if c["add_hp"] and supports_hp(c["physics_list"]):
        out.append("/rad4space/physics/AddHP true")
    if c["add_rdm"] and supports_rdm(c["physics_list"]):
        out.append("/rad4space/physics/AddRDM true")
    out.append(f"/rad4space/physics/SetGlobalCut {_num(c['global_cut_mm'])} mm")
    if c["max_step_mm"] > 0.0:
        out.append(f"/rad4space/physics/SetMaxStep {_num(c['max_step_mm'])} mm")
    return out


def macro_preview(cfg):
    """Full PreInit block with comment header, as shown in the dialog."""
    c = sanitize(cfg)
    head = [
        "# ---- physics process (PreInit, before /run/initialize) ----",
        "# Physics list decides which processes are built (EM, hadronic",
        "# cascades / strings, decay ...) and therefore which particles exist."]
    lines = macro_lines(c)
    if c["add_hp"] and not supports_hp(c["physics_list"]):
        lines.insert(1, "# (AddHP skipped: the list already has HP neutrons)")
    if c["add_rdm"] and not supports_rdm(c["physics_list"]):
        lines.insert(1, "# (AddRDM skipped: no effect with Shielding)")
    return "\n".join(head + lines)
