"""
GdmIParser - GDML File Parser

Parses the five standard GDML sections:
  <define>     — constants, positions, rotations, quantities
  <materials>  — isotopes, elements, materials
  <solids>     — solid geometry definitions
  <structure>  — volume / physvol tree hierarchy
  <setup>      — world volume reference

Current MVP supported solid types: box, sphere, tube, tessellated
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .gdml_tree import GdmlNode, GdmlNodeType, Placement
from .gdml_evaluator import GdmIEvaluator


class GdmIParser:
    """
    GDML file parser

    Parse flow:
      1. Parse <define> section  -> collect constants/positions/rotations
      2. Parse <materials> section -> collect material definitions
      3. Parse <solids> section   -> build solid definition dict
      4. Parse <structure> section -> build volume/physvol tree
      5. Parse <setup> section    -> mark world volume
      6. Build complete GdmlNode tree, resolve values for OCC/VTK representation
    """

    # Unit conversion factors (to mm)
    _LENGTH_UNITS = {
        "mm": 1.0,
        "cm": 10.0,
        "m": 1000.0,
        "um": 0.001,
        "nm": 0.000001,
        "km": 1000000.0,
        "": 1.0,  # default to mm when no unit
    }

    # Angle unit conversion factors (to degrees)
    _ANGLE_UNITS = {
        "deg": 1.0,
        "rad": 57.29577951308232,
        "": 1.0,
    }

    # Fully supported solid tags (parsed with solid_params for 3D rendering)
    _SUPPORTED_SOLIDS = frozenset({
        "box", "sphere", "orb",
        "tube", "tubs",
        "cone",
        "tessellated",
        "torus",
        "ellipsoid",
        "polycone", "genericPolycone",
    })

    def __init__(self):
        self._evaluator = GdmIEvaluator()

        # Temporary storage during parsing
        self._positions: Dict[str, Tuple[float, float, float]] = {}  # name -> (x,y,z)
        self._rotations: Dict[str, Tuple[float, float, float]] = {}  # name -> (x,y,z)
        self._solids: Dict[str, GdmlNode] = {}        # name -> solid node
        self._volumes: Dict[str, GdmlNode] = {}        # name -> volume node
        self._assemblies: Dict[str, GdmlNode] = {}     # name -> assembly node

        self._world_ref: str = ""  # world volume name referenced in setup

        # Unsupported solids encountered during parsing (for user warning)
        self._unsupported_solids: List[Dict[str, str]] = []

    def parse_file(self, filepath: str) -> GdmlNode:
        """
        Parse a single GDML file, return the file root node.

        Args:
            filepath: GDML file path

        Returns:
            File node (GdmlNodeType.GDML_FILE) with parsed structure tree as children
        """
        self._clear()
        filepath = str(filepath)
        tree = ET.parse(filepath)
        root = tree.getroot()

        # Capture original XML declaration (comment, standalone, etc.)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                first = f.readline().strip()
                if first.startswith("<?xml"):
                    file_node.raw_declaration = first
        except Exception:
            pass

        if root.tag != "gdml":
            raise ValueError(f"Not a valid GDML file: root tag is '{root.tag}'")

        file_name = Path(filepath).name
        file_node = GdmlNode(GdmlNodeType.GDML_FILE, file_name)

        # Parse sections in order
        for child in root:
            tag = child.tag
            if tag == "define":
                self._parse_define(child)
                file_node.raw_define_xml = ET.tostring(child, encoding="unicode")
            elif tag == "materials":
                self._parse_materials(child)
                file_node.raw_materials_xml = ET.tostring(child, encoding="unicode")
            elif tag == "solids":
                self._parse_solids(child)
            elif tag == "structure":
                self._parse_structure(child, file_node)
            elif tag == "setup":
                self._parse_setup(child)
                file_node.raw_setup_xml = ET.tostring(child, encoding="unicode")

        # Build world node — keep original name so raw_setup_xml ref matches
        if self._world_ref and self._world_ref in self._volumes:
            world_node = self._volumes[self._world_ref]
            world_node.node_type = GdmlNodeType.WORLD_NODE

            # The world volume was already added as child of file_node in _parse_structure,
            # but may have been moved elsewhere by physvol volumeref.
            # Ensure it's under file_node with only one copy.
            if world_node not in file_node._children:
                file_node.add_child(world_node)

        # Attach list of unsupported solids for downstream warning
        if self._unsupported_solids:
            file_node._unsupported_solids = list(self._unsupported_solids)

        return file_node

    def _clear(self):
        """Clear parsing state"""
        self._positions.clear()
        self._rotations.clear()
        self._solids.clear()
        self._volumes.clear()
        self._assemblies.clear()
        self._world_ref = ""
        self._unsupported_solids.clear()

    # ==================== <define> parsing ====================

    def _parse_define(self, define_elem: ET.Element):
        """Parse the <define> section"""
        for child in define_elem:
            tag = child.tag
            if tag == "constant":
                name = child.get("name", "")
                value_str = child.get("value", "0")
                try:
                    value = self._evaluator.evaluate(value_str)
                    self._evaluator.set_constant(name, value)
                except ValueError:
                    pass

            elif tag == "position":
                name = child.get("name", "")
                unit = child.get("unit", "mm")
                factor = self._LENGTH_UNITS.get(unit, 1.0)
                x = self._evaluator.evaluate(child.get("x", "0")) * factor
                y = self._evaluator.evaluate(child.get("y", "0")) * factor
                z = self._evaluator.evaluate(child.get("z", "0")) * factor
                self._positions[name] = (x, y, z)

            elif tag == "rotation":
                name = child.get("name", "")
                unit = child.get("unit", "deg")
                factor = self._ANGLE_UNITS.get(unit, 1.0)
                x = self._evaluator.evaluate(child.get("x", "0")) * factor
                y = self._evaluator.evaluate(child.get("y", "0")) * factor
                z = self._evaluator.evaluate(child.get("z", "0")) * factor
                self._rotations[name] = (x, y, z)

            elif tag == "quantity":
                name = child.get("name", "")
                value_str = child.get("value", "0")
                try:
                    value = self._evaluator.evaluate(value_str)
                    self._evaluator.set_constant(name, value)
                except ValueError:
                    pass

    # ==================== <materials> parsing (MVP simplified) ====================

    def _parse_materials(self, materials_elem: ET.Element):
        """
        Parse the <materials> section (MVP simplified).
        Currently does basic parsing, recording material name and parameters for later use.
        """
        for child in materials_elem:
            tag = child.tag
            if tag == "material":
                name = child.get("name", "")
                # Record density and other info
                d_elem = child.find("D")
                density = 0.0
                if d_elem is not None:
                    density = self._evaluator.evaluate(d_elem.get("value", "0"))
                # MVP: deep material structure parsing not yet implemented

    # ==================== <solids> parsing ====================

    def _parse_solids(self, solids_elem: ET.Element):
        """Parse the <solids> section"""
        for child in solids_elem:
            tag = child.tag
            name = child.get("name", "")

            if tag == "box":
                node = self._parse_box(child, name)
            elif tag == "sphere":
                node = self._parse_sphere(child, name)
            elif tag in ("tube", "tubs"):
                node = self._parse_tube(child, name)
                node.gdml_tag = tag  # preserve original tag name (tubs vs tube)
            elif tag in ("cone",):
                node = self._parse_cone(child, name)
            elif tag == "tessellated":
                node = self._parse_tessellated(child, name)
            elif tag == "orb":
                node = self._parse_orb(child, name)
            elif tag == "torus":
                node = self._parse_torus(child, name)
            elif tag == "ellipsoid":
                node = self._parse_ellipsoid(child, name)
            elif tag in ("polycone", "genericPolycone"):
                node = self._parse_polycone(child, name)
            else:
                # All other solid types: store attributes for round-trip
                # Note: these are NOT fully supported — they won't be rendered
                # in 3D view but will be preserved for GDML export.
                node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
                node.gdml_tag = tag
                node.gdml_attrs = dict(child.attrib)
                # Store raw XML for complex solids (those with sub-elements)
                # e.g. polycone, polyhedra, xtru, booleans, multiUnion, scaledSolid
                if len(child) > 0:
                    node.raw_solid_xml = ET.tostring(child, encoding="unicode")
                # Track as unsupported for user warning
                self._unsupported_solids.append({"tag": tag, "name": name})

            if node:
                self._solids[name] = node

    def _parse_box(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a box solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "box"
        node.gdml_attrs = dict(elem.attrib)

        lunit = elem.get("lunit", "mm")
        factor = self._LENGTH_UNITS.get(lunit, 1.0)

        x = self._evaluator.evaluate(elem.get("x", "0")) * factor
        y = self._evaluator.evaluate(elem.get("y", "0")) * factor
        z = self._evaluator.evaluate(elem.get("z", "0")) * factor

        node.solid_params = {"x": x, "y": y, "z": z}
        return node

    def _parse_sphere(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a sphere solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "sphere"
        node.gdml_attrs = dict(elem.attrib)

        lunit = elem.get("lunit", "mm")
        aunit = elem.get("aunit", "deg")
        lfactor = self._LENGTH_UNITS.get(lunit, 1.0)
        afactor = self._ANGLE_UNITS.get(aunit, 1.0)

        rmin = self._evaluator.evaluate(elem.get("rmin", "0")) * lfactor
        rmax = self._evaluator.evaluate(elem.get("rmax", "0")) * lfactor
        startphi = self._evaluator.evaluate(elem.get("startphi", "0")) * afactor
        deltaphi = self._evaluator.evaluate(elem.get("deltaphi", "360")) * afactor
        starttheta = self._evaluator.evaluate(elem.get("starttheta", "0")) * afactor
        deltatheta = self._evaluator.evaluate(elem.get("deltatheta", "180")) * afactor

        node.solid_params = {
            "rmin": rmin, "rmax": rmax,
            "startphi": startphi, "deltaphi": deltaphi,
            "starttheta": starttheta, "deltatheta": deltatheta,
        }
        return node

    def _parse_tube(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a tube solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "tube"
        node.gdml_attrs = dict(elem.attrib)

        lunit = elem.get("lunit", "mm")
        aunit = elem.get("aunit", "deg")
        lfactor = self._LENGTH_UNITS.get(lunit, 1.0)
        afactor = self._ANGLE_UNITS.get(aunit, 1.0)

        rmin = self._evaluator.evaluate(elem.get("rmin", "0")) * lfactor
        rmax = self._evaluator.evaluate(elem.get("rmax", "0")) * lfactor
        z = self._evaluator.evaluate(elem.get("z", "0")) * lfactor
        startphi = self._evaluator.evaluate(elem.get("startphi", "0")) * afactor
        deltaphi = self._evaluator.evaluate(elem.get("deltaphi", "360")) * afactor

        node.solid_params = {
            "rmin": rmin, "rmax": rmax, "z": z,
            "startphi": startphi, "deltaphi": deltaphi,
        }
        return node

    def _parse_cone(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a cone solid (G4Cons)"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "cone"
        node.gdml_attrs = dict(elem.attrib)

        lunit = elem.get("lunit", "mm")
        aunit = elem.get("aunit", "deg")
        lfactor = self._LENGTH_UNITS.get(lunit, 1.0)
        afactor = self._ANGLE_UNITS.get(aunit, 1.0)

        rmin1 = self._evaluator.evaluate(elem.get("rmin1", "0")) * lfactor
        rmax1 = self._evaluator.evaluate(elem.get("rmax1", "0")) * lfactor
        rmin2 = self._evaluator.evaluate(elem.get("rmin2", "0")) * lfactor
        rmax2 = self._evaluator.evaluate(elem.get("rmax2", "0")) * lfactor
        z = self._evaluator.evaluate(elem.get("z", "0")) * lfactor
        startphi = self._evaluator.evaluate(elem.get("startphi", "0")) * afactor
        deltaphi = self._evaluator.evaluate(elem.get("deltaphi", "360")) * afactor

        node.solid_params = {
            "rmin1": rmin1, "rmax1": rmax1,
            "rmin2": rmin2, "rmax2": rmax2,
            "z": z,
            "startphi": startphi, "deltaphi": deltaphi,
        }
        return node

    def _parse_tessellated(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a tessellated solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "tessellated"
        node.gdml_attrs = dict(elem.attrib)

        # Collect triangles and quadrangles as vertex name references
        triangles: List[Tuple[str, str, str]] = []            # (v1, v2, v3) name refs
        quadrangles: List[Tuple[str, str, str, str]] = []     # (v1, v2, v3, v4)

        vertex_names: set = set()
        for child in elem:
            if child.tag == "triangular":
                v1 = child.get("vertex1", "")
                v2 = child.get("vertex2", "")
                v3 = child.get("vertex3", "")
                if v1 and v2 and v3:
                    triangles.append((v1, v2, v3))
                    vertex_names.update((v1, v2, v3))
            elif child.tag == "quadrangular":
                v1 = child.get("vertex1", "")
                v2 = child.get("vertex2", "")
                v3 = child.get("vertex3", "")
                v4 = child.get("vertex4", "")
                if v1 and v2 and v3 and v4:
                    quadrangles.append((v1, v2, v3, v4))
                    vertex_names.update((v1, v2, v3, v4))

        # Resolve vertex coordinates from global positions
        resolved_vertices: Dict[str, Tuple[float, float, float]] = {}
        unresolved = False
        for vn in vertex_names:
            if vn in self._positions:
                resolved_vertices[vn] = self._positions[vn]
            else:
                # Inline vertex might be defined inside tessellated element (GDML inline)
                resolved_vertices[vn] = (0.0, 0.0, 0.0)
                unresolved = True

        # Resolve triangle face vertex indices
        resolved_triangles: List[Tuple[int, int, int]] = []
        for v1, v2, v3 in triangles:
            if v1 in resolved_vertices and v2 in resolved_vertices and v3 in resolved_vertices:
                resolved_triangles.append((v1, v2, v3))

        # Resolve quadrangle face vertex indices
        resolved_quadrangles: List[Tuple[int, int, int, int]] = []
        for v1, v2, v3, v4 in quadrangles:
            if all(v in resolved_vertices for v in (v1, v2, v3, v4)):
                resolved_quadrangles.append((v1, v2, v3, v4))

        node.solid_params = {
            "tri_count": len(triangles),
            "quad_count": len(quadrangles),
            "vertices": resolved_vertices,
            "triangles": resolved_triangles,
            "quadrangles": resolved_quadrangles,
        }
        # Preserve raw XML for perfect-fidelity export
        node.raw_solid_xml = ET.tostring(elem, encoding="unicode")

        return node

    def _parse_orb(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse an orb solid (full sphere with single radius)"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "orb"
        node.gdml_attrs = dict(elem.attrib)
        lfactor = self._LENGTH_UNITS.get(elem.get("lunit", "mm"), 1.0)
        r = self._evaluator.evaluate(elem.get("r", "1")) * lfactor
        node.solid_params = {"rmax": r, "rmin": 0,
                             "startphi": 0, "deltaphi": 360,
                             "starttheta": 0, "deltatheta": 180}
        return node

    def _parse_torus(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a torus solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "torus"
        node.gdml_attrs = dict(elem.attrib)
        lfactor = self._LENGTH_UNITS.get(elem.get("lunit", "mm"), 1.0)
        afactor = self._ANGLE_UNITS.get(elem.get("aunit", "deg"), 1.0)
        rtor = self._evaluator.evaluate(elem.get("rtor", "1")) * lfactor
        rmin = self._evaluator.evaluate(elem.get("rmin", "0")) * lfactor
        rmax = self._evaluator.evaluate(elem.get("rmax", "1")) * lfactor
        startphi = self._evaluator.evaluate(elem.get("startphi", "0")) * afactor
        deltaphi = self._evaluator.evaluate(elem.get("deltaphi", "360")) * afactor
        node.solid_params = {
            "rtor": rtor, "rmin": rmin, "rmax": rmax,
            "startphi": startphi, "deltaphi": deltaphi,
        }
        return node

    def _parse_ellipsoid(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse an ellipsoid solid"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "ellipsoid"
        node.gdml_attrs = dict(elem.attrib)
        lfactor = self._LENGTH_UNITS.get(elem.get("lunit", "mm"), 1.0)
        ax = self._evaluator.evaluate(elem.get("ax", "1")) * lfactor
        by = self._evaluator.evaluate(elem.get("by", "1")) * lfactor
        cz = self._evaluator.evaluate(elem.get("cz", "1")) * lfactor
        zcut1 = self._evaluator.evaluate(elem.get("zcut1", "-99999")) * lfactor
        zcut2 = self._evaluator.evaluate(elem.get("zcut2", "99999")) * lfactor
        node.solid_params = {
            "ax": ax, "by": by, "cz": cz,
            "zcut1": zcut1, "zcut2": zcut2,
        }
        return node

    def _parse_polycone(self, elem: ET.Element, name: str) -> GdmlNode:
        """Parse a polycone solid (stacked conical sections)"""
        node = GdmlNode(GdmlNodeType.SOLID_DEF, name)
        node.gdml_tag = "polycone"
        node.gdml_attrs = dict(elem.attrib)
        # Store raw XML for round-trip (has <zplane> sub-elements)
        node.raw_solid_xml = ET.tostring(elem, encoding="unicode")
        lfactor = self._LENGTH_UNITS.get(elem.get("lunit", "mm"), 1.0)
        afactor = self._ANGLE_UNITS.get(elem.get("aunit", "deg"), 1.0)
        startphi = self._evaluator.evaluate(elem.get("startphi", "0")) * afactor
        deltaphi = self._evaluator.evaluate(elem.get("deltaphi", "360")) * afactor
        # Extract zplane sections
        zplanes = []
        for child in elem:
            if child.tag == "zplane":
                z = self._evaluator.evaluate(child.get("z", "0")) * lfactor
                rmin = self._evaluator.evaluate(child.get("rmin", "0")) * lfactor
                rmax = self._evaluator.evaluate(child.get("rmax", "1")) * lfactor
                zplanes.append({"z": z, "rmin": rmin, "rmax": rmax})
        node.solid_params = {
            "startphi": startphi, "deltaphi": deltaphi,
            "zplanes": zplanes,
        }
        return node

    # ==================== <structure> parsing ====================

    def _parse_structure(self, structure_elem: ET.Element, parent_node: GdmlNode):
        """Parse the <structure> section.

        Following Geant4's G4LogicalVolumeStore pattern:
        - Each <volume> creates a LOGICAL VOLUME definition (VOLUME_NODE)
        - Volumes are added as direct children of the file node (the "store")
        - Physical placements (physvol -> volumeref) create instance clones
          instead of reparenting the original, so the same volume can be
          referenced by multiple physvols without conflict.
        """
        for child in structure_elem:
            tag = child.tag
            if tag == "volume":
                vol_node = self._parse_volume(child)
                if vol_node:
                    # Add volume as child of file node (LogicalVolumeStore),
                    # following Geant4's G4LogicalVolumeStore pattern.
                    # This keeps the definition separate from physical instances.
                    parent_node.add_child(vol_node)
            elif tag == "assembly":
                asm_node = self._parse_assembly(child)
                if asm_node:
                    asm_name = asm_node.name
                    self._assemblies[asm_name] = asm_node
                    parent_node.add_child(asm_node)

    def _parse_volume(self, vol_elem: ET.Element) -> Optional[GdmlNode]:
        """Parse a <volume> element"""
        name = vol_elem.get("name", "")
        if not name:
            return None

        vol_node = GdmlNode(GdmlNodeType.VOLUME_NODE, name)
        vol_node.gdml_attrs = dict(vol_elem.attrib)

        for child in vol_elem:
            tag = child.tag

            if tag == "materialref":
                mat_ref = child.get("ref", "")
                vol_node.material_name = mat_ref
                vol_node.gdml_attrs["materialref"] = mat_ref

            elif tag == "solidref":
                solid_ref = child.get("ref", "")
                vol_node.ref_name = solid_ref
                vol_node.gdml_attrs["solidref"] = solid_ref

                # Reference solid defined in <solids> section
                if solid_ref in self._solids:
                    solid_node = self._solids[solid_ref]
                    # Copy solid parameters to volume node (for rendering)
                    vol_node.gdml_tag = solid_node.gdml_tag
                    vol_node.solid_params = dict(solid_node.solid_params)
                    # Keep solid node as child of volume (preserve original definition for export)
                    solid_node.name = solid_ref
                    vol_node.add_child(solid_node)

            elif tag == "physvol":
                phys_node = self._parse_physvol(child)
                if phys_node:
                    vol_node.add_child(phys_node)

            elif tag == "auxiliary":
                aux_type = child.get("auxtype", "")
                aux_val = child.get("auxvalue", "")
                vol_node.gdml_attrs[f"aux_{aux_type}"] = aux_val

        self._volumes[name] = vol_node
        return vol_node

    def _parse_physvol(self, phys_elem: ET.Element) -> Optional[GdmlNode]:
        """Parse a <physvol> element

        Following Geant4's G4PVPlacement pattern: each physvol creates a
        new physical instance with its own transform. The instance is a
        recursively cloned subtree (volume + nested physvols), so the
        same logical volume can be placed multiple times independently.
        """
        name = phys_elem.get("name", "")
        phys_node = GdmlNode(GdmlNodeType.PHYVOL_NODE, name)
        phys_node.gdml_attrs = dict(phys_elem.attrib)
        phys_node.placement = Placement()

        # Discover referenced volume name to give unnamed physvol a meaningful name
        ref_name = phys_elem.find("volumeref")
        ref = ref_name.get("ref", "") if ref_name is not None else ""
        if not name and ref:
            phys_node._display_name = f"physvol - {ref}"
            phys_node.name = ""  # Keep name empty so exporter doesn't write auto-generated name
        phys_node.ref_name = ref

        for child in phys_elem:
            tag = child.tag

            if tag == "volumeref":
                ref = child.get("ref", "")
                phys_node.ref_name = ref
                phys_node.gdml_attrs["volumeref"] = ref

                # Create an INSTANCE clone subtree, not a reference to the
                # original volume (which stays in the LogicalVolumeStore).
                # The clone recursively copies nested physvol hierarchy so
                # multi-level placements (e.g., World -> lDetector -> lTes)
                # are preserved independently per physvol.
                if ref in self._volumes:
                    ref_vol = self._volumes[ref]
                    inst = self._clone_volume_instance(ref_vol)
                    phys_node.add_child(inst)
                elif ref in self._assemblies:
                    # physvol can also reference an <assembly>
                    # Clone all of the assembly's physvol children (with their
                    # volume instance subtrees) under this physvol, so the
                    # 3D scene builder can find and render them.
                    asm_node = self._assemblies[ref]
                    phys_node.gdml_attrs["assemblyref"] = ref
                    for asm_child in asm_node.children:
                        if asm_child.node_type == GdmlNodeType.PHYVOL_NODE:
                            cloned_pv = self._clone_physvol(asm_child)
                            phys_node.add_child(cloned_pv)

            elif tag == "position":
                unit = child.get("unit", "mm")
                factor = self._LENGTH_UNITS.get(unit, 1.0)
                x = self._evaluator.evaluate(child.get("x", "0")) * factor
                y = self._evaluator.evaluate(child.get("y", "0")) * factor
                z = self._evaluator.evaluate(child.get("z", "0")) * factor
                phys_node.placement.x = x
                phys_node.placement.y = y
                phys_node.placement.z = z
                phys_node.placement.unit = unit

            elif tag == "positionref":
                ref = child.get("ref", "")
                phys_node.gdml_attrs["positionref"] = ref
                if ref in self._positions:
                    pos = self._positions[ref]
                    phys_node.placement.x = pos[0]
                    phys_node.placement.y = pos[1]
                    phys_node.placement.z = pos[2]

            elif tag == "rotation":
                unit = child.get("unit", "deg")
                factor = self._ANGLE_UNITS.get(unit, 1.0)
                x = self._evaluator.evaluate(child.get("x", "0")) * factor
                y = self._evaluator.evaluate(child.get("y", "0")) * factor
                z = self._evaluator.evaluate(child.get("z", "0")) * factor
                phys_node.placement.rot_x = x
                phys_node.placement.rot_y = y
                phys_node.placement.rot_z = z
                phys_node.placement.rot_unit = unit

            elif tag == "rotationref":
                ref = child.get("ref", "")
                phys_node.gdml_attrs["rotationref"] = ref
                if ref in self._rotations:
                    rot = self._rotations[ref]
                    phys_node.placement.rot_x = rot[0]
                    phys_node.placement.rot_y = rot[1]
                    phys_node.placement.rot_z = rot[2]

        return phys_node

    def _clone_volume_instance(self, vol_node: GdmlNode) -> GdmlNode:
        """Recursively clone a volume as a physical instance.

        Analogous to Geant4 creating a G4PVPlacement: the clone gets its
        own solid parameters and recursively clones nested physvol children,
        but the original volume definition stays untouched in the store.
        SOLID_DEF children are NOT cloned (they belong to the Solids group).
        """
        inst = GdmlNode(GdmlNodeType.VOLUME_NODE, vol_node.name)
        inst.solid_params = dict(vol_node.solid_params) if vol_node.solid_params else None
        inst.gdml_tag = vol_node.gdml_tag
        inst.material_name = vol_node.material_name
        inst.gdml_attrs = dict(vol_node.gdml_attrs)

        # Recursively clone nested physvol children
        for child in vol_node.children:
            if child.node_type == GdmlNodeType.PHYVOL_NODE:
                pv_clone = self._clone_physvol(child)
                inst.add_child(pv_clone)

        return inst

    def _clone_physvol(self, pv_node: GdmlNode) -> GdmlNode:
        """Clone a PHYVOL_NODE with its instance subtree."""
        clone = GdmlNode(GdmlNodeType.PHYVOL_NODE, pv_node.name)
        clone.ref_name = pv_node.ref_name
        clone.gdml_attrs = dict(pv_node.gdml_attrs)
        if pv_node.placement:
            clone.placement = Placement(
                x=pv_node.placement.x, y=pv_node.placement.y, z=pv_node.placement.z,
                rot_x=pv_node.placement.rot_x, rot_y=pv_node.placement.rot_y,
                rot_z=pv_node.placement.rot_z,
                unit=pv_node.placement.unit, rot_unit=pv_node.placement.rot_unit,
            )

        for child in pv_node.children:
            if child.node_type == GdmlNodeType.VOLUME_NODE:
                inst_clone = self._clone_volume_instance(child)
                clone.add_child(inst_clone)
            elif child.node_type == GdmlNodeType.PHYVOL_NODE:
                # Handle nested assembly physvol children
                pv_clone = self._clone_physvol(child)
                clone.add_child(pv_clone)

        return clone

    def _parse_assembly(self, asm_elem: ET.Element) -> Optional[GdmlNode]:
        """Parse an <assembly> element"""
        name = asm_elem.get("name", "")
        if not name:
            return None

        asm_node = GdmlNode(GdmlNodeType.ASSEMBLY_NODE, name)
        asm_node.gdml_attrs = dict(asm_elem.attrib)

        for child in asm_elem:
            if child.tag == "physvol":
                phys_node = self._parse_physvol(child)
                if phys_node:
                    asm_node.add_child(phys_node)

        return asm_node

    # ==================== <setup> parsing ====================

    def _parse_setup(self, setup_elem: ET.Element):
        """Parse the <setup> section: ref attribute is on child <world> element"""
        world_elem = setup_elem.find("world")
        if world_elem is not None:
            self._world_ref = world_elem.get("ref", "")
