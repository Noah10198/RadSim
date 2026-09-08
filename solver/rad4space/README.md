# rad4space

基于 Geant4 11.4.2 的辐射求解器（batch 仿真）。设计参照 gorad / RE03 / exgps，
全部采用 Geant4 原生机制：

- **几何**：GDML 导入（G4GDMLParser，`/rad4space/gdml/SetGDMLFile`）
- **并行**：多线程 MT（G4RunManagerFactory，线程数自动取 CPU 核数）
- **物理**：可替换物理列表（G4PhysListFactory + messenger，运行时可切换，
  参考 gorad 的 GRPhysicsList 做法）
- **源**：通用粒子源 GPS（G4GeneralParticleSource，同 exgps）
- **记录**：原生 command-based scoring（RE03 风格 probe/boxMesh + primitive
  scorer）+ 原生 1-D histogram 填充（G4 Book For Application Developers
  4.9.8，`G4TScoreHistFiller<G4AnalysisManager>`）

## 目录结构

```
rad4space/
  rad4space.cc            # 入口
  src/  R4DetectorConstruction.cc   GDML 导入 + messenger
        R4PhysicsList.cc           可替换物理列表 + messenger
        R4ActionInitialization.cc  user action 注册
        R4RunAction.cc             analysis 输出 + histogram filler
        R4PrimaryGeneratorAction.cc  GPS
  include/  R4*.hh
  run.mac                   batch 宏（几何/物理/源/记录）
  vis.mac                   interactive 可视化宏
  gps_point.mac             备用 GPS 宏
  simpleCone.gdml / axes.gdml  测试几何
```

## 依赖（Windows 预编译版）

- Geant4 11.4.2（`target/bin` 已加入系统 PATH）
- xerces-c 3.3.0（GDML 解析，`target/bin` 已加入 PATH）
- Qt 6.11（Geant4 预编译的 `G4interfaces.dll` 依赖 Qt，`bin` 已加入 PATH）

## 构建

```bat
cmake -S rad4space -B rad4space/build -DGeant4_DIR=D:/Application/Geant4/geant4-v11.4.2/target/lib/cmake/Geant4
cmake --build rad4space/build --config Release --parallel 8
```

> 若不需要可视化，可用 `-DWITH_GEANT4_UIVIS=OFF` 减小链接面。

## 运行

```bat
cd rad4space\build\Release
rad4space.exe run.mac          :: batch
rad4space.exe run.mac 8        :: 指定 8 线程
rad4space.exe                  :: interactive：自动执行 vis.mac，
                               ::   Qt 窗口渲染 axes.gdml 结构 + 10 个质子轨迹
```

### 已知环境坑（重要）

若在激活了 conda 的终端运行报 `0xC0000139`，是因为 conda 环境自带的旧版
Qt6（如 `pyoccenv\Library\bin`）抢在 Geant4 匹配的 Qt6.11 之前被加载。
把 Qt6.11 放到 PATH 最前再运行：

```bat
set PATH=D:\Application\Qt6.11\6.11.1\msvc2022_64\bin;%PATH%
cd rad4space\build\Release
rad4space.exe run.mac
```

## run.mac 说明

```mac
/rad4space/gdml/SetGDMLFile axes.gdml     # 几何（PreInit）
/rad4space/physics/SetPL FTFP_BERT        # 物理列表，可换 QGSP_BIC/Shielding...
/rad4space/physics/SetGlobalCut 0.7 mm
/run/initialize                           # 必须先于 /gps /score /analysis
/gps/particle proton                      # 源（exgps 风格）
...
/score/create/probe Probes 5. cm          # RE03 风格 scoring
/score/quantity/volumeFlux volFlux
/score/fill1D 0 Probes volFlux            # 4.9.8 原生 histogram 填充
```

注意：`/analysis/h1/create` 的 histogram id 从 **0** 开始，`/score/fill1D`
的 id 与之对应。

## 粒子与物理列表

**GPS 默认粒子是电子 e-**（G4GeneralParticleSource 的内部默认）。即使只设了
能量/位置/方向，只要没写 `/gps/particle`，发射的就是 e-。建议总是显式指定：

```mac
/gps/particle proton          # 任意 Geant4 粒子名
/gps/ion 26 56 26             # 离子：Z A Q（如 Fe-56）
/gps/energy 100 MeV
```

当前默认的 `FTFP_BERT` 是 Geant4 全粒子参考列表，空间环境常用粒子全覆盖：
电子/正电子、gamma、质子、中子、π/K/μ、离子（H→Fe→U 含核碎裂）、不稳定
粒子衰变。

针对空间环境（GRAS 风格）的推荐：

| 场景 | 推荐物理列表 | 说明 |
|---|---|---|
| 通用分析 | `FTFP_BERT` / `QGSP_BERT` | 高能段覆盖好 |
| 屏蔽 / 重离子防护（NASA） | `Shielding` | QMD 重离子碎裂 + 热中子 HP |
| 活化产物 / 余晖剂量 | `Shielding` + `AddRDM true` | 放射性衰变 |

物理命令（PreInit，须在 `/run/initialize` 之前）：

- `/rad4space/physics/SetPL <name>`：任意参考列表名（FTFP_BERT、QGSP_BIC、
  QGSP_BERT、Shielding 等）
- `/rad4space/physics/AddHP true`：追加 `_HP` 高精度中子（非 Shielding 时）
- `/rad4space/physics/AddRDM true`：注册 G4RadioactiveDecayPhysics（非 Shielding 时）
- `/rad4space/physics/SetGlobalCut <len>`：gamma / e- / e+ / proton 生产阈值
- `/rad4space/physics/SetMaxStep <len>`：所有体积的单步最大步长
  （`G4UserLimits`，等价于 GRAS 的 `StepMax`；0 = 关闭，默认关闭）

**ion 需要单独设 cut 吗？不需要。** production cut 机制只对 gamma / e± / proton
有意义——它们决定二次粒子（δ 电子、光子）的产生阈值。离子作为入射粒子不受
production cut 约束，其能量沉积的精细度由 **e- 的 cut** 主导（δ 电子产额）。
所以目前只对四个粒子设 cut 是合理的（与 GRAS 默认一致）。

空间环境物理配置完整示例（PreInit，须在 `/run/initialize` 之前，顺序固定）：

```mac
# --- 几何 & 物理 ---
/rad4space/gdml/SetGDMLFile axes.gdml
/rad4space/physics/SetPL Shielding        # NASA 空间防护：QMD 重离子 + HP 热中子
/rad4space/physics/AddRDM true            # 活化产物放射性衰变（可选）
/rad4space/physics/SetGlobalCut 0.7 mm    # gamma/e-/e+/proton 生产阈值
/rad4space/physics/SetMaxStep 1. mm       # 限单步步长：可视化/薄层能沉精度（可选）
/run/initialize
```

## mesh 测试脚本

Geant4 11.4 原生 command-based scoring（新版 `/score/` 语法），4 个独立测试宏
（`rad4space.exe mesh_xxx.mac [线程数]`，均已实测通过）：

| 脚本 | 覆盖 | 输出 |
|---|---|---|
| `mesh_probe.mac` | `/score/create/probe` 探测立方体 + `/score/fill1D` 1-D 直方图 | `mesh_probe.csv` + `rad4space_h1_*.csv` |
| `mesh_realworld.mac` | `/score/create/realWorldLogVol` 真实几何体积评分 | `mesh_realworld.csv` + `rad4space_h1_*.csv` |
| `mesh_box.mac` | `/score/create/boxMesh` 直角网格 | `mesh_box_eDep.csv` |
| `mesh_cylinder.mac` | `/score/create/cylinderMesh` 圆柱网格 | `mesh_cylinder_eDep.csv` |

要点：

- `/score/fill1D <histID> <mesh> <scorer>` **只支持 probe 和 realWorldLogVol**；
  boxMesh / cylinderMesh 只能用 `/score/dumpQuantityToFile` 导出 3-D 网格
- 新版语法 `/score/mesh/boxSize <Dx> <Dy> <Dz> <unit>`、`/score/mesh/cylinderSize <R> <Dz> <unit>`
  **不带 mesh 名**（作用于最近创建的 mesh）
