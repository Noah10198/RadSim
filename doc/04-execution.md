# 04 · 运行调度与求解器执行

> 源码：`core/run_manager.py`、`core/solver_config.py`、`core/mac_builder.py`
> 界面：`ui/dialogs/run_monitor.py`

## 1. 职责

`RunManager` 是一个 **独立的任务队列**，负责：

- 接收一批任务并排队；
- 按并发上限（默认 `max_concurrent = 2`）逐个拉起；
- 通过 `QProcess` 启动真实求解器（或降级为模拟进度）；
- 把求解器控制台输出重定向到每个任务的 `run.log`；
- 通过 Qt 信号向界面广播状态与进度；
- 支持停止单个 / 全部任务。

它**不关心**任务怎么配置——配置在启动前已经写进 `RunTask`，并由 `mac_builder`
落到 `run.mac`。

## 2. 状态机

```
idle ──start()──> queued ──_pump()──> running ──┬─> completed
  ▲                                            ├─> failed
  └────────────────────────────────────────────┴─> stopped
```

| 状态 | 含义 |
|---|---|
| `idle` | 已创建，未排队 |
| `queued` | 已入队，等待并发名额 |
| `running` | 进程已拉起（或模拟计时器在跑） |
| `completed` | 进程退出码 0 |
| `failed` | 退出码非 0，或启动失败 / 宏写入失败 |
| `stopped` | 用户主动停止 |

## 3. 对外信号

| 信号 | 参数 | 触发时机 |
|---|---|---|
| `task_added` | `RunTask` | `add_task()` |
| `task_started` | `name` | 任务从队列进入运行 |
| `task_progress` | `name, percent` | 心跳计时器 |
| `task_finished` | `name, status` | 结束 / 失败 / 停止 |
| `all_finished` | — | 队列与运行集合都空了 |

`run_monitor.py` 里的监控窗口订阅这些信号，刷新表格与进度条；主窗口用
`task_finished` 决定何时刷新结果树。

## 4. 公开 API

```python
rm = RunManager(parent, max_concurrent=2)

rm.configure_solver(exe, gdml_full_path, out_root)   # 绑定真实求解器
rm.solver_configured() -> bool                        # 是否具备真实运行条件
rm.add_task(task)                                     # 登记任务
rm.start([names]) / rm.start_all()                    # 入队并开始泵送
rm.stop_task(name) / rm.stop_all()                    # 停止
rm.is_running_any() -> bool
rm.get_task(name) / rm.running_names()
rm.clear()                                            # 清空全部状态（换几何 / 载入项目）
```

`configure_solver()` 中，`exe` 为 `None` 或文件不存在时会被归一化为 `None`，
运行随即进入**模拟模式**——这让界面流程在没有求解器的机器上也能跑通。

## 5. 排队与泵送

```python
def _pump(self):
    while len(self._running) < self._max_concurrent and self._queue:
        self._spawn(self._queue.pop(0))
```

- 先进先出；
- 每完成 / 停止一个任务都会再次 `_pump()`，自动补位；
- 已处于 `running` / `queued` 的任务重复 `start()` 会被忽略。

## 6. 真实求解器路径

### 6.1 启动前

1. `write_workdir(gdml_path, task, out_root)` 生成工作目录并写入 `run.mac`；
   写失败直接判 `failed`；
2. 命令行参数只有一个：`[<workdir>/run.mac]`；
3. `QProcess.setWorkingDirectory(workdir)`——求解器的相对输出都落在工作目录里。

### 6.2 环境变量（Windows 上的关键一步）

```python
env = QProcessEnvironment.systemEnvironment()
dll_dirs = runtime_dll_dirs()          # core/solver_config.py
env.insert("PATH", os.pathsep.join(dll_dirs) + os.pathsep + cur)
```

求解器是链接 Qt6 DLL 的 Geant4 程序。如果 GUI 从 conda 环境启动，conda 自带的
旧版 Qt6 DLL 会抢先加载，求解器启动即失败（`0xC0000135` 找不到 DLL /
`0xC0000139` 找不到入口）。把正确的 Qt `bin` 目录**前置**到 `PATH` 即可解决。

`runtime_dll_dirs()` 的顺序：用户在 **Solver Setting** 里配置的 `solver/qt_bin_dir`
优先，其次是 `DEFAULT_QT_BIN_DIRS` 里的开发机路径；非 Windows 返回空列表。

### 6.3 日志重定向

- `setProcessChannelMode(MergedChannels)`：stdout + stderr 合并；
- `run.log` 以二进制打开，`readyReadStandardOutput` → `_read_solver_output()`
  边读边写边 flush；
- 进程结束时 `_close_log()` 再读一次残余数据并关闭文件；
- 路径写进 `task.run_log`（**不持久化**到 `project.json`），供结果树里的
  “run log” 节点打开。

### 6.4 进度

真实进程的进度是**不确定的**（Geant4 不输出百分比）：心跳计时器每 300 ms 让
进度 `+2`，封顶 99，进程退出后才置 100。所以进度条只表示“还活着”，不表示真实完成度。

### 6.5 结束

```python
def _on_proc_finished(self, name, code):
    status = "completed" if code == 0 else "failed"
```

`_finish()` 会：停掉心跳计时器 → 确保进程已退出（未退出则 `kill`）→ 关闭日志 →
从运行集合移除 → 写入 `task.run_time` → 发 `task_finished` → `_pump()` 补位 →
必要时发 `all_finished`。

`run_time` 用 `time.monotonic()` 计时，格式化为 `HH:MM:SS`。

## 7. 模拟模式（无求解器时的降级）

`solver_configured()` 为假时，用 `QTimer`（200 ms 一跳、每跳 +10%）模拟进度，
到 100% 判 `completed`。用于界面开发与流程自测，**不产生任何结果文件**。

## 8. 停止与清理

| 操作 | 行为 |
|---|---|
| `stop_task(name)` | 运行中：`terminate()`，2 秒内未退出则 `kill()`；排队中：直接出队并置 `stopped` |
| `stop_all()` | 对运行中与排队中的任务逐个执行上述逻辑 |
| `clear()` | 先 `stop_all()`，再停计时器、`kill` 残留进程、关闭全部日志句柄、清空任务表 / 队列 / 运行集合 |

`clear()` 在主窗口“导入新几何”“载入项目”等场景被调用，确保上一个项目的进程和
句柄不会泄漏到下一个项目。

## 9. 目录约定

```
solver/runs/                 # get_results_root()，可被 QSettings 覆盖
└── <safe_task_name>/        # safe_task_name = 非法字符替换为 _
    ├── run.mac
    ├── run.log
    ├── out_<mesh>.csv       # realworld / probe
    ├── out_Box_<q>.csv      # voxel
    └── rad4space_h1_*.csv   # 一维直方图
```

草稿输出留在 `solver/runs`；保存项目时由 `project_io.save_project()` 镜像到
`<项目>/results/<task>/`（见 [06-project-io.md](06-project-io.md)）。

## 10. 排错清单

| 现象 | 排查方向 |
|---|---|
| 任务瞬间 `failed` | 求解器路径是否配置正确；`run.log` 里是否有 `0xC0000135/0xC0000139` |
| `run.log` 为空 | 进程未成功启动（`waitForStarted` 3 秒超时） |
| 进度条停在 99% | 进程仍在运行，属正常表现 |
| 结果文件缺失 | 宏里 dump 命令是否在 beamOn 之后；任务是否真的 `completed` |
| 重跑后结果混乱 | `write_workdir` 会清空任务目录，若手动放了文件会被删除 |
