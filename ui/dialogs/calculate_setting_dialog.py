"""
CalculateSettingDialog — task calculation settings (thread count, etc.).

Corresponds to the "Calculate Setting" child node under a task node in the
project tree.
Thread count: 0 = unassigned (it can be split evenly across CPU cores on Run).

Non-modal and cached per task by the main window (mirrors ParticleDialog):
saving writes task.calculate.n_threads, notifies the parent MainWindow
(on_calculate_saved) and closes the window.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QSpinBox,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.mac_builder import DEFAULT_EVENTS


class CalculateSettingDialog(QDialog):

    close_requested = pyqtSignal()

    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self._task = task
        self._task_name = getattr(task, "name", "") or ""
        calc = getattr(task, "calculate", None)
        n_threads = calc.n_threads if calc else 0
        n_events = calc.n_events if calc else 0
        self._dark = False
        self._cpu_count = os.cpu_count() or 4

        self.setWindowTitle("Calculate Setting")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(f"Calculation settings - {self._task_name}")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        # Label column stretches, so both fixed-width spin boxes sit flush
        # right and share one width -> a clean right-aligned input column.
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Thread count (CPU cores):"), 0, 0)
        self._spin = QSpinBox()
        self._spin.setRange(1, self._cpu_count)
        self._spin.setValue(n_threads if n_threads > 0 else self._cpu_count)
        grid.addWidget(self._spin, 0, 1)

        grid.addWidget(QLabel("Number of events (/run/beamOn):"), 1, 0)
        self._events = QSpinBox()
        self._events.setRange(0, 100_000_000)
        self._events.setSingleStep(1000)
        self._events.setValue(n_events)
        # 0 -> auto: mac_builder falls back to its DEFAULT_EVENTS
        self._events.setSpecialValueText(f"{DEFAULT_EVENTS}")
        grid.addWidget(self._events, 1, 1)

        grid.setColumnStretch(0, 1)
        for spin in (self._spin, self._events):
            spin.setFixedWidth(200)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addLayout(grid)

        hint = QLabel(
            f"CPU cores on this machine: {self._cpu_count}.\n"
            "If you choose \"auto-split by CPU cores\" when running, it overrides the value here.\n"
            "Events (0 = auto): the number after /run/beamOn in the generated run.mac.\n"
            "It also shows live in the right-side \"Run Macro Preview\" panel.")
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch()
        save = QPushButton("Save to Task")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        btns.addWidget(save)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def _save(self):
        """Write n_threads and n_events back to the CURRENT task object and
        notify the parent MainWindow, then close (WA_DeleteOnClose lets the
        main window clear its cache).

        The task is re-fetched by name so the save always lands on the object
        the run manager / macro preview actually use - even if the tasks were
        rebuilt (import GDML / load project) while this dialog stayed open."""
        parent = self.parent()
        task = self._task
        try:
            rm = getattr(parent, "_run_manager", None)
            if rm is not None:
                task = rm.get_task(self._task_name) or task
        except Exception:
            pass
        if task is None:
            self.close()
            return
        task.calculate.n_threads = self._spin.value()
        task.calculate.n_events = self._events.value()
        try:
            if parent is not None and hasattr(parent, "on_calculate_saved"):
                parent.on_calculate_saved(self._task_name, True)
        except Exception:
            pass
        self.close()

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
