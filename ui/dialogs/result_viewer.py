"""
ResultViewerDialog — inspect the scoring output of a finished task.

rad4space writes one CSV per scored mesh / quantity into the task's run
directory (solver/runs/<task>/, next to run.mac and run.log):
  - real world volumes  -> out_<logical-volume>.csv (dumpAllQuantitiesToFile)
  - probes              -> out_<probe-name>.csv     (dumpAllQuantitiesToFile)
  - voxel boxMesh       -> out_Box_<quantity>.csv   (dumpQuantityToFile)

Double-clicking an "<analysis> result" node in the project tree opens this
dialog for the task's run directory: pick an output file on the left, then
view it as a data table with per-column statistics, or as the raw text the
solver dumped (Geant4 scoring files keep their column legend in '#' comment
lines that only the raw view shows verbatim).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

# Cap huge grids: the raw view and the statistics read at most this many
# bytes; the data table additionally caps the number of filled rows.
_MAX_BYTES = 16 * 1024 * 1024
_MAX_TABLE_ROWS = 50_000


def _fmt(v) -> str:
    """Compact numeric formatting for the statistics pane."""
    return ("%g" % v) if isinstance(v, float) else str(v)


class ResultViewerDialog(QDialog):
    """Read-only viewer for the out_*.csv files of one finished run."""

    def __init__(self, title: str, work_dir: str, dark: bool = False,
                 parent=None):
        super().__init__(parent)
        self._work_dir = work_dir
        self._dark = bool(dark)
        self._current = None  # parse result of the selected file

        self.setWindowTitle(title)
        self.resize(1060, 720)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._build_ui()
        self._scan_outputs()
        self.set_dark_theme(self._dark)
        if self._file_list.count() > 0:
            self._file_list.setCurrentRow(0)

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        dir_lbl = QLabel("Run directory: " + self._work_dir)
        dir_lbl.setWordWrap(True)
        dir_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(dir_lbl)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._file_list = QListWidget()
        self._file_list.setMinimumWidth(230)
        self._file_list.itemSelectionChanged.connect(self._on_pick)
        split.addWidget(self._file_list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self._meta = QLabel("No output file selected.")
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        rl.addWidget(self._meta)

        self._tabs = QTabWidget()
        # page 1: data table + per-column statistics
        page_data = QWidget()
        pd = QVBoxLayout(page_data)
        pd.setContentsMargins(6, 6, 6, 6)
        pd.setSpacing(6)
        self._table = QTableWidget()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(False)
        self._table.verticalHeader().setVisible(False)
        pd.addWidget(self._table, 1)
        self._stats = QPlainTextEdit()
        self._stats.setReadOnly(True)
        self._stats.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._stats.setFixedHeight(170)
        pd.addWidget(self._stats)
        # page 2: the raw text the solver dumped
        page_raw = QWidget()
        pr = QVBoxLayout(page_raw)
        pr.setContentsMargins(6, 6, 6, 6)
        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        pr.addWidget(self._raw)
        self._tabs.addTab(page_data, "Table + statistics")
        self._tabs.addTab(page_raw, "Raw CSV")
        rl.addWidget(self._tabs, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self._count_lbl = QLabel("")
        btns.addWidget(self._count_lbl, 0)
        btns.addSpacing(12)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

    # ── file discovery / parsing ────────────────────────────────────────

    def _scan_outputs(self):
        """List the scoring CSVs of the run dir. out_*.csv is the normal
        solver naming; fall back to any *.csv so foreign output still opens."""
        self._file_list.clear()
        try:
            names = [n for n in os.listdir(self._work_dir)
                     if n.lower().endswith(".csv")]
        except OSError as e:
            names = []
            self._meta.setText(f"[cannot list run directory: {e}]")
        out = [n for n in sorted(names) if n.lower().startswith("out_")]
        names = out or sorted(names)
        for n in names:
            self._file_list.addItem(n)
        if not names:
            self._show_no_files()

    def _show_no_files(self):
        self._meta.setText(
            f"No result file (out_*.csv) found in:\n{self._work_dir}\n\n"
            "Only tasks executed with the real rad4space solver produce "
            "scoring output; simulated runs and runs that failed before the "
            "dump step leave no file to view.")
        self._stats.setPlainText("")
        self._raw.setPlainText("")
        self._table.setRowCount(0)
        self._count_lbl.setText("")

    def _on_pick(self):
        item = self._file_list.currentItem()
        if item is None:
            return
        path = os.path.join(self._work_dir, item.text())
        try:
            parsed = self._parse_file(path)
        except Exception as e:  # never crash on an odd dump
            parsed = {"ok": False,
                      "msg": f"Failed to read {item.text()}: {e}"}
        self._current = parsed
        self._render()

    def _parse_file(self, path):
        """Read one scoring CSV (capped) into a small dict:
        comments / colnames / table_rows / stats / raw / truncated."""
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return {"ok": False, "msg": f"cannot stat file: {e}"}
        if size == 0:
            return {"ok": True, "empty": True,
                    "comments": [], "colnames": [], "table_rows": [],
                    "stats": [], "raw": "", "truncated": False}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(_MAX_BYTES if size > _MAX_BYTES else size)
        except OSError as e:
            return {"ok": False, "msg": f"cannot read file: {e}"}
        truncated = size > _MAX_BYTES

        comments = []          # '#' comment bodies
        colnames = None        # last comment that looks like a column legend
        table_rows = []        # first _MAX_TABLE_ROWS data lines (cell str)
        # running numeric accumulators per column for the statistics
        acc_ent, acc_nz, acc_min, acc_max, acc_sum = [], [], [], [], []
        n_data = 0
        width = 0

        for line in raw.splitlines():
            if line.startswith("#"):
                body = line[1:].strip()
                comments.append(body)
                if "," in body and ":" not in body:
                    cand = [c.strip() for c in body.split(",")]
                    if len(cand) >= 2 and all(cand):
                        colnames = cand
                continue
            if not line.strip():
                continue
            cells = [c.strip() for c in line.split(",")]
            width = max(width, len(cells))
            if n_data < _MAX_TABLE_ROWS:
                table_rows.append(cells)
            for ci, cell in enumerate(cells):
                if len(acc_ent) <= ci:
                    pad = ci + 1 - len(acc_ent)
                    acc_ent += [0] * pad
                    acc_nz += [0] * pad
                    acc_min += [None] * pad
                    acc_max += [None] * pad
                    acc_sum += [0.0] * pad
                try:
                    v = float(cell)
                except ValueError:
                    continue
                acc_ent[ci] += 1
                if v != 0.0:
                    acc_nz[ci] += 1
                if acc_min[ci] is None or v < acc_min[ci]:
                    acc_min[ci] = v
                if acc_max[ci] is None or v > acc_max[ci]:
                    acc_max[ci] = v
                acc_sum[ci] += v
            n_data += 1

        n_cols = max(width, len(colnames or []), len(acc_ent))
        if colnames is None:
            colnames = [f"col{i + 1}" for i in range(n_cols)]
        elif len(colnames) < n_cols:
            colnames = list(colnames) + [f"col{i + 1}"
                                         for i in range(len(colnames),
                                                        n_cols)]
        stats = []
        for ci in range(n_cols):
            if ci >= len(acc_ent) or acc_ent[ci] == 0:
                continue
            stats.append({
                "name": colnames[ci],
                "entries": acc_ent[ci],
                "nonzero": acc_nz[ci],
                "min": acc_min[ci],
                "max": acc_max[ci],
                "sum": acc_sum[ci],
            })
        return {"ok": True, "empty": False, "comments": comments,
                "colnames": colnames, "table_rows": table_rows,
                "stats": stats, "raw": raw, "truncated": truncated,
                "rows": n_data, "size": size}

    # ── rendering ───────────────────────────────────────────────────────

    def _render(self):
        cur = self._current
        if cur is None:
            return
        if not cur.get("ok"):
            self._meta.setText(cur.get("msg", "parse error"))
            self._table.setRowCount(0)
            self._stats.setPlainText("")
            self._raw.setPlainText("")
            self._count_lbl.setText("")
            return
        if cur.get("empty"):
            self._meta.setText("This result file is empty (0 bytes) - the "
                               "scorer dumped nothing.")
            self._table.setRowCount(0)
            self._stats.setPlainText("")
            self._raw.setPlainText("")
            self._count_lbl.setText("0 rows")
            return

        item = self._file_list.currentItem()
        name = item.text() if item else "output"
        meta = [c for c in cur["comments"] if not c.startswith(("mesh ",
                                                                "scorer ",
                                                                "primitive"))]
        size_txt = f"{cur['size'] / 1024:.1f} KB" if cur["size"] >= 1024 \
            else f"{cur['size']} B"
        head = f"{name}  ({cur['rows']} data rows, {size_txt})"
        if meta:
            head += "\n" + "\n".join(meta[:3])
        self._meta.setText(head)

        # raw page
        raw = cur["raw"]
        if cur["truncated"]:
            raw += (f"\n\n… [truncated: showing the first "
                    f"{_MAX_BYTES // (1024 * 1024)} MB of "
                    f"{cur['size'] / (1024 * 1024):.1f} MB]")
        self._raw.setPlainText(raw)

        # data table (capped)
        rows = cur["table_rows"]
        cols = cur["colnames"]
        self._table.clear()
        self._table.setColumnCount(len(cols))
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setRowCount(len(rows))
        for ri, row in enumerate(rows):
            for ci in range(len(cols)):
                txt = row[ci] if ci < len(row) else ""
                self._table.setItem(ri, ci, QTableWidgetItem(txt))

        # statistics pane
        lines = [f"Per-column statistics over {cur['rows']} data row(s)"
                 + (" (file read cap reached - see raw tab for the tail)"
                    if cur["truncated"] else "")]
        for s in cur["stats"]:
            mean = s["sum"] / s["entries"]
            lines.append(
                f"  {s['name']:<22} n={s['entries']:<8} "
                f"non-zero={s['nonzero']:<8} "
                f"min={_fmt(s['min']):<14} max={_fmt(s['max']):<14} "
                f"mean={_fmt(mean):<14} sum={_fmt(s['sum'])}")
        self._stats.setPlainText("\n".join(lines))

        note = f"{cur['rows']} rows"
        if len(rows) < cur["rows"]:
            note += f" (table shows the first {len(rows)})"
        self._count_lbl.setText(note)

    # ── theme ───────────────────────────────────────────────────────────

    def set_dark_theme(self, dark: bool):
        self._dark = bool(dark)
        if dark:
            base, bg, fg, alt = "#1e1e2e", "#11111b", "#cdd6f4", "#313244"
        else:
            base, bg, fg, alt = "#f5f5f5", "#ffffff", "#2c2c2c", "#f0f0f0"
        self.setStyleSheet(f"""
            QDialog {{ background-color: {base}; }}
            QLabel {{ color: {fg}; font-size: 12px; }}
            QListWidget, QTableWidget, QPlainTextEdit {{
                background-color: {bg}; color: {fg};
                border: 1px solid {alt}; border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }}
            QListWidget::item:selected {{
                background-color: {alt}; color: {fg};
            }}
            QHeaderView::section {{
                background-color: {alt}; color: {fg};
                border: none; padding: 3px 8px; font-size: 12px;
            }}
            QTabWidget::pane {{
                border: 1px solid {alt}; border-radius: 4px;
            }}
            QTabBar::tab {{
                background-color: {alt}; color: {fg};
                padding: 5px 14px; margin-right: 2px;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{ background-color: {bg}; }}
            QPushButton {{
                background-color: {alt}; color: {fg};
                border: 1px solid {alt}; border-radius: 6px;
                padding: 6px 18px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: #0078d4; }}
            QPlainTextEdit {{ selection-background-color: #45475a; }}
        """)
