"""ParticleDialog v2 - particle source settings.

Interaction model (no window jumping):

  * The dialog has ONE fixed window size, decided once at open time and sized
    so the full GPS form fits without ever resizing.  Content changes (mode
    switch, spectrum / shape / angular type switch) only swap widgets inside
    the left scroll area; the window never moves or resizes.
  * Top-left: three mode buttons - ParticleGun (simple mono source),
    GeneralParticleSource (full spectrum / shape / angle form) and
    Import file (bring in a hand-written .mac and use it verbatim).  The
    three source types are independent of each other; only one is ever
    active, and clicking the active one again returns to the empty state.
  * Opening with no saved config shows a calm blank state; clicking a mode
    fills in that source's parameters and refreshes the live macro preview.
  * Parameter pages for the two form modes are fully separate - "whose is
    whose", no shared rows, no grayed-out fields.  Both pages keep their own
    values while the dialog is open and both are persisted together on save.
  * Import-file mode is deliberately hands-off: the chosen text is loaded
    into the right side, which becomes a plain editable box there.  Nothing
    is parsed back into the gun / GPS forms and nothing is filtered - the
    saved text is written to the .mac exactly as the user left it.
  * Right side = generated /gps macro preview (read-only in form modes, and
    an editable text buffer in import-file mode).
  * Units fixed mm / MeV / deg; mm -> cm is applied when writing the .mac.

The data schema / macro builder live in gps_source.py (pure, no Qt).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QButtonGroup, QComboBox, QDoubleSpinBox, QSpinBox, QWidget,
    QSplitter, QScrollArea, QPlainTextEdit, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

from ui.dialogs import gps_source as gps
from ui.dialogs.analysis_common import DIALOG_STYLE, fit_size_to_screen

# unit token -> spin-box kind (range / decimals class)
_KIND = {"mm": "mm", "MeV": "MeV", "deg": "deg+", "K": "unit", "": "unit"}

# sensible seed values for keys that are not present in a loaded config
_DEFS = {
    "e_mono": 1.0, "e_min": 0.01, "e_max": 10.0, "e_sigma": 0.1,
    "gradient": 1.0, "intercept": 1.0, "alpha": 1.0, "ezero": 1.0,
    "radius": 20.0, "inner_radius": 5.0,
    "halfx": 20.0, "halfy": 20.0, "halfz": 20.0,
    "palpha": 0.0, "ptheta": 0.0, "pphi": 0.0,
    "theta_min": 0.0, "theta_max": 180.0,
    "phi_min": 0.0, "phi_max": 360.0,
    "sigma_r": 1.0, "sigma_x": 1.0, "sigma_y": 1.0,
    "fx": 0.0, "fy": 0.0, "fz": 0.0,
}


# All parameter rows use the same label width and the same value-control
# width, so every combo box and spin box sits in one aligned column.
_LABEL_W = 104
_CTRL_W = 230


class FieldRow(QWidget):
    """One parameter line: fixed-width label + spin box + unit suffix.
    All rows share the same label width so value boxes line up in columns."""

    changed = pyqtSignal()

    def __init__(self, key, label, unit, label_w=_LABEL_W, spin_w=_CTRL_W,
                 value=0.0, parent=None):
        super().__init__(parent)
        self._key = key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(label)
        lbl.setFixedWidth(label_w)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl)
        sp = QDoubleSpinBox()
        sp.setDecimals(3 if unit in ("mm", "deg") else 4)
        kind = _KIND.get(unit, "unit")
        if kind == "mm":
            sp.setRange(-1e5, 1e5)
        elif kind == "MeV":
            sp.setRange(1e-9, 1e6)
        elif kind == "deg+":
            sp.setRange(0.0, 720.0)
        else:
            sp.setRange(-1e6, 1e6)
        sp.setValue(float(value or 0))      # seed before signal connect
        if unit:
            sp.setSuffix(" " + unit)
        sp.setFixedWidth(spin_w)
        sp.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(sp)
        lay.addStretch()
        self._spin = sp
        sp.valueChanged.connect(self.changed.emit)

    @property
    def key(self):
        return self._key

    def value(self):
        return self._spin.value()

    def set_value(self, v):
        self._spin.setValue(float(v or 0))

    def focus_input(self):
        self._spin.setFocus()
        try:
            self._spin.selectAll()
        except Exception:
            pass


class VecRow(QWidget):
    """One unitless 3-component vector row: fixed-width label then three small
    x / y / z spin boxes. Used for the rot1 / rot2 orientation axes whose
    components are not physical lengths and carry no unit suffix."""

    changed = pyqtSignal()

    def __init__(self, key, label, default=(1.0, 0.0, 0.0), tip="",
                 label_w=_LABEL_W, spin_w=108, parent=None):
        super().__init__(parent)
        self._key = key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lbl = QLabel(label)
        lbl.setFixedWidth(label_w)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl)
        self._spins = []
        for tag, v0 in zip("xyz", default):
            tl = QLabel(tag)
            tl.setFixedWidth(12)
            lay.addWidget(tl)
            sp = QDoubleSpinBox()
            sp.setDecimals(3)
            sp.setRange(-1e6, 1e6)
            sp.setValue(float(v0))          # seed before signal connect
            sp.setFixedWidth(spin_w)
            sp.setAlignment(Qt.AlignmentFlag.AlignRight)
            if tip:
                sp.setToolTip(tip)
            lay.addWidget(sp)
            self._spins.append(sp)
            sp.valueChanged.connect(self.changed.emit)
        lay.addStretch()
        if tip:
            self.setToolTip(tip)

    @property
    def key(self):
        return self._key

    def value(self):
        return (self._spins[0].value(), self._spins[1].value(),
                self._spins[2].value())

    def set_value(self, v):
        for sp, d in zip(self._spins, v):
            sp.setValue(float(d))


class ParticleDialog(QDialog):
    """Particle source settings (fixed-size window, no content jumping)."""

    close_requested = pyqtSignal()

    def __init__(self, parent=None, task=None, gdml_agent=None):
        super().__init__(parent)
        self._task = task
        self._gdml_agent = gdml_agent
        self._dark = False
        self._mode = None                 # None | "gun" | "gps" | "file"
        self._gun_ready = False           # page has been seeded at least once
        self._gps_ready = False
        self._file_text = ""              # raw macro text held in file mode
        self._file_name = ""              # last imported file name (display)
        self._user_data = []              # [[E(MeV), weight], ...]
        self._defs = dict(_DEFS)
        self._acc = "#0078d4"             # accent (light)
        self._titles = []                 # (QLabel, no, name) refreshed on theme
        self._mode_buttons = []           # the top mode buttons
        self._preview_win = None          # held GunDirectionPreview window

        self.setWindowTitle("Particle Source")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._load_existing()
        self._apply_theme(False)
        # One fixed size for the whole life of the dialog.  It is chosen to
        # fit the tallest page (GPS) so switching modes never resizes it.
        # The window is slightly narrower than before: the parameter column
        # only needs its form width, the rest belongs to the macro preview.
        w, h = fit_size_to_screen(self, 1000, 880)
        self.resize(w, h)
        QTimer.singleShot(0, self._settle_split)
        self._refresh_preview()

    def _settle_split(self):
        """Park the splitter so the parameter column sits at its minimum
        (content) width and the macro preview starts right after it."""
        try:
            avail = self._split.width()
            self._split.setSizes([560, max(360, avail - 560)])
        except Exception:
            pass

    # ------------------------------------------------------------- shell ----

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        # -- top-left mode switcher ----------------------------------------
        top = QHBoxLayout()
        top.setSpacing(8)
        self._btn_gun = QPushButton("ParticleGun")
        self._btn_gps = QPushButton("GeneralParticleSource")
        self._btn_file = QPushButton("Import file\u2026")
        for b, fn in ((self._btn_gun, lambda: self._click_mode("gun")),
                      (self._btn_gps, lambda: self._click_mode("gps")),
                      (self._btn_file, lambda: self._click_mode("file"))):
            b.setCheckable(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            self._mode_buttons.append(b)
            top.addWidget(b)
        top.addStretch()
        lay.addLayout(top)

        # -- body: parameters (left) | macro preview (right) ---------------
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.Shape.NoFrame)
        sc.setMinimumWidth(560)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(2, 2, 2, 2)
        bv.setSpacing(6)

        self._hint = QLabel(
            "\n\nSelect ParticleGun, GeneralParticleSource or Import file "
            "above to configure the source.\nThe macro appears on the right "
            "(in import mode you can edit it there).")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignTop
                                | Qt.AlignmentFlag.AlignHCenter)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#8a8d9a;font-size:12px;")
        bv.addWidget(self._hint)

        self._gun_page = self._build_gun_page()
        self._gps_page = self._build_gps_page()
        self._file_page = self._build_file_page()
        bv.addWidget(self._gun_page)
        bv.addWidget(self._gps_page)
        bv.addWidget(self._file_page)
        bv.addStretch()

        sc.setWidget(body)
        split.addWidget(sc)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMinimumWidth(360)
        self._preview.setMinimumHeight(320)
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._preview.setFont(mono)
        self._preview.textChanged.connect(self._on_preview_edited)
        split.addWidget(self._preview)
        # The parameter column keeps its minimum (content) width while extra
        # space always goes to the macro preview, so dragging the handle to
        # the left stops exactly at the form and the preview starts there.
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self._split = split
        lay.addWidget(split, 1)

        # -- bottom actions -------------------------------------------------
        bar = QHBoxLayout()
        bar.addStretch()
        self._btn_3d = QPushButton("3D Preview")
        self._btn_3d.setToolTip(
            "Open a live 3D sketch of the source: position plus the emitted "
            "direction / angular distribution.  Works for ParticleGun and "
            "GeneralParticleSource.")
        self._btn_3d.clicked.connect(self._open_3d_preview)
        self._btn_3d.setEnabled(False)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.close)
        self._btn_save = QPushButton("Save to Task")
        self._btn_save.clicked.connect(self._save)
        self._btn_save.setEnabled(False)
        bar.addWidget(self._btn_3d)
        bar.addWidget(self._btn_cancel)
        bar.addWidget(self._btn_save)
        lay.addLayout(bar)

        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False)

    # ------------------------------------------------------- small pieces --

    def _mk_title(self, no, name):
        lab = QLabel()
        self._titles.append((lab, no, name))
        lab.setContentsMargins(2, 10, 0, 2)
        return lab

    def _apply_titles(self):
        for lab, no, name in self._titles:
            if no:
                lab.setText(
                    f"<span style='color:{self._acc};font-size:13px;"
                    f"font-weight:600;'>{no} </span>"
                    f"<span style='font-size:13px;font-weight:600;'>{name}"
                    f"</span>")
            else:
                lab.setText(f"<b style='font-size:13px;'>{name}</b>")

    def _build_particle_block(self, page_v, tag):
        """Standard / ion particle chooser.  Returns a namespace dict with the
        widgets so gun and gps pages can share the same construction code."""
        grp = QButtonGroup(self)
        rb_std = QRadioButton("Standard particle")
        rb_ion = QRadioButton("Ion")
        grp.addButton(rb_std)
        grp.addButton(rb_ion)

        rw = QWidget()
        rh = QHBoxLayout(rw)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.addWidget(rb_std)
        rh.addWidget(rb_ion)
        rh.addStretch()
        page_v.addWidget(rw)

        std_w = QWidget()
        sl = QHBoxLayout(std_w)
        sl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Type:")
        lbl.setFixedWidth(_LABEL_W)
        sl.addWidget(lbl)
        cb = QComboBox()
        cb.addItems(gps.PARTICLES)
        cb.setCurrentText("gamma")
        cb.setFixedWidth(_CTRL_W)
        sl.addWidget(cb)
        sl.addStretch()
        page_v.addWidget(std_w)

        ion_w = QWidget()
        il = QHBoxLayout(ion_w)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(4)
        z, a, q = QSpinBox(), QSpinBox(), QSpinBox()
        z.setRange(1, 130)
        a.setRange(1, 330)
        q.setRange(-1, 130)
        e = QDoubleSpinBox()
        e.setRange(0.0, 1e6)
        e.setDecimals(1)
        for lbl, w, suffix in (("Z:", z, ""), ("A:", a, ""),
                               ("Q:", q, ""), ("E*:", e, "")):
            lb = QLabel(lbl)
            lb.setFixedWidth(24)
            il.addWidget(lb)
            w.setFixedWidth(76)
            if suffix:
                w.setSuffix(" " + suffix)
            il.addWidget(w)
        il.addStretch()
        page_v.addWidget(ion_w)

        def _apply():
            ion = rb_ion.isChecked()
            std_w.setVisible(not ion)
            ion_w.setVisible(ion)

        rb_std.toggled.connect(lambda _c: (_apply(), self._refresh_preview()))
        rb_std.setChecked(True)
        _apply()
        for w in (z, a, q, e):
            w.valueChanged.connect(self._refresh_preview)
        cb.currentIndexChanged.connect(self._refresh_preview)

        return {"std": rb_std, "ion": rb_ion, "combo": cb,
                "z": z, "a": a, "q": q, "e": e, "std_w": std_w,
                "ion_w": ion_w, "tag": tag}

    def _num_row(self, key, label, unit):
        fr = FieldRow(key, label, unit, value=self._defs.get(key, 0.0))
        fr.changed.connect(self._refresh_preview)
        return fr

    # ----------------------------------------------------- Import file ----

    def _build_file_page(self):
        """Import-file mode: no parameter form at all.  A single "Import
        file..." button loads a hand-written .mac whose text is shown in the
        right-side box, where the user can edit it.  The text is used exactly
        as-is: nothing is parsed into the gun / GPS forms and nothing is
        filtered, so the user stays in control of their macro."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        v.addWidget(self._mk_title(0, "Import file"))
        row = QHBoxLayout()
        row.setSpacing(6)
        btn = QPushButton("Import file\u2026")
        btn.clicked.connect(self._import_macro_file)
        row.addWidget(btn)
        self._file_loaded = QLabel("no file imported")
        self._file_loaded.setStyleSheet("color:#8a8d9a;")
        row.addWidget(self._file_loaded)
        row.addStretch()
        v.addLayout(row)

        note = QLabel(
            "The chosen text appears on the right where you can edit it "
            "directly.\nLines are used exactly as shown - nothing is parsed, "
            "filtered or converted.\nParticleGun / GeneralParticleSource are "
            "not affected; this source is independent of them.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a8d9a;font-size:12px;")
        v.addWidget(note)
        v.addStretch()
        page.setVisible(False)
        return page

    def _import_macro_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import macro file", "",
            "Macro (*.mac *.txt *.g4mac *.in *.mcr);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as f:
                text = f.read()
        except OSError:
            QMessageBox.warning(self, "Import failed",
                                "Could not read the selected file.")
            return
        self._file_text = text
        self._file_name = os.path.basename(path)
        n = len([ln for ln in text.splitlines() if ln.strip()])
        self._file_loaded.setText(
            f"{self._file_name}  ({n} lines)")
        if self._mode == "file":
            self._sync_file_editor()
        self._refresh_preview()
        self._btn_save.setEnabled(True)

    # ------------------------------------------------------- ParticleGun ----

    def _build_gun_page(self):
        """ParticleGun = mono particle, point position, fixed direction.
        Four static groups; every row is always visible (nothing to jump)."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        v.addWidget(self._mk_title(1, "Particle"))
        self._g_p = self._build_particle_block(v, "gun")

        v.addWidget(self._mk_title(2, "Energy"))
        self._g_energy = self._num_row("energy", "Energy E", "MeV")
        v.addWidget(self._g_energy)

        v.addWidget(self._mk_title(3, "Position"))
        self._g_pos = {}
        for k, lbl in (("x", "x"), ("y", "y"), ("z", "z")):
            fr = self._num_row("g" + k, "Position " + lbl, "mm")
            self._g_pos[k] = fr
            v.addWidget(fr)

        v.addWidget(self._mk_title(4, "Direction"))
        self._g_dir = {}
        for k, lbl in (("x", "dx"), ("y", "dy"), ("z", "dz")):
            fr = self._num_row("d" + k, lbl, "")
            fr.set_value({"x": 0.0, "y": 0.0, "z": 1.0}[k])
            self._g_dir[k] = fr
            v.addWidget(fr)
        page.setVisible(False)
        return page

    def _populate_gun(self, cfg=None):
        g = None
        if cfg:
            g = cfg.get("gun")
        if g is None:
            g = gps.default_gun_config()
        gp = g.get("particle", {}) or {}
        p = self._g_p
        if gp.get("kind") == "ion":
            p["ion"].setChecked(True)
            p["z"].setValue(int(gp.get("z", 26)))
            p["a"].setValue(int(gp.get("a", 56)))
            p["q"].setValue(int(gp.get("q", 0)))
            p["e"].setValue(float(gp.get("e", 0)))
        else:
            p["std"].setChecked(True)
            ix = p["combo"].findText(gp.get("name", "gamma"))
            if ix >= 0:
                p["combo"].setCurrentIndex(ix)
        self._g_energy.set_value(g.get("energy", 10.0))
        ps = g.get("position", {}) or {}
        for k in ("x", "y", "z"):
            self._g_pos[k].set_value(ps.get(k, 0.0))
        d = g.get("direction", {}) or {}
        for k, dv in (("x", 0.0), ("y", 0.0), ("z", 1.0)):
            self._g_dir[k].set_value(d.get(k, dv))

    def _collect_gun(self):
        p = self._g_p
        if p["ion"].isChecked():
            gp = {"kind": "ion", "z": p["z"].value(), "a": p["a"].value(),
                  "q": p["q"].value(), "e": p["e"].value()}
        else:
            gp = {"kind": "standard", "name": p["combo"].currentText()}
        return {"particle": gp,
                "energy": self._g_energy.value(),
                "position": {k: self._g_pos[k].value() for k in ("x", "y", "z")},
                "direction": {k: self._g_dir[k].value() for k in ("x", "y", "z")}}

    # ----------------------------------------------------- GPS (full) ------

    def _build_gps_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        # 1 -- particle ----------------------------------------------------
        v.addWidget(self._mk_title(1, "Particle"))
        self._p = self._build_particle_block(v, "gps")

        # 2 -- energy spectrum ---------------------------------------------
        v.addWidget(self._mk_title(2, "Energy spectrum"))
        er = QHBoxLayout()
        er.setSpacing(6)
        lbl = QLabel("Type:")
        lbl.setFixedWidth(_LABEL_W)
        er.addWidget(lbl)
        self._ene_cb = QComboBox()
        for t, lab in gps.ENERGY_TYPES:
            self._ene_cb.addItem(lab, t)
        self._ene_cb.currentIndexChanged.connect(self._apply_ene_type)
        self._ene_cb.setFixedWidth(_CTRL_W)
        er.addWidget(self._ene_cb)
        er.addStretch()
        v.addLayout(er)
        self._ene_pages = {}
        self._ene_rows = {}      # type -> [(key, FieldRow), ...]
        for t, _lab in gps.ENERGY_TYPES:
            pw = QWidget()
            pl = QVBoxLayout(pw)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(4)
            rows = []
            if t == "User":
                uh = QHBoxLayout()
                btn = QPushButton("Load spectrum file\u2026")
                btn.clicked.connect(self._import_user_spectrum)
                self._user_btn = btn
                info = QLabel("no spectrum loaded")
                info.setStyleSheet("color:#8a8d9a;")
                self._user_info = info
                uh.addWidget(btn)
                uh.addWidget(info)
                uh.addStretch()
                pl.addLayout(uh)
            else:
                for key, label, unit in gps.ENERGY_FIELDS.get(t, []):
                    fr = self._num_row(key, label, unit)
                    pl.addWidget(fr)
                    rows.append((key, fr))
            pl.addStretch()
            pw.setVisible(False)
            v.addWidget(pw)
            self._ene_pages[t] = pw
            self._ene_rows[t] = rows

        # 3 -- source position ---------------------------------------------
        v.addWidget(self._mk_title(3, "Source position"))
        pr = QHBoxLayout()
        pr.setSpacing(6)
        lbl = QLabel("Type:")
        lbl.setFixedWidth(_LABEL_W)
        pr.addWidget(lbl)
        self._pos_cb = QComboBox()
        for t, lab in gps.POS_TYPES:
            self._pos_cb.addItem(lab, t)
        self._pos_cb.currentIndexChanged.connect(self._apply_pos_type)
        self._pos_cb.setFixedWidth(_CTRL_W)
        pr.addWidget(self._pos_cb)
        pr.addStretch()
        v.addLayout(pr)
        self._shape_row_w = QWidget()
        shr = QHBoxLayout(self._shape_row_w)
        shr.setContentsMargins(0, 0, 0, 0)
        shr.setSpacing(6)
        lbl = QLabel("Shape:")
        lbl.setFixedWidth(_LABEL_W)
        shr.addWidget(lbl)
        self._shape_cb = QComboBox()
        self._shape_cb.currentIndexChanged.connect(self._apply_shape)
        self._shape_cb.setFixedWidth(_CTRL_W)
        shr.addWidget(self._shape_cb)
        shr.addStretch()
        v.addWidget(self._shape_row_w)

        self._xyz = []
        for k in ("x", "y", "z"):
            fr = self._num_row("c" + k, "Centre " + k, "mm")
            self._xyz.append(fr)
            v.addWidget(fr)

        self._shape_pages = {}
        self._shape_rows = {}   # shape -> [(key, FieldRow), ...]
        shapes = []
        for lst in gps.POS_SHAPES.values():
            for s in lst:
                if s not in shapes:
                    shapes.append(s)
        for sh in shapes:
            pw = QWidget()
            pl = QVBoxLayout(pw)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(4)
            rows = []
            for key, label, unit in gps.SHAPE_FIELDS.get(sh, []):
                fr = self._num_row(key, label, unit)
                pl.addWidget(fr)
                rows.append((key, fr))
            pl.addStretch()
            pw.setVisible(False)
            v.addWidget(pw)
            self._shape_pages[sh] = pw
            self._shape_rows[sh] = rows

        pos_tip = ("Orientation of the source shape axes (manual Table 2.4): "
                   "rot1 = X' direction, rot2 = a second vector in its X'Y' "
                   "plane. Keep 1,0,0 / 0,1,0 for the default (unrotated) "
                   "shape.")
        self._pos_rot1 = VecRow("rot1", "rot1 (X')",
                                gps.ROT_AXES[0][1], tip=pos_tip)
        self._pos_rot2 = VecRow("rot2", "rot2 (Y')",
                                gps.ROT_AXES[1][1], tip=pos_tip)
        for row in (self._pos_rot1, self._pos_rot2):
            row.changed.connect(self._refresh_preview)
            v.addWidget(row)

        # 4 -- angular distribution ----------------------------------------
        v.addWidget(self._mk_title(4, "Angular distribution"))
        ar = QHBoxLayout()
        ar.setSpacing(6)
        lbl = QLabel("Type:")
        lbl.setFixedWidth(_LABEL_W)
        ar.addWidget(lbl)
        self._ang_cb = QComboBox()
        for t, lab in gps.ANG_TYPES:
            self._ang_cb.addItem(lab, t)
        self._ang_cb.currentIndexChanged.connect(self._apply_ang_type)
        self._ang_cb.setFixedWidth(_CTRL_W)
        ar.addWidget(self._ang_cb)
        ar.addStretch()
        v.addLayout(ar)
        self._ang_pages = {}
        self._ang_rows = {}     # type -> [(key, FieldRow), ...]
        for t, _lab in gps.ANG_TYPES:
            pw = QWidget()
            pl = QVBoxLayout(pw)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(4)
            rows = []
            for key, label, unit in gps.ANG_FIELDS.get(t, []):
                fr = self._num_row(key, label, unit)
                pl.addWidget(fr)
                rows.append((key, fr))
            pl.addStretch()
            pw.setVisible(False)
            v.addWidget(pw)
            self._ang_pages[t] = pw
            self._ang_rows[t] = rows

        ang_tip = ("Orientation of the angular-distribution axes (manual "
                   "Table 2.5, Fig. 2.3): rot1 = X' direction, rot2 = a "
                   "second vector in its X'Y' plane. Rotate these together "
                   "with the source-shape axes when the shape is tilted.")
        self._ang_rot1 = VecRow("rot1", "rot1 (X')",
                                gps.ROT_AXES[0][1], tip=ang_tip)
        self._ang_rot2 = VecRow("rot2", "rot2 (Y')",
                                gps.ROT_AXES[1][1], tip=ang_tip)
        for row in (self._ang_rot1, self._ang_rot2):
            row.changed.connect(self._refresh_preview)
            v.addWidget(row)

        page.setVisible(False)
        return page

    # ----------------------------------------------------- GPS handlers ----

    def _apply_ene_type(self, _ix=None):
        t = self._ene_cb.currentData() or "Lin"
        for k, pg in self._ene_pages.items():
            pg.setVisible(k == t)
        self._refresh_preview()

    def _apply_pos_type(self, _ix=None):
        t = self._pos_cb.currentData() or "Point"
        lst = gps.POS_SHAPES.get(t, [])
        self._shape_row_w.setVisible(t != "Point")
        # rot1/rot2 tilt the extended source.  A Surface (sphere) cannot show
        # the tilt, so only the Plane type keeps its rotation editable.
        for row in (self._pos_rot1, self._pos_rot2):
            row.setVisible(t == "Plane")
        old = self._shape_cb.currentData()
        self._shape_cb.blockSignals(True)
        self._shape_cb.clear()
        for s in lst:
            self._shape_cb.addItem(s, s)
        self._shape_cb.blockSignals(False)
        if old in lst:
            self._shape_cb.setCurrentIndex(lst.index(old))
        elif lst:
            self._shape_cb.setCurrentIndex(0)
        self._apply_shape()

    def _apply_shape(self, _ix=None):
        sh = self._shape_cb.currentData() or ""
        for k, pg in self._shape_pages.items():
            pg.setVisible(bool(sh) and k == sh)
        self._refresh_preview()

    def _apply_ang_type(self, _ix=None):
        t = self._ang_cb.currentData() or "iso"
        for k, pg in self._ang_pages.items():
            pg.setVisible(k == t)
        # iso needs no reference axes: the user drives theta/phi directly and
        # rotating an isotropic window is invisible anyway.  cos emission does
        # depend on an orientation, so its rot1/rot2 stay editable.
        for row in (self._ang_rot1, self._ang_rot2):
            row.setVisible(t == "cos")
        self._refresh_preview()

    # ----------------------------------------------------- GPS load/save ----

    def _populate_gps(self, cfg=None):
        c = cfg if cfg is not None else gps.default_config()
        # particle
        p = c.get("particle", {}) or {}
        pb = self._p
        if p.get("kind") == "ion":
            pb["ion"].setChecked(True)
            pb["z"].setValue(int(p.get("z", 26)))
            pb["a"].setValue(int(p.get("a", 56)))
            pb["q"].setValue(int(p.get("q", 0)))
            pb["e"].setValue(float(p.get("e", 0)))
        else:
            pb["std"].setChecked(True)
            ix = pb["combo"].findText(p.get("name", "gamma"))
            if ix >= 0:
                pb["combo"].setCurrentIndex(ix)
        # energy
        en = c.get("energy", {}) or {}
        t = en.get("type", "Lin")
        ix = self._ene_cb.findData(t)
        if ix >= 0:
            self._ene_cb.blockSignals(True)
            self._ene_cb.setCurrentIndex(ix)
            self._ene_cb.blockSignals(False)
        if t == "User":
            self._user_data = [list(x) for x in (en.get("data") or [])]
        else:
            for key, fr in self._ene_rows.get(t, []):
                if key in en:
                    fr.set_value(en[key])
        self._apply_ene_type()
        # position
        ps = c.get("position", {}) or {}
        pt = ps.get("type", "Point")
        if pt not in {t for t, _lab in gps.POS_TYPES}:
            # A saved task can still carry a position type the form no longer
            # offers (Volume).  Fall back to Surface - the closest option that
            # keeps the source extended - instead of silently collapsing it
            # to the Point default and losing the whole extent.
            pt = "Surface"
        ix = self._pos_cb.findData(pt)
        if ix >= 0:
            self._pos_cb.blockSignals(True)
            self._pos_cb.setCurrentIndex(ix)
            self._pos_cb.blockSignals(False)
        lst = gps.POS_SHAPES.get(pt, [])
        sh = ps.get("shape", lst[0] if lst else "")
        if sh not in lst:
            # Saved shapes outside the trimmed set (e.g. Plane + Circle or
            # Surface + Ellipsoid) map onto the single shape that type offers.
            sh = lst[0] if lst else ""
        self._shape_cb.blockSignals(True)
        self._shape_cb.clear()
        for s in lst:
            self._shape_cb.addItem(s, s)
        self._shape_cb.blockSignals(False)
        if sh in lst:
            self._shape_cb.setCurrentIndex(lst.index(sh))
        self._apply_pos_type()
        self._shape_cb.blockSignals(True)
        if sh in lst:
            self._shape_cb.setCurrentIndex(lst.index(sh))
        self._shape_cb.blockSignals(False)
        self._apply_shape()
        for i, k in enumerate(("x", "y", "z")):
            self._xyz[i].set_value(ps.get("c" + k, 0.0))
        for key, fr in self._shape_rows.get(sh, []):
            if key in ps:
                fr.set_value(ps[key])
        for tag, row in (("rot1", self._pos_rot1), ("rot2", self._pos_rot2)):
            v = ps.get(tag)
            if isinstance(v, dict):
                row.set_value((v.get("x", 0), v.get("y", 0), v.get("z", 0)))
            else:
                row.set_value(dict(gps.ROT_AXES)[tag])
        # angular
        an = c.get("angular", {}) or {}
        at = an.get("type", "iso")
        ix = self._ang_cb.findData(at)
        if ix >= 0:
            self._ang_cb.blockSignals(True)
            self._ang_cb.setCurrentIndex(ix)
            self._ang_cb.blockSignals(False)
        self._apply_ang_type()
        for key, fr in self._ang_rows.get(at, []):
            if key in an:
                fr.set_value(an[key])
        for tag, row in (("rot1", self._ang_rot1), ("rot2", self._ang_rot2)):
            v = an.get(tag)
            if isinstance(v, dict):
                row.set_value((v.get("x", 0), v.get("y", 0), v.get("z", 0)))
            else:
                row.set_value(dict(gps.ROT_AXES)[tag])
        self._update_user_info()

    def _collect_gps(self):
        pb = self._p
        if pb["ion"].isChecked():
            p = {"kind": "ion", "z": pb["z"].value(), "a": pb["a"].value(),
                 "q": pb["q"].value(), "e": pb["e"].value()}
        else:
            p = {"kind": "standard", "name": pb["combo"].currentText()}
        t = self._ene_cb.currentData() or "Lin"
        en = {"type": t}
        if t == "User":
            en["data"] = [list(x) for x in self._user_data]
        else:
            for key, fr in self._ene_rows.get(t, []):
                en[key] = fr.value()
        pt = self._pos_cb.currentData() or "Point"
        ps = {"type": pt}
        if pt != "Point":
            sh = self._shape_cb.currentData() or ""
            if sh:
                ps["shape"] = sh
                for key, fr in self._shape_rows.get(sh, []):
                    ps[key] = fr.value()
        for i, k in enumerate(("x", "y", "z")):
            ps["c" + k] = self._xyz[i].value()
        # Rotations only tilt a Plane source; Surface (sphere) / Point never
        # carry rot1/rot2 in the stored config (see _apply_pos_type).
        if pt == "Plane":
            for tag, row in (("rot1", self._pos_rot1),
                             ("rot2", self._pos_rot2)):
                v = row.value()
                if v != dict(gps.ROT_AXES)[tag]:
                    ps[tag] = {"x": v[0], "y": v[1], "z": v[2]}
        at = self._ang_cb.currentData() or "iso"
        an = {"type": at}
        for key, fr in self._ang_rows.get(at, []):
            an[key] = fr.value()
        # rot1/rot2 only orient a cos lobe; iso ignores them (see
        # _apply_ang_type), so they are only stored for cos.
        if at == "cos":
            for tag, row in (("rot1", self._ang_rot1),
                             ("rot2", self._ang_rot2)):
                v = row.value()
                if v != dict(gps.ROT_AXES)[tag]:
                    an[tag] = {"x": v[0], "y": v[1], "z": v[2]}
        return {"particle": p, "number": 1, "energy": en,
                "position": ps, "angular": an}

    # -------------------------------------------------------- user data ----

    def _import_user_spectrum(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load spectrum", "", "Spectrum (*.txt *.dat *.csv);;All (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return
        pts = gps.parse_spectrum_text(text)
        if not pts:
            return
        self._user_data = [list(x) for x in pts]
        self._update_user_info()
        self._refresh_preview()

    def _update_user_info(self):
        d = self._user_data
        if not d:
            self._user_info.setText("no spectrum loaded")
            return
        es = [x[0] for x in d]
        self._user_info.setText(
            f"{len(d)} points, E {es[0]:g}\u2013{es[-1]:g} MeV")

    # ------------------------------------------------------ mode / state ---

    def _click_mode(self, mode):
        # clicking the active mode again returns to the empty state; values
        # already entered on a page are kept for the next visit (never
        # overwritten by a second seeding pass)
        old = self._mode
        if self._mode == mode:
            self._mode = None
        else:
            if mode == "gun" and not self._gun_ready:
                self._populate_gun()
                self._gun_ready = True
            elif mode == "gps" and not self._gps_ready:
                self._populate_gps()
                self._gps_ready = True
            self._mode = mode
        if old != self._mode and self._preview_win is not None:
            # gun and gps previews are different windows; never keep the
            # previous mode's sketch on screen after a mode change.
            try:
                self._preview_win.close()
            except Exception:
                pass
            self._preview_win = None
        self._apply_state()

    def _apply_state(self):
        self._hint.setVisible(self._mode is None)
        self._gun_page.setVisible(self._mode == "gun")
        self._gps_page.setVisible(self._mode == "gps")
        self._file_page.setVisible(self._mode == "file")
        self._btn_save.setEnabled(self._mode is not None)
        self._btn_3d.setEnabled(self._mode in ("gun", "gps"))
        if self._mode not in ("gun", "gps") and self._preview_win is not None:
            try:
                self._preview_win.close()
            except Exception:
                pass
            self._preview_win = None
        # Right side: generated macro (read-only) in the form modes, plain
        # editable text buffer in import-file mode.
        if self._mode == "file":
            self._preview.setReadOnly(False)
            self._sync_file_editor()
        else:
            self._preview.setReadOnly(True)
        self._style_mode_buttons()
        self._refresh_preview()

    def _sync_file_editor(self):
        """Push the held raw text into the preview box (file mode only).
        setPlainText is not a user edit, so its textChanged must be ignored:
        block the signal while writing."""
        self._preview.blockSignals(True)
        self._preview.setPlainText(self._file_text)
        self._preview.blockSignals(False)
        c = self._preview.textCursor()
        c.movePosition(c.MoveOperation.Start)
        self._preview.setTextCursor(c)

    def _on_preview_edited(self):
        """Keystrokes / paste inside the editable preview (file mode): keep
        the held raw text in sync so edits survive a mode switch."""
        if self._mode == "file":
            self._file_text = self._preview.toPlainText()

    def _style_mode_buttons(self):
        on = (f"background:{self._acc};color:#fff;border:1px solid "
              f"{self._acc};border-radius:6px;padding:5px 16px;"
              f"font-weight:bold;")
        off = ("background:transparent;")   # default push-button look wins
        for b, m in ((self._btn_gun, "gun"), (self._btn_gps, "gps"),
                     (self._btn_file, "file")):
            b.setStyleSheet(on if self._mode == m else off)

    def _load_existing(self):
        cfg = (self._task.particle if self._task is not None else None)
        if cfg:
            self._populate_gun(cfg)
            self._populate_gps(cfg)
            self._gun_ready = True
            self._gps_ready = True
            mode = cfg.get("mode", "gps" if cfg.get("energy") else "gun")
            if mode == "file":
                self._file_text = cfg.get("raw") or ""
                self._file_name = cfg.get("file_name") or ""
                n = len([ln for ln in self._file_text.splitlines()
                         if ln.strip()])
                self._file_loaded.setText(
                    (self._file_name or "imported macro")
                    + f"  ({n} lines)")
            self._mode = mode
            self._apply_state()
        # else: calm blank state until the user picks a mode

    # ------------------------------------------------------------ collect --

    def _collect(self):
        if self._mode is None:
            return None
        gun = self._collect_gun()
        gps_part = self._collect_gps()
        if self._mode == "gun":
            p = dict(gun["particle"])
        else:
            p = dict(gps_part["particle"])
        cfg = {"unit": "mm", "mode": self._mode, "gun": gun,
               "particle": p, "number": gps_part["number"],
               "energy": gps_part["energy"], "position": gps_part["position"],
               "angular": gps_part["angular"]}
        if self._mode == "file":
            # The source is the raw text in the editable preview.  The gun /
            # GPS copies above stay in the dict only so the saved project has
            # the same overall shape in every mode; macro_lines("file")
            # ignores them and returns cfg["raw"] verbatim.
            cfg["mode"] = "file"
            cfg["raw"] = self._preview.toPlainText()
            cfg["file_name"] = self._file_name
        return cfg

    # ------------------------------------------------------------ preview --

    def _open_3d_preview(self):
        """Open (or raise) the live 3D sketch window for the current source.

        The gun and the GPS modes share one preview style (translucent scene,
        corner axes, live refresh) but show different content; see
        gun_direction_preview.py / gps_direction_preview.py."""
        if self._mode not in ("gun", "gps"):
            return
        if self._preview_win is not None:
            try:
                self._preview_win.raise_()
                self._preview_win.activateWindow()
            except Exception:
                self._preview_win = None
            if self._preview_win is not None:
                return
        try:
            if self._mode == "gun":
                from ui.dialogs.gun_direction_preview import GunDirectionPreview
                cls = GunDirectionPreview
            else:
                from ui.dialogs.gps_direction_preview import GPSDirectionPreview
                cls = GPSDirectionPreview
            self._preview_win = cls(self, dark=self._dark, parent=None)
            self._preview_win.destroyed.connect(self._preview_closed)
        except Exception:
            self._preview_win = None

    def _preview_closed(self):
        self._preview_win = None

    def _refresh_preview(self):
        if not hasattr(self, "_preview"):
            return
        if self._mode == "file":
            return    # the box is the live editable buffer, never rewritten
        cfg = self._collect()
        if cfg is None:
            self._preview.setPlainText(
                "# (empty)\n# Select ParticleGun, GeneralParticleSource or "
                "Import file above to configure.")
        else:
            lines = gps.macro_lines(cfg)
            self._preview.setPlainText("\n".join(lines) or "# (empty)")
        c = self._preview.textCursor()
        c.movePosition(c.MoveOperation.Start)
        self._preview.setTextCursor(c)

    def closeEvent(self, event):
        if self._preview_win is not None:
            try:
                self._preview_win.close()
            except Exception:
                pass
            self._preview_win = None
        super().closeEvent(event)

    # ------------------------------------------------------- validation ----

    def _check_energy_range(self, cfg):
        """Return an error text when the active spectrum carries an inverted
        E min / E max pair, else None. Only checked on Save so editing the two
        fields in any order never pops up a window mid-edit."""
        if self._mode != "gps":
            return None
        en = cfg.get("energy") or {}
        mn, mx = en.get("e_min"), en.get("e_max")
        if mn is None or mx is None:
            return None
        if float(mn) > float(mx):
            return (f"Energy spectrum: E min ({mn:g} MeV) is larger than "
                    f"E max ({mx:g} MeV).\nE min must not exceed E max.")
        return None

    def _focus_energy_row(self, keys):
        """Focus the first visible E min / E max row of the active spectrum."""
        t = self._ene_cb.currentData() if hasattr(self, "_ene_cb") else None
        for k, fr in self._ene_rows.get(t, []):
            if k in keys:
                fr.focus_input()
                break

    def _save(self):
        if self._task is None:
            self.close()
            return
        cfg = self._collect()
        if cfg is None:
            self.close()
            return
        err = self._check_energy_range(cfg)
        if err:
            QMessageBox.warning(self, "Invalid Energy Range", err)
            self._focus_energy_row(("e_min", "e_max"))
            return
        if self._mode == "file" and not (cfg.get("raw") or "").strip():
            QMessageBox.warning(
                self, "Empty Macro",
                "The imported macro text is empty.\nImport a .mac / text "
                "file or type the commands before saving.")
            return
        self._task.particle = cfg
        try:
            from app.main_window import MainWindow
            if isinstance(self.parent(), MainWindow):
                self.parent().on_particle_saved(self._task.name, True)
        except Exception:
            pass
        self.close()

    # -------------------------------------------------------------- theme --

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        self._apply_theme(dark)

    def _apply_theme(self, dark):
        self._dark = dark
        self._acc = "#89b4fa" if dark else "#0078d4"
        self.setStyleSheet(DIALOG_STYLE(dark))
        self._apply_titles()
        extra = (f"QPlainTextEdit {{ background-color:#181825; color:#cdd6f4;"
                 f"border:1px solid #45475a; border-radius:6px; }}")
        if not dark:
            extra = (f"QPlainTextEdit {{ background-color:#ffffff;"
                     f"color:#2c2c2c; border:1px solid #d0d0d0;"
                     f"border-radius:6px; }}")
        self._preview.setStyleSheet(extra)
        self._btn_save.setStyleSheet(
            f"background:{self._acc};color:#fff;border:1px solid {self._acc};"
            f"border-radius:6px;padding:5px 16px;font-weight:bold;")
        self._btn_cancel.setStyleSheet("")
        self._style_mode_buttons()
