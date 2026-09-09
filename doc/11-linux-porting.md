# RadSim 跨平台移植指南：Windows → Ubuntu / Linux

> 适用版本：**RadSim 0.1.0** ｜ 编写日期：2026-09-09 ｜ 性质：**分析文档，不含代码改动**
>
> 目的：让 RadSim 在 Windows 与 Ubuntu/Linux 上双平台工作。本文只回答"**哪里需要改、为什么、怎么改（方向）**"，不提供实现。

---

## 0. 结论速览

**总体判断：Python 层可移植性良好，真正的重活在两处——求解器重建 + 图形上下文/字体。**

| 结论 | 说明 |
|---|---|
| ✅ Python 代码整体可移植 | 路径统一用 `os.path`/`os.pathsep`；无 `subprocess`/`shell=True`/`os.startfile`；文件读写基本已带 `encoding="utf-8"`；`QProcess`/`QSettings`/`QThread` 均为跨平台 API |
| 🔴 1 处功能失效 | `core/solver_config.py` 的运行时库注入只认 Windows `PATH`，Linux 下返回空列表（`LD_LIBRARY_PATH` 未处理） |
| 🔴 1 处必须重建 | `solver/rad4space/build/` 是 MSVC 产物，Linux 必须重编；且它链接 Qt6/OpenGL/X11 |
| 🔴 1 处架构风险 | VTK 用**已废弃**的 `QVTKRenderWindowInteractor` + `WId` 原生窗口嵌入，Wayland 下大概率不可用 |
| 🟠 1 处观感问题 | 图标全依赖 emoji + `Segoe UI Emoji`，Ubuntu 缺字体会变方框/空白 |
| 🟡 一批中低风险 | 硬编码 `D:\` Qt 目录、`Qt6Core.dll` 探测、默认输出目录落在仓库内、`run.mac` 中带空格的 GDML 路径、编码/换行细节 |
| ✅ 可直接沿用 | `core/` 的 GDML 解析/写出/表达式求值、`mac_builder` 的数值格式化（`%g` 与 locale 无关）、结果 CSV 解析、项目 JSON、日志、Ribbon/主题/QSS |

**工作量预估**：环境 0.5 天；求解器 Linux 重建 1–2 天；平台适配层 + 字体/图标 1–2 天；VTK 窗口方案验证 1–3 天。

---

## 1. 影响分级总览

| 级别 | 含义 | 条目数 |
|---|---|---|
| 🔴 阻断 | 不解决则核心功能不可用 | 3 |
| 🟠 高 | 功能静默失效或明显异常 | 5 |
| 🟡 中 | 体验/一致性/边缘场景 | 9 |
| 🟢 低 | 文案、可移植性打磨 | 8 |

---

## 2. 逐模块分析

### 2.1 运行环境与依赖

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `environment.yml:1-176` | 名为 `pyoccenv` 的 Windows conda 快照，包带 `win-64` build hash（`h70ea87e` 等），含 `vc=14.3`、`ucrt`、`vs2015_runtime`、`mkl` | Linux **无法直接复现**。需生成 `environment.linux.yml`（去掉 build hash 让 conda 重解），确认 `vtk=9.3.1`/`qt6-main`/`pyqt` 的 linux-64 版本 | 🟠 高 |
| `environment.yml:89,104` | `occt`、`pythonocc-core` | RadSim 代码零处 import，但**套件内另有专用 OCC 程序，环境必须统一 → 必须保留**。Linux 下需确认 conda `pythonocc-core` 的 linux-64 可用性及 `libGL`/`libGLU`/`libXmu`/`libXi` 等系统依赖 | 🟡 中 |
| `environment.yml:145,166,169` | `gmsh`、`pyqtgraph`、`pyvista` | RadSim 未引用；若套件其它程序用到则保留，否则可移除 | 🟢 低 |
| `requirements.txt:12-18` | `PyQt6==6.4.2`/`vtk==9.3.1`/`numpy==2.2.6`/`matplotlib==3.10.7` | 均有 linux-64 wheel；但 PyQt6 的 manylinux wheel 依赖系统 `libxcb-*`、`libEGL`、`libxkbcommon` 等（见第 5 章） | 🟡 中 |
| `doc/10-troubleshooting.md` | 只记录 Windows 环境（Qt DLL 冲突、`0xC0000135/0xC0000139`） | 应补 Linux 段：`libGL error`、Wayland、字体、`LD_LIBRARY_PATH` | 🟢 低 |

> **关于环境名 `pyoccenv`**：这个名字、以及 `environment.yml` 里的 `occt` / `pythonocc-core` / `gmsh` / `pyvista` / `pyqtgraph`，都来自 gdmleditor / cad2gdml 血统。**RadSim 的 Python 代码对 OCC/pythonocc 零 import**（全文搜索 `import OCC` / `from OCC` / `pythonocc` 结果为 0），它的 3D 视图用的是 **VTK**（`vtkmodules`）；`ui/vtk_widget.py` 里 "same style as OCC's Viewer3d" 只是风格致敬（照抄 cad2gdml 的显示行为），不是 OCC 代码。
> **但不要因此删除这些包**：交付物是一整套套件，另有专用 OCC 程序，环境要统一。对 RadSim 自身而言，OCC 与"Linux 下 3D 显示是否可用"无关；而 OCC 侧在 Wayland 下有**同类问题**，见 [8.2](#82-occ-侧也有同样的限制重要)。

### 2.2 求解器 rad4space（**最重的一项**）

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `solver/rad4space/build/` | 仓库内提交了 **MSVC 产物**：`*.vcxproj`、`rad4space.dir/Release/*.obj`、`*.tlog`、`Release/rad4space.exe`；tlog 硬编码 `D:\APPLICATION\GEANT4\...` | Linux **完全不可用**，必须新建 `build-linux/` 重编。仓库根目录**没有 `.gitignore`**，构建产物被一起跟踪，建议先加 `.gitignore` | 🔴 阻断 |
| `solver/rad4space/CMakeLists.txt:11-16` | `option(WITH_GEANT4_UIVIS ... ON)` + `find_package(Geant4 REQUIRED ui_all vis_all)` | `ui_all vis_all` 把 **Qt6 可视化驱动**拉进链接，Linux 下同样需要 Qt6+OpenGL+X11 运行时。GUI 只用 batch，可考虑 `-DWITH_GEANT4_UIVIS=OFF` 减小依赖面 | 🟠 高 |
| `solver/rad4space/rad4space.cc:27-28,41-42,79-86` | 无条件 `#include "G4UIExecutive.hh"`/`"G4VisExecutive.hh"`；`argc==1` 时 `new G4UIExecutive(argc, argv, "Qt")`；交互模式才 `new G4VisExecutive` | 想彻底去掉 Qt 依赖，仅加 CMake 开关**不够**，这两处 include 与 `"Qt"` session 需用 `#ifdef` 包住（C++ 侧改动，需单独评审） | 🟡 中 |
| `solver/rad4space/rad4space.cc:42` | 交互模式显式 `"Qt"` session | Linux 无 Qt session 会退化/报错；但 GUI 走 batch（`argc==2`）不触发，**非阻断** | 🟢 低 |
| 构建命令 | README 用 `--config Release`（MSVC 多配置生成器） | Linux 默认 Makefiles/Ninja 是**单配置**：产物落在 `build-linux/rad4space`，**没有 `Release/` 子目录** | 🟠 高 |
| 可执行位 | Windows 无此概念 | 编译出的 `rad4space` 需 `+x`；经压缩包/网盘/git 传递可能丢失 | 🟠 高 |

### 2.3 求解器启动与运行时库（**核心功能失效点**）

| 位置 | 现状 | Linux 下的问题 | 建议方向 | 级别 |
|---|---|---|---|---|
| `core/solver_config.py:109-127` `runtime_dll_dirs()` | 首行 `if os.name != "nt": return []`，Linux 恒空；其余逻辑是"把 Qt bin 放到 `PATH` 最前" | **Linux 动态链接器不读 `PATH`，只读 `LD_LIBRARY_PATH`（或 rpath/ld.so.conf）**。找不到 `libQt6Core.so.6`、`libG4*.so`、`libxerces-c-3.3.so` 时会以 `error while loading shared libraries` 退出 | 按平台注入：Windows 用 `PATH`，Linux 用 `LD_LIBRARY_PATH`；目录来源仍"用户设置优先 + 候选回退" | 🔴 阻断 |
| `core/run_manager.py:211-217` | `env.insert("PATH", os.pathsep.join(dll_dirs) + ...)` | 同上：Linux 下对动态库**完全无效**，等于没做 | 按平台选择 `PATH`/`LD_LIBRARY_PATH`，可两者都注入 | 🔴 阻断 |
| `core/solver_config.py:24-26` `DEFAULT_QT_BIN_DIRS` | 硬编码 `r"D:\Application\Qt6.11\6.11.1\msvc2022_64\bin"` | Linux 上目录不存在（`isdir` 过滤后为空，不崩），但等于**没有回退候选** | 按平台给候选（`/usr/lib/x86_64-linux-gnu`、`/opt/Qt/6.*/gcc_64/lib`、conda env 的 `lib/`），或改为"求解器同目录/lib"约定 | 🟠 高 |
| `core/solver_config.py:38-43` `default_solver_path()` | 已按 `os.name` 选 `rad4space.exe`/`rad4space`；候选 `build/Release/`、`build/`、`rad4space/` | 候选基本够用，但 Linux 单配置构建更可能落在 `build-linux/`；且只判 `isfile` 不判可执行位 | 补 `build-linux/`、`build/bin/`；用 `os.access(path, os.X_OK)` 判定 | 🟡 中 |
| `core/run_manager.py:65` | `self._solver_exe = exe if exe and os.path.isfile(exe) else None` | Linux 下文件存在但**无 `+x`** 仍被视为有效；`QProcess` 启动失败后，因 `None` 会退化成"模拟进度"，易出现"看起来在跑其实没跑" | 增加可执行位检查，日志区分"不存在/不可执行" | 🟠 高 |
| `core/run_manager.py:235-240` | `proc.start(exe, args)` + `waitForStarted(3000)` | 3 秒在慢盘/网络盘偏短；Linux 下二进制 fork 成功但 loader 失败时 `waitForStarted` 仍返回 true，需靠退出码 127/126 识别 | 适当放宽超时；错误提示区分平台 | 🟡 中 |
| `core/run_manager.py` 错误文案 | 绑定 `0xC0000135`/`0xC0000139`（Windows DLL 错误码） | Linux 对应为退出码 **127**（找不到 `.so`）/ **126**（无执行权限） | 文案与诊断分支按平台区分 | 🟢 低 |
| `core/run_manager.py:307,329-331` | 停止 `terminate()`，2 秒后 `kill()` | 语义正确（SIGTERM→SIGKILL）。但 Geant4 默认不处理 SIGTERM，输出可能不完整；若派生子孙进程，`kill()` 只杀主进程 | 可选：Linux 下用进程组/`setsid` 让整组退出 | 🟡 中 |
| `core/run_manager.py:220,268-271` | `MergedChannels` + 二进制写 `run.log` | 跨平台 OK。但 Linux 下 stdout 接管道是**全缓冲（4KB）**，`readyReadStandardOutput` 可能长时间不触发，进度心跳看起来"卡住" | 可选：`stdbuf -o0 -e0` 包裹启动，或让求解器定期 flush | 🟡 中 |

### 2.4 VTK / OpenGL / 窗口嵌入（**架构性风险**）

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `ui/vtk_widget.py:24` | `from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor` | VTK **已废弃**的 legacy 类，靠把渲染窗口绑到 Qt 的原生窗口 ID（Windows HWND / X11 XID）工作。Wayland **没有稳定原生窗口 ID 可嵌入**，基本不可用 | 🔴 阻断（Wayland） |
| `ui/vtk_widget.py:229-262` `_ensure_window_bound()` | `int(winId())` + `rw.SetWindowInfo(str(wid))` + 必要时 `rw.Finalize()` 重绑 | X11 下原理成立（XID 是十进制整数），但注释描述的问题（`wglMakeCurrent failed`）是 Windows 专有；Linux 下 `Finalize()` 会销毁 GLX/EGL 上下文，时序冲突可能黑屏 | 🟠 高 |
| `ui/vtk_widget.py:120,203-209,622-627` | `Initialize()`、`SetSwapControl(0)` 关 vsync | `SetSwapControl` 已 try/except，安全；Linux/Mesa 下可能静默无效，vsync 行为与 Windows 不同 | 🟢 低 |
| `ui/vtk_widget.py:130-188` | 先 `SetOffScreenRendering(False)` 试探，正则解析 `ReportCapabilities()` 的 vendor/renderer/version；失败则 `SetOffScreenRendering(True)` 软回退 | 逻辑可移植，但 Linux 无 GPU/无 DISPLAY 时 `Render()` 可能直接报错而非返回空；软回退需 Mesa（`libGL`+llvmpipe）或 OSMesa | 🟡 中 |
| `ui/vtk_widget.py:32-38` | 显式 import `vtkRenderingOpenGL2`/`vtkRenderingVolumeOpenGL2` | Linux 同样需要，**保留即可** | ✅ |
| 平台选择 | 代码未设置 `QT_QPA_PLATFORM` | Ubuntu GNOME 默认 Wayland 会话下大概率起不来。短期：强制 `QT_QPA_PLATFORM=xcb`（XWayland）；长期：迁到 `QVTKOpenGLNativeWidget` + `vtkGenericOpenGLRenderWindow` | 🔴 阻断（Wayland） |
| 无头/远程 | 未处理 | 无显示器需 `xvfb-run`，或 `LIBGL_ALWAYS_SOFTWARE=1` + Mesa 软渲染 | 🟡 中 |

> **推荐路线**：先用 `QT_QPA_PLATFORM=xcb` 在 X11/XWayland 下跑通并验收，再评估是否把 `VtkWidget` 内部换成 `QVTKOpenGLNativeWidget`（对外 API `get_scene/build_scene/render` 可保持不变，改动集中在 `ui/vtk_widget.py`，调用方无需改）。

### 2.5 界面外观与字体

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `ui/ribbon_toolbar.py:16-28` `_create_emoji_icon()` | 用 `QFont("Segoe UI Emoji", 48)` 把 emoji 画进 `QPixmap` 作图标 | Ubuntu 默认**无 Segoe UI Emoji**；未装彩色 emoji 字体时，Ribbon 图标（📁🧾💾🎯▶️🟢⏹⚙️☀️❓）变**空白/方框** | 🟠 高 |
| `ui/ribbon_toolbar.py:202` | QSS `font-family: "Segoe UI", "Arial", sans-serif` | 缺字体时 Qt 会回退，不崩，但字重/字距不一致 | 🟢 低 |
| `app/main_window.py:114-124,285` | 日志/宏预览用 `"Consolas", "Courier New", monospace` | Linux 无 Consolas，需回退 `DejaVu Sans Mono`/`Noto Sans Mono`，否则等宽效果丢失 | 🟡 中 |
| 中文显示 | 界面文案全英文，但项目名/任务名/路径可能含中文 | 系统未装中文字体（`fonts-noto-cjk`）时中文变方框 | 🟡 中 |
| `ui/probe_chart_dialog.py:15-25` | `matplotlib.use("QtAgg")` | 可移植；但图表标签含中文时，matplotlib 默认字体无 CJK → 方框，需配 `font.sans-serif` | 🟡 中 |

**建议方向**：图标不要依赖 emoji 字体——最稳的是把 Ribbon 图标改为随包分发的 SVG/PNG 资源（`QIcon` 直接加载），并保留"emoji 字体回退链"兜底；字体在启动时按平台设置 `QFont` 回退列表。

### 2.6 文件、路径与权限

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `core/mac_builder.py:318` | `f"/rad4space/gdml/SetGDMLFile {gdml_full_path}"` | Geant4 宏命令**按空格切分参数**。路径含空格（`/home/me/My Documents/a.gdml`）会截断，求解器读到错误路径而失败 | 🟠 高 |
| `core/mac_builder.py:363-367` | `re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name)`，随后 `rmtree`+`makedirs` | Windows 文件系统大小写不敏感，Linux **敏感**：`Task` 与 `task` 在 Windows 是同一目录、Linux 是两个。跨平台迁移项目时结果目录可能"对不上" | 🟡 中 |
| `core/mac_builder.py:366` | `shutil.rmtree(work, ignore_errors=True)` | Linux 下旧结果文件只读/目录无写权限时，`ignore_errors` 会**静默保留旧文件**，造成"新结果混旧结果" | 🟡 中 |
| `core/project_io.py:66,133,148` | `shutil.copy2/copytree/rmtree`，`copytree` 保留源权限 | Linux 下源文件只读 → 副本也只读，后续 `rmtree` 可能失败并被 `ignore_errors` 吞掉 | 🟢 低 |
| `core/project_io.py:64` | `os.path.basename(src)` 作为项目内几何文件名 | 不同目录的同名 GDML 互相覆盖（两平台都有，Linux 更容易踩） | 🟢 低 |
| 符号链接 | 无相关处理 | 项目目录可能是符号链接，`os.path.abspath` 不解析链接，`abspath(src) != abspath(dst)` 可能误判 | 🟢 低 |
| `app/main_window.py:1169` | `QDesktopServices.openUrl(QUrl.fromLocalFile(work))` | **可移植**，Linux 走 `xdg-open`；仅需确认装了 `xdg-utils` | ✅ |

### 2.7 文本编码与换行

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `core/gdml_parser.py:91` | `ET.parse(filepath)` | 遵守 XML 声明的编码，**正确** | ✅ |
| `core/gdml_parser.py:96` | `open(filepath, "r", encoding="utf-8")` 只读第一行声明 | 若 GDML 实际是 latin-1/GBK，抛 `UnicodeDecodeError` 导致导入失败（Linux 上更易遇到第三方工具产出的非 UTF-8 GDML） | 🟡 中 |
| `core/gdml_writer.py:152`、`core/mac_builder.py:368`、`core/project_io.py:96` | 统一 `encoding="utf-8"` | 正确 | ✅ |
| 结果读取 | `ui/probe_result_viewer.py:33,93`、`ui/voxel_result_viewer.py:619`、`ui/dialogs/result_viewer.py:184` 文本模式无 `newline=""` | Linux 下输出 `\n`，通用换行能正确处理，**不阻断**；仅当出现 `\r\n` 时手工 `split(",")` 可能残留 `\r`（`strip()` 已覆盖） | 🟢 低 |
| `ui/trajectory_viewer.py:127` | `newline=""` + `csv.DictReader` | **正确**，推荐写法 | ✅ |
| `core/mac_builder.py:102-103` `_num()` | `"%g" % v` | Python `%` 格式化**不受 locale 影响**（始终 `.` 作小数点），Linux 德/法语 locale 下也安全 | ✅ |
| 宏换行 | `build_mac_text` 用 `"\n".join()` | Geant4 两种换行都接受 | ✅ |

### 2.8 进程与线程

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `app/main_window.py:180-182,585-600` | 大 GDML（≥500 KB）走 `QThread`+`_ImportWorker` | 跨平台 OK；Linux 下同样需 `quit()+wait()`，现有 `all_done` 处理已覆盖 | ✅ |
| `core/run_manager.py:220` | `MergedChannels` | 跨平台 OK | ✅ |
| `core/run_manager.py:307,329-331` | `kill()`/`terminate()` | 语义正确，见 2.3 关于 SIGTERM 与子进程组 | 🟡 中 |
| `RunManager(max_concurrent=2)` | 并发 2 个求解器进程 | Linux 下每个进程默认吃满所有核心（`G4GetNumberOfCores()`），两任务互相抢 CPU；且 `realWorldLogVol` 计分在 MT 下不准确。**与平台无关，但服务器核多时更明显** | 🟡 中 |

### 2.9 配置持久化与用户目录

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `core/solver_config.py:15-19,53` | `QSettings("RadSim", "RadSim")` | 跨平台 API，但**存储位置不同**：Windows 写注册表，Linux 写 `~/.config/RadSim/RadSim.conf`；迁移用户配置需手工导出/重建 | 🟢 低 |
| `core/solver_config.py:60-63` `default_results_root()` | `_repo_root()/solver/runs` | 若装在 `/opt`、`/usr/local` 或只读目录，或**多用户共用一份安装**，默认输出目录不可写 → 所有运行失败 | 🟠 高 |
| `ui/dialogs/solver_setting_dialog.py:147,154` | `os.path.expanduser("~")` | 可移植 | ✅ |
| `core/solver_config.py` 键名 | `solver/qt_bin_dir`（Windows 语义） | 语义在 Linux 下应理解为"额外库目录"；可保留键名做兼容，仅改 UI 文案 | 🟢 低 |

### 2.10 求解器设置对话框（功能误导）

| 位置 | 现状 | Linux 下的问题 | 级别 |
|---|---|---|---|
| `ui/dialogs/solver_setting_dialog.py:171-175` | 用 `Qt6Core.dll` 是否存在来判断"Qt 运行时目录是否有效" | Linux 下永远找不到 `Qt6Core.dll` → **该字段始终显示"未找到"**，用户无法判断设置是否正确 | 🟠 高 |
| `ui/dialogs/solver_setting_dialog.py:48` | 占位符 `rad4space.exe` | 文案 | 🟢 低 |
| `ui/dialogs/solver_setting_dialog.py:73` | 占位符 `…\msvc2022_64\bin` | 文案，应给 Linux 示例 | 🟢 低 |
| `ui/dialogs/solver_setting_dialog.py:109-116` | 说明文字只提 DLL | 应补 `.so`/`LD_LIBRARY_PATH` | 🟢 低 |
| `ui/dialogs/solver_setting_dialog.py:134-138` | 已按 `os.name` 切换文件过滤器（`*.exe` vs 全部） | **正确**，保留 | ✅ |
| `ui/dialogs/solver_setting_dialog.py:30-32` | `WindowContextHelpButtonHint` | X11 下该 flag 被忽略，无副作用 | ✅ |

### 2.11 打包与分发

| 项目 | Windows 现状 | Linux 需要做的事 | 级别 |
|---|---|---|---|
| 构建产物 | 无 `.gitignore`，`build/` 与 `*.exe` 入库 | 加 `.gitignore` 排除 `build*/`、`*.o`、`*.so`、`__pycache__/`；Linux 用独立构建目录 | 🟡 中 |
| 分发形态 | 未见 PyInstaller/Nuitka 配置 | 可用 conda-pack 或 PyInstaller；需补 `.desktop` 文件、图标（PNG/SVG）、`Exec`/`Icon` 路径 | 🟡 中 |
| 安装位置 | 用户目录下双击运行 | 若装到系统目录，需处理 `default_results_root()` 的写权限（见 2.9） | 🟠 高 |
| 依赖完整性 | conda 环境含全部运行时 | Linux 需确保 Geant4 数据文件（`G4LEDATA`、`G4ENSDFSTATEDATA` 等）随环境一起安装，否则求解器运行时报错 | 🟠 高 |

### 2.12 确认**无需**改动的部分（可放心）

- `core/gdml_parser.py` / `gdml_tree.py` / `gdml_evaluator.py` / `gdml_writer.py` / `gdml_agent.py`：纯 XML/DOM 逻辑，与平台无关。
- `core/materials_lib.py`：纯数据字典与 JSON 读写（注意：`data/element.xml`、`data/nist.txt` 目前**未被代码引用**，Linux 下不构成阻塞）。
- `core/project_model.py`：`os.path.join` 统一拼接，路径分隔符无硬编码。
- `core/logger.py`：标准 logging + 文件 handler。
- `vtk_engine/`：`VtkScene`/`VtkSolidFactory` 只操作 VTK 数据对象，不碰原生窗口。
- 主题/QSS 与 Ribbon 布局逻辑：除字体名外与平台无关。
- `ui/dialogs/*` 的文件选择器：均用 `QFileDialog` + `os.name` 分支。

---

## 3. 建议的修改清单（按文件聚合）

> 优先级：**P0** = 不解决跑不起来；**P1** = 跑起来但功能不对；**P2** = 体验/一致性；**P3** = 打磨。

| 优先级 | 文件 | 关键位置 | 要改什么（方向） |
|---|---|---|---|
| P0 | `core/solver_config.py` | `109-127` | `runtime_dll_dirs()` 增加 Linux 分支；把库目录按平台分别投递到 `PATH` / `LD_LIBRARY_PATH` |
| P0 | `core/run_manager.py` | `211-217` | 同上，`QProcessEnvironment` 按平台注入 |
| P0 | `core/solver_config.py` | `24-26` | `DEFAULT_QT_BIN_DIRS` 改为按平台的候选列表 |
| P0 | `solver/rad4space/build/` | 整个目录 | 不复用；Linux 新建 `build-linux/` 重编，并补 `.gitignore` |
| P0 | 启动入口 | — | Linux/Wayland 下设置 `QT_QPA_PLATFORM=xcb`（或用 `QVTKOpenGLNativeWidget` 替代 legacy interactor） |
| P1 | `core/solver_config.py` | `38-43,60-63` | 求解器候选路径补 `build-linux/`；`os.access(..., X_OK)`；`default_results_root()` 在安装目录不可写时回退到 XDG 目录 |
| P1 | `core/run_manager.py` | `65,235-240` | 可执行位检查；启动失败提示区分平台错误码 |
| P1 | `ui/dialogs/solver_setting_dialog.py` | `171-175` | 探测目标改为平台相关（`Qt6Core.dll` / `libQt6Core.so.6`） |
| P1 | `ui/ribbon_toolbar.py` | `16-28` | 图标改为随包 SVG/PNG 资源，或加字体回退链并检测可用性 |
| P1 | `core/mac_builder.py` | `318` | `SetGDMLFile` 路径含空格时的处理（引号/转义，或把 GDML 复制到工作目录用相对文件名） |
| P1 | `solver/rad4space/CMakeLists.txt` | `11-16` | 评估 `WITH_GEANT4_UIVIS=OFF`，并配套 `rad4space.cc` 的 `#ifdef` 改造 |
| P2 | `app/main_window.py` | `114-124,285` | 等宽字体加 Linux 回退 |
| P2 | `ui/ribbon_toolbar.py` | `202` | QSS 字体族加 Linux 回退 |
| P2 | `ui/probe_chart_dialog.py` | `15-25` | matplotlib 中文字体配置（若图表含中文） |
| P2 | `core/gdml_parser.py` | `96` | 声明行读取加 `errors=` 或改用 `ET` 的编码推断 |
| P2 | `core/mac_builder.py` | `363-367` | 任务名大小写归一（跨平台目录一致）；`rmtree` 失败要显式告警而非静默 |
| P2 | `core/run_manager.py` | `220,268-271` | 评估 stdout 缓冲导致进度卡住，必要时 `stdbuf` |
| P2 | `environment.yml` | 全文 | 生成 `environment.linux.yml`，移除未用依赖（occt/pythonocc/gmsh/pyvista/pyqtgraph） |
| P3 | `main.py` | `16-18,20-24,33-48` | Windows 专有逻辑加平台判断（目前靠 try/except 兜底，不阻断） |
| P3 | `ui/dialogs/solver_setting_dialog.py` | `48,73,109-116` | 文案与占位符按平台 |
| P3 | 各 viewer | 见 2.7 | 补 `newline=""`（可选，Linux 下不影响） |
| P3 | `doc/10-troubleshooting.md` | — | 增加 Linux 排障章节 |

---

## 4. 建议引入的平台适配层

为把"平台差异"收敛到一个地方，建议新增 `core/platform_compat.py`（**只提供函数，不含业务逻辑**），上层各处改为调用它。建议包含：

| 函数（建议名） | 职责 |
|---|---|
| `is_windows()` / `is_linux()` / `is_wayland()` | 平台判定，替代散落的 `os.name == "nt"` |
| `solver_exe_name()` | `rad4space.exe` / `rad4space` |
| `is_executable(path)` | Windows 用 `isfile`，Linux 用 `isfile + os.access(X_OK)` |
| `solver_search_paths(repo_root)` | 按平台给出求解器候选路径（含 `build-linux/`） |
| `runtime_lib_dirs(configured_dir)` | 按平台返回需要注入的库目录（用户设置 + 候选 + 求解器同目录） |
| `apply_runtime_env(env, lib_dirs)` | 把库目录写入 `PATH` 或 `LD_LIBRARY_PATH`（可同时写） |
| `default_results_root()` | Windows 用仓库内目录；Linux 优先 XDG（`~/.local/share/RadSim/runs`），不可写时回退 |
| `detect_qt_runtime(dir)` | 检查 `Qt6Core.dll` / `libQt6Core.so.6` |
| `mono_font_families()` / `ui_font_families()` | 返回平台字体回退链 |
| `icon_backend()` | 判断 emoji 字体是否可用，决定用字体图标还是资源图标 |
| `qt_platform_hint()` | 需要时返回 `QT_QPA_PLATFORM=xcb` 等建议值（在 `QApplication` 创建**之前**生效） |

这样第 3 章清单里的 P0/P1 项大部分只需改一处，Windows 行为保持不变。

---

## 5. Ubuntu 环境搭建清单（供实施参考）

### 5.1 系统依赖（apt）

```bash
# Qt6 / X11 / OpenGL 运行库
sudo apt install -y libgl1 libglx-mesa0 libegl1 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-cursor0 \
    libxcb-xfixes0 libdbus-1-3
# 软件渲染兜底 + 无头
sudo apt install -y mesa-utils libosmesa6 xvfb x11-utils
# 字体
sudo apt install -y fonts-noto-cjk fonts-noto-color-emoji fonts-dejavu-core
# 打开文件夹
sudo apt install -y xdg-utils
```

### 5.2 Python 环境

```bash
conda env create -f environment.linux.yml   # 由 environment.yml 转换而来，去掉 build hash
conda activate radsim
python -c "import PyQt6, vtk, numpy, matplotlib; print('ok')"
```

### 5.3 求解器重建

```bash
cd solver/rad4space
cmake -S . -B build-linux -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="$CONDA_PREFIX" \
      -DWITH_GEANT4_UIVIS=ON          # 若 2.2 的 #ifdef 改造完成，可改 OFF
cmake --build build-linux -j$(nproc)
chmod +x build-linux/rad4space
ldd build-linux/rad4space | grep "not found"   # 必须为空
```

### 5.4 运行

```bash
export QT_QPA_PLATFORM=xcb          # Wayland 会话下必需
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"
python main.py
```

无显示器时：`xvfb-run -a -s "-screen 0 1920x1080x24" python main.py`。

---

## 6. 验收清单（Checklist）

| # | 验收项 | 期望 |
|---|---|---|
| 1 | 启动主窗口 | 无崩溃；Ribbon 图标可见（非方框） |
| 2 | 导入 GDML（大文件 ≥500 KB） | 后台线程解析，界面不卡死 |
| 3 | 3D 预览 | 能渲染、旋转、缩放；控制台无 `libGL error` |
| 4 | 求解器路径检测 | 能识别 `build-linux/rad4space` 且判定为可执行 |
| 5 | Qt 运行时目录检测 | 填入 conda `lib` 后显示"已找到" |
| 6 | 运行任务（realworld / probe / voxel） | `run.log` 正常增长；进度不卡死；退出码为 0 |
| 7 | 停止任务 | 进程确实退出，无僵尸进程残留 |
| 8 | 结果可视化 | 体素/轨迹/图表均能加载并显示 |
| 9 | 保存/加载项目 | 关闭再打开，几何与任务设置完整 |
| 10 | 中文项目名/路径 | 界面、结果目录、日志均无乱码 |
| 11 | 路径含空格的项目 | 求解器仍能找到 GDML |
| 12 | 窗口切换/最小化再恢复 | VTK 视图不黑屏 |
| 13 | 与 Windows 结果对比 | 同一 GDML + 同一事件数，结果量级一致 |
| 14 | 无头模式 | `xvfb-run` 下可完成一次完整运行 |

---

## 7. 风险与未验证项

1. **Wayland 是最大不确定性**：`QVTKRenderWindowInteractor` 在 Wayland 下能否工作取决于发行版/VTK 构建；`QT_QPA_PLATFORM=xcb` 只是规避，不是根治。若必须原生 Wayland，需迁移到 `QVTKOpenGLNativeWidget`。
2. **Geant4 多线程计分**：`realWorldLogVol` 在 MT 模式下的结果准确性需实测（与平台无关，但 Linux 核多会放大）。
3. **两个并发任务的 CPU 争抢**：`RunManager(max_concurrent=2)` 在 Linux 多核机器上需实测墙钟时间与内存占用。
4. **高 DPI / 分数缩放**：GNOME 150% 缩放下 VTK 渲染尺寸与鼠标坐标可能错位，需实测。
5. **文件系统差异**：若项目放在 NFS/SMB 或大小写敏感的 Linux 分区，与 Windows 之间互传项目可能出现"目录对不上/文件被覆盖"。
6. **求解器数值一致性**：不同编译器（MSVC vs GCC）与优化级别可能导致浮点结果有微小差异，需用同一算例做回归对比。
7. **本文未覆盖**：安装包签名、自动更新、多用户权限模型、CI 构建流水线。

---

## 8. 专题：VTK 窗口嵌入在 Ubuntu 下怎么解决

### 8.1 边界澄清：OCC 要保留，但 RadSim 的 3D 视图不是 OCC

- conda 环境叫 `pyoccenv`，`environment.yml` 里含 `occt`、`pythonocc-core`、`gmsh`、`pyvista`、`pyqtgraph`。**这些要保留**：RadSim 只是套件中的一员，另有专用 OCC 程序，环境必须统一，不能为 RadSim 单独裁剪。
- 但对 **RadSim 这个程序本身**：代码对 OCC/pythonocc **零 import**（全文搜索结果为 0），3D 视图用的是 **VTK**（`vtkmodules`）。
- `ui/vtk_widget.py` 里的 "same style as OCC's Viewer3d" 只是**风格致敬**（照抄 cad2gdml 的显示行为），不是 OCC 代码。
- 结论：RadSim 的 Wayland 黑屏是 **VTK legacy 窗口嵌入**造成的，与 OCC 无关；但**同样的坑 OCC 侧也有**（见 8.2），统一环境反而便于用同一套启动策略一次解决。

### 8.2 OCC 侧也有同样的限制（重要）

OCCT 的可视化同样依赖**原生窗口句柄**：`Aspect_Window` 只有 `WNT_Window`（Windows）、`Xw_Window`（X11/Xlib）、`Cocoa_Window`（macOS）、`EGL_Window`（离屏）几种实现，**没有 Wayland 后端**。

- 因此用 `V3d_View` + `AIS_InteractiveContext` 的专用 OCC 程序，在原生 Wayland 会话下**同样起不来**，表现与 RadSim 一致（黑屏/建窗失败）。
- 好消息：`Xw_Window` 在 **XWayland** 下正常工作（程序被当作 X11 客户端）。
- 所以整个套件的策略可以统一：**在启动器层面统一设 `QT_QPA_PLATFORM=xcb`**。若 OCC 程序不用 Qt 而用裸 Xlib，等价做法是确保它跑在 XWayland 会话里（不要用 `GDK_BACKEND=wayland` 之类的原生 Wayland 启动方式）。
- 这正好利用了"环境统一"的前提：**一处配置，全套件受益**。
- 长期想彻底摆脱 XWayland：VTK 侧走方案 B（`QVTKOpenGLNativeWidget`，见 8.5）即可；OCC 侧在 OCCT 官方支持 Wayland 之前，仍需 XWayland 或 `EGL_Window` 离屏渲染。

### 8.3 为什么 legacy 组件在 Wayland 下不行

`QVTKRenderWindowInteractor` 的工作方式是"原生窗口 ID 嵌入"：

1. 创建一个带 `WA_NativeWindow` 的 `QWidget`；
2. 用 `winId()` 取**原生窗口句柄**（Windows = HWND，X11 = XID，一个整数）；
3. 把该整数交给 VTK：`renderWindow.SetWindowInfo(str(wid))`；
4. VTK 的 OpenGL2 后端在这个原生窗口上**直接建 GL 上下文**（Windows 用 WGL，X11 用 GLX）。

Wayland 下客户端**拿不到这种可绘制的原生句柄**：`winId()` 返回的不是 XID，而 VTK 的 legacy 路径**没有 Wayland 后端**。于是上下文创建失败 → 黑屏/空白，严重时崩溃。

所以先看会话类型：

```bash
echo $XDG_SESSION_TYPE        # wayland / x11
python -c "from PyQt6.QtWidgets import QApplication; from PyQt6.QtGui import QGuiApplication; QApplication([]); print(QGuiApplication.platformName())"
```

- 打印 `xcb` → 走 X11/XWayland，**legacy 组件可正常工作**；
- 打印 `wayland` → legacy 组件大概率失效。

Ubuntu 22.04 / 24.04 的 GNOME 默认是 Wayland；登录界面可切到 "Ubuntu on Xorg" 验证。

### 8.4 方案 A：强制走 XWayland（0 行代码，先解封）

Ubuntu 默认带 XWayland，只要让 Qt 用 `xcb` 平台插件，`winId()` 就返回真正的 XID，legacy 组件行为与 X11 一致。

```bash
export QT_QPA_PLATFORM=xcb
python main.py
```

三种落地方式：
- 命令行：`QT_QPA_PLATFORM=xcb python main.py`
- 桌面快捷方式：`Exec=env QT_QPA_PLATFORM=xcb /path/to/python /path/to/main.py`
- 代码里（`main.py` 创建 `QApplication` **之前**，且仅在 Wayland 会话下）：`os.environ.setdefault("QT_QPA_PLATFORM", "xcb")`

前提与代价：
- 需装 `libxcb-*` 系列（见 5.1 节）；
- 没有 XWayland 的精简环境（部分 wlroots 组合器）下 `xcb` 会连不上 display；
- 这是**规避**不是修复；分数缩放下 XWayland 窗口可能偏糊。

### 8.5 方案 B：迁移到 `QVTKOpenGLNativeWidget`（推荐长期）

VTK 官方给 Qt 的现代集成（`vtkmodules.qt.QVTKOpenGLNativeWidget`，VTK ≥ 9.0，当前 9.3.1 可用）。它用 **Qt 自己的 OpenGL 上下文**（`QOpenGLWidget`），Windows / X11 / Wayland / macOS 表现一致，**不再需要 WId 绑定与重绑**，HiDPI 由 Qt 处理。

改动集中在 `ui/vtk_widget.py`，对外 API（`get_scene` / `build_scene` / `render` / `node_picked`）不变：

| 现在 | 改成 |
|---|---|
| `QVTKRenderWindowInteractor` | `QVTKOpenGLNativeWidget` + `vtkGenericOpenGLRenderWindow` |
| `self._vtk_interactor.GetRenderWindow()` | 自建的 `self._render_window` |
| `self._vtk_interactor.Initialize()` / `Start()` | 新组件由 Qt 事件循环驱动，按官方示例通常只需 `GetInteractor().Initialize()`，**不要沿用 `showEvent` 里 `Start()` 的写法** |
| `_ensure_window_bound()` + `_bound_wid` / `_bound_once` / `SetWindowInfo` / `Finalize` | **整段删除**（既是 Wayland 问题的根源，也是 Windows `wglMakeCurrent failed` 的来源） |
| `ReportCapabilities()` 正则解析 | 可用 VTK 9 的 `GetOpenGLVendor()/GetOpenGLRenderer()/GetOpenGLVersion()` 简化 |
| `SetSwapControl(0)` 关 vsync | 保留但别依赖：Wayland 由合成器决定，X11 下 GLX 可能静默无效 |

**关键前置条件**：必须在 `QApplication` 创建**之前**设置默认 `QSurfaceFormat`，否则 `QOpenGLWidget` 可能拿到不兼容上下文（黑屏或 `Failed to create OpenGL context`）：

```python
from PyQt6.QtGui import QSurfaceFormat
fmt = QSurfaceFormat()
fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
fmt.setVersion(3, 2)
fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setStencilBufferSize(8)
fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
fmt.setSamples(0)          # 与现在的 SetMultiSamples(0) 保持一致
QSurfaceFormat.setDefaultFormat(fmt)
```

工作量：约 1 个文件、50–80 行；需回归测试拾取、剖切、工具栏、体素渲染、窗口隐藏/显示。

### 8.6 方案 C（不推荐）

- **独立 VTK 窗口**（不做 Qt 嵌入）：体验割裂。
- **离屏渲染 + `vtkWindowToImageFilter` 贴到 QLabel**：交互要自己实现、性能差，仅在无 GPU / 纯远程桌面场景兜底。

### 8.7 建议路线

1. **套件层面**：在统一启动器（或各程序的 `.desktop`）里统一设 `QT_QPA_PLATFORM=xcb`，让 RadSim 与专用 OCC 程序一起跑在 XWayland 下——零代码风险，可立刻做第 6 章验收。
2. **RadSim 层面**：排期做**方案 B**，一次性消掉 WId 重绑逻辑。它同时是 Windows 侧 `wglMakeCurrent failed` 的根源，属"双平台同时受益"的改造。
3. **OCC 程序层面**：在 OCCT 官方支持 Wayland 之前继续依赖 XWayland；若该程序需要无头/远程运行，评估 `EGL_Window` 离屏路线。
4. 方案 B 完成后 RadSim 不再需要 `QT_QPA_PLATFORM=xcb`，可回归原生 Wayland；但套件里只要还有 OCC 程序，统一设 `xcb` 仍更省事。

---

## 附：与其它文档的关系

- 架构与分层 → `doc/01-architecture.md`
- 求解器启动/状态机细节 → `doc/04-execution.md`
- 宏文件格式与生成 → `doc/03-mac-builder.md`
- 可视化实现 → `doc/07-visualization.md`
- Windows 环境与排障 → `doc/10-troubleshooting.md`（建议后续补 Linux 段）
