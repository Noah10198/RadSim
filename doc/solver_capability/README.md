# rad4space solver 能力清单（脚本全集）

> 依据：`3dRad/solver/rad4space` 源码、`build/Release/` 下 23 个 .mac 测试脚本、
>       手册《BookForApplicationDevelopers》(Release 11.4) 4.8 Parallel Geometries。
> 用途：GUI 的 mac 生成器输入 —— 每个命令、参数、阶段限制都从这里来。

## 1. 脚本通用结构（GUI 生成 mac 的顺序约束）

```
# [阶段 1] PreInit 命令（必须在 /run/initialize 之前）
/rad4space/gdml/SetGDMLFile <file>
/rad4space/physics/SetPL <list>
/rad4space/physics/AddHP <bool>
/rad4space/physics/AddRDM <bool>
/rad4space/physics/SetMaxStep <mm>
/run/verbose 1  /control/verbose 1

# [阶段 2] 初始化（此后才能用 /gps /score /analysis）
/rad4space/physics/SetGlobalCut <mm>     # 实际放在 PreInit 也可
/run/initialize

# [阶段 3] 粒子源
/gps/...

# [阶段 4] 评分网格定义（/score/create ... /score/close）
/score/...

# [阶段 5] 能谱直方图（仅 probe / realworld 支持）
/analysis/h1/create ...
/score/fill1D ...

# [阶段 6] 运行 + 导出
/run/beamOn <nEvents>
/score/dumpQuantityToFile <mesh> <qty> <file.csv>
exit
```

## 2. rad4space 自定义命令（G4GenericMessenger 注册）

| 命令 | 参数 | 阶段 | 说明 |
|---|---|---|---|
| `/rad4space/gdml/SetGDMLFile` | 文件路径 | PreInit | 导入 GDML 几何 |
| `/rad4space/physics/SetPL` | 物理列表名 | PreInit | `FTFP_BERT` / `QGSP_BIC` / `Shielding` 等参考列表 |
| `/rad4space/physics/AddHP` | true / false | PreInit | 追加 `_HP` 高精度中子变体（Shielding 除外） |
| `/rad4space/physics/AddRDM` | true / false | PreInit | 注册 `G4RadioactiveDecayPhysics`（Shielding 下无效） |
| `/rad4space/physics/SetGlobalCut` | 数值 + mm | Init 前 | 全局生产截断（gamma/e-/e+/proton） |
| `/rad4space/physics/SetMaxStep` | 数值 + mm | PreInit | `G4UserLimits` 全局最大步长，0 = 关闭 |
| `/rad4space/analysis/filename` | 名称 | - | 输出文件基名（默认 csv） |

## 3. 评分网格：四种创建方式（核心）

| 网格类型 | 创建命令 | 配套命令 | 输出 |
|---|---|---|---|
| **voxel·直角** | `/score/create/boxMesh <name>` | `/score/mesh/boxSize dx dy dz cm`（半尺寸）、`/score/mesh/nBin nx ny nz`、`/score/mesh/translate` | 体素 CSV（`iX,iY,iZ,val,...`） |
| **voxel·柱** | `/score/create/cylinderMesh <name>` | `/score/mesh/cylinderSize R halfDz cm`、`/score/mesh/nBin nr nz nphi` | 体素 CSV |
| **realworld** | `/score/create/realWorldLogVol <LV名>` | 无（一个逻辑体一个 cell，mesh 命令无效） | 逐体汇总 CSV |
| **probe** | `/score/create/probe <name> <halfSize> cm` | `/score/probe/locate x y z cm` | 逐探针汇总 CSV |

> 背景（手册 4.8）：Geant4 的 mesh 评分基于 **平行世界（Parallel World）**——
> 平行世界是叠加在质量几何上的"幽灵几何"，`G4Transportation` 被自动替换为
> `G4CoupledTransportation`，粒子同时受质量几何与平行世界边界限制。
> 网格/探针/幽灵体都可任意放置、互不重叠限制，材料对物理无影响（除非开启
> layered mass geometry）。这解释了为什么 boxMesh 可以放在几何体外、probe 可以任意定位。

## 4. 通用 /score 命令

