"""
RunMonitorDialog — non-modal dialog for monitoring task execution.

The UI shell is modeled on 1dRad (emoji status / progress bar / Select All /
Run Log) and is driven by RunManager signals instead of keeping its own state.
Light theme by default (3dRad defaults to white). Adds a "➕ Add Task" button.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QCheckBox, QTextEdit, QScrollArea, QWidget,
    QFrame, QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class _TaskProgressWidget(QFrame):
    """Progress display for a single task."""

    def __init__(self, task_name: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._dark = False
        self._setup_ui(task_name)

    def _setup_ui(self, name: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._checkbox = QCheckBox(name)
        self._checkbox.setChecked(True)
        header.addWidget(self._checkbox)
        header.addStretch()
        self._status_label = QLabel("⏳ Queued")
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._status_label)
        layout.addLayout(header)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(20)
        layout.addWidget(self._progress)

        self._time_label = QLabel("")
        layout.addWidget(self._time_label)

    def set_status(self, status: str, progress: int = 0,
                   run_time: str = ""):
        emoji_map = {
            "idle": "⏸", "queued": "⏳", "running": "🔄",
            "completed": "✅", "failed": "❌", "stopped": "⏹",
        }
        emoji = emoji_map.get(status, "⏳")
        self._status_label.setText(f"{emoji} {status.capitalize()}")
        self._progress.setValue(progress)
        if run_time:
            self._time_label.setText(f"Run time: {run_time}")

    def is_selected(self) -> bool:
        return self._checkbox.isChecked()

    def get_task_name(self) -> str:
        return self._checkbox.text()

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        if dark:
            self.setStyleSheet("""
                QFrame {
                    background-color: #313244;
                    border: 1px solid #45475a;
                    border-radius: 6px;
                }
                QCheckBox { color: #cdd6f4; font-size: 12px; font-weight: bold; }
                QLabel { color: #cdd6f4; font-size: 12px; }
                QProgressBar {
                    background-color: #1e1e2e; color: #cdd6f4;
                    border: none; border-radius: 4px;
                    text-align: center; font-size: 11px;
                }
                QProgressBar::chunk { background-color: #89b4fa; border-radius: 4px; }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                }
                QCheckBox { color: #2c2c2c; font-size: 12px; font-weight: bold; }
                QLabel { color: #2c2c2c; font-size: 12px; }
                QProgressBar {
                    background-color: #ffffff; color: #2c2c2c;
                    border: 1px solid #d0d0d0; border-radius: 4px;
                    text-align: center; font-size: 11px;
                }
                QProgressBar::chunk { background-color: #0078d4; border-radius: 4px; }
            """)


class RunMonitorDialog(QDialog):
    """Non-modal run monitor - the user can keep interacting with the main
    window while tasks are running."""

    run_selected = pyqtSignal(list)   # names of the selected tasks
    stop_all = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._task_widgets: dict[str, _TaskProgressWidget] = {}

        self.setWindowTitle("▶️ Run Monitor")
        self.setMinimumSize(550, 750)
        self.resize(600, 900)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        control_bar = QHBoxLayout()
        self._select_all_cb = QCheckBox("☐ Select All")
        self._select_all_cb.setChecked(True)
        self._select_all_cb.stateChanged.connect(self._on_select_all)
        control_bar.addWidget(self._select_all_cb)
        control_bar.addStretch()

        hint = QLabel("To add a task, right-click Tasks in the project tree")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        control_bar.addWidget(hint)

        self._run_btn = QPushButton("▶️ Run Selected")
        self._run_btn.clicked.connect(self._on_run)
        control_bar.addWidget(self._run_btn)

        self._stop_btn = QPushButton("⏹ Stop All")
        self._stop_btn.clicked.connect(self.stop_all.emit)
        control_bar.addWidget(self._stop_btn)
        layout.addLayout(control_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._task_container = QWidget()
        self._task_layout = QVBoxLayout(self._task_container)
        self._task_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._task_layout.setSpacing(6)
        scroll.setWidget(self._task_container)
        layout.addWidget(scroll)

        summary = QHBoxLayout()
        self._summary_label = QLabel("No tasks added")
        self._summary_label.setStyleSheet(
            "font-size: 11px; color: #6c7086;")
        summary.addWidget(self._summary_label)
        summary.addStretch()
        layout.addLayout(summary)

        log_group = QGroupBox("Run Log")
        log_layout = QVBoxLayout(log_group)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setFont(QFont("Consolas", 10))
        log_layout.addWidget(self._log_text)
        layout.addWidget(log_group)

    # ---- Task Management ----

    def add_task(self, task_name: str):
        if task_name in self._task_widgets:
            return
        w = _TaskProgressWidget(task_name)
        w.set_dark_theme(self._dark)
        self._task_widgets[task_name] = w
        self._task_layout.addWidget(w)
        self._update_summary()

    def sync_tasks(self, names: list):
        """Sync the task list: drop deleted ones, add new ones (tasks are
        managed from the project tree context menu)."""
        for name in list(self._task_widgets):
            if name not in names:
                w = self._task_widgets.pop(name)
                self._task_layout.removeWidget(w)
                w.deleteLater()
        for name in names:
            self.add_task(name)
        self._update_summary()

    def update_task_status(self, task_name: str, status: str,
                           progress: int = 0, run_time: str = ""):
        if task_name in self._task_widgets:
            self._task_widgets[task_name].set_status(
                status, progress, run_time)

    def append_log(self, message: str):
        self._log_text.append(message)
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ---- Internal ----

    def _on_select_all(self, state: int):
        checked = state == Qt.CheckState.Checked.value
        for w in self._task_widgets.values():
            w._checkbox.setChecked(checked)

    def _on_run(self):
        selected = [name for name, w in self._task_widgets.items()
                    if w.is_selected()]
        if selected:
            self.run_selected.emit(selected)

    def _update_summary(self):
        n = len(self._task_widgets)
        self._summary_label.setText(
            f"{n} task(s) added" if n else "No tasks added")

    # ---- Theme ----

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        for w in self._task_widgets.values():
            w.set_dark_theme(dark)
        if dark:
            self.setStyleSheet("""
                QDialog { background-color: #1e1e2e; }
                QLabel { color: #cdd6f4; font-size: 12px; }
                QCheckBox { color: #cdd6f4; font-size: 12px; }
                QGroupBox {
                    color: #cdd6f4; font-weight: bold;
                    border: 1px solid #45475a; border-radius: 6px;
                    margin-top: 12px; padding: 16px 8px 8px 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; padding: 2px 8px;
                    color: #89b4fa;
                }
                QTextEdit {
                    background-color: #11111b; color: #a6adc8;
                    border: 1px solid #45475a; border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton {
                    background-color: #313244; color: #cdd6f4;
                    border: 1px solid #45475a; border-radius: 6px;
                    padding: 6px 18px; font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #45475a; border: 1px solid #89b4fa;
                }
                QScrollBar:vertical { background-color: #1e1e2e; width: 8px; }
                QScrollBar::handle:vertical {
                    background-color: #45475a; border-radius: 4px;
                }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #f5f5f5; }
                QLabel { color: #2c2c2c; font-size: 12px; }
                QCheckBox { color: #2c2c2c; font-size: 12px; }
                QGroupBox {
                    color: #2c2c2c; font-weight: bold;
                    border: 1px solid #d0d0d0; border-radius: 6px;
                    margin-top: 12px; padding: 16px 8px 8px 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin; padding: 2px 8px;
                    color: #2c2c2c;
                }
                QTextEdit {
                    background-color: #ffffff; color: #2c2c2c;
                    border: 1px solid #d0d0d0; border-radius: 4px;
                    font-size: 11px;
                }
                QPushButton {
                    background-color: #f0f0f0; color: #2c2c2c;
                    border: 1px solid #d0d0d0; border-radius: 6px;
                    padding: 6px 18px; font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #e4e7eb; border: 1px solid #0078d4;
                }
                QScrollBar:vertical { background-color: #f0f0f0; width: 8px; }
                QScrollBar::handle:vertical { background-color: #c0c0c0; border-radius: 4px; }
            """)
