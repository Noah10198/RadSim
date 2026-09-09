# 09 · 数据格式参考

> 所有文件格式均由本仓库代码实际读写，字段名以代码为准。

## 1. project.json

```json
{
  "format": "radsim-project",
  "version": 1,
  "gdml_paths": ["geometry/model.gdml"],
  "results_root": "D:/Project/Easy2Rad/RadSim/solver/runs",
  "tasks": [
    {
      "name": "Run_001",
      "analysis_type": "default",
      "gdml_files": ["geometry/model.gdml"],
      "calculate": {"n_threads": 8, "n_events": 10000},
      "particle": { "...": "见第 4 节" },
      "physics": { "...": "见第 5 节" },
      "analysis_config": { "...": "见 [05 文档](05-analysis.md)" }
    }
  ]
}
```

- `format` 兼容旧值 `3drad-project`；
- `gdml_paths` 在项目文件夹内为**相对路径**；
- 运行态字段（`status` / `progress` / `run_time` / `run_log`）不写入。

## 2. run.mac

分段结构见 [03 文档](03-mac-builder.md)。示例：

```
/control/saveHistory
/run/numberOfThreads 8
/run/verbose 1
/control/verbose 1
/event/verbose 0
/tracking/verbose 0
/rad4space/gdml/SetGDMLFile D:/geo/model.gdml
/rad4space/physics/SetPL FTFP_BERT
/rad4space/physics/SetGlobalCut 1.0 mm
/run/initialize
/gps/particle gamma
/gps/energy 1.0 MeV
/gps/position 0 0 0 cm
/gps/direction 0 0 1
/score/create/boxMesh Box
/score/mesh/boxSize 10 10 10 cm
/score/mesh/nBin 50 50 50
/score/mesh/translate/xyz 0 0 0 cm
/score/quantity/doseDeposit dose Gy
/score/close
/analysis/h1/create Box_dose Box_dose 100 0.0001 1.0 Gy
/score/fill1D 0 Box dose
/run/beamOn 10000
/score/dumpQuantityToFile Box dose out_Box_dose.csv
```

## 3. 结果 CSV

### 3.1 `out_<mesh>.csv`（realworld / probe）

```
# mesh name: P1
# primitive scorer name: q1
# i, i, i, total(value) [MeV], total(val^2), entry
0,0,0,1.234e-05,3.2e-11,10000
```

- 每个 `# primitive scorer name:` 起一个新块；
- 数据行取第 4 列（value）、第 6 列（entry）；
- 单位从 `total(value) [MeV]` 的方括号里回读，因此文件自描述。

### 3.2 `out_Box_<q>.csv`（voxel）

```
iX,iY,iZ,value[,val2,entry]
```

- 文件里 **iZ 变化最快**；查看器按 `idx = ix + nx*(iy + ny*iz)` 重排；
- 网格参数 `half` / `center` / `nbin` 从 `analysis_config["voxel"]` 取，不在文件里。

### 3.3 `rad4space_h1_<mesh>_<q>.csv`（一维直方图）

```
#title ...
#dimension 1
#axis edges 0.001 0.01 ... 1.0
#annotation ...
#bin_number 102
entries,Sw,Sw2,Sxw0,Sx2w0
10000,...
```

- 支持 `tools::histo::h1d` 文本 dump 与 legacy G4 的 `#axis fixed/log` 两种写法；
- 计数取每行第一个逗号前的字段；
- 轴类型由边界是否等差/等比推断；`rebin_log()` 用于修正「配置 log 但 dump 成 fixed」的构建。

### 3.4 `Traj.csv`

```
eventID,trackID,parentID,particle,step,x,y,z
```

- 查看器按 `(eventID, trackID)` 分组，组内按 `step` 升序连线；
- 多线程运行时只包含被选中 worker 的事件（见限制）。

### 3.5 `run.log`

求解器 stdout + stderr 合并（`MergedChannels`），二进制追加写入。
加载项目时用它判断任务是否成功：末尾不含 `error` / `fatal` / `abnormal` / `failed`
即视为完成。

## 4. 粒子源配置（`task.particle`）

```python
{
  "mode": "gun" | "gps" | "file",
  "particle": "gamma",
  "energy": 1.0, "energy_unit": "MeV",
  "position": [0, 0, 0],            # mm
  "direction": [0, 0, 1],
  "pos_type": "Point" | "Beam" | ...,
  "ang_type": "iso" | "cos" | "cone" | ...,
  "spectrum": {...},
  "macro_text": "...",              # mode == "file" 时原样写入
}
```

`mode == "file"` 时 `gps_source.macro_lines()` 直接返回 `macro_text`，不解析。

## 5. 物理配置（`task.physics`）

```python
{
  "physics_list": "FTFP_BERT",
  "add_hp": False, "add_rdm": False,
  "global_cut": 1.0,     # mm
  "max_step": 0.0,       # mm，0 表示不写该命令
}
```

生成的命令序列见 [03 文档第 4 节](03-mac-builder.md#4-物理与源复用对话框模块的宏生成器)。

## 6. 静态资源

| 文件 | 内容 |
|---|---|
| `data/element.xml` | 元素表：符号 → (Z, 原子量) |
| `data/nist.txt` | NIST 材料列表（`G4_` 前缀）与密度 |

## 7. QSettings 键

| 键 | 默认/探测 |
|---|---|
| `solver/executable` | 依次探测 `solver/rad4space/build/Release/rad4space.exe`、`build/rad4space.exe`、`rad4space.exe` |
| `solver/qt_bin_dir` | 求解器所需 Qt6 bin 目录；留空则用内置开发机路径 |
| `solver/results_root` | 默认 `solver/runs` |

## 8. 目录约定

```
solver/runs/<safe_task_name>/     # 草稿输出（所有项目共享）
<项目>/geometry/                  # 几何副本
<项目>/results/<safe_task_name>/  # 保存后的结果快照
```

`safe_task_name()` 把非 `[A-Za-z0-9_.\-]` 字符替换为 `_`。
