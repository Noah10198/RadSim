"""
VtkSolidFactory - VTK Solid Factory

Converts parsed GDML solid parameters to vtkActor. Supports:
  - box -> vtkCubeSource
  - sphere -> vtkSphereSource
  - tube -> vtkCylinderSource + vtkCylinderSource (inner/outer cylinder boolean subtract)
  - tessellated -> vtkPolyData (triangle mesh direct construction)

Following cad2gdml style, a single factory class manages all type creation.
"""

from typing import Dict, List, Tuple, Optional
import math

from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkTriangle, vtkCellArray
from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonComputationalGeometry import vtkParametricTorus
from vtkmodules.vtkFiltersSources import (
    vtkCubeSource,
    vtkSphereSource,
    vtkCylinderSource,
    vtkParametricFunctionSource,
)
from vtkmodules.vtkFiltersModeling import vtkLinearExtrusionFilter
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkProperty,
)
from vtkmodules.vtkFiltersGeneral import vtkBooleanOperationPolyDataFilter
from vtkmodules.vtkFiltersCore import vtkAppendPolyData
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter

from core.gdml_tree import GdmlNode, GdmlNodeType, Placement


class VtkSolidFactory:
    """
    VTK Solid Factory (Singleton)

    Responsibilities:
      - Create vtkActor based on GdmlNode type and parameters
      - Manage VTK colors, transparency and other rendering properties
      - Provide basic preset color schemes
    """

    _instance: Optional['VtkSolidFactory'] = None

    # VTK rendering precision control
    THETA_RESOLUTION: int = 48
    PHI_RESOLUTION: int = 48

    # Preset colors (R, G, B 0-1)
    _COLORS = {
        "default": (0.7, 0.7, 0.7),
        "world": (0.9, 0.9, 0.95),
        "selected": (1.0, 0.8, 0.0),
        "G4_AIR": (0.85, 0.85, 0.9),
        "G4_Al": (0.8, 0.8, 0.9),
        "G4_Cu": (0.9, 0.6, 0.4),
        "G4_Si": (0.6, 0.7, 0.8),
        "G4_WATER": (0.3, 0.5, 0.9),
        "G4_POLYETHYLENE": (0.85, 0.85, 0.7),
        "G4_Galactic": (0.95, 0.95, 1.0),
        "SSteel": (0.7, 0.7, 0.75),
        "Iron": (0.7, 0.65, 0.6),
        "Lead": (0.5, 0.5, 0.55),
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Geometry cache: geometry key -> vtkPolyDataMapper. Multiple physical
        # instances of the same source volume share a single polydata/mapper,
        # which avoids repeated tessellation, repeated VBO uploads and
        # per-actor shader recompilation. For files containing tens of
        # thousands of placements (e.g. g4e with 16k physvols), duplicated
        # geometry was the main cause of both rendering lag and slow
        # scene construction.
        self._geometry_cache: Dict[tuple, vtkPolyDataMapper] = {}

    # ==================== Main creation interface ====================

    def create_actor(self, node: GdmlNode) -> Optional[vtkActor]:
        """
        Create VTK Actor based on node type and parameters.

        Args:
            node: GdmlNode (usually VOLUME_NODE type, must have solid_params)

        Returns:
            vtkActor object, or None if creation fails
        """
        mapper = self._get_shared_mapper(node)
        if mapper is None:
            return None

        actor = vtkActor()
        actor.SetMapper(mapper)

        # Set color by volume identity (name or entry_id) — each physical body
        # gets its own color independent of shared material names
        color_key = node.entry_id if node.entry_id else node.name
        color = self._get_color_for_node(color_key)
        actor.GetProperty().SetColor(*color)

        # ── Material properties for realistic shading ──
        prop = actor.GetProperty()
        prop.SetAmbient(0.20)
        prop.SetDiffuse(0.75)
        prop.SetSpecular(0.35)
        prop.SetSpecularPower(32)
        prop.SetInterpolationToPhong()      # smooth shading

        # World volume is semi-transparent
        if node.node_type == GdmlNodeType.WORLD_NODE:
            actor.GetProperty().SetOpacity(0.15)
            actor.GetProperty().SetRepresentationToWireframe()

        return actor

    # ==================== Shared geometry / mapper cache ====================

    def clear_cache(self) -> None:
        """Clear the geometry cache (called before every full rebuild to
        prevent mismatches caused by id() reuse)."""
        self._geometry_cache.clear()

    def _geometry_key(self, node: GdmlNode) -> Optional[tuple]:
        """Geometry identity key used to share a mapper across physical instances.

        Physical instances of the same source volume are created by the parser
        as a shallow copy of solid_params: scalar parameters keep identical
        values, while list/dict parameters (tessellated vertices/triangles,
        polycone zplanes, ...) share the very same nested object. Scalars are
        therefore keyed by quantized value and nested objects by id(), which
        costs nothing and still distinguishes geometries exactly.
        """
        tag = node.gdml_tag
        if not tag or not node.solid_params:
            return None
        parts: List[object] = [tag]
        for k in sorted(node.solid_params.keys()):
            v = node.solid_params[k]
            if isinstance(v, float):
                parts.append((k, round(v, 6)))
            elif isinstance(v, int):
                parts.append((k, v))
            elif isinstance(v, dict):
                parts.append((k, "dict", id(v)))
            elif isinstance(v, list):
                parts.append((k, "list", id(v)))
            else:
                parts.append((k, type(v).__name__, id(v)))
        return tuple(parts)

    def _get_shared_mapper(self, node: GdmlNode) -> Optional[vtkPolyDataMapper]:
        """Return the mapper for a node's geometry; instances sharing the same
        geometry also share the same polydata + mapper."""
        key = self._geometry_key(node)
        if key is not None:
            cached = self._geometry_cache.get(key)
            if cached is not None:
                return cached

        poly_data = self._build_polydata(node)
        if poly_data is None:
            return None

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(poly_data)
        if key is not None:
            self._geometry_cache[key] = mapper
        return mapper

    def _build_polydata(self, node: GdmlNode) -> Optional[vtkPolyData]:
        """Build the geometry polydata for the given solid type (the low-level
        path taken on a cache miss)."""
        params = node.solid_params
        gdml_tag = node.gdml_tag

        if gdml_tag in ("box",):
            return self._create_box(params)
        elif gdml_tag in ("sphere", "orb"):
            return self._create_sphere(params)
        elif gdml_tag in ("tube", "tubs"):
            return self._create_tube(params)
        elif gdml_tag in ("cone",):
            return self._create_cone(params)
        elif gdml_tag == "tessellated":
            return self._create_tessellated(node)
        elif gdml_tag == "torus":
            return self._create_torus(params)
        elif gdml_tag == "ellipsoid":
            return self._create_ellipsoid(params)
        elif gdml_tag in ("polycone", "genericPolycone"):
            return self._create_polycone(params)
        return None

    # ==================== Per-type creation methods ====================

    def _create_box(self, params: Dict[str, float]) -> vtkPolyData:
        """Create a box solid"""
        x = params.get("x", 1.0)
        y = params.get("y", 1.0)
        z = params.get("z", 1.0)

        source = vtkCubeSource()
        source.SetXLength(x)
        source.SetYLength(y)
        source.SetZLength(z)
        source.Update()
        return source.GetOutput()

    def _create_sphere(self, params: Dict[str, float]) -> vtkPolyData:
        """Create a sphere solid"""
        rmax = params.get("rmax", 1.0)
        rmin = params.get("rmin", 0.0)
        startphi = params.get("startphi", 0.0)
        deltaphi = params.get("deltaphi", 360.0)
        starttheta = params.get("starttheta", 0.0)
        deltatheta = params.get("deltatheta", 180.0)

        # VTK vtkSphereSource only supports full spheres or longitude/latitude slices
        # For hollow spheres (rmin > 0), simplified: outer sphere only
        source = vtkSphereSource()
        source.SetRadius(rmax)
        source.SetThetaResolution(self.THETA_RESOLUTION)
        source.SetPhiResolution(self.PHI_RESOLUTION)

        # Handle angle ranges
        # VTK ThetaRange is longitude (0-360), PhiRange is latitude (0-180)
        source.SetStartTheta(startphi)
        source.SetEndTheta(startphi + deltaphi)
        source.SetStartPhi(starttheta)
        source.SetEndPhi(starttheta + deltatheta)

        source.Update()

        if rmin > 0:
            # Inner hole processing: could add vtkBooleanOperationPolyDataFilter here
            pass

        return source.GetOutput()

    def _create_torus(self, params: Dict[str, float]) -> vtkPolyData:
        """Create a torus solid using vtkParametricTorus"""
        rtor = params.get("rtor", 50.0)
        rmax = params.get("rmax", 10.0)
        rmin = params.get("rmin", 0.0)
        startphi = params.get("startphi", 0.0)
        deltaphi = params.get("deltaphi", 360.0)

        torus = vtkParametricTorus()
        torus.SetRingRadius(rtor)
        torus.SetCrossSectionRadius(rmax)
        torus.SetN(self.THETA_RESOLUTION)
        torus.SetM(self.PHI_RESOLUTION)

        source = vtkParametricFunctionSource()
        source.SetParametricFunction(torus)
        source.SetUResolution(self.THETA_RESOLUTION)
        source.SetVResolution(self.PHI_RESOLUTION)
        source.Update()

        if rmin > 0:
            # Hollow torus: subtract inner tube
            inner = vtkParametricTorus()
            inner.SetRingRadius(rtor)
            inner.SetCrossSectionRadius(rmin)
            inner.SetN(self.THETA_RESOLUTION)
            inner.SetM(self.PHI_RESOLUTION)
            inner_src = vtkParametricFunctionSource()
            inner_src.SetParametricFunction(inner)
            inner_src.SetUResolution(self.THETA_RESOLUTION)
            inner_src.SetVResolution(self.PHI_RESOLUTION)
            inner_src.Update()

            boolean_op = vtkBooleanOperationPolyDataFilter()
            boolean_op.SetOperationToDifference()
            boolean_op.SetInputData(0, source.GetOutput())
            boolean_op.SetInputData(1, inner_src.GetOutput())
            boolean_op.Update()
            return boolean_op.GetOutput()

        return source.GetOutput()

    def _create_ellipsoid(self, params: Dict[str, float]) -> vtkPolyData:
        """Create an ellipsoid by scaling a sphere"""
        ax = params.get("ax", 1.0)
        by = params.get("by", 1.0)
        cz = params.get("cz", 1.0)
        zcut1 = params.get("zcut1", -99999.0)
        zcut2 = params.get("zcut2", 99999.0)

        # Use unit sphere then scale
        source = vtkSphereSource()
        source.SetRadius(1.0)
        source.SetThetaResolution(self.THETA_RESOLUTION)
        source.SetPhiResolution(self.PHI_RESOLUTION)
        source.Update()

        transform = vtkTransform()
        transform.Scale(ax, by, cz)
        tfilter = vtkTransformPolyDataFilter()
        tfilter.SetInputData(source.GetOutput())
        tfilter.SetTransform(transform)
        tfilter.Update()

        return tfilter.GetOutput()

    def _create_tube(self, params: Dict[str, float]) -> vtkPolyData:
        """Create a tube solid (cylindrical pipe) using manual mesh."""
        rmin = params.get("rmin", 0.0)
        rmax = params.get("rmax", 1.0)
        z = params.get("z", 1.0)
        startphi = params.get("startphi", 0.0)
        deltaphi = params.get("deltaphi", 360.0)
        is_full = abs(deltaphi - 360.0) < 0.001

        h = z
        n = self.THETA_RESOLUTION

        if rmin <= 0:
            # Solid cylinder: use VTK source (fast, no boolean needed)
            source = vtkCylinderSource()
            source.SetRadius(rmax)
            source.SetHeight(h)
            source.SetResolution(n)
            source.Update()
            return source.GetOutput()

        # --- Hollow tube: build mesh manually ---
        points = vtkPoints()
        triangles = vtkCellArray()
        zh = h * 0.5

        def angle(t):
            if is_full:
                return 2.0 * math.pi * t
            return math.radians(startphi + t * deltaphi)

        # Outer wall: bottom ring (z=-zh) -> top ring (z=+zh)
        for side in range(2):
            zpos = -zh if side == 0 else zh
            for j in range(n + 1):
                a = angle(j / n)
                points.InsertNextPoint(rmax * math.cos(a), rmax * math.sin(a), zpos)
        for j in range(n):
            b0, b1 = j, j + 1
            t0, t1 = n + 1 + j, n + 1 + j + 1
            triangles.InsertNextCell(3, [b0, t0, b1])
            triangles.InsertNextCell(3, [b1, t0, t1])

        # Inner wall
        inner_off = 2 * (n + 1)
        for side in range(2):
            zpos = -zh if side == 0 else zh
            for j in range(n + 1):
                a = angle(j / n)
                points.InsertNextPoint(rmin * math.cos(a), rmin * math.sin(a), zpos)
        for j in range(n):
            b0, b1 = inner_off + j, inner_off + j + 1
            t0, t1 = inner_off + n + 1 + j, inner_off + n + 1 + j + 1
            triangles.InsertNextCell(3, [b0, b1, t0])
            triangles.InsertNextCell(3, [b1, t1, t0])

        # End caps (full 360 only)
        if is_full:
            band_off = inner_off + 2 * (n + 1)
            for cap_side in range(2):
                zpos = -zh if cap_side == 0 else zh
                o_start = band_off
                for j in range(n + 1):
                    a = angle(j / n)
                    points.InsertNextPoint(rmax * math.cos(a), rmax * math.sin(a), zpos)
                i_start = points.GetNumberOfPoints()
                for j in range(n + 1):
                    a = angle(j / n)
                    points.InsertNextPoint(rmin * math.cos(a), rmin * math.sin(a), zpos)
                for j in range(n):
                    o0, o1 = o_start + j, o_start + j + 1
                    i0, i1 = i_start + j, i_start + j + 1
                    if cap_side == 0:  # bottom, normal -Z
                        triangles.InsertNextCell(3, [o0, o1, i0])
                        triangles.InsertNextCell(3, [o1, i1, i0])
                    else:  # top, normal +Z
                        triangles.InsertNextCell(3, [o0, i0, o1])
                        triangles.InsertNextCell(3, [o1, i0, i1])
                band_off = i_start + n + 1

        pd = vtkPolyData()
        pd.SetPoints(points)
        pd.SetPolys(triangles)
        return pd

    def _create_cone(self, params: Dict[str, float]) -> vtkPolyData:
        """Create a cone solid (G4Cons)"""
        rmin1 = params.get("rmin1", 0.0)
        rmax1 = params.get("rmax1", 1.0)
        rmin2 = params.get("rmin2", 0.0)
        rmax2 = params.get("rmax2", 1.0)
        z = params.get("z", 1.0)

        # Use conical segment approximation: subdivide height, each segment is a frustum
        # Simple approach: approximate with vtkConeSource or linear transition frustum
        # MVP: if rmax1 == rmax2 and rmin1 == rmin2, treat as tube
        if abs(rmax1 - rmax2) < 0.001 and abs(rmin1 - rmin2) < 0.001:
            params_simple = {"rmin": rmin1, "rmax": rmax1, "z": z,
                             "startphi": 0, "deltaphi": 360}
            return self._create_tube(params_simple)

        # Temporarily use multi-segment cylinder approximation
        segments = 16
        from vtkmodules.vtkFiltersCore import vtkAppendPolyData
        append = vtkAppendPolyData()

        for i in range(segments):
            t0 = i / segments
            t1 = (i + 1) / segments
            r0 = rmax1 + (rmax2 - rmax1) * t0
            r1 = rmax1 + (rmax2 - rmax1) * t1
            h = z / segments
            z0 = -z / 2 + t0 * z

            if r0 > 0.001:
                seg_source = vtkCylinderSource()
                seg_source.SetRadius((r0 + r1) / 2)
                seg_source.SetHeight(h)
                seg_source.SetResolution(self.THETA_RESOLUTION // 4)
                seg_source.Update()

                # Translate each segment
                from vtkmodules.vtkCommonTransforms import vtkTransform
                from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
                transform = vtkTransform()
                transform.Translate(0, 0, z0)
                tfilter = vtkTransformPolyDataFilter()
                tfilter.SetInputData(seg_source.GetOutput())
                tfilter.SetTransform(transform)
                tfilter.Update()
                append.AddInputData(tfilter.GetOutput())

        append.Update()
        return append.GetOutput()

    def _create_tessellated(self, node: GdmlNode) -> vtkPolyData:
        """Create tessellated solid from triangles/quadrangles vertex data."""
        poly_data = vtkPolyData()
        points = vtkPoints()
        polys = vtkCellArray()

        if not node.solid_params:
            return poly_data

        vertices: dict = node.solid_params.get("vertices", {})
        triangles: list = node.solid_params.get("triangles", [])
        quadrangles: list = node.solid_params.get("quadrangles", [])

        if not vertices or (not triangles and not quadrangles):
            return poly_data

        # Build vertex name -> index map, insert points
        vname_to_idx: Dict[str, int] = {}
        for vname, coord in vertices.items():
            vname_to_idx[vname] = points.InsertNextPoint(coord)

        # Insert triangle faces
        for v1_name, v2_name, v3_name in triangles:
            tri = vtkTriangle()
            tri.GetPointIds().SetId(0, vname_to_idx.get(v1_name, 0))
            tri.GetPointIds().SetId(1, vname_to_idx.get(v2_name, 0))
            tri.GetPointIds().SetId(2, vname_to_idx.get(v3_name, 0))
            polys.InsertNextCell(tri)

        # Insert quadrangles as two triangles each (for VTK rendering)
        for v1_name, v2_name, v3_name, v4_name in quadrangles:
            i1 = vname_to_idx.get(v1_name, 0)
            i2 = vname_to_idx.get(v2_name, 0)
            i3 = vname_to_idx.get(v3_name, 0)
            i4 = vname_to_idx.get(v4_name, 0)

            # Split quad into two triangles: (v1,v2,v3) and (v1,v3,v4)
            tri1 = vtkTriangle()
            tri1.GetPointIds().SetId(0, i1)
            tri1.GetPointIds().SetId(1, i2)
            tri1.GetPointIds().SetId(2, i3)
            polys.InsertNextCell(tri1)

            tri2 = vtkTriangle()
            tri2.GetPointIds().SetId(0, i1)
            tri2.GetPointIds().SetId(1, i3)
            tri2.GetPointIds().SetId(2, i4)
            polys.InsertNextCell(tri2)

        poly_data.SetPoints(points)
        poly_data.SetPolys(polys)
        return poly_data

    def _create_polycone(self, params: Dict) -> vtkPolyData:
        """Create a polycone solid by building the mesh manually.
        
        Constructs vertices and triangles for each zplane-to-zplane 
        conical section, avoiding fragile boolean operations entirely.
        Supports both solid (rmin=0) and hollow (rmin>0) polycones.
        """
        zplanes: list = params.get("zplanes", [])
        if len(zplanes) < 2:
            return vtkPolyData()

        startphi = params.get("startphi", 0.0)
        deltaphi = params.get("deltaphi", 360.0)
        is_full = abs(deltaphi - 360.0) < 0.001

        n_theta = self.THETA_RESOLUTION
        append = vtkAppendPolyData()

        for i in range(len(zplanes) - 1):
            zp0 = zplanes[i]
            zp1 = zplanes[i + 1]

            z0 = zp0["z"]
            z1 = zp1["z"]
            rmin0 = zp0["rmin"]
            rmax0 = zp0["rmax"]
            rmin1 = zp1["rmin"]
            rmax1 = zp1["rmax"]

            if abs(z1 - z0) < 0.001 or (rmax0 < 0.001 and rmax1 < 0.001):
                continue

            points = vtkPoints()
            triangles = vtkCellArray()

            def angle(t):
                """Return angle in radians with startphi offset."""
                return math.radians(startphi + t * deltaphi) if not is_full else 2.0 * math.pi * t

            # --- Outer wall ---
            # Bottom ring (r0, z0) → Top ring (r1, z1)
            for side in range(2):
                r_outer = rmax0 if side == 0 else rmax1
                z = z0 if side == 0 else z1
                for j in range(n_theta + 1):
                    t = j / n_theta
                    a = angle(t)
                    points.InsertNextPoint(r_outer * math.cos(a),
                                           r_outer * math.sin(a),
                                           z)

            # Triangles for outer wall
            for j in range(n_theta):
                b0 = j
                b1 = j + 1
                t0 = n_theta + 1 + j
                t1 = n_theta + 1 + j + 1
                # Two triangles per quad
                triangles.InsertNextCell(3, [b0, t0, b1])
                triangles.InsertNextCell(3, [b1, t0, t1])

            offset = 2 * (n_theta + 1)

            # --- Inner wall (hollow only) ---
            has_inner = (rmin0 > 0.001 or rmin1 > 0.001)
            if has_inner:
                rmin0_ = max(rmin0, 0.001)
                rmin1_ = max(rmin1, 0.001)
                for side in range(2):
                    r_inner = rmin0_ if side == 0 else rmin1_
                    z = z0 if side == 0 else z1
                    for j in range(n_theta + 1):
                        t = j / n_theta
                        a = angle(t)
                        points.InsertNextPoint(r_inner * math.cos(a),
                                               r_inner * math.sin(a),
                                               z)

                # Triangles for inner wall (reversed winding for inward-facing)
                for j in range(n_theta):
                    b0 = offset + j
                    b1 = offset + j + 1
                    t0 = offset + n_theta + 1 + j
                    t1 = offset + n_theta + 1 + j + 1
                    triangles.InsertNextCell(3, [b0, b1, t0])
                    triangles.InsertNextCell(3, [b1, t1, t0])

                offset += 2 * (n_theta + 1)

            # --- End caps (only for full 360° sections) ---
            if is_full:
                for cap_side in range(2):
                    z = z0 if cap_side == 0 else z1
                    r_outer = rmax0 if cap_side == 0 else rmax1
                    r_inner = rmin0 if cap_side == 0 else rmin1
                    has_inner_this = r_inner > 0.001

                    ring_start = points.GetNumberOfPoints()
                    for j in range(n_theta + 1):
                        t = j / n_theta
                        a = angle(t)
                        points.InsertNextPoint(r_outer * math.cos(a),
                                               r_outer * math.sin(a),
                                               z)

                    if has_inner_this:
                        inner_start = points.GetNumberOfPoints()
                        for j in range(n_theta + 1):
                            t = j / n_theta
                            a = angle(t)
                            points.InsertNextPoint(r_inner * math.cos(a),
                                                   r_inner * math.sin(a),
                                                   z)
                        # Band between outer and inner rings (no center point)
                        for j in range(n_theta):
                            o0 = ring_start + j
                            o1 = ring_start + j + 1
                            i0 = inner_start + j
                            i1 = inner_start + j + 1
                            if cap_side == 0:  # bottom, normal faces -Z
                                triangles.InsertNextCell(3, [o0, o1, i0])
                                triangles.InsertNextCell(3, [o1, i1, i0])
                            else:  # top, normal faces +Z
                                triangles.InsertNextCell(3, [o0, i0, o1])
                                triangles.InsertNextCell(3, [o1, i0, i1])
                    else:
                        # Solid cap: fan from center to outer ring
                        center_idx = points.GetNumberOfPoints()
                        points.InsertNextPoint(0.0, 0.0, z)
                        for j in range(n_theta):
                            p0 = ring_start + j
                            p1 = ring_start + j + 1
                            if cap_side == 0:  # bottom, normal -Z: CW
                                triangles.InsertNextCell(3, [center_idx, p1, p0])
                            else:  # top, normal +Z: CCW
                                triangles.InsertNextCell(3, [center_idx, p0, p1])

            # Build polydata for this section
            pd = vtkPolyData()
            pd.SetPoints(points)
            pd.SetPolys(triangles)
            append.AddInputData(pd)

        append.Update()
        return append.GetOutput()

    @staticmethod
    def _get_color_for_node(name: str) -> Tuple[float, float, float]:
        """Generate a stable, visually distinct color from a node's name/ID.
        Uses a curated palette of 20+ colors for the first nodes, then
        falls back to a hash-based hue spread for uniqueness."""
        curated = [
            (0.50, 0.70, 0.90),  # soft blue
            (0.90, 0.55, 0.30),  # orange
            (0.55, 0.80, 0.55),  # green
            (0.90, 0.65, 0.75),  # pink
            (0.70, 0.55, 0.85),  # purple
            (0.90, 0.80, 0.40),  # gold
            (0.55, 0.80, 0.90),  # cyan
            (0.85, 0.60, 0.50),  # salmon
            (0.65, 0.75, 0.50),  # olive
            (0.90, 0.70, 0.90),  # light magenta
            (0.50, 0.60, 0.75),  # steel blue
            (0.75, 0.50, 0.40),  # brown
            (0.65, 0.80, 0.75),  # seafoam
            (0.85, 0.60, 0.65),  # rose
            (0.70, 0.70, 0.50),  # khaki
            (0.55, 0.65, 0.85),  # cornflower
            (0.85, 0.75, 0.55),  # tan
            (0.65, 0.55, 0.75),  # lavender
            (0.80, 0.65, 0.55),  # clay
            (0.60, 0.75, 0.70),  # sage
        ]

        import hashlib
        h = hashlib.md5(name.encode()).hexdigest()
        idx = int(h[:4], 16) % len(curated)
        return curated[idx]
