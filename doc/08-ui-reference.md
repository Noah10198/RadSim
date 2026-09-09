# 08 · 界面参考

> 源码：`app/main_window.py`、`ui/ribbon_toolbar.py`、`ui/project_tree.py`、
> `ui/mac_preview.py`、`ui/dialogs/*`

## 1. 主窗口布局

```
┌───────────────────────────────────────────────────────────────────────┐
│ QToolBar ── RibbonToolBar                                              │
├──────────────┬────────────────────────────────────┬───────────────────┤
│ QDockWidget  │  QSplitter(Vertical)               │ QDockWidget       │
│ "Project"    │   ├─ QStackedWidget _center_stack  │ "Run Macro        │
│  ProjectTree │   │   0 = QLabel 占位               │  Preview"         │
│  Widget      │   │   1 = VtkWidget 3D 视图        │  MacPreviewDock   │
│              │   └─ QTextEdit 日志面板            │                   │
├──────────────┴────────────────────────────────────┴───────────────────┤
│ 状态栏 QLabel _status_label                                            │
└───────────────────────────────────────────────────────────────────────┘
```

`_center_stack` 的 index 0 是导入几何前的占位提示，导入成功后切到 index 1。
中央 `QSplitter` 上下比例 3:1（初始 600:150）。

## 2. Ribbon 工具栏

| 按钮 | 信号 | 主窗口槽 | 行为 |
|---|---|---|---|
| 📁 Import GDML | `import_clicked` | `_on_import_gdml` | 导入几何（≥500 KB 走后台线程） |
| 🧾 Load Project | `load_clicked` | `_load_project` | 打开 `project.json` |
| 💾 Save Project | `save_clicked` | `_save_project` | 首次选目录，之后原地保存 |
| 🎯 Reset View | `reset_view_clicked` | `_on_reset_view` | 相机复位 |
| ▶️ Run | `run_clicked` | `_on_run` | 打开运行启动器 |
| 🟢 Idle / 🔄 / ⚠️ / ✅ | `status_clicked` | `_on_status_clicked` | 打开任务监视器，图标随状态变化 |
| ⏹ Stop | `stop_clicked` | `_on_stop` | `RunManager.stop_all()` |
| ⚙️ Solver Setting | `solver_setting_clicked` | `_on_solver_setting` | 求解器路径配置 |
| 🌙 / ☀️ Theme | `theme_toggled` | `_toggle_theme` | 明暗主题 |
| ❓ Help | `help_clicked` | `_on_help` | 关于/帮助 |

## 3. 项目树

### 层级

```
Project
├── Geometry
│   └── <GDML 文件>            ☑ 可勾选
│       ├── Solids
│       │   └── <solid 定义>   不可勾选（非 box 时文本带 [tag]）
│       └── World
│           └── <放置实例>      ☑ 可勾选（下钻到 PHYSVOL，不单独建节点）
└── Tasks
    └── <任务名>
        ├── Calculate Setting [N threads]
        ├── Particle Setting
        ├── Physics Process
        ├── Analysis
        │   ├── Real World
        │   ├── Probe
        │   └── Voxel
        └── Results
```

### 交互

| 交互 | 效果 |
|---|---|
| 单击节点 | `node_selected(str)` → 3D 高亮 |
| 勾选/取消 | `visibility_changed(str, bool)` → 场景显隐 |
| 3D 里单击 | `node_picked(str)` → 树定位（双向联动） |
| 双击任务子节点 | 打开对应配置对话框 |
| 双击结果节点 | 打开对应查看器 |
| 右键任务节点 | `task_context` / `task_action` 回传动作（新增任务、重命名、复制、删除、运行等） |

任务节点会显示状态标记：线程数、是否已配置粒子/物理/分析、运行状态。

## 4. 右侧宏预览

`MacPreviewDock`：顶部下拉切换任务，主体用等宽字体显示
`core.mac_builder.build_mac_text(gdml_path, task)` 的结果。
任何配置保存后主窗口调用 `_refresh_mac_preview()` 重渲；发出 `task_changed(str)`
时由 `_render_mac_preview` 切换任务。

