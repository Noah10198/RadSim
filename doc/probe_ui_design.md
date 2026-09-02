# Probe 分析界面设计

> 状态：原型已定稿（`doc/ui_mockup_probe.html`，可交互验证）
> 属于：`doc/GUI_Design.md` 第 5 节"probe 分析配置"的落地细化
> 对应 solver：`/score/create/probe <名> <半尺寸> cm`（一个探针 = 一个 scoring mesh）
> 权威参考：`doc/solver_capability/probe/mesh_multi_probe.mac`（多探针输出范例，GUI 生成即此形态）

## 一、界面风格

**模态弹窗 · 左 3D + 右表单**，与 voxel 同构（同一套"内嵌 3D 编辑框架"）：

```
┌─ Probe 分析设置 ───────────────────────────────────────────┐
│ 左：3D 场景（内嵌 VTK）       右：表单                        │
│   · gdml 几何半透明 + 世界边界  · 探针属性：名称/半尺寸/       │
│   · 每个探针一个彩色线框盒       x y z/材料下拉                │
│   · 只读：旋转 + 缩放          · Quantity：名称/类型/单位锁/   │
│   · 探针 chip 条（场景下方）     filter（行内展开）            │
│   · 「+ 添加探针（默认居中）」  · 能谱直方图：关联量/bins/     │
│                                范围/log                      │
├───────────────────────────────────────────────────────────────┤
│ 已配置探针 1/2 · 当前 P1: q1·h1 1     [取消] [确认]            │
└───────────────────────────────────────────────────────────────┘
```

**视觉基调**：与 realworld 完全同一套主题 token（`--bg/--p/--p2/--bd/--ac/--ok/--wr/--red`），
不出现硬编码色值；跟随主界面颜色模式（详见 `doc/realworld_ui_design.md`「一、界面风格·主题联动」）。

## 二、交互模型（核心：3D 只读查看，参数全部表单输入）

> 用户定稿：**3D 场景只提供旋转 + 缩放**，探针的位置/尺寸一律用坐标/数值输入。

1. **一直可视化**：3D 内嵌在弹窗里（不是 preview 后弹窗），探针与几何的位置关系随时可见，告别"盲调坐标"。
2. **3D 只读**：左场景是纯查看视图（旋转视角 + 缩放），**不做拖拽编辑**；任何参数修改都在右侧表单。
3. **表单驱动 + 3D 实时刷新**：右侧改 x/y/z、半尺寸、材料 → 3D 立即重绘该探针（位置/大小/颜色）。
4. **添加即所见**：点「+ 添加探针」→ 场景中心出现默认 5cm 探针并自动选中，在右侧输入坐标定位。
5. **选中即联动**：点击探针 chip（场景下方）→ 3D 高亮该探针 + 右侧表单/quantity/直方图整体切到它。

> 三种分析的 3D 定位原则（与 voxel 划清边界）：
> - realworld：无 3D（逻辑体天然在几何里）
> - probe：**查看型**——3D 只读校验位置/大小，参数靠表单（本文件）
> - voxel：**编辑型**——3D 是配置核心（网格框与几何对齐、nBin 实时看密度），内嵌实时编辑

## 三、设置方式（操作路径）

```
项目树 Runs → Analysis → 双击「Probe 分析」（模态）
   → 「+ 添加探针」→ 场景中心出现 5cm 探针（自动选中）
   → 右侧输入名称/半尺寸/位置 x y z/材料 → 3D 实时确认位置关系
   → 添加 quantity（15 种全开放）+ 可选 filter（行内展开）
   → 添加能谱直方图（关联量/ bins/范围/log）
   → 右下角「确认」保存关闭 → 主界面「▶ 运行」
```

## 四、联动逻辑

全部沿用 realworld 的 9 条（`doc/realworld_ui_design.md` 第三节），此处仅列 probe 特有/差异项：

1. **一个探针一个位置**：多位置 = 添加多个探针，每个独立 `/score/create/probe` 块。
2. **探针可增删**：chip 条 hover ✕ 删除（连同其 quantity/直方图一起删）；☑ = 该探针已配置（有任一 quantity 或直方图），由配置驱动，非手动勾选。
3. **单位锁定 / 类型候选 / 直方图关联量过滤**：与 realworld 完全相同（15 种类型、10 种可挂 fill1D；映射表见 `realworld_ui_design.md`）。
4. **材料联动提示**：材料选 `none` 时右侧提示"材料覆盖已关闭（用几何原材料计算）"。
5. **确认 ≠ 运行**：右下角「确认」只保存，「▶ 运行」在主界面。

## 五、状态模型（原型 JS）

```js
state = {
  active: 0,                    // 当前选中探针索引
  probes: [{
    name:'P1', half:5, loc:{x:0,y:0,z:0}, mat:'G4_WATER',
    qs: [{ name:'q1', type:'volumeFlux', f:null }],
    hs: [{ q:'q1', bins:100, rng:'0.01 – 2000.', log:true }]
  }]                            // 每探针独立，增删/选中联动
};
```

材料候选：`G4_WATER / G4_AIR / G4_Al / G4_Cu / G4_Fe / G4_Pb / none`。

## 六、mac 生成规则（对照 mesh_multi_probe.mac）

每探针一个块 + 全局直方图编号 + 每探针一个 CSV：

```mac
/score/create/probe P1 5. cm
/score/probe/material G4_WATER        # 材料选 none 时不生成此行
/score/probe/locate 0. 0. -20. cm
/score/quantity/volumeFlux volFlux
/score/quantity/energyDeposit eDep MeV
/score/filter/particle protonFilter proton   # filter 紧跟其 target quantity
/score/close

/analysis/h1/create P1_volFlux P1_volFlux 100 0.01 2000. MeV ! log
/score/fill1D 0 P1 volFlux
/analysis/h1/create P1_eDep   P1_eDep   100 0.001 1000. MeV ! log
/score/fill1D 1 P1 eDep
...
/run/beamOn 1000
/score/dumpAllQuantitiesToFile P1 mesh_multi_probe_P1.csv
```

**生成器必须注意（mac_generator 实现要点）**：

1. **fill1D 的 id 是全局连续编号**（跨所有探针、按 `/analysis/h1/create` 顺序 0..N），不是每个探针从 0 开始——生成器维护一个全局计数器。
2. **filter 只绑定"紧邻其前的 quantity"**（G4 顺序绑定规则）：GUI 里每个 quantity 行挂自己的 filter、生成时紧跟 target，天然正确。手写脚本容易犯"一个 filter 想过滤多个量"的错（见 mesh_multi_probe.mac 头注释）。
3. **material 可选**：`none` 不生成 `/score/probe/material` 行（无覆盖，用几何材料）；NIST 材料才生成。
4. **每探针单独 dump**：`dumpAllQuantitiesToFile <探针名> <输出基名>_<探针名>.csv`。
5. 粒子源（/gps）不在 probe 弹窗内，由 beam_dialog 单独配置。

## 七、与其它文档的关系

| 条目 | 位置 |
|---|---|
| 三种分析对比、弹窗归类 | `GUI_Design.md` §3、§5 |
| Filter 通用规则（5 种类型、离子特例） | `GUI_Design.md` §7 |
| 类型/单位映射表、单位锁定 | `realworld_ui_design.md` 第三节 |
| 主题 token 与主界面联动 | `realworld_ui_design.md` 一、界面风格 |
| 多探针 mac 权威范例 | `solver_capability/probe/mesh_multi_probe.mac` |
