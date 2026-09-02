"""
CalculateSettingDialog — task calculation settings (thread count, etc.).

Corresponds to the "Calculate Setting" child node under a task node in the
project tree.
Thread count: 0 = unassigned (it can be split evenly across CPU cores on Run).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
)
from PyQt6.QtCore import Qt


class CalculateSettingDialog(QDialog):

    def __init__(self, parent=None, task_name: str = "", n_threads: int = 0):
        super().__init__(parent)
        self._dark = False
        self._cpu_count = os.cpu_count() or 4

        self.setWindowTitle("Calculate Setting")
        self.setMinimumWidth(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(f"Calculation settings - {task_name}")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Thread count (CPU cores):"))
        self._spin = QSpinBox()
        self._spin.setRange(1, self._cpu_count)
        self._spin.setValue(n_threads if n_threads > 0 else self._cpu_count)
        row.addWidget(self._spin)
        row.addStretch()
        layout.addLayout(row)

        hint = QLabel(
            f"CPU cores on this machine: {self._cpu_count}.\n"
            "If you choose \"auto-split by CPU cores\" when running, it overrides the value here.")
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def get_n_threads(self) -> int:
        return self._spin.value()

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        if dark:
            self.setStyleSheet("""
                QDialog { background-color: #1e1e2e; }
                QLabel { color: #cdd6f4; font-size: 12px; }
                QSpinBox {
                    background-color: #313244; color: #cdd6f4;
                    border: 1px solid #45475a; border-radius: 4px;
                    padding: 3px 6px; font-size: 12px;
                }
                QPushButton {
                    background-color: #313244; color: #cdd6f4;
                    border: 1px solid #45475a; border-radius: 6px;
                    padding: 6px 18px; font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #45475a; border: 1px solid #89b4fa;
                }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #f5f5f5; }
                QLabel { color: #2c2c2c; font-size: 12px; }
                QSpinBox {
                    background-color: #ffffff; color: #2c2c2c;
                    border: 1px solid #d0d0d0; border-radius: 4px;
                    padding: 3px 6px; font-size: 12px;
                }
                QPushButton {
                    background-color: #f0f0f0; color: #2c2c2c;
                    border: 1px solid #d0d0d0; border-radius: 6px;
                    padding: 6px 18px; font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #e4e7eb; border: 1px solid #0078d4;
                }
            """)
