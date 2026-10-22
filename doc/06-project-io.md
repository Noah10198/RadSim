# 06 · Project Save and Load

> Source: `core/project_io.py`, `app/main_window.py` (`_save_project` / `_load_project`)

## Contents

- [1. A project is a folder](#1-a-project-is-a-folder)
- [2. project.json structure](#2-projectjson-structure)
- [3. Save flow](#3-save-flow)
- [4. Load flow](#4-load-flow)
- [5. Draft directory vs project directory](#5-draft-directory-vs-project-directory)
- [6. The task name is the primary key](#6-the-task-name-is-the-primary-key)
- [7. Troubleshooting](#7-troubleshooting)

## 1. A project is a folder

RadSim has no database and no separate configuration-file concept. **A project is a folder you can
copy as a whole**:

```
MyProject/
├── project.json           manifest (geometry references + task list)
├── geometry/
│   └── <imported>.gdml    a copy of the geometry file
└── results/
    └── <safe_task_name>/  a snapshot of each task's run output
        ├── run.mac
        ├── run.log
        ├── out_*.csv
        └── rad4space_h1_*.csv
```

Copy the folder to another machine, install RadSim and the solver, and you can reproduce it as it
was.

## 2. project.json structure

| Field | Meaning |
|---|---|
| `format` | `"radsim-project"`; the legacy value `"3drad-project"` is still accepted |
| `version` | currently `1` |
| `gdml_paths` | the geometry file list. After copying into `geometry/` these are **relative paths**, which is what keeps the project portable |
| `results_root` | the draft results root at save time (used to locate the output on replay) |
| `tasks` | the task array |

Each task object contains:

| Field | Meaning |
|---|---|
| `name` | task name (unique, and the key used by `RunManager`) |
| `analysis_type` | `default` and friends |
| `gdml_files` | the geometry this task references |
| `calculate` | `{n_threads, n_events}` |
| `particle` | particle source configuration (see doc 05) |
| `physics` | physics configuration (see doc 05) |
| `analysis_config` | the configuration of the three analysis modes (see doc 05) |

> Runtime fields (`status`, `progress`, `run_time`, `run_log`) are **not written** to
> `project.json`; they are rebuilt on load by scanning the result files on disk.

## 3. Save flow

There is exactly one entry point: `MainWindow._save_project()`.

1. **Determine the project directory**
   - `self._project_dir is None` → `QFileDialog.getExistingDirectory` asks the user;
   - if the chosen directory already contains `project_file(folder)`, ask whether to overwrite;
   - once decided, **later saves do not ask again** (changing folder means restarting or deleting
     the current project and saving again).
2. **Collect the data**: walk `RunManager._tasks`, serialize each `RunTask` into the fields above,
   and hand them together with `gdml_paths` and `get_results_root()` to
   `core.project_io.save_project()`.
3. **Write to disk** (inside `save_project()`):
   - write `project.json`;
   - **copy** the geometry files into `<project>/geometry/` and rewrite `gdml_paths` as relative
     paths;
   - **mirror** the draft results directory `solver/runs/<task>/` into
     `<project>/results/<task>/`.
4. **Exceptions**: every failure is `try/except`ed → `QMessageBox.warning` + log, without aborting
   the program.

### Why it is a "hard save"

Saving is a **full mirror**, not an incremental patch:

- `geometry/` and `results/` are rewritten from the current state, so a deleted task disappears
  together with its saved results;
- the benefit is that a project folder is always self-consistent and never keeps "ghost results"
  around;
- the cost is that saving takes time proportional to the size of the results — a large result set
  saves slowly.

## 4. Load flow

Entry point: `MainWindow._load_project()`, in this order:

1. **Pre-check**: if `RunManager.is_running_any()` or any task is running, refuse and tell the
   user.
2. **Choose a file**: `QFileDialog.getOpenFileName` on `project.json`.
3. **Clean the draft output** (critical): the draft results root `solver/runs` is **shared by all
   projects**. Before loading, call `clear_task_output(results_root, name)` for every current task
   name, otherwise leftover CSVs from a same-named task of the previous project are read as this
   project's results.
4. **Drop the runtime state**: `_close_task_dialogs()` → `_run_manager.clear()` →
   `_project_tree.clear_tasks()` → `_task_counter = 0`.
5. **Restore the geometry**: call `_replace_gdml()` on `gdml_paths[0]` (which internally goes
   through the same parse + tree + scene path as an import).
6. **Rebuild the tasks**: refill each `RunTask`, re-attach it to the project tree and set the
   "configured" flags of the individual settings.
7. **Restore the results**: `_restore_task_outputs(task)` scans the task's result directory —
   - if `out_*.csv` exists, or the tail of `run.log` contains none of `error` / `fatal` /
     `abnormal` / `failed`, the task counts as finished and its status becomes `completed`;
   - `_refresh_task_results()` then rebuilds the Results subtree from the files on disk and the
     `analysis_config`.
8. **Wrap up**: `_ensure_default_task()` (add one when there is none) → `_sync_mac_preview_tasks()`.

## 5. Draft directory vs project directory

This is the easiest thing to confuse:

| Directory | Role | Written by | Cleared when |
|---|---|---|---|
| `solver/runs/<task>/` | **draft output**, shared by all projects | `RunManager` / `mac_builder.write_workdir` | before every run; on project load, per task name; on task deletion |
| `<project>/results/<task>/` | **project snapshot**, travels with the project | `project_io.save_project` | rewritten from the current task list on every save |

When a result viewer reads, the priority in `MainWindow._result_work_dir(task)` is:

```
the directory of task.run_log  →  get_results_root()/<task>  →  <project>/results/<task>
```

So "just ran but not saved yet" reads the draft directory, while "reopened after saving" reads the
project directory.

## 6. The task name is the primary key

`RunManager._tasks` is a `name → RunTask` dictionary, project-tree nodes are indexed by task name
as well, and the result directory name is the sanitized version of that name. Therefore:

- **task names must be unique**: duplicates overwrite each other's results;
- renaming a task (`_rename_task`) has to update the dictionary key, the tree node, the macro
  preview and the monitors together;
- directory names go through `safe_task_name()`, which replaces illegal characters with `_` — so
  renaming to two different names that sanitize to the same string (`a/b` and `a_b`) shares one
  directory, a known edge case.

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| another project's files appear in the result tree | the draft directory was not cleaned (the normal flow does clean it; copying a result directory by hand can trigger this) |
| saving is slow | a hard save mirrors the whole result directory |
| the project will not open on another machine | `geometry/` is missing, or the relative paths in `project.json` were edited by hand |
| results of a deleted task survive | the task was removed but the files stayed in the project folder — a hard save rewrites `results/`, so check whether the save actually succeeded |
| wanting to move to a different project folder | by design the folder is fixed by the first save; restart, or delete `project.json` and save again |
