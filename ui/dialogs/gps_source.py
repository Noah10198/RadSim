"""gps_source - pure GPS (G4GeneralParticleSource) data model + macro builder.

No Qt dependency: reused by particle_dialog.py and later by the run pipeline.
Units fixed in GUI: length mm -> macro cm (/10); energy MeV; angle deg.
Command set follows manual §2.7 (Book For Application Developers 11.4) and the
rad4space solver examples (R4PrimaryGeneratorAction uses a standard GPS).
"""
# Usage: cfg = DEFAULT_CONFIG(); lines = build_macro(cfg)

import math

PARTICLES = ["gamma", "e-", "e+", "proton", "neutron", "alpha",
             "deuteron", "triton", "He3", "mu-", "mu+", "pi-", "pi+",
             "anti_proton"]

ENERGY_TYPES = [("Mono", "Mono"), ("Lin", "Linear (Lin)"),
                ("Gauss", "Gaussian (Gauss)"), ("Pow", "Power-law (Pow)"),
                ("Exp", "Exponential (Exp)"),
                ("User", "User spectrum (import)")]

POS_TYPES = [("Point", "Point"), ("Plane", "Plane"),
             ("Surface", "Surface")]
# Shape set per position type offered in the source form: a Plane source is
# modelled as a Rectangle and a Surface source as a sphere shell.  Macro
# building / old saved configs intentionally keep working on wider string
# values (Volume, Ellipsoid, Para, ...) because those code paths read the
# stored keys directly - they are needed to render and keep older tasks.
POS_SHAPES = {"Plane": ["Rectangle"], "Surface": ["Sphere"]}
# rot1 (x') + rot2 (y', in plane) orient the source-shape / angular axes;
# unitless vectors, not necessarily unit; default pair means "no rotation"
# (manual Table 2.4/2.5).  Stored as {"x","y","z"} dicts under position/angular.
ROT_AXES = (("rot1", (1.0, 0.0, 0.0)), ("rot2", (0.0, 1.0, 0.0)))

# Offered angular types in the source form. planar / beam1d / beam2d /
# focused are deliberately NOT offered: they have no effect on the
# spatial-radiation picture this app computes, and omitting them keeps the
# coordinate transforms that matter (iso / cos) unambiguous. Macro building /
# old saved configs still keep working on the wider string set (ANG_FIELDS,
# _CMD below) because those code paths read the stored keys directly.
ANG_TYPES = [("iso", "Isotropic (iso)"), ("cos", "Cosine (cos)")]

# field = (key, label, unit); unit in mm/MeV/deg/K/""(unitless)
ENERGY_FIELDS = {
    "Mono": [("e_mono", "Energy E", "MeV")],
    "Lin": [("e_min", "E min", "MeV"), ("e_max", "E max", "MeV"),
            ("gradient", "Slope", ""), ("intercept", "Intercept", "")],
    "Gauss": [("e_mono", "Mean E", "MeV"), ("e_sigma", "StdDev σ", "MeV")],
    "Pow": [("e_min", "E min", "MeV"), ("e_max", "E max", "MeV"),
            ("alpha", "Spectral index α", "")],
    "Exp": [("e_min", "E min", "MeV"), ("e_max", "E max", "MeV"),
            ("ezero", "Scale E0", "MeV")],
    "User": [],    # data lives in cfg.energy.data = [[E(MeV), weight], ...]
}
SHAPE_FIELDS = {
    "Circle": [("radius", "Radius", "mm")],
    "Annulus": [("inner_radius", "Inner radius", "mm"),
                ("radius", "Outer radius", "mm")],
    "Ellipse": [("halfx", "Half-width x", "mm"), ("halfy", "Half-height y", "mm")],
    "Square": [("halfx", "Half-width x", "mm"), ("halfy", "Half-height y", "mm")],
    "Rectangle": [("halfx", "Half-width x", "mm"),
                  ("halfy", "Half-height y", "mm")],
    "Sphere": [("radius", "Radius", "mm")],
    "Ellipsoid": [("halfx", "Half-width x", "mm"),
                  ("halfy", "Half-height y", "mm"),
                  ("halfz", "Half-depth z", "mm")],
    "Cylinder": [("radius", "Radius", "mm"), ("halfz", "Half-height z", "mm")],
    "Para": [("halfx", "Half-width x", "mm"), ("halfy", "Half-height y", "mm"),
             ("halfz", "Half-depth z", "mm"), ("palpha", "α", "deg"),
             ("ptheta", "θ", "deg"), ("pphi", "φ", "deg")],
}
POS_XYZ = [("cx", "x", "mm"), ("cy", "y", "mm"), ("cz", "z", "mm")]
SHAPE_LABEL = {"Circle": "Circle", "Annulus": "Annulus",
               "Ellipse": "Ellipse", "Square": "Square",
               "Rectangle": "Rectangle", "Sphere": "Sphere",
               "Ellipsoid": "Ellipsoid", "Cylinder": "Cylinder",
               "Para": "Para"}
