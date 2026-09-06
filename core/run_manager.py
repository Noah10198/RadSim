"""
RunManager - RadSim multi-task run manager

Independent task queue with a concurrency cap (max_concurrent). A task either
runs through a REAL solver process (when the rad4space executable is available)
or - as a fallback for UI development when no solver can be launched - through
a simulated progress timer.

Real solver path (configured by the main window before running):
    RunManager.configure_solver(exe, gdml_full_path, out_root)
    exe          absolute path to rad4space.exe (or None -> simulate)
    gdml_path    absolute path of the imported GDML
    out_root     directory under which each task gets its own work dir

When configured, _spawn_solver() builds the run.mac (core.mac_builder) and
launches the solver with QProcess. Every run parameter (thread count, event
count, scoring, ...) is written INTO the macro file itself, so the executable
is started with run.mac as its only argument - a single file tells the whole
story of the run.
"""

import os
import time
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from core.project_model import RunTask
from core.solver_config import runtime_dll_dirs


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
        self._procs: Dict[str, QProcess] = {}
        self._start_ticks: Dict[str, float] = {}
        # open binary handles of each running task's run.log (solver console)
        self._log_files: Dict[str, object] = {}

        # real solver wiring (None until configure_solver() is called)
        self._solver_exe: Optional[str] = None
        self._gdml_path: Optional[str] = None
        self._out_root: Optional[str] = None

    # ── Solver configuration (real process mode) ──
    def configure_solver(self, exe: Optional[str], gdml_path: Optional[str],
                         out_root: Optional[str]) -> None:
        """Give the manager the real solver inputs. exe may be None (or a
        non-existent path) to fall back to simulated progress."""
        self._solver_exe = exe if exe and os.path.isfile(exe) else None
        self._gdml_path = gdml_path
        self._out_root = out_root

    def solver_configured(self) -> bool:
        return self._solver_exe is not None and self._gdml_path is not None

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

    def stop_task(self, name: str) -> None:
        """Cancel a single task (running or queued)."""
        if name in self._running:
            self._stop_task(name, "stopped")
            self._pump()
        elif name in self._queue:
            self._queue.remove(name)
            task = self._tasks.get(name)
            if task:
                task.status = "stopped"
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
        self._timers.clear()
        for proc in self._procs.values():
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
        self._procs.clear()
        for logf in self._log_files.values():
            try:
                logf.close()
            except OSError:
                pass
        self._log_files.clear()
        self._tasks.clear()
        self._queue.clear()
        self._running.clear()
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

        if self.solver_configured():
            # real solver: launching the process drives completion
            self._launch_solver(task)
        else:
            # simulation fallback (no solver available for development)
            self._spawn_solver_simulated(task)

    # ---- simulated path (kept as the no-solver fallback) ----
    def _spawn_solver_simulated(self, task: RunTask) -> None:
        timer = QTimer(self)
        timer.setInterval(self.STEP_MS)
        timer.timeout.connect(lambda: self._advance(task.name))
        timer.start()
        self._timers[task.name] = timer

    def _advance(self, name: str) -> None:
        task = self._tasks.get(name)
        if task is None or name not in self._running:
            return
        if name in self._procs:
            # a real process exists - this timer is only a heartbeat
            if self._procs[name].state() == QProcess.ProcessState.Running:
                return
        task.progress += self.STEP_DELTA
        if task.progress >= 100:
            task.progress = 100
            self._finish(name, "completed")
            return
        self.task_progress.emit(name, task.progress)

    # ---- real solver path ----
    def _launch_solver(self, task: RunTask) -> None:
        from core.mac_builder import write_workdir
        try:
            work = write_workdir(self._gdml_path, task, self._out_root)
        except Exception as e:
            self._logger_err(task.name, f"failed to write run macro: {e}")
            self._finish(task.name, "failed")
            return

        # All configuration (threads, events, scoring) is embedded in the
        # macro itself - start the solver with run.mac as the only argument.
        args = [os.path.join(work, "run.mac")]

        proc = QProcess(self)
        proc.setWorkingDirectory(work)
        # Prepend the machine Qt6 bin to PATH so the solver loads the local Qt
        # DLLs instead of a conda python's older ones (0xC0000135/0xC0000139).
        env = QProcessEnvironment.systemEnvironment()
        dll_dirs = runtime_dll_dirs()
        if dll_dirs:
            cur = env.value("PATH", "")
            env.insert("PATH", os.pathsep.join(dll_dirs) +
                       (os.pathsep + cur if cur else ""))
        proc.setProcessEnvironment(env)
        proc.finished.connect(
            lambda code, _s, n=task.name: self._on_proc_finished(n, code))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Redirect the solver console (stdout+stderr merged) into run.log next
        # to run.mac so every run keeps a verifiable record; the main window
        # exposes it as a viewable node under the task's Results.
        log_path = os.path.join(work, "run.log")
        task.run_log = log_path
        try:
            logf = open(log_path, "wb")
        except OSError as e:
            self._logger_err(task.name, f"cannot create run.log: {e}")
            logf = None
        if logf is not None:
            self._log_files[task.name] = logf
        proc.readyReadStandardOutput.connect(
            lambda n=task.name: self._read_solver_output(n))
        proc.start(self._solver_exe, args)
        if not proc.waitForStarted(3000):
            self._logger_err(task.name,
                             f"failed to start {self._solver_exe}")
            self._finish(task.name, "failed")
            return
        self._procs[task.name] = proc

        # heartbeat for the progress bar (bounded so it never auto-completes)
        timer = QTimer(self)
        timer.setInterval(300)
        timer.timeout.connect(lambda: self._emit_progress(task.name))
        timer.start()
        self._timers[task.name] = timer

    def _emit_progress(self, name: str) -> None:
        task = self._tasks.get(name)
        if task is None or name not in self._running:
            return
        proc = self._procs.get(name)
        pct = 0
        if proc is not None and proc.state() == QProcess.ProcessState.Running:
            # indeterminate pulse while the process is alive
            task.progress = min(99, task.progress + 2)
            pct = task.progress
        self.task_progress.emit(name, pct)

    def _read_solver_output(self, name: str) -> None:
        """Append whatever the solver printed to the task's run.log."""
        proc = self._procs.get(name)
        logf = self._log_files.get(name)
        if proc is None or logf is None:
            return
        data = proc.readAllStandardOutput()  # merged stdout+stderr bytes
        if data:
            try:
                logf.write(bytes(data))
                logf.flush()
            except OSError as e:
                self._logger_err(name, f"run.log write failed: {e}")

    def _close_log(self, name: str, proc=None) -> None:
        """Flush any buffered solver output and close the task's run.log."""
        logf = self._log_files.pop(name, None)
        if logf is None:
            return
        try:
            if proc is not None:
                data = proc.readAllStandardOutput()
                if data:
                    logf.write(bytes(data))
            logf.close()
        except OSError as e:
            self._logger_err(name, f"run.log finalize failed: {e}")

    def _on_proc_finished(self, name: str, code: int) -> None:
        status = "completed" if code == 0 else "failed"
        if status == "failed":
            self._logger_err(name, f"solver exited with code {code}")
        self._finish(name, status)

    def _logger_err(self, name: str, msg: str) -> None:
        # lightweight stderr (main window UI normally logs; keep a console echo)
        print(f"[{name}] {msg}")

    def _finish(self, name: str, status: str) -> None:
        timer = self._timers.pop(name, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        proc = self._procs.pop(name, None)
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()
        self._close_log(name, proc)
        if name in self._running:
            self._running.discard(name)
        task = self._tasks.get(name)
        if task:
            task.status = status
            elapsed = time.monotonic() - self._start_ticks.get(name, 0.0)
            task.run_time = time.strftime("%H:%M:%S", time.gmtime(elapsed))
            task.progress = 100 if status == "completed" else task.progress
        self.task_finished.emit(name, status)
        self._pump()
        if not self.is_running_any():
            self.all_finished.emit()

    def _stop_task(self, name: str, status: str) -> None:
        timer = self._timers.pop(name, None)
        if timer:
            timer.stop()
            timer.deleteLater()
        proc = self._procs.pop(name, None)
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            proc.terminate()
            if not proc.waitForFinished(2000):
                proc.kill()
        self._close_log(name, proc)
        if name in self._running:
            self._running.discard(name)
        task = self._tasks.get(name)
        if task:
            task.status = status
        self.task_finished.emit(name, status)
