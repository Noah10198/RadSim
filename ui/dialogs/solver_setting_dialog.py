"""
SolverSettingDialog - configure the path of the solver executable.

Non-modal dialog opened by the "Solver Setting" toolbar button. The path is
persisted through QSettings (see core/solver_config.py); when left empty the
dialog falls back to the automatically detected repository path.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog,
)
from PyQt6.QtCore import Qt

from core.solver_config import get_solver_path, set_solver_path


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

        note = QLabel(
            "The solver is invoked per task as:\n"
            "    <solver> <task script> [thread count]\n"
            "The executable name / final location may still change later.")
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

    def _save(self):
        set_solver_path(self._path_edit.text().strip())
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
