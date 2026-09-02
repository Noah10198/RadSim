# 结果-配置耦合设计（三维结果图 + GDML 几何对齐）

> 主题：solver 输出的 CSV 不含空间坐标，后处理三维展示时如何"记住"网格/探针参数，
> 把数值结果确定性映射回几何坐标，与 GDML 叠加渲染。
> 前置：`solver_capability/README.md`（/score 命令与能力差异）、`GUI_Design.md §8/§9/§10`（结果定位/窗口/文件管理）。
> 本文档是 §8 的系统化扩展：补全 probe、voxel translate、校验与过期规则。

## 1. 问题（实测确认）

solver 输出的 CSV 是"索引 + 数值"，**不含绝对坐标**。实测输出（`rad4space/build/Release/`）：

probe（`t_probe_edep.csv`，单探针）：
```
# mesh name: Probes
# primitive scorer name: eDep
# i, i, i, total(value) [MeV], total(val^2), entry
0,0,0,9065.390040918774,866101.6876571288,100
```

voxel（`mesh_box_eDep.csv`，boxMesh）：
```
# mesh name: Box
# primitive scorer name: eDep
# iX, iY, iZ, total(value) [MeV], total(val^2), entry
0,0,0,0,0,0
0,0,1,0,0,0
0,0,2,0,0,0
...
```

> 结论：坐标**不是**从 CSV 读出来的，而是从**定义参数**数学重建出来的。
> 所以参数必须随结果一起持久化 —— 这就是后处理要"记住"的东西。

## 2. 核心原则

1. **参数即坐标**：CSV 索引 → 参数 → 绝对坐标是**确定性映射**，无歧义。
2. **一次运行 = 一套配置 = 一组输出**（强绑定）：run 目录里的 `run_meta.json` 是结果的唯一"解码字典"。
3. **跨 run 不混用**：改了网格/探针参数重跑 = 新 run；旧 run 的 meta 与 CSV 永远配对。

## 3. 三类分析的坐标重建规则

| 分析 | CSV 内容 | 坐标来源 | 重建方法 |
|---|---|---|---|
| realworld | 每逻辑体一行（copy number 索引） | 逻辑体名 | **天然耦合**：按逻辑体名找 GDML 几何体，无需计算 |
| probe | 每探针一行（copy index） | locate 列表 | **行序 = `/score/probe/locate` 顺序**；第 i 行 = 第 i 个坐标 |
| voxel | 每体素一行（iX,iY,iZ） | boxSize/translate/nBin | **索引公式**（见下） |

### 3.1 voxel 重建公式（统一版，含 translate）

```
h = half_size_cm = boxSize/2   （boxSize 是半尺寸！）
c = center_cm    = translate   （无 translate 时 = (0,0,0)，兼容 GUI_Design §8 旧式）
d = 2·h / nBin                 （每轴体素边长）

cell(i,j,k) 中心 = ( c.x - h.x + (i+0.5)·d.x,
                     c.y - h.y + (j+0.5)·d.y,
                     c.z - h.z + (k+0.5)·d.z )
```

- CSV 行序：iX 变化最快，iY 次之，iZ 最慢（G4 逐 cell 输出，与 G4Box 一致）
- 构建 `vtkImageData`：`origin = (c.x-h.x, c.y-h.y, c.z-h.z)`，`spacing = d`，`dimensions = nBin`
- 单位统一 cm（G4 mesh 内部与 GDML 世界坐标均为 cm）

### 3.2 probe 重建规则

- 第 i 行 = 第 i 个 `/score/probe/locate x y z cm` 的探针，坐标直接取自列表
- 渲染：`vtkPoints` + 立方线框（半尺寸已知）+ 数值标签；多探针按 locate 顺序编号
- **顺序必须由 GUI 固定并持久化**：probe 弹窗保存有序的 locate 列表，mac 生成器按该顺序写 `/score/probe/locate`
- 待实测项：多探针 CSV 的 copy index 列（`0,0,0 / 1,0,0 / 2,0,0 …`？）；接入多探针前用一次真实运行确认

### 3.3 几何包围盒计算（自动定位模式的数据来源）

GDML 的 world volume 只是容器，**不计入包围盒**。弹窗的「全部几何体 / 选中几何」两种自动定位，其 AABB 由 GDML 解析器计算：

1. **排除规则**：跳过 world（及其同质容器层），只统计真正的几何体
2. **局部 AABB**：每个逻辑体的 solid → 局部 AABB（`G4Box` → ±half；`G4Tubs` → ±r / ±dz；其余按 solid 参数换算）
3. **世界 AABB**：局部 AABB 的 8 个角点经 placement 变换链（父级 rotation + translation 逐级传递）后取 min/max
4. **多实例**：同一逻辑体放置多次 → 各实例世界 AABB 取**并集**
5. **「全部几何体」** = 所有实例世界 AABB 的并集；**「选中几何」** = 该逻辑体多实例的并集
6. 输出即网格默认值：`half_size_cm` = AABB 半尺寸，`center_cm` = AABB 中心（写入 mac 的 boxSize / translate）

