"""GDML Writer — serializes GdmlNode tree back to GDML XML.

Preserves original structure whenever possible.
Only adds wrapper levels for file_transforms or multi-file merge.
Adds XML comments when placement_overrides are applied.

Uses minidom for pretty-printed output (matches cad2gdml convention).
"""

from typing import Dict, Optional, Set, TYPE_CHECKING
import xml.etree.ElementTree as ET
from xml.dom import minidom
from core.gdml_tree import GdmlNode, GdmlNodeType, Placement

if TYPE_CHECKING:
    from core.materials_lib import MaterialsLib


def _fmt(v: float) -> str:
    if isinstance(v, (int, float)):
        return f"{v:.6g}".rstrip(".")
    return str(v)


def _strip_element_text(elem: ET.Element) -> None:
    """Strip all text/tail whitespace so pretty-printer adds clean indentation."""
    elem.text = None
    elem.tail = None
    for child in elem:
        _strip_element_text(child)


def _unique(name: str, used: Set[str]) -> str:
    base = name
    n = 1
    while name in used:
        name = f"{base}_{n}"
        n += 1
    used.add(name)
    return name


# -------------------------------------------------------------------
# Linear/angular attribute sets for solid serialisation
# -------------------------------------------------------------------
_LINEAR = {"x", "y", "z", "rmin", "rmax", "rmin1", "rmax1",
           "rmin2", "rmax2", "dx", "dy", "dz", "pDz", "pSteel",
           "pDx1", "pDx2", "pDy1", "pDy2", "width", "height",
           "length", "halflength"}
_ANGULAR = {"startphi", "deltaphi", "starttheta", "deltatheta",
            "SPhi", "DPhi", "STheta", "DTheta"}




