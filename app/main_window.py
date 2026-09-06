"""
MainWindow - the RadSim main window

Layout, theme, and sizing follow gdmleditor (cad2gdml lineage) item by item:
  - Ribbon toolbar (emoji icons + text below, 72px tall)
  - Left project-tree dock (280) + central VTK + bottom log + status bar
  - QPalette + QSS light/dark theme
Scaffolding stage: GDML import and rendering work; the analysis dialogs and
the run pipeline are placeholders, to be filled in later per
`doc/GUI_Design.md` and `doc/implementation_roadmap.md`.
"""

import os
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QTextEdit, QSplitter, QLabel, QFileDialog,
    QMessageBox, QDockWidget, QToolBar, QStackedWidget, QApplication,
)
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal
from PyQt6.QtGui import QPalette, QColor, QFont

from core.gdml_agent import GdmlAgent
from core.project_io import save_project, load_project
from core.run_manager import RunManager, RunTask
from utils.logger import AsyncLogger, LogLevel
from ui.ribbon_toolbar import RibbonToolBar
from ui.project_tree import ProjectTreeWidget
from ui.vtk_widget import VtkWidget
from ui.dialogs.run_monitor import RunMonitorDialog, TaskMonitorDialog
from ui.dialogs.calculate_setting_dialog import CalculateSettingDialog
from ui.dialogs.solver_setting_dialog import SolverSettingDialog
from ui.dialogs.realworld_dialog import RealWorldDialog
from ui.dialogs.probe_dialog import ProbeDialog
from ui.dialogs.voxel_dialog import VoxelDialog
from ui.dialogs.particle_dialog import ParticleDialog
from ui.dialogs.physics_dialog import PhysicsDialog


# Parse GDML above this size (bytes) on a background thread to keep the main
# window responsive (same approach as gdmleditor)
_LARGE_FILE_THRESHOLD = 500_000


