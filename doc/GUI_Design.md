# 3dRad GUI 设计文档

> 状态：设计阶段（未写代码）
> 目标：为 rad4space solver 提供可视化 GUI，实现 GDML 几何渲染 + 三种分析（realworld / probe / voxel）配置与结果展示，风格与 1dRad 保持一致。
> 界面原型：`doc/ui_mockup.html`（静态视觉稿，含主窗口 / voxel 配置弹框 / 结果窗口）

## 1. 目录结构

```
3dRad/
├── main.py
├── app/
│   └── main_window.py          # 主窗口框架（多任务 + 项目树 + VTK）
├── ui/
│   ├── ribbon_toolbar.py       # 顶部工具栏
│   ├── project_tree.py         # 项目树（GDML / Runs / 结果）
│   ├── vtk_widget.py           # 主窗口：GDML 几何渲染
│   ├── voxel_view.py           # 结果窗口：体素 + 切片
│   ├── filter_panel.py         # 共享 Filter 配置组件
│   └── dialogs/
│       ├── gdml_import_dialog.py   # 导入 GDML（含 Decimate 勾选）
│       ├── realworld_dialog.py     # realworld 分析配置（纯表单）
│       ├── probe_dialog.py         # probe 分析配置（轻量 3D）
│       ├── voxel_dialog.py         # voxel 分析配置（轻量 3D）
│       ├── beam_dialog.py          # 粒子源配置
│       └── run_monitor.py          # 运行进度
├── core/
│   ├── gdml_renderer.py        # 复用 gdmleditor 的 parser + solid_factory → actor
│   ├── voxel_data.py           # mesh CSV → vtkImageData（后台线程）
│   ├── mac_generator.py        # 配置 → solver 输入 .mac
│   ├── result_meta.py          # run_meta.json 读写
│   └── csv_parser.py           # 按 header 自动识别 CSV 类型
└── runs/                       # 每次运行自动生成 Run_XXX/ 目录（归档）
└── solver/
    └── rad4space/              # 原样保留，不改动
```

## 2. 主窗口布局

- 顶部 **Ribbon 工具栏**：文件（导入 GDML / 保存 / 加载）、任务、运行 / 停止、主题、帮助
- 左侧 **项目树**（dock）：GDML / Runs / 结果三级结构
- 中央 **VTK 视图**：纯显示 GDML 几何（增量导入），左键旋转 / 滚轮缩放 / 右键平移
- 底部 **状态栏** + 可选日志面板
- 任务组织参考 1dRad 多任务形式：`task → particle setup / physics / analysis`

```
Project
├── GDML 1 (axes.gdml)
├── GDML 2 (detector.gdml)          # 增量导入，面片多时提示压缩显示
├── Runs
│   └── Run 001                     # = runs/Run_001/ 目录映射
│       ├── 能谱 volFlux            # 双击 → 曲线窗口
│       ├── 体素结果 eDep           # 双击 → 结果窗口
│       └── TID 汇总                # 双击 → 表格
```

### 2.1 GDML 导入

- 增量导入，每个 GDML 一个项目树节点
- 导入对话框勾选 **压缩面片（仅显示）**：对 tessellated 面片用 `vtkDecimatePro`，只影响渲染 actor
- 面片数 > 50 万时自动弹提示，小文件静默跳过
- 项目树选中几何节点 → 3D 视图画该几何包围框（仅导航辅助）

## 3. 任务与分析体系

每个 task 展开：particle setup（粒子源）→ physics process（物理列表/截断）→ analysis。

**analysis 分三种类型**，参数与展示策略均不同：

| 类型 | solver 命令 | GUI 展示 | 需要设置的参数 |
|---|---|---|---|
| realworld | `/score/create/realWorldLogVol <LV>` | **纯表单弹框**（无需 3D） | 勾选逻辑体 + quantity + 能谱 + filter |
| probe | `/score/create/probe <name> <halfSize>` + `/score/probe/locate` | **轻量 3D 弹框** | 尺寸 + 位置 + quantity + 能谱 + filter（可多探针） |
| voxel | `/score/create/boxMesh` + `/score/mesh/boxSize nBin` | **轻量 3D 弹框** | 类型 + 范围 + nBin + quantity + filter（**无**能谱） |

> 注：probe 不是"自定义材料"——它是自定义位置/尺寸的立方体探针，材料由探针所处位置的几何决定。
> voxel 无能谱：boxMesh/cylinderMesh 不支持 `/score/fill1D`（仅 dumpQuantityToFile）。

