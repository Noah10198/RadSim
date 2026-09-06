"""
SolverSettingDialog - configure the solver executable and its Qt runtime.

Non-modal dialog opened by the "Solver Setting" toolbar button. Both paths are
persisted through QSettings (see core/solver_config.py); when left empty they
fall back to the automatically detected repository / Qt6 paths.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog,
)
from PyQt6.QtCore import Qt

from core.solver_config import (
    get_qt_bin_dir, get_solver_path, set_qt_bin_dir, set_solver_path)


class SolverSettingDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Solver Setting")
        self.setMinimumWidth(620)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Solver executable path")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setText(get_solver_path())
        self._path_edit.setPlaceholderText("rad4space.exe (or the equivalent name)")
        row.addWidget(self._path_edit, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._info)

        qt_title = QLabel("Qt runtime bin (optional)")
        qt_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        qt_title.setToolTip(
            "The solver is a Geant4 app linking the Qt6 DLLs of the Qt it was "
            "built against. When the GUI runs from a conda python, its older "
            "Qt DLLs hijack the solver and it exits with 0xC0000135/0xC0000139. "
            "Point here to the machine-wide Qt bin that matches the solver.")
        layout.addWidget(qt_title)

        qt_row = QHBoxLayout()
        self._qt_edit = QLineEdit()
        self._qt_edit.setText(get_qt_bin_dir())
        self._qt_edit.setPlaceholderText("…\\msvc2022_64\\bin (Qt6 DLLs)")
        qt_row.addWidget(self._qt_edit, 1)

        qt_browse_btn = QPushButton("Browse…")
        qt_browse_btn.clicked.connect(self._on_browse_qt)
        qt_row.addWidget(qt_browse_btn)
        layout.addLayout(qt_row)

        self._qt_info = QLabel("")
        self._qt_info.setWordWrap(True)
        self._qt_info.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._qt_info)

        note = QLabel(
            "Empty fields fall back to the auto-detected paths. Publishing "
            "tip: copy the solver's Qt/Geant4 DLLs next to rad4space.exe and "
            "this Qt setting becomes unnecessary.")
        note.setStyleSheet("color: #6c7086; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        save_btn = QPushButton("✅ Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

        self._path_edit.textChanged.connect(self._update_info)
        self._qt_edit.textChanged.connect(self._update_info)
        self._update_info()

    def _on_browse(self):
        if os.name == "nt":
            filt = "Executable (*.exe);;All files (*.*)"
        else:
            filt = "Executable (*);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the solver executable", self._path_edit.text(), filt)
        if path:
            self._path_edit.setText(path)

    def _on_browse_qt(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select the Qt runtime (bin) directory",
            self._qt_edit.text() or os.path.expanduser("~"))
        if path:
            self._qt_edit.setText(path)

    def _update_info(self):
        path = self._path_edit.text().strip()
        if path and os.path.isfile(path):
            self._info.setText("✓ File exists")
        elif path:
            self._info.setText("File not found at this path yet.")
        else:
            self._info.setText(
                "Empty: falls back to the automatically detected path under "
                "solver/rad4space/build.")

        qt = self._qt_edit.text().strip()
        if qt:
            if os.path.isdir(qt) and os.path.isfile(
                    os.path.join(qt, "Qt6Core.dll")):
                self._qt_info.setText("✓ Qt6Core.dll found here")
            elif os.path.isdir(qt):
                self._qt_info.setText("Directory exists (Qt6Core.dll not in it).")
            else:
                self._qt_info.setText("Directory not found yet.")
        else:
            self._qt_info.setText(
                "Empty: falls back to the auto-detected Qt6 bin. Set it when "
                "the solver links another Qt than this GUI's python.")

    def _save(self):
        set_solver_path(self._path_edit.text().strip())
        set_qt_bin_dir(self._qt_edit.text())
        self.close()

    def set_dark_theme(self, dark: bool):
        self._apply_style(dark)

    def _apply_style(self, dark: bool = False):
        if dark:
            bg, fg, field, border, btn = (
                "#1e1e2e", "#cdd6f4", "#11111b", "#45475a", "#313244")
        else:
            bg, fg, field, border, btn = (
                "#f5f5f5", "#2c2c2c", "#ffffff", "#d0d0d0", "#f0f0f0")
        self.setStyleSheet(f"""
            QDialog {{ background-color: {bg}; }}
            QLabel {{ color: {fg}; font-size: 12px; }}
            QLineEdit {{
                background-color: {field}; color: {fg};
                border: 1px solid {border}; border-radius: 4px;
                padding: 5px 8px; font-size: 12px;
            }}
            QPushButton {{
                background-color: {btn}; color: {fg};
                border: 1px solid {border}; border-radius: 6px;
                padding: 6px 18px; font-size: 12px;
            }}
            QPushButton:hover {{ border: 1px solid #0078d4; }}
        """)
