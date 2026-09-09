# RadSim 开发文档

> 版本 0.1.0 ｜ 最后更新 2026-09-09
> 面向开发者与二次开发者；使用说明请看仓库根目录的 [README.md](../README.md)。

## 文档索引

| 文档 | 内容 |
|---|---|
| [01 · 架构总览](01-architecture.md) | 分层、模块依赖图、四条数据流、线程模型、单例、扩展点 |
| [02 · GDML 处理链路](02-gdml-pipeline.md) | 解析器、节点树、表达式求值、写回、材料库、碰撞检测 |
| [03 · run.mac 生成](03-mac-builder.md) | 宏的 8 个段落、物理/源复用、三种计分命令、单位换算 |
| [04 · 运行调度](04-execution.md) | RunManager 状态机、QProcess、日志重定向、停止与清理 |
| [05 · 分析与结果](05-analysis.md) | realworld / probe / voxel 配置结构、计分数量清单、结果分组 |
| [06 · 项目保存与加载](06-project-io.md) | 项目文件夹布局、`project.json`、硬保存、草稿目录区别 |
| [07 · 可视化](07-visualization.md) | VTK 场景、实体工厂、WId 重绑、体素/轨迹/曲线查看器 |
| [08 · 界面参考](08-ui-reference.md) | 布局、Ribbon、项目树、对话框与查看器清单 |
| [09 · 数据格式](09-data-formats.md) | 项目 JSON、run.mac、各类结果 CSV、配置结构、QSettings |
| [10 · 环境与排错](10-troubleshooting.md) | 依赖版本、安装、Qt DLL 冲突、常见现象、已知限制 |
| [11 · Linux 移植指南](11-linux-porting.md) | 双平台改造点清单、求解器重建、`LD_LIBRARY_PATH`、VTK/Wayland、字体、验收清单 |

## 按主题查找

| 我想了解… | 看这里 |
|---|---|
| 整体怎么分层、模块之间怎么依赖 | [01](01-architecture.md#2-分层) |
| GDML 怎么被解析成树、哪些实体支持 | [02](02-gdml-pipeline.md#2-gdmiparser) |
| 界面上的配置怎么变成 Geant4 命令 | [03](03-mac-builder.md) |
| 求解器怎么被启动、日志去哪了 | [04](04-execution.md) |
| 三种分析模式分别要配什么、结果怎么读 | [05](05-analysis.md) |
| 项目保存成什么、怎么迁移 | [06](06-project-io.md) |
| 3D 视图、体素、轨迹是怎么画出来的 | [07](07-visualization.md) |
| 某个按钮/对话框在哪、叫什么 | [08](08-ui-reference.md) |
| 某个 CSV 的列是什么意思 | [09](09-data-formats.md) |
| 跑不起来 / 求解器秒退 | [10](10-troubleshooting.md#3-求解器与-qt-dll-冲突最常见问题) |
| 想搬到 Ubuntu / 双平台工作 | [11](11-linux-porting.md) |
| Ubuntu/Wayland 下 3D 视图黑屏怎么办（VTK 与 OCC 都有此坑） | [11 · 第 8 节](11-linux-porting.md#8-专题vtk-窗口嵌入在-ubuntu-下怎么解决) |

## 阅读路径建议

**第一次接手这个项目**：
01 → 02 → 03 → 04 → 05 → 07，然后按需查 08/09。

**只想改界面**：
08 → 01（第 7 节信号总线）→ 05（若涉及分析对话框）。

**只想改物理/宏**：
03 → 05 → 02。

**排查线上问题**：
10 → 04（运行）→ 09（结果文件）。

**要移植到 Linux / 双平台工作**：
11 → 04（求解器启动）→ 07（VTK 窗口）→ 10（环境）。

## 约定速查

| 项 | 约定 |
|---|---|
| 长度单位 | 界面与内部 mm，宏内 cm |
| 角度单位 | deg |
| 密度单位 | g/cm³ |
| 任务主键 | 任务名（必须唯一） |
| 目录名 | `safe_task_name()`：非法字符 → `_` |
| 持久化 | `QSettings("RadSim", "RadSim")` |
| 日志 | 统一 `AsyncLogger.log_system(...)` |
| 线程 | UI/VTK 全在主线程；只有大 GDML 解析与求解器进程例外 |