class _ImportWorker(QObject):
    """Parse large GDML on a background thread (thread-safe; never touches
    agent state or the UI).

    Ported from gdmleditor: parse_file_only only parses, with no UI work, so
    it can run off the main thread; the parse result returns to the main
    thread through a queued signal.
    """

    # (success, msg, file_node_or_None), auto-queued across threads to the
    # main thread
    file_parsed = pyqtSignal(bool, str, object)
    # emitted once the run finishes (the thread is about to exit)
    all_done = pyqtSignal()

    def __init__(self, agent: GdmlAgent, filepath: str):
        super().__init__()
        self._agent = agent
        self._filepath = filepath

    def stop(self):
        """Requested on window close to exit as soon as possible (single-file
        parsing has no mid-run checkpoint)."""

    def run(self):
        # Parsing is pure-Python heavy computation: tighten the GIL switch
        # interval so the main-thread event pump keeps processing and the UI
        # does not freeze for long stretches while large files are parsed.
        import sys as _sys
        _prev = _sys.getswitchinterval()
        _sys.setswitchinterval(max(0.001, min(_prev, 0.005)))
        try:
            file_node, msg = self._agent.parse_file_only(self._filepath)
            self.file_parsed.emit(file_node is not None, msg, file_node)
        finally:
            _sys.setswitchinterval(_prev)
            self.all_done.emit()


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RadSim - 3D Radiation Simulation")
        self.resize(1400, 900)
        self._dark_theme = False

        self._gdml_agent = GdmlAgent()
        self._logger = AsyncLogger()
        self._vtk_widget: Optional[VtkWidget] = None

        # Background import (large GDML parsing goes to a thread; see
        # _ImportWorker)
        self._import_thread: Optional[QThread] = None
        self._import_worker: Optional[_ImportWorker] = None
        self._pending_gdml_node = None   # file_node parsed successfully on the background thread
        self._pending_gdml_error = ""    # reason the background parse failed

        # Multi-task running (queue + concurrency cap; see core/run_manager.py)
        self._run_manager = RunManager(max_concurrent=2)
        self._run_launcher: Optional[RunMonitorDialog] = None
        self._task_monitor: Optional[TaskMonitorDialog] = None
        self._task_counter = 0
        self._gdml_paths: list[str] = []  # real paths of imported GDML (for project save)
        self._analysis_dialogs: dict[tuple, object] = {}  # (task, kind) -> dialog
        self._particle_dialogs: dict[tuple, object] = {}  # ("particle", task) -> dialog

        self._init_toolbar()
        self._init_project_tree()
        self._init_center_placeholder()
        self._init_vtk_widget()
        self._init_log_panel()
        self._init_layout()
        self._init_status_bar()

        self._apply_global_theme(False)  # light theme by default
        self._connect_signals()

        # Always start with a default Run_001 (calculate setting has defaults,
        # so it can run directly)
        self._ensure_default_task()

        self._logger.log_system("RadSim started")
        self._logger.log_system("Ready — click [📁 Import GDML] to load a geometry.")
        self._logger.log_system("Default task Run_001 created (right-click Tasks to add more)")

    # ==================== Theme ====================

    def _apply_global_theme(self, dark: bool):
        self._dark_theme = dark
        if dark:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#181825"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#313244"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("#f38ba8"))
            palette.setColor(QPalette.ColorRole.Link, QColor("#89b4fa"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#45475a"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#cdd6f4"))
            self.setPalette(palette)
            mw_bg = "#1e1e2e"; dock_bg = "#1e1e2e"; dock_fg = "#cdd6f4"
            dock_t_bg = "#181825"; dock_t_fg = "#a6adc8"; dock_t_bd = "#313244"
            sp_color = "#313244"; log_bg = "#11111b"; log_fg = "#a6adc8"
            st_bg = "#181825"; st_fg = "#a6adc8"
        else:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#f5f5f5"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#e8e8e8"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#2c2c2c"))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("#d32f2f"))
            palette.setColor(QPalette.ColorRole.Link, QColor("#0078d4"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            self.setPalette(palette)
            mw_bg = "#f5f5f5"; dock_bg = "#f5f5f5"; dock_fg = "#2c2c2c"
            dock_t_bg = "#e8e8e8"; dock_t_fg = "#555555"; dock_t_bd = "#d0d0d0"
            sp_color = "#cccccc"; log_bg = "#fafafa"; log_fg = "#555555"
            st_bg = "#e8e8e8"; st_fg = "#555555"

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {mw_bg}; }}
            QDockWidget {{ background-color: {dock_bg}; color: {dock_fg};
                titlebar-close-icon: none; titlebar-normal-icon: none; }}
            QDockWidget::title {{ background-color: {dock_t_bg}; color: {dock_t_fg};
                font-size: 13px; font-weight: bold; padding: 4px 8px;
                border-bottom: 1px solid {dock_t_bd}; text-align: left; }}
            QSplitter::handle {{ background-color: {sp_color}; }}
            QSplitter::handle:horizontal {{ width: 2px; }}
            QSplitter::handle:vertical {{ height: 2px; }}
            QScrollBar:vertical {{ background: {log_bg}; width: 10px; margin: 0px; }}
            QScrollBar::handle:vertical {{ background: {dock_t_bg}; min-height: 20px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {sp_color}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)

        self._log_widget.setStyleSheet(f"""
            #SystemLog {{ background-color: {log_bg}; color: {log_fg};
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px; border: none; padding: 4px; }}
        """)

        self._toolbar.set_dark_theme(dark)
        self._project_tree.set_dark_theme(dark)
        if self._vtk_widget is not None:
            self._vtk_widget.set_dark_theme(dark)

    def _toggle_theme(self):
        self._apply_global_theme(not self._dark_theme)
        if self._run_launcher is not None:
            self._run_launcher.set_dark_theme(self._dark_theme)
        if self._task_monitor is not None:
            self._task_monitor.set_dark_theme(self._dark_theme)
        solver_dlg = getattr(self, "_solver_dialog", None)
        if solver_dlg is not None:
            solver_dlg.set_dark_theme(self._dark_theme)
        for dlg in self._analysis_dialogs.values():
            try:
                dlg.set_dark_theme(self._dark_theme)
            except Exception:
                pass
        for dlg in self._particle_dialogs.values():
            try:
                dlg.set_dark_theme(self._dark_theme)
            except Exception:
                pass
        self._logger.log_system(
            f"Theme switched to {'dark' if self._dark_theme else 'light'} mode")

    # ==================== UI initialization ====================

    def _init_toolbar(self):
        self._toolbar = RibbonToolBar()
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.addWidget(self._toolbar)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

    def _init_project_tree(self):
        self._project_tree = ProjectTreeWidget()
        self._tree_dock = QDockWidget("Project", self)
        self._tree_dock.setWidget(self._project_tree)
        self._tree_dock.setMinimumWidth(280)
        self._tree_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._tree_dock)
        self.resizeDocks([self._tree_dock], [280], Qt.Orientation.Horizontal)

    def _init_center_placeholder(self):
        self._center_placeholder = QLabel(
            "No 3D view loaded\n\n"
            "Click [📁 Import GDML] on the toolbar to load a GDML file.\n"
            "RadSim focuses on calculation: only one GDML geometry is allowed at a time.")
        self._center_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._center_placeholder.setStyleSheet(
            "color: #6c7086; font-size: 14px; padding: 40px;")

    def _init_vtk_widget(self):
        self._vtk_widget = VtkWidget()
        self._vtk_widget.set_dark_theme(self._dark_theme)
        self._vtk_widget.node_picked.connect(self._on_node_picked)
        # Same as gdmleditor: hide until the layout below shows the 3D view.
        self._vtk_widget.setVisible(False)

    def _init_log_panel(self):
        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setObjectName("SystemLog")
        self._log_widget.setMaximumHeight(150)
        self._log_widget.setFont(QFont("Consolas", 9))
        self._logger.set_system_log_widget(self._log_widget)

    def _init_layout(self):
        self._center_stack = QStackedWidget()
        self._center_stack.addWidget(self._center_placeholder)  # index 0
        self._center_stack.addWidget(self._vtk_widget)          # index 1 — default 3D view
        # Show the 3D view immediately (with cube axes + XYZ labels), exactly
        # like gdmleditor. The placeholder page is only a fallback.
        self._vtk_widget.setVisible(True)
        self._center_stack.setCurrentIndex(1)

        central = QSplitter(Qt.Orientation.Vertical)
        central.addWidget(self._center_stack)
        central.addWidget(self._log_widget)
        central.setStretchFactor(0, 3)
        central.setStretchFactor(1, 1)
        central.setSizes([600, 150])
        self.setCentralWidget(central)

    def _init_status_bar(self):
        self._status_label = QLabel("Ready")
        self.statusBar().addPermanentWidget(self._status_label)

    # ==================== Signals ====================

    def _connect_signals(self):
        self._toolbar.import_clicked.connect(self._on_import_gdml)
        self._toolbar.load_clicked.connect(self._load_project)
        self._toolbar.save_clicked.connect(self._save_project)
        self._toolbar.reset_view_clicked.connect(self._on_reset_view)
        self._toolbar.run_clicked.connect(self._on_run)
        self._toolbar.stop_clicked.connect(self._on_stop)
        self._toolbar.status_clicked.connect(self._on_status_clicked)
        self._toolbar.solver_setting_clicked.connect(self._on_solver_setting)
        self._toolbar.theme_toggled.connect(self._toggle_theme)
        self._toolbar.help_clicked.connect(self._on_help)

        self._project_tree.node_selected.connect(self._on_node_selected)
        self._project_tree.visibility_changed.connect(self._on_visibility_changed)
        self._project_tree.task_action.connect(self._on_task_action)
        self._project_tree.task_context.connect(self._on_task_context)

        # Multi-task running
        rm = self._run_manager
        rm.task_started.connect(self._on_task_started)
        rm.task_progress.connect(self._on_task_progress)
        rm.task_finished.connect(self._on_task_finished)
        rm.all_finished.connect(self._on_all_finished)

    # ==================== GDML Import ====================

    def _on_import_gdml(self):
        """RadSim allows only one GDML: importing again first asks whether to
        replace."""
        if self._import_thread and self._import_thread.isRunning():
            QMessageBox.information(
                self, "Import in Progress",
                "GDML is being parsed in the background; please wait until it finishes before importing again.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import GDML File", "",
            "GDML Files (*.gdml);;XML Files (*.xml);;All Files (*)")
        if not file_path:
            return
        if self._gdml_agent.get_all_file_nodes():
            ret = QMessageBox.question(
                self, "Replace Geometry",
                "A geometry already exists. RadSim supports only one GDML geometry.\n\n"
                "Replace the existing geometry? (the task list will be cleared)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
            self._run_manager.clear()
            self._project_tree.clear_tasks()
            self._task_counter = 0
        # Large files (>=500KB) are parsed on a background thread to avoid
        # freezing the UI during import (same as gdmleditor)
        if os.path.getsize(file_path) < _LARGE_FILE_THRESHOLD:
            if self._replace_gdml(file_path):
                self._ensure_default_task()
                self._logger.log_system(f"Geometry replaced: {file_path}")
        else:
            self._replace_gdml_async(file_path)

    def _replace_gdml(self, filepath: str) -> bool:
        """Replace the current geometry (RadSim's single GDML) and refresh the
        main window."""
        self._gdml_agent.clear()
        success, msg = self._gdml_agent.load_gdml_file(filepath)
        if not success:
            QMessageBox.warning(self, "Import Error",
                                f"Failed to import:\n{msg}")
            return False
        self._gdml_paths = [filepath]
        self._rebuild_ui()
        self._check_unsupported_solids()
        return True

    # ---- Large-file background parsing (ported from gdmleditor) ----

    def _replace_gdml_async(self, filepath: str):
        """Large file: parsed purely on a background thread, then atomically
        replaced on the main thread once parsing succeeds."""
        self._logger.log_system(
            f"Parsing large file in background: {os.path.basename(filepath)} "
            f"({os.path.getsize(filepath) / 1e6:.1f} MB)")
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        progress = QProgressDialog(
            "Parsing GDML in the background…\n"
            "Large files may take a while; the UI stays responsive in the meantime.",
            None, 0, 0, self)   # marquee; no cancel, to avoid a partially imported state
        progress.setWindowTitle("Importing GDML")
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        worker = _ImportWorker(self._gdml_agent, filepath)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.file_parsed.connect(self._on_async_file_parsed)
        worker.all_done.connect(
            lambda: self._on_async_import_done(progress, filepath, thread))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._import_worker = worker
        self._import_thread = thread
        thread.start()

    def _on_async_file_parsed(self, success: bool, msg: str, file_node: object):
        """Worker thread -> main thread: stash the parse result (without
        replacing the geometry mid-way)."""
        if success and file_node is not None:
            self._pending_gdml_node = file_node
            self._logger.log_system(f"  [OK] {msg}")
        else:
            self._pending_gdml_error = msg or "Unknown error"
            self._logger.log_system(f"  [ERR] {msg}", LogLevel.ERROR)

    def _on_async_import_done(self, progress: object, filepath: str,
                              thread: QThread):
        """Worker finished (on the main thread): tear down the thread and
        atomically replace the geometry.

        The progress dialog stays open until the 3D scene build/render is fully
        done - otherwise, during a large-geometry rebuild, the UI looks frozen
        with no progress feedback at all.
        """
        node, err = self._pending_gdml_node, self._pending_gdml_error
        self._pending_gdml_node, self._pending_gdml_error = None, ""

        thread.quit()
        thread.wait(2000)
        self._import_thread = None
        self._import_worker = None

        if node is None:
            progress.close()
            QMessageBox.warning(self, "Import Error",
                                f"Failed to import:\n{err}")
            return
        try:
            self._gdml_agent.clear()
            self._gdml_agent.add_parsed_file_node(node)
            self._gdml_paths = [filepath]
            self._rebuild_ui(progress)
            self._ensure_default_task()
        finally:
            # Close the progress dialog only after the scene render/UI rebuild
            # is done
            progress.close()
        self._check_unsupported_solids()
        self._logger.log_system(f"Geometry replaced: {filepath}")

    def _check_unsupported_solids(self):
        unsupported = self._gdml_agent.get_unsupported_solids()
        if not unsupported:
            return
        from collections import Counter
        tag_counts = Counter(s["tag"] for s in unsupported)
        detail_lines = []
        for tag, count in tag_counts.most_common():
            names = [s["name"] for s in unsupported if s["tag"] == tag]
            detail_lines.append(f"  • {tag} ({count}): {', '.join(names)}")
        QMessageBox.warning(
            self, "Incomplete Geometry Parsing",
            "The following solid types were found but cannot be fully parsed:\n\n"
            + "\n".join(detail_lines) + "\n\n"
            "These solids will be preserved for export but NOT rendered.")

    def _rebuild_ui(self, progress=None):
        """Rebuild the project tree and the 3D scene.

        When progress (a QProgressDialog) is not None - the large-file async
        import path - the dialog text is refreshed periodically inside the
        tree/scene build loop and the event loop is yielded, keeping the UI
        responsive during large-geometry rebuilds.
        """
        root = self._gdml_agent.get_root_node()
        scene = self._vtk_widget.get_scene()
        if progress is not None and scene is not None:
            tree_cb = self._make_rebuild_flusher(progress, "Project tree")
            scene.set_build_progress_callback(
                self._make_rebuild_flusher(progress, "3D scene"))
        else:
            tree_cb = None
        try:
            self._project_tree.build_from_node_tree(root, progress_cb=tree_cb)
            self._vtk_widget.build_scene(root)
        finally:
            if scene is not None:
                scene.set_build_progress_callback(None)
        self._center_stack.setCurrentIndex(1)
        count = len(self._gdml_agent.get_all_file_nodes())
        self._status_label.setText(f"Files loaded: {count}")
        self._logger.log_system(f"Rebuilt UI with {count} file(s)")

    def _make_rebuild_flusher(self, progress: object, what: str):
        """Build-progress callback: throttled refresh of the dialog text and
        yielding of the event loop (to prevent UI freeze)."""
        import time
        state = {"last": 0.0}

        def flush(done: int):
            now = time.monotonic()
            if now - state["last"] >= 0.1:
                state["last"] = now
                progress.setLabelText(
                    f"Building {what}… ({done} nodes processed)")
                QApplication.processEvents()

        return flush

    # ==================== Handlers ====================

    def _on_analysis(self, kind: str):
        self._logger.log_system(
            f"[{kind}] analysis config dialog - planned; see doc/implementation_roadmap.md")
        self._status_label.setText(f"{kind} analysis dialog (placeholder)")
        QMessageBox.information(
            self, f"{kind} Analysis",
            f"{kind} analysis config dialog is not wired up yet.\n"
            f"Planning: see doc/GUI_Design.md and doc/implementation_roadmap.md.")

    def _on_run(self):
        """Run: optionally ask for even CPU-core assignment, then open the
        slim run launcher (checkbox list + Run Selected)."""
        if not self._gdml_agent.get_all_file_nodes():
            QMessageBox.information(
                self, "No Geometry",
                "Please import a GDML file before creating a run task.")
            return
        launcher = self._ensure_run_launcher()
        tasks = list(self._run_manager._tasks.values())
        if not tasks:
            QMessageBox.information(
                self, "No Tasks",
                "No tasks yet. Add a task by right-clicking \"Tasks\" in the "
                "project tree before running.")
            launcher.show()
            launcher.raise_()
            return
        ret = QMessageBox.question(
            self, "Assign compute cores",
            "Split the computer's CPU cores evenly across tasks based on the core count?\n\n"
            "Yes: total CPU cores are split by task count (at least 1 core per task),"
            "and written to each task's Calculate Setting.\n"
            "No: use each task's current Calculate Setting configuration.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            total = os.cpu_count() or 4
            idle_tasks = [t for t in tasks if t.status == "idle"]
            if idle_tasks:
                per = max(1, total // len(idle_tasks))
                for t in idle_tasks:
                    t.calculate.n_threads = per
                    self._project_tree.update_task_threads(t.name, per)
                self._logger.log_system(
                    f"CPU split: {total} cores / {len(idle_tasks)} tasks -> "
                    f"{per} threads/task")
        else:
            self._logger.log_system(
                "Skipped auto-assignment; using each task's existing Calculate Setting")
        launcher.show()
        launcher.raise_()

    def _on_stop(self):
        self._run_manager.stop_all()
        self._logger.log_system("Stop All requested")
        self._update_status_button()

    # ==================== Task status / Project ====================

    def _on_status_clicked(self):
        """Idle/status button: open the task monitor (progress bars, per-row
        cancel, Run Selected / Stop All)."""
        monitor = self._ensure_task_monitor()
        monitor.show()
        monitor.raise_()

    def _update_status_button(self):
        tasks = list(self._run_manager._tasks.values())
        if not tasks:
            self._toolbar.set_status("idle")
            return
        running = [t for t in tasks if t.status in ("running", "queued")]
        failed = [t for t in tasks if t.status == "failed"]
        if running:
            self._toolbar.set_status("running", f"{len(running)}/{len(tasks)}")
        elif failed:
            self._toolbar.set_status("issues", f"{len(failed)} failed")
        else:
            self._toolbar.set_status("idle")

    def _on_solver_setting(self):
        """Open the solver path setting dialog (lazy singleton)."""
        dlg = getattr(self, "_solver_dialog", None)
        if dlg is None:
            dlg = SolverSettingDialog(self)
            dlg.set_dark_theme(self._dark_theme)
            self._solver_dialog = dlg
        dlg.show()
        dlg.raise_()

    def _on_task_action(self, payload: str):
        """A project-tree task node was clicked
        (calculate/particle/physics/analysis/result)."""
        action, _, rest = payload.partition(":")
        if action == "calculate":
            self._open_calculate_setting(rest)
        elif action == "particle":
            self._open_particle_dialog(rest)
        elif action == "physics":
            self._open_physics_dialog(rest)
        elif action == "analysis":
            task_name, _, kind = rest.partition(":")
            self._open_analysis_dialog(task_name, kind)
        elif action == "result":
            self._on_result_activated(rest)

    def _open_calculate_setting(self, task_name: str):
        task = self._run_manager.get_task(task_name)
        if task is None:
            return
        dlg = CalculateSettingDialog(
            self, task_name, task.calculate.n_threads)
        dlg.set_dark_theme(self._dark_theme)
        if dlg.exec():
            task.calculate.n_threads = dlg.get_n_threads()
            self._project_tree.update_task_threads(
                task_name, task.calculate.n_threads)
            self._logger.log_system(
                f"[{task_name}] Calculate Setting: "
                f"{task.calculate.n_threads} threads")

    def _open_particle_dialog(self, task_name: str):
        """Double-clicking the task's "Particle Setting" node opens the GPS
        source dialog (non-modal, cached per task)."""
        task = self._run_manager.get_task(task_name)
        if task is None:
            return
        if task.status in ("running", "queued"):
            QMessageBox.information(
                self, "Task Running",
                "A task is running; particle source cannot be modified.")
            return
        key = ("particle", task_name)
        dlg = self._particle_dialogs.get(key)
        if dlg is None:
            dlg = ParticleDialog(self, task=task,
                                 gdml_agent=self._gdml_agent)
            dlg.set_dark_theme(self._dark_theme)
            dlg.destroyed.connect(
                lambda _o, k=key: self._particle_dialogs.pop(k, None))
            if hasattr(dlg, "close_requested"):
                dlg.close_requested.connect(
                    lambda k=key: self._particle_dialogs.pop(k, None))
            self._particle_dialogs[key] = dlg
            self._logger.log_system(
                f"[{task_name}] particle source (GPS) dialog opened")
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _open_physics_dialog(self, task_name: str):
        """Double-clicking the task's "Physics Process" node opens the physics
        settings dialog (modal); saving marks the tree node configured."""
        task = self._run_manager.get_task(task_name)
        if task is None:
            return
        if task.status in ("running", "queued"):
            QMessageBox.information(
                self, "Task Running",
                "A task is running; the physics process cannot be modified.")
            return
        dlg = PhysicsDialog(self, task_name=task_name, config=task.physics)
        dlg.set_dark_theme(self._dark_theme)
        if dlg.exec():
            task.physics = dlg.get_config()
            self._project_tree.set_physics_configured(task_name, True)
            self._logger.log_system(
                f"[{task_name}] Physics Process saved: "
                f"{task.physics.get('physics_list')}")

    def on_particle_saved(self, task_name: str, configured: bool):
        """Callback after the particle source dialog saves: mark the tree node."""
        self._project_tree.set_particle_configured(task_name, configured)
        self._logger.log_system(
            f"[{task_name}] particle source saved"
            + (" (configured)" if configured else " (empty)"))

    def _save_project(self):
        if not self._gdml_paths:
            QMessageBox.information(
                self, "Nothing to Save", "Please import a GDML geometry first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", "", "RadSim Project (*.json)")
        if not path:
            return
        tasks = []
        for t in self._run_manager._tasks.values():
            tasks.append({
                "name": t.name,
                "analysis_type": t.analysis_type,
                "gdml_files": t.gdml_files,
                "calculate": {"n_threads": t.calculate.n_threads},
                "particle": t.particle or {},
                "physics": t.physics or {},
                "analysis_config": t.analysis_config or {},
            })
        save_project(path, gdml_paths=self._gdml_paths, tasks=tasks)
        self._logger.log_system(f"Project saved: {path}")

    def _load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Project", "", "RadSim Project (*.json)")
        if not path:
            return
        try:
            gdml_paths, tasks = load_project(path)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", str(e))
            return
        if not gdml_paths:
            QMessageBox.warning(self, "Load Error", "Project file is missing the geometry path.")
            return
        self._run_manager.clear()
        self._project_tree.clear_tasks()
        self._task_counter = 0
        if not self._replace_gdml(gdml_paths[0]):
            return
        for td in tasks:
            t = RunTask(
                name=td.get("name", f"Run_{self._task_counter + 1:03d}"),
                gdml_files=td.get("gdml_files", gdml_paths),
                analysis_type=td.get("analysis_type", ""))
            t.calculate.n_threads = td.get("calculate", {}).get("n_threads", 0)
            t.particle = td.get("particle", {}) or {}
            t.physics = td.get("physics", {}) or {}
            t.analysis_config = td.get("analysis_config", {}) or {}
            self._task_counter += 1
            self._run_manager.add_task(t)
            self._project_tree.add_task(
                t.name, t.analysis_type, t.calculate.n_threads)
            kind_map = {"realworld": "real world", "probe": "probe",
                        "voxel": "voxel"}
            for k, label in kind_map.items():
                if t.analysis_config.get(k):
                    self._project_tree.set_analysis_configured(
                        t.name, label, True)
            if t.particle:
                self._project_tree.set_particle_configured(t.name, True)
            if t.physics:
                self._project_tree.set_physics_configured(t.name, True)
        self._ensure_default_task()
        self._logger.log_system(
            f"Project loaded: {path} ({len(tasks)} task(s))")

    # ==================== Multi-task running ====================

    def _ensure_run_launcher(self) -> RunMonitorDialog:
        """Create the slim run launcher (Run toolbar button) on demand."""
        if self._run_launcher is None:
            self._run_launcher = RunMonitorDialog(self)
            self._run_launcher.set_dark_theme(self._dark_theme)
            self._run_launcher.run_selected.connect(self._run_manager.start)
            self._run_manager.task_added.connect(
                lambda task: self._run_launcher.add_task(task.name))
            for t in self._run_manager._tasks.values():
                self._run_launcher.add_task(t.name)
            if self._run_manager.is_running_any():
                self._run_launcher.set_busy(True)
        return self._run_launcher

    def _ensure_task_monitor(self) -> TaskMonitorDialog:
        """Create the task monitor (Idle toolbar button) on demand."""
        if self._task_monitor is None:
            self._task_monitor = TaskMonitorDialog(self)
            self._task_monitor.set_dark_theme(self._dark_theme)
            self._task_monitor.run_selected.connect(self._run_manager.start)
            self._task_monitor.stop_all.connect(self._run_manager.stop_all)
            self._task_monitor.cancel_task.connect(
                self._run_manager.stop_task)
            self._run_manager.task_added.connect(
                lambda task: self._task_monitor.add_task(task.name))
            for t in self._run_manager._tasks.values():
                self._task_monitor.add_task(t.name)
            if self._run_manager.is_running_any():
                self._task_monitor.set_busy(True)
        return self._task_monitor

    def _sync_run_monitor_tasks(self):
        keys = list(self._run_manager._tasks.keys())
        if self._run_launcher is not None:
            self._run_launcher.sync_tasks(keys)
        if self._task_monitor is not None:
            self._task_monitor.sync_tasks(keys)

    def _ensure_default_task(self):
        """Make sure at least one default task exists (Run_001, whose calculate
        default thread count equals the CPU core count)."""
        if self._run_manager._tasks:
            return
        files = [f.name for f in self._gdml_agent.get_all_file_nodes()]
        self._task_counter = max(self._task_counter, 1)
        task = RunTask(name="Run_001",
                       gdml_files=files or [],
                       analysis_type="default")
        task.calculate.n_threads = max(1, (os.cpu_count() or 4) // 2)
        self._run_manager.add_task(task)
        self._project_tree.add_task(
            task.name, task.analysis_type, task.calculate.n_threads)

    def _add_default_run_task(self):
        """Add a new task (right-click Tasks -> Add Task). Importing a GDML is
        not required first."""
        self._task_counter += 1
        files = [f.name for f in self._gdml_agent.get_all_file_nodes()]
        task = RunTask(name=f"Run_{self._task_counter:03d}",
                       gdml_files=files, analysis_type="default")
        task.calculate.n_threads = max(1, (os.cpu_count() or 4) // 2)
        self._run_manager.add_task(task)
        self._project_tree.add_task(
            task.name, task.analysis_type, task.calculate.n_threads)
        self._logger.log_system(
            f"Task added: {task.name} ({', '.join(files) or 'no geometry'})")

    # ==================== Task context menu / analysis dialog ====================

    def _on_task_context(self, action: str, payload: str):
        if action == "add_task":
            self._add_default_run_task()
        elif action == "rename_task":
            self._rename_task(payload)
        elif action == "duplicate_task":
            self._duplicate_task(payload)
        elif action == "delete_task":
            self._delete_task(payload)
        elif action == "configure_analysis":
            act, _, rest = payload.partition(":")
            if act == "analysis":
                task_name, _, kind = rest.partition(":")
                self._open_analysis_dialog(task_name, kind)
        elif action == "view_result":
            _, _, ref = payload.partition(":")
            self._on_result_activated(ref)

    def _rename_task(self, old_name: str):
        from PyQt6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename Task", "New task name:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name in self._run_manager._tasks:
            QMessageBox.warning(self, "Rename", "Task name already exists.")
            return
        task = self._run_manager.get_task(old_name)
        if task is None:
            return
        self._run_manager._tasks.pop(old_name, None)
        task.name = new_name
        self._run_manager._tasks[new_name] = task
        self._project_tree.rename_task(old_name, new_name)
        self._sync_run_monitor_tasks()
        self._logger.log_system(f"Task renamed: {old_name} → {new_name}")

    def _duplicate_task(self, name: str):
        import copy
        src = self._run_manager.get_task(name)
        if src is None:
            return
        new = copy.deepcopy(src)
        self._task_counter += 1
        new.name = f"Run_{self._task_counter:03d}"
        new.status = "idle"
        new.progress = 0
        new.run_time = ""
        self._run_manager._tasks[new.name] = new
        self._project_tree.add_task(
            new.name, new.analysis_type, new.calculate.n_threads)
        kind_map = {"realworld": "real world", "probe": "probe", "voxel": "voxel"}
        for k, label in kind_map.items():
            if new.analysis_config.get(k):
                self._project_tree.set_analysis_configured(
                    new.name, label, True)
        if new.particle:
            self._project_tree.set_particle_configured(new.name, True)
        if new.physics:
            self._project_tree.set_physics_configured(new.name, True)
        self._sync_run_monitor_tasks()
        self._logger.log_system(f"Task duplicated: {name} → {new.name}")

    def _delete_task(self, name: str):
        task = self._run_manager.get_task(name)
        if task is None:
            return
        if task.status in ("running", "queued"):
            QMessageBox.information(self, "Delete Task",
                                    "A task is running; please stop it first.")
            return
        self._run_manager._tasks.pop(name, None)
        self._project_tree.remove_task(name)
        self._analysis_dialogs = {
            k: v for k, v in self._analysis_dialogs.items() if k[0] != name}
        self._particle_dialogs = {
            k: v for k, v in self._particle_dialogs.items() if k[1] != name}
        self._sync_run_monitor_tasks()
        self._logger.log_system(f"Task deleted: {name}")

    def _open_analysis_dialog(self, task_name: str, kind: str):
        """Double-clicking an Analysis child opens the matching analysis config
        dialog (non-modal)."""
        task = self._run_manager.get_task(task_name)
        if task is None:
            return
        if not self._gdml_agent.get_all_file_nodes():
            QMessageBox.information(
                self, "No Geometry", "Please import a GDML file before configuring analysis.")
            return
        if task.status in ("running", "queued"):
            QMessageBox.information(
                self, "Task Running", "A task is running; analysis config cannot be modified.")
            return
        key = (task_name, kind)
        dlg = self._analysis_dialogs.get(key)
        if dlg is None:
            cls = {
                "real world": RealWorldDialog,
                "probe": ProbeDialog,
                "voxel": VoxelDialog,
            }.get(kind)
            if cls is None:
                return
            dlg = cls(self, task=task, gdml_agent=self._gdml_agent)
            dlg.set_dark_theme(self._dark_theme)
            dlg.destroyed.connect(
                lambda _o, k=key: self._analysis_dialogs.pop(k, None))
            if hasattr(dlg, "close_requested"):
                # probe/voxel are destroyed on close: drop the cache synchronously
                # and rebuild fresh on reopen
                dlg.close_requested.connect(
                    lambda k=key: self._analysis_dialogs.pop(k, None))
            self._analysis_dialogs[key] = dlg
            self._logger.log_system(
                f"[{task_name}] {kind} analysis config dialog opened")
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def on_analysis_saved(self, task_name: str, config_key: str,
                          configured: bool):
        """Callback after an analysis dialog saves its config: update the
        configured marker in the project tree."""
        kind_label = {"realworld": "real world", "probe": "probe",
                      "voxel": "voxel"}.get(config_key, config_key)
        self._project_tree.set_analysis_configured(
            task_name, kind_label, configured)
        self._logger.log_system(
            f"[{task_name}] {kind_label} config saved"
            + (" (configured)" if configured else " (empty)"))

    def _on_task_started(self, name: str):
        self._toolbar.set_running(True)
        self._project_tree.set_task_status(name, "running")
        self._status_label.setText(f"Running: {name}")
        self._logger.log_system(f"[{name}] started")
        if self._run_launcher:
            self._run_launcher.set_busy(True)
            self._run_launcher.update_task_status(name, "running")
        if self._task_monitor:
            self._task_monitor.set_busy(True)
            self._task_monitor.update_task_status(name, "running", 0)
        self._update_status_button()

    def _on_task_progress(self, name: str, percent: int):
        if self._task_monitor:
            self._task_monitor.update_task_status(name, "running", percent)

    def _on_task_finished(self, name: str, status: str):
        task = self._run_manager.get_task(name)
        run_time = task.run_time if task else ""
        pct = 100 if status == "completed" else (task.progress if task else 0)
        if self._run_launcher:
            self._run_launcher.update_task_status(name, status, pct, run_time)
        if self._task_monitor:
            self._task_monitor.update_task_status(name, status, pct, run_time)
        self._logger.log_system(f"[{name}] {status} ({run_time})")
        self._project_tree.set_task_status(name, status)
        if status == "completed":
            label = (task.analysis_type or "default") + " result"
            self._project_tree.add_task_result(name, label)
        self._update_status_button()

    def _on_all_finished(self):
        self._toolbar.set_running(False)
        if self._run_launcher:
            self._run_launcher.set_busy(False)
        if self._task_monitor:
            self._task_monitor.set_busy(False)
        self._status_label.setText("All tasks finished")
        self._logger.log_system("All tasks finished")
        self._toolbar.set_status("done")

    def _on_reset_view(self):
        if self._vtk_widget:
            self._vtk_widget.get_scene().reset_camera()
            self._vtk_widget.refresh()
        self._logger.log_system("View reset")

    def _on_node_selected(self, entry_id: str):
        node = self._gdml_agent.get_node_by_entry_id(entry_id)
        if node:
            self._vtk_widget.get_scene().select_node(entry_id)
            self._vtk_widget.refresh()
            self._status_label.setText(f"Selected: {node.name}")
        else:
            self._status_label.setText("No node selected")

    def _on_visibility_changed(self, entry_id: str, visible: bool):
        if self._vtk_widget:
            self._vtk_widget.get_scene().set_visibility(entry_id, visible)
            self._vtk_widget.refresh()

    def _on_node_picked(self, entry_id: str):
        self._project_tree.select_item_by_entry_id(entry_id)
        self._on_node_selected(entry_id)

    def _on_result_activated(self, ref: str):
        # ref looks like "Run_001:energy spectrum volFlux" or ":TID summary"
        self._logger.log_system(f"Opening result: {ref} - viewer planned")
        QMessageBox.information(self, "Result Viewer",
                                f"Result viewer not wired up yet: {ref}")

    def _on_help(self):
        QMessageBox.about(self, "About RadSim",
            "RadSim v0.1.0\n\n"
            "3D Radiation Simulation GUI for rad4space solver.\n\n"
            "Supported:\n"
            "  · GDML geometry import & render (box/sphere/tube/cone/tessellated...)\n"
            "  · Analyses: realworld / probe / voxel (planned)\n\n"
            "Built with PyQt6 and VTK.\n"
            "Part of Easy2Rad project.")

    def get_system_log_widget(self):
        return self._log_widget

    def closeEvent(self, event):
        # On close: if a background parse is still running, request exit and
        # wait for the thread to finish
        if self._import_worker:
            self._import_worker.stop()
        if self._import_thread and self._import_thread.isRunning():
            self._import_thread.quit()
            self._import_thread.wait(2000)
        if self._vtk_widget:
            self._vtk_widget.cleanup()
        super().closeEvent(event)
