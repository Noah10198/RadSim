# 02 · GDML 处理链路

> 源码：`core/gdml_parser.py`、`core/gdml_tree.py`、`core/gdml_evaluator.py`、
> `core/gdml_writer.py`、`core/materials_lib.py`、`core/collision_detector.py`、`core/gdml_agent.py`

## 1. 链路总览

```
.gdml 文件
   │  GdmIParser.parse_file()
   ▼
GdmlNode 树（VOLUME_NODE 逻辑体积 + PHYVOL_NODE 放置实例 + SOLID_DEF）
   │  ├─ GdmIEvaluator  属性表达式求值
   │  ├─ VtkSolidFactory → VtkScene   3D 渲染
   │  └─ GdmlAgent      统一门面（单例）
   ▼
GdmlWriter.write()  →  合并 / 覆盖后的 .gdml（供求解器使用）
```

设计取向：**解析结果必须能无损回写**。因此每个节点除了结构化参数（`solid_params`），
还保留原始 XML 片段（`raw_solid_xml`、`raw_define_xml` 等），写回时优先复用原始文本，
只有被用户改过的地方才重新生成。这样 `polycone`、`xtru`、布尔运算等复杂实体也能
原样往返。

## 2. GdmIParser

### 解析流程

`GdmIParser.parse_file(filepath) -> GdmlNode`：

1. 解析 `<define>` → 收集常量（`constant`）、位置（`position`）、旋转（`rotation`）；
2. 解析 `<materials>` → 记录材料名与密度（MVP 简化）；
3. 解析 `<solids>` → 每个 solid 一个 `SOLID_DEF` 节点，参数折算为 **mm**；
4. 解析 `<structure>` → 每个 `<volume>` 一个 `VOLUME_NODE`（逻辑体积“仓库”），
   `<physvol>` 展开为 `PHYVOL_NODE` 放置实例；
5. 解析 `<setup>` → 记录 world 引用。

### 实体解析方法

| 方法 | GDML 标签 |
|---|---|
| `_parse_box` | `box` |
| `_parse_sphere` | `sphere` |
| `_parse_orb` | `orb` |
| `_parse_tube` | `tube` |
| `_parse_cone` | `cone`（G4Cons） |
| `_parse_torus` | `torus` |
| `_parse_ellipsoid` | `ellipsoid` |
| `_parse_polycone` | `polycone`（保留 `<zplane>` 原始 XML） |
| `_parse_tessellated` | `tessellated` |

其余实体类型不生成结构化参数，但会被记录并原样保留原始 XML，写回时照抄。

### 实例化语义（关键设计）

参照 Geant4 的两级模型：

- `VOLUME_NODE` = `G4LogicalVolume`，只存在于“仓库”里，**不被直接渲染**；
- `PHYVOL_NODE` = `G4PVPlacement`，`_clone_volume_instance()` / `_clone_physvol()`
  递归克隆整个子树，每个实例持有自己的 `Placement`。

因此同一逻辑体积被放置 N 次，树上就有 N 个独立实例，各自可以单独改位置、
单独显示/隐藏——这与 3D 视图里看到的结果一一对应。

`<assembly>` 由 `_parse_assembly()` 处理，节点类型为 `ASSEMBLY_NODE`。

### 容错

- 根节点不是 GDML 时抛 `ValueError`；
- XML 声明、常量求值、顶点缺失等异常静默降级，不中断整次导入；
- 不支持的实体类型只登记（`_unsupported_solids`），由
  `GdmlAgent.get_unsupported_solids()` 汇总给界面提示。

## 3. GdmlNode 与 Placement

`GdmlNode` 继承 `QObject`，带 `data_changed = pyqtSignal()`，是界面刷新的统一触发点。

| 属性 | 说明 |
|---|---|
| `node_type` | `GdmlNodeType` |
| `name` / `entry_id` | 名称与唯一标识（`GDM_xxx`，用于覆盖查找） |
| `gdml_tag` / `gdml_attrs` | 原始标签名与原始 XML 属性 |
| `solid_params` | 解析后的数值参数（**mm / deg**） |
| `material_name` | 材料名 |
| `placement` | `Placement`，仅 `PHYVOL_NODE` 有意义 |
| `file_transform` | `Placement`，仅 `GDML_FILE` 有意义，整文件平移/旋转 |
| `ref_name` | `volumeref` / `solidref` 的引用名 |
| `vtk_actor` / `visible` | 渲染对象与可见性 |
| `raw_*_xml` | 原始 XML 片段（声明 / define / materials / setup / solid） |
| `parent` / `children` | 树结构 |

`GdmlNodeType` 取值：`DONT_CARE`、`ROOT_NODE`、`GDML_FILE`、`DEFINE_NODE`、
`MATERIAL_NODE`、`SOLID_DEF`、`VOLUME_NODE`、`PHYVOL_NODE`、`ASSEMBLY_NODE`、
`WORLD_NODE`、`BOOLEAN_NODE`、`AUX_NODE`。
其中 `DEFINE_NODE` / `MATERIAL_NODE` / `BOOLEAN_NODE` / `AUX_NODE` 是预留值，
当前解析阶段不会产生。

`Placement` 是 dataclass：`x/y/z`（mm）、`rot_x/rot_y/rot_z`（deg）、`unit`、`rot_unit`。

树操作 API：`add_child` / `remove_child` / `get_child_count` / `is_leaf` /
`get_all_descendants` / `get_leaf_nodes` / `find_node_by_name`。

## 4. GdmIEvaluator

