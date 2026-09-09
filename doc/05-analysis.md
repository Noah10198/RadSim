# 05 · 分析与结果

> 源码：`ui/dialogs/analysis_common.py`、`ui/dialogs/{realworld,probe,voxel}_dialog.py`、
> `core/mac_builder.py`、`ui/probe_result_viewer.py`

## 1. 三种分析模式

| kind | 计分对象 | 网格 | 输出 | 查看器 |
|---|---|---|---|---|
| `realworld` | 逻辑体积（LogicalVolume） | 每体积一个 scorer | `out_<LV>.csv` | 柱状图 / 能谱 |
| `probe` | 探针立方体 | 每探针一个 scorer | `out_<probe>.csv` | 柱状图 / 能谱 |
| `voxel` | 直角网格 | 单个 `boxMesh` | `out_Box_<q>.csv` | 3D 体渲染 |

三种模式**可同时启用**，判定标准是「该模式下至少配置了一个计分数量」
（`mac_builder._kind_is_active`）。

## 2. 配置数据结构

```python
task.analysis_config = {
    "realworld": {"volumes": {<LVname>: (qs, hs)}},
    "probe":     {"probes": [{"name","half","x","y","z","material","qs","hs"}]},
    "voxel":     {"mode","center","half","nbin","selected","qs","hs"},
}
```

- `qs`：计分数量列表，每项 `{"name": str, "type": str, "filter": str | None}`
- `hs`：一维直方图列表，每项 `{"q": <quantity name>, "bins": int, "rng": [lo, hi], "log": bool}`
- `half` / `x,y,z` / `center` 单位均为 **mm**（写入宏时 ÷10 变 cm）
- `voxel.mode`：`all_geo`（自动取整个几何包围盒）或 `manual`（手填 center/half）

## 3. 计分数量清单

权威定义在 `analysis_common.QUANTITY_TYPES`（`type, 标签, 单位, 直方图x单位`）：

| type | 单位 | 直方图 x 单位 |
|---|---|---|
| `energyDeposit` | MeV | MeV |
| `doseDeposit` | Gy | Gy |
| `volumeFlux` | — | MeV |
| `nOfStep` | — | mm |
| `nOfTrack` | — | MeV |
| `nOfSecondary` | — | MeV |
| `cellFlux` | cm⁻² | MeV |
| `passageCellFlux` | cm⁻² | MeV |
| `passageCellCurrent` | — | MeV |
| `passageTrackLength` | mm | mm |
| `trackLength` | mm | 不支持 |
| `cellCharge` | e⁺ | 不支持 |
| `nOfCollision` | — | 不支持 |
| `nOfTerminatedTrack` | — | 不支持 |
| `population` | — | 不支持 |

单位列为空时界面显示 `[count]`。只有 `energyDeposit` / `doseDeposit` 在宏里写单位，
其余按求解器原生单位输出（见 `mac_builder._QUANTITY_UNIT`）。

## 4. 过滤器与粒子选项

`FILTER_TYPES`（Geant4 只实现这 5 种）：`particle`、`kineticEnergy`、
`particleWithEnergy`、`charged`、`neutral`。

`PARTICLE_CHOICES`：gamma、e-、e+、proton、neutron、alpha、He3、deuteron、triton、
mu-、mu+、pi-、pi+。

`ENERGY_UNITS`：MeV、keV、GeV。
`MATERIAL_CHOICES`（探针）：none、G4_WATER、G4_AIR、G4_Al、G4_Cu、G4_Fe、G4_Pb。

## 5. 一维直方图规则

1. 仅当 `quantity_meta(type)[1] is not None` 时支持，否则该行被静默跳过；
2. 默认区间按数量类型给（`HISTOGRAM_DEFAULT_RANGES`），如 `energyDeposit (0.001, 10)`、
   `doseDeposit (0.0001, 1)`；未定类型时用 `(0.001, 1000)`；
3. **同一数量类型的所有 series 必须共用 bins / range / log**，否则叠加在一张图上
   x 轴不对齐。`histogram_parameter_conflicts()` 在用户还在表单上时就给出警告；
4. 直方图 id 由 `mac_builder` 里的**全局计数器**分配（`/score/fill1D <id> <mesh> <q>`），
   多网格时必须连续递增。

## 6. 结果解析与分组

`probe_result_viewer.py` 是纯数据模块（不 import Qt / matplotlib）：

| 函数 | 输入 | 输出 |
|---|---|---|
| `parse_out_csv` | `out_*.csv` | `{"mesh", "blocks": [{name, unit, value, entry}]}`，单位从 `# ... [MeV]` 图例行回读 |
| `parse_h1_csv` | `rad4space_h1_*.csv` | `{nbins, lo, hi, log, edges, centers, counts, total, underflow, overflow, title}` |
| `rebin_log` | 线性直方图 | 某些构建即使配置为 log 也写 `#axis fixed`，此处按同 lo/hi/nbins 在 log10 轴重建 |
| `build_result_groups` | `entities`（name/qs/hs）+ work_dir | `{"quantity": [...], "histogram": [...]}` |
| `build_probe_result_groups` | probes 列表 + work_dir | 同上 |
| `find_group` | groups + kind + label | 单个分组 |

**分组键是数量类型（type），不是数量名**——所以 P1/P2/P3 的 `doseDeposit` 会归入
同一组比较，组标签形如 `doseDeposit [Gy]`。文件缺失的 series 被丢弃，空组被移除。

## 7. 项目树里的结果节点

任务完成后 `_refresh_task_results()` 先清空再按磁盘重建：

```
<task>
└── Results
    ├── <type [unit]>          ← quantity 组，双击开柱状图
    │   ├── <probe1>: <qname>
    │   └── <probe2>: <qname>
    ├── <type [xunit]>         ← histogram 组，双击开阶梯曲线
    ├── Voxel <qname>          ← 双击开 3D 体渲染
    ├── Trajectory             ← 双击开轨迹查看器
    └── run log
```

## 8. 常见陷阱

| 陷阱 | 说明 |
|---|---|
| 数量名重复 | 同一网格内重名会让 dump 文件互相覆盖 |
| 只配 `hs` 不配 `qs` | 该数量不会被创建，直方图也无数据 |
| 探针材质选 `none` | 宏里不写 `/score/probe/material`，使用求解器默认 |
| voxel 手填 `half` 过大 | 体渲染内存按 `(nbin+1)³` 增长 |
| 直方图 bins 不一致 | 曲线对比失真，对话框会提前警告 |
| 改了数量类型但没改名字 | 结果分组按 type 走，名字只作显示 |
