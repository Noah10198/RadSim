"""
Parse a Geant4 tools::histo::h1d CSV dump (the one written by
/analysis/h1 + /score/fill1D) and print / plot the normalized
differential spectrum.

    #axis fixed 10 0 10        -> 10 bins over [0,10] MeV
    #bin_number 12             -> 10 bins + underflow + overflow
    entries,Sw,Sw2,Sxw0,Sx2w0  -> weighted cumulants per bin

Per bin:
    P_i  = entries / N                        probability
    p(E) = entries / (N * dE)  [1/MeV]        differential density dN/dE
    dp   = sqrt(entries)/(N*dE)               Poisson error

Usage:
    python plot_h1_spectrum.py <file.csv> [--noplot]
"""
import sys
import numpy as np


def load_h1_csv(path):
    nbins = xmin = xmax = None
    rows = []
    in_data = False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#axis"):
                p = line.split()
                nbins, xmin, xmax = int(p[2]), float(p[3]), float(p[4])
            elif line.startswith("entries"):
                in_data = True
                continue
            elif in_data:
                vals = line.split(",")
                if len(vals) < 5:
                    continue
                rows.append([float(v) for v in vals[:5]])
    rows = np.array(rows)  # (nbins+2, 5): underflow + nbins + overflow
    assert nbins and len(rows) == nbins + 2, \
        f"expected {nbins}+2 data rows, got {len(rows)}"
    entries = rows[1:-1, 0].astype(np.int64)  # drop under/overflow
    sw  = rows[1:-1, 1]
    sxw = rows[1:-1, 3]
    return nbins, xmin, xmax, entries, sw, sxw


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "volFlux_100k.csv"
    noplot = "--noplot" in sys.argv

    nbins, xmin, xmax, entries, sw, sxw = load_h1_csv(path)

    dE = (xmax - xmin) / nbins
    E  = xmin + (np.arange(nbins) + 0.5) * dE   # bin centers
    N  = int(entries.sum())

    P  = entries / N
    p  = entries / (N * dE)                    # dN/dE [1/MeV]
    dp = np.sqrt(entries) / (N * dE)
    avg = np.zeros_like(sw)
    np.divide(sxw, sw, out=avg, where=sw > 0)  # true mean inside the bin

    print(f"file           : {path}")
    print(f"axis           : {nbins} bins  [{xmin}, {xmax}] MeV   dE = {dE} MeV")
    print(f"total entries  : {N}")
    print(f"checks         : sum(P) = {P.sum():.6f}   sum(p)*dE = {(p*dE).sum():.6f}")
    print()
    hdr = (f"{'bin':>3} {'E range [MeV]':>15} {'E_cent':>7} {'entries':>8} "
           f"{'<E> [MeV]':>9} {'P_i':>9} {'p(E)=dN/dE':>12} {'dp':>10}")
    print(hdr)
    print("-" * len(hdr))
    for i in range(nbins):
        lo = xmin + i * dE
        hi = lo + dE
        print(f"{i+1:>3} {lo:6.2f}-{hi:<6.2f} {E[i]:7.3f} {entries[i]:8d} "
              f"{avg[i]:9.3f} {P[i]:9.5f} {p[i]:12.5f} {dp[i]:10.5f}")

    if not noplot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
            ax1.bar(E, entries, width=0.85 * dE, align="center",
                    color="#4C72B0", alpha=0.85)
            ax1.set_xlabel("E [MeV]")
            ax1.set_ylabel("counts per bin")
            ax1.set_title("Raw bin counts")
            ax2.errorbar(E, p, yerr=dp, fmt="o-", capsize=3, color="#C44E52",
                         label=f"N={N}")
            ax2.set_xlabel("E [MeV]")
            ax2.set_ylabel("p(E) = dN/dE  [1/MeV]")
            ax2.set_title("Normalized differential spectrum")
            ax2.grid(alpha=0.3)
            ax2.legend()
            fig.tight_layout()
            out = path.rsplit(".", 1)[0] + "_spectrum.png"
            fig.savefig(out, dpi=150)
            print(f"\nfigure saved   : {out}")
        except ImportError:
            print("\n[matplotlib not installed - table only]")


if __name__ == "__main__":
    main()