## 4. `run_meta.json` 完整 schema（与 GUI_Design §8.1 兼容扩展）

```json
{
  "run_id": "Run_003",
  "gdmls": ["axes.gdml"],
  "beam": { "particle": "proton", "energy_mev": 100, "n_events": 1000 },

  "analysis": "voxel",                    // voxel | probe | realworld
  "mesh": {                                // voxel：沿用 §8.1 字段 + 新字段
    "name": "M1",
    "type": "boxMesh",                    // boxMesh | cylinderMesh
    "mode": "all_geo",                    // all_geo | volume | manual（弹窗三种定位模式）
    "half_size_cm": [60, 60, 60],
    "n_bin": [20, 20, 20],
    "center_cm": [0, 0, 0],               // = translate，缺省 [0,0,0]
    "selected_volume": null               // mode=volume 时的逻辑体名，便于核对
  },
  "probe": {                               // probe：半尺寸 + 有序 locate
    "name": "Probes",
    "half_size_cm": 5,
    "material": "G4_WATER",
    "locates_cm": [[0,0,0], [25,0,0], [0,25,0]]
  },
  "quantities": [                          // 顺序 = mac 书写顺序 = CSV 块顺序
    { "name": "eDep", "type": "energyDeposit", "unit": "MeV", "filter": null },
    { "name": "protonFlux", "type": "volumeFlux", "unit": "", "filter": { "t": "particle", "p": "proton" } }
  ],
  "outputs": {
    "voxel_csv": "M1_eDep.csv",           // voxel：每 quantity 一个
    "probe_csv": "Probes.csv",            // probe/realworld：dumpAllQuantitiesToFile
    "spectra_csv": "rad4space_h1_eDep.csv"
  }
}
```

要点：
- `quantities` 顺序 = mac 书写顺序 = CSV 中 quantity 块顺序，后处理据此把列/块对应回类型与单位
- voxel 的 `half_size_cm` 即使 `mode=volume`/`mode=all_geo` 也**记录当时自动算出的具体值**（不只是 mode），保证重建始终可用
- `mode=all_geo` 的 AABB **不含 world 容器**（见 §3.3）；若 GDML 无 world 包装则以全部体积为准
- 每次运行前由弹窗确认回调把**当前快照**写入 `run_meta.json`，与 `input.mac`、CSV 同目录

## 5. 后处理重建流程

```
用户双击 Run 下的结果项
  → 读 run_meta.json + 读 CSV（QThread）
  → 按 analysis 分支：
       voxel    → 3.1 公式建 vtkImageData（origin/spacing/dimensions 直接来自 meta）
       probe    → locates 建 vtkPoints + 线框
       realworld→ 逻辑体名查 GDML，逐体数值着色
  → 一致性校验（见 §6），不过则拒绝渲染 + 提示
  → VTK 场景：GDML 三角网(半透明) + 结果体/点叠加（坐标同 cm 系统，天然对齐）
  → 交互：旋转/缩放/切片（复用 GUI_Design §9 结果窗口）
```

## 6. 一致性校验（防止"参数改了忘重跑"）

| 校验 | 规则 | 失败处理 |
|---|---|---|
| 体素总数 | CSV 行数 == nx·ny·nz | 拒绝渲染，提示"结果与配置不符，请重跑" |
| quantity 块 | CSV 块顺序/数量 == quantities 列表 | 同上 |
| probe 行数 | CSV 行数 == locates 数量 | 同上 |
| 几何匹配 | 当前 GDML 文件 == run_meta.gdmls | 提示"几何已更换，旧结果可能错位" |

> 这些校验让"CSV 无坐标"从缺陷变成特性：**任何配置变更都会在渲染前暴露**。

## 7. 过期检测（展示层）

- 每次打开结果时，用"当前几何 + 当前配置"重算预期体素数量，与 run_meta + CSV 比对
- 不一致 → 结果项标"⚠ 过期"，点击引导重新运行，而不是静默显示错误位置的数据

## 8. 与现有设计的对接

- 弹窗确认回调（realworld/probe/voxel）→ 统一写 `run_meta.json`（`result_meta.py` 读写，见 GUI_Design §1 模块清单）
- mac 生成器按 `quantities` 顺序写 `/score/quantity` + 紧跟 `/score/filter`（顺序绑定，见 solver README §5）
- 结果文件管理沿用 `GUI_Design.md §10`：一次运行一个目录
- 参考实现模式：1dRad 的 `_on_analysis_view_result`

## 9. 待验证项

- 多探针 CSV 的实际行格式（copy index 列）
- cylinderMesh（后续扩展）重建公式 = 柱坐标 (r, z, phi) 索引 → 需先转直角坐标，纳入时补本节
