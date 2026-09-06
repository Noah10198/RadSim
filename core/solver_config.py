"""
solver_config - path of the rad4space solver executable.

The solver is a Geant4 batch executable invoked per task as
    <solver> <task.mac> [threads]
A user override is persisted with QSettings; when absent a well-known path
under the repository's solver/ folder is used as the default candidate.
"""

import os
from typing import cast

from PyQt6.QtCore import QSettings

APP_ORG = "RadSim"
APP_NAME = "RadSim"
KEY_EXECUTABLE = "solver/executable"
KEY_QT_BIN = "solver/qt_bin_dir"

# Well-known Qt bin directories on this dev machine, used only as a fallback
# probe. A real deployment points the setting at the Qt that the solver was
# built against (or copies the solver's DLLs next to its executable instead).
DEFAULT_QT_BIN_DIRS = [
    r"D:\Application\Qt6.11\6.11.1\msvc2022_64\bin",
]


def _repo_root() -> str:
    # core/ -> RadSim project root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_solver_path() -> str:
    """Return the first existing candidate for the rad4space executable
    (platform aware), or an empty string if none is found."""
    root = _repo_root()
    exe = "rad4space.exe" if os.name == "nt" else "rad4space"
    candidates = [
        os.path.join(root, "solver", "rad4space", "build", "Release", exe),
        os.path.join(root, "solver", "rad4space", "build", exe),
        os.path.join(root, "solver", "rad4space", exe),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return candidates[0]


def get_solver_path() -> str:
    """Return the configured solver path (user override if set, otherwise the
    default candidate)."""
    settings = QSettings(APP_ORG, APP_NAME)
    saved = cast(str, settings.value(KEY_EXECUTABLE, ""))
    if saved:
        return saved
    return default_solver_path()


def set_solver_path(path: str) -> None:
    settings = QSettings(APP_ORG, APP_NAME)
    if path:
        settings.setValue(KEY_EXECUTABLE, path)
    else:
        settings.remove(KEY_EXECUTABLE)


def get_qt_bin_dir() -> str:
    """Return the user-configured Qt runtime (bin) directory for the solver,
    or an empty string when unset."""
    settings = QSettings(APP_ORG, APP_NAME)
    saved = cast(str, settings.value(KEY_QT_BIN, ""))
    return saved.strip()


def set_qt_bin_dir(path: str) -> None:
    settings = QSettings(APP_ORG, APP_NAME)
    if path.strip():
        settings.setValue(KEY_QT_BIN, path.strip())
    else:
        settings.remove(KEY_QT_BIN)


def runtime_dll_dirs() -> "list[str]":
    """Directories that must come first on PATH before launching rad4space.exe.

    The solver is a Geant4 app linking the Qt6 DLLs it was built against. When
    the GUI runs from a conda python, its own (older) Qt DLLs are loaded
    instead and the solver dies at startup with 0xC0000135 (DLL not found) or
    0xC0000139 (entry point not found). Prepending the right Qt bin fixes it:
    the user's setting wins, with the dev-machine candidates as a fallback.
    """
    if os.name != "nt":
        return []
    dirs: "list[str]" = []
    saved = get_qt_bin_dir()
    if saved:
        dirs.append(saved)
    for d in DEFAULT_QT_BIN_DIRS:
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs
