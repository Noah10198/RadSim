# 03 · run.mac 生成与求解器接口

> 源码：`core/mac_builder.py`（纯 Python，不依赖 Qt）
> 相关：`ui/dialogs/physics_config.py`、`ui/dialogs/gps_source.py`、`core/run_manager.py`

## 1. 设计原则

rad4space 是一个 **Geant4 batch 程序**，它只接受一个参数——宏文件：

```
rad4space.exe  <workdir>/run.mac
```

因此「运行配置」这件事完全落在宏文件里：线程数、事件数、几何路径、物理列表、
粒子源、计分网格、直方图、输出文件名，全部由 `mac_builder` 写进 `run.mac`。
命令行不再传递任何开关，这带来两个好处：

- 每次运行都有一份可复现、可人工阅读的完整记录；
- GUI 与求解器之间不需要自定义参数协议，宏文件本身就是协议。

## 2. 输入：一个 RunTask

`build_mac_text(gdml_full_path, task)` 从 `RunTask`（`core/project_model.py`）的四个字段取值：

| 字段 | 类型 | 由谁写入 | 作用 |
|---|---|---|---|
| `task.calculate` | `CalculateSetting` | 计算设置对话框 | `n_threads` 线程数、`n_events` 事件数 |
| `task.physics` | dict | 物理过程对话框 | 物理列表、HP/RDM 开关、截断、最大步长 |
| `task.particle` | dict | 粒子源对话框 | gun / gps / 导入文件三种模式 |
| `task.analysis_config` | dict | 三个分析对话框 | `realworld` / `probe` / `voxel` 计分配置 |

`gdml_full_path` 是导入几何的**绝对路径**，宏里用 `/rad4space/gdml/SetGDMLFile` 直接引用，
几何文件不复制到工作目录。

## 3. 输出：run.mac 的 8 个段落

`build_mac_text()` 按固定顺序拼接，顺序本身有语义（PreInit / PostInit）：

| # | 段落 | 内容 | 时机 |
|---|---|---|---|
| 1 | run control | `/control/saveHistory`、可选 `/run/numberOfThreads N`、`/run/verbose 1`、`/control/verbose 1`、`/event/verbose 0`、`/tracking/verbose 0` | PreInit |
| 2 | geometry | `/rad4space/gdml/SetGDMLFile <绝对路径>` | PreInit |
| 3 | physics | `physics_config.macro_lines(task.physics)` | PreInit |
| 4 | initialize | `/run/initialize`（此后运行选项被冻结） | 分界点 |
| 5 | source | `gps_source.macro_lines(task.particle)` | PostInit |
| 6 | scoring setup | 网格 / 直方图 / fill1D 的创建命令 | PostInit，**必须**在 beamOn 前 |
| 7 | run | `/run/beamOn <N>` | — |
| 8 | scoring dump | `/score/dump*` 输出命令 | **必须**在 beamOn 后 |

几个关键点：

- **线程行可选**：`n_threads == 0` 时整行省略，求解器回退到自身默认线程数。
- **事件数兜底**：`n_events <= 0` 时使用 `DEFAULT_EVENTS = 10000`，避免空跑。
- **dump 必须在 beamOn 之后**：在 beamOn 之前 dump 会写出全零文件——这是宏里
  注释反复强调的坑。
- **直方图必须在 beamOn 之前创建并绑定**：`/analysis/h1/create` + `/score/fill1D`
  都属于 setup 段，否则运行期没有累积目标。

## 4. 物理与源：复用对话框模块的宏生成器

`mac_builder` 不自己拼物理和源的命令，而是直接调用两个对话框模块里的纯函数
（这两个模块虽然放在 `ui/dialogs/` 下，但宏生成部分是纯逻辑）：

```python
from ui.dialogs import physics_config as pcfg   # macro_lines(cfg)
from ui.dialogs import gps_source as gps        # macro_lines(cfg)
```

### 物理段（`physics_config.macro_lines`）

```
/rad4space/physics/SetPL <physics_list>
/rad4space/physics/AddHP true        # 仅当 add_hp 且列表支持
/rad4space/physics/AddRDM true       # 仅当 add_rdm 且列表支持
/rad4space/physics/SetGlobalCut <mm> mm
/rad4space/physics/SetMaxStep <mm> mm # 仅当 > 0
```

注意截断与步长的单位是 **mm**（不是 cm），这是求解器命令本身的约定。

### 源段（`gps_source.macro_lines`）

按 `cfg["mode"]` 分派：

| mode | 生成内容 |
|---|---|
| `gun` | G4ParticleGun 的 `/gps/*` 别名命令（`/gps/particle`、`/gps/energy`、`/gps/position`、`/gps/direction`） |
| `gps` | 完整 GPS 序列（`/gps/pos/type`、`/gps/ang/type`、`/gps/ene/type` …） |
| `file`（导入的原始宏） | 文本原样写入，不解析、不过滤 |

**单位换算发生在这一层**：源位置 / 中心 / 形状尺寸 / 焦点由 mm 除以 10 转成 cm；
能量恒为 MeV、角度恒为 deg，不做换算。

## 5. 计分：三种分析模式

