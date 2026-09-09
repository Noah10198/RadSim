"""
project_io - RadSim project save / load (JSON + side files)

A RadSim project is a FOLDER:

    MyProject/
        project.json        config: geometry refs + task list
        geometry/*.gdml     copy of the imported GDML
        results/<task>/     snapshot of each task's run output

project.json stores the geometry path RELATIVE to the project folder, so the
whole folder can be moved or copied without breaking the geometry reference.

Saving is a "hard save": the config is overwritten and each task's draft output
folder is mirrored (full overwrite) into results/. A task whose draft folder
does not exist keeps whatever was saved before - loading a project clears the
draft folders, and an immediate re-save must not wipe the project's results.
"""

import json
import os
import re
import shutil
from typing import Any, Dict, List, Tuple

PROJECT_FILE = "project.json"
GEOMETRY_DIR = "geometry"
RESULTS_DIR = "results"


def safe_task_name(name: str) -> str:
    """Folder name a task's output uses on disk. Mirrors
    mac_builder.write_workdir so the draft folder and the saved copy match."""
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", name or "") or "task"


def project_file(project_dir: str) -> str:
    """Path of project.json inside a project folder."""
    return os.path.join(project_dir, PROJECT_FILE)


def save_project(project_dir: str, *, gdml_paths: List[str],
                 tasks: List[Dict[str, Any]], results_root: str = "") -> str:
    """Write the project into project_dir and return the project.json path.

    Hard save: the folder is made to match the caller's current state exactly.

    - the GDML is copied into <project>/geometry/; geometry files that are no
      longer referenced are removed
    - every task that has a draft output folder under results_root gets its
      output mirrored into <project>/results/<task>/ (full overwrite)
    - results folders that no longer belong to a task are removed, so deleting
      a task in the UI also removes its saved results
    """
    os.makedirs(project_dir, exist_ok=True)
    geom_dir = os.path.join(project_dir, GEOMETRY_DIR)
    os.makedirs(geom_dir, exist_ok=True)

    stored_paths: List[str] = []
    keep_geom: set = set()
    for src in gdml_paths:
        if not src:
            continue
        name = os.path.basename(src)
        dst = os.path.join(geom_dir, name)
        if os.path.isfile(src) and os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        if os.path.isfile(dst):
            stored_paths.append(os.path.join(GEOMETRY_DIR, name))
            keep_geom.add(name)
        else:
            stored_paths.append(src)   # source is gone: keep the absolute ref
    _prune_dir(geom_dir, keep_geom)

    results_dir = os.path.join(project_dir, RESULTS_DIR)
    if results_root:
        keep_results: set = set()
        for td in tasks:
            name = td.get("name") or ""
            if not name:
                continue
            safe = safe_task_name(name)
            keep_results.add(safe)
            src = os.path.join(results_root, safe)
            if os.path.isdir(src):
                _mirror_dir(src, os.path.join(results_dir, safe))
        _prune_dir(results_dir, keep_results)

    data = {
        "format": "radsim-project",
        "version": 1,
        "gdml_paths": stored_paths,
        "tasks": tasks,
    }
    path = project_file(project_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def load_project(path: str) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """Read a project.json. Returns (project_dir, gdml_paths, tasks); relative
    geometry paths are resolved against the project folder."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") not in ("radsim-project", "3drad-project"):
        raise ValueError("Not a valid RadSim project file")
    project_dir = os.path.dirname(os.path.abspath(path))
    raw = data.get("gdml_paths", []) or []
    gdml_paths = [
        p if os.path.isabs(p) else os.path.join(project_dir, p) for p in raw
    ]
    return project_dir, gdml_paths, data.get("tasks", []) or []


def clear_task_output(results_root: str, task_name: str) -> None:
    """Delete a task's DRAFT output folder under the results root.

    Called when a project is loaded: the draft root is shared by every project,
    so results left there by the previously open project would otherwise be
    shown as if they belonged to the project being loaded."""
    if not results_root or not task_name:
        return
    d = os.path.join(results_root, safe_task_name(task_name))
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


def _mirror_dir(src: str, dst: str) -> None:
    """Full overwrite: drop dst, then copy src."""
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)


def _prune_dir(root: str, keep: set) -> None:
    """Remove every entry in root whose name is not in keep.

    Used by the hard save to drop results of deleted tasks and geometry files
    the project no longer references."""
    if not os.path.isdir(root):
        return
    for entry in os.listdir(root):
        if entry in keep:
            continue
        path = os.path.join(root, entry)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
