"""
MacPreviewDock - right-dock widget showing the assembled run.mac for a task.

The MainWindow owns the data: it picks a task (via the combo box), renders the
mac text with core.mac_builder.build_mac_text() (the exact same function used
to write each task's run.mac before the solver launch) and pushes the result
here with set_text().

This widget is intentionally dumb (no imports of core/…): it only renders.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPlainTextEdit,
)


class MacPreviewDock(QWidget):

    # emitted when the user picks another task in the header combo
    task_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._task_label = QLabel("Task:")
        self._combo = QComboBox()
        self._combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumWidth(140)
        self._combo.currentTextChanged.connect(self._on_task_selected)
        head.addWidget(self._task_label)
        head.addWidget(self._combo, 1)
        layout.addLayout(head)

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._edit.setObjectName("MacPreviewText")
        self._edit.setPlaceholderText(
            "No run macro yet.\n\n"
            "Import a GDML and pick a task to preview the exact run.mac\n"
            "that will be handed to rad4space when you press Run.")
        layout.addWidget(self._edit, 1)

    # ---- task list management ----

    def sync_tasks(self, names) -> None:
        """Refresh the combo items to match the current task names, keeping
        the current selection when it still exists."""
        current = self._combo.currentText()
        # block signals so repopulation does not trigger spurious refreshes
        self._combo.blockSignals(True)
        self._combo.clear()
        for n in names:
            self._combo.addItem(n)
        if current in names:
            self._combo.setCurrentText(current)
        self._combo.blockSignals(False)

    def current_task(self) -> str:
        return self._combo.currentText() or None

    def select_task(self, task_name: str) -> None:
        if task_name and task_name != self._combo.currentText():
            self._combo.setCurrentText(task_name)
        # currentTextChanged fires only on real changes; emit anyway so callers
        # that select an already-selected task still get a refresh
        if task_name:
            self._on_task_selected(task_name)

    def task_count(self) -> int:
        return self._combo.count()

    # ---- content ----

    def set_text(self, text: str) -> None:
        self._edit.setPlainText(text)

    def set_placeholder(self, text: str) -> None:
        self._edit.setPlainText(text)

    # ---- internals ----

    def _on_task_selected(self, task_name: str) -> None:
        if task_name:
            self.task_changed.emit(task_name)

    def set_dark_theme(self, dark: bool) -> None:
        self._dark = dark
        if dark:
            self.setStyleSheet(
                "QLabel { color: #a6adc8; font-size: 12px; }"
                "QComboBox { background-color: #313244; color: #cdd6f4;"
                " border: 1px solid #45475a; border-radius: 4px;"
                " padding: 2px 6px; font-size: 12px; }"
                "QComboBox QAbstractItemView { background-color: #313244;"
                " color: #cdd6f4; selection-background-color: #45475a; }"
                "#MacPreviewText { background-color: #11111b; color: #cdd6f4;"
                " font-family: \"Consolas\", \"Courier New\", monospace;"
                " font-size: 12px; border: 1px solid #313244;"
                " border-radius: 4px; padding: 4px;"
                " selection-background-color: #45475a; }")
        else:
            self.setStyleSheet(
                "QLabel { color: #555555; font-size: 12px; }"
                "QComboBox { background-color: #ffffff; color: #2c2c2c;"
                " border: 1px solid #d0d0d0; border-radius: 4px;"
                " padding: 2px 6px; font-size: 12px; }"
                "QComboBox QAbstractItemView { background-color: #ffffff;"
                " color: #2c2c2c; selection-background-color: #e0f0ff; }"
                "#MacPreviewText { background-color: #fafafa; color: #1f2328;"
                " font-family: \"Consolas\", \"Courier New\", monospace;"
                " font-size: 12px; border: 1px solid #d0d0d0;"
                " border-radius: 4px; padding: 4px;"
                " selection-background-color: #cde5ff; }")