`scoring_block(analysis_config)` 返回 `(setup_lines, dump_lines)`，并按
`active_kinds()` 的顺序依次生成。**三种模式可以同时启用**——它们各自是独立的
scorer mesh，rad4space 能在同一次 `/run/beamOn` 里一起计分，而不是只保留一种。

`active_kinds()` 的判定标准是「配置里至少存在一个计分数量」：

| kind | 判定 |
|---|---|
| `realworld` | 任一逻辑体积的 `qs` 或 `hs` 非空 |
| `probe` | 任一探针的 `qs` 或 `hs` 非空 |
| `voxel` | `voxel.qs` 非空 |

### 5.1 real world（逻辑体积计分）

```gdscript
/score/create/realWorldLogVol <LVname>
/score/quantity/<type> <qname> [unit]
/score/close
```

每个配置了计分量的逻辑体积一个网格，网格名 = 逻辑体积名。

### 5.2 probe（探针立方体）

```gdscript
/score/create/probe <name> <half/10> cm
/score/probe/material <material>        # 可选，material == "none" 时省略
/score/probe/locate <x/10> <y/10> <z/10> cm
/score/quantity/<type> <qname> [unit]
/score/close
```

`half` 是探针立方体的**半边长**（mm），换算为 cm。

### 5.3 voxel（直角网格）

```gdscript
/score/create/boxMesh Box
/score/mesh/boxSize <half[0]/10> <half[1]/10> <half[2]/10> cm   # 半长，不是全宽
/score/mesh/nBin <nx> <ny> <nz>
/score/mesh/translate/xyz <cx/10> <cy/10> <cz/10> cm
/score/quantity/<type> <qname> [unit]
/score/close
```

`/score/mesh/boxSize` 取的是**半长**，宏里专门留了注释提醒。

### 5.4 计分数量（quantity）与单位

`/score/quantity/<type> <name> [unit]` 中 `<type>` 就是分析配置里的 `type` 键。
只有两个 scorer 会在样本文件里写单位，因此只有它们追加单位后缀：

```python
_QUANTITY_UNIT = {"energyDeposit": "MeV", "doseDeposit": "Gy"}
```

其余数量按求解器原生单位输出，不写单位。

完整可选数量（15 种）见 [09-data-formats.md](09-data-formats.md#计分数量清单)，
清单的唯一权威来源是 `ui/dialogs/analysis_common.QUANTITY_TYPES`，
`mac_builder._HIST_XUNIT` 是它在 core 侧的一份镜像（避免 core 反向依赖 Qt）。

### 5.5 一维直方图（能谱）

对支持直方图的数量，每个 `hs` 条目生成两行：

```gdscript
/analysis/h1/create <mesh>_<qname> <mesh>_<qname> <bins> <xmin> <xmax> <xunit> [ ! log ]
/score/fill1D <globalId> <mesh> <qname>
```

- `globalId` 来自一个**全局共享计数器** `id_state["n"]`。G4TScoreHistFiller 按
  创建顺序全局编号，因此 realworld + probe 同时启用时，id 必须连续递增，不能各自从 0 开始。
- `xunit` 由数量类型决定（`_HIST_XUNIT`）；为 `None` 的数量（如 `trackLength`、
  `cellCharge`）不支持直方图，会被静默跳过。
- `log` 为真时在行尾追加 ` ! log`。

### 5.6 输出命令

| kind | dump 命令 | 产出文件 |
|---|---|---|
| realworld / probe | `/score/dumpAllQuantitiesToFile <mesh> out_<mesh>.csv` | `out_<网格名>.csv` |
| voxel | `/score/dumpQuantityToFile Box <q> out_Box_<q>.csv` | 每个数量一个 `out_Box_<q>.csv` |

voxel 是 3D 网格，没有 `dumpAll`，只能按数量逐个 dump。

## 6. 工作目录

`write_workdir(gdml_full_path, task, out_root)`：

1. 用 `re.sub(r"[^A-Za-z0-9_.\-]", "_", task.name)` 把任务名净化成安全的目录名
   （与 `core/project_io.safe_task_name` 保持一致的规则，这样草稿目录和保存后的副本能对上）；
2. 若 `<out_root>/<safe>` 已存在，**整个删除**——重跑不允许残留上一次的 csv / log，
   否则较短的一次运行会留下陈旧结果；
3. 重新创建目录，写入 `run.mac`，返回工作目录路径。

默认 `out_root` 是 `solver/runs`（见 `core/solver_config.get_results_root`），
可用 QSettings 覆盖。每个任务独立子目录，因此并发运行不会互相覆盖。

## 7. 常见陷阱

| 陷阱 | 说明 |
|---|---|
| dump 放在 beamOn 之前 | 写出全零文件 |
| 直方图 id 各自从 0 开始 | 多网格时 `/score/fill1D` 绑错目标 |
| `boxSize` 误传全宽 | 网格尺寸大一倍（应传半长） |
| `n_events = 0` | 宏里会兜底为 10000，而不是不跑 |
| 物理/几何命令写到 `/run/initialize` 之后 | 不生效 |
| 源位置忘记 mm→cm | 源跑到 10 倍远的位置 |
