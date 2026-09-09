# 01 · 架构总览

> 版本 0.1.0 ｜ 对应代码：`main.py`、`app/`、`core/`、`vtk_engine/`、`ui/`、`utils/`

## 1. 定位

RadSim 是 **rad4space（Geant4 batch 求解器）的图形前端**。它自身不做物理计算，
职责可以概括为三件事：

1. **看懂几何**：解析 GDML，重建 Geant4 的「逻辑体积 / 物理放置」两级模型，并渲染成 3D；
2. **翻译配置**：把界面上的表单翻译成一份 `run.mac`；
3. **调度与呈现**：以子进程方式运行求解器，把控制台输出与结果 CSV 回收成可视化视图。

因此整个系统的边界非常清晰：**求解器是黑盒，宏文件是唯一接口**（见
[03-mac-builder.md](03-mac-builder.md)）。

## 2. 分层

| 层 | 目录 | 职责 | 允许依赖 |
|---|---|---|---|
| 入口 | `main.py` | 创建 `QApplication`、装配主窗口 | `app` |
| 编排 | `app/main_window.py` | 布局、信号连接、任务编排、项目存取、线程管理 | 全部下层 |
| 领域 | `core/` | GDML 解析/写回、材料库、宏生成、运行调度、项目 IO | 仅 `PyQt6.QtCore`（`QObject`/`pyqtSignal`/`QSettings`/`QProcess`） |
| 渲染 | `vtk_engine/` | VTK 场景与实体工厂 | `vtkmodules`、`core` |
| 表现 | `ui/`、`ui/dialogs/` | 控件与对话框 | `core`、`vtk_engine` |
| 基础设施 | `utils/logger.py` | 异步日志单例 | 无 |
| 资源 | `data/` | `element.xml`、`nist.txt` | — |
| 外部 | `solver/` | rad4space 源码/构建产物/运行输出 | — |

**依赖方向是单向的**：`ui → core / vtk_engine → core`。`core` 里除了
`PyQt6.QtCore` 的几个基础设施类，不引用任何 UI，因此核心逻辑可以脱离界面单独测试。

`ui/dialogs/physics_config.py` 与 `ui/dialogs/gps_source.py` 虽然物理上位于 UI 目录，
但其中的 `macro_lines(cfg)` 是**纯函数**，被 `core/mac_builder.py` 反向调用。
这是唯一一处「core → ui」的引用，属于有意的折衷：宏命令的知识只写一份。

## 3. 模块依赖图

```
                          main.py
                             │
                     app/main_window.py ─────────────────┐
                        │        │        │               │
          ┌─────────────┤        │        │               │
          ▼             ▼        ▼        ▼               ▼
     ui/*.py     ui/dialogs/*.py  core/*.py        utils/logger.py
          │             │             │
          │             └──► (macro_lines 纯函数)
          ▼                           ▼
     vtk_engine/*.py  ◄──────── GdmlAgent / GdmlParser / GdmlWriter
          │                           │
          ▼                           ▼
      vtkmodules                 data/element.xml
                                 data/nist.txt

     core/run_manager.py ──QProcess──► solver/rad4space/build/Release/rad4space.exe
                                                      │
                                                      ▼
                                          solver/runs/<task>/*.csv
```

## 4. 四条关键数据流

### 4.1 几何流（导入）

```
.gdml ─► GdmIParser.parse_file ─► GdmlNode 树 ─► GdmlAgent（单例）
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                  ▼
            ProjectTreeWidget   VtkScene.build_from_tree   MacPreview
              （左侧树）           （中央 3D）              （右侧宏预览）
```

大文件（≥ 500 KB）时，`parse_file` 在 `_ImportWorker` 线程里跑，结果通过队列信号
回主线程，再由主线程**一次性**重建树与场景。

### 4.2 配置流（编辑）

```
对话框表单 ─► RunTask.{particle,physics,calculate,analysis_config}
                    │
                    └─► MacPreviewDock 实时预览 build_mac_text(...)
```

配置直接写在 `RunTask` 对象上（对话框持有同一个引用），保存时序列化进 `project.json`。

### 4.3 运行流（执行）

```
Run 启动器 ─► MainWindow._start_selected_tasks ─► RunManager.start(names)
                                                       │
                          ┌────────────────────────────┘
                          ▼
        write_workdir() → run.mac → QProcess(rad4space run.mac)
                          │                    │
                          ▼                    ▼
                   run.log（重定向）      out_*.csv / h1_*.csv
```

### 4.4 结果流（呈现）

```
out_*.csv ─► probe_result_viewer.build_result_groups ─► 项目树 Results 子树
rad4space_h1_*.csv ─┘                                      │
                                                           ├─► ProbeResultChartDialog（曲线）
Traj.csv ──────────────────────────────────────────────────┴─► TrajectoryViewerDialog（轨迹）
```

`probe_result_viewer.py` 刻意不 import Qt/matplotlib，保证项目树构建时保持轻量。

## 5. 进程与线程模型

