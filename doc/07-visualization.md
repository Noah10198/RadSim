# 07 · 可视化

> 源码：`vtk_engine/vtk_scene.py`、`vtk_engine/vtk_solid_factory.py`、`ui/vtk_widget.py`、
> `ui/vtk_view_window.py`、`ui/voxel_result_viewer.py`、`ui/trajectory_viewer.py`、
> `ui/probe_chart_dialog.py`

## 1. 组成

| 组件 | 作用 |
|---|---|
| `VtkScene` | 场景容器：渲染器、actor 树、拾取、相机 |
| `VtkSolidFactory` | `GdmlNode` → `vtkPolyData` / `vtkActor`（单例 + 几何缓存） |
| `VtkWidget` | 3D 视图控件：QVTK 交互器 + 工具栏 + 裁剪面板 |
| `VtkPreviewWidget` | 轻量派生版，只保留视口，供对话框内预览 |
| `VoxelResultViewer` | 体素结果 3D 体渲染 |
| `TrajectoryViewerDialog` | 粒子轨迹折线查看 |
| `ProbeResultChartDialog` | 柱状图与能谱阶梯曲线 |

## 2. VtkScene

公开 API：`build_from_tree`、`clear`、`add_node`、`remove_node`、`set_visible`、
`highlight`、`reset_camera`、`fit_all`、`set_interactor`、`set_override_provider`。

**放置累加规则**：工厂只产出局部坐标系几何，位置/旋转由 `_apply_node_placement()`
沿父链累加后写到 actor 上：

- `PHYVOL_NODE` 累加 `placement`（可被 override provider 覆盖）；
- `GDML_FILE` 累加 `file_transform`，但 **`WORLD_NODE` 本身被排除**（世界盒固定不动）；
- 旋转取负：GDML 是被动（frame）约定，VTK `SetOrientation` 是主动旋转，故
  `SetOrientation(-rx, -ry, -rz)`。

**拾取**：内部 `vtkCellPicker` + 左键观察者 → `VtkWidget.node_picked(str)` →
主窗口定位树节点；反向「树选中 → 3D 高亮」走 `highlight()`，构成双向联动。

## 3. VtkSolidFactory

| GDML tag | 构造方式 | 备注 |
|---|---|---|
| `box` | `vtkCubeSource` | |
| `sphere` / `orb` | `vtkSphereSource`（Theta/Phi = 48） | **`rmin > 0` 空心球未实现** |
| `tube` / `tubs` | `rmin <= 0` → `vtkCylinderSource`；否则手工网格（内外壁 + 端盖） | 端盖仅全 360° 时生成 |
| `cone` | 上下半径相同则委托 tube；否则 16 段圆台近似合并 | 内半径未参与 |
| `torus` | `vtkParametricTorus`，`rmin > 0` 时布尔 Difference | 唯一用布尔运算 |
| `ellipsoid` | 单位球 + `vtkTransform.Scale` | `zcut` 未使用 |
| `tessellated` | 直接建 `vtkPolyData`（quad 拆两个三角） | vertices 为空则返回空 |
| `polycone` / `genericPolycone` | 按 zplane 逐段生成并合并 | 不用布尔运算 |

不支持的 tag（`trap`、`trd`、`para`、`hype`、`polyhedra`、`xtru`、`arb8`、`cutTube` 等）
→ `_build_polydata` 返回 `None` → **静默跳过**，导入时由主窗口统计并提示一次。

**几何缓存**：`_geometry_cache` 让同一源 volume 的多个实例共享 polydata + mapper；
键由 tag 与 `solid_params` 组成（浮点 6 位小数）；`clear_cache()` 在每次全量重建前调用。

**颜色**：`color_key = entry_id or name` → md5 前 4 位对 20 色调色板取模，
稳定且与材质名无关（`_COLORS` 里的材质预设表是遗留代码，未接入）。
`WORLD_NODE` 用 `Opacity 0.15` + 线框。

## 4. VtkWidget

按钮：▣ Transparency/Solid、✕ Edges、✂ Clip、⌂ Fit、◻ Ortho/Perspective、X/Y/Z 视图。
另有 `vtkCubeAxesActor` 做坐标轴与尺寸标注。

### WId 重绑（关键机制）

legacy `QVTKRenderWindowInteractor` 在 hide/show 后会重建原生窗口，WId 变化而
`vtkRenderWindow` 仍绑旧 HWND/HDC，表现为满屏 `wglMakeCurrent failed`。
`_ensure_window_bound()` 的流程：

