"""particle_preview - small live schematics (QPainter 2D) shown on the right
side of each section in the particle-source dialog.

Four canvases: (1) particle, (2) energy spectrum (histogram / curve),
(3) source position & shape, (4) angular distribution. They are schematic
illustrations that update live with the config, not physically scaled.
"""

import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush, QFont, QPolygonF
from PyQt6.QtCore import QPointF

_GLYPH = {"gamma": "γ", "e-": "e⁻", "e+": "e⁺", "proton": "p⁺",
          "neutron": "n", "alpha": "α", "deuteron": "d", "triton": "t",
          "He3": "³He", "mu-": "μ⁻", "mu+": "μ⁺", "pi-": "π⁻",
          "pi+": "π⁺", "anti_proton": "p̄"}


class SchematicPane(QWidget):
    """section: 1 particle / 2 energy / 3 position / 4 angular."""

    def __init__(self, section: int, parent=None):
        super().__init__(parent)
        self._section = section
        self._cfg = None
        self._dark = False
        self.setMinimumWidth(188)
        self.setMinimumHeight(118)

    def set_dark(self, dark: bool):
        self._dark = dark
        self.update()

    def set_cfg(self, cfg):
        self._cfg = cfg
        self.update()

    # ---------- palette ----------

    def _pal(self):
        if self._dark:
            return {"bg": QColor("#171a24"), "line": QColor("#7fb3ff"),
                    "fill": QColor(79, 140, 255, 66), "dim": QColor("#8a8d9a"),
                    "txt": QColor("#cdd6f4"), "ok": QColor("#9fefb0")}
        return {"bg": QColor("#f1f4fa"), "line": QColor("#0067c0"),
                "fill": QColor(0, 103, 192, 40), "dim": QColor("#7a7f8c"),
                "txt": QColor("#2c2c2c"), "ok": QColor("#1e8a4c")}

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._pal()
        p.fillRect(self.rect(), c["bg"])
        if self._cfg is None:
            return
        if self._section == 1:
            self._draw_particle(p, c)
        elif self._section == 2:
            self._draw_energy(p, c)
        elif self._section == 3:
            self._draw_position(p, c)
        else:
            self._draw_angular(p, c)

    # ---------- helpers ----------

    @staticmethod
    def _text(p: QPainter, x: float, y: float, s: str, color, size=10,
              bold=False):
        f = QFont("Segoe UI", size)
        f.setBold(bold)
        p.setFont(f)
        p.setPen(QPen(color))
        p.drawText(int(x), int(y), s)

    @staticmethod
    def _seg(p: QPainter, x1: float, y1: float, x2: float, y2: float):
        """Draw with float coordinates: drawLine only takes int/QPoint*
        overloads, so route everything through QPointF."""
        p.drawLine(QPointF(float(x1), float(y1)),
                   QPointF(float(x2), float(y2)))

    # ---------- 1. Particle ----------

    def _draw_particle(self, p, c):
        w, h = self.width(), self.height()
        cx, cy = w * 0.5, h * 0.48
        part = (self._cfg.get("particle") or {})
        if part.get("kind") == "ion":
            p.setBrush(c["fill"])
            p.setPen(QPen(c["line"], 1.6))
            p.drawEllipse(QPointF(cx, cy), 30, 30)
            self._text(p, cx - 16, cy + 5, "ion", c["txt"], 12, True)
            self._text(p, cx + 40, cy - 6,
                       f"Z={part.get('z', 26)}  A={part.get('a', 56)}",
                       c["dim"], 9)
            self._text(p, cx + 40, cy + 6,
                       f"Q={part.get('q', 0)}  E*={part.get('e', 0)}keV",
                       c["dim"], 9)
            return
        name = part.get("name", "gamma")
        glyph = _GLYPH.get(name, name)
        # Atom icon + central particle
        p.setPen(QPen(c["line"], 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r in (26, 18):
            p.drawEllipse(QPointF(cx - 8, cy - 8), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["fill"])
        p.drawEllipse(QPointF(cx - 8, cy - 8), 8, 8)
        p.setBrush(QBrush(c["line"]))
        p.drawEllipse(QPointF(cx + 28, cy - 22), 4, 4)
        p.drawEllipse(QPointF(cx - 34, cy + 12), 3, 3)
        p.setPen(QPen(c["line"], 1))
        p.drawLine(QPointF(cx - 8, cy - 8), QPointF(cx + 24, cy - 18))
        p.drawLine(QPointF(cx - 8, cy - 8), QPointF(cx - 31, cy + 9))
        self._text(p, cx + 36, cy + 34, name, c["txt"], 11, True)
        self._text(p, int(cx - 34), int(cy + 34), "GPS", c["dim"], 9)

    # ---------- 2. Energy spectrum ----------

    def _draw_energy(self, p, c):
        w, h = self.width(), self.height()
        en = self._cfg.get("energy") or {}
        t = en.get("type", "Lin")
        L, R, T, B = 26, w - 6, 14, h - 20
        # Energy range
        mono = en.get("e_mono", 1)
        if t == "Mono":
            lo, hi = mono * 0.6, mono * 1.4
        elif t == "Gauss":
            sgm = en.get("e_sigma", 0.1)
            lo, hi = mono - 4 * sgm, mono + 4 * sgm
        elif t == "Exp":
            e0 = en.get("ezero", 1) or 1
            lo, hi = 0.0, 5 * e0
        elif t == "User":
            _d = en.get("data") or []
            if _d:
                es = [float(x[0]) for x in _d]
                lo, hi = min(es), max(es)
            else:
                lo, hi = 0.0, 1.0
        else:
            lo = en.get("e_min", 0)
            hi = en.get("e_max", 10) or 10
        if hi <= lo:
            hi = lo + 1
        lo, hi = float(lo), float(hi)

        def fx(x):
            return L + (x - lo) / (hi - lo) * (R - L)

        p.setPen(QPen(c["dim"], 1))
        self._seg(p, L, B, R, B)
        self._seg(p, L, T, L, B)

        if t == "Mono":
            # Mono = one point on the axis + a short spike with arrowhead
            # (avoid a full-height vertical bar)
            x = fx(mono)
            p.setPen(QPen(c["line"], 1.8))
            self._seg(p, x, B, x, T - 26)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["line"])
            tri = QPolygonF([QPointF(x - 4, T - 26),
                             QPointF(x + 4, T - 26), QPointF(x, T - 14)])
            p.drawPolygon(tri)
            p.setBrush(QBrush(c["line"]))
            p.drawEllipse(QPointF(x, B - 1), 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            self._text(p, max(6, int(x) - 44), T + 8, f"Mono {mono:g} MeV",
                       c["txt"], 9)
            self._text(p, max(4, L - 8), B + 13, f"{lo:g}", c["dim"], 8)
            self._text(p, max(4, R - 30), B + 13, f"{hi:g}", c["dim"], 8)
            return

        if t == "User":
            data = [[float(a), float(b)]
                    for a, b in (en.get("data") or []) if b > 0]
            self._text(p, L, T - 3, "User spectrum", c["txt"], 10, True)
            if not data:
                self._text(p, L, T + 11, "(no data imported)", c["dim"], 9)
                return
            wmax = max(b for _a, b in data) or 1.0

            def fy(v):
                return B - (v / wmax) * (B - T - 12)

            xs = [fx(a) for a, _b in data]
            if len(xs) > 1:
                step = min(xs[i + 1] - xs[i] for i in range(len(xs) - 1))
            else:
                step = (R - L) * 0.03
            bw = max(1.4, step * 0.72)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["fill"])
            for xx, (_a, b) in zip(xs, data):
                y0 = fy(b)
                p.drawRect(int(xx - bw / 2), int(y0),
                           max(1, int(bw)), max(1, int(B - y0)))
            pts = QPolygonF([QPointF(xx, fy(b))
                             for xx, (_a, b) in zip(xs, data)])
            p.setPen(QPen(c["line"], 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(pts)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["ok"])
            for xx in xs:
                p.drawEllipse(QPointF(xx, B - 1), 1.6, 1.6)
            p.setBrush(Qt.BrushStyle.NoBrush)
            self._text(p, max(4, L - 8), B + 13, f"{lo:g}", c["dim"], 8)
            self._text(p, max(4, R - 44), B + 13, f"{hi:g}", c["dim"], 8)
            self._text(p, L, T + 9, f"{len(data)} bins (weights sketchy)",
                       c["dim"], 8)
            return

        def fy(y):
            return B - (y / 1.1) * (B - T)

        pts = []
        ymax = 0.0
        vals = []
        for i in range(81):
            x = lo + (hi - lo) * i / 80
            if t == "Lin":
                g = en.get("gradient", 1)
                v = en.get("intercept", 0) + g * (x - lo)
            elif t == "Gauss":
                sgm = en.get("e_sigma", 0.1) or 0.1
                v = math.exp(-((x - mono) ** 2) / (2 * sgm * sgm))
            elif t == "Pow":
                a = en.get("alpha", 1)
                v = (max(x, lo) / hi) ** a
            elif t == "Exp":
                e0 = en.get("ezero", 1) or 1
                v = math.exp(-x / e0)
            else:
                v = 1.0
            v = max(v, 0.0)
            vals.append(v)
            ymax = max(ymax, v)
        for i, x in enumerate([lo + (hi - lo) * i / 80 for i in range(81)]):
            v = vals[i] / ymax if ymax > 0 else 0
            pts.append(QPointF(fx(x), fy(v)))
        if not pts:
            return
        p.setPen(QPen(c["line"], 1.6))
        p.setBrush(c["fill"])
        poly = QPolygonF(pts)
        poly.append(QPointF(R, B))
        poly.append(QPointF(L, B))
        p.drawPolygon(poly)
        p.setBrush(Qt.BrushStyle.NoBrush)
        self._text(p, L - 8, B + 13, f"{lo:g}", c["dim"], 8)
        self._text(p, R - 34, B + 13, f"{hi:g}", c["dim"], 8)
        self._text(p, L, T, t, c["txt"], 10, True)
        self._text(p, L + 34, T, "curve sketch", c["dim"], 9)

    # ---------- 3. Source position ----------

    def _draw_position(self, p, c):
        w, h = self.width(), self.height()
        ps = self._cfg.get("position") or {}
        ptype = ps.get("type", "Point")
        shape = ps.get("shape", "")
        cx, cy = w * 0.42, h * 0.5
        # Display size helper (schematic, not to scale)
        def mm(v, fallback=30.0):
            return float(v) if v is not None else fallback

        if ptype == "Point":
            p.setPen(QPen(c["line"], 1.4))
            for r in (18, 9):
                p.drawEllipse(QPointF(cx, cy), r, r)
            p.drawLine(QPointF(cx - 26, cy), QPointF(cx - 13, cy))
            p.drawLine(QPointF(cx + 13, cy), QPointF(cx + 26, cy))
            self._text(p, int(cx - 18), int(cy + 36), "Point", c["txt"], 10, True)
            self._text(p, int(cx + 32), int(cy + 36),
                       "center only", c["dim"], 9)
            return
        # Display extents (projected, schematic)
        hx = max(mm(ps.get("halfx"), 20), 8)
        hy = max(mm(ps.get("halfy"), 20), 8)
        hz = max(mm(ps.get("halfz"), 20), 8)
        r = max(mm(ps.get("radius"), 20), 8)
        scale = 1.7
        p.setBrush(c["fill"])
        p.setPen(QPen(c["line"], 1.4))
        if shape == "Circle":
            p.drawEllipse(QPointF(cx, cy), r * scale, r * scale)
            self._text(p, int(cx + r * scale + 8), int(cy - 4), "Circle",
                       c["txt"], 10, True)
        elif shape == "Annulus":
            p.drawEllipse(QPointF(cx, cy), r * scale, r * scale)
            ir = max(mm(ps.get("inner_radius"), 8), 2)
            p.drawEllipse(QPointF(cx, cy), ir * scale, ir * scale)
            self._text(p, int(cx + r * scale + 8), int(cy - 4), "Annulus",
                       c["txt"], 10, True)
        elif shape in ("Ellipse", "Ellipsoid", "Cylinder"):
            rx, ry = hx * scale, (hy if shape == "Ellipse" else hz) * scale
            p.drawEllipse(QPointF(cx, cy), rx, ry)
            self._text(p, int(cx + rx + 8), int(cy - 4), shape, c["txt"],
                       10, True)
        elif shape == "Sphere":
            p.drawEllipse(QPointF(cx, cy), r * scale, r * scale)
            p.setPen(QPen(c["dim"], 1, Qt.PenStyle.DashLine))
            p.drawEllipse(QPointF(cx, cy), r * scale * 0.7, r * scale * 0.7)
            self._text(p, int(cx + r * scale + 8), int(cy - 4), "Sphere",
                       c["txt"], 10, True)
        elif shape == "Square":
            p.drawRect(int(cx - hx * scale), int(cy - hy * scale),
                       int(hx * 2 * scale), int(hy * 2 * scale))
            self._text(p, int(cx + hx * scale + 8), int(cy - 4), "Square",
                       c["txt"], 10, True)
        elif shape == "Rectangle":
            p.drawRect(int(cx - hx * scale), int(cy - hy * scale),
                       int(hx * 2 * scale), int(hy * 2 * scale))
            self._text(p, int(cx + hx * scale + 8), int(cy - 4),
                       "Rectangle", c["txt"], 10, True)
        elif shape == "Para":
            pts = QPolygonF([QPointF(cx - hx * scale, cy + hy * scale),
                             QPointF(cx + hx * scale, cy + hy * scale),
                             QPointF(cx + hx * scale + 12, cy - hy * scale),
                             QPointF(cx - hx * scale + 12, cy - hy * scale)])
            p.drawPolygon(pts)
            self._text(p, int(cx + hx * scale + 22), int(cy - 4), "Para",
                       c["txt"], 10, True)
        # Start-point sampling sketch: in-plane / on-surface / in-volume
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["ok"])

        def mark(x, y):
            p.drawEllipse(QPointF(x, y), 1.7, 1.7)

        def loop_pts(a0, a1, rr, n=8):
            return [(cx + rr * math.cos(a), cy - rr * math.sin(a))
                    for a in [a0 + (a1 - a0) * i / (n - 1) for i in range(n)]]

        if ptype == "Plane":
            if shape == "Circle":
                for a in (45, 135, 225, 315):
                    a = math.radians(a)
                    mark(cx + 0.55 * r * scale * math.cos(a),
                         cy + 0.55 * r * scale * math.sin(a))
            elif shape == "Annulus":
                ir = max(mm(ps.get("inner_radius"), 8), 2)
                for a in (45, 135, 225, 315):
                    a = math.radians(a)
                    rr = (r + ir) / 2 * scale
                    mark(cx + rr * math.cos(a), cy + rr * math.sin(a))
            elif shape == "Ellipse":
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        mark(cx + 0.5 * hx * scale * sx,
                             cy + 0.5 * hy * scale * sy)
            elif shape in ("Square", "Rectangle", "Para"):
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        mark(cx + 0.4 * hx * scale * sx,
                             cy + 0.4 * hy * scale * sy)
            mark(cx, cy)
        elif ptype in ("Surface", "Volume"):
            if shape == "Sphere":
                rr = (r if ptype == "Surface" else 0.5 * r) * scale
                for a in loop_pts(0.0, math.tau, rr):
                    mark(*a)
            elif shape in ("Ellipsoid", "Cylinder"):
                rx, ry = hx * scale, hz * scale
                if ptype == "Surface":
                    for a in (0, 90, 180, 270, 45, 135, 225, 315):
                        a = math.radians(a)
                        mark(cx + rx * math.cos(a), cy - ry * math.sin(a))
                else:
                    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                        mark(cx + 0.5 * rx * sx, cy + 0.5 * ry * sy)
                    mark(cx, cy)
            else:
                mark(cx, cy)
            # Surface closed solids: one outward-normal arrow as an example
            if ptype == "Surface" and shape in (
                    "Sphere", "Ellipsoid", "Cylinder"):
                d = (r if shape == "Sphere" else hx) * scale
                ux, uy = 0.7071, -0.7071
                x0, y0 = cx + d * ux, cy + d * uy
                x1, y1 = x0 + 15 * ux, y0 + 15 * uy
                p.setPen(QPen(c["ok"], 2))
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
                for k in (-1, 1):
                    p.drawLine(QPointF(x1, y1),
                               QPointF(x1 - 7 * ux + 3.4 * uy * k,
                                       y1 - 7 * uy - 3.4 * ux * k))
                p.setPen(QPen(c["dim"], 1))
                self._text(p, int(x1 + 4), int(y1 + 3), "outward normal",
                           c["ok"], 8)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Center mark + captions
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c["line"])
        p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        s = position_footnote(ps, ptype, shape)
        p.setPen(QPen(c["dim"], 1, Qt.PenStyle.DotLine))
        p.drawLine(4, int(h) - 4, int(w) - 4, int(h) - 4)
        self._text(p, 6, int(h) - 7, s, c["dim"], 8)
        # Position-type caption
        region = {"Plane": "points in the plane",
                  "Surface": "points on the surface",
                  "Volume": "points in the volume"}.get(ptype, ptype)
        self._text(p, 6, 14, f"{ptype} / {shape}", c["txt"], 10, True)
        self._text(p, 6, 27, "center " + _xyz(ps), c["dim"], 8)
        self._text(p, 6, 40, f"Start: {region} (direction: see Angular)",
                   c["ok"], 8)

    # ---------- 4. Angular distribution ----------

    def _draw_angular(self, p, c):
        w, h = self.width(), self.height()
        an = self._cfg.get("angular") or {}
        t = an.get("type", "iso")
        cx, cy = w * 0.42, h * 0.52

        def ray(angle, r, col=c["ok"]):
            p.setPen(QPen(col, 1.5))
            p.drawLine(QPointF(cx, cy), QPointF(cx + r * math.cos(angle),
                                                cy - r * math.sin(angle)))
            # arrowhead
            a2 = angle + math.pi - 0.45
            ax, ay = cx + (r - 6) * math.cos(angle), cy - (r - 6) * math.sin(angle)
            p.drawLine(QPointF(ax, ay),
                       QPointF(ax + 5 * math.cos(a2), ay - 5 * math.sin(a2)))

        p.setPen(QPen(c["line"], 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if t == "iso":
            p.drawEllipse(QPointF(cx, cy), 34, 34)
            for i in range(8):
                ray(2 * math.pi * i / 8, 34)
            self._text(p, int(cx - 46), int(cy + 46), "iso 4π isotropic",
                       c["txt"], 10, True)
            self._text(p, int(cx - 46), int(cy + 58),
                       "θ=0 → -Z (default frame)", c["dim"], 8)
        elif t in ("cos", "planar"):
            p.drawArc(int(cx - 40), int(cy - 40), 80, 80, 0 * 16,
                      -180 * 16)
            for i in range(6):
                a = math.pi * (0.02 + 0.155 * i)
                ray(math.pi - a, 34)
            self._text(p, int(cx - 46), int(cy + 46), f"{t} hemisphere",
                       c["txt"], 10, True)
            ps_ = self._cfg.get("position") or {}
            surf = ps_.get("type") == "Surface" and ps_.get("shape") in (
                "Sphere", "Ellipsoid", "Cylinder")
            if surf and t == "cos":
                sub = "Surface+cos: along outward surface normal"
            elif t == "cos":
                sub = "cosine relative to θ=0 → -Z"
            else:
                sub = "planar: along reference (θ=0 → -Z)"
            self._text(p, int(cx - 46), int(cy + 58), sub, c["dim"], 8)
        elif t in ("beam1d", "beam2d"):
            sgm = an.get("sigma_r", an.get("sigma_x", 1)) or 1
            half = min(0.32, 0.03 * float(sgm) + 0.12)
            p.drawArc(int(cx - 46), int(cy - 46), 92, 92, 0 * 16, -180 * 16)
            for k in (-1, 0, 1):
                a = math.pi / 2 + k * half
                ray(math.pi - a * 1.4, 40 if k == 0 else 32)
            self._text(p, int(cx - 60), int(cy + 46), f"{t} narrow beam",
                       c["txt"], 10, True)
            self._text(p, int(cx - 60), int(cy + 58),
                       f"σ={sgm:g}°", c["dim"], 8)
        elif t == "focused":
            fx = w * 0.86
            p.setPen(QPen(c["line"], 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(cx, cy), QPointF(fx, cy))
            for yy in (-24, -12, 0, 12, 24):
                ray(math.atan2(-yy, fx - cx) if yy else 0.0, 44)
                p.setPen(QPen(c["ok"], 1.5))
                p.drawLine(QPointF(cx, cy), QPointF(fx, cy + yy))
                p.setPen(QPen(c["line"], 1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c["ok"])
            p.drawEllipse(QPointF(fx, cy), 4, 4)
            self._text(p, int(fx) - 40, int(cy) + 22, "focus point", c["txt"], 10)
            self._text(p, 6, 14, f"focused {_xyz(an, 'f')}", c["dim"], 8)
        p.setPen(QPen(c["line"], 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 2, 2)


def _xyz(d, pfx="c"):
    return (f"({d.get(pfx + 'x', 0):g},{d.get(pfx + 'y', 0):g},"
            f"{d.get(pfx + 'z', 0):g})")


def position_footnote(ps, ptype, shape):
    """One-line footnote at the bottom of the position schematic:
    half-widths / radius etc. (mm)."""
    from ui.dialogs import gps_source as g
    if ptype == "Point":
        return ""
    parts = []
    for key, _lbl, _u in g.SHAPE_FIELDS.get(shape, []):
        if key in ps and ps[key]:
            parts.append(f"{key}={ps[key]:g}mm")
    return "  ".join(parts)