- cylinder 的 `/score/mesh/nBin` 顺序是 `Nr Nz Nphi`
- mesh 命令须在 `/run/initialize` 之后、`/run/beamOn` 之前
- `realWorldLogVol` 的 mesh 名就是逻辑体积名（如 `TOP`、`vOrigin`），
  `/score/mesh/` 命令对它无效

## 输出

- `Probes.csv`：primitive scorer 积分（total、total²、entry）
- `rad4space_h1_<name>.csv`：1-D 能谱 histogram
- 默认输出类型为 csv（`R4RunAction` 中 `SetDefaultFileType("csv")`）

## 粒子轨迹数据（重绘时如何连接，不误连）

轨迹输出与上面的 scoring / histogram 无关，用于在 GUI 端按位置重绘粒子路径。
**始终输出**（无需开关命令）：`R4SteppingAction` 把轨迹点写入进程级共享存储，
由 **master 的 `EndOfRunAction`** 一次性写出 `Traj.csv`（工作目录下）。
从 master 写（而不是 worker）是因为默认 tasking 模式的线程编号与经典 MT 不同，
master 的 EndOfRunAction 是最可靠的统一落盘点。

为避免跨线程合并，**记录者只选一个 worker**：不是写死线程号，而是**原子地让
第一个进入 stepping 的 worker 当选**（`ClaimRecorder()`）。tasking 下 worker
编号为 0..N-1、经典 MT 下为 1..N，写死任何一个都会在另一种模式下失效，故动态选取。

> 因此默认多线程时 Traj.csv 只含"当选 worker"处理的那部分事件（约 beamOn/nThreads）；
> 要全量，轨迹用途的宏里固定写 `/run/numberOfThreads 1`（唯一 worker 必然当选）。
> serial 模式下没有 worker 线程、不会输出。

上限是代码内**硬编码**的两个常量（都在 `R4RunAction.cc`，需要时改后重编译）：
- `kMaxRecordEvents`：最多记录**完整事件**数（0=不限，默认不限）；
- `kMaxTrajPoints`：Traj.csv 总点数上限（默认约 5000）。

截断发生在**事件/轨迹边界**，保证写出的每条轨迹完整（不会出现半截折线）。

### 数据模型：每个点一行，带分组键（单位：mm）

```
eventID, trackID, parentID, particle, step, x, y, z
```

- `step=0` 的一行是这条 track 的**起点（顶点）**；`step=1..N` 是每个 step 的终点；
- `parentID=0` ⇒ primary；次级粒子的 `parentID` 指向产生它的 trackID；
- 保留 `particle` 名称，仅用于读取端**按粒子类型上色**（"手册"配色表由读取端维护，
  求解器不产颜色）。

### 为什么只有位置 + 分组键，没有 vol / t / Ekin

重绘只关心一件事：**这条折线的几何形状与连接顺序**。

- 几何形状：由有序的 `(x,y,z)` 完全决定；
- 连接顺序：由 `(eventID, trackID, step)` 决定。

`vol / t / Ekin` 不参与折线拓扑，加进去对重绘没有意义；将来若确实需要，可在后处理
按 `(eventID, trackID, step)` 回查，或作为附加属性列补充，不会改变连接规则。

### 连接规则（读取端实现，按此保证不误连）

1. 按 `(eventID, trackID)` 分组 —— 一个组就是一条轨迹；
2. 组内按 `step` 升序排列；
3. 相邻两点相连成线段。

容易误连的三个坑（为什么必须有分组键）：

- 次级粒子在母粒子某步终点"诞生"，二者**坐标重合但 trackID 不同**，只靠位置/近邻
  连接就会串线 → 必须按 trackID 分组；
- 每个事件内 trackID 从 1 重新编号 → **分组键必须带 eventID**，只按 trackID 会把
  不同事件连在一起；
- 当前只采线程 1：其 eventID 从 0 重新计，且只覆盖该线程分到的部分事件 →
  需要完整事件号/全量数据时用 `/run/numberOfThreads 1`（线程 1 即唯一 worker）。