GDML 属性允许写成表达式，例如 `2.*pi`、`9825-DOFFSET`、`PCOLL2_THICK/2+5`。

- 预定义常量：`pi`、`PI`、`HALFPI`、`TWOPI`；
- 用户常量：`set_constant` / `set_constants`（来自 `<define>` 的 `constant`）；
- 支持四则运算、括号、负号；
- 求值时按**名称长度降序**替换，避免 `PI` 被 `HALFPI` 的子串规则误伤；
- 用 `eval(expr, {"__builtins__": {}}, math.__dict__)` 沙箱执行，禁用内建函数。

⚠️ **未定义的标识符会被替换为 `0`**，不抛异常。这让脏 GDML 也能导入，但会静默
掩盖引用错误——排查尺寸异常时，先怀疑这里。

## 5. GdmlWriter

```python
writer.write(root_node, placement_overrides, filepath, mat_lib=None)
```

| 机制 | 说明 |
|---|---|
| 单文件 / 多文件 | `_export_single` 处理一个 GDML 文件；`_export_multi` 合并多个文件为一个 GDML（收集各文件的 world、solid、define 后去重写出） |
| 放置覆盖 | `placement_overrides` 是 `entry_id → Placement` 的字典；`_get_effective()` 优先取覆盖值，被覆盖的 physvol 会带注释标记，方便人工核对 |
| 文件级变换 | 文件节点有 `file_transform` 时，用 `_wrap_world_volume()` 生成一个包裹世界体积来承载整体平移/旋转 |
| 去重 | `_used_names` / `_written_vols` / `_written_solids` 三个集合，避免重复写出同名 volume/solid |
| 本地材料注入 | `_append_local_materials()` 把用户自定义元素/化合物/混合物写进 `<materials>` |
| 单位声明 | 固定 `lunit="mm"`、`aunit="deg"`、position `unit="mm"`、rotation `unit="deg"` |
| 数值精度 | `_fmt()` 用 `f"{v:.6g}"`，6 位有效数字 |

> 注意：`GdmlWriter` 与 `MaterialsLib` 目前只在 `core/` 内部被引用，
> 界面层尚未接线，属于「已实现、待接入」的能力。

## 6. MaterialsLib

数据来源：

- `data/element.xml` → 元素库 `_ELEMENT_DB: symbol → (Z, atom_weight)`；
- `data/nist.txt` → NIST 材料列表（`G4_` 前缀）；
- 兜底：内置 7 种常用材料（`G4_AIR`、`G4_Al` …）与默认化合物（水）。

三类用户材料：

| 类别 | 类 | 表达方式 |
|---|---|---|
| 自定义元素 | `CustomElement` | 名称、符号、密度、原子量、原子序数 |
| 化合物 | `CompoundMaterial` + `CompoundItem` | 原子个数比 |
| 混合物 | `MixtureMaterial` + `MixtureItem` | 质量分数（归一化到 6 位小数） |

主要 API：`load_elements_from_xml`、`load_nist_from_file`、`get_atom_weight`、
`get_atomic_number`、`get_nist_list`、`get_nist_density`、`add_custom_element` /
`add_compound` / `add_mixture` 及对应的 `get_all_*` / `delete_*`、`generate_id()`。
所有类都实现了 `to_dict()` / `from_dict()`，便于序列化。

密度单位 **g/cm³**，原子量 **g/mole**。

## 7. CollisionDetector

`core/collision_detector.py` 提供基于 AABB（轴对齐包围盒）的粗筛：

| 函数 | 作用 |
|---|---|
| `compute_half_size(node)` | 由 `solid_params` 推算半尺寸 |
| `compute_world_aabb(node, ...)` | 用 VTK 变换矩阵把 8 个角点变换到世界坐标后求包围盒 |
| `compute_world_transform(node, override_provider=None)` | 沿父链累加平移与欧拉角，返回 `(tx,ty,tz,rx,ry,rz)` |
| `aabb_overlap(a, b)` | 盒盒相交判定 |
| `generate_full_pairs(nodes)` | 全组合两两配对 |
| `generate_sampled_pairs(nodes)` | 随机采样约 5%（下限 2、上限 50），多文件时保证至少一个跨文件配对 |

`GdmlAgent` 用它计算场景 / 体积 / 世界的包围盒。完整的两两碰撞检测尚未接入界面，
属于预留能力；`GdmlAgent._local_aabb` 里有一份等价的本地 AABB 逻辑，二者存在重复。

## 8. 单位与精度约定

| 项 | 约定 |
|---|---|
| 长度 | 内部统一 **mm**；解析时用 `_LENGTH_UNITS` 折算 cm/m/um/nm/km |
| 角度 | 统一 **deg**，rad 自动折算 |
| 写回 | 显式声明 `lunit="mm"`、`aunit="deg"` |
| 密度 | g/cm³ |
| 原子量 | g/mole |
| 数值输出 | 6 位有效数字；变更判定阈值 `1e-9`，旋转判定 `1e-6` |

## 9. 已知限制

- `<materials>` 只解析名称与密度，材料深层结构（元素组成）不参与解析；
- 表达式中的未定义标识符静默变 `0`；
- `GdmIEvaluator` 无结果缓存，高频调用会重复求值；
- `GdmlAgent` 复用同一个 `GdmIParser` 实例，而解析器带可变状态，
  `parse_file_only` 的线程安全仅在串行调用前提下成立（当前后台线程只有一路）；
- `get_all_descendants()` 每次递归全树，超大模型下注意调用次数。
