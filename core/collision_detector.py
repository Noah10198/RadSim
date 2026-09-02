"""
AABB-based collision detection — pure computation, no Qt dependency.
"""
import random
from typing import Dict, List, Optional, Tuple, Callable
from vtkmodules.vtkCommonTransforms import vtkTransform
from core.gdml_tree import GdmlNode, GdmlNodeType, Placement

AABB = Tuple[float, float, float, float, float, float]  # xmin,xmax,ymin,ymax,zmin,zmax


def compute_half_size(node: GdmlNode) -> Tuple[float, float, float]:
    """Conservative half-size (hx, hy, hz) for any solid type."""
    p = node.solid_params
    if not p:
        return (0.0, 0.0, 0.0)
    tag = node.gdml_tag

    if tag == 'box':
        return (p.get('x', 0.0), p.get('y', 0.0), p.get('z', 0.0))
    if tag in ('sphere', 'orb'):
        r = p.get('rmax', 0.0)
        return (r, r, r)
    if tag in ('tube', 'tubs', 'twistedtube'):
        r = p.get('rmax', 0.0)
        z = p.get('z', 0.0) * 0.5
        return (r, r, z)
    if tag in ('cone', 'twistedcone', 'cons'):
        r = max(p.get('rmax1', 0.0), p.get('rmax2', 0.0))
        z = p.get('z', 0.0) * 0.5
        return (r, r, z)
    if tag in ('polycone', 'genericPolycone'):
        zplanes = p.get('zplanes', [])
        if zplanes:
            zs = [zp['z'] for zp in zplanes]
            rs = [max(zp.get('rmax', 0), zp.get('rmin', 0)) for zp in zplanes]
            r = max(rs)
            z = (max(zs) - min(zs)) * 0.5
            return (r, r, z)
        return (0.0, 0.0, 0.0)
    if tag == 'ellipsoid':
        return (p.get('ax', 0.0), p.get('by', 0.0), p.get('cz', 0.0))
    if tag == 'torus':
        return (p.get('rmax', p.get('rtor', 0.0)),
                p.get('rmax', p.get('rtor', 0.0)),
                p.get('rmax', p.get('rtor', 0.0)))
    if tag in ('tessellated', 'xtru'):
        vertices = p.get('vertices')
        if isinstance(vertices, dict) and vertices:
            xs = [v[0] for v in vertices.values()]
            ys = [v[1] for v in vertices.values()]
            zs = [v[2] for v in vertices.values()]
            return ((max(xs) - min(xs)) * 0.5,
                    (max(ys) - min(ys)) * 0.5,
                    (max(zs) - min(zs)) * 0.5)
    # Fallback: first three numeric values
    num_vals = [v for v in p.values() if isinstance(v, (int, float))]
    return (float(num_vals[0]) if len(num_vals) > 0 else 0.0,
            float(num_vals[1]) if len(num_vals) > 1 else 0.0,
            float(num_vals[2]) if len(num_vals) > 2 else 0.0)


def compute_world_transform(
    node: GdmlNode,
    override_provider: Optional[Callable[[str], Optional[Placement]]] = None,
) -> Tuple[float, float, float, float, float, float]:
    """World-space (tx, ty, tz, rx, ry, rz) — mirrors vtk_scene placement."""
    tx = ty = tz = rx = ry = rz = 0.0
    is_world = (node.node_type == GdmlNodeType.WORLD_NODE)

    current = node.parent
    while current is not None:
        if current.node_type == GdmlNodeType.PHYVOL_NODE:
            p = current.placement
            if override_provider and current.entry_id:
                override = override_provider(current.entry_id)
                if override:
                    p = override
            if p:
                tx += p.x; ty += p.y; tz += p.z
                rx += p.rot_x; ry += p.rot_y; rz += p.rot_z
        elif current.node_type == GdmlNodeType.GDML_FILE and not is_world:
            ft = current.file_transform
            if ft:
                tx += ft.x; ty += ft.y; tz += ft.z
                rx += ft.rot_x; ry += ft.rot_y; rz += ft.rot_z
        current = current.parent

    return tx, ty, tz, rx, ry, rz


