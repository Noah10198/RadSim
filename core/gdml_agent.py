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

    def compute_scene_bbox(self) -> Tuple[float, float, float, float, float, float]:
        """
        Compute global axis-aligned bounding box of all renderable volumes.

        Returns:
            (xmin, xmax, ymin, ymax, zmin, zmax)
            Returns (0,0,0,0,0,0) if no volumes exist
        """
        xmin = ymin = zmin = float('inf')
        xmax = ymax = zmax = float('-inf')
        found = False

        for vol in self.get_all_renderable_volumes():
            if not vol.solid_params:
                continue
            # Half-size
            hx = vol.solid_params.get('x', 0) / 2.0
            hy = vol.solid_params.get('y', 0) / 2.0
            hz = vol.solid_params.get('z', 0) / 2.0

            # Accumulate global position from parent chain
            tx, ty, tz = self._compute_global_position(vol)
            lxmin, lxmax = tx - hx, tx + hx
            lymin, lymax = ty - hy, ty + hy
            lzmin, lzmax = tz - hz, tz + hz

            if lxmin < xmin: xmin = lxmin
            if lxmax > xmax: xmax = lxmax
            if lymin < ymin: ymin = lymin
            if lymax > ymax: ymax = lymax
            if lzmin < zmin: zmin = lzmin
            if lzmax > zmax: zmax = lzmax
            found = True

        if not found:
            return (0, 0, 0, 0, 0, 0)
        return (xmin, xmax, ymin, ymax, zmin, zmax)

    def _compute_global_position(self, node: GdmlNode) -> Tuple[float, float, float]:
        """
        Walk up parent chain, accumulating:
        - PHYVOL_NODE placements (per-physvol positioning, with override support)
        - GDML_FILE file_transform (file-level translate/rotate)

        Note: placement overrides from Transform dialog must be accounted for,
        otherwise bbox will use original (pre-transform) positions.
        """
        tx = ty = tz = 0.0
        cur = node.parent
        while cur is not None:
            if cur.node_type == GdmlNodeType.PHYVOL_NODE:
                # Start from original GDML placement, then check for override
                p = cur.placement
                if cur.entry_id and cur.entry_id in self._placement_overrides:
                    p = self._placement_overrides[cur.entry_id]
                if p is not None:
                    tx += p.x
                    ty += p.y
                    tz += p.z
            elif cur.node_type == GdmlNodeType.GDML_FILE and cur.file_transform:
                ft = cur.file_transform
                tx += ft.x
                ty += ft.y
                tz += ft.z
            cur = cur.parent
        return (tx, ty, tz)

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