## 4. realworld 分析配置（纯表单弹框）

```
逻辑体列表（来自 GDML 解析，含体积/材料）→ 打勾选择
quantity 勾选（energyDeposit / doseDeposit / volumeFlux ...）
能谱设置（bin 数 / 范围 / log 轴，可选）
FilterPanel（可选）
→ 生成 mac
```

realworld 用现有逻辑体打格，几何上无新内容可预览，因此不需要 3D。

## 5. probe 分析配置（轻量 3D 弹框）

```
左侧 3D 预览（简化渲染已导入 GDML）   右侧 表单
  · 探针线框立方体（可拖/可输入定位）     · 尺寸 halfSize
  · 支持添加多个探针                     · 位置 x y z
                                       · quantity 勾选
                                       · 能谱设置
                                       · FilterPanel
→ 生成 mac（多探针 → 多条 /score/create/probe）
```

## 6. voxel 分析配置（轻量 3D 弹框）

**起步聚焦 Box（直角坐标）**，Cylinder 后续扩展。

```
左侧 3D 预览                           右侧 表单
  · 几何线框 + 网格框 + 细分线抽稀        · 类型: Box（Cylinder 禁用/占位）
  · 密度指示器（cell 总数/单 cell/密度）  · 范围:
  · 选中几何高亮                          · ( ) 包围全部几何体（不含世界容器）
                                        · (●) 包围选中几何体
                                        · ( ) 手动指定（半尺寸 + 平移）
                                        · nBin [x][y][z]
                                        · quantity 勾选（无能谱）
                                        · FilterPanel
→ 生成 mac（自动转成 boxSize + nBin + translate）
```

- "包围全部几何体"：除 world 容器外所有体积的联合 AABB → 自动算出 boxSize + translate（算法见 `result_coupling_design.md §3.3`）
- "包围选中几何体"：场景选中几何 → 该逻辑体（多实例取联合）AABB → 自动算出 boxSize + translate
- "手动指定"：直接填半尺寸 + 平移（即 boxSize + translate 语义，透明直观）

### 6.1 细分线抽稀（防止"黑乎乎"）

"黑 blob" 成因：线数量爆炸 + 深度遮挡 + 颜色过深。对策三层：

**① 视觉层**：外框（boxSize）深色粗线常显；细分线浅灰细线 + 40% 透明度，默认隐藏。

**② 交互层（核心）按密度自适应抽稀**：

| 网格规模 | 细分线画法 |
|---|---|
| ≤ 10³ | 全画（约 6k 条线，清晰） |
| ≤ 25³ | 隔 2~3 条画 1 条 |
| > 25³ | 只画外框 + 三个面上疏网格（每 5~10 条画 1），标注"示意线" |

预览只表达"覆盖范围 + 大致密度"，不要求精确到 cell；精确体素场在结果窗口以切片/体绘制展示。

**③ 辅助信息**：实时显示 cell 总数、单 cell 体积、密度分级（疏/中/密/过密，>50³ 标红提示 Geant4 内存压力）。

## 7. Filter 配置（共享 FilterPanel 组件）

Geant4 filter 命令（realworld/probe/voxel 通用）：

```
/score/filter/particle name gamma
/score/filter/kineticEnergy name 0.1 10 MeV
/score/filter/particleWithEnergy name proton 1. 100. MeV
/score/filter/charged name
/score/filter/neutral name
```

> 注意：G4 的 filter 实现类只有这 5 种（`source/digits_hits/scorer/src/` 确认），
> 网上流传的 `charge` / `particleWithCharge` / `region` filter 不存在。

**UI 设计**：
- **filter 挂在 quantity 上**，但**一个 quantity 只能挂一个 filter**（G4 顺序绑定规则，见 `solver_capability/README.md §5`）
- 生成 mac 时 filter 行**必须紧跟其 target quantity 之后**，不能跨 quantity 指定
- FilterPanel 为共享组件，三种分析弹框复用；每个 quantity 行可展开
- 添加 filter 类型：粒子种类 / 动能范围 / 粒子+动能 / 带电 / 中性
- **离子是特例**：`particle` 下拉**首版只列标准粒子**（gamma / e- / e+ / proton / neutron）+ 轻离子（alpha / He3 / deuteron / triton）；
  **重离子核素选择器列入后续扩展**（需 `/gps/particle ion` + `/gps/ion Z A` 预创建核素，见 `solver_capability/README.md §5` 离子坑）