ANG_FIELDS = {
    "iso": [("theta_min", "θ min", "deg"), ("theta_max", "θ max", "deg"),
            ("phi_min", "φ min", "deg"), ("phi_max", "φ max", "deg")],
    "cos": [], "planar": [],
    "beam1d": [("sigma_r", "Radial σr", "deg")],
    "beam2d": [("sigma_x", "σ x", "deg"), ("sigma_y", "σ y", "deg")],
    "focused": [("fx", "Focus x", "mm"), ("fy", "Focus y", "mm"),
                ("fz", "Focus z", "mm")],
}

# key -> (macro command prefix, unit-suffix token or "")
_CMD = {
    # energy
    "e_mono": ("/gps/ene/mono", "MeV"), "e_min": ("/gps/ene/min", "MeV"),
    "e_max": ("/gps/ene/max", "MeV"), "e_sigma": ("/gps/ene/sigma", "MeV"),
    "ezero": ("/gps/ene/ezero", ""),     "gradient": ("/gps/ene/gradient", ""),
    "intercept": ("/gps/ene/intercept", ""), "alpha": ("/gps/ene/alpha", ""),
    # position shape
    "halfx": ("/gps/pos/halfx", "cm"), "halfy": ("/gps/pos/halfy", "cm"),
    "halfz": ("/gps/pos/halfz", "cm"), "radius": ("/gps/pos/radius", "cm"),
    "inner_radius": ("/gps/pos/inner_radius", "cm"),
    "palpha": ("/gps/pos/paralp", "deg"), "ptheta": ("/gps/pos/parthe", "deg"),
    "pphi": ("/gps/pos/parphi", "deg"),
    # angular
    "theta_min": ("/gps/ang/mintheta", "deg"),
    "theta_max": ("/gps/ang/maxtheta", "deg"),
    "phi_min": ("/gps/ang/minphi", "deg"),
    "phi_max": ("/gps/ang/maxphi", "deg"),
    "sigma_r": ("/gps/ang/sigma_r", "deg"),
    "sigma_x": ("/gps/ang/sigma_x", "deg"),
    "sigma_y": ("/gps/ang/sigma_y", "deg"),
}


def default_gun_config():
    """G4ParticleGun (driven through the /gps UI commands): one mono-energetic
    particle from a point, emitted along a fixed direction."""
    return {
        "particle": {"kind": "standard", "name": "gamma"},
        "energy": 10.0,                                  # MeV  (/gps/energy)
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},      # mm   (/gps/position)
        "direction": {"x": 0.0, "y": 0.0, "z": 1.0},     #      (/gps/direction)
    }


def default_config():
    """Defaults for a freshly opened GPS page (GUI-internal unit mm): gamma,
    Lin 2-10 MeV, angular cos (per manual 2.7.4 test2.g4mac), while the source
    position defaults to a spherical surface shell (Surface + Sphere) as
    chosen for this app. mode "gun" is the dialog default until a mode click."""
    return {
        "unit": "mm",
        "mode": "gun",
        "gun": default_gun_config(),
        "particle": {"kind": "standard", "name": "gamma"},
        "number": 1,
        "energy": {"type": "Lin", "e_min": 2.0, "e_max": 10.0,
                   "gradient": 1.0, "intercept": 1.0},
        "position": {"type": "Surface", "shape": "Sphere",
                     "cx": 10.0, "cy": 20.0, "cz": 10.0,
                     "radius": 10.0},
        "angular": {"type": "cos"},
    }


