# 06 · 项目保存与加载

> 源码：`core/project_io.py`、`app/main_window.py`（`_save_project` / `_load_project`）

## 1. 一个项目 = 一个文件夹

RadSim 没有数据库，也没有单独的配置文件概念。**项目就是一个可整体拷贝的文件夹**：

```
MyProject/
├── project.json           配置清单（几何引用 + 任务列表）
├── geometry/
│   └── <导入的>.gdml       几何文件副本
└── results/
    └── <safe_task_name>/   每个任务运行输出的快照
        ├── run.mac
        ├── run.log
        ├── out_*.csv
        └── rad4space_h1_*.csv
```

只要把这个文件夹拷到另一台机器，再装好 RadSim 与求解器，就能原样复现。

## 2. project.json 结构

| 字段 | 说明 |
|---|---|
| `format` | `"radsim-project"`；兼容旧值 `"3drad-project"` |
| `version` | 当前 `1` |
| `gdml_paths` | 几何文件路径列表。复制到 `geometry/` 后**存相对路径**，保证可迁移 |
| `results_root` | 保存时的草稿结果根目录（用于回放定位） |
| `tasks` | 任务数组 |

每个任务对象包含：

| 字段 | 说明 |
|---|---|
| `name` | 任务名（唯一，同时是 `RunManager` 的键） |
| `analysis_type` | `default` 等 |
| `gdml_files` | 该任务引用的几何 |
| `calculate` | `{n_threads, n_events}` |
| `particle` | 粒子源配置（见 05 文档） |
| `physics` | 物理配置（见 05 文档） |
| `analysis_config` | 三种分析模式的配置（见 05 文档） |

> 运行态字段（`status`、`progress`、`run_time`、`run_log`）**不写入** `project.json`；
> 它们由加载时扫描磁盘上的结果文件重建。

## 3. 保存流程

入口只有一个：`MainWindow._save_project()`。

1. **确定项目目录**
   - `self._project_dir is None` → `QFileDialog.getExistingDirectory` 让用户选；
   - 若所选目录里已存在 `project_file(folder)`，询问是否覆盖；
   - 一旦确定，**后续保存不再询问**（想换目录需重启，或删掉当前项目重新保存）。
2. **收集数据**：遍历 `RunManager._tasks`，把每个 `RunTask` 序列化成上表的字段，
   连同 `gdml_paths` 与 `get_results_root()` 一起交给 `core.project_io.save_project()`。
3. **落盘**（`save_project()` 内）：
   - 写 `project.json`；
   - 把几何文件**复制**到 `<项目>/geometry/`，并把 `gdml_paths` 改写为相对路径；
   - 把草稿结果目录 `solver/runs/<task>/` **镜像**到 `<项目>/results/<task>/`。
4. **异常**：任何失败都 `try/except` → `QMessageBox.warning` + 日志，不中断程序。

### 为什么是「硬保存」

保存是**全量镜像**，不是增量补丁：

- `geometry/` 与 `results/` 按当前状态重写，删除的任务会连同其已保存结果一起消失；
- 好处是项目文件夹永远自洽，不会残留「幽灵结果」；
- 代价是保存耗时与结果体积成正比——大型结果集保存会比较慢。

## 4. 加载流程

入口：`MainWindow._load_project()`。顺序如下：

1. **前置检查**：若 `RunManager.is_running_any()` 或有任务在跑，直接拒绝并提示。
2. **选文件**：`QFileDialog.getOpenFileName` 选 `project.json`。
3. **清理草稿输出**（关键）：草稿结果根 `solver/runs` 是**所有项目共享**的。
   加载前对当前每个任务名调用 `clear_task_output(results_root, name)`，
   否则旧项目里同名任务的残留 CSV 会被新项目当成自己的结果。
4. **清空运行时**：`_close_task_dialogs()` → `_run_manager.clear()` →
   `_project_tree.clear_tasks()` → `_task_counter = 0`。
5. **恢复几何**：对 `gdml_paths[0]` 调用 `_replace_gdml()`（内部走与导入相同的
   解析 + 建树 + 建场景路径）。
6. **重建任务**：逐个 `RunTask` 回填字段，重新挂到项目树上，并设置各配置项的
   「已配置」标记。
7. **恢复结果**：`_restore_task_outputs(task)` 扫描该任务的结果目录——
   - 存在 `out_*.csv`，或 `run.log` 末尾不含 `error` / `fatal` / `abnormal` / `failed`，
     则判定为已完成，状态置 `completed`；
   - 随后 `_refresh_task_results()` 按磁盘文件与 `analysis_config` 重建 Results 子树。
8. **收尾**：`_ensure_default_task()`（没有任务时补一个）→ `_sync_mac_preview_tasks()`。

## 5. 草稿目录 vs 项目目录

这是最容易混淆的一点：

| 目录 | 角色 | 谁写 | 何时清 |
|---|---|---|---|
| `solver/runs/<task>/` | **草稿输出**，所有项目共享 | `RunManager` / `mac_builder.write_workdir` | 每次运行前清空；加载项目时按任务名清理；删除任务时清理 |
| `<项目>/results/<task>/` | **项目快照**，随项目走 | `project_io.save_project` | 保存时按当前任务列表重写 |

结果查看器读取时，`MainWindow._result_work_dir(task)` 的优先级是：

```
task.run_log 所在目录  →  get_results_root()/<task>  →  <项目>/results/<task>
```

所以「刚跑完但还没保存」看的是草稿目录，「保存后重新打开项目」看的是项目目录。

## 6. 任务名即主键

`RunManager._tasks` 是 `name → RunTask` 的字典，项目树节点也用任务名索引，
结果目录名还是任务名的净化版本。因此：

- **任务名必须唯一**：重名会互相覆盖结果；
- 重命名任务（`_rename_task`）要同时改字典键、树节点、宏预览与监视器；
- 目录名走 `safe_task_name()`，非法字符替换为 `_`——重命名成不同但净化后相同的名字
  （如 `a/b` 与 `a_b`）会共用同一个目录，属于已知边界情况。

## 7. 排错

| 现象 | 原因 |
|---|---|
| 打开项目后结果树里出现别的项目的文件 | 草稿目录未清理（正常流程会清，手工拷贝结果目录时可能触发） |
| 保存很慢 | 硬保存全量镜像结果目录 |
| 换了电脑打不开 | `geometry/` 缺失，或 `project.json` 里的相对路径被手工改过 |
| 保存后旧任务结果还在 | 任务被删除了但项目目录里残留 —— 硬保存会重写 `results/`，若仍存在请检查是否保存成功 |
| 想换项目文件夹 | 当前设计为「一次保存即固定」，需重启或删除 `project.json` 后重新保存 |
