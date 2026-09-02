"""
project_io - 3dRad project save / load (JSON)

Saved content:
  - Geometry file paths (3dRad allows a single GDML file)
  - Task list (name / analysis type / calculation settings / linked geometry)
"""

import json
from typing import Any, Dict, List, Tuple


def save_project(path: str, *, gdml_paths: List[str],
                 tasks: List[Dict[str, Any]]) -> None:
    data = {
        "format": "3drad-project",
        "version": 1,
        "gdml_paths": gdml_paths,
        "tasks": tasks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_project(path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "3drad-project":
        raise ValueError("Not a valid 3dRad project file")
    return data.get("gdml_paths", []), data.get("tasks", [])
