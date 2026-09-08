"""ProbeResultChartDialog - one matplotlib comparison chart per result group
(probe probes and realworld logical volumes share the same dialog).

* quantity group : bar per (entity, quantity) of the same physical type, so
  e.g. the doseDeposit measured by several entities sit side by side.
* histogram group: one step curve per entity histogram of the same type on a
  single axis, with optional per-entity normalisation.

The group payload comes from probe_result_viewer.build_result_groups. The
dialog itself is entity-agnostic - entity_label only words the axis title and
the default export file name. If matplotlib is missing it shows an install
hint.
"""

try:
    import matplotlib

    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    _MPL = True
except Exception:  # pragma: no cover - depends on user's site-packages
    _MPL = False
    Figure = FigureCanvasQTAgg = None

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

_DARK_BG, _DARK_FG, _LIGHT_BG, _LIGHT_FG = (
    "#11111b", "#cdd6f4", "#ffffff", "#2c2c2c")
_CYCLE = ["#4c8df0", "#e07050", "#43a95f", "#d6b12b", "#b05cc7",
          "#2ea8c7", "#e06ac7", "#8a9bb5"]


def _fmt(v) -> str:
    try:
        if v == 0 or 1e-4 <= abs(v) < 1e6:
            return f"{v:.6g}"
        return f"{v:.3e}"
    except Exception:
        return str(v)