class GdmlWriter:
    """GDML file writer with override and file-transform support."""

    def __init__(self):
        self._overrides: Dict[str, Placement] = {}
        self._used_names: Set[str] = set()
        self._written_vols: Set[str] = set()
        self._written_solids: Set[str] = set()
        self._file_node: Optional[GdmlNode] = None

    # ── Public entry point ────────────────────────────────────────

    def write(self, root_node: GdmlNode,
              placement_overrides: Dict[str, Placement],
              filepath: str,
              mat_lib: Optional['MaterialsLib'] = None) -> None:
        self._overrides = placement_overrides
        self._used_names.clear()
        self._written_vols.clear()
        self._written_solids.clear()
        self._file_node = None
        self._mat_lib = mat_lib

        files = [c for c in root_node.children
                 if c.node_type == GdmlNodeType.GDML_FILE]

        gdml = ET.Element("gdml")
        gdml.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        gdml.set("xsi:noNamespaceSchemaLocation",
                 "http://service-spi.web.cern.ch/service-spi/"
                 "app/releases/GDML/schema/gdml.xsd")

        # ── Single file: reconstruct from raw sections ────────────
        if len(files) == 1:
            self._file_node = files[0]
            fn = files[0]

            # <define> — raw XML as base, but keep mutable (writers may add)
            if fn.raw_define_xml:
                define = ET.fromstring(fn.raw_define_xml)
                _strip_element_text(define)  # remove conflicting whitespace
            else:
                define = ET.Element("define")
            gdml.append(define)

            # <materials> — raw XML as base, then append local materials
            if fn.raw_materials_xml:
                mats = ET.fromstring(fn.raw_materials_xml)
                _strip_element_text(mats)
            else:
                mats = ET.Element("materials")
            self._append_local_materials(mats)
            gdml.append(mats)

            solids = ET.SubElement(gdml, "solids")
            structure = ET.SubElement(gdml, "structure")

            self._export_single(fn, define, solids, structure)

            # <setup> — use raw XML if available
            if fn.raw_setup_xml:
                stp = ET.fromstring(fn.raw_setup_xml)
                _strip_element_text(stp)
                gdml.append(stp)
            else:
                setup = ET.SubElement(gdml, "setup")
                setup.set("name", "Default")
                setup.set("version", "1.0")
                wv = self._find_world_volume(
                    self._find_world_node(fn))
                if wv and wv.name:
                    ET.SubElement(setup, "world").set("ref", wv.name)

        # ── Multi-file: merge under a unifying World ───────────────
        elif len(files) > 1:
            define = ET.SubElement(gdml, "define")
            materials = ET.SubElement(gdml, "materials")
            solids = ET.SubElement(gdml, "solids")
            structure = ET.SubElement(gdml, "structure")
            self._export_multi(files, define, materials, solids, structure)

            # <setup> pointing to the unified wrapper World
            setup = ET.SubElement(gdml, "setup")
            setup.set("name", "Default")
            setup.set("version", "1.0")
            ET.SubElement(setup, "world").set("ref", "World")

        rough = ET.tostring(gdml, encoding="unicode")
        pretty = minidom.parseString(rough).toprettyxml(indent="  ")
        # Preserve original XML declaration (standalone, encoding, etc.)
        fn = files[0] if len(files) == 1 else None
        if fn and fn.raw_declaration:
            lines = pretty.split("\n")
            if lines and lines[0].startswith("<?xml"):
                lines[0] = fn.raw_declaration
            pretty = "\n".join(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(pretty)

    # ── Single-file export ────────────────────────────────────────

    def _export_single(self, fn: GdmlNode,
                       define: ET.Element,
                       solids: ET.Element,
                       structure: ET.Element) -> None:
        ft = fn.file_transform
        wn = self._find_world_node(fn)
        wv = self._find_world_volume(wn) if wn else None
        if wv is None:
            return

        # Collect all solids (from whole file tree)
        for d in fn.get_all_descendants():
            if d.node_type == GdmlNodeType.SOLID_DEF and d.name:
                self._check_write_solid(solids, d, d.name)

        # Collect and write all logical volumes (direct children of fn)
        for c in fn.children:
            if (c.node_type == GdmlNodeType.VOLUME_NODE
                    and c.name != wv.name):
                self._write_volume_to_structure(c, structure, solids, define)

        # Write assembly definitions
        for c in fn.children:
            if c.node_type == GdmlNodeType.ASSEMBLY_NODE and c.name:
                self._write_assembly_to_structure(c, structure, solids, define)

        # Write the top world volume itself (with its physvols).
        # parent_ft bakes the file_transform into each physvol's inline
        # <position>/<rotation> element.  No wrapper volume is created,
        # so the original file structure is preserved and no G4_Galactic
        # material is needed.
        self._write_volume_to_structure(wv, structure, solids, define,
                                        parent_ft=ft)

    def _wrap_world_volume(self, wv: GdmlNode, ft: Placement,
                           define: ET.Element, solids: ET.Element,
                           structure: ET.Element) -> None:
        """Replace the world volume with a wrapper that applies file_transform."""
        wv_name = wv.name or "World"
        wrap_name = _unique(f"{wv_name}_ft", self._used_names)
        box_name = _unique(f"Box_{wrap_name}", self._used_names)
        pos_name = _unique(f"pos_{wrap_name}", self._used_names)
        rot_name = None

        # Add comment
        cmt = f" file_transform: x={_fmt(ft.x)} y={_fmt(ft.y)} z={_fmt(ft.z)}"
        if ft.rot_x or ft.rot_y or ft.rot_z:
            cmt += f" rot_x={_fmt(ft.rot_x)} rot_y={_fmt(ft.rot_y)} rot_z={_fmt(ft.rot_z)}"
        structure.insert(list(structure).index(structure.findall("./volume")[0])
                         if len(structure) > 0 else 0,
                         ET.Comment(cmt))

        # Tiny wrapper box
        b = ET.SubElement(solids, "box")
        b.set("name", box_name)
        b.set("x", "1")
        b.set("y", "1")
        b.set("z", "1")
        b.set("lunit", "mm")

        # Position + rotation in define
        pos = ET.SubElement(define, "position")
        pos.set("name", pos_name)
        pos.set("x", _fmt(ft.x))
        pos.set("y", _fmt(ft.y))
        pos.set("z", _fmt(ft.z))
        pos.set("unit", ft.unit or "mm")
        if ft.rot_x or ft.rot_y or ft.rot_z:
            rot_name = _unique(f"rot_{wrap_name}", self._used_names)
            rot = ET.SubElement(define, "rotation")
            rot.set("name", rot_name)
            rot.set("x", _fmt(ft.rot_x))
            rot.set("y", _fmt(ft.rot_y))
            rot.set("z", _fmt(ft.rot_z))
            rot.set("unit", ft.rot_unit or "deg")

        # Wrapper volume
        vol = ET.SubElement(structure, "volume")
        vol.set("name", wrap_name)
        ET.SubElement(vol, "materialref").set("ref", "G4_Galactic")
        ET.SubElement(vol, "solidref").set("ref", box_name)

        ipv = ET.SubElement(vol, "physvol")
        ET.SubElement(ipv, "volumeref").set("ref", wv_name)
        ET.SubElement(ipv, "positionref").set("ref", pos_name)
        if rot_name:
            ET.SubElement(ipv, "rotationref").set("ref", rot_name)

    # ── Multi-file export ─────────────────────────────────────────

    def _export_multi(self, files: list[GdmlNode],
                      define: ET.Element,
                      materials: ET.Element,
                      solids: ET.Element,
                      structure: ET.Element) -> None:
        # Find world volumes and the solid names they use, so we can
        # exclude them from the bulk solid copy (their solids are orphaned
        # after flattening and may conflict with the unified WorldBox name).
        world_solid_names: set[str] = set()
        for fn in files:
            wn = self._find_world_node(fn)
            wv = self._find_world_volume(wn) if wn else None
            if wv:
                sname = (wv.gdml_attrs or {}).get("solidref", "")
                if sname:
                    world_solid_names.add(sname)

        # Collect solids from all files, excluding world volume solids.
        for fn in files:
            for d in fn.get_all_descendants():
                if (d.node_type == GdmlNodeType.SOLID_DEF
                        and d.name
                        and d.name not in world_solid_names):
                    self._check_write_solid(solids, d, d.name)

        # World box — use the size from the first file's world node (after
        # "Redefine World" may have resized it), falling back to 200000 mm.
        wx = wy = wz = "200000"
        if files:
            first_world = self._find_world_node(files[0])
            if first_world and first_world.solid_params:
                p = first_world.solid_params
                wx = _fmt(p.get("x", 200000))
                wy = _fmt(p.get("y", 200000))
                wz = _fmt(p.get("z", 200000))

        wb_name = _unique("WorldBox", self._used_names)
        b = ET.SubElement(solids, "box")
        b.set("name", wb_name)
        b.set("x", wx)
        b.set("y", wy)
        b.set("z", wz)
        b.set("lunit", "mm")

        # Determine unified World material:
        # - If ALL world volumes share the same material → use it
        # - If they differ (or none) → use G4_AIR (Geant4 built-in NIST material,
        #   no definition needed in GDML)
        world_mat = "G4_AIR"
        if files:
            mats: set[str] = set()
            for fn in files:
                wn2 = self._find_world_node(fn)
                wv2 = self._find_world_volume(wn2) if wn2 else None
                if wv2:
                    m = (wv2.material_name
                         or (wv2.gdml_attrs or {}).get("materialref"))
                    if m:
                        mats.add(m)
            if len(mats) == 1:
                world_mat = mats.pop()

        world_vol = ET.Element("volume")
        world_vol.set("name", "World")
        ET.SubElement(world_vol, "materialref").set("ref", world_mat)
        ET.SubElement(world_vol, "solidref").set("ref", wb_name)

        for fn in files:
            ft = fn.file_transform
            wn = self._find_world_node(fn)
            wv = self._find_world_volume(wn) if wn else None
            if wv is None:
                continue

            # Write logical volumes (excluding the world volume itself)
            for c in fn.children:
                if (c.node_type == GdmlNodeType.VOLUME_NODE
                        and c.name != wv.name):
                    self._write_volume_to_structure(
                        c, structure, solids, define)

            # Write assembly definitions
            for c in fn.children:
                if c.node_type == GdmlNodeType.ASSEMBLY_NODE and c.name:
                    self._write_assembly_to_structure(
                        c, structure, solids, define)

            # Flatten: do NOT write the original world volume.
            # Instead, write its child physvols directly into the unified
            # World volume, baking file_transform into each placement.
            # This produces a single world box in the output.
            for child in wv.children:
                if child.node_type == GdmlNodeType.PHYVOL_NODE:
                    self._write_physvol(child, world_vol, ft, define)

        # Copy define entries (positions, rotations, constants, etc.)
        # from each file's original <define> into the output, so that
        # positionref/rotationref references (and tessellated vertex refs)
        # resolve correctly in the flattened output.
        for fn in files:
            raw_def = fn.raw_define_xml
            if not raw_def:
                continue
            try:
                def_elem = ET.fromstring(raw_def)
                _strip_element_text(def_elem)
                for child in def_elem:
                    name = child.get("name")
                    if name:
                        existing = define.find(f"./*[@name='{name}']")
                        if existing is None:
                            define.append(child)
            except Exception:
                pass

        structure.append(world_vol)

    # ── Volume writer ─────────────────────────────────────────────

    def _check_write_solid(self, parent: ET.Element,
                           node: GdmlNode, name: str) -> None:
        if name in self._written_solids:
            return
        self._written_solids.add(name)

        # Use raw XML for complex solids (polycone, xtru, booleans, etc.)
        # for perfect round-trip fidelity
        if node.raw_solid_xml:
            raw_elem = ET.fromstring(node.raw_solid_xml)
            raw_elem.set("name", name)
            _strip_element_text(raw_elem)  # avoid extra blank lines in output
            parent.append(raw_elem)
            return

        tag = node.gdml_tag or "box"
        try:
            e = ET.SubElement(parent, tag)
        except ValueError:
            e = ET.SubElement(parent, "box")
        e.set("name", name)

        has_l = has_a = False
        for k, v in (node.solid_params or {}).items():
            if not isinstance(v, (int, float)):
                continue
            if k in _LINEAR:
                e.set(k, _fmt(v))
                has_l = True
            elif k in _ANGULAR:
                e.set(k, _fmt(v))
                has_a = True
            else:
                e.set(k, _fmt(v))
        if has_l:
            e.set("lunit", "mm")
        if has_a:
            e.set("aunit", "deg")
        if node.gdml_attrs:
            for k, v in node.gdml_attrs.items():
                if k != "name" and k not in (node.solid_params or {}):
                    e.set(k, v)

    def _write_volume_to_structure(self, vn: GdmlNode,
                                   structure: ET.Element,
                                   solids: ET.Element,
                                   define: ET.Element,
                                   parent_ft: Optional[Placement] = None,
                                   _depth: int = 0) -> None:
        name = vn.name or "unnamed"
        if name in self._written_vols:
            return
        self._written_vols.add(name)

        vol = ET.SubElement(structure, "volume")
        vol.set("name", name)

        # materialref
        mat = vn.material_name or (vn.gdml_attrs or {}).get("materialref")
        if mat:
            ET.SubElement(vol, "materialref").set("ref", mat)
        else:
            ET.SubElement(vol, "materialref").set("ref", "G4_Galactic")

        # solidref
        sref = (vn.gdml_attrs or {}).get("solidref")
        if not sref:
            for c in vn.children:
                if c.node_type == GdmlNodeType.SOLID_DEF and c.name:
                    sref = c.name
                    break
        if sref:
            ET.SubElement(vol, "solidref").set("ref", sref)

        # Children: physvols and nested volumes
        for c in vn.children:
            if c.node_type == GdmlNodeType.PHYVOL_NODE:
                self._write_physvol(c, vol, parent_ft, define)
            elif c.node_type == GdmlNodeType.VOLUME_NODE:
                self._write_volume_to_structure(
                    c, structure, solids, define, None, _depth + 1)

    def _write_assembly_to_structure(self, asm_node: GdmlNode,
                                      structure: ET.Element,
                                      solids: ET.Element,
                                      define: ET.Element) -> None:
        """Write an <assembly> element with its physvol children."""
        name = asm_node.name or "unnamed_assembly"
        asm = ET.SubElement(structure, "assembly")
        asm.set("name", name)

        for c in asm_node.children:
            if c.node_type == GdmlNodeType.PHYVOL_NODE:
                self._write_physvol(c, asm, None, define)
            elif c.node_type == GdmlNodeType.VOLUME_NODE:
                self._write_volume_to_structure(
                    c, structure, solids, define, None)

    # ── Physvol writer ────────────────────────────────────────────

    def _has_override(self, pv: GdmlNode) -> bool:
        return bool(pv.entry_id and pv.entry_id in self._overrides)

    def _get_effective(self, pv: GdmlNode) -> Placement:
        if pv.entry_id and pv.entry_id in self._overrides:
            return self._overrides[pv.entry_id]
        return pv.placement or Placement()

    def _write_physvol(self, pv_node: GdmlNode,
                       parent_vol: ET.Element,
                       parent_ft: Optional[Placement],
                       define: ET.Element) -> None:
        # Add comment if overridden
        is_overridden = self._has_override(pv_node)
        effective = self._get_effective(pv_node)

        # Merge file_transform into placement
        if parent_ft is not None:
            effective = Placement(
                x=effective.x + parent_ft.x,
                y=effective.y + parent_ft.y,
                z=effective.z + parent_ft.z,
                rot_x=effective.rot_x + parent_ft.rot_x,
                rot_y=effective.rot_y + parent_ft.rot_y,
                rot_z=effective.rot_z + parent_ft.rot_z,
                unit=effective.unit or parent_ft.unit,
                rot_unit=effective.rot_unit or parent_ft.rot_unit
            )

        if is_overridden:
            parts = []
            orig = pv_node.placement or Placement()
            if abs(effective.x - orig.x) > 1e-9:
                parts.append(f"x={_fmt(orig.x)} -> {_fmt(effective.x)}")
            if abs(effective.y - orig.y) > 1e-9:
                parts.append(f"y={_fmt(orig.y)} -> {_fmt(effective.y)}")
            if abs(effective.z - orig.z) > 1e-9:
                parts.append(f"z={_fmt(orig.z)} -> {_fmt(effective.z)}")
            if abs(effective.rot_x - orig.rot_x) > 1e-9:
                parts.append(f"rot_x={_fmt(orig.rot_x)} -> {_fmt(effective.rot_x)}")
            if abs(effective.rot_y - orig.rot_y) > 1e-9:
                parts.append(f"rot_y={_fmt(orig.rot_y)} -> {_fmt(effective.rot_y)}")
            if abs(effective.rot_z - orig.rot_z) > 1e-9:
                parts.append(f"rot_z={_fmt(orig.rot_z)} -> {_fmt(effective.rot_z)}")
            if parts:
                cmt = " transform overridden: " + ", ".join(parts)
                parent_vol.append(ET.Comment(cmt))

        pv = ET.SubElement(parent_vol, "physvol")
        if pv_node.name:
            pv.set("name", pv_node.name)

        # volumeref (may reference a volume or assembly)
        vref = (pv_node.gdml_attrs or {}).get("volumeref")
        aref = (pv_node.gdml_attrs or {}).get("assemblyref")
        if not vref:
            vref = pv_node.ref_name
        if not vref and not aref:
            for c in pv_node.children:
                if c.node_type == GdmlNodeType.VOLUME_NODE and c.name:
                    vref = c.name
                    break
        if vref:
            ET.SubElement(pv, "volumeref").set("ref", vref)
        elif aref:
            ET.SubElement(pv, "volumeref").set("ref", aref)
        else:
            return  # invalid physvol

        # position — prefer original positionref when values are unchanged
        orig_pos = pv_node.placement or Placement()
        pv_positionref = (pv_node.gdml_attrs or {}).get("positionref")
        pos_changed = (
            abs(effective.x - orig_pos.x) > 1e-9 or
            abs(effective.y - orig_pos.y) > 1e-9 or
            abs(effective.z - orig_pos.z) > 1e-9
        )
        if pv_positionref and not pos_changed and not is_overridden:
            ET.SubElement(pv, "positionref").set("ref", pv_positionref)
        elif abs(effective.x) > 1e-9 or abs(effective.y) > 1e-9 or abs(effective.z) > 1e-9:
            pos = ET.SubElement(pv, "position")
            pos.set("name", f"pos_{pv_positionref or pv_node.ref_name or 'physvol'}")
            pos.set("x", _fmt(effective.x))
            pos.set("y", _fmt(effective.y))
            pos.set("z", _fmt(effective.z))
            pos.set("unit", effective.unit or "mm")

        # rotation — prefer original rotationref when values are unchanged
        orig_rot = pv_node.placement or Placement()
        pv_rotationref = (pv_node.gdml_attrs or {}).get("rotationref")
        rot_changed = (
            abs(effective.rot_x - orig_rot.rot_x) > 1e-9 or
            abs(effective.rot_y - orig_rot.rot_y) > 1e-9 or
            abs(effective.rot_z - orig_rot.rot_z) > 1e-9
        )
        if pv_rotationref and not rot_changed and not is_overridden:
            ET.SubElement(pv, "rotationref").set("ref", pv_rotationref)
        elif (abs(effective.rot_x) > 1e-9 or abs(effective.rot_y) > 1e-9 or
              abs(effective.rot_z) > 1e-9):
            rot = ET.SubElement(pv, "rotation")
            rot.set("name", f"rot_{pv_rotationref or pv_node.ref_name or 'physvol'}")
            rot.set("x", _fmt(effective.rot_x))
            rot.set("y", _fmt(effective.rot_y))
            rot.set("z", _fmt(effective.rot_z))
            rot.set("unit", effective.rot_unit or "deg")

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _find_world_node(fn: GdmlNode) -> Optional[GdmlNode]:
        for c in fn.children:
            if c.node_type == GdmlNodeType.WORLD_NODE:
                return c
            if c.node_type == GdmlNodeType.VOLUME_NODE:
                for cc in c.children:
                    if cc.node_type == GdmlNodeType.WORLD_NODE:
                        return cc
        return None

    @staticmethod
    def _find_world_volume(wn: GdmlNode) -> Optional[GdmlNode]:
        """The WORLD_NODE itself IS the volume (no child wrapper)."""
        if wn is None:
            return None
        return wn

    def _append_local_materials(self, mats: ET.Element) -> None:
        """Append user-defined local materials to the <materials> element.

        Custom elements → <element name="..." formula="..." Z="..."><atom/></element>
        Compounds      → <material name="..."><D/><composite n="..." ref="..."/>...</material>
        Mixtures       → <material name="..."><D/><fraction n="..." ref="..."/>...</material>
        """
        if self._mat_lib is None:
            return

        # Helper: check if a name already exists in the materials section
        existing = set()
        for child in mats:
            name = child.get("name")
            if name:
                existing.add(name)

        # 1. Custom elements → <element>
        for ce in self._mat_lib.get_all_custom_elements():
            if ce.name in existing:
                continue
            el = ET.SubElement(mats, "element")
            el.set("name", ce.name)
            if ce.symbol:
                el.set("formula", ce.symbol)
            el.set("Z", str(int(ce.atomic_number) if ce.atomic_number == int(ce.atomic_number) else ce.atomic_number))
            atom = ET.SubElement(el, "atom")
            atom.set("unit", "g/mole")
            atom.set("type", "A")
            atom.set("value", str(ce.atom_weight))

        # 2. Compounds → <material> with <composite>
        for comp in self._mat_lib.get_all_compounds():
            if comp.mat_name in existing:
                continue
            mat = ET.SubElement(mats, "material")
            mat.set("name", comp.mat_name)
            d = ET.SubElement(mat, "D")
            d.set("type", "density")
            d.set("unit", "g/cm3")
            d.set("value", str(comp.density))
            for i, c in enumerate(comp.components):
                comp_elem = ET.SubElement(mat, "composite")
                n_val = c.atom_count
                comp_elem.set("n", str(int(n_val) if n_val == int(n_val) else n_val))
                comp_elem.set("ref", c.symbol)

        # 3. Mixtures → <material> with <fraction>
        for mix in self._mat_lib.get_all_mixtures():
            if mix.mat_name in existing:
                continue
            mat = ET.SubElement(mats, "material")
            mat.set("name", mix.mat_name)
            d = ET.SubElement(mat, "D")
            d.set("type", "density")
            d.set("unit", "g/cm3")
            d.set("value", str(mix.density))
            total = sum(c.mass_fraction for c in mix.components)
            for c in mix.components:
                frac = c.mass_fraction / total if total > 0 else 0
                f_elem = ET.SubElement(mat, "fraction")
                f_elem.set("n", f"{frac:.6f}")
                f_elem.set("ref", c.symbol)


