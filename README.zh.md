# RadSim

RadSim 是辐射求解器 [rad4space](solver/rad4space/README.md) 的图形前端（GUI）：
在 3D 视图中浏览 GDML 几何、可视化配置粒子源与物理过程、批量运行蒙特卡罗仿真，
并直接查看体素剂量、探针通量、能谱和粒子轨迹等结果。

- 语言：Python 3.10
- 界面：PyQt6 + VTK
- 求解器：基于 Geant4 11.4.2 的 batch 可执行程序 `rad4space.exe`
- 平台：Windows x64（当前仅在 Windows 上验证）

> **版本 0.1.0** ｜ 最后更新 2026-09-09 ｜ 模块级开发文档见 [`doc/`](doc/README.md)

## 功能特性

| 模块 | 说明 |
|---|---|
| GDML 几何 | 导入 GDML，树形浏览层级结构，3D 渲染并支持拾取、显隐、位移编辑 |
| 任务管理 | 一个项目可包含多个任务，每个任务独立配置几何、源、物理和分析 |
| 粒子源 | GPS 通用源：单能 / 能谱 / 离子，位置与方向可视化预览 |
| 物理过程 | 可切换物理列表（FTFP_BERT / Shielding 等），设置生产阈值与最大步长 |
| 分析模式 | real world（逻辑体积）、probe（探针）、voxel（直角网格）三种计分方式 |
| 运行调度 | 多任务队列，并发上限 2，实时进度与日志，可随时停止 |
| 结果查看 | 3D 体素云图、探针对比曲线、能谱直方图、粒子轨迹、运行日志、通用文件查看 |
| 项目持久化 | 项目 = 一个文件夹（`project.json` + `geometry/` + `results/`），可整体迁移 |
| 实时预览 | 右侧面板按当前配置实时生成 `run.mac` 预览 |

## 界面概览

```
┌──────────────────────────────────────────────────────────────────────┐
│ 📁 Import GDML │ 🧾 Load Project │ 💾 Save Project ┃ 🎯 Reset View ┃  │
│ ▶️ Run │ 🟢 Idle │ ⏹ Stop ┃ ⚙️ Solver Setting │ ☀️ Theme │ ❓ Help  │
├──────────────┬───────────────────────────────────┬───────────────────┤
│  Project 树  │          3D 视图 (VTK)            │  run.mac 预览     │
│              ├───────────────────────────────────┤                   │
│              │          系统日志                 │                   │
├──────────────┴───────────────────────────────────┴───────────────────┤
│ 状态栏                                                                │
└──────────────────────────────────────────────────────────────────────┘
```

工具栏按钮：

| 按钮 | 功能 |
|---|---|
| 📁 Import GDML | 导入 GDML 几何（一个项目仅支持一个几何文件） |
| 🧾 Load Project | 打开已保存的项目（选择 `project.json`） |
| 💾 Save Project | 保存项目；首次保存时选择项目文件夹 |
| 🎯 Reset View | 3D 相机复位 |
| ▶️ Run | 打开运行启动器，勾选任务并启动 |
| 🟢 Idle / 🔄 Running / ⚠️ Issues / ✅ Done | 任务监控窗口，显示每个任务的进度与状态 |
| ⏹ Stop | 停止所有正在运行的任务 |
| ⚙️ Solver Setting | 配置求解器可执行文件与 Qt 运行时目录 |
| 🌙 / ☀️ Theme | 深色 / 浅色主题切换 |
| ❓ Help | 帮助 |

## 目录结构

```
RadSim/
├── main.py                     程序入口（QApplication + 主窗口）
├── app/
│   └── main_window.py          主窗口：布局、信号连接、任务编排、项目存取
├── core/                       与界面解耦的核心逻辑
│   ├── gdml_parser.py          GDML 解析（define/materials/solids/structure/setup）
│   ├── gdml_tree.py            GDML 数据节点树（GdmlNode / Placement）
│   ├── gdml_evaluator.py       GDML 属性表达式求值
│   ├── gdml_writer.py          GDML 写回（多文件合并、位移覆盖、本地材料注入）
│   ├── gdml_agent.py           GDML 数据代理（单例，统一入口）
│   ├── materials_lib.py        材料库（NIST + 自定义元素 / 化合物 / 混合物）
│   ├── mac_builder.py          生成 run.mac 与任务工作目录
│   ├── collision_detector.py   实体 AABB 碰撞检测
│   ├── run_manager.py          多任务运行调度（QProcess）
│   ├── project_io.py           项目保存 / 加载（文件夹式）
│   ├── project_model.py        RunTask / CalculateSetting 数据模型
│   └── solver_config.py        求解器路径与结果目录（QSettings）
├── vtk_engine/                 VTK 场景管理与实体工厂
│   ├── vtk_scene.py            渲染窗口、actor 树、拾取 / 高亮
│   └── vtk_solid_factory.py    按 GDML 实体类型构建 polydata / actor
├── ui/                         PyQt 界面组件
│   ├── ribbon_toolbar.py       Ribbon 工具栏
│   ├── project_tree.py         项目树（几何 + 任务 + 结果）
│   ├── vtk_widget.py           3D 视图控件
│   ├── mac_preview.py          右侧 run.mac 预览面板
│   ├── trajectory_viewer.py    粒子轨迹查看器
│   ├── voxel_result_viewer.py  体素结果 3D 查看器
│   ├── probe_result_viewer.py  计分结果读取与分组（无 Qt 依赖）
│   ├── probe_chart_dialog.py   探针 / real world 对比图（matplotlib）
│   └── dialogs/                各配置与结果对话框
├── utils/logger.py             异步日志单例
├── data/                       element.xml（元素表）、nist.txt（NIST 材料表）
├── solver/                     rad4space 源码、构建产物与运行输出
│   ├── rad4space/              求解器（C++，Geant4）
│   └── runs/                   默认的任务输出根目录
└── test/                       测试用 GDML 与样例数据
```

