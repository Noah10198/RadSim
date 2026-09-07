"""Chart-based probe result reading + grouping (no Qt/matplotlib imports,
so project-tree building stays light).

rad4space writes per probe P: ONE out_P.csv with every quantity's integrated
value (each in its own "# primitive scorer name" block), plus one
rad4space_h1_P_qx.csv per configured 1-D histogram. A quantity only means
something compared across probes, therefore values/histograms are grouped by
physical quantity TYPE (from the saved probe config - never by the arbitrary
per-probe q-name), e.g. the doseDeposit of P1/P2/P3 share one group.

Groups are pure data; plotting happens in probe_chart_dialog.py.
"""

import os

# ----------------------------------------------------------------------
# file parsing
# ----------------------------------------------------------------------


def parse_out_csv(path):
    """out_<mesh>.csv -> {"mesh", "blocks":[{"name","unit","value","entry"}]}

    Block format:
        # primitive scorer name: q1
        # i, i, i, total(value) [MeV], total(val^2), entry
        0,0,0,<total>,<val2>,<entry>
    Unit is read back from the column legend ("[MeV]") rather than the config
    so a file from an edited config still labels itself."""
    out = {"mesh": "", "blocks": []}
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        cur = None
        for line in fh:
            if line.startswith("#"):
                body = line[1:].strip()
                if body.startswith("mesh name:"):
                    out["mesh"] = body.split(":", 1)[1].strip()
                elif body.startswith("primitive scorer name:"):
                    cur = {"name": body.split(":", 1)[1].strip(),
                           "unit": "", "value": None, "entry": 0}
                    out["blocks"].append(cur)
                elif cur is not None and "total(value)" in body:
                    cur["unit"] = body.partition("[")[2].partition("]")[0]\
                        .strip() if "[" in body else ""
                continue
            if cur is not None and line.strip():
                cells = [c.strip() for c in line.split(",")]
                if len(cells) >= 4:
                    try:
                        cur["value"] = float(cells[3])
                        if len(cells) >= 6:
                            cur["entry"] = float(cells[5])
                    except ValueError:
                        pass
                cur = None  # one data row closes the block
    out["blocks"] = [b for b in out["blocks"]
                     if b["value"] is not None and b["name"]]
    return out


def parse_h1_csv(path):
    """rad4space_h1_<mesh>_<q>.csv (tools::histo h1d text dump) -> dict or
    None.

        #axis fixed <nbins> <xmin> <xmax>   (or '#axis log ...')
        #bin_number <nbins+2>
        entries,Sw,Sw2,Sxw0,Sx2w0
        <underflow>
        <bin rows...>
        <overflow>

    Returns {nbins, lo, hi, log, edges, centers, counts, total, underflow,
    overflow, title}. Edges are linear for 'fixed' and logarithmic for 'log'.
    """
    header = {}
    counts = []
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    with fh:
        in_data = False
        for line in fh:
            if line.startswith("#"):
                body = line[1:].strip()
                if body.startswith("axis "):
                    kind, _, rest = body[5:].strip().partition(" ")
                    toks = rest.split()
                    if len(toks) >= 3:
                        header["axis"] = kind
                        header["nbins"] = int(toks[0])
                        header["lo"] = float(toks[1])
                        header["hi"] = float(toks[2])
                elif body.startswith("title "):
                    header["title"] = body.split(" ", 1)[1].strip()
                continue
            if not in_data:
                in_data = line.strip().lower().startswith("entries")
                continue
            first = line.split(",")[0].strip()
            if first:
                try:
                    counts.append(float(first))
                except ValueError:
                    pass
    nbins = header.get("nbins")
    lo, hi = header.get("lo", 0.0), header.get("hi", 1.0)
    if not nbins or nbins <= 0 or hi <= lo:
        return None
    log = header.get("axis", "fixed") == "log"
    if len(counts) == nbins + 2:  # underflow + bins + overflow
        underflow, overflow = counts[0], counts[-1]
        counts = counts[1:1 + nbins]
    else:
        underflow, overflow = None, None
        counts = (counts + [0.0] * nbins)[:nbins]
    if log:
        import math

        llo, lhi = math.log10(lo), math.log10(hi)
        edges = [10.0 ** (llo + (lhi - llo) * i / nbins)
                 for i in range(nbins + 1)]
    else:
        w = (hi - lo) / nbins
        edges = [lo + w * i for i in range(nbins + 1)]
    centers = [(edges[i] + edges[i + 1]) * 0.5 for i in range(nbins)]
    return {"nbins": nbins, "lo": lo, "hi": hi, "log": log,
            "edges": edges, "centers": centers,
            "counts": counts, "total": sum(counts),
            "underflow": underflow, "overflow": overflow,
            "title": header.get("title", os.path.basename(path))}