## 5. 日志与状态栏

- 日志：`QTextEdit`，通过 `AsyncLogger.set_system_log_widget()` 注入，只读、自动滚动；
- 状态栏：`Files loaded: N`、运行状态、最近一次操作提示。

## 6. 对话框清单

| 文件 | 类 | 类型 | 打开方式 | 写入 |
|---|---|---|---|---|
| `calculate_setting_dialog.py` | `CalculateSettingDialog` | 配置 | `_open_calculate_setting` | `task.calculate.n_threads` |
| `particle_dialog.py` | `ParticleDialog` | 配置 | `_open_particle_dialog` | `task.particle` |
| `physics_dialog.py` | `PhysicsDialog` | 配置 | `_open_physics_dialog` | `task.physics` |
| `realworld_dialog.py` | `RealWorldDialog` | 配置 | `_open_analysis_dialog("realworld")` | `analysis_config["realworld"]` |
| `probe_dialog.py` | `ProbeDialog` | 配置 | `_open_analysis_dialog("probe")` | `analysis_config["probe"]` |
| `voxel_dialog.py` | `VoxelDialog` | 配置 | `_open_analysis_dialog("voxel")` | `analysis_config["voxel"]` |
| `solver_setting_dialog.py` | `SolverSettingDialog` | 配置 | `_on_solver_setting` | QSettings |
| `run_monitor.py` | `RunMonitorDialog` / `TaskMonitorDialog` | 运行 | `_ensure_run_launcher` / `_ensure_task_monitor` | — |
| `result_viewer.py` | — | 结果 | 通用文件查看 | — |
| `analysis_common.py` | 若干组件 | 公共 | 被三个分析对话框复用 | — |
| `gps_source.py` / `physics_config.py` | 纯函数 | 公共 | 被 `mac_builder` 调用 | — |
| `particle_geo.py` / `particle_preview.py` / `source_geo_preview.py` | 预览 | 预览 | 被粒子/分析对话框复用 | — |
| `direction_preview.py` / `gps_direction_preview.py` / `gun_direction_preview.py` | 方向预览 | 预览 | 被粒子对话框复用 | — |

对话框缓存键：`_analysis_dialogs[(task, kind)]`、`_particle_dialogs[("particle", task)]`、
`_physics_dialogs[("physics", task)]`、`_calculate_dialogs[("calculate", task)]`，
关闭时清除。

## 7. 结果查看器

| 查看器 | 触发 | 数据源 |
|---|---|---|
| `VoxelResultViewer` | 双击 `Voxel <q>` 节点 | `out_Box_<q>.csv` |
| `TrajectoryViewerDialog` | 双击 `Trajectory` 节点 | `Traj.csv` |
| `ProbeResultChartDialog` | 双击 quantity / histogram 组 | `out_<mesh>.csv` / `rad4space_h1_*.csv` |
| `ResultViewerDialog` | 双击 run log / 其他文件 | 任意文本 |

查看器按任务缓存（`_voxel_viewers[(task, qname)]`、`_traj_viewers[task]`），
任务重跑后 `_refresh_open_voxel_previews()` / `_refresh_open_traj_viewers()` 自动刷新。

## 8. 主题

`_toggle_theme()` 翻转 `_dark_theme` 后：

1. `_apply_global_theme()` 设置 `QPalette` + 全局 QSS + 日志框样式；
2. 逐个把新主题推给运行启动器、任务监视器、求解器设置对话框、各缓存对话框与查看器
   （各自实现 `set_dark_theme(bool)`）。

轨迹颜色在两种主题下保持不变；只有背景、文字、World 线框颜色会切换。

## 9. 交互约定

- 运行中/排队中的任务**不能**打开配置对话框，也不能删除；
- 只有完成任务才重建结果子树（`_on_task_finished` 里判 `completed`）；
- 关闭主窗口时**先关所有次级 QVTK 窗口**再销毁主窗口（`closeEvent`），否则 GL 上下文
  释放顺序错误会刷屏报错；
- 所有配置对话框保存后都会刷新宏预览并更新树上的「已配置」标记。
