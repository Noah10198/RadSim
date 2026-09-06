"""
PhysicsProcessDialog - configure the physics process of a RunTask.

Edits a dict (ui/dialogs/physics_config.py schema) that will be turned into
the PreInit physics block of the rad4space run macro. The dialog also shows a
live preview of that macro block and a human-readable summary of the selected
reference physics list (model set, particle coverage, caveats).

Because the solver selects the physics list with a SINGLE G4PhysListFactory
name (e.g. QGSP_BIC_HP, Shielding_EMY, FTFP_BERT_EMZ), the list control is an
editable combo box: it offers the curated space-radiation names and lets the
user type any other valid reference-list name (with incremental filtering).
The AddHP / AddRDM toggles are kept but are only meaningful for base names that
do not already carry that feature - when they are incompatible a red hint
explains that the solver would drop them.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog,
                             QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel,
                             QPlainTextEdit, QPushButton, QSplitter,
                             QVBoxLayout, QWidget)

from ui.dialogs.analysis_common import DIALOG_STYLE, fit_size_to_screen
from ui.dialogs import physics_config as pc

# dark/light QSS blocks for QPlainTextEdit (DIALOG_STYLE has no rule for it)
_PLAINTEXT_STYLE = {
    True: "QPlainTextEdit{background:#10141c;color:#e2e8f0;"
          "border:1px solid #2c3a4f;border-radius:4px;"
          "selection-background-color:#2d6a9f;padding:4px;}",
    False: "QPlainTextEdit{background:#ffffff;color:#1a2733;"
           "border:1px solid #b8c4cf;border-radius:4px;"
           "selection-background-color:#9bc2e3;padding:4px;}",
}

# red "advisory" text appended over the base theme (kept theme-independent)
_WARN_STYLE = {
    True: "QLabel#warnText{color:#ff7b72;background:transparent;}",
    False: "QLabel#warnText{color:#b3261e;background:transparent;}",
}


class PhysicsDialog(QDialog):
    """Non-modal editor for task.physics, cached per task by the main window
    (mirrors ParticleDialog). Saving writes task.physics, notifies the parent
    MainWindow (on_physics_saved) and closes the window."""

    close_requested = pyqtSignal()

    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self._task = task
        self._task_name = getattr(task, "name", "") or ""
        self._cfg = pc.sanitize(getattr(task, "physics", None))
        self.setWindowTitle("Physics Process")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        # restore the saved toggles so the dialog reflects the stored config;
        # an incompatible AddHP/AddRDM then immediately shows the red warning.
        # (Done after _build_ui because each setChecked fires _refresh, which
        # needs every widget - including _warn_lbl and the spin boxes - alive.)
        self._hp_chk.setChecked(bool(self._cfg["add_hp"]))
        self._rdm_chk.setChecked(bool(self._cfg["add_rdm"]))
        self._refresh()
        fit_size_to_screen(self, 940, 560)

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        head = QLabel("Physics Process" if not self._task_name
                      else f"Physics Process - {self._task_name}")
        head.setObjectName("dialogTitle")
        root.addWidget(head)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # ---- left: form
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        lv.setSpacing(6)

        g1 = QGroupBox("Reference physics list (G4PhysListFactory name)")
        gv = QVBoxLayout(g1)

        # editable combo: curated items + free typing with contains-filtering
        self._pl_combo = QComboBox()
        self._pl_combo.setEditable(True)
        self._pl_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._pl_combo.setMaxVisibleItems(14)
        for key, _models, _note in pc.REFERENCE_LISTS:
            self._pl_combo.addItem(key)
        completer = self._pl_combo.completer()
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionPrefix("")
        pl_name = str(self._cfg["physics_list"])
        idx = self._pl_combo.findText(pl_name, Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            self._pl_combo.setCurrentIndex(idx)
        else:
            self._pl_combo.setEditText(pl_name)
        self._pl_combo.currentTextChanged.connect(self._on_change)
        gv.addWidget(self._pl_combo)

        self._info_lbl = QLabel()
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setAlignment(Qt.AlignmentFlag.AlignTop |
                                    Qt.AlignmentFlag.AlignLeft)
        self._info_lbl.setMinimumHeight(90)
        gv.addWidget(self._info_lbl)

        self._hp_chk = QCheckBox("Add high-precision neutron models (HP, "
                                 "<20 MeV ENDF cross-sections)")
        self._hp_chk.setToolTip(
            "Writes /rad4space/physics/AddHP true - the solver appends '_HP' "
            "to the base list name. Meaningless for names that already end in "
            "_HP/_HPT or are in the Shielding family (they carry HP already).")
        self._rdm_chk = QCheckBox("Add radioactive decay (RDM) - activation "
                                  "products decay via beta/alpha chains")
        self._rdm_chk.setToolTip(
            "Registers G4RadioactiveDecayPhysics. Shielding family and every "
            "_HP list already decay activation products, so AddRDM is then "
            "dropped.")
        self._hp_chk.toggled.connect(self._refresh)
        self._rdm_chk.toggled.connect(self._refresh)
        gv.addWidget(self._hp_chk)
        gv.addWidget(self._rdm_chk)

        self._warn_lbl = QLabel()
        self._warn_lbl.setObjectName("warnText")
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setVisible(False)
        gv.addWidget(self._warn_lbl)
        lv.addWidget(g1)

        g2 = QGroupBox("Production cuts & step limit")
        g2v = QVBoxLayout(g2)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Global production cut"))
        self._cut = QDoubleSpinBox()
        self._cut.setRange(0.0, 100.0)
        self._cut.setDecimals(4)
        self._cut.setSingleStep(0.1)
        self._cut.setValue(float(self._cfg["global_cut_mm"]))
        self._cut.setSuffix(" mm")
        self._cut.setToolTip(pc.CUT[4])
        self._cut.valueChanged.connect(self._refresh)
        row1.addWidget(self._cut, 1)
        g2v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Max step length"))
        self._step = QDoubleSpinBox()
        self._step.setRange(0.0, 100000.0)
        self._step.setDecimals(3)
        self._step.setSingleStep(1.0)
        self._step.setValue(float(self._cfg["max_step_mm"]))
        self._step.setSuffix(" mm")
        self._step.setToolTip(pc.STEP[4] + " 0 = no limit.")
        self._step.valueChanged.connect(self._refresh)
        row2.addWidget(self._step, 1)
        g2v.addLayout(row2)
        lv.addWidget(g2)
        lv.addStretch(1)
        split.addWidget(left)

        # ---- right: macro preview
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)
        rv.setSpacing(6)
        pv_t = QLabel("run.mac physics block (PreInit)")
        pv_t.setObjectName("dialogTitle")
        rv.addWidget(pv_t)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(QFont("Consolas", 10))
        self._preview.setMinimumWidth(360)
        rv.addWidget(self._preview, 1)
        split.addWidget(right)
        split.setSizes([520, 420])

        # ---- footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self._ok_btn = QPushButton("Save to Task")
        self._ok_btn.setObjectName("primaryButton")
        self._ok_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.close)
        foot.addWidget(self._ok_btn)
        foot.addWidget(cancel_btn)
        root.addLayout(foot)

    # ------------------------------------------------------------- logic
    def _pl_name(self):
        """Current name in the editable field (whitespace trimmed)."""
        return self._pl_combo.currentText().strip()

    def _on_change(self):
        # keep typed custom names; when the typed text matches a curated item
        # exactly, snap the combo so the user can see the model summary too
        self._refresh()

    def _refresh(self):
        name = self._pl_name()
        # short on-screen text (models + note); the fuller particle-coverage
        # explanation shows when the mouse hovers over the list combo box
        self._info_lbl.setText(pc.line_summary(name))
        self._pl_combo.setToolTip(pc.hover_text(name))

        cfg = self.get_config()

        # red advisory: list which toggles would be dropped for this name
        warns = pc.warnings(name, cfg["add_hp"], cfg["add_rdm"])
        if warns:
            self._warn_lbl.setText("<br>".join(warns))
            self._warn_lbl.setVisible(True)
        else:
            self._warn_lbl.clear()
            self._warn_lbl.setVisible(False)

        self._preview.setPlainText(pc.macro_preview(cfg))

    def get_config(self):
        name = self._pl_name()
        return {
            "physics_list": name,
            "add_hp": self._hp_chk.isChecked(),
            "add_rdm": self._rdm_chk.isChecked(),
            "global_cut_mm": round(self._cut.value(), 4),
            "max_step_mm": round(self._step.value(), 3),
        }

    def _save(self):
        """Write the config to the task, notify the parent MainWindow so it can
        refresh the tree node, then close (WA_DeleteOnClose destroys the dialog,
        which the main window uses to clear its cache - same as ParticleDialog)."""
        if self._task is None:
            self.close()
            return
        self._task.physics = self.get_config()
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "on_physics_saved"):
                parent.on_physics_saved(self._task_name, True)
        except Exception:
            pass
        self.close()

    # ------------------------------------------------------------- theme
    def set_dark_theme(self, dark: bool):
        self.setStyleSheet(DIALOG_STYLE(dark) + _WARN_STYLE[bool(dark)])
        self._preview.setStyleSheet(_PLAINTEXT_STYLE[bool(dark)])
