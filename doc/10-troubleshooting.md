# 10 · 环境与排错

> 版本 0.1.0 ｜ 最后更新 2026-09-09

## 1. 运行环境

| 项 | 版本 |
|---|---|
| Python | 3.10（开发验证 3.10.19） |
| 操作系统 | Windows x64 |
| PyQt6 | 6.4.2 |
| VTK | 9.3.1（导入名为 `vtkmodules`） |
| numpy | 2.2.6 |
| matplotlib | 3.10.7（可选，仅曲线图使用） |
| 求解器 | rad4space，基于 Geant4 11.4.2 |

## 2. 安装

```bash
# 推荐：完整环境快照
conda env create -f environment.yml
conda activate pyoccenv
python main.py

# 或 pip
pip install -r requirements.txt
python main.py
```

求解器：仓库已含 `solver/rad4space/build/Release/rad4space.exe`；
自行编译见 `solver/rad4space/README.zh.md`。

## 3. 求解器与 Qt DLL 冲突（最常见问题）

**现象**：任务秒退，`run.log` 为空或只有一行，退出码 `0xC0000135`（找不到 DLL）
或 `0xC0000139`（找不到入口点）。

**原因**：rad4space 链接 Qt6。若 GUI 从 conda 环境启动，conda 自带的旧版 Qt6 DLL
会因 `PATH` 顺序抢先加载。

**处理**：

1. 打开 **⚙️ Solver Setting**；
2. 把求解器所用的 Qt6 `bin` 目录填进 `solver/qt_bin_dir`；
3. 重新运行。

RadSim 会在启动求解器前把该目录**前置**到子进程 `PATH`（`core/solver_config.runtime_dll_dirs`），
不影响 GUI 自身的 Qt。

## 4. 常见现象对照表

| 现象 | 原因 / 处理 |
|---|---|
| 3D 视图全白/全黑 | 导入的是不支持渲染的实体；或 GL 上下文失效（切换主题/多屏后）。点 **⌂ Fit** 或重启 |
| 日志刷 `wglMakeCurrent failed` | 次级 VTK 窗口与主窗口的 GL 上下文释放顺序问题。正常关闭主窗口会先关次级窗口；若仍出现，检查是否有窗口被强杀 |
| 求解器路径显示未配置 | `solver/executable` 为空且自动探测失败，手动指定即可；未配置时程序以**模拟进度**运行 |
| 进度条停在 99% | 真实进程仍在跑（进度是不确定型），属正常 |
| 任务 `failed` | 先看 `run.log`；再看宏预览是否合理 |
| 结果树没有新节点 | 只有 `completed` 的任务才重建结果子树；`failed` 只会挂 `run log` |
| 结果文件存在但界面读不到 | 草稿目录与项目目录不是同一个；见 [06 文档第 5 节](06-project-io.md#5-草稿目录-vs-项目目录) |
| 导入 GDML 卡住 | ≥500 KB 走后台线程并弹模态进度框；超大文件建议先精简几何 |
| 几何尺寸明显不对 | GDML 表达式里引用了未定义标识符——求值器会静默替换为 `0`（见 [02 文档](02-gdml-pipeline.md)） |
| 部分实体不显示 | `trap` / `trd` / `para` / `polyhedra` / `xtru` / 布尔运算等不支持渲染，导入时会弹提示 |
| 探针曲线图报「matplotlib is not installed」 | 安装 matplotlib 后重开对话框 |
| 直方图 x 轴不对齐 | 同一数量类型的 bins/range 不一致，对话框会提前警告 |
| 保存很慢 | 保存是硬保存（全量镜像 `results/`） |
| 想换项目文件夹 | 首次保存即固定，需重启后重新保存 |

## 5. 日志与诊断

- 界面日志面板：`AsyncLogger` 写入，包含导入、配置、运行、异常；
- 任务日志：`solver/runs/<task>/run.log`（或项目 `results/<task>/run.log`）；
- 宏文件：同目录 `run.mac`，可直接在命令行手动执行以复现：

```
<qt_bin>; solver\rad4space\build\Release\rad4space.exe solver\runs\Run_001\run.mac
```

## 6. 已知限制（汇总）

| 限制 | 说明 |
|---|---|
| 单几何 | 一个项目只支持一个 GDML |
| 材料解析简化 | `<materials>` 只记录名称与密度 |
| 未定义标识符 | 求值结果静默为 `0` |
| 空心球 / cone | 空心球简化为外壳；cone 用 16 段近似，内半径不参与 |
| 不渲染实体 | `trap`、`trd`、`para`、`hype`、`polyhedra`、`xtru`、`arb8`、`cutTube`、布尔运算等 |
| 框选 / 右键菜单 | 3D 视图未实现框选与右键上下文菜单 |
| 轨迹动画 | 轨迹查看器无播放/时间轴，只有筛选 |
| 多线程轨迹 | `Traj.csv` 只含被选中 worker 的事件，需要完整轨迹时用 `/run/numberOfThreads 1` |
| 进度语义 | 真实运行进度为不确定型，仅表示「进程还活着」 |
| 单位 | GUI 与内部为 mm，宏内按求解器要求换算 cm |

## 7. 性能提示

- 球/柱/环的圆周分辨率固定 48，`cone` 固定 16 段——实体数量多时三角面会迅速膨胀；
- 体素查看器内存约 `(nbin+1)³ × 8` 字节，`nbin` 三轴各 200 即约 65 MB；
- 场景已关闭 MSAA 与 vsync，并缓存共享几何；如仍卡顿，优先减少可见实体。

## 8. 相关文档

- [架构总览](01-architecture.md)
- [GDML 处理链路](02-gdml-pipeline.md)
- [run.mac 生成](03-mac-builder.md)
- [运行调度](04-execution.md)
- [分析与结果](05-analysis.md)
- [项目保存与加载](06-project-io.md)
- [可视化](07-visualization.md)
- [界面参考](08-ui-reference.md)
- [数据格式](09-data-formats.md)