## 安装

### 方式一：conda（推荐）

项目在 Python 3.10 的 conda 环境中开发，`environment.yml` 是从该环境完整导出的快照：

```bash
conda env create -f environment.yml
conda activate pyoccenv
python main.py
```

### 方式二：pip

```bash
pip install -r requirements.txt
python main.py
```

> 代码中导入 VTK 使用 `vtkmodules`，对应的 PyPI 包名是 `vtk`。
> `matplotlib` 仅在探针 / real world 对比图对话框中使用，缺失时该对话框会提示安装。

### 求解器 rad4space

GUI 只是前端，真正的仿真由 `solver/rad4space/` 下的 Geant4 程序完成。
仓库中已包含构建好的 `solver/rad4space/build/Release/rad4space.exe`；
如需自行编译，参见 [solver/rad4space/README.md](solver/rad4space/README.md)
（依赖 Geant4 11.4.2、xerces-c、Qt 6.11）。

求解器可执行文件路径与 Qt 运行时目录可在 **⚙️ Solver Setting** 中配置，
并通过 `QSettings` 持久化；留空时按以下顺序自动探测：

```
solver/rad4space/build/Release/rad4space.exe
solver/rad4space/build/rad4space.exe
solver/rad4space/rad4space.exe
```

> 注意：从 conda 环境启动求解器时，若其自带的旧版 Qt6 DLL 抢先加载，
> 求解器会以 `0xC0000135` / `0xC0000139` 退出。RadSim 会在启动求解器前
> 把配置的 Qt bin 目录前置到 `PATH`，因此在 Solver Setting 中填对 Qt 路径即可。

## 使用说明

### 1. 导入几何

点击 **📁 Import GDML**。几何文件小于 500 KB 时同步解析，否则在后台线程解析
（界面保持响应）。导入后：

- 左侧 Project 树出现 Geometry 子树，勾选框控制可见性；
- 中央 3D 视图渲染几何，单击可选中并反选树节点；
- 系统会自动创建一个默认任务 `Run_001`。

> 一个项目只支持一个 GDML。再次导入会询问是否替换当前几何与任务。

### 2. 配置任务

在 Project 树中双击任务下的节点进行配置：

| 节点 | 配置内容 |
|---|---|
| Calculate Setting | 线程数、事件数 |
| Particle Setting | 粒子类型、能量 / 能谱、位置、方向分布 |
| Physics Process | 物理列表、生产阈值、最大步长 |
| Analysis → real world / probe / voxel | 计分对象与计分数量 |

右侧 **run.mac 预览** 面板会实时显示当前配置生成的宏文件内容。

三种分析模式：

- **real world**：按逻辑体积计分，选择要统计的体积及计分数量；
- **probe**：在指定位置放置探针立方体，配置半长、材质与计分数量；
- **voxel**：直角网格，配置网格范围（全几何或手动）、分箱数与计分数量。

### 3. 运行

点击 **▶️ Run** 打开运行启动器，勾选要运行的任务后启动。
`RunManager` 以最多 2 个任务并发的方式排队执行：

- 每个任务在 `<结果根目录>/<任务名>/` 下生成 `run.mac` 并启动求解器；
- 求解器 stdout/stderr 合并写入 `run.log`；
- 进度条与状态（idle / queued / running / completed / failed / stopped）实时同步到
  项目树与监控窗口；
- 点击 **⏹ Stop** 可停止全部任务（先 `terminate`，2 秒后未退出则 `kill`）。

未配置求解器时，会以模拟进度运行，便于测试界面流程。

### 4. 查看结果

任务完成后，Project 树会自动挂上 Results 子树。双击结果节点：

| 结果 | 查看器 |
|---|---|
| 体素网格（`q:`） | 3D 体素云图 |
| 探针 / real world 计分（`pq:` / `rq:`） | 对比曲线图（matplotlib） |
| 能谱直方图（`ph:` / `rh:`） | 对比曲线图 |
| 粒子轨迹 | 轨迹查看器（按粒子类型着色） |
| run log | 日志查看器 |
| 其他文件 | 通用文件查看器 |

