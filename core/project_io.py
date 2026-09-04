"""
project_io - RadSim project save / load (JSON)

Saved content:
  - Geometry file paths (RadSim allows a single GDML file)
  - Task list (name / analysis type / calculation settings / linked geometry)
"""

import json
from typing import Any, Dict, List, Tuple


def save_project(path: str, *, gdml_paths: List[str],
                 tasks: List[Dict[str, Any]]) -> None:
    data = {
        "format": "radsim-project",
        "version": 1,
        "gdml_paths": gdml_paths,
        "tasks": tasks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_project(path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") not in ("radsim-project", "3drad-project"):
        raise ValueError("Not a valid RadSim project file")
    return data.get("gdml_paths", []), data.get("tasks", [])