- **多粒子统计**：用户多选粒子时自动拆成多个 quantity（`eDep_gamma`、`eDep_e`），mac 生成器自动处理，用户无感
- 默认折叠、无 filter，普通用户无认知负担

## 8. 体素结果的定位（关键技术点）

**CSV 只含体素索引，不含坐标**。`/score/dumpQuantityToFile` 输出：

```
# iX, iY, iZ, total(value) [MeV], total(val^2), entry
0,0,0,0,0,0
```

体素场位置由 **mesh 配置**数学决定（boxMesh 中心默认在原点）：

- cell(i,j,k) 中心 = `( -halfX + (i+0.5)*dx, ... )`，`dx = 2*halfX/nBinX`
- 重建 vtkImageData：`origin=(-halfX,-halfY,-halfZ)`，`spacing=(dx,dy,dz)`，`dimensions=nBin`

运行前必须把 mesh 配置存为结果元数据，与 Run 绑定；结果窗口据此重建体素场，自动贴合几何。

### 8.1 结果元数据（`run_meta.json`）

```json
{
  "run_id": "Run 001",
  "gdmls": ["axes.gdml", "detector.gdml"],
  "beam": { "particle": "proton", "energy_mev": 100, "n_events": 1000 },
  "mesh": { "type": "boxMesh", "half_size_cm": [15,15,15], "n_bin": [10,10,10], "center_cm": [0,0,0] },
  "outputs": { "voxel_csv": "...", "spectra_csv": "...", "tid_csv": "..." }
}
```

## 9. 结果窗口（独立非模态对话框）

```
┌────────────────────────────────────────────────┐
│ 3D 视图                │ XY 切片 (z=5)         │
│ · 几何线框(半透明)      │  [热力图] ←滑条       │
│ · 3 个切面(可拖)       │ YZ 切片 (x=8)         │
│ · (可选)体绘制/等值面   │  [热力图] ←滑条       │
│                       │ XZ 切片 (y=11)        │
│ · 色条 + 范围控制      │  [热力图] ←滑条       │
└────────────────────────────────────────────────┘
```

- 2D 切片：`vtkImageResliceMapper`，GPU 纹理贴图，成本极低
- 3D 切面：`vtkImagePlaneWidget`，与 2D 切片联动
- 颜色：`vtkColorTransferFunction`（蓝→绿→黄→红）+ 色条；默认显示中心切面定位热点
- 可选增强（默认关）：GPU 体绘制（低值透明，防黑 blob）/ `vtkMarchingCubes` 等值面

## 10. 结果文件管理

**"一次运行 = 一个目录 = 一个 Run 节点"**：

```
3dRad/runs/Run_003/
├── run_meta.json      # 配置快照（可追溯）
├── input.mac          # 本次执行的 mac 副本
├── solver.log
├── mesh_box_eDep.csv  # 体素场
├── rad4space_h1_volFlux.csv  # 能谱
├── Probes.csv         # probe/realworld 汇总
└── tid.csv
```

- **CSV 自动分类**（按固定 header）：体素场 → 结果窗口；能谱 → 曲线；单行汇总 → 表格
- 运行完成自动刷新项目树 Run 节点下的结果项
- **多 Run 对比**：多选 Run → 能谱曲线叠加 / 表格并列
- **导出**：从查看器导出 PNG / CSV
- 与 1dRad 的 `_on_analysis_view_result` 模式保持一致

## 11. 性能策略

1. 显示分辨率受 Geant4 限制（实际 10³~50³），vtkImageData 无压力
2. 切片渲染 = GPU 纹理，成本不随网格加密翻倍
3. CSV 解析 + vtkImageData 构建放 `QThread`，主窗口不卡
4. 超大网格（>128³）显示层 `vtkImageShrink3D` 降采样，数据层保留原值

## 12. 技术依赖

- Python + PySide6 + vtk（`vtkmodules`）
- VTK 模块：`vtkRenderingVolumeOpenGL2`（GPU 体绘制）、`vtkImagingCore`（reslice/shrink）、`vtkFiltersCore`（MarchingCubes/DecimatePro）、`vtkRenderingImage`
- 曲线图：pyqtgraph 或 matplotlib
- 复用 gdmleditor 的 GDML parser 与 `vtk_solid_factory`（待确认其是否可被直接 import）