class ProbeResultChartDialog(QDialog):
    """One comparison chart for one probe result group."""

    def __init__(self, title, group, dark=False, parent=None,
                 entity_label="probe"):
        super().__init__(parent)
        self._group = group
        self._dark = bool(dark)
        self._entity_label = entity_label
        self._series = group.get("series") or []
        self.setWindowTitle(title)
        if self._group.get("kind") == "quantity":
            # wider canvas once there are many bars so they never get
            # squeezed (width grows with the probe count, capped on screen)
            n = len(self._series)
            wide = min(1560, max(560, 440 + n * 72))
            self.resize(int(wide), 660)
        else:
            self.resize(1040, 700)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui()
        if _MPL:
            self._replot()
        else:
            self._canvas_host.setText(
                "matplotlib is not installed.\n\n"
                "Install it (pip install matplotlib) to view probe results "
                "as comparison charts.")
        self._apply_theme()

    # ------------------------------------------------------------ UI --

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        if _MPL:
            self._canvas = FigureCanvasQTAgg(Figure())
            self._canvas_host = self._canvas
        else:
            self._canvas = None
            self._canvas_host = QLabel("")
            self._canvas_host.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._canvas_host.setMinimumHeight(360)
        lay.addWidget(self._canvas_host, 1)

        bar = QHBoxLayout()
        if self._group.get("kind") == "histogram" and _MPL:
            self._norm_cb = QCheckBox("Normalize each probe to its total")
            self._norm_cb.stateChanged.connect(self._replot)
            bar.addWidget(self._norm_cb)
            self._log_cb = QCheckBox("Log x axis")
            self._log_cb.setChecked(
                any(s.get("hist", {}).get("log") for s in self._series))
            self._log_cb.stateChanged.connect(self._replot)
            bar.addWidget(self._log_cb)
        else:
            self._norm_cb = self._log_cb = None
        bar.addStretch(1)
        if _MPL:
            save_btn = QPushButton("Save PNG")
            save_btn.clicked.connect(self._save_png)
            bar.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        lay.addLayout(bar)

    def _entity_name(self, s) -> str:
        """Series holder label: 'entity' for groups built by
        probe_result_viewer.build_result_groups, 'probe' for groups produced
        by an older build_probe_result_groups."""
        return str(s.get("entity") or s.get("probe") or "?")

    # -------------------------------------------------------- theme --

    def _apply_theme(self):
        if self._dark:
            self.setStyleSheet(
                f"QDialog {{ background: {_DARK_BG}; }}"
                f"QLabel {{ color: {_DARK_FG}; background: transparent; }}"
                f"QCheckBox {{ color: {_DARK_FG}; }}"
                f"QPushButton {{ background: #1e1e2e; color: {_DARK_FG}; "
                f"border: 1px solid #45475a; border-radius: 6px; "
                f"padding: 4px 14px; }}")
        else:
            self.setStyleSheet("")

    # ------------------------------------------------------ plots --

    def _replot(self):
        if not _MPL or self._canvas is None:
            return
        fig = self._canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        fg = _DARK_FG if self._dark else _LIGHT_FG
        ax.tick_params(colors=fg, labelsize=9)
        for sp in ax.spines.values():
            sp.set_color(fg if self._dark else "#bbbbbb")
        if self._group.get("kind") == "quantity":
            self._plot_quantity(ax)
        else:
            self._plot_histogram(ax)
        fig.tight_layout()
        self._canvas.draw()

    def _fg(self):
        return _DARK_FG if self._dark else _LIGHT_FG

    @staticmethod
    def _xtick_angle(labels) -> int:
        """x-label angle (degrees) that keeps neighbouring ticks apart.

        Entity names are often long (realworld logical volumes like
        as1-oc-214_Solid_1_vol), so a pure tick-count threshold (rotate only
        once there are 8+ bars) still lets a handful of long labels overlap.
        Combine both signals: short names stay horizontal, mid-length names
        tilt 30 deg, longer ones (or many ticks) turn 45 deg right-aligned -
        the usual sweet spot. 90 deg wastes vertical space and reads badly,
        so it is intentionally not used.
        """
        longest = max((len(x) for x in labels), default=0)
        if longest >= 12 or len(labels) > 12:
            return 45
        if longest > 6 or len(labels) > 8:
            return 30
        return 0

    def _plot_quantity(self, ax):
        series = self._series
        n = len(series)
        names = [self._entity_name(s) for s in series]
        dup = {nm for nm in names if names.count(nm) > 1}
        labels = [f"{self._entity_name(s)} ({s['qname']})"
                  if self._entity_name(s) in dup
                  else self._entity_name(s) for s in series]
        unit = next((s.get("unit") for s in series if s.get("unit")), "")
        ax.set_title(f"{self._group.get('label')} — total per "
                     f"{self._entity_label}", color=self._fg(), fontsize=12)
        ax.set_ylabel(f"total [{unit}]" if unit else "total")
        ax.set_xlabel(self._entity_label)
        xs = list(range(n))
        # fixed bar thickness: a lone bar stays slim, many bars keep a clean
        # gap between neighbours
        w = 0.5 if n == 1 else 0.42
        ax.bar(xs, [s.get("value", 0.0) for s in series], width=w,
               color=[_CYCLE[i % len(_CYCLE)] for i in xs])
        ax.set_xticks(xs)
        rot = self._xtick_angle(labels)
        ax.set_xticklabels(labels, fontsize=9, rotation=rot,
                           ha="right" if rot else "center",
                           rotation_mode="anchor")
        pad = (1.0 - w) / 2 + 0.18
        ax.set_xlim(-pad, n - 1 + pad)
        ax.grid(axis="y", alpha=0.25 if self._dark else 0.5, linestyle="--")
        for xi, s in zip(xs, series):
            v = s.get("value", 0.0)
            ax.text(xi, v, _fmt(v), ha="center",
                    va="bottom" if v >= 0 else "top",
                    fontsize=8, color=self._fg())

    def _plot_histogram(self, ax):
        norm = bool(self._norm_cb.isChecked()) if self._norm_cb else False
        logx = bool(self._log_cb.isChecked()) if self._log_cb else False
        total = sum((s.get("hist", {}).get("total") or 0) for s in self._series)
        ax.set_title(f"{self._group.get('label')}",
                     color=self._fg(), fontsize=12)
        ax.set_ylabel("counts per bin" if not norm else "% of total counts")
        xunit = next((s.get("xunit") for s in self._series if s.get("xunit")),
                     None)
        ax.set_xlabel(f"[{xunit}]" if xunit else "value")
        if logx:
            ax.set_xscale("log")
        names = [self._entity_name(s) for s in self._series]
        dup = {n for n in names if names.count(n) > 1}
        for i, s in enumerate(self._series):
            h = s.get("hist") or {}
            edges, counts = h.get("edges"), h.get("counts")
            if not edges or not counts:
                continue
            ys = list(counts)
            if norm and total:
                ys = [c / total * 100.0 for c in ys]
            xs = list(edges)
            ys_ = list(ys) + [ys[-1] if ys else 0.0]
            ename = self._entity_name(s)
            label = f"{ename} ({s['qname']})" if ename in dup else ename
            ax.step(xs, ys_, where="post", color=_CYCLE[i % len(_CYCLE)],
                    label=label, lw=1.6)
        if self._series:
            ax.legend()
        ax.grid(alpha=0.25 if self._dark else 0.5, linestyle="--")

    # ------------------------------------------------------ actions --

    def _save_png(self):
        if not _MPL or self._canvas is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save chart", f"{self._entity_label}_result.png",
            "PNG image (*.png)")
        if path:
            fig = self._canvas.figure
            w = max(400, self._canvas.width())
            h = max(300, self._canvas.height())
            fig.set_size_inches(w / 100.0, h / 100.0)
            fig.savefig(path, dpi=150,
                        facecolor=fig.get_facecolor())