```
/score/quantity/<primitive> <name> [unit]   # energyDeposit MeV / volumeFlux / doseDeposit ...
/score/filter/particle <fname> <particle>   # 粒子筛选（绑定"紧邻其前"的 quantity，见 §5）
/score/close
/score/list
/score/verbose <n>
/score/fill1D <idx> <mesh> <qty>            # 1-D 能谱填充（box/cylinder 不支持！）
/score/dumpQuantityToFile <mesh> <qty> <file>
/score/dumpAllQuantitiesToFile <mesh> <file>
```

**能力差异表**：

| 能力 | realworld | probe | voxel (box/cylinder) |
|---|---|---|---|
| energyDeposit / volumeFlux 等 quantity | ✓ | ✓ | ✓ |
| 能谱 fill1D | ✓ | ✓ | ✗（`dumpQuantityToFile` 出体素场） |
| filter | ✓ | ✓ | ✓ |
| 汇总 CSV | `dumpAllQuantitiesToFile` | 同左 | 无（用 dumpQuantityToFile） |

## 5. filter（过滤器）详解

**一句话**：filter 给某个 quantity 加筛选条件——不满足条件的粒子/事件，就不记进这个量。

### 绑定规则（BFAD 11.4 官方 + rad4space 实测）

> "`/score/filter` command affects on the immediately preceding scorer"

1. **顺序绑定**：`/score/filter/xxx` 只作用于**紧挨在它前面那一条 `/score/quantity`**。书写顺序永远是 quantity 在前、filter 在后；
2. **一对一**：每个 quantity 最多挂一个 filter；想要多种过滤 → 定义多个不同名字的同类型 quantity；
3. **白名单语义**：filter 是"只放行指定粒子"，不匹配的贡献被丢弃；但粒子本身照常模拟，物理过程不受影响；
4. **过滤时机**：在 step/track 被记入 scorer 前判断，不满足则不计入该量；
5. rad4space 实测（`run.mac` / `mesh_probe.mac`）：全部按"quantity 后紧跟 filter"书写，日志确认 `G4VScoringMesh::SetFilter() : protonFilter is set to protonFlux`。

### filter 类型（仅 5 种，源码确认）

| UI 命令 | 语法 | 用途 |
|---|---|---|
| `particle` | `/score/filter/particle <名> <粒子>` | 按粒子种类（gamma / e- / e+ / proton / alpha …） |
| `kineticEnergy` | `/score/filter/kineticEnergy <名> <Emin> <Emax> <单位>` | 按动能区间 |
| `particleWithEnergy` | `<名> <粒子> <Emin> <Emax> <单位>` | 粒子 + 动能区间组合 |
| `charged` | `/score/filter/charged <名>` | 只收带电粒子（含全部离子） |
| `neutral` | `/score/filter/neutral <名>` | 只收中性粒子 |

> 依据：`source/digits_hits/scorer/src/` 下 filter 实现类仅 5 个
> （`G4SDParticleFilter` / `G4SDKineticEnergyFilter` / `G4SDParticleWithEnergyFilter` /
> `G4SDChargedFilter` / `G4SDNeutralFilter`）。
> 网上流传的 `charge` / `particleWithCharge` / `region` filter **不存在**。

### 筛选离子（ion）的坑

- **不能直接 `/score/filter/particle C12`**：`G4SDParticleFilter` 构造时用
  `G4ParticleTable::FindParticle(name)` 解析粒子名，而 `FindParticle` **只做字典查找、不解析离子名**。
  具体核素离子（C12 / O16 / Fe56…）由 `G4IonTable` **惰性创建**——mac 解析阶段（beamOn 前）
  粒子表里没有它们 → filter 构造直接 `FatalException` 崩溃（`DetPS0101`）。
- **能按名筛的"离子"只有预定义轻离子**：proton / deuteron / triton / alpha / He3（粒子表常驻）。
- **没有"筛所有离子"的内置 filter**：`charged` 只排除中性（离子全带电，但质子 / e± 也带电）。
- **要筛特定重离子**（如空间辐射 Fe、C）：必须在 mac 里先让核素进粒子表——用
  `/gps/particle ion` + `/gps/ion Z A` 定义束流（此时创建核素），再 `/score/filter/particle Fe56`。
  局限：束流必须就是该核素；只有它（及其碎裂产物中的同核素）能被统计。