def _f(v):
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "0"


def _append_rotation_lines(out, sub, prefix):
    """Emit /gps/<pos|ang>/rot1|rot2 lines for a stored rotation.
    sub is the position/angular config subset; vectors are {'x','y','z'} dicts.
    Identity vectors are never stored by the GUI, so presence means a rotation."""
    for tag, default in ROT_AXES:
        v = sub.get(tag)
        if not isinstance(v, dict):
            continue
        try:
            vals = (float(v.get("x", 0)), float(v.get("y", 0)),
                    float(v.get("z", 0)))
        except (TypeError, ValueError):
            continue
        if vals == default:      # identity = "no rotation", never written
            continue
        out.append(f"{prefix}/{tag} {_f(vals[0])} {_f(vals[1])} "
                   f"{_f(vals[2])}")


def build_gun_macro(cfg) -> list:
    """ParticleGun-mode macro: the /gps commands the simple source needs
    (/gps/particle, /gps/ion, /gps/energy, /gps/position, /gps/direction).
    mm -> cm conversion matches build_macro."""
    g = cfg.get("gun") or default_gun_config()
    out = []
    p = g.get("particle", {})
    if p.get("kind") == "ion":
        out.append("/gps/particle ion")
        out.append(f"/gps/ion {_f(p.get('z', 26))} {_f(p.get('a', 56))} "
                   f"{_f(p.get('q', 0))} {_f(p.get('e', 0))}")
    else:
        out.append(f"/gps/particle {p.get('name', 'gamma')}")
    out.append(f"/gps/energy {_f(g.get('energy', 10.0))} MeV")
    ps = g.get("position", {})
    out.append(f"/gps/position {_f(ps.get('x', 0) / 10)} "
               f"{_f(ps.get('y', 0) / 10)} {_f(ps.get('z', 0) / 10)} cm")
    d = g.get("direction", {})
    out.append(f"/gps/direction {_f(d.get('x', 0))} {_f(d.get('y', 0))} "
               f"{_f(d.get('z', 1))}")
    return out


def macro_lines(cfg) -> list:
    """Dispatch by mode:
      * 'gun'  -> build_gun_macro (simple mono /gps commands)
      * 'file' -> the user-imported raw macro text, returned verbatim
                  (lines are neither parsed nor filtered; cfg.raw holds it)
      * else   -> the full GPS macro (configs saved before "mode" existed
                  are plain GPS configs and fall in here)
    """
    mode = cfg.get("mode", "gps")
    if mode == "gun":
        return build_gun_macro(cfg)
    if mode == "file":
        raw = cfg.get("raw") or ""
        return raw.splitlines()
    return build_macro(cfg)


