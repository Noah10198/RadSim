#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 VTK 离屏渲染，并排对比三卷着色数据的实际可见范围 vs 包络盒。

三卷数据共用同一解析标量场 d = |pos-center|（radial 距离），因此各面板
之间唯一差异就是“采样点怎么放”：
  base    : 当前代码 origin = center-half+0.5s, dims = nbin  -> 着色凸包内缩半格
  A-pad   : 方案 A, np.pad(edge) 一圈, dims = n+2            -> 凸包外扩半格
  A-exact : 复制点放在包络盒两个面上, dims = n+1             -> 凸包正好 = 包络盒
每个面板都用灰色线框画出同一个 [center±half] 包络盒，直接看 # 颜色凸包
与线框的贴合情况。

输出: test/voxel_option_a_vtk.png
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import vtkmodules.all as vtk
except ImportError:
    print("本环境没有 VTK，无法渲染。")
    sys.exit(1)


def extents(n, h, c, mode):
    """(dims, origin) —— 与 ui/voxel_result_viewer.py 相同的公式约定。"""
    s = 2.0 * h / n
    if mode == "base":
        return n, c - h + 0.5 * s
    if mode == "A-pad":
        return n + 2, c - h - 0.5 * s
    return n + 1, c - h          # A-exact


def build_image(nxyz, origin, spacing, center):
    """构造 scalar = radial 距离的 vtkImageData（标量顺序 x 最快，同加载器）。"""
    nx, ny, nz = nxyz
    img = vtk.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    img.SetSpacing(spacing[0], spacing[1], spacing[2])
    img.SetOrigin(origin[0], origin[1], origin[2])

    arr = vtk.vtkFloatArray()
    arr.SetNumberOfComponents(1)
    arr.SetNumberOfTuples(nx * ny * nz)
    for iz in range(nz):
        z = origin[2] + iz * spacing[2]
        for iy in range(ny):
            y = origin[1] + iy * spacing[1]
            base = iz * (nx * ny) + iy * nx
            for ix in range(nx):
                x = origin[0] + ix * spacing[0]
                dx, dy, dz = x - center[0], y - center[1], z - center[2]
                arr.SetTuple1(base + ix, (dx * dx + dy * dy + dz * dz) ** 0.5)
    img.GetPointData().SetScalars(arr)
    return img


def make_volume(img, dmax):
    ctf = vtk.vtkColorTransferFunction()
    for v, rgb in ((0.0, (0.10, 0.25, 0.55)),
                   (dmax * 0.35, (0.15, 0.72, 0.68)),
                   (dmax * 0.70, (0.95, 0.72, 0.15)),
                   (dmax, (0.88, 0.12, 0.12))):
        ctf.AddRGBPoint(v, *rgb)
    otf = vtk.vtkPiecewiseFunction()
    for v, o in ((0.0, 0.08), (dmax * 0.3, 0.22),
                 (dmax * 0.65, 0.42), (dmax, 0.62)):
        otf.AddPoint(v, o)
    prop = vtk.vtkVolumeProperty()
    prop.SetColor(ctf)
    prop.SetScalarOpacity(otf)
    prop.ShadeOn()
    prop.SetInterpolationTypeToLinear()

    mapper = vtk.vtkFixedPointVolumeRayCastMapper()
    mapper.SetInputData(img)
    mapper.SetBlendModeToComposite()
    vol = vtk.vtkVolume()
    vol.SetMapper(mapper)
    vol.SetProperty(prop)
    return vol


def make_outline(center, half):
    cube = vtk.vtkCubeSource()
    cube.SetCenter(center[0], center[1], center[2])
    cube.SetXLength(2 * half[0])
    cube.SetYLength(2 * half[1])
    cube.SetZLength(2 * half[2])
    outl = vtk.vtkOutlineFilter()
    outl.SetInputConnection(cube.GetOutputPort())
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(outl.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(0.82, 0.84, 0.88)
    a.GetProperty().SetLineWidth(1.5)
    return a


def add_label(ren, text):
    t = vtk.vtkTextActor()
    t.SetInput(text)
    t.GetTextProperty().SetFontSize(26)
    t.GetTextProperty().SetColor(1, 1, 1)
    t.SetPosition(0.06, 0.90)
    ren.AddActor2D(t)


def main():
    nbin = [6, 5, 4]
    half = [12.0, 10.0, 8.0]
    center = [0.0, 0.0, 0.0]
    spacing = [2.0 * half[i] / nbin[i] for i in range(3)]

    modes = [
        ("base    (现状, 内缩半格)", "base"),
        ("A-pad   (补一圈, 外扩半格)", "A-pad"),
        ("A-exact (面复制, 正好铺满)", "A-exact"),
    ]
    dmax = (half[0] ** 2 + half[1] ** 2 + half[2] ** 2) ** 0.5

    ren_win = vtk.vtkRenderWindow()
    ren_win.SetOffScreenRendering(1)
    ren_win.SetSize(1500, 500)
    ren_win.SetMultiSamples(0)

    n = len(modes)
    for i, (label, mode) in enumerate(modes):
        x0, x1 = i / n, (i + 1) / n
        ren = vtk.vtkRenderer()
        ren.SetViewport(x0, 0.0, x1, 1.0)
        ren.SetBackground(0.075, 0.085, 0.105)

        dims = []
        origin = []
        for ax in range(3):
            d, o = extents(nbin[ax], half[ax], center[ax], mode)
            dims.append(d)
            origin.append(o)
        img = build_image(dims, origin, spacing, center)
        ren.AddVolume(make_volume(img, dmax))
        ren.AddActor(make_outline(center, half))
        add_label(ren, label)

        cam = ren.GetActiveCamera()
        cam.SetPosition(95.0, -80.0, 100.0)
        cam.SetFocalPoint(0, 0, 0)
        cam.SetViewUp(0, 0, 1)
        cam.ParallelProjectionOn()
        cam.SetParallelScale(34.0)
        ren_win.AddRenderer(ren)

    ren_win.Render()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "voxel_option_a_vtk.png")
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(ren_win)
    w2i.SetScale(1)
    w2i.Update()
    png = vtk.vtkPNGWriter()
    png.SetFileName(out)
    png.SetInputConnection(w2i.GetOutputPort())
    png.Write()
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
