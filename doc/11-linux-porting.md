# RadSim Cross-Platform Porting Guide: Windows → Ubuntu / Linux

> Nature: **analysis document (forward-looking plan), no code changes.**
>
> Goal: make RadSim work on both Windows and Ubuntu/Linux. This document only answers "**what needs to change, why, and in which direction**"; it does not provide implementations.

## Contents

- [0. Executive Summary](#0-executive-summary)
- [1. Severity Overview](#1-severity-overview)
- [2. Module-by-Module Analysis](#2-module-by-module-analysis)
- [3. Proposed Change List (grouped by file)](#3-proposed-change-list-grouped-by-file)
- [4. Proposed Platform Compatibility Layer](#4-proposed-platform-compatibility-layer)
- [5. Ubuntu Environment Setup Checklist](#5-ubuntu-environment-setup-checklist)
- [6. Acceptance Checklist](#6-acceptance-checklist)
- [7. Risks and Unverified Items](#7-risks-and-unverified-items)
- [8. Deep Dive: Solving VTK Window Embedding on Ubuntu](#8-deep-dive-solving-vtk-window-embedding-on-ubuntu)
- [Appendix: Relation to Other Documents](#appendix-relation-to-other-documents)

---

## 0. Executive Summary

**Overall assessment: the Python layer ports well. The real work is in two places — rebuilding the solver, and the graphics context / fonts.**

| Conclusion | Notes |
|---|---|
| ✅ Python code is portable overall | Paths use `os.path`/`os.pathsep`; no `subprocess`/`shell=True`/`os.startfile`; file I/O mostly has `encoding="utf-8"`; `QProcess`/`QSettings`/`QThread` are all cross-platform APIs |
| 🔴 1 functional failure | `core/solver_config.py` runtime library injection only handles Windows `PATH`; on Linux it returns an empty list (`LD_LIBRARY_PATH` unhandled) |
| 🔴 1 mandatory rebuild | `solver/rad4space/build/` is an MSVC artifact; Linux must rebuild it, and it links against Qt6/OpenGL/X11 |
| 🔴 1 architectural risk | VTK uses the **deprecated** `QVTKRenderWindowInteractor` + `WId` native window embedding, which is very likely unusable under Wayland |
| 🟠 1 cosmetic issue | Icons rely entirely on emoji + `Segoe UI Emoji`; Ubuntu without that font shows boxes/blanks |
| 🟡 A batch of medium/low risks | Hard-coded local Qt directory, `Qt6Core.dll` probing, default output directory inside the repo, GDML paths with spaces in `run.mac`, encoding/newline details |
| ✅ Can be reused as-is | `core/` GDML parsing/writing/expression evaluation, `mac_builder` numeric formatting (`%g` is locale-independent), result CSV parsing, project JSON, logging, Ribbon/theme/QSS |

**Effort estimate**: environment 0.5 day; Linux solver rebuild 1–2 days; platform compatibility layer + fonts/icons 1–2 days; VTK window approach validation 1–3 days.

---

## 1. Severity Overview

| Level | Meaning | Count |
|---|---|---|
| 🔴 Blocking | Core functionality unusable unless resolved | 3 |
| 🟠 High | Functionality silently fails or clearly misbehaves | 5 |
| 🟡 Medium | UX / consistency / edge cases | 9 |
| 🟢 Low | Copy, portability polish | 8 |

---

## 2. Module-by-Module Analysis

### 2.1 Runtime Environment and Dependencies

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `environment.yml:1-176` | A Windows conda snapshot named `pyoccenv`, with `win-64` build hashes (`h70ea87e`, etc.), including `vc=14.3`, `ucrt`, `vs2015_runtime`, `mkl` | Linux **cannot reproduce it directly**. Need `environment.linux.yml` (drop build hashes so conda re-solves); confirm linux-64 versions of `vtk=9.3.1`/`qt6-main`/`pyqt` | 🟠 High |
| `environment.yml:89,104` | `occt`, `pythonocc-core` | Zero imports in RadSim code, but **the suite contains a dedicated OCC program, so the environment must stay unified → must keep**. On Linux, confirm conda `pythonocc-core` linux-64 availability and system deps (`libGL`/`libGLU`/`libXmu`/`libXi`, etc.) | 🟡 Medium |
| `environment.yml:145,166,169` | `gmsh`, `pyqtgraph`, `pyvista` | Not referenced by RadSim; keep if other suite programs use them, otherwise removable | 🟢 Low |
| `requirements.txt:12-18` | `PyQt6==6.4.2`/`vtk==9.3.1`/`numpy==2.2.6`/`matplotlib==3.10.7` | All have linux-64 wheels; but the PyQt6 manylinux wheel depends on system `libxcb-*`, `libEGL`, `libxkbcommon`, etc. (see chapter 5) | 🟡 Medium |
| `doc/10-troubleshooting.md` | Only documents the Windows environment (Qt DLL conflicts, `0xC0000135/0xC0000139`) | Should add a Linux section: `libGL error`, Wayland, fonts, `LD_LIBRARY_PATH` | 🟢 Low |

> **About the environment name `pyoccenv`**: this name, along with `occt` / `pythonocc-core` / `gmsh` / `pyvista` / `pyqtgraph` in `environment.yml`, comes from the gdmleditor / cad2gdml lineage. **RadSim's Python code has zero imports of OCC/pythonocc** (a full-text search for `import OCC` / `from OCC` / `pythonocc` returns 0); its 3D view uses **VTK** (`vtkmodules`). The "same style as OCC's Viewer3d" comment in `ui/vtk_widget.py` is a style homage (copying cad2gdml's display behavior), not OCC code.
> **But do not delete these packages because of this**: the deliverable is a complete suite with a dedicated OCC program, and the environment must stay unified. For RadSim itself, OCC is irrelevant to "whether 3D display works on Linux"; and the OCC side has the **same class of problem** under Wayland — see [8.2](#82-the-occ-side-has-the-same-limitation-important).

### 2.2 Solver rad4space (**the heaviest item**)

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `solver/rad4space/build/` | The repo commits **MSVC artifacts**: `*.vcxproj`, `rad4space.dir/Release/*.obj`, `*.tlog`, `Release/rad4space.exe`; the tlog hard-codes a local Geant4 path | **Completely unusable on Linux**; must create a new `build-linux/` and rebuild. The repo root has **no `.gitignore`**, so build artifacts are tracked together — add `.gitignore` first | 🔴 Blocking |
| `solver/rad4space/CMakeLists.txt:11-16` | `option(WITH_GEANT4_UIVIS ... ON)` + `find_package(Geant4 REQUIRED ui_all vis_all)` | `ui_all vis_all` pulls the **Qt6 visualization driver** into the link, which on Linux also needs Qt6+OpenGL+X11 at runtime. The GUI only uses batch, so consider `-DWITH_GEANT4_UIVIS=OFF` to shrink the dependency surface | 🟠 High |
| `solver/rad4space/rad4space.cc:27-28,41-42,79-86` | Unconditional `#include "G4UIExecutive.hh"`/`"G4VisExecutive.hh"`; `new G4UIExecutive(argc, argv, "Qt")` when `argc==1`; `new G4VisExecutive` only in interactive mode | To fully remove the Qt dependency, adding a CMake switch **is not enough**: these two includes and the `"Qt"` session must be wrapped in `#ifdef` (C++ changes requiring separate review) | 🟡 Medium |
| `solver/rad4space/rad4space.cc:42` | Interactive mode explicitly uses a `"Qt"` session | With no Qt session on Linux it degrades/errors; but the GUI goes through batch (`argc==2`) and never triggers it, so **not blocking** | 🟢 Low |
| Build command | README uses `--config Release` (MSVC multi-config generator) | Linux Makefiles/Ninja default to **single-config**: the artifact lands at `build-linux/rad4space` with **no `Release/` subdirectory** | 🟠 High |
| Executable bit | No such concept on Windows | The compiled `rad4space` needs `+x`; it can be lost when transferred via archive/cloud drive/git | 🟠 High |

### 2.3 Solver Launch and Runtime Libraries (**core functionality failure point**)

| Location | Current state | Problem on Linux | Suggested direction | Level |
|---|---|---|---|---|
| `core/solver_config.py:109-127` `runtime_dll_dirs()` | First line `if os.name != "nt": return []`, so always empty on Linux; the rest "prepends Qt bin to `PATH`" | **The Linux dynamic linker does not read `PATH`, only `LD_LIBRARY_PATH` (or rpath/ld.so.conf)**. When `libQt6Core.so.6`, `libG4*.so`, `libxerces-c-3.3.so` are missing it exits with `error while loading shared libraries` | Inject per platform: Windows uses `PATH`, Linux uses `LD_LIBRARY_PATH`; directory sources remain "user setting first + candidate fallback" | 🔴 Blocking |
| `core/run_manager.py:211-217` | `env.insert("PATH", os.pathsep.join(dll_dirs) + ...)` | Same as above: **completely ineffective** for dynamic libraries on Linux, i.e. does nothing | Choose `PATH`/`LD_LIBRARY_PATH` per platform; injecting both is acceptable | 🔴 Blocking |
| `core/solver_config.py:24-26` `DEFAULT_QT_BIN_DIRS` | Hard-codes `r"D:\Application\Qt6.11\6.11.1\msvc2022_64\bin"` | The directory does not exist on Linux (filtered out by `isdir`, no crash), but it effectively means **no fallback candidate** | Provide candidates per platform (`/usr/lib/x86_64-linux-gnu`, `/opt/Qt/6.*/gcc_64/lib`, conda env `lib/`), or switch to a "solver-adjacent `lib/`" convention | 🟠 High |
| `core/solver_config.py:38-43` `default_solver_path()` | Already picks `rad4space.exe`/`rad4space` by `os.name`; candidates `build/Release/`, `build/`, `rad4space/` | Candidates are mostly fine, but a single-config Linux build more likely lands in `build-linux/`; and it only checks `isfile`, not the executable bit | Add `build-linux/`, `build/bin/`; use `os.access(path, os.X_OK)` | 🟡 Medium |
| `core/run_manager.py:65` | `self._solver_exe = exe if exe and os.path.isfile(exe) else None` | On Linux a file that exists but has **no `+x`** is still considered valid; after `QProcess` fails to launch, `None` degenerates into "simulated progress", easily producing "looks like it's running but isn't" | Add an executable-bit check; distinguish "missing/unexecutable" in logs | 🟠 High |
| `core/run_manager.py:235-240` | `proc.start(exe, args)` + `waitForStarted(3000)` | 3 seconds is short on slow/network disks; on Linux, when the binary forks successfully but the loader fails, `waitForStarted` still returns true, so you must rely on exit codes 127/126 | Loosen the timeout appropriately; make error messages platform-aware | 🟡 Medium |
| `core/run_manager.py` error text | Bound to `0xC0000135`/`0xC0000139` (Windows DLL error codes) | The Linux counterparts are exit code **127** (`.so` not found) / **126** (no execute permission) | Split text and diagnostic branches by platform | 🟢 Low |
| `core/run_manager.py:307,329-331` | Stop: `terminate()`, then `kill()` after 2 seconds | Semantics are correct (SIGTERM→SIGKILL). But Geant4 does not handle SIGTERM by default, so output may be incomplete; and if child processes are spawned, `kill()` only kills the main process | Optional: use a process group/`setsid` on Linux so the whole group exits | 🟡 Medium |
| `core/run_manager.py:220,268-271` | `MergedChannels` + binary writes to `run.log` | Cross-platform OK. But on Linux, stdout through a pipe is **fully buffered (4 KB)**, so `readyReadStandardOutput` may not fire for a long time and progress heartbeat looks "stuck" | Optional: wrap the launch with `stdbuf -o0 -e0`, or have the solver flush periodically | 🟡 Medium |

### 2.4 VTK / OpenGL / Window Embedding (**architectural risk**)

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `ui/vtk_widget.py:24` | `from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor` | A VTK **deprecated** legacy class that works by binding the render window to Qt's native window ID (Windows HWND / X11 XID). Wayland **has no stable native window ID to embed**, so it is basically unusable | 🔴 Blocking (Wayland) |
| `ui/vtk_widget.py:229-262` `_ensure_window_bound()` | `int(winId())` + `rw.SetWindowInfo(str(wid))` + `rw.Finalize()` rebind when needed | The principle holds under X11 (XID is a decimal integer), but the problem described in the comment (`wglMakeCurrent failed`) is Windows-specific; on Linux `Finalize()` destroys the GLX/EGL context and timing conflicts can cause a black screen | 🟠 High |
| `ui/vtk_widget.py:120,203-209,622-627` | `Initialize()`, `SetSwapControl(0)` to disable vsync | `SetSwapControl` is already wrapped in try/except, safe; under Linux/Mesa it may silently do nothing, and vsync behavior differs from Windows | 🟢 Low |
| `ui/vtk_widget.py:130-188` | First probes with `SetOffScreenRendering(False)`, regex-parses vendor/renderer/version from `ReportCapabilities()`; on failure falls back to `SetOffScreenRendering(True)` software rendering | The logic is portable, but on Linux with no GPU/no DISPLAY, `Render()` may throw rather than return empty; the software fallback needs Mesa (`libGL`+llvmpipe) or OSMesa | 🟡 Medium |
| `ui/vtk_widget.py:32-38` | Explicitly imports `vtkRenderingOpenGL2`/`vtkRenderingVolumeOpenGL2` | Also needed on Linux — **just keep it** | ✅ |
| Platform selection | The code never sets `QT_QPA_PLATFORM` | Under Ubuntu GNOME's default Wayland session it most likely fails to start. Short term: force `QT_QPA_PLATFORM=xcb` (XWayland); long term: migrate to `QVTKOpenGLNativeWidget` + `vtkGenericOpenGLRenderWindow` | 🔴 Blocking (Wayland) |
| Headless/remote | Not handled | With no display, need `xvfb-run`, or `LIBGL_ALWAYS_SOFTWARE=1` + Mesa software rendering | 🟡 Medium |

> **Recommended path**: first get it running and accepted under X11/XWayland with `QT_QPA_PLATFORM=xcb`, then evaluate replacing internals of `VtkWidget` with `QVTKOpenGLNativeWidget` (the public API `get_scene/build_scene/render` can stay unchanged; changes are confined to `ui/vtk_widget.py`, and callers need no modification).

### 2.5 UI Appearance and Fonts

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `ui/ribbon_toolbar.py:16-28` `_create_emoji_icon()` | Uses `QFont("Segoe UI Emoji", 48)` to draw emoji into a `QPixmap` as an icon | Ubuntu has **no Segoe UI Emoji** by default; without a color emoji font, Ribbon icons (📁🧾💾🎯▶️🟢⏹⚙️☀️❓) become **blank/boxes** | 🟠 High |
| `ui/ribbon_toolbar.py:202` | QSS `font-family: "Segoe UI", "Arial", sans-serif` | Qt falls back when the font is missing without crashing, but weight/letter-spacing differ | 🟢 Low |
| `app/main_window.py:114-124,285` | Log/macro preview uses `"Consolas", "Courier New", monospace` | No Consolas on Linux; need `DejaVu Sans Mono`/`Noto Sans Mono` fallback, otherwise monospace effect is lost | 🟡 Medium |
| Chinese display | UI copy is all English, but project/task names/paths may contain Chinese | Without a Chinese font installed (`fonts-noto-cjk`), Chinese becomes boxes | 🟡 Medium |
| `ui/probe_chart_dialog.py:15-25` | `matplotlib.use("QtAgg")` | Portable; but when chart labels contain Chinese, matplotlib's default font has no CJK → boxes; needs `font.sans-serif` config | 🟡 Medium |

**Suggested direction**: do not let icons depend on an emoji font — the safest is to change the Ribbon icons to SVG/PNG resources shipped with the package (loaded directly by `QIcon`), keeping an "emoji font fallback chain" as a backstop; set a platform-based `QFont` fallback list at startup.

### 2.6 Files, Paths, and Permissions

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `core/mac_builder.py:322` | `f"/rad4space/gdml/SetGDMLFile {gdml_full_path}"` | Geant4 macro commands **split arguments on spaces**. A path with spaces (`/home/me/My Documents/a.gdml`) gets truncated, and the solver reads a wrong path and fails | 🟠 High |
| `core/mac_builder.py:367-371` | `re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name)`, then `rmtree`+`makedirs` | Windows filesystems are case-insensitive, Linux is **case-sensitive**: `Task` and `task` are one directory on Windows but two on Linux. Migrating projects across platforms may make result directories "not match" | 🟡 Medium |
| `core/mac_builder.py:370` | `shutil.rmtree(work, ignore_errors=True)` | On Linux, when old result files are read-only or the directory is not writable, `ignore_errors` **silently keeps the old files**, causing "new results mixed with old results" | 🟡 Medium |
| `core/project_io.py:66,133,148` | `shutil.copy2/copytree/rmtree`; `copytree` preserves source permissions | On Linux a read-only source makes the copy read-only too, and a later `rmtree` may fail and be swallowed by `ignore_errors` | 🟢 Low |
| `core/project_io.py:64` | `os.path.basename(src)` as the in-project geometry filename | Same-named GDML from different directories overwrite each other (affects both platforms; easier to hit on Linux) | 🟢 Low |
| Symbolic links | No handling | The project directory may be a symlink; `os.path.abspath` does not resolve links, so `abspath(src) != abspath(dst)` may be misjudged | 🟢 Low |
| `app/main_window.py:1169` | `QDesktopServices.openUrl(QUrl.fromLocalFile(work))` | **Portable**; Linux goes through `xdg-open`; just confirm `xdg-utils` is installed | ✅ |

### 2.7 Text Encoding and Line Endings

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `core/gdml_parser.py:91` | `ET.parse(filepath)` | Honors the XML-declared encoding — **correct** | ✅ |
| `core/gdml_parser.py:96` | `open(filepath, "r", encoding="utf-8")` reads only the first-line declaration | If the GDML is actually latin-1/GBK, it throws `UnicodeDecodeError` and import fails (more likely on Linux with non-UTF-8 GDML produced by third-party tools) | 🟡 Medium |
| `core/gdml_writer.py:152`, `core/mac_builder.py:372`, `core/project_io.py:96` | Uniform `encoding="utf-8"` | Correct | ✅ |
| Result reading | `ui/probe_result_viewer.py:33,93`, `ui/voxel_result_viewer.py:619`, `ui/dialogs/result_viewer.py:184` text mode without `newline=""` | Linux emits `\n` and universal newlines handles it — **not blocking**; only when `\r\n` appears can manual `split(",")` leave a trailing `\r` (already covered by `strip()`) | 🟢 Low |
| `ui/trajectory_viewer.py:127` | `newline=""` + `csv.DictReader` | **Correct**; the recommended form | ✅ |
| `core/mac_builder.py:106-107` `_num()` | `"%g" % v` | Python `%` formatting is **not locale-affected** (always `.` as decimal point), safe even under German/French locales on Linux | ✅ |
| Macro line endings | `build_mac_text` uses `"\n".join()` | Geant4 accepts both line endings | ✅ |

### 2.8 Processes and Threads

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `app/main_window.py:180-182,585-600` | Large GDML (≥500 KB) uses `QThread`+`_ImportWorker` | Cross-platform OK; on Linux `quit()+wait()` is equally required, and the existing `all_done` handling covers it | ✅ |
| `core/run_manager.py:220` | `MergedChannels` | Cross-platform OK | ✅ |
| `core/run_manager.py:307,329-331` | `kill()`/`terminate()` | Semantics correct; see 2.3 regarding SIGTERM and process groups | 🟡 Medium |
| `RunManager(max_concurrent=2)` | 2 concurrent solver processes | On Linux each process consumes all cores by default (`G4GetNumberOfCores()`), so two tasks fight over CPU; also `realWorldLogVol` scoring is inaccurate under MT. **Platform-independent, but more visible on many-core servers** | 🟡 Medium |

### 2.9 Configuration Persistence and User Directories

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `core/solver_config.py:15-19,53` | `QSettings("RadSim", "RadSim")` | Cross-platform API, but the **storage location differs**: Windows writes the registry, Linux writes `~/.config/RadSim/RadSim.conf`; migrating user config requires manual export/rebuild | 🟢 Low |
| `core/solver_config.py:60-63` `default_results_root()` | `_repo_root()/solver/runs` | If installed under `/opt`, `/usr/local`, or a read-only directory, or if **multiple users share one installation**, the default output directory is not writable → all runs fail | 🟠 High |
| `ui/dialogs/solver_setting_dialog.py:147,154` | `os.path.expanduser("~")` | Portable | ✅ |
| `core/solver_config.py` key name | `solver/qt_bin_dir` (Windows semantics) | On Linux it should be understood as "extra library directory"; keep the key name for compatibility and change only the UI copy | 🟢 Low |

### 2.10 Solver Settings Dialog (misleading functionality)

| Location | Current state | Problem on Linux | Level |
|---|---|---|---|
| `ui/dialogs/solver_setting_dialog.py:171-175` | Uses the existence of `Qt6Core.dll` to decide whether "the Qt runtime directory is valid" | On Linux `Qt6Core.dll` is never found → **the field always shows "not found"**, and the user cannot tell whether the setting is correct | 🟠 High |
| `ui/dialogs/solver_setting_dialog.py:48` | Placeholder `rad4space.exe` | Copy | 🟢 Low |
| `ui/dialogs/solver_setting_dialog.py:73` | Placeholder `…\msvc2022_64\bin` | Copy; should give a Linux example | 🟢 Low |
| `ui/dialogs/solver_setting_dialog.py:109-116` | Explanatory text mentions only DLLs | Should add `.so`/`LD_LIBRARY_PATH` | 🟢 Low |
| `ui/dialogs/solver_setting_dialog.py:134-138` | Already switches the file filter by `os.name` (`*.exe` vs all) | **Correct**, keep it | ✅ |
| `ui/dialogs/solver_setting_dialog.py:30-32` | `WindowContextHelpButtonHint` | This flag is ignored under X11 with no side effects | ✅ |

### 2.11 Packaging and Distribution

| Item | Windows current state | What Linux needs | Level |
|---|---|---|---|
| Build artifacts | No `.gitignore`; `build/` and `*.exe` are committed | Add `.gitignore` excluding `build*/`, `*.o`, `*.so`, `__pycache__/`; use a separate build directory on Linux | 🟡 Medium |
| Distribution form | No PyInstaller/Nuitka config seen | conda-pack or PyInstaller; add a `.desktop` file, icon (PNG/SVG), and `Exec`/`Icon` paths | 🟡 Medium |
| Install location | Double-click run from the user directory | If installed to a system directory, handle write permissions for `default_results_root()` (see 2.9) | 🟠 High |
| Dependency completeness | The conda environment includes all runtimes | On Linux, ensure Geant4 data files (`G4LEDATA`, `G4ENSDFSTATEDATA`, etc.) are installed with the environment, otherwise the solver errors at runtime | 🟠 High |

### 2.12 Parts Confirmed to Need **No** Changes (safe)

- `core/gdml_parser.py` / `gdml_tree.py` / `gdml_evaluator.py` / `gdml_writer.py` / `gdml_agent.py`: pure XML/DOM logic, platform-independent.
- `core/materials_lib.py`: pure data dict and JSON I/O (note: `data/element.xml`, `data/nist.txt` are currently **not referenced by the code**, so they are not a blocker on Linux).
- `core/project_model.py`: paths joined uniformly via `os.path.join`; no hard-coded separators.
- `core/logger.py`: standard logging + file handler.
- `vtk_engine/`: `VtkScene`/`VtkSolidFactory` only operate on VTK data objects and never touch native windows.
- Theme/QSS and Ribbon layout logic: platform-independent apart from font names.
- `ui/dialogs/*` file pickers: all use `QFileDialog` + `os.name` branches.

---

## 3. Proposed Change List (grouped by file)

> Priority: **P0** = won't run without it; **P1** = runs but behaves wrong; **P2** = UX/consistency; **P3** = polish.

| Priority | File | Key location | What to change (direction) |
|---|---|---|---|
| P0 | `core/solver_config.py` | `109-127` | Add a Linux branch to `runtime_dll_dirs()`; deliver library directories to `PATH` / `LD_LIBRARY_PATH` per platform |
| P0 | `core/run_manager.py` | `211-217` | Same as above; inject via `QProcessEnvironment` per platform |
| P0 | `core/solver_config.py` | `24-26` | Change `DEFAULT_QT_BIN_DIRS` to a per-platform candidate list |
| P0 | `solver/rad4space/build/` | whole directory | Do not reuse; create `build-linux/` and rebuild on Linux, and add `.gitignore` |
| P0 | Startup entry | — | Set `QT_QPA_PLATFORM=xcb` on Linux/Wayland (or replace the legacy interactor with `QVTKOpenGLNativeWidget`) |
| P1 | `core/solver_config.py` | `38-43,60-63` | Add `build-linux/` to solver candidates; `os.access(..., X_OK)`; make `default_results_root()` fall back to the XDG directory when the install directory is not writable |
| P1 | `core/run_manager.py` | `65,235-240` | Executable-bit check; platform-specific startup failure messages |
| P1 | `ui/dialogs/solver_setting_dialog.py` | `171-175` | Make the probe target platform-specific (`Qt6Core.dll` / `libQt6Core.so.6`) |
| P1 | `ui/ribbon_toolbar.py` | `16-28` | Change icons to packaged SVG/PNG resources, or add a font fallback chain and availability detection |
| P1 | `core/mac_builder.py` | `322` | Handle spaces in the `SetGDMLFile` path (quote/escape, or copy the GDML into the working directory and use a relative filename) |
| P1 | `solver/rad4space/CMakeLists.txt` | `11-16` | Evaluate `WITH_GEANT4_UIVIS=OFF` with the accompanying `#ifdef` changes in `rad4space.cc` |
| P2 | `app/main_window.py` | `114-124,285` | Add a Linux fallback for the monospace font |
| P2 | `ui/ribbon_toolbar.py` | `202` | Add a Linux fallback to the QSS font family |
| P2 | `ui/probe_chart_dialog.py` | `15-25` | Configure a Chinese font for matplotlib (if charts contain Chinese) |
| P2 | `core/gdml_parser.py` | `96` | Add `errors=` when reading the declaration line, or switch to `ET`'s encoding inference |
| P2 | `core/mac_builder.py` | `367-371` | Normalize task-name case (consistent directories across platforms); warn explicitly on `rmtree` failure instead of silently |
| P2 | `core/run_manager.py` | `220,268-271` | Evaluate stdout buffering causing stuck progress; use `stdbuf` if necessary |
| P2 | `environment.yml` | whole file | Generate `environment.linux.yml`, removing unused deps (occt/pythonocc/gmsh/pyvista/pyqtgraph) |
| P3 | `main.py` | `16-18,20-24,33-48` | Add platform checks to Windows-specific logic (currently masked by try/except, not blocking) |
| P3 | `ui/dialogs/solver_setting_dialog.py` | `48,73,109-116` | Platform-aware copy and placeholders |
| P3 | Viewers | see 2.7 | Add `newline=""` (optional; no impact on Linux) |
| P3 | `doc/10-troubleshooting.md` | — | Add a Linux troubleshooting section |

---

## 4. Proposed Platform Compatibility Layer

To converge "platform differences" into one place, add `core/platform_compat.py` (**functions only, no business logic**) and have the upper layers call it. It should contain:

| Function (proposed name) | Responsibility |
|---|---|
| `is_windows()` / `is_linux()` / `is_wayland()` | Platform detection, replacing scattered `os.name == "nt"` |
| `solver_exe_name()` | `rad4space.exe` / `rad4space` |
| `is_executable(path)` | Windows uses `isfile`; Linux uses `isfile + os.access(X_OK)` |
| `solver_search_paths(repo_root)` | Per-platform solver candidate paths (including `build-linux/`) |
| `runtime_lib_dirs(configured_dir)` | Per-platform library directories to inject (user setting + candidates + solver-adjacent) |
| `apply_runtime_env(env, lib_dirs)` | Write library directories into `PATH` or `LD_LIBRARY_PATH` (both allowed) |
| `default_results_root()` | Windows uses the in-repo directory; Linux prefers XDG (`~/.local/share/RadSim/runs`) with fallback when not writable |
| `detect_qt_runtime(dir)` | Checks `Qt6Core.dll` / `libQt6Core.so.6` |
| `mono_font_families()` / `ui_font_families()` | Return per-platform font fallback chains |
| `icon_backend()` | Decide whether an emoji font is available, to choose font icons vs resource icons |
| `qt_platform_hint()` | Return a suggested value such as `QT_QPA_PLATFORM=xcb` when needed (must take effect **before** `QApplication` is created) |

This way most P0/P1 items in the chapter 3 list need only one change, and Windows behavior stays unchanged.

---

## 5. Ubuntu Environment Setup Checklist (for reference during implementation)

### 5.1 System Dependencies (apt)

```bash
# Qt6 / X11 / OpenGL runtime libraries
sudo apt install -y libgl1 libglx-mesa0 libegl1 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-cursor0 \
    libxcb-xfixes0 libdbus-1-3
# Software rendering backstop + headless
sudo apt install -y mesa-utils libosmesa6 xvfb x11-utils
# Fonts
sudo apt install -y fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu-core
# Open folder
sudo apt install -y xdg-utils
```

### 5.2 Python Environment

```bash
conda env create -f environment.linux.yml   # converted from environment.yml, build hashes removed
conda activate radsim
python -c "import PyQt6, vtk, numpy, matplotlib; print('ok')"
```

### 5.3 Solver Rebuild

```bash
cd solver/rad4space
cmake -S . -B build-linux -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="$CONDA_PREFIX" \
      -DWITH_GEANT4_UIVIS=ON          # can be OFF once the #ifdef changes in 2.2 are done
cmake --build build-linux -j$(nproc)
chmod +x build-linux/rad4space
ldd build-linux/rad4space | grep "not found"   # must be empty
```

### 5.4 Running

```bash
export QT_QPA_PLATFORM=xcb          # required under a Wayland session
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"
python main.py
```

Without a display: `xvfb-run -a -s "-screen 0 1920x1080x24" python main.py`.

---

## 6. Acceptance Checklist

| # | Item | Expected |
|---|---|---|
| 1 | Launch the main window | No crash; Ribbon icons visible (not boxes) |
| 2 | Import GDML (large file ≥500 KB) | Parsed in a background thread; UI does not freeze |
| 3 | 3D preview | Renders, rotates, zooms; no `libGL error` in the console |
| 4 | Solver path detection | Detects `build-linux/rad4space` and judges it executable |
| 5 | Qt runtime directory detection | After entering the conda `lib`, shows "found" |
| 6 | Run tasks (realworld / probe / voxel) | `run.log` grows normally; progress does not stall; exit code 0 |
| 7 | Stop a task | The process actually exits; no zombie processes remain |
| 8 | Result visualization | Voxel/trajectory/charts all load and display |
| 9 | Save/load project | After close and reopen, geometry and task settings are intact |
| 10 | Chinese project name/path | No mojibake in UI, result directory, or logs |
| 11 | Project with spaces in the path | The solver still finds the GDML |
| 12 | Window switch/minimize then restore | The VTK view does not go black |
| 13 | Compare with Windows results | Same GDML + same event count yields results of the same order of magnitude |
| 14 | Headless mode | A complete run finishes under `xvfb-run` |

---

## 7. Risks and Unverified Items

1. **Wayland is the biggest uncertainty**: whether `QVTKRenderWindowInteractor` works under Wayland depends on the distro/VTK build; `QT_QPA_PLATFORM=xcb` only works around it, not a cure. If native Wayland is mandatory, migrate to `QVTKOpenGLNativeWidget`.
2. **Geant4 multithreaded scoring**: the accuracy of `realWorldLogVol` under MT mode needs measurement (platform-independent, but amplified by many cores on Linux).
3. **CPU contention between two concurrent tasks**: `RunManager(max_concurrent=2)` needs wall-clock and memory measurement on many-core Linux machines.
4. **High DPI / fractional scaling**: under GNOME 150% scaling, the VTK render size and mouse coordinates may be misaligned; needs measurement.
5. **Filesystem differences**: if the project lives on NFS/SMB or a case-sensitive Linux partition, transferring projects to/from Windows may cause "directory mismatch/overwritten files".
6. **Solver numerical consistency**: different compilers (MSVC vs GCC) and optimization levels can cause tiny floating-point differences; use the same case for a regression comparison.
7. **Not covered here**: installer signing, auto-update, multi-user permission model, CI build pipeline.

---

## 8. Deep Dive: Solving VTK Window Embedding on Ubuntu

### 8.1 Boundary Clarification: OCC Stays, but RadSim's 3D View Is Not OCC

- The conda environment is called `pyoccenv`, and `environment.yml` contains `occt`, `pythonocc-core`, `gmsh`, `pyvista`, `pyqtgraph`. **These must stay**: RadSim is only one member of the suite, and there is a dedicated OCC program, so the environment must remain unified and cannot be trimmed just for RadSim.
- But for **the RadSim program itself**: the code has **zero imports** of OCC/pythonocc (full-text search returns 0), and the 3D view uses **VTK** (`vtkmodules`).
- The "same style as OCC's Viewer3d" in `ui/vtk_widget.py` is only a **style homage** (copying cad2gdml's display behavior), not OCC code.
- Conclusion: RadSim's Wayland black screen is caused by **VTK legacy window embedding** and has nothing to do with OCC; but **the OCC side has the same pitfall** (see 8.2), and a unified environment is actually easier because one launch strategy solves both at once.

### 8.2 The OCC Side Has the Same Limitation (important)

OCCT visualization likewise depends on **native window handles**: `Aspect_Window` has only `WNT_Window` (Windows), `Xw_Window` (X11/Xlib), `Cocoa_Window` (macOS), and `EGL_Window` (off-screen) implementations — **there is no Wayland backend**.

- Therefore a dedicated OCC program using `V3d_View` + `AIS_InteractiveContext` **also fails to start** under a native Wayland session, behaving exactly like RadSim (black screen/window creation failure).
- Good news: `Xw_Window` works normally under **XWayland** (the program is treated as an X11 client).
- So the suite-wide strategy can be unified: **set `QT_QPA_PLATFORM=xcb` at the launcher level**. If an OCC program does not use Qt but raw Xlib, the equivalent is to ensure it runs inside an XWayland session (avoid native Wayland launch methods such as `GDK_BACKEND=wayland`).
- This nicely leverages the "unified environment" premise: **configure once, benefit suite-wide**.
- To fully eliminate XWayland long term: the VTK side can use approach B (`QVTKOpenGLNativeWidget`, see 8.5); the OCC side still needs XWayland or `EGL_Window` off-screen rendering until OCCT officially supports Wayland.

### 8.3 Why the Legacy Component Fails Under Wayland

`QVTKRenderWindowInteractor` works by "native window ID embedding":

1. Create a `QWidget` with `WA_NativeWindow`;
2. Get the **native window handle** via `winId()` (Windows = HWND, X11 = XID, an integer);
3. Hand that integer to VTK: `renderWindow.SetWindowInfo(str(wid))`;
4. VTK's OpenGL2 backend **creates a GL context directly** on that native window (WGL on Windows, GLX on X11).

Under Wayland a client **cannot obtain such a drawable native handle**: `winId()` does not return an XID, and VTK's legacy path **has no Wayland backend**. So context creation fails → black/blank screen, and in severe cases a crash.

So first check the session type:

```bash
echo $XDG_SESSION_TYPE        # wayland / x11
python -c "from PyQt6.QtWidgets import QApplication; from PyQt6.QtGui import QGuiApplication; QApplication([]); print(QGuiApplication.platformName())"
```

- Printing `xcb` → X11/XWayland, **the legacy component works normally**;
- Printing `wayland` → the legacy component very likely fails.

Ubuntu 22.04 / 24.04 GNOME defaults to Wayland; you can switch to "Ubuntu on Xorg" at the login screen to verify.

### 8.4 Approach A: Force XWayland (0 lines of code, unblocks first)

Ubuntu ships XWayland by default. As long as Qt uses the `xcb` platform plugin, `winId()` returns a real XID and the legacy component behaves as under X11.

```bash
export QT_QPA_PLATFORM=xcb
python main.py
```

Three ways to apply it:
- Command line: `QT_QPA_PLATFORM=xcb python main.py`
- Desktop shortcut: `Exec=env QT_QPA_PLATFORM=xcb /path/to/python /path/to/main.py`
- In code (in `main.py`, **before** creating `QApplication`, and only under a Wayland session): `os.environ.setdefault("QT_QPA_PLATFORM", "xcb")`

Prerequisites and costs:
- Need the `libxcb-*` series (see section 5.1);
- On minimal environments without XWayland (some wlroots compositors), `xcb` cannot connect to a display;
- This is a **workaround**, not a fix; XWayland windows may look blurry under fractional scaling.

### 8.5 Approach B: Migrate to `QVTKOpenGLNativeWidget` (recommended long term)

VTK's official modern Qt integration (`vtkmodules.qt.QVTKOpenGLNativeWidget`, VTK ≥ 9.0, available with the current 9.3.1). It uses **Qt's own OpenGL context** (`QOpenGLWidget`) and behaves consistently on Windows / X11 / Wayland / macOS, **no longer needing WId binding and rebinding**, with HiDPI handled by Qt.

Changes are confined to `ui/vtk_widget.py`, with the public API (`get_scene` / `build_scene` / `render` / `node_picked`) unchanged:

| Current | Change to |
|---|---|
| `QVTKRenderWindowInteractor` | `QVTKOpenGLNativeWidget` + `vtkGenericOpenGLRenderWindow` |
| `self._vtk_interactor.GetRenderWindow()` | A self-created `self._render_window` |
| `self._vtk_interactor.Initialize()` / `Start()` | The new widget is driven by the Qt event loop; per the official example usually only `GetInteractor().Initialize()` is needed — **do not keep the `Start()` call in `showEvent`** |
| `_ensure_window_bound()` + `_bound_wid` / `_bound_once` / `SetWindowInfo` / `Finalize` | **Delete the whole block** (it is both the root of the Wayland problem and the source of Windows `wglMakeCurrent failed`) |
| Regex parsing of `ReportCapabilities()` | Can be simplified with VTK 9's `GetOpenGLVendor()/GetOpenGLRenderer()/GetOpenGLVersion()` |
| `SetSwapControl(0)` to disable vsync | Keep but do not rely on it: Wayland is decided by the compositor, and GLX may silently ignore it under X11 |

**Key prerequisite**: the default `QSurfaceFormat` must be set **before** `QApplication` is created, otherwise `QOpenGLWidget` may get an incompatible context (black screen or `Failed to create OpenGL context`):

```python
from PyQt6.QtGui import QSurfaceFormat
fmt = QSurfaceFormat()
fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
fmt.setVersion(3, 2)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setStencilBufferSize(8)
fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
fmt.setSamples(0)          # keep consistent with the current SetMultiSamples(0)
QSurfaceFormat.setDefaultFormat(fmt)
```

Effort: about 1 file, 50–80 lines; requires regression testing of picking, clipping, toolbars, voxel rendering, and window hide/show.

### 8.6 Approach C (not recommended)

- **Standalone VTK window** (no Qt embedding): fragmented experience.
- **Off-screen rendering + `vtkWindowToImageFilter` blitted into a QLabel**: interaction must be implemented manually with poor performance; only a backstop for no-GPU / pure remote desktop scenarios.

### 8.7 Recommended Path

1. **Suite level**: set `QT_QPA_PLATFORM=xcb` uniformly in a shared launcher (or each program's `.desktop`), so RadSim and the dedicated OCC program both run under XWayland — zero code risk, and the chapter 6 acceptance can proceed immediately.
2. **RadSim level**: schedule **approach B** to remove the WId rebinding logic in one shot. It is also the root of `wglMakeCurrent failed` on Windows, so it is a "both platforms benefit" change.
3. **OCC program level**: keep relying on XWayland until OCCT officially supports Wayland; if that program needs headless/remote operation, evaluate the `EGL_Window` off-screen route.
4. After approach B, RadSim no longer needs `QT_QPA_PLATFORM=xcb` and can return to native Wayland; but as long as the suite still contains OCC programs, setting `xcb` uniformly remains simpler.

---

## Appendix: Relation to Other Documents

- Architecture and layering → `doc/01-architecture.md`
- Solver launch/state machine details → `doc/04-execution.md`
- Macro file format and generation → `doc/03-mac-builder.md`
- Visualization implementation → `doc/07-visualization.md`
- Windows environment and troubleshooting → `doc/10-troubleshooting.md` (a Linux section is recommended later)