def build_macro(cfg) -> list:
    """Build the GPS macro lines (without /run/beamOn). Direction semantics
    follow the manual: no auto flip."""
    out = []
    # 1. Particle
    p = cfg.get("particle", {})
    if p.get("kind") == "ion":
        out.append("/gps/particle ion")
        out.append(f"/gps/ion {_f(p.get('z', 26))} {_f(p.get('a', 56))} "
                   f"{_f(p.get('q', 0))} {_f(p.get('e', 0))}")
    else:
        out.append(f"/gps/particle {p.get('name', 'gamma')}")
    out.append(f"/gps/number {_f(cfg.get('number', 1))}")

    # 2. Energy spectrum
    en = cfg.get("energy", {})
    etype = en.get("type", "Lin")
    out.append(f"/gps/ene/type {etype}")
    # GPS 的 Lin 分布是定义在 [E_min, E_max] 区间上的线性 p.d.f
    # f(E)=gradient*E+intercept。四个参数都要显式写出：E 上下限缺失时源
    # 只会在默认(约 0)能段上分布，gradient/intercept 双零时分布恒为零，
    # 两种情况都会让源静默不发粒子，导致所有记分恒 0。
    # 缺省回退与默认配置一致：E 上下限 2–10 MeV、gradient/intercept (1,1)。
    if etype == "Lin":
        lo = float(en.get("e_min", 0.0) or 0.0)
        hi = float(en.get("e_max", 0.0) or 0.0)
        if not (0 < lo < hi):
            lo, hi = 2.0, 10.0
        out.append(f"/gps/ene/min {_f(lo)} MeV")
        out.append(f"/gps/ene/max {_f(hi)} MeV")
        g = en.get("gradient", 0.0) or 0.0
        i = en.get("intercept", 0.0) or 0.0
        if not g and not i:
            g, i = 1.0, 1.0
        out.append(f"/gps/ene/gradient {_f(g)}")
        out.append(f"/gps/ene/intercept {_f(i)}")
    else:
        for key, _lbl, _u in ENERGY_FIELDS.get(etype, []):
            if key in en:
                pre, suf = _CMD[key]
                out.append(f"{pre} {_f(en[key])}" + (f" {suf}" if suf else ""))
    if etype == "User":
        d = en.get("data") or []
        if d:
            es = [x[0] for x in d]
            out.append(
                f"# user spectrum, {len(d)} points "
                f"(E {_f(min(es))}-{_f(max(es))} MeV); the /gps/histogram "
                "lines are appended at run stage once the solver is checked")

    # 3. Source position
    ps = cfg.get("position", {})
    ptype = ps.get("type", "Point")
    out.append(f"/gps/pos/type {ptype}")
    shape = ps.get("shape", "")
    if ptype != "Point":
        out.append(f"/gps/pos/shape {shape}")
    out.append(f"/gps/pos/centre {_f(ps.get('cx', 0) / 10)} "
               f"{_f(ps.get('cy', 0) / 10)} {_f(ps.get('cz', 0) / 10)} cm")
    for key, _lbl, _u in SHAPE_FIELDS.get(shape, []):
        if key in ps:
            pre, suf = _CMD[key]
            v = ps[key] / 10 if suf == "cm" else ps[key]
            out.append(f"{pre} {_f(v)}" + (f" {suf}" if suf else ""))
    # rot axes tilt the source shape. A Point has no shape and a Surface
    # sphere is orientation-blind (uniform shell), so only Plane -- and legacy
    # non-spherical Surface shapes -- carry /gps/pos/rot lines.
    if ptype == "Plane" or (ptype == "Surface" and shape != "Sphere"):
        _append_rotation_lines(out, ps, "/gps/pos")

    # 4. Angular distribution
    an = cfg.get("angular", {})
    atype = an.get("type", "iso")
    out.append(f"/gps/ang/type {atype}")
    if atype == "focused":
        out.append(f"/gps/ang/focuspoint {_f(an.get('fx', 0) / 10)} "
                   f"{_f(an.get('fy', 0) / 10)} {_f(an.get('fz', 0) / 10)} cm")
    else:
        for key, _lbl, _u in ANG_FIELDS.get(atype, []):
            if key in an:
                pre, suf = _CMD[key]
                out.append(f"{pre} {_f(an[key])}" + (f" {suf}" if suf else ""))
    _append_rotation_lines(out, an, "/gps/ang")
    return out


# ---------- Short chip summaries (shown in the section headers) ----------

def gun_summary(cfg) -> str:
    g = cfg.get("gun") or {}
    p = g.get("particle", {})
    if p.get("kind") == "ion":
        pt = f"ion {p.get('z', 26)}/{p.get('a', 56)}"
    else:
        pt = p.get("name", "gamma")
    ps = g.get("position", {})
    d = g.get("direction", {})
    return (f"{pt}  {_f(g.get('energy', 10))} MeV  "
            f"@({_f(ps.get('x', 0))},{_f(ps.get('y', 0))},"
            f"{_f(ps.get('z', 0))})mm  "
            f"dir({_f(d.get('x', 0))},{_f(d.get('y', 0))},"
            f"{_f(d.get('z', 1))})")


def particle_summary(cfg) -> str:
    p = cfg.get("particle", {})
    if p.get("kind") == "ion":
        return f"ion {p.get('z', 26)}/{p.get('a', 56)}"
    return p.get("name", "gamma")


def energy_summary(cfg) -> str:
    en = cfg.get("energy", {})
    t = en.get("type", "Lin")
    if t == "Mono":
        return f"Mono {_f(en.get('e_mono', 1))} MeV"
    if t in ("Lin", "Gauss", "Pow"):
        mn = en.get("e_min", en.get("e_mono", 0))
        mx = en.get("e_max", en.get("e_mono", 0))
        return f"{t} {_f(mn)}–{_f(mx)} MeV"
    if t == "Exp":
        mn = en.get("e_min")
        mx = en.get("e_max")
        s = f"Exp E0={_f(en.get('ezero', 1))}"
        if mn is not None and mx is not None:
            s += f", {_f(mn)}–{_f(mx)} MeV"
        return s
    if t == "User":
        d = en.get("data") or []
        if not d:
            return "User (not loaded)"
        es = [x[0] for x in d]
        return f"User {len(d)}pt {_f(min(es))}-{_f(max(es))} MeV"
    return t


def position_summary(cfg) -> str:
    ps = cfg.get("position", {})
    t, shape = ps.get("type", "Point"), ps.get("shape", "")
    s = t
    if shape:
        s += "·" + SHAPE_LABEL.get(shape, shape)
    if t != "Point":
        hx = ps.get("halfx")
        hy = ps.get("halfy")
        r = ps.get("radius")
        if hx and hy:
            s += f" {_f(hx * 2)}×{_f(hy * 2)}mm"
        elif r:
            s += f" r={_f(r)}mm"
        elif ps.get("halfz"):
            hz = ps.get("halfz")
            s += f" {_f((hx or r or 0) * 2)}×{_f(hz * 2)}mm"
    if any(k in ps for k in ("cx", "cy", "cz")):
        s += f" @({_f(ps.get('cx', 0))},{_f(ps.get('cy', 0))},{_f(ps.get('cz', 0))})mm"
    return s


def angular_summary(cfg) -> str:
    an = cfg.get("angular", {})
    t = an.get("type", "iso")
    if t == "beam1d":
        return f"beam1d σ={_f(an.get('sigma_r', 0))}°"
    if t == "beam2d":
        return f"beam2d σx={_f(an.get('sigma_x', 0))}°"
    return t


# ---------- User spectrum data ----------

def parse_spectrum_text(text: str, max_points: int = 512):
    """Parse a user spectrum text into [[E(MeV), weight], ...] sorted by E
    with duplicate energies merged.

    One pair per line: E(MeV) weight; text after '#' is a comment; spaces,
    tabs and commas are all accepted separators. When the data is larger than
    max_points it is re-binned on an even E grid.
    """
    pts = []
    for raw in text.splitlines():
        line = (raw.split("#", 1)[0] if "#" in raw else raw).strip()
        if not line:
            continue
        parts = line.replace(",", " ").replace("\t", " ").split()
        if len(parts) < 2:
            continue
        try:
            e = float(parts[0])
            w = float(parts[1])
        except ValueError:
            continue
        if e > 0 and w >= 0:
            pts.append([e, w])
    if not pts:
        return []
    pts.sort(key=lambda z: z[0])
    out = []
    for e, w in pts:
        if out and abs(out[-1][0] - e) < 1e-9 * max(1.0, abs(e)):
            out[-1][1] += w
        else:
            out.append([e, w])
    if len(out) <= max_points:
        return out
    return _rebin(out, max_points)


def _rebin(pts, n: int):
    """Split monotone (E, w) points into n equal E-bins; each bin keeps its
    mid E and the summed weight."""
    lo, hi = pts[0][0], pts[-1][0]
    if hi <= lo:
        return pts[:n]
    buckets = [[] for _ in range(n)]
    for e, w in pts:
        i = min(n - 1, int((e - lo) / (hi - lo) * n))
        buckets[i].append((e, w))
    res = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        e0 = lo + (hi - lo) * (i + 0.5) / n
        res.append([round(e0, 6), round(sum(w for _e, w in b), 6)])
    return res or pts[:1]


def example_user_spectrum():
    """Example user spectrum: exponential background + a characteristic peak
    (only used to demo import/plotting)."""
    pts = []
    for i in range(64):
        e = 0.05 + (i + 0.5) * 0.18      # 0.05 ~ 11.6 MeV
        peak = 2.4 * math.exp(-((e - 1.2) / 0.09) ** 2)
        bg = 1.1 * math.exp(-e / 2.6)
        pts.append([round(e, 4), round(bg + peak, 4)])
    return pts
