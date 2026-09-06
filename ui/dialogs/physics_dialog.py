"""
PhysicsProcessDialog - configure the physics process of a RunTask.

Edits a dict (ui/dialogs/physics_config.py schema) that will be turned into
the PreInit physics block of the rad4space run macro. The dialog also shows a
live preview of that macro block and a human-readable summary of the selected
reference physics list (model set, particle coverage, caveats).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                             QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QSplitter, QVBoxLayout, QWidget)

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


class PhysicsDialog(QDialog):
    """Modal editor for task.physics (pure QDialog, used with exec())."""

    def __init__(self, parent=None, task_name: str = "", config=None):
        super().__init__(parent)
        self._task_name = task_name
        self._cfg = pc.sanitize(config)
        self.setWindowTitle("Physics Process")
        self.setModal(True)
        self._build_ui()
        self._refresh()
        fit_size_to_screen(self, 920, 600)

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        head = QLabel("Physics Process" if not self._task_name
                      else f"Physics Process - {self._task_name}")
        head.setObjectName("dialogTitle")
        root.addWidget(head)

        sub = QLabel("Select the Geant4 reference physics list - it defines "
                     "which physical processes are built (EM, hadronic "
                     "cascades/strings, decay) and thus which particle types "
                     "exist in the simulation.")
        sub.setWordWrap(True)
        root.addWidget(sub)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # ---- left: form
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)
        lv.setSpacing(6)

        g1 = QGroupBox("Reference physics list")
        gv = QVBoxLayout(g1)
        self._pl_combo = QComboBox()
        for key, models, _ in pc.REFERENCE_LISTS:
            self._pl_combo.addItem(f"{key}  -  {models}", key)
        idx = self._pl_combo.findData(self._cfg["physics_list"])
        self._pl_combo.setCurrentIndex(max(idx, 0))
        self._pl_combo.currentIndexChanged.connect(self._on_change)
        gv.addWidget(self._pl_combo)

        self._info_lbl = QLabel()
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setAlignment(Qt.AlignmentFlag.AlignTop |
                                    Qt.AlignmentFlag.AlignLeft)
        self._info_lbl.setMinimumHeight(150)
        gv.addWidget(self._info_lbl)

        self._hp_chk = QCheckBox("Add high-precision neutron models (HP, "
                                 "<20 MeV ENDF cross-sections)")
        self._hp_chk.setToolTip(
            "Writes /rad4space/physics/AddHP true - the solver appends '_HP' "
            "to the list name. Greyed out for lists that already ship HP.")
        self._rdm_chk = QCheckBox("Add radioactive decay (RDM) - activation "
                                  "products decay via beta/alpha chains")
        self._rdm_chk.setToolTip(
            "Registers G4RadioactiveDecayPhysics. No effect with Shielding.")
        self._hp_chk.toggled.connect(self._refresh)
        self._rdm_chk.toggled.connect(self._refresh)
        gv.addWidget(self._hp_chk)
        gv.addWidget(self._rdm_chk)
        lv.addWidget(g1)

        g2 = QGroupBox("Production cuts & step limit")
        g2v = QVBoxLayout(g2)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Global production cut"))
        self._cut = QDoubleSpinBox()
        self._cut.setRange(0.0, 100.0)
        self._cut.setDecimals(4)
        self._cut.setSingleStep(0.1)
        self._cut.setValue(self._cfg["global_cut_mm"])
        self._cut.setSuffix(" mm")
        self._cut.setToolTip(pc.CUT[4])
        self._cut.valueChanged.connect(self._refresh)
        row1.addWidget(self._cut, 1)
        g2v.addLayout(row1)
        cut_hint = QLabel(pc.CUT[4])
        cut_hint.setWordWrap(True)
        g2v.addWidget(cut_hint)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Max step length"))
        self._step = QDoubleSpinBox()
        self._step.setRange(0.0, 100000.0)
        self._step.setDecimals(3)
        self._step.setSingleStep(1.0)
        self._step.setValue(self._cfg["max_step_mm"])
        self._step.setSuffix(" mm")
        self._step.setToolTip(pc.STEP[4] + " 0 = no limit.")
        self._step.valueChanged.connect(self._refresh)
        row2.addWidget(self._step, 1)
        g2v.addLayout(row2)
        step_hint = QLabel(pc.STEP[4])
        step_hint.setWordWrap(True)
        g2v.addWidget(step_hint)
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
        note = QLabel("All commands must appear before /run/initialize. "
                      "FTFP_BERT / 0.7 mm is already the solver default, so "
                      "an empty configuration is valid too.")
        note.setWordWrap(True)
        rv.addWidget(note)
        split.addWidget(right)
        split.setSizes([500, 400])

        # ---- footer
        foot = QHBoxLayout()
        foot.addStretch(1)
        self._ok_btn = QPushButton("Save")
        self._ok_btn.setObjectName("primaryButton")
        self._ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        foot.addWidget(self._ok_btn)
        foot.addWidget(cancel_btn)
        root.addLayout(foot)

    # ------------------------------------------------------------- logic
    def _pl_key(self):
        return self._pl_combo.currentData()

    def _on_change(self):
        key = self._pl_key()
        # lists with built-in HP neutrons cannot take AddHP
        hp_ok = pc.supports_hp(key)
        rdm_ok = pc.supports_rdm(key)
        self._hp_chk.setEnabled(hp_ok)
        if not hp_ok:
            self._hp_chk.setChecked(False)
        self._rdm_chk.setEnabled(rdm_ok)
        if not rdm_ok:
            self._rdm_chk.setChecked(False)
        self._refresh()

    def _refresh(self):
        key = self._pl_key()
        self._info_lbl.setText(pc.summary_text(key))
        cfg = self.get_config()
        if cfg["add_hp"] and not pc.supports_hp(key):
            cfg["add_hp"] = False
        if cfg["add_rdm"] and not pc.supports_rdm(key):
            cfg["add_rdm"] = False
        self._preview.setPlainText(pc.macro_preview(cfg))

    def get_config(self):
        return {
            "physics_list": self._pl_key(),
            "add_hp": self._hp_chk.isChecked(),
            "add_rdm": self._rdm_chk.isChecked(),
            "global_cut_mm": round(self._cut.value(), 4),
            "max_step_mm": round(self._step.value(), 3),
        }

    # ------------------------------------------------------------- theme
    def set_dark_theme(self, dark: bool):
        self.setStyleSheet(DIALOG_STYLE(dark))
        self._preview.setStyleSheet(_PLAINTEXT_STYLE[bool(dark)])
