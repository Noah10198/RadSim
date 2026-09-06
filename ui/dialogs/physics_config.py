"""
physics_config - physics process metadata + run.mac writer (pure Python, no Qt).

Mirrors solver/rad4space/src/R4PhysicsList.cc - the whole physics surface is
five PreInit commands written before /run/initialize:

    /rad4space/physics/SetPL <name>    select Geant4 reference physics list
    /rad4space/physics/AddHP true      append _HP high-precision neutrons
    /rad4space/physics/AddRDM true     register G4RadioactiveDecayPhysics
    /rad4space/physics/SetGlobalCut x mm   production cut gamma/e-/e+/proton
    /rad4space/physics/SetMaxStep x mm     G4UserLimits max step (0 = off)

IMPORTANT (solver >= new SetPL): the reference physics list is a SINGLE
G4PhysListFactory name, so HP / RDM / EM options are usually already encoded in
the name itself, e.g. QGSP_BIC_HP, Shielding_EMY, FTFP_BERT_EMZ.  The AddHP /
AddRDM toggles still exist and are only meaningful when the base name does NOT
already contain that feature - see supports_hp() / supports_rdm() below.  The
dialog lets the user pick a curated complete name OR type any valid
G4PhysListFactory name.

Facts taken from "Guide For Physics Lists, Release 11.4" (FIRST__plg_dump.txt):
  - Factory base names: list in BASE_NAMES below.
  - EM suffix may be appended to any base name: EMV/EMX/EMY/EMZ (options 1-4),
    LIV, PEN, _GS, _LE, WVI, _SS.
  - The *_HP family already activates RadioactiveDecay (FTFP_BERT_HP,
    QGSP_BIC_HP, QGSP_BERT_HP ...). Shielding / ShieldingLEND also invoke it.

RunTask.physics keys: physics_list, add_hp, add_rdm, global_cut_mm, max_step_mm.
physics_list is now a free-text G4PhysListFactory name (default FTFP_BERT).
"""

# EM-suffix short description shown in hints / list rendering.
EM_SUFFIX = {
    "_EMV": "EM Opt1 (fast, lower precision)",
    "_EMX": "EM Opt2 (fast, lower precision)",
    "_EMY": "EM Opt3 (accurate, slower)",
    "_EMZ": "EM Opt4 (most accurate EM, slowest)",
    "_LIV": "Livermore EM (on Opt3 base)",
    "_PEN": "Penelope-2008 EM (on Opt3 base)",
}

# The whole Shielding family (Shielding / ShieldingLEND / ShieldingM and any of
# their EM-suffixed forms) already carries high-precision neutrons AND
# RadioactiveDecay, so AddHP / AddRDM must stay off for them.  Matched by
# prefix so "Shielding_EMY" is caught too.
_SHIELDING = "Shielding"

# Any *_HP / *_HPT reference list already decays activation products, so a
# second AddRDM registration is pointless (the solver only special-cases the
# exact base name "Shielding", but registering RDM twice is wrong anyway).
_HP_TOKENS = ("_HP", "_HPT", "HPT")

# Curated plain base names that the solver can safely turn into a *_HP name by
# appending the suffix.  Only these may use the AddHP toggle.  A name that ends
# with an EM suffix (e.g. FTFP_BERT_EMZ) cannot take "_HP" on the end - the
# EM suffix must sit at the very end (FTFP_BERT_HP_EMZ), so AddHP is not offered.
_ADD_HP_BASE = {"FTFP_BERT", "QGSP_BERT", "QGSP_BIC", "QGSP_FTFP_BERT",
                "QGSP_INCLXX", "FTF_BIC"}


