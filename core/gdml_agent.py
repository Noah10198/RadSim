"""
GdmlAgent - GDML Data Agent (Singleton)

Corresponds to cad2gdml's GeoDataAgent design, providing a unified interface
for the GDML data module. Manages the lifecycle of all GDML data nodes:
  - Load/parse GDML files
  - Incremental import (merge multiple GDML files)
  - Node lookup/modification
  - Edit overlay management
  - Export
"""

import uuid
from typing import List, Optional, Dict, Tuple
from pathlib import Path

from .gdml_tree import GdmlNode, GdmlNodeType, Placement
from .gdml_parser import GdmIParser
from .gdml_evaluator import GdmIEvaluator
from .collision_detector import compute_world_transform
from vtkmodules.vtkCommonTransforms import vtkTransform


class GdmlAgent:
    """GDML Data Agent (Singleton)"""

    _instance: Optional['GdmlAgent'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._root_node = GdmlNode(GdmlNodeType.ROOT_NODE, "GDML Editor Root")
        self._entry_id_map: Dict[str, GdmlNode] = {}
        self._parser = GdmIParser()

        # Edit overlay: physvol placement overrides
        # key: entry_id, value: Placement
        self._placement_overrides: Dict[str, Placement] = {}

        # Material overrides
        self._material_overrides: Dict[str, str] = {}

    def load_gdml_file(self, filepath: str) -> Tuple[bool, str]:
        """
        Load a single GDML file (blocking, main-thread path).
        For non-blocking import, use parse_file_only() + add_parsed_file_node().

        Args:
            filepath: GDML file path

        Returns:
            (success, error_message)
        """
        try:
            file_node, file_name = self._parse_file_only(filepath)
            self._add_parsed_file_node(file_node)
            return True, self._make_loaded_msg(file_name, file_node)
        except Exception as e:
            return False, str(e)

    def parse_file_only(self, filepath: str) -> Tuple[Optional['GdmlNode'], str]:
        """
        Parse a GDML file WITHOUT mutating agent state.
        Thread-safe — can be called from a background thread.

        Returns:
            (file_node, filename) on success
            (None, error_message) on failure
        """
        try:
            return self._parse_file_only(filepath)
        except Exception as e:
            return None, str(e)

    def _parse_file_only(self, filepath: str) -> Tuple['GdmlNode', str]:
        """Internal: parse file, return (file_node, filename)."""
        file_name = Path(filepath).name
        file_node = self._parser.parse_file(filepath)
        return file_node, file_name

    def add_parsed_file_node(self, file_node: 'GdmlNode') -> str:
        """
        Add a pre-parsed file node to agent state (MUST be called on main thread).
        Returns the loaded message string.
        """
        return self._add_parsed_file_node(file_node)

    def _add_parsed_file_node(self, file_node: 'GdmlNode') -> str:
        """Internal: assign entry_ids and attach file_node to root."""
        entry_id = self._generate_entry_id()
        file_node.entry_id = entry_id
        self._entry_id_map[entry_id] = file_node
        self._root_node.add_child(file_node)

        for child in file_node.get_all_descendants():
            child.entry_id = self._generate_entry_id()
            self._entry_id_map[child.entry_id] = child

        return self._make_loaded_msg(file_node.name, file_node)

    @staticmethod
    def _make_loaded_msg(file_name: str, file_node: 'GdmlNode') -> str:
        """Build the success message string."""
        msg = f"Loaded: {file_name}"
        unsupported = getattr(file_node, '_unsupported_solids', None)
        if unsupported:
            msg += f" ({len(unsupported)} solid type(s) not fully parsed)"
        return msg

    def get_unsupported_solids(self) -> List[Dict[str, str]]:
        """
        Collect all unsupported solid types across all loaded files.
        Returns a list of {"tag": tag, "name": name, "file": filename}.
        """
        result = []
        for file_node in self.get_all_file_nodes():
            unsupported = getattr(file_node, '_unsupported_solids', None)
            if unsupported:
                filename = file_node.name
                for s in unsupported:
                    result.append({**s, "file": filename})
        return result

    def get_root_node(self) -> GdmlNode:
        return self._root_node

    def get_all_file_nodes(self) -> List[GdmlNode]:
        """Get all imported GDML file nodes"""
        return [c for c in self._root_node.children
                if c.node_type == GdmlNodeType.GDML_FILE]

    def get_node_by_entry_id(self, entry_id: str) -> Optional[GdmlNode]:
        return self._entry_id_map.get(entry_id)

    def find_node_by_name(self, name: str) -> Optional[GdmlNode]:
        return self._root_node.find_node_by_name(name)

    def get_all_renderable_volumes(self) -> List[GdmlNode]:
        """
        Get all renderable volume nodes.

        Note: volume nodes may have SOLID_DEF children (from solidref references),
        but they are still renderable. This detects volume/world nodes with
        solid_params, excluding world nodes from renderable list.
        """
        results = []
        for file_node in self.get_all_file_nodes():
            for node in file_node.get_all_descendants():
                if node.node_type not in (GdmlNodeType.VOLUME_NODE,
                                           GdmlNodeType.WORLD_NODE):
                    continue
                if not node.solid_params:
                    continue
                # Exclude world node (world itself is not part of scene bbox)
                if node.node_type == GdmlNodeType.WORLD_NODE:
                    continue
                results.append(node)
        return results

    def get_all_physvols(self) -> List[GdmlNode]:
        """Get all physvol nodes"""
        results = []
        for file_node in self.get_all_file_nodes():
            for node in file_node.get_all_descendants():
                if node.node_type == GdmlNodeType.PHYVOL_NODE:
                    results.append(node)
        return results

    # ---- Edit overlay ----

    def set_placement_override(self, entry_id: str, placement: Placement):
        """Set physvol placement override"""
        self._placement_overrides[entry_id] = placement
        node = self._entry_id_map.get(entry_id)
        if node:
            node.data_changed.emit()

    def get_placement_override(self, entry_id: str) -> Optional[Placement]:
        return self._placement_overrides.get(entry_id)

    def get_all_placement_overrides(self) -> Dict[str, Placement]:
        """Return the entire overrides dict (for export)."""
        return dict(self._placement_overrides)

    def clear_placement_override(self, entry_id: str):
        self._placement_overrides.pop(entry_id, None)
        node = self._entry_id_map.get(entry_id)
        if node:
            node.data_changed.emit()

    def has_placement_override(self, entry_id: str) -> bool:
        return entry_id in self._placement_overrides

    def set_material_override(self, entry_id: str, material_name: str):
        """Set volume material override"""
        self._material_overrides[entry_id] = material_name
        node = self._entry_id_map.get(entry_id)
        if node:
            node.material_name = material_name
            node.data_changed.emit()

    # ---- Node operations ----

    def remove_file_node(self, entry_id: str) -> bool:
        """Remove file node and all its children"""
        node = self._entry_id_map.get(entry_id)
        if node is None:
            return False
        if node.parent:
            node.parent.remove_child(node)
        self._entry_id_map.pop(entry_id, None)
        for desc in node.get_all_descendants():
            self._entry_id_map.pop(desc.entry_id, None)
        return True

    def _generate_entry_id(self) -> str:
        return f"GDM_{uuid.uuid4().hex[:12].upper()}"

    # ---- BBox & World operations ----

    # ---- Bounding boxes (world-frame, rotation-aware) ----
    #
    # The union of the *rendered instances* (VOLUME_NODEs cloned under a
    # physvol that belongs to the WORLD subtree - the same set VtkScene
    # builds actors for) is the true "geometry extent". LogicalVolumeStore
    # definitions are NOT physical geometry and are therefore excluded, as
    # is the world container itself. Each instance is boxed with its local
    # AABB (per solid type) transformed by the full parent-chain placement
    # (translation + Euler rotation), so rotated / tessellated / repeated
    # volumes are enclosed correctly.

    def compute_scene_bbox(self) -> Tuple[float, float, float, float, float, float]:
        """Union AABB of every physically placed volume (world excluded).

        Returns (xmin, xmax, ymin, ymax, zmin, zmax), or all zeros when no
        geometry exists.
        """
        boxes = [b for b in (self._world_aabb(n)
                             for n in self._iter_renderable_instances())
                 if b is not None]
        if not boxes:
            return (0, 0, 0, 0, 0, 0)
        return (min(b[0] for b in boxes), max(b[1] for b in boxes),
                min(b[2] for b in boxes), max(b[3] for b in boxes),
                min(b[4] for b in boxes), max(b[5] for b in boxes))

    def get_renderable_volume_names(self) -> List[str]:
        """Distinct logical-volume names that are physically placed under a
        world (one entry per logical volume, not per instance)."""
        seen: List[str] = []
        for inst in self._iter_renderable_instances():
            n = inst.name
            if n and n not in seen:
                seen.append(n)
        return seen

    def compute_volume_bbox(self, name: str
                            ) -> Tuple[float, float, float, float, float, float]:
        """Union AABB of all physical instances of one logical volume."""
        boxes = [b for n in self._iter_renderable_instances()
                 if n.name == name
                 for b in (self._world_aabb(n),) if b is not None]
        if not boxes:
            return (0, 0, 0, 0, 0, 0)
        return (min(b[0] for b in boxes), max(b[1] for b in boxes),
                min(b[2] for b in boxes), max(b[3] for b in boxes),
                min(b[4] for b in boxes), max(b[5] for b in boxes))

    # ---- Internals ----

    def _iter_renderable_instances(self):
        """Yield every volume node that VtkScene renders in normal mode
        (render_all_volumes=False): instance clones under the world subtree."""
        for file_node in self.get_all_file_nodes():
            yield from self._walk_instances(file_node, False)

    def _walk_instances(self, node: GdmlNode, under_world: bool):
        uw = under_world or node.node_type == GdmlNodeType.WORLD_NODE
        if (uw and node.node_type == GdmlNodeType.VOLUME_NODE
                and node.parent
                and node.parent.node_type == GdmlNodeType.PHYVOL_NODE
                and node.solid_params):
            yield node
        for child in node.children:
            yield from self._walk_instances(child, uw)

    @staticmethod
    def _local_aabb(node: GdmlNode) -> Optional[Tuple[float, float, float,
                                                      float, float, float]]:
        """Exact local AABB (xmin, xmax, ymin, ymax, zmin, zmax) of the
        solid in the volume's own frame — matches VtkSolidFactory rendering.
        None for solids that are not renderable (contribute nothing)."""
        p = node.solid_params or {}
        tag = node.gdml_tag
        if tag == "box":
            x, y, z = (p.get("x", 0) / 2, p.get("y", 0) / 2, p.get("z", 0) / 2)
            return (-x, x, -y, y, -z, z)
        if tag in ("sphere", "orb"):
            r = p.get("rmax", 0.0)
            return (-r, r, -r, r, -r, r)
        if tag in ("tube", "tubs"):
            r, z = p.get("rmax", 0.0), p.get("z", 0.0) / 2
            return (-r, r, -r, r, -z, z)
        if tag in ("cone", "cons"):
            r = max(p.get("rmax1", 0.0), p.get("rmax2", 0.0))
            z = p.get("z", 0.0) / 2
            return (-r, r, -r, r, -z, z)
        if tag == "torus":
            r = p.get("rtor", 0.0) + p.get("rmax", 0.0)
            z = p.get("rmax", 0.0)
            return (-r, r, -r, r, -z, z)
        if tag == "ellipsoid":
            ax, by, cz = p.get("ax", 0.0), p.get("by", 0.0), p.get("cz", 0.0)
            return (-ax, ax, -by, by, -cz, cz)
        if tag in ("polycone", "genericPolycone"):
            planes = p.get("zplanes") or []
            if not planes:
                return (0, 0, 0, 0, 0, 0)
            r = max(max(zp.get("rmax", 0.0), zp.get("rmin", 0.0))
                    for zp in planes)
            zs = [zp["z"] for zp in planes]
            return (-r, r, -r, r, min(zs), max(zs))
        if tag == "tessellated":
            verts = p.get("vertices") or {}
            if not verts:
                return (0, 0, 0, 0, 0, 0)
            xs = [v[0] for v in verts.values()]
            ys = [v[1] for v in verts.values()]
            zs = [v[2] for v in verts.values()]
            return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
        return None

    def _override_provider(self, entry_id: str) -> Optional[Placement]:
        return self._placement_overrides.get(entry_id)

    def _world_aabb(self, node: GdmlNode):
        """World-frame AABB of a single placed volume instance."""
        lb = self._local_aabb(node)
        if lb is None:
            return None
        tx, ty, tz, rx, ry, rz = compute_world_transform(
            node, self._override_provider)
        corners = [
            (lb[0], lb[2], lb[4]), (lb[1], lb[2], lb[4]),
            (lb[0], lb[3], lb[4]), (lb[1], lb[3], lb[4]),
            (lb[0], lb[2], lb[5]), (lb[1], lb[2], lb[5]),
            (lb[0], lb[3], lb[5]), (lb[1], lb[3], lb[5]),
        ]
        if abs(rx) < 1e-9 and abs(ry) < 1e-9 and abs(rz) < 1e-9:
            xs = [c[0] + tx for c in corners]
            ys = [c[1] + ty for c in corners]
            zs = [c[2] + tz for c in corners]
            return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
        # Same passive-Euler -> VTK active-order mapping as the renderer:
        # SetOrientation(-rx, -ry, -rz) == Translate -> RotateZ(-rz) ->
        # RotateX(-ry) -> RotateY(-rx).
        t = vtkTransform()
        t.Translate(tx, ty, tz)
        t.RotateZ(-rz)
        t.RotateX(-ry)
        t.RotateY(-rx)
        xs, ys, zs = [], [], []
        for cx, cy, cz in corners:
            wx, wy, wz = t.TransformPoint(cx, cy, cz)
            xs.append(wx); ys.append(wy); zs.append(wz)
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def compute_world_bbox(self) -> Optional[Tuple[float, float, float,
                                                   float, float, float]]:
        """Union of the world-frame AABBs of every world container.

        Unlike compute_scene_bbox (which excludes the world container), this
        returns the world box itself, so callers can validate e.g. particle
        source placement against the world. Returns None when no geometry /
        no world node exists.
        """
        boxes = [b for n in self.get_world_nodes()
                 for b in (self._world_aabb(n),) if b is not None]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), max(b[1] for b in boxes),
                min(b[2] for b in boxes), max(b[3] for b in boxes),
                min(b[4] for b in boxes), max(b[5] for b in boxes))

    def get_world_nodes(self) -> List[GdmlNode]:
        """Get all WORlD_NODE nodes"""
        results = []
        for file_node in self.get_all_file_nodes():
            for node in file_node.get_all_descendants():
                if node.node_type == GdmlNodeType.WORLD_NODE:
                    results.append(node)
            # Also check direct children of file node
            for c in file_node.children:
                if c.node_type == GdmlNodeType.WORLD_NODE:
                    if c not in results:
                        results.append(c)
        return results

    def get_world_materials(self) -> List[str]:
        """Get distinct material names used by all world volumes."""
        mats: Set[str] = set()
        for w in self.get_world_nodes():
            m = (w.material_name
                 or (w.gdml_attrs or {}).get("materialref", "")
                 or "").strip()
            if m:
                mats.add(m)
        return list(mats)

    def set_world_size(self, world_node: GdmlNode, half: float):
        """
        Set world volume size (half-size).

        Args:
            world_node: WORLD_NODE node
            half: half-length
        """
        full = half * 2.0
        world_node.solid_params['x'] = full
        world_node.solid_params['y'] = full
        world_node.solid_params['z'] = full

        # Also update solid child node (BoxDef) if present
        for child in world_node.children:
            if child.node_type == GdmlNodeType.SOLID_DEF:
                child.solid_params['x'] = full
                child.solid_params['y'] = full
                child.solid_params['z'] = full
                break

    def clear(self):
        """Clear all data"""
        self._root_node = GdmlNode(GdmlNodeType.ROOT_NODE, "GDML Editor Root")
        self._entry_id_map.clear()
        self._placement_overrides.clear()
        self._material_overrides.clear()
