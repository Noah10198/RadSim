"""particle_geo - relationship between the particle source and imported
geometry / World volume (pure Python, no VTK/Qt).

Unit convention: mm, consistent with the GDML parser; the particle source
config in gps_source.cfg is stored in mm as well. When geometry is missing or
cannot be evaluated, every result safely falls back to None/False and the UI
shows a hint to the user.
"""

# The meaning of each key inside the source "position" subset is documented
# in gps_source.SHAPE_FIELDS.


def geometry_loaded(agent) -> bool:
    """Return True when at least one GDML geometry file has been imported."""
    try:
        return bool(agent is not None and agent.get_all_file_nodes())
    except Exception:
        return False


def world_bbox_mm(agent):
    """World (container) bounding box in world coordinates
    (xmin,xmax,ymin,ymax,zmin,zmax), in mm.

    Returns None when nothing was imported or no world node exists.
    Uses the public gdml_agent interface.
    """
    try:
        if agent is None:
            return None
        return agent.compute_world_bbox()
    except Exception:
        return None


def geometry_bbox_mm(agent):
    """AABB of the imported geometry (world container excluded), in mm;
    None when there is no geometry."""
    try:
        if agent is None:
            return None
        bb = agent.compute_scene_bbox()
        return bb if any(bb) else None
    except Exception:
        return None


def source_aabb_mm(ps) -> tuple:
    """Estimate an AABB for the source from its "position" config
    (xmin,xmax,ymin,ymax,zmin,zmax), in mm.

    Planar sources (Plane/Circle/Square/etc.) use z=cz with zero thickness
    (schematic: a +Z-facing plane); Sphere/Ellipsoid/Cylinder use the same
    extents whether volume or surface. Para tilt is ignored (conservative box).
    """
    pt = ps.get("type", "Point")
    sh = ps.get("shape", "")
    cx = float(ps.get("cx", 0) or 0)
    cy = float(ps.get("cy", 0) or 0)
    cz = float(ps.get("cz", 0) or 0)

    def f(k):
        try:
            return float(ps.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    ex = ey = ez = 0.0
    if pt == "Point":
        pass
    elif sh in ("Circle", "Annulus"):
        r = f("radius")
        ex = ey = r
    elif sh in ("Square", "Rectangle"):
        ex, ey = f("halfx"), f("halfy")
    elif sh == "Ellipse":
        ex, ey = f("halfx"), f("halfy")
    elif sh == "Sphere":
        r = f("radius")
        ex = ey = ez = r
    elif sh == "Ellipsoid":
        ex, ey, ez = f("halfx"), f("halfy"), f("halfz")
    elif sh == "Cylinder":
        ex, ey, ez = f("radius"), f("radius"), f("halfz")
    elif sh == "Para":
        ex, ey, ez = f("halfx"), f("halfy"), f("halfz")
    return (cx - ex, cx + ex, cy - ey, cy + ey, cz - ez, cz + ez)


def _contains(outer, inner) -> bool:
    for i in range(0, 6, 2):
        if inner[i] < outer[i] - 1e-9 or inner[i + 1] > outer[i + 1] + 1e-9:
            return False
    return True


def _overlaps(a, b) -> bool:
    """Return True when the two AABBs overlap."""
    for i in range(0, 6, 2):
        if a[i + 1] < b[i] or a[i] > b[i + 1]:
            return False
    return True


def check_source_world(cfg, world) -> dict:
    """Check the source against the World volume and return a dict:

    keys:
      status   "no_geo" | "no_world" | "inside" | "partial" | "outside"
      msg      one-line human message for the UI
      src_aabb source AABB
    """
    if not cfg:
        return {"status": "no_geo",
                "msg": "Particle source config is empty", "src_aabb": None}
    src = source_aabb_mm(cfg.get("position") or {})
    if not world:
        return {"status": "no_world",
                "msg": "No geometry / World imported - cannot validate",
                "src_aabb": src}
    if _contains(world, src):
        return {"status": "inside",
                "msg": "Source is fully inside the World volume",
                "src_aabb": src}
    if _overlaps(src, world):
        return {"status": "partial",
                "msg": "Source partially exceeds the World volume - "
                       "out-of-bounds particles would not be emitted or "
                       "would leave geometry immediately",
                "src_aabb": src}
    return {"status": "outside",
            "msg": "Source lies outside the World volume - "
                   "particles would never enter the geometry",
            "src_aabb": src}


def fmt_bbox(bb) -> str:
    if not bb:
        return "-"
    return (f"x[{bb[0]:g},{bb[1]:g}] y[{bb[2]:g},{bb[3]:g}] "
            f"z[{bb[4]:g},{bb[5]:g}] mm")


def source_center_text(ps) -> str:
    ps = ps or {}
    return (f"({float(ps.get('cx', 0) or 0):g}, "
            f"{float(ps.get('cy', 0) or 0):g}, "
            f"{float(ps.get('cz', 0) or 0):g}) mm")
