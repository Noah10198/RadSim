# 04 · Run Dispatch and Solver Execution

> Source: `core/run_manager.py`, `core/solver_config.py`, `core/mac_builder.py`
> UI: `ui/dialogs/run_monitor.py`

## Contents

- [1. Responsibility](#1-responsibility)
- [2. State machine](#2-state-machine)
- [3. Signals](#3-signals)
- [4. Public API](#4-public-api)
- [5. Queueing and pumping](#5-queueing-and-pumping)
- [6. The real solver path](#6-the-real-solver-path)
- [7. Simulation mode (the fallback without a solver)](#7-simulation-mode-the-fallback-without-a-solver)
- [8. Stopping and cleanup](#8-stopping-and-cleanup)
- [9. Directory conventions](#9-directory-conventions)
- [10. Troubleshooting checklist](#10-troubleshooting-checklist)

## 1. Responsibility

`RunManager` is a **standalone task queue** responsible for:

- accepting a batch of tasks and queueing them;
- starting them one by one up to a concurrency limit (`max_concurrent = 2` by default);
- launching the real solver through `QProcess` (or degrading to simulated progress);
- redirecting the solver's console output into each task's `run.log`;
- broadcasting status and progress to the UI over Qt signals;
- stopping one task or all of them.

It **does not care** how a task was configured: that has already been written onto the `RunTask`
and turned into `run.mac` by `mac_builder` before the start.

## 2. State machine

```
idle ──start()──> queued ──_pump()──> running ──┬─> completed
  ▲                                            ├─> failed
  └────────────────────────────────────────────┴─> stopped
```

| State | Meaning |
|---|---|
| `idle` | created, not queued |
| `queued` | queued, waiting for a concurrency slot |
| `running` | the process has been started (or the simulation timer runs) |
| `completed` | the process exited with code 0 |
| `failed` | non-zero exit code, a failed launch, or a failed macro write |
| `stopped` | stopped by the user |

## 3. Signals

| Signal | Arguments | Emitted when |
|---|---|---|
| `task_added` | `RunTask` | `add_task()` |
| `task_started` | `name` | a task leaves the queue and starts |
| `task_progress` | `name, percent` | on the heartbeat timer |
| `task_finished` | `name, status` | finished / failed / stopped |
| `all_finished` | — | both the queue and the running set are empty |

The monitor windows in `run_monitor.py` subscribe to these signals to refresh their tables and
progress bars; the main window uses `task_finished` to decide when to refresh the result tree.

## 4. Public API

```python
rm = RunManager(parent, max_concurrent=2)

rm.configure_solver(exe, gdml_full_path, out_root)   # bind the real solver
rm.solver_configured() -> bool                        # can it really run?
rm.add_task(task)                                     # register a task
rm.start([names]) / rm.start_all()                    # queue and start pumping
rm.stop_task(name) / rm.stop_all()                    # stop
rm.is_running_any() -> bool
rm.get_task(name) / rm.running_names()
rm.clear()                                            # drop all state (new geometry / project load)
```

In `configure_solver()`, an `exe` of `None` — or one pointing at a missing file — is normalized to
`None` and the run then enters **simulation mode**, which lets the UI flow be exercised on a
machine without the solver.

## 5. Queueing and pumping

```python
def _pump(self):
    while len(self._running) < self._max_concurrent and self._queue:
        self._spawn(self._queue.pop(0))
```

- first in, first out;
- every finished or stopped task triggers another `_pump()`, which fills the free slot;
- calling `start()` again for a task already `running` or `queued` is ignored.

## 6. The real solver path

### 6.1 Before launch

1. `write_workdir(gdml_path, task, out_root)` creates the working directory and writes `run.mac`;
   a failure here is reported as `failed` immediately;
2. the command line carries a single argument: `[<workdir>/run.mac]`;
3. `QProcess.setWorkingDirectory(workdir)` — every relative output of the solver lands in the
   working directory.

### 6.2 Environment variables (the decisive step on Windows)

```python
env = QProcessEnvironment.systemEnvironment()
dll_dirs = runtime_dll_dirs()          # core/solver_config.py
env.insert("PATH", os.pathsep.join(dll_dirs) + os.pathsep + cur)
```

The solver is a Geant4 program linked against the Qt6 DLLs. When the GUI is started from a conda
environment, conda's older Qt6 DLLs are loaded first and the solver fails at start-up
(`0xC0000135`, DLL not found, or `0xC0000139`, entry point not found). Putting the correct Qt `bin`
directory **in front of** `PATH` solves it.

Order used by `runtime_dll_dirs()`: the `solver/qt_bin_dir` configured by the user in **Solver
Setting** first, then the development-machine paths in `DEFAULT_QT_BIN_DIRS`; the list is empty on
non-Windows platforms.

### 6.3 Log redirection

- `setProcessChannelMode(MergedChannels)`: stdout and stderr merged;
- `run.log` is opened in binary mode and `readyReadStandardOutput` → `_read_solver_output()`
  writes and flushes as data arrives;
- when the process ends, `_close_log()` reads the remainder once more and closes the file;
- the path is stored in `task.run_log` (**not persisted** to `project.json`) so that the
  "run log" node in the result tree can open it.

### 6.4 Progress

The progress of a real process is **indeterminate** (Geant4 prints no percentage): the heartbeat
timer adds `+2` every 300 ms, capped at 99, and only reaches 100 once the process exits. The bar
therefore means "still alive", not "this much done".

### 6.5 Finishing

```python
def _on_proc_finished(self, name, code):
    status = "completed" if code == 0 else "failed"
```

`_finish()` stops the heartbeat timer → makes sure the process is gone (`kill` if not) → closes the
log → removes the task from the running set → writes `task.run_time` → emits `task_finished` →
`_pump()` to fill the slot → emits `all_finished` when nothing is left.

`run_time` is measured with `time.monotonic()` and formatted as `HH:MM:SS`.

## 7. Simulation mode (the fallback without a solver)

When `solver_configured()` is false, a `QTimer` (one tick per 200 ms, +10 % per tick) simulates
progress and reports `completed` at 100 %. It exists for UI development and flow testing and
**produces no result files**.

## 8. Stopping and cleanup

| Operation | Behaviour |
|---|---|
| `stop_task(name)` | running: `terminate()`, then `kill()` if it has not exited within 2 s; queued: removed from the queue and marked `stopped` |
| `stop_all()` | applies the logic above to every running and queued task |
| `clear()` | `stop_all()` first, then stop the timers, `kill` any surviving process, close every log handle, and empty the task table / queue / running set |

The main window calls `clear()` when importing new geometry or loading a project, so that the
processes and file handles of the previous project cannot leak into the next one.

## 9. Directory conventions

```
solver/runs/                 # get_results_root(), overridable through QSettings
└── <safe_task_name>/        # safe_task_name = illegal characters replaced by _
    ├── run.mac
    ├── run.log
    ├── out_<mesh>.csv       # realworld / probe
    ├── out_Box_<q>.csv      # voxel
    └── rad4space_h1_*.csv   # 1D histograms
```

Draft output stays in `solver/runs`; saving a project mirrors it into `<project>/results/<task>/`
via `project_io.save_project()` (see [06-project-io.md](06-project-io.md)).

## 10. Troubleshooting checklist

| Symptom | Where to look |
|---|---|
| a task goes `failed` instantly | is the solver path configured correctly, and does `run.log` mention `0xC0000135` / `0xC0000139`? |
| `run.log` is empty | the process never started (`waitForStarted` timed out after 3 s) |
| the progress bar sticks at 99 % | the process is still running; this is normal |
| result files are missing | is the dump command after beamOn, and did the task really reach `completed`? |
| results are mixed up after a re-run | `write_workdir` wipes the task directory, so files placed there by hand are deleted |