# Curated, space-relevant COMPLETE reference-list names offered in the dropdown.
# Every entry is a full, directly usable G4PhysListFactory name.  Each item:
#   (name, one-line model set, extra note)
REFERENCE_LISTS = [
    # ---- general purpose (defaults / collider-grade hadron coverage) ----
    ("FTFP_BERT",
     "FTFP string + Bertini cascade (standard EM)",
     "rad4space default and best all-round list: Fritiof string model for the "
     "high-energy tail, Bertini cascade below ~10 GeV."),
    ("FTFP_BERT_EMZ",
     "FTFP_BERT + EM Opt4 (most accurate EM)",
     "Same hadronics as FTFP_BERT but with the best-of-low-energy+standard EM "
     "set. Slower than the default EM - pick when accurate low-energy "
     "electron/gamma tracking matters."),
    ("FTFP_BERT_HP",
     "FTFP_BERT + high-precision neutrons (<20 MeV)",
     "As FTFP_BERT but neutrons up to 20 MeV use ParticleHP (ENDF) tables; "
     "also activates radioactive decay. Needs the G4NDL data."),
    ("QGSP_BERT",
     "QGS string + Bertini cascade + precompound",
     "Former Geant4 default; QGS above ~20 GeV, BERT below. Matches many "
     "published Geant4 benchmarks."),
    ("QGSP_BERT_EMZ",
     "QGSP_BERT + EM Opt4 (most accurate EM)",
     "High-precision EM variant of QGSP_BERT, useful when both detailed EM and "
     "the classic QGS/BERT hadronic split are wanted."),
    ("QGSP_BERT_HP",
     "QGSP_BERT + high-precision neutrons",
     "HP-neutron variant of QGSP_BERT with radioactive decay activated. "
     "(Not recommended by Geant4 for general use; still under validation.)"),
    ("QGSP_BIC",
     "QGS string + Binary cascade (standard EM)",
     "BIC intra-nuclear transport below ~10 GeV; the EM default here is Opt4, "
     "preferred for proton / ion therapy and low-energy hadron studies."),
    ("QGSP_BIC_HP",
     "QGSP_BIC + HP neutrons + RDM (EM Opt4)",
     "Best single name for proton / neutron transport with accurate "
     "low-energy neutrons and activation decay: used for GCR / SEE work. "
     "Already includes HP and RadioactiveDecay - do not add them again."),
    ("QGSP_FTFP_BERT",
     "QGS + FTF forward region + Bertini cascade",
     "QGS in the central region, FTF for the forward / diffractive part, BERT "
     "at low energy."),
    ("QGSP_INCLXX",
     "QGS string + INCL++ cascade",
     "CEA INCL++ intra-nuclear cascade for p / n / light-ion spallation "
     "benchmarks."),
    ("FTF_BIC",
     "FTFP string + Binary cascade",
     "FTF at high energy plus the more detailed BIC at low energy."),
    ("QBBC",
     "Quark-gluon precompound + string models",
     "Recommended for medical AND space applications - accurate below 1 GeV "
     "for thin targets."),
    # ---- NASA shielding / deep-penetration neutron transport ----
    ("Shielding",
     "FTFP_BERT base + QMD ion frag + HP thermal neutrons + RDM",
     "Space-radiation list (NASA) for deep shielding and heavy-ion transport "
     "(H-Fe-U): high-precision thermal neutrons, fission and radioactive "
     "decay are all already included. No AddHP / AddRDM needed."),
    ("Shielding_EMY",
     "Shielding + EM Opt3 (accurate, slower)",
     "Shielding with the accurate Urban-multiple-scattering EM set. Good "
     "balanced choice for shielding dose / SEE studies. Already contains HP "
     "and RDM."),
    ("Shielding_EMZ",
     "Shielding + EM Opt4 (most accurate EM)",
     "Shielding with the best-of EM set. Slowest EM but maximises dose/fluence "
     "precision in thin regions."),
    ("Shielding_LIV",
     "Shielding + Livermore EM (on Opt3 base)",
     "Shielding whose gamma/e- transport uses Livermore models - handy for "
     "low-energy dose in materials."),
    ("ShieldingLEND",
     "Shielding with LEND low-energy neutron data",
     "Shielding whose thermal neutrons use ENDF-driven LEND models instead of "
     "the native ParticleHP tables."),
    ("ShieldingLEND_EMZ",
     "ShieldingLEND + EM Opt4",
     "LEND-neutron shielding with the highest-precision EM option."),
]

COVERAGE_TEXT = (
    "Particle types handled: gamma, e-/e+, mu, pi, K, proton, neutron "
    "(thermal-to-high with HP / Shielding), light ions d/t/alpha/He3 and "
    "heavy ions up to U (fragmentation detail depends on the list). The *_HP "
    "lists and Shielding additionally decay activation products via "
    "beta/alpha chains (RadioactiveDecay)."
)

# (range, unit text, decimal digits, hint) used by the dialog spin boxes
CUT = ("global_cut_mm", 0.0, 100.0, 4,
       "Production threshold for gamma / e- / e+ / proton - it sets how finely "
       "secondary delta-electrons and photons are generated. Ions are never "
       "cut directly; their energy-deposit detail is governed by the e- cut.")
STEP = ("max_step_mm", 0.0, 100000.0, 3,
        "Maximum step length applied to every volume (G4UserLimits, GRAS "
        "StepMax). 0 = no limit. A limit improves thin-layer energy-deposit "
        "accuracy and visibility of tracks. (Requires G4StepLimiterPhysics, "
        "which the solver registers automatically when a limit is set.)")