- **GUI 设计（首版范围）**：粒子 filter 下拉只列**标准粒子**（gamma / e- / e+ / proton / neutron …）+ 轻离子（alpha / He3 / deuteron / triton）；
  离子过滤提供 `charged` / `neutral`；**重离子核素选择器列为后续扩展**（需 `/gps/ion` 预创建，见上）。

### 经典写法（G4 example B5 同款）

```
/score/quantity/energyDeposit eDep          # 无 filter → 所有粒子的能量沉积
/score/quantity/nOfStep nOfStepGamma        # ← 绑定 gammaFilter
/score/filter/particle gammaFilter gamma      # 只记光子步数
/score/quantity/nOfStep nOfStepEMinus       # ← 绑定 eMinusFilter
/score/filter/particle eMinusFilter e-        # 只记电子步数
/score/quantity/nOfStep nOfStepEPlus        # ← 绑定 ePlusFilter
/score/filter/particle ePlusFilter e+         # 只记正电子步数
```

### GUI 映射

filter 在界面上是 **quantity 行的"附加属性"**（不是独立概念）：

- 每个 quantity 行：`名称 + 类型 + [filter]`，filter 默认"无"
- filter 下拉：`无 / 粒子 / 动能区间 / 带电 / 中性 …`，选中后展开参数子行
- 生成 mac 时"quantity 行后紧跟 filter 行"，天然满足顺序绑定，不会错位

## 6. 能谱直方图（/analysis/h1）

```
/analysis/h1/create <name> <title> <nbins> <xmin> <xmax> <unit> [!log]
/score/fill1D <idx> <mesh> <qty>
```

- 参数序列：`/analysis/h1/create <name> <title> <nbins> <xmin> <xmax> <unit> <valFcn> <binScheme>`，后 6 个可选。
  其中 `!` 是 G4 UI 层的**占位符**（=该参数用默认值，源码依据 `G4UIcommand.cc` 的 `DoIt()`，手册正文未讲解），
  末位 `log` 是**对数分箱**（binScheme），与 `valFcn`（对填充值取 log/log10/exp，默认 none）是两回事。
  例：`... MeV ! log` = valFcn 用默认 none + 对数分箱。
- 输出由 `G4AnalysisManager` 写 csv（`G4TScoreHistFiller` 绑定 scorer→h1）

### 6.1 primitive scorers 全集（BFAD 11.4 Table 8，realWorld/probe 全部可用）

官方《Command-based scoring》Table 8（旧版手册为 4.9.9 / Table 4.1）。realWorld 与 probe 相同：
**17 种全部可定义**；能谱 fill1D 也只对 probe / realWorld 开放（box / cylinder mesh 不支持）。

| scorer 类型 | 量 | 默认单位 | 1D 能谱 x 轴 | 1D 能谱 y 轴 |
|---|---|---|---|---|
| energyDeposit | 体积内沉积能量 | MeV | 每步能量沉积 (MeV) | 径迹权重 |
| doseDeposit | 体积内沉积剂量 | Gy | 每步剂量 (Gy) | 径迹权重 |
| volumeFlux | 进入体积的径迹数 | 计数 | 入射动能 Ek (MeV) | 径迹权重 |
| nOfStep | 体积内步数 | 计数 | **步长 (mm)** | entry（未加权） |
| nOfTrack | 体积内径迹数（穿 + 终止） | 计数 | 入射动能 Ek (MeV) | 径迹权重 |
| nOfSecondary | 产生的次级径迹数 | 计数 | 入射动能 Ek (MeV) | 径迹权重 |
| cellFlux | 径迹长度 ÷ 体积 | cm⁻² | 入射动能 Ek (MeV) | 加权通量 |
| passageCellFlux | 仅穿过体积的径迹通量 | cm⁻² | 入射动能 Ek (MeV) | 加权通量 |
| passageCellCurrent | 穿过体积的径迹数 | 计数 | 入射动能 Ek (MeV) | 径迹权重 |
| passageTrackLength | 穿过体积的径迹长度和 | mm | 径迹长度 (mm) | entry（未加权） |
| trackLength | 体积内总径迹长度 | mm | —（不支持 fill1D） | — |
| cellCharge | 体积内沉积电荷 | e⁺ | — | — |
| nOfCollision | 物理相互作用步数 | 计数 | — | — |
| nOfTerminatedTrack | 体积内终止径迹数 | 计数 | — | — |
| population | 事件内体积中唯一径迹数 | 计数 | — | — |
| flatSurfaceCurrent | -z 面电流（仅 boxMesh） | cm⁻² | 入射动能 Ek (MeV) | 径迹权重 |
| flatSurfaceFlux | -z 面通量 1/cosθ（仅 boxMesh） | cm⁻² | 入射动能 Ek (MeV) | 径迹权重 |