def rebin_log(hist):
    """Recompute a histogram's edges/centers on a log10 axis. Some rad4space
    builds write '#axis fixed' even for log-binned histograms, so when the
    saved probe config asked for a log histogram the edges must be rebuilt
    from the same lo/hi/nbins range, otherwise the dump would be drawn on a
    misleading linear axis."""
    import math

    lo, hi, n = hist["lo"], hist["hi"], hist["nbins"]
    llo, lhi = math.log10(lo), math.log10(hi)
    edges = [10.0 ** (llo + (lhi - llo) * i / n) for i in range(n + 1)]
    centers = [(edges[i] + edges[i + 1]) * 0.5 for i in range(n)]
    return {**hist, "log": True, "edges": edges, "centers": centers}


# ----------------------------------------------------------------------
# cross-probe grouping by quantity type
# ----------------------------------------------------------------------

def _type_unit_label(qtype, unit):
    return f"{qtype} [{unit}]" if unit else qtype


def build_probe_result_groups(probes, work_dir):
    """Group the probe outputs of one finished run by physical quantity type.

    probes   : saved probe config list (task.analysis_config["probe"]).
    work_dir : task run directory (out_*.csv, rad4space_h1_*.csv dumps).

    Returns {"quantity": [group...], "histogram": [group...]} with each group
    {"kind", "label", "series": [...]}:
      quantity series : {probe, qname, unit, value, entry}
      histogram series: {probe, qname, xunit, hist, cfg}
    Missing/unparsable files drop their series; empty groups are removed.
    """
    from ui.dialogs.analysis_common import quantity_meta

    qgroups, hgroups = {}, {}

    def _add(groups, qtype, unit, series):
        grp = groups.setdefault(
            qtype, {"kind": "", "label": _type_unit_label(qtype, unit),
                    "series": []})
        grp["series"].append(series)

    for p in probes or []:
        pname = str(p.get("name") or "").strip()
        if not pname:
            continue
        qmeta = {str(q.get("name") or ""): q for q in (p.get("qs") or [])}

        # ---- integrated values: out_<probe>.csv ----
        out_path = os.path.join(work_dir, f"out_{pname}.csv")
        blocks = parse_out_csv(out_path)["blocks"] if os.path.isfile(
            out_path) else []
        for b in blocks:
            q = qmeta.get(b["name"])
            if q is None:
                continue
            _add(qgroups, str(q.get("type") or "energyDeposit"), b["unit"],
                 {"probe": pname, "qname": b["name"], "unit": b["unit"],
                  "value": b["value"], "entry": b["entry"]})

        # ---- 1-D histograms: rad4space_h1_<probe>_<q>.csv ----
        for h in (p.get("hs") or []):
            qname = str(h.get("q") or "")
            q = qmeta.get(qname)
            if q is None:
                continue
            qtype = str(q.get("type") or "energyDeposit")
            xunit = quantity_meta(qtype)[1]
            if not xunit:
                continue
            hpath = os.path.join(work_dir, f"rad4space_h1_{pname}_{qname}.csv")
            hist = parse_h1_csv(hpath) if os.path.isfile(hpath) else None
            if hist is None:
                continue
            if h.get("log") and not hist["log"]:
                hist = rebin_log(hist)
            _add(hgroups, qtype, xunit,
                 {"probe": pname, "qname": qname, "xunit": xunit,
                  "hist": hist, "cfg": dict(h)})

    def _finalise(groups, kind):
        for g in groups.values():
            g["kind"] = kind
        return sorted(groups.values(), key=lambda g: g["label"])

    return {"quantity": _finalise(qgroups, "quantity"),
            "histogram": _finalise(hgroups, "histogram")}


def find_group(groups, kind, label):
    """The group whose label matches (used when a tree leaf is clicked)."""
    for g in groups.get(kind, []):
        if g["label"] == label:
            return g
    return None