def default_config():
    return {"physics_list": "FTFP_BERT", "add_hp": False, "add_rdm": False,
            "global_cut_mm": 0.7, "max_step_mm": 0.0}


def sanitize(config):
    """Coerce to the dict schema. physics_list is free text (any valid
    G4PhysListFactory name), so unknown names are kept, not reset - the solver
    is the authority and will abort only on a truly invalid name."""
    cfg = default_config()
    if isinstance(config, dict):
        for k in cfg:
            if k in config and config[k] is not None:
                cfg[k] = config[k]
    name = str(cfg["physics_list"]).strip()
    cfg["physics_list"] = name if name else "FTFP_BERT"
    return cfg


def _is_shielding(name):
    """Shielding family: Shielding itself and every Shielding* / Shielding*_EM?
    variant already ships HP neutrons + RDM."""
    return name.startswith(_SHIELDING)


def _has_hp_suffix(name):
    return any(t in name for t in _HP_TOKENS)


def _has_rdm(name):
    """The list already decays activation products on its own: every Shielding
    family member and every *_HP / *_HPT reference list."""
    return _is_shielding(name) or _has_hp_suffix(name)


def supports_hp(name):
    """True if AddHP is meaningful.  AddHP appends '_HP' to the very end of the
    name, so it is only safe for a curated PLAIN base list (FTFP_BERT etc.).
    Names that already carry HP/HPT, belong to the Shielding family, or carry
    an EM suffix cannot take a trailing '_HP' (that would be an invalid name)."""
    return name in _ADD_HP_BASE


def supports_rdm(name):
    """True if AddRDM is meaningful.  Registering G4RadioactiveDecayPhysics is
    safe for any non-Shielding list that does not already decay products (the
    Shielding family and every *_HP list do by themselves)."""
    return not _has_rdm(name)


def info(name):
    """(model-set text, note) for a curated name, or a generic fallback for a
    free-typed valid-but-unknown G4PhysListFactory name."""
    for key, models, note in REFERENCE_LISTS:
        if key == name:
            return models, note
    return "Custom G4PhysListFactory reference list", \
        "Not in the curated list. Any valid Geant4 reference name is accepted, " \
        "e.g. a base list with a different EM suffix (EMV/EMX/EMY/EMZ/LIV/PEN)."


def warnings(name, add_hp, add_rdm):
    """Human-readable issues (red text) for the dialog, in macro order.

    Returns a list of strings. Each corresponds to a parameter that will be
    silently dropped or that is meaningless given the chosen reference list.
    """
    name = (name or "").strip()
    out = []
    if add_hp and not supports_hp(name):
        if _is_shielding(name) or _has_hp_suffix(name):
            out.append(f"AddHP is dropped: <b>{name}</b> already contains "
                       "high-precision neutron models (the Shielding family, or "
                       "an '_HP'/'HPT' suffix). Adding another '_HP' would make "
                       "an invalid list name.")
        else:
            out.append(f"AddHP is dropped: <b>{name}</b> is not a plain base "
                       "list, so the solver cannot append '_HP' to it (an EM "
                       "suffix must stay at the end, e.g. choose "
                       "FTFP_BERT_HP_EMZ instead).")
    if add_rdm and not supports_rdm(name):
        out.append(f"AddRDM is dropped: <b>{name}</b> already activates "
                   "RadioactiveDecay (the Shielding family and every *_HP list "
                   "decay activation products by themselves).")
    return out


def line_summary(name):
    """Two short lines kept on-screen next to the list combo: the model set
    (e.g. "FTFP string + Bertini cascade") plus the curated note.  The longer
    particle-coverage explanation is moved to the combo's hover tooltip."""
    models, note = info(name)
    return f"{name}: {models}\n\n{note}"


def hover_text(name):
    """Full description used as the combo-box tooltip (hover): model set,
    particle coverage and the curated note.  Also lists the reachable EM
    suffixes for typed names."""
    models, note = info(name)
    return (f"{name}\n{models}\n\n{COVERAGE_TEXT}\n\nNote: {note}")


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
    ins = 1
    if c["add_hp"] and not supports_hp(c["physics_list"]):
        lines.insert(ins, "# (AddHP skipped: the list already has HP neutrons)")
        ins += 1
    if c["add_rdm"] and not supports_rdm(c["physics_list"]):
        lines.insert(ins, "# (AddRDM skipped: the list already decays products)")
    return "\n".join(head + lines)