def compute_world_aabb(
    node: GdmlNode,
    override_provider: Optional[Callable[[str], Optional[Placement]]] = None,
) -> AABB:
    """World-space AABB for a volume node."""
    hx, hy, hz = compute_half_size(node)
    tx, ty, tz, rx, ry, rz = compute_world_transform(node, override_provider)

    # Local bounding box corners
    corners = [
        (-hx, -hy, -hz), ( hx, -hy, -hz),
        (-hx,  hy, -hz), ( hx,  hy, -hz),
        (-hx, -hy,  hz), ( hx, -hy,  hz),
        (-hx,  hy,  hz), ( hx,  hy,  hz),
    ]

    if abs(rx) < 1e-6 and abs(ry) < 1e-6 and abs(rz) < 1e-6:
        xmin = tx + min(c[0] for c in corners)
        xmax = tx + max(c[0] for c in corners)
        ymin = ty + min(c[1] for c in corners)
        ymax = ty + max(c[1] for c in corners)
        zmin = tz + min(c[2] for c in corners)
        zmax = tz + max(c[2] for c in corners)
        return xmin, xmax, ymin, ymax, zmin, zmax

    # Use VTK transform matching actor orientation.
    # Must match VtkScene.get_world_polydata / _apply_node_placement:
    #   SetOrientation(-rx, -ry, -rz) applies body-frame Y(-rx) → X(-ry) → Z(-rz)
    #   which in vtkTransform pre-multiply order means: RotateZ(-rz) → RotateX(-ry) → RotateY(-rx)
    t = vtkTransform()
    t.Translate(tx, ty, tz)
    t.RotateZ(-rz)
    t.RotateX(-ry)
    t.RotateY(-rx)

    xmin = ymin = zmin = float('inf')
    xmax = ymax = zmax = float('-inf')
    for cx, cy, cz in corners:
        wx, wy, wz = t.TransformPoint(cx, cy, cz)
        xmin = min(xmin, wx); xmax = max(xmax, wx)
        ymin = min(ymin, wy); ymax = max(ymax, wy)
        zmin = min(zmin, wz); zmax = max(zmax, wz)
    return xmin, xmax, ymin, ymax, zmin, zmax


def aabb_overlap(aabb1: AABB, aabb2: AABB) -> Optional[Tuple[float, float, float]]:
    """Return (ox, oy, oz) overlap dims, or None if no overlap."""
    ox = min(aabb1[1], aabb2[1]) - max(aabb1[0], aabb2[0])
    oy = min(aabb1[3], aabb2[3]) - max(aabb1[2], aabb2[2])
    oz = min(aabb1[5], aabb2[5]) - max(aabb1[4], aabb2[4])
    return (ox, oy, oz) if ox > 0 and oy > 0 and oz > 0 else None


def generate_full_pairs(indices: List[int]) -> List[Tuple[int, int]]:
    """All unique (i,j) pairs, i<j."""
    n = len(indices)
    return [(indices[i], indices[j]) for i in range(n) for j in range(i + 1, n)]


def generate_sampled_pairs(
    indices: List[int],
    file_ids: Optional[Dict[int, str]] = None,
) -> List[Tuple[int, int]]:
    """Randomly sample up to 5% (min 2, max 50) of total pairs.

    If file_ids is provided and multiple files exist, guarantees at least
    one cross-file pair among the sampled results.
    """
    n = len(indices)
    total = n * (n - 1) // 2
    n_sample = min(max(2, int(total * 0.05)), 50)
    if total <= n_sample:
        return generate_full_pairs(indices)

    all_pairs = generate_full_pairs(indices)

    # Ensure at least one cross-file pair
    if file_ids:
        unique_files = set(file_ids.values())
        if len(unique_files) > 1:
            cross = [(i, j) for i, j in all_pairs
                     if file_ids.get(i) != file_ids.get(j)]
            if cross:
                # Pick one forced cross-file pair, rest random
                forced = [random.choice(cross)]
                remaining = [p for p in all_pairs if p not in forced]
                sampled = forced + random.sample(remaining, n_sample - 1)
                random.shuffle(sampled)
                return sampled

    return random.sample(all_pairs, n_sample)
