#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Demo: 读取 rad4space 生成的 Traj.csv, 重建粒子轨迹并用 VTK 交互显示
------------------------------------------------------------
数据来源（求解器端, 单位 mm）
    rad4space 在 run 结束由 master 写出的 Traj.csv, 每行一个轨迹点:
        eventID, trackID, parentID, particle, step, x, y, z
    其中 step=0 的行是该轨迹的起点(顶点); step=1..N 是每一步的终点。

为什么能安全连线(与 README 轨迹节一致)
    1. 一条轨迹 = 同一个 (eventID, trackID) 的所有行;
    2. 组内按 step 升序排列, 相邻两点连一条线段即可还原粒子真实路径;
    3. 次级粒子与母粒子在某点坐标重合, 但 trackID 不同, 分组后各连各的,
       不会串线; 事件之间 trackID 会重置, 所以分组键必须带 eventID。
    本例把"每条轨迹"做成 vtkPolyLine(一个 cell), 天然就是一条折线。

颜色
    按 Geant4 手册(Boo Application Developers 11.4, shouce.txt) 8.7 节
    G4TrajectoryDrawByParticleID 的默认配色:
        gamma=green, e-=red, e+=blue, pi+/-=magenta,
        proton=cyan, neutron=yellow, 其它=grey
    (手册 8.7 节另给出按电荷的默认模型 drawByCharge:
        positive=blue, negative=red, neutral=green)
    本脚本对"手册没列出的粒子"用灰色;
    离子/核碎片(alpha, deuteron, ... 以及形如 Fe56 的重离子)额外用橙色,
    避免与 e+(蓝)、proton(青) 混淆。
    实现上把"粒子名"转成整数序号作为 cell 标量, 再用 vtkLookupTable 映射颜色,
    右侧 vtkScalarBarActor 直接显示 粒子名 <-> 颜色。

交互
    左键拖拽旋转 / 滚轮缩放 / 中键平移 (vtkInteractorStyleTrackballCamera)

用法
    python plot_traj_vtk.py [csv路径] [--primary] [--event N] [--dry]
    csv路径缺省为 Traj.csv; 找不到时自动去脚本同级的 build/Release 找。
"""

import argparse
import csv
import os
import re
import sys

import vtk

# 手册配色表: 手册只列出这几种特殊粒子, 其余统一灰色
PARTICLE_COLOUR = {
    "gamma":   (0.0, 1.0, 0.0),   # green
    "e-":      (1.0, 0.0, 0.0),   # red
    "e+":      (0.0, 0.0, 1.0),   # blue
    "pi+":     (1.0, 0.0, 1.0),   # magenta
    "pi-":     (1.0, 0.0, 1.0),   # magenta
    "proton":  (0.0, 1.0, 1.0),   # cyan
    "neutron": (1.0, 1.0, 0.0),   # yellow
}
# 离子/核碎片的专属色 (橙), 与上面七色都不冲突
ION_COLOUR = (1.0, 0.55, 0.0)
OTHER_COLOUR = (0.6, 0.6, 0.6)    # grey

# 轻离子的 Geant4 粒子名(不含重离子: 重离子按名字形态 He3/Fe56 识别)
ION_NAMES = {"alpha", "deuteron", "triton", "He3", "GenericIon"}


def _is_ion_name(name):
    """判断粒子名是否为离子/核碎片。

    容忍 Geant4 可能给出的各种写法:
      Fe56, Fe56[0.0](激发态), anti_Fe56, alpha, deuteron, ...
    """
    n = name
    if n.startswith("anti_"):
        n = n[len("anti_"):]
    if "[" in n:                      # 去掉激发态标记, 如 Fe56[0.0]
        n = n[:n.index("[")]
    if n in ION_NAMES:
        return True
    # 形如 Fe56 / He4 / C12 / Li7 (元素符号+质量数)
    return bool(re.fullmatch(r"[A-Z][a-z]?[0-9]+", n))


def colour_for(particle):
    """返回粒子应使用的 RGB。

    优先级: 手册表 > 已知离子名 > 形如 "Fe56"/"Li7" 的重离子 > 灰色。
    """
    if particle in PARTICLE_COLOUR:
        return PARTICLE_COLOUR[particle]
    if _is_ion_name(particle):
        return ION_COLOUR
    return OTHER_COLOUR


def load_tracks(path, primary_only=False, event_only=None):
    """读 CSV 并按轨迹分组。

    返回 { (eventID, trackID): [(step, x, y, z, particle), ...], ... }
    - 支持两个可选过滤: 只看 primary(parentID=0), 只看某个事件;
    - 组内按 step 排序, 保证连线顺序与粒子真实运动方向一致。
    """
    tracks = {}
    with open(path, newline="") as f:
        # DictReader 用第一行做列名, 之后每行是 dict
        for row in csv.DictReader(f):
            if primary_only and row["parentID"].strip() != "0":
                continue
            if event_only is not None and int(row["eventID"]) != event_only:
                continue
            key = (int(row["eventID"]), int(row["trackID"]))
            tracks.setdefault(key, []).append(
                (int(row["step"]),
                 float(row["x"]), float(row["y"]), float(row["z"]),
                 row["particle"]))
    for key in tracks:
        # step 升序: step0(顶点)->step1->... 就是整条路径
        tracks[key].sort(key=lambda p: p[0])
    return tracks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="Traj.csv",
                    help="Traj.csv 路径(缺省在当前目录/脚本同级 build/Release 找)")
    ap.add_argument("--primary", action="store_true",
                    help="只看 primary (parentID=0)")
    ap.add_argument("--event", type=int, default=None,
                    help="只看某个 eventID")
    ap.add_argument("--dry", action="store_true",
                    help="只解析并打印统计, 不弹窗口")
    args = ap.parse_args()

    # ---- 定位文件: 当前目录找不到, 就去脚本同级的 build/Release 兜底 ----
    path = args.csv
    if not os.path.isfile(path) and args.csv == "Traj.csv":
        alt = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "build", "Release", "Traj.csv")
        if os.path.isfile(alt):
            path = alt
    if not os.path.isfile(path):
        sys.exit("找不到 Traj.csv: %s\n请用绝对路径指定, 例如 "
                 "python plot_traj_vtk.py D:/.../build/Release/Traj.csv"
                 % os.path.abspath(path))

    # ---- 解析分组: 得到 {轨迹: 有序点列} ----
    tracks = load_tracks(path, args.primary, args.event)
    if not tracks:
        print("没有可显示的轨迹, 请检查文件/过滤条件")
        sys.exit(1)

    npoints = sum(len(v) for v in tracks.values())
    if args.dry:   # 只打印概况, 方便快速验证数据, 不进入渲染
        print("events/tracks/points:",
              len({k[0] for k in tracks}), len(tracks), npoints)
        ptypes = sorted({p[-1] for v in tracks.values() for p in v})
        print("particles:", ptypes)
        return

    # =========================================================
    # 构建 vtkPolyData: 所有轨迹的所有点放进一个 vtkPoints;
    # 每条轨迹 = 一个 vtkPolyLine = 一条折线; 用 cell 数据记粒子序号。
    # =========================================================
    pts = vtk.vtkPoints()
    lines = vtk.vtkCellArray()
    cellType = vtk.vtkIntArray()
    cellType.SetName("particleType")

    # 出现的粒子名排序编号(便于建 lut 与图例)
    pnames = sorted({p[-1] for v in tracks.values() for p in v})
    pidx = {n: i for i, n in enumerate(pnames)}

    for key, plist in tracks.items():
        # 1) 先插入这条轨迹的所有点, 记下 point id 列表
        ids = []
        for (_step, x, y, z, pname) in plist:
            ids.append(pts.InsertNextPoint(x, y, z))
            cellType.InsertNextValue(pidx[pname])   # 每个 cell 一个粒子序号
        # 2) 用一个 vtkPolyLine 把这些有序点串成一条折线
        cell = vtk.vtkPolyLine()
        cell.GetPointIds().SetNumberOfIds(len(ids))
        for i, pid in enumerate(ids):
            cell.GetPointIds().SetId(i, pid)
        lines.InsertNextCell(cell)

    poly = vtk.vtkPolyData()
    poly.SetPoints(pts)
    poly.SetLines(lines)
    poly.GetCellData().SetScalars(cellType)

    # =========================================================
    # 颜色映射: 粒子序号 0..N-1 -> 手册配色 (vtkLookupTable)
    # 并给每个序号挂上粒子名注释, scalar bar 就能显示名称。
    # =========================================================
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(len(pnames))
    lut.SetRange(0, len(pnames) - 1)
    lut.Build()
    for i, name in enumerate(pnames):
        rgb = colour_for(name)
        lut.SetTableValue(i, rgb[0], rgb[1], rgb[2], 1.0)
        lut.SetAnnotation(i, name)

    # 把 cell 标量(粒子序号)按 lut 着色, 颜色精度取离散值
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    mapper.SetLookupTable(lut)
    mapper.SetScalarRange(0, len(pnames) - 1)
    mapper.SetScalarModeToUseCellData()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetLineWidth(1.2)
    actor.GetProperty().SetOpacity(0.8)   # 半透明, 叠线处不会刺眼

    # =========================================================
    # 右侧图例: vtkScalarBarActor 复用同一张 lut,
    # 显示 "颜色块 + 粒子名", 颜色保证和线一致。
    # =========================================================
    bar = vtk.vtkScalarBarActor()
    bar.SetLookupTable(lut)
    bar.SetTitle("particle")
    bar.DrawAnnotationsOn()
    bar.SetMaximumNumberOfColors(len(pnames))
    bar.SetNumberOfLabels(0)
    for tp in (bar.GetTitleTextProperty(),
               bar.GetLabelTextProperty(),
               bar.GetAnnotationTextProperty()):
        tp.SetColor(0.1, 0.1, 0.1)        # 白底上用深色文字

    # =========================================================
    # 渲染窗口与交互
    # =========================================================
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(1.0, 1.0, 1.0)   # 白色背景
    renderer.AddActor(actor)
    renderer.AddActor(bar)
    renderer.ResetCamera()                  # 自动取景把轨迹放进视野

    renWin = vtk.vtkRenderWindow()
    renWin.AddRenderer(renderer)
    renWin.SetSize(1100, 850)
    renWin.SetWindowName("rad4space Traj.csv (%d tracks, %d pts)"
                         % (len(tracks), npoints))

    # TrackballCamera: 左键旋转 / 滚轮缩放 / 中键平移
    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(renWin)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    renWin.Render()
    interactor.Start()   # 进入事件循环, 直到窗口关闭


if __name__ == "__main__":
    main()