1. 取当前 `winId()`，与 `_bound_wid` 相同则返回；
2. 若之前绑过（`_bound_once`），先 `Finalize()` 释放旧上下文；
3. `SetWindowInfo(str(wid))` 让 VTK 为新 HWND 重建上下文；
4. 重新 `SetSwapControl(0)`（新上下文会重置 vsync）。

`_maybe_start_interactor()` 保证 `Start()` 只执行一次且延迟到首次 show 之后。

### GL 初始化与软件回退

- `SetMultiSamples(0)` 关 MSAA；
- 先尝试 GPU（`SetOffScreenRendering(False)`），解析 `ReportCapabilities()` 确认真的
  拿到硬件 OpenGL，失败则回退 `SetOffScreenRendering(True)`（软件/Mesa）；
- `SetSwapControl(0)` 关 vsync：几十万三角面离屏只要几毫秒，开 vsync 反而被拉到
  16.7 ms/帧，拖拽卡顿。

### 交互现状

- 旋转/平移/缩放：`vtkInteractorStyleTrackballCamera`；
- 拾取：单击选中；
- **框选（rubber band）与右键上下文菜单未实现**；
- 裁剪用 `_mapper_addr(m)`（`GetAddressAsString`）按 mapper 去重，而不是 `id(m)`——
  VTK Python 不保证一个 C++ mapper 只有一个 wrapper。

## 5. 体素结果查看器

- **解析**：CSV 行 `iX,iY,iZ,value[,val2,entry]`，取 `parts[3]`；文件里 iZ 变化最快，
  存数组时按 `idx = ix + nx*(iy + ny*iz)` 重排；
- **网格**：`spacing = 2*half/nbin`，`origin = center - half`（mm）；
  `_edge_boundary_lattice` 把逐 cell 数据重采样到 `(nbin+1)³` 边界格点，
  使体渲染范围正好覆盖 `center ± half`；
- **渲染**：`vtkImageData` + `vtkFixedPointVolumeRayCastMapper` + `vtkVolume`，
  线性插值、不光照；5 停靠点蓝→青→绿→黄→红色标；
- **可调**：Opacity 滑块（10–100，默认 95）、Clip 切片、Fit/Ortho/XYZ 视图；
- **背景几何**：`set_geometry_ghost(True, wireframe=True)`，中性色线框、`LineWidth 2.0`；
- **重跑刷新**：`refresh_if_changed()` 用 `(mtime_ns, size)` 判断是否需要重载；
- `WA_DeleteOnClose = True`：避免缓存隐藏窗口复用陈旧 HWND/HDC。

## 6. 轨迹查看器

- **解析**：`csv.DictReader`，必需列 `eventID, trackID, parentID, particle, step, x, y, z`；
  按 `(event, track)` 分组，组内按 `step` 升序排序，step 0 即顶点；
- **连线**：**每条 track 一条 `vtkPolyLine`**（不跨 event 串接），粒子类型写入
  cell data，mapper 用 `SetScalarModeToUseCellData()` + lookup table 着色；
- **配色**：Geant4 `TrajectoryDrawByParticleID` 默认色（gamma 绿 / e- 红 / e+ 蓝 /
  π± 品红 / proton 青 / neutron 黄 / 离子橙 / 其他灰），两种主题下轨迹颜色相同；
- **筛选**：event / track / parent 三个区间 + 粒子复选框，点 **Apply Filter** 才生效，
  **Show All** 重置；**没有播放动画功能**。

## 7. 曲线对话框

- `group["kind"] == "quantity"` → 柱状图，8 色循环，柱顶标数值（`%.6g` 或 `%.3e`）；
- `group["kind"] == "histogram"` → `ax.step(..., where="post")` 阶梯曲线，带 legend；
- 归一化（`% of total counts`）与对数 x 轴两个复选框，改动即重绘；
- **导出 PNG**（`dpi=150`，按画布像素设 `figsize`）；
- matplotlib 缺失时：画布退化为 `QLabel` 提示 `pip install matplotlib`，
  归一化/对数/导出控件不创建，`_replot()` / `_save_png()` 直接返回，不抛异常。

## 8. 注意事项

| 项 | 说明 |
|---|---|
| GL 上下文 | 主窗口关闭时必须**先关所有次级 QVTK 窗口**，再销毁主窗口，否则日志被 `wglMakeCurrent failed` 刷屏 |
| 场景重建 | `VtkWidget` 复用同一实例，重建时先 `clear_cache()` + `clear()` |
| 内存 | 体素场为 `(nbin+1)³` 双精度数组，`nbin` 过大时注意内存 |
| 线程 | 所有 VTK 操作必须在主线程 |
| 精度 | 球/柱/环的圆周分辨率固定 48，cone 固定 16 段 |
