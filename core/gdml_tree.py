"""
GdmlNode - GDML Data Node Tree

Corresponds to cad2gdml's GDataNode design, tailored for GDML data structures.
Each node can be a GDML file, volume, solid, physvol, etc.,
with associated VTK render objects, materials, placement info, etc.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal


class GdmlNodeType(Enum):
    """Node type enumeration"""
    DONT_CARE = 0
    ROOT_NODE = 1      # Root node "GDML Editor Root"
    GDML_FILE = 2      # Single GDML file
    DEFINE_NODE = 3    # <define> section
    MATERIAL_NODE = 4  # <materials> section
    SOLID_DEF = 5      # Solid definition in <solids>
    VOLUME_NODE = 6    # <volume>
    PHYVOL_NODE = 7    # <physvol> (physical volume placement)
    ASSEMBLY_NODE = 8  # <assembly>
    WORLD_NODE = 9     # <world> reference
    BOOLEAN_NODE = 10  # union/subtraction/intersection
    AUX_NODE = 11      # auxiliary info


@dataclass
class Placement:
    """Physical volume placement info"""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rot_x: float = 0.0  # degrees
    rot_y: float = 0.0
    rot_z: float = 0.0
    unit: str = "mm"
    rot_unit: str = "deg"


class GdmlNode(QObject):
    """
    GDML data node

    Encapsulates a node in the GDML geometry tree, including parsed parameters,
    VTK render objects, materials, placement info, etc.
    Nodes can have children, forming a tree structure.
    """

    data_changed = pyqtSignal()

    def __init__(self, node_type: GdmlNodeType = GdmlNodeType.DONT_CARE, name: str = ""):
        super().__init__()
        self._node_type = node_type
        self._name = name

        # Original GDML info (for export)
        self._gdml_tag: str = ""           # "box", "cone", "tube", "tessellated", etc.
        self._gdml_attrs: Dict[str, str] = {}  # Raw XML attributes, preserved for export

        # Solid parameters (parsed values, in mm)
        self._solid_params: Dict[str, float] = {}

        # Material
        self._material_name: str = ""

        # Placement (only needed for PHYVOL_NODE)
        self._placement: Optional[Placement] = None

        # VTK related
        self._vtk_actor = None        # vtkActor
        self._visible: bool = True

        # Tree structure
        self._parent: Optional['GdmlNode'] = None
        self._children: List['GdmlNode'] = []
        self._entry_id: str = ""

        # File-level transform (only used by GDML_FILE nodes)
        # Allows translating/rotating an entire imported file's geometry as a group
        self._file_transform: Optional[Placement] = None

        # Reference relations: volume references solid; physvol references volume
        self._ref_name: str = ""  # e.g. volumeref or solidref ref attribute value

        # Raw XML of top-level sections (stored by parser for export fidelity)
        self._raw_declaration: str = ""      # <?xml version="1.0" ... ?>
        self._raw_define_xml: str = ""       # <define>...</define>
        self._raw_materials_xml: str = ""    # <materials>...</materials>
        self._raw_setup_xml: str = ""        # <setup>...</setup>

        # Raw XML of the solid element (for complex solids with sub-elements)
        # Used by writer for perfect round-trip of polycone/xtru/boolean etc.
        self._raw_solid_xml: str = ""

    # ---- Properties ----

    @property
    def node_type(self) -> GdmlNodeType:
        return self._node_type

    @node_type.setter
    def node_type(self, val: GdmlNodeType):
        self._node_type = val

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, val: str):
        self._name = val

    @property
    def gdml_tag(self) -> str:
        return self._gdml_tag

    @gdml_tag.setter
    def gdml_tag(self, val: str):
        self._gdml_tag = val

    @property
    def gdml_attrs(self) -> Dict[str, str]:
        return self._gdml_attrs

    @gdml_attrs.setter
    def gdml_attrs(self, val: Dict[str, str]):
        self._gdml_attrs = val

    @property
    def solid_params(self) -> Dict[str, float]:
        return self._solid_params

    @solid_params.setter
    def solid_params(self, val: Dict[str, float]):
        self._solid_params = val

    @property
    def material_name(self) -> str:
        return self._material_name

    @material_name.setter
    def material_name(self, val: str):
        self._material_name = val

    @property
    def placement(self) -> Optional[Placement]:
        return self._placement

    @placement.setter
    def placement(self, val: Optional[Placement]):
        self._placement = val

    @property
    def file_transform(self) -> Optional[Placement]:
        """
        File-level transform (GDML_FILE nodes only).
        Translates/rotates ALL geometry in this file as a single group.
        Returns None if no file transform is set.
        """
        return self._file_transform

    @file_transform.setter
    def file_transform(self, val: Optional[Placement]):
        self._file_transform = val

    @property
    def vtk_actor(self):
        """Get VTK Actor"""
        return self._vtk_actor

    @vtk_actor.setter
    def vtk_actor(self, val):
        self._vtk_actor = val

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, val: bool):
        self._visible = val

    @property
    def ref_name(self) -> str:
        return self._ref_name

    @ref_name.setter
    def ref_name(self, val: str):
        self._ref_name = val

    @property
    def raw_declaration(self) -> str:
        return self._raw_declaration

    @raw_declaration.setter
    def raw_declaration(self, val: str):
        self._raw_declaration = val

    @property
    def raw_define_xml(self) -> str:
        return self._raw_define_xml

    @raw_define_xml.setter
    def raw_define_xml(self, val: str):
        self._raw_define_xml = val

    @property
    def raw_materials_xml(self) -> str:
        return self._raw_materials_xml

    @raw_materials_xml.setter
    def raw_materials_xml(self, val: str):
        self._raw_materials_xml = val

    @property
    def raw_setup_xml(self) -> str:
        return self._raw_setup_xml

    @raw_setup_xml.setter
    def raw_setup_xml(self, val: str):
        self._raw_setup_xml = val

    @property
    def raw_solid_xml(self) -> str:
        return self._raw_solid_xml

    @raw_solid_xml.setter
    def raw_solid_xml(self, val: str):
        self._raw_solid_xml = val

    @property
    def entry_id(self) -> str:
        return self._entry_id

    @entry_id.setter
    def entry_id(self, val: str):
        self._entry_id = val

    # ---- Tree operations ----

    @property
    def parent(self) -> Optional['GdmlNode']:
        return self._parent

    @property
    def children(self) -> List['GdmlNode']:
        return self._children.copy()

    def add_child(self, child: 'GdmlNode'):
        """Add child node; removes from old parent first if already attached"""
        if child._parent is not None:
            if child in child._parent._children:
                child._parent._children.remove(child)
        child._parent = self
        self._children.append(child)

    def remove_child(self, child: 'GdmlNode'):
        if child in self._children:
            self._children.remove(child)
            child._parent = None

    def get_child_count(self) -> int:
        return len(self._children)

    def is_leaf(self) -> bool:
        return len(self._children) == 0

    def get_all_descendants(self) -> List['GdmlNode']:
        result = []
        for child in self._children:
            result.append(child)
            result.extend(child.get_all_descendants())
        return result

    def get_leaf_nodes(self) -> List['GdmlNode']:
        result = []
        for child in self._children:
            if child.is_leaf():
                result.append(child)
            else:
                result.extend(child.get_leaf_nodes())
        return result

    def find_node_by_name(self, name: str) -> Optional['GdmlNode']:
        """Find descendant node by name"""
        if self._name == name:
            return self
        for child in self._children:
            found = child.find_node_by_name(name)
            if found:
                return found
        return None

    def __repr__(self) -> str:
        return (f"GdmlNode(name='{self._name}', type={self._node_type}, "
                f"gdml_tag='{self._gdml_tag}', entry_id='{self._entry_id}')")