## 项目文件格式

一个项目就是一个文件夹：

```
MyProject/
├── project.json          配置：几何引用 + 任务列表
├── geometry/*.gdml       导入 GDML 的副本
└── results/<task>/       每个任务运行输出的快照
```

`project.json` 字段：

| 字段 | 说明 |
|---|---|
| `format` | 固定为 `radsim-project`（兼容旧的 `3drad-project`） |
| `version` | 当前为 `1` |
| `gdml_paths` | 几何文件路径，复制到 `geometry/` 后存**相对路径**，便于整体迁移 |
| `tasks` | 任务列表，每个任务包含 `name`、`analysis_type`、`particle`、`physics`、`calculate`、`analysis_config` 等 |

保存是“硬保存”：几何与 `results/` 全量镜像，删除任务同时删除其已保存结果。
加载项目时会先清理草稿输出目录，再从 `project.json` 重建任务与结果树。

> 首次保存后项目文件夹即固定，之后再次保存会原地更新。

## 输出文件

任务输出位于 `<结果根目录>/<任务名>/`（默认 `solver/runs/<任务名>/`）：

| 文件 | 说明 |
|---|---|
| `run.mac` | 本次运行使用的宏文件 |
| `run.log` | 求解器标准输出 / 错误 |
| `out_*.csv` | 各计分网格的积分值（每个 primitive scorer 一个块） |
| `rad4space_h1_*.csv` | 一维能谱直方图 |
| `Traj.csv` | 粒子轨迹点（`eventID, trackID, parentID, particle, step, x, y, z`） |

## 配置持久化

以下设置通过 `QSettings`（`RadSim/RadSim`）保存到注册表：

| 键 | 说明 |
|---|---|
| `solver/executable` | 求解器可执行文件路径 |
| `solver/qt_bin_dir` | 求解器所需的 Qt 运行时 bin 目录 |
| `solver/results_root` | 任务输出根目录（默认 `solver/runs`） |

## 已知限制

- GDML `<materials>` 为简化解析，仅记录材料名与密度；
- 部分实体类型（`polyhedra`、`xtru`、布尔运算、`multiUnion`、`scaledSolid` 等）
  不参与 3D 渲染，仅在导出时原样写回，导入时会给出提示；
- 表达式求值中未定义的标识符会被替换为 `0`；
- 空心球（`rmin > 0`）在预览中简化为外壳，`cone` 以 16 段圆柱近似；
- 一个项目只支持一个 GDML 几何；
- GUI 内部长度单位为 **mm**，写入宏文件时统一换算为 **cm**；
- 多线程运行时 `Traj.csv` 只包含被选中的那一个 worker 线程处理的事件，
  需要完整轨迹时请在宏中固定 `/run/numberOfThreads 1`。

## 开发说明

- **线程模型**：仅大 GDML（≥ 500 KB）解析在 `QThread` 中进行，且只调用
  线程安全的 `parse_file_only`，结果经队列信号回主线程原子替换；
  其余 UI 与场景构建都在主线程。
- **运行调度**：`RunManager` 全程非阻塞（`QProcess` + `QTimer` 心跳），
  仅在启动时 `waitForStarted(3000)`、停止时 `waitForFinished(2000)` 做有限阻塞。
- **VTK 窗口**：使用 `QVTKRenderWindowInteractor`，窗口隐藏 / 显示会重建原生窗口
  导致 `WId` 变化，`VtkWidget` 检测到后重新绑定；关闭主窗口时先关闭所有二级窗口
  以释放 GL 上下文。
- **单例**：`GdmlAgent` 与 `AsyncLogger` 均为单例。

## 版本历史

| 版本 | 日期 | 说明 |
|---|---|---|
| 0.1.0 | 2026-09-09 | 首个版本：GDML 导入与 3D 浏览、任务配置、realworld / probe / voxel 三种分析、多任务运行调度、项目保存与加载、结果可视化 |

## 相关文档

- **开发文档（模块级）**：[`doc/`](doc/README.md)
  - [架构总览](doc/01-architecture.md) ｜ [GDML 处理链路](doc/02-gdml-pipeline.md) ｜ [run.mac 生成](doc/03-mac-builder.md)
  - [运行调度](doc/04-execution.md) ｜ [分析与结果](doc/05-analysis.md) ｜ [项目保存与加载](doc/06-project-io.md)
  - [可视化](doc/07-visualization.md) ｜ [界面参考](doc/08-ui-reference.md) ｜ [数据格式](doc/09-data-formats.md) ｜ [环境与排错](doc/10-troubleshooting.md)
- 求解器说明与构建方法：[solver/rad4space/README.md](solver/rad4space/README.md)
- 英文版说明：[README.en.md](README.en.md)
