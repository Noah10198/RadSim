"""
RunManager - 3dRad multi-task run manager

Refactored on top of 1dRad's QTimer-based simulation, with the multi-task
mechanism prepared up front:
  - Independent task queue with a concurrency limit (max_concurrent, e.g. 2)
  - Signal-driven UI (task_added / task_started / task_progress /
    task_finished / all_finished)
  - Placeholder for the real solver call: _spawn_solver() is a no-op for now
    and will later be replaced by a QProcess driving the real progress
    (see step 4 of doc/implementation_roadmap.md).
"""

import time
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.project_model import RunTask


class RunManager(QObject):

    task_added = pyqtSignal(object)          # RunTask
    task_started = pyqtSignal(str)           # name
    task_progress = pyqtSignal(str, int)     # name, percent (0-100)
    task_finished = pyqtSignal(str, str)     # name, status
    all_finished = pyqtSignal()

    STEP_MS = 200
    STEP_DELTA = 10

    def __init__(self, parent=None, max_concurrent: int = 2):
        super().__init__(parent)
        self._max_concurrent = max_concurrent
        self._tasks: Dict[str, RunTask] = {}
        self._queue: List[str] = []
        self._running: Set[str] = set()
        self._timers: Dict[str, QTimer] = {}
        self._start_ticks: Dict[str, float] = {}

    # ── Public API ──

    def add_task(self, task: RunTask) -> None:
        self._tasks[task.name] = task
        self.task_added.emit(task)

    def start(self, names: List[str]) -> None:
        for name in names:
            task = self._tasks.get(name)
            if task is None or task.status in ("running", "queued"):
                continue
            task.status = "queued"
            self._queue.append(name)
            self.task_progress.emit(name, 0)
        self._pump()

    def start_all(self) -> None:
        names = [t.name for t in self._tasks.values() if t.status == "idle"]
        if names:
            self.start(names)

    def stop_all(self) -> None:
        for name in list(self._running):
            self._stop_task(name, "stopped")
        for name in list(self._queue):
            task = self._tasks.get(name)
            if task:
                task.status = "stopped"
            self._queue.remove(name)
            self.task_finished.emit(name, "stopped")
        if not self.is_running_any():
            self.all_finished.emit()

    def is_running_any(self) -> bool:
        return bool(self._running or self._queue)

    def clear(self) -> None:
        """Clear all tasks (used when replacing geometry / loading a project)."""
        self.stop_all()
        for timer in self._timers.values():
            timer.stop()
        self._tasks.clear()
        self._queue.clear()
        self._running.clear()
        self._timers.clear()
        self._start_ticks.clear()

    def get_task(self, name: str) -> Optional[RunTask]:
        return self._tasks.get(name)

    def running_names(self) -> List[str]:
        return list(self._running)

    # ── Internals ──

    def _pump(self) -> None:
        while len(self._running) < self._max_concurrent and self._queue:
            self._spawn(self._queue.pop(0))

    def _spawn(self, name: str) -> None:
        task = self._tasks.get(name)
        if task is None:
            return
        task.status = "running"
        task.progress = 0
        self._running.add(name)
        self._start_ticks[name] = time.monotonic()
        self.task_started.emit(name)

        # Call point of the real solver (to be replaced by a QProcess)
        self._spawn_solver(task)

        timer = QTimer(self)
        timer.setInterval(self.STEP_MS)
        timer.timeout.connect(lambda: self._advance(name))
        timer.start()
        self._timers[name] = timer

    def _advance(self, name: str) -> None:
        task = self._tasks.get(name)
        if task is None or name not in self._running:
            return
        task.progress += self.STEP_DELTA
        if task.progress >= 100:
            task.progress = 100
            self._finish(name, "completed")
            return
        self.task_progress.emit(name, task.progress)

    def _finish(self, name: str, status: str) -> None:
        timer = self._timers.pop(name, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        if name in self._running:
            self._running.discard(name)
        task = self._tasks.get(name)
        if task:
            task.status = status
            elapsed = time.monotonic() - self._start_ticks.get(name, 0.0)
            task.run_time = time.strftime("%H:%M:%S", time.gmtime(elapsed))
        self.task_finished.emit(name, status)
        self._pump()
        if not self.is_running_any():
            self.all_finished.emit()

    def _stop_task(self, name: str, status: str) -> None:
        timer = self._timers.pop(name, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        if name in self._running:
            self._running.discard(name)
        task = self._tasks.get(name)
        if task:
            task.status = status
        self.task_finished.emit(name, status)

    def _spawn_solver(self, task: RunTask) -> None:
        """Placeholder for the real rad4space invocation (QProcess launching
        the executable).

        No-op during the shell-building stage; when the solver is wired in:
          1. build the solver inputs from task.gdml_files / task.analysis_type
          2. QProcess.start(exe, args), parse stdout for progress
          3. call _finish(name, 'completed') when it is done
        """
        pass