> `flatSurface*` 仅用于 boxMesh → 与 fill1D（仅 probe/realWorld）**互斥，GUI 不出现**；
> `trackLength` 虽可对 realWorld 定义，但 x 轴 n/a → 不能挂 fill1D。

### 6.2 能谱 x 轴单位由 quantity 类型决定（GUI 联动规则）

直方图单位**不是自由选择**，随关联 quantity 类型自动确定：

| quantity 类型 | x 轴含义 | x 轴单位（GUI 单位下拉） |
|---|---|---|
| energyDeposit | 每步能量沉积 | **MeV**（可换算 keV / GeV） |
| doseDeposit | 每步剂量 | **Gy**（可换算 mGy） |
| volumeFlux / nOfTrack / nOfSecondary / cellFlux / passageCellFlux / passageCellCurrent | 入射粒子动能 Ek | **MeV**（可换算 keV / GeV） |
| nOfStep | 步长 | **mm** |
| passageTrackLength | 径迹长度 | **mm** |

> 所以"energyDeposit 能谱单位只能是 MeV"：x 轴是能量沉积值，量纲固定；
> GUI 的单位下拉应**随关联量类型切换**，不是万能下拉。

## 7. 粒子源（/gps）支持的能量分布（来自测试脚本）

| 分布 | 命令 |
|---|---|
| 单能 | `/gps/energy 100 MeV` |
| 线性谱 | `/gps/ene/type Lin` + `/gps/ene/min 1. MeV` + `/gps/ene/max 10. MeV` + gradient/intercept |
| 用户自定义谱 | `/gps/ene/type User` + `/gps/hist/type energy` + `/gps/hist/point E p` |

其他：`/gps/pos/type Point`、`/gps/pos/centre`、`/gps/direction`、`/gps/verbose`。

> 注意：`/gps/ene/type Lin` 必须显式设置 gradient/intercept（默认 0 会在 Geant4 11.4.2 产生 NaN，track 瞬间被 kill，所有 scorer 读 0）。

## 8. 运行模式

- 批处理：`rad4space.exe run.mac [nThreads]`（多线程第二参数）
- 交互/可视化：`rad4space.exe`（无参）→ 执行 `vis.mac`（OGLIQt 窗口，`/vis/drawVolume` + 轨迹绘制），**此时 run.mac 不执行**

## 9. 目录索引

- `realworld/realworld.mac` — 逻辑体评分完整模板（含能谱 + filter 示例）
- `probe/probe.mac` — 探针评分完整模板（含能谱）
- `voxel/box.mac` — 直角网格模板
- `voxel/cylinder.mac` — 柱坐标网格模板（后续扩展）

## 10. TID（总电离剂量）说明

**TID 不是 solver 功能，是 GUI 后处理**。solver 只提供 `energyDeposit` / `doseDeposit`
quantity（体素场或汇总 CSV），TID 由 GUI 端对结果积分求和得到：

```
TID = Σ energyDeposit(体素) / 质量   （或直接用 doseDeposit 求和）
```

因此：
- solver / mac 层完全不用动
- GUI 的"TID 汇总"结果项 = 在结果表格里加一列后处理计算（按 Run 绑定 run_meta.json 里的密度/体积信息）
- 与 1dRad 的做法保持一致即可
