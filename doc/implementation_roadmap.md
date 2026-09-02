# 3dRad GUI 实施路线与难度评估

> 依据：对 1dRad / gdmleditor / cad2gdml 代码库的实盘勘查 + 3dRad 既有设计
> （`GUI_Design.md`、`result_coupling_design.md`、`realworld/probe/voxel` 弹窗设计、`solver_capability/README.md`）。
> 状态：评估阶段。目标：确认哪些抄、哪些拼、哪些必须新写、按什么顺序交付。

## 0. 总体结论

**有信心完成。** 核心难点与你判断的基本一致（脚本生成、分析脚本设置、多任务、结果处理），
但有一个**认知修正**：1dRad 的"多任务运行"目前是 `QTimer` 模拟进度（`main_window._on_run_selected`），
**从未真正调用过 solver**。所以多任务这块只能借鉴其 run_monitor UI，管线必须新写。

## 1. 资产盘点（可复用清单）

### 1.1 直接从 gdmleditor 照抄（成熟、零风险）

| 模块 | 文件 | 用途 |
|---|---|---|
| GDML 解析 | `core/gdml_parser.py` `gdml_tree.py` `gdml_evaluator.py` | 五段解析、单位换算、表达式求值、逻辑体/物理体/多实例克隆 |
| 材料库 | `core/materials_lib.py` | NIST + 自定义材料 |
| VTK 渲染 | `vtk_engine/vtk_solid_factory.py` `vtk_scene.py` | solid→actor（9 种类型）、placement 链、世界框、拾取 |
| VTK 控件 | `ui/vtk_widget.py` | QVTK 封装、网格/坐标轴、暗色主题 |
| 界面骨架 | `app/main_window.py` `ui/ribbon_toolbar.py` `ui/project_tree.py` | Ribbon + dock + 状态栏 + 亮暗切换 |
| AABB 原语 | `core/collision_detector.py` | `compute_half_size`（按 solid 类型）、`compute_world_aabb`（**含旋转**） |

### 1.2 从 1dRad 复用（成熟、零风险）

| 模块 | 文件 | 用途 |
|---|---|---|
| 数据模型 | `core/project_model.py` | `TaskData / ParticleSetup / PhysicsSetup / AnalysisItem` dataclass 契约 |
| 粒子源 UI | `ui/dialogs/particle_setup_dialog.py` | 单能/高斯、方向/位置（**spectrum 是 TODO**） |
| 日志 | `utils/logger.py` | `AsyncLogger` 后台队列 |
| 运行监控 UI | `ui/dialogs/run_monitor.py` | 每任务进度条/状态/勾选（**仅 UI，逻辑要重写**） |
| 主窗口编排 | `app/main_window.py` | 信号接线、懒加载弹窗、主题切换的模式 |

## 2. 难点分级

### 🟢 A 级 · 拼装即得（小改）

| 项 | 现有资产 | 需做的事 | 风险 |
|---|---|---|---|
| 几何包围盒（all_geo / volume） | collision_detector 的 `compute_world_aabb` + half_size | 写聚合函数：遍历可渲染实例 → world_aabb → 并集（不含 world） | 低（§3.3 已定算法） |
| 主题 token 收拢 | gdmleditor 的分散 QSS | 按 `realworld_ui_design.md` 集中成 token 字典 | 低 |
| 物理过程 UI | rad4space 5 条命令已文档化 | 下拉+checkbox+数值（SetPL/AddHP/AddRDM/SetGlobalCut/SetMaxStep） | 低 |
| run_meta 读写 | — | 按 `result_coupling_design.md §4` schema | 低 |

### 🟡 B 级 · 新写但规则已固化（机械翻译）

| 项 | 依据 | 工作量 |
|---|---|---|
| 三个分析弹窗（realworld/probe/voxel） | 设计文档 + mockup 已定稿 | 中 |
| `mac_generator.py` | `solver_capability/README.md` 阶段顺序 + filter 顺序绑定 + 各模板 | 中（关键是阶段顺序正确） |
| `voxel_data.py`（CSV→vtkImageData） | `result_coupling_design §3.1` 公式 | 低 |
| `csv_parser.py`（按 header 分类） | 实测 header（`# iX,iY,iZ,...`）| 低 |
| probe 结果展示（点+线框+标签） | 设计已定 | 低 |

### 🔴 C 级 · 真难点（需要实测/设计验证）

| 项 | 难度来源 | 应对 |
|---|---|---|
| **运行管线（QProcess 调 solver）** | 1dRad 未通，需新写：子进程启动、mac 传递、日志解析进度、错误/超时/崩溃处理 | 单任务先通，再队列化 |
| **多任务并发** | rad4space 自身支持多线程，多实例并发 = 多个 QProcess；停止要杀进程树 | 参考 run_monitor UI，逻辑重写 |
| **粒子源自定义谱** | 1dRad spectrum=TODO；solver 支持 Lin/User hist | 谱编辑器（线性参数 or 表格点） |
| **realworld 结果↔几何对齐** | CSV 按 copy number 索引，GDML 多实例的 copy index 语义要实测对齐 | 用 axes.gdml 小场景实测映射规则 |
| **结果-配置耦合校验** | 依赖 solver 实际 CSV 行为（多探针行序待实测） | 接入前跑一次真实运行确认（见 §9 待验证项） |

## 3. 风险清单（按破坏性排序）

1. **copy number 语义**：realworld 输出按物理体 copy number，解析器克隆机制下的编号顺序必须与 CSV 行序一致——不对则整个 realworld 结果错位。**先小场景实测。**
2. **solver 交互契约**：进度输出格式、错误输出、退出码，决定了 run_monitor 怎么接。**读 solver 源码确认输出点。**
3. **多探针 CSV 行序**：probe 结果依赖 locate 顺序，需一次真实运行验证。
4. **自定义谱的 `/gps/hist`**：Lin 需显式 gradient/intercept（README §7 已记录 NaN 坑），User hist 点表要 GUI 校验合法性。

## 4. 建议实施顺序（每步可运行验证）

```
① 搭壳        主窗口 + Ribbon + 项目树 + 主题 token + GDML 导入渲染   （照抄 gdmleditor）
② 包围盒      AABB 聚合函数 → voxel 弹窗 3D 场景先能显示网格框         （小改）
③ 弹窗+脚本   realworld → probe → voxel 弹窗 + mac_generator           （B 级）
④ 单任务管线  run_meta + QProcess 单任务跑通 + run_monitor 接真实进度  （C 级，最重要）
⑤ 结果耦合    csv_parser + voxel_data + 结果窗口（voxel 切片先出）     （B 级）
⑥ 多任务      run_monitor 扩展为队列 + 并发 + 停止/清理                 （C 级）
⑦ 补全        realworld/probe 结果展示 + 物理过程 UI + 自定义谱 + 过期检测
⑧ 抛光        全量主题核对、help、空态、性能（>128³ 降采样）
```

> 里程碑：④ 完成 = "能真正跑出结果"，⑤ 完成 = "能看三维结果"，⑦ 完成 = 全功能可用。

## 5. 与 1dRad 的边界

- 1dRad 的 solver（C++）与 rad4space 完全不同（平面分层 vs 3D 世界），**solver 层零复用**；
- GUI 层复用其数据模型/UI 框架/粒子源/监控 UI，但**"配置→脚本→运行→解析"整条链路在 1dRad 是空的**，正是 3dRad 的工作量主体。