| 场景 | 机制 | 说明 |
|---|---|---|
| 全部 UI / VTK 渲染 | 主线程 | VTK 与 Qt 都非线程安全，所有场景操作都在主线程 |
| 大 GDML 解析（≥ 500 KB） | `QThread` + `_ImportWorker`（`moveToThread`） | 只调用线程安全的 `parse_file_only`，结果暂存在 `_pending_gdml_node`，回到主线程才替换 |
| 求解器运行 | `QProcess` 子进程 | 不占 Python 线程；`QTimer` 心跳每 300 ms 推进度 |
| 日志 | `AsyncLogger` 单例 | 后台队列写入，UI 通过 `set_system_log_widget` 注入的控件消费 |
| 建树 / 建场景 | 主线程 + `processEvents` 节流 | 大模型下用 `_make_rebuild_flusher` 每 0.1 s 刷新进度框，避免界面假死 |

**没有多线程共享可变状态**：后台线程只产出「解析结果」，不做任何 UI 或 `GdmlAgent`
状态修改。`GdmlAgent` 复用单个 `GdmIParser` 实例，其可变状态也只在主线程被访问。

## 6. 单例与长生命周期对象

| 对象 | 位置 | 生命周期 |
|---|---|---|
| `GdmlAgent` | `core/gdml_agent.py` | 进程级单例，持有全部几何数据与覆盖项 |
| `AsyncLogger` | `utils/logger.py` | 进程级单例 |
| `VtkSolidFactory` | `vtk_engine/vtk_solid_factory.py` | 单例，内部有几何缓存 `_geometry_cache` |
| `RunManager` | `MainWindow.__init__` | 与主窗口同寿命，`max_concurrent=2` |
| 运行启动器 / 任务监视器 | `MainWindow` 懒建 | 首次打开时创建，之后复用 |
| 各配置对话框 | 按任务缓存 | `_analysis_dialogs` / `_particle_dialogs` / `_physics_dialogs` / `_calculate_dialogs`，关闭时清缓存 |
| 各结果查看器 | 按任务缓存 | `_voxel_viewers` / `_traj_viewers` |

## 7. 信号总线

界面没有集中式的事件总线，而是**就近连接**，三条主线：

| 来源 | 信号 | 去向 |
|---|---|---|
| `RibbonToolBar` | `import_clicked` / `load_clicked` / `save_clicked` / `run_clicked` / `stop_clicked` / `reset_view_clicked` / `status_clicked` / `solver_setting_clicked` / `theme_toggled` / `help_clicked` | `MainWindow._on_*` |
| `ProjectTreeWidget` | `node_selected` / `visibility_changed` / `task_action` / `task_context` | `MainWindow._on_node_selected` / `_on_visibility_changed` / `_on_task_action` / `_on_task_context` |
| `VtkWidget` | `node_picked` | `MainWindow._on_node_picked`（树与 3D 双向联动） |
| `RunManager` | `task_started` / `task_progress` / `task_finished` / `all_finished` / `task_added` | 主窗口 + 两个监视窗口 |
| `GdmlNode` | `data_changed` | 触发场景/树刷新 |

## 8. 全局约定

| 项 | 约定 |
|---|---|
| 长度单位 | 界面与内部一律 **mm**；宏文件里按求解器要求换算为 cm（见 03 文档） |
| 角度单位 | **deg** |
| 密度 | g/cm³ |
| 任务目录名 | `safe_task_name()`：非 `[A-Za-z0-9_.\-]` 的字符替换为 `_` |
| 任务标识 | 任务名即字典键（`RunManager._tasks: name → RunTask`），因此**任务名必须唯一** |
| 持久化 | `QSettings("RadSim", "RadSim")`，键 `solver/executable`、`solver/qt_bin_dir`、`solver/results_root` |
| 日志 | 统一走 `AsyncLogger.log_system(...)`，禁止裸 `print` |
| 异常 | UI 层捕获后弹 `QMessageBox.warning` 并记日志，不向上抛 |

## 9. 扩展点

| 想加什么 | 需要改哪里 |
|---|---|
| 新的 GDML 实体类型 | `core/gdml_parser.py` 加 `_parse_xxx`；`vtk_engine/vtk_solid_factory.py` 的 `_build_polydata` 加分派分支；`collision_detector.compute_half_size` 补尺寸 |
| 新的计分数量 | `ui/dialogs/analysis_common.QUANTITY_TYPES`（权威清单）；同步 `core/mac_builder._HIST_XUNIT` 与 `_QUANTITY_UNIT` |
| 新的分析模式 | 新对话框 + `core/mac_builder.scoring_block()` 新分支 + `probe_result_viewer` 分组 + 项目树结果节点 + `main_window._refresh_task_results` |
| 新的结果查看器 | `ui/` 下新增对话框，在 `result_viewer.py` 或 `main_window` 里按文件类型分派 |
| 新的工具栏按钮 | `ui/ribbon_toolbar.py` 加信号 + 按钮；`main_window._connect_signals()` 连接 |

## 10. 相关文档

- [02 · GDML 处理链路](02-gdml-pipeline.md)
- [03 · run.mac 生成](03-mac-builder.md)
- [04 · 运行调度](04-execution.md)
- [05 · 分析与结果](05-analysis.md)
- [06 · 项目保存与加载](06-project-io.md)
- [07 · 可视化](07-visualization.md)
- [08 · 界面参考](08-ui-reference.md)
- [09 · 数据格式](09-data-formats.md)
- [10 · 环境与排错](10-troubleshooting.md)
