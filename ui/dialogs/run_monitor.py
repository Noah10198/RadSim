"""
Run launcher + task monitor dialogs (two independent windows).

Design agreed with the user:
  - "Run" toolbar button  -> RunMonitorDialog  : slim launcher. Rows carry a
    checkbox (select tasks), two columns (task name / status). A "Run
    Selected" button sits at the top right and is greyed out while any task is
    running, so repeated clicks cannot double-start tasks. No progress bars,
    no run log, no select-all row.
  - "Idle" toolbar button -> TaskMonitorDialog : per-task rows with checkbox,
    status, a progress bar while running, a per-row "cancel" button and a
    "Run Selected" / "Stop All" pair at the top right. No run log, no
    select-all row.
Both dialogs are non-modal and are driven by RunManager signals.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QFrame, QWidget, QScrollArea, QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor

STATUS_META = {
    "idle":      ("⏸", "Idle",      QColor("#808080")),
    "queued":    ("⏳", "Queued",    QColor("#b58900")),
    "running":   ("🔄", "Running",   QColor("#0078d4")),
    "completed": ("✅", "Completed", QColor("#2e8b57")),
    "failed":    ("❌", "Failed",    QColor("#c0392b")),
    "stopped":   ("⏹", "Stopped",   QColor("#c0392b")),
}


def _status_text(status: str) -> str:
    emoji, label, _color = STATUS_META.get(status, STATUS_META["idle"])
    return f"{emoji} {label}"


def _status_color(status: str) -> QColor:
    return STATUS_META.get(status, STATUS_META["idle"])[2]


def _styles(dark: bool) -> str:
    """Shared stylesheet for both dialogs (light theme by default)."""
    if dark:
        return """
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; font-size: 12px; }
            QCheckBox { color: #cdd6f4; font-size: 12px; }
            QTreeWidget {
                background-color: #11111b; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 6px;
                font-size: 12px;
            }
            QTreeWidget::item { height: 24px; }
            QTreeWidget::item:selected {
                background-color: #313244; color: #cdd6f4;
            }
            QHeaderView::section {
                background-color: #313244; color: #cdd6f4;
                border: none; border-right: 1px solid #45475a;
                border-bottom: 1px solid #45475a;
                padding: 4px 6px; font-size: 12px;
            }
            QScrollArea { background-color: #1e1e2e; border: none; }
            #TaskRowsContainer { background-color: #1e1e2e; }
            QProgressBar {
                background-color: #1e1e2e; color: #cdd6f4;
                border: none; border-radius: 4px;
                text-align: center; font-size: 11px;
            }
            QProgressBar::chunk { background-color: #89b4fa; border-radius: 4px; }
            QPushButton {
                background-color: #313244; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 6px;
                padding: 6px 18px; font-size: 12px;
            }
            QPushButton:hover { background-color: #45475a; border: 1px solid #89b4fa; }
            QPushButton:disabled { color: rgba(140,140,140,0.5); }
            QScrollBar:vertical { background-color: #1e1e2e; width: 8px; }
            QScrollBar::handle:vertical { background-color: #45475a; border-radius: 4px; }
            QScrollBar:horizontal { background-color: #1e1e2e; height: 8px; }
            QScrollBar::handle:horizontal { background-color: #45475a; border-radius: 4px; }
            QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
        """
    return """
        QDialog { background-color: #f5f5f5; }
        QLabel { color: #2c2c2c; font-size: 12px; }
        QCheckBox { color: #2c2c2c; font-size: 12px; }
        QTreeWidget {
            background-color: #ffffff; color: #2c2c2c;
            border: 1px solid #d0d0d0; border-radius: 6px;
            font-size: 12px;
        }
        QTreeWidget::item { height: 24px; }
        QTreeWidget::item:selected {
            background-color: #e4e7eb; color: #2c2c2c;
        }
        QHeaderView::section {
            background-color: #e8e8e8; color: #555555;
            border: none; border-right: 1px solid #d0d0d0;
            border-bottom: 1px solid #d0d0d0;
            padding: 4px 6px; font-size: 12px;
        }
        QScrollArea { background-color: #f5f5f5; border: none; }
        #TaskRowsContainer { background-color: #ffffff; }
        QProgressBar {
            background-color: #ffffff; color: #2c2c2c;
            border: 1px solid #d0d0d0; border-radius: 4px;
            text-align: center; font-size: 11px;
        }
        QProgressBar::chunk { background-color: #0078d4; border-radius: 4px; }
        QPushButton {
            background-color: #f0f0f0; color: #2c2c2c;
            border: 1px solid #d0d0d0; border-radius: 6px;
            padding: 6px 18px; font-size: 12px;
        }
        QPushButton:hover { background-color: #e4e7eb; border: 1px solid #0078d4; }
        QPushButton:disabled { color: rgba(140,140,140,0.5); }
        QScrollBar:vertical { background-color: #f0f0f0; width: 8px; }
        QScrollBar::handle:vertical { background-color: #c0c0c0; border-radius: 4px; }
        QScrollBar:horizontal { background-color: #f0f0f0; height: 8px; }
        QScrollBar::handle:horizontal { background-color: #c0c0c0; border-radius: 4px; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
    """


class _TaskRowWidget(QFrame):
    """One task row inside the task monitor (Idle window): checkbox + name,
    status on the right, a progress bar and a per-row cancel button."""

    cancel_requested = pyqtSignal(str)   # task name

    def __init__(self, task_name: str, dark: bool = False, parent=None):
        super().__init__(parent)
        self._dark = dark
        self._name = task_name
        self._setup_ui()
        self.set_dark_theme(dark)

    def _setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        head = QHBoxLayout()
        self._checkbox = QCheckBox(self._name)
        self._checkbox.setChecked(True)
        self._checkbox.setStyleSheet("font-weight: bold;")
        head.addWidget(self._checkbox)
        head.addStretch()

        self._status_label = QLabel(_status_text("idle"))
        head.addWidget(self._status_label)

        self._cancel_btn = QPushButton("✕ Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(
            lambda: self.cancel_requested.emit(self._name))
        head.addWidget(self._cancel_btn)
        lay.addLayout(head)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(18)
        lay.addWidget(self._progress)

    def set_status(self, status: str, progress: int = 0,
                   run_time: str = ""):
        self._status_label.setText(_status_text(status))
        color = _status_color(status)
        self._status_label.setStyleSheet(f"color: {color.name()};")
        if status == "running":
            self._progress.setVisible(True)
            self._progress.setValue(progress)
            self._cancel_btn.setEnabled(True)
        elif status == "queued":
            self._progress.setVisible(True)
            self._progress.setValue(0)
            self._cancel_btn.setEnabled(True)
        else:
            self._progress.setVisible(False)
            self._progress.setValue(0)
            self._cancel_btn.setEnabled(False)

    def is_selected(self) -> bool:
        return self._checkbox.isChecked()

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        if dark:
            self.setStyleSheet("""
                QFrame {
                    background-color: #313244;
                    border: 1px solid #45475a; border-radius: 6px;
                }
                QCheckBox { color: #cdd6f4; font-size: 12px; }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #f5f5f5;
                    border: 1px solid #e0e0e0; border-radius: 6px;
                }
                QCheckBox { color: #2c2c2c; font-size: 12px; }
            """)


class RunMonitorDialog(QDialog):
    """Run launcher (Run toolbar button): select tasks and start them.

    A two-column table (task name / status) under the control bar; no run log
    and no progress bars here - progress lives in the task monitor opened by
    the Idle/status button. The "Run Selected" button is greyed out while any
    task is running to prevent double-starting.
    """

    run_selected = pyqtSignal(list)   # names of the selected tasks

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._items: dict[str, QTreeWidgetItem] = {}

        # Same aspect as the main window (1400x900), i.e. width:height ~ 3:2.
        self.setWindowTitle("Run")
        self.setMinimumSize(560, 360)
        self.resize(700, 450)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._setup_ui()
        self._apply_theme(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Select tasks to run"))
        bar.addStretch()
        self._run_btn = QPushButton("Run Selected")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run)
        bar.addWidget(self._run_btn)
        layout.addLayout(bar)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Task", "Status"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        # The two columns share the available width equally (50/50).
        header = self._tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        layout.addWidget(self._tree, 1)

        hint = QLabel(
            "To add a task, right-click \"Tasks\" in the project tree.")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

    # ---- Task management ----

    def add_task(self, task_name: str):
        if task_name in self._items:
            return
        item = QTreeWidgetItem([task_name, _status_text("idle")])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        self._tree.addTopLevelItem(item)
        self._items[task_name] = item
        self._run_btn.setEnabled(len(self._items) > 0)

    def sync_tasks(self, names: list):
        for name in list(self._items):
            if name not in names:
                self._tree.takeTopLevelItem(
                    self._tree.indexOfTopLevelItem(self._items.pop(name)))
        for name in names:
            self.add_task(name)

    def update_task_status(self, task_name: str, status: str,
                           progress: int = 0, run_time: str = ""):
        item = self._items.get(task_name)
        if item is None:
            return
        text = _status_text(status)
        if run_time and status in ("completed", "failed", "stopped"):
            text += f" ({run_time})"
        item.setText(1, text)
        item.setForeground(1, _status_color(status))

    def set_busy(self, busy: bool):
        """Grey out the Run Selected button while tasks are running so the
        user cannot start the same tasks twice."""
        self._run_btn.setEnabled(not busy and bool(self._items))

    # ---- Internal ----

    def _on_run(self):
        names = []
        for name, item in self._items.items():
            if item.checkState(0) == Qt.CheckState.Checked:
                names.append(name)
        if names:
            self.run_selected.emit(names)

    def showEvent(self, event):
        super().showEvent(event)
        # Equalize once the initial layout has settled (header width known).
        QTimer.singleShot(0, self._equalize_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_tree"):
            self._equalize_columns()

    def _equalize_columns(self):
        """Keep the Task / Status columns at exactly equal widths."""
        header = self._tree.header()
        total = header.width()
        if total <= 0:
            return
        half = total // 2
        header.resizeSection(0, half)
        header.resizeSection(1, total - half)

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        self._apply_theme(dark)

    def _apply_theme(self, dark: bool):
        self.setStyleSheet(_styles(dark))


class TaskMonitorDialog(QDialog):
    """Task monitor (Idle/status toolbar button): one row per task with
    checkbox + name + status, a progress bar while running, and a per-row
    cancel button. "Run Selected" and "Stop All" sit at the top right.
    """

    run_selected = pyqtSignal(list)   # names of the selected tasks
    stop_all = pyqtSignal()
    cancel_task = pyqtSignal(str)     # single-task cancel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._rows: dict[str, _TaskRowWidget] = {}

        # Same aspect as the main window (1400x900), i.e. width:height ~ 3:2.
        self.setWindowTitle("Task Monitor")
        self.setMinimumSize(560, 360)
        self.resize(700, 450)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._setup_ui()
        self._apply_theme(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        bar = QHBoxLayout()
        bar.addStretch()
        self._run_btn = QPushButton("Run Selected")
        self._run_btn.clicked.connect(self._on_run)
        bar.addWidget(self._run_btn)
        self._stop_btn = QPushButton("Stop All")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self.stop_all.emit)
        bar.addWidget(self._stop_btn)
        layout.addLayout(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = QWidget()
        # Object name so the stylesheet can paint the scroll area's background
        # in both themes (the viewport stays white otherwise).
        self._container.setObjectName("TaskRowsContainer")
        self._rows_layout = QVBoxLayout(self._container)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._rows_layout.setSpacing(6)
        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

        self._summary = QLabel("No tasks")
        self._summary.setStyleSheet("font-size: 11px; color: #6c7086;")
        layout.addWidget(self._summary)

    # ---- Task management ----

    def add_task(self, task_name: str):
        if task_name in self._rows:
            return
        w = _TaskRowWidget(task_name, self._dark)
        w.cancel_requested.connect(self.cancel_task.emit)
        self._rows[task_name] = w
        self._rows_layout.addWidget(w)
        self._update_summary()

    def sync_tasks(self, names: list):
        for name in list(self._rows):
            if name not in names:
                w = self._rows.pop(name)
                self._rows_layout.removeWidget(w)
                w.deleteLater()
        for name in names:
            self.add_task(name)
        self._update_summary()

    def update_task_status(self, task_name: str, status: str,
                           progress: int = 0, run_time: str = ""):
        w = self._rows.get(task_name)
        if w is not None:
            w.set_status(status, progress, run_time)
        active = self._any_active()
        self._stop_btn.setEnabled(active)
        self._run_btn.setEnabled(not active)

    def _any_active(self) -> bool:
        for w in self._rows.values():
            if w._cancel_btn.isEnabled():
                return True
        return False

    def set_busy(self, busy: bool):
        self._run_btn.setEnabled(not busy)
        self._stop_btn.setEnabled(busy)

    # ---- Internal ----

    def _on_run(self):
        names = [name for name, w in self._rows.items() if w.is_selected()]
        if names:
            self.run_selected.emit(names)

    def _update_summary(self):
        n = len(self._rows)
        self._summary.setText(f"{n} task(s)" if n else "No tasks")

    # ---- Theme ----

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        for w in self._rows.values():
            w.set_dark_theme(dark)
        self._apply_theme(dark)

    def _apply_theme(self, dark: bool):
        self.setStyleSheet(_styles(dark))
