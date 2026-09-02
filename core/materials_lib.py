"""
MaterialsLib -- Material library manager.

Provides three material sources:
1. NIST standard materials (G4_* prefix, read-only)
2. User-defined custom elements
3. User-defined compounds / mixtures

Reused from cad2gdml/core/materials_lib.py
"""

from typing import Dict, List, Optional, Tuple, Any
import os
import json


# ============================ Material Category Enum ============================

class MatCategory:
    """Material category enum."""
    CUSTOM = "custom"       # Custom element
    COMPOUND = "compound"   # Compound (atom count ratio)
    MIXTURE = "mixture"     # Mixture (mass fraction)
    NO_CATE = "no_cate"     # Uncategorized


# ============================ Data Structures ============================

class CompoundItem:
    """One element component in a compound (atom count ratio)."""
    def __init__(self, symbol: str, atom_count: float):
        self.symbol = symbol
        self.atom_count = atom_count

    def to_dict(self) -> Dict:
        return {"symbol": self.symbol, "atom_count": self.atom_count}

    @staticmethod
    def from_dict(d: Dict) -> 'CompoundItem':
        return CompoundItem(d["symbol"], d["atom_count"])


class MixtureItem:
    """One component in a mixture (mass fraction)."""
    def __init__(self, symbol: str, mass_fraction: float):
        self.symbol = symbol
        self.mass_fraction = mass_fraction

    def to_dict(self) -> Dict:
        return {"symbol": self.symbol, "mass_fraction": self.mass_fraction}

    @staticmethod
    def from_dict(d: Dict) -> 'MixtureItem':
        return MixtureItem(d["symbol"], d["mass_fraction"])


class CustomElement:
    """Custom element material."""
    def __init__(self, mat_id: str, name: str, symbol: str, density: float,
                 atom_weight: float, atomic_number: float):
        self.mat_id = mat_id
        self.name = name
        self.symbol = symbol
        self.density = density
        self.atom_weight = atom_weight
        self.atomic_number = atomic_number
        self.category = MatCategory.CUSTOM

    def to_dict(self) -> Dict:
        return {
            "mat_id": self.mat_id, "name": self.name, "symbol": self.symbol,
            "density": self.density, "atom_weight": self.atom_weight,
            "atomic_number": self.atomic_number, "category": self.category,
        }

    @staticmethod
    def from_dict(d: Dict) -> 'CustomElement':
        return CustomElement(d["mat_id"], d["name"], d["symbol"],
                             d["density"], d["atom_weight"], d["atomic_number"])


class CompoundMaterial:
    """Compound material (atom count ratio)."""
    def __init__(self, mat_id: str, mat_name: str, density: float,
                 components: List[CompoundItem]):
        self.mat_id = mat_id
        self.mat_name = mat_name
        self.density = density
        self.components = components
        self.category = MatCategory.COMPOUND

    def to_dict(self) -> Dict:
        return {
            "mat_id": self.mat_id, "mat_name": self.mat_name,
            "density": self.density, "category": self.category,
            "components": [c.to_dict() for c in self.components],
        }

    @staticmethod
    def from_dict(d: Dict) -> 'CompoundMaterial':
        comps = [CompoundItem.from_dict(c) for c in d.get("components", [])]
        return CompoundMaterial(d["mat_id"], d["mat_name"], d["density"], comps)


class MixtureMaterial:
    """Mixture material (mass fraction)."""
    def __init__(self, mat_id: str, mat_name: str, density: float,
                 components: List[MixtureItem]):
        self.mat_id = mat_id
        self.mat_name = mat_name
        self.density = density
        self.components = components
        self.category = MatCategory.MIXTURE

    def to_dict(self) -> Dict:
        return {
            "mat_id": self.mat_id, "mat_name": self.mat_name,
            "density": self.density, "category": self.category,
            "components": [c.to_dict() for c in self.components],
        }

    @staticmethod
    def from_dict(d: Dict) -> 'MixtureMaterial':
        comps = [MixtureItem.from_dict(c) for c in d.get("components", [])]
        return MixtureMaterial(d["mat_id"], d["mat_name"], d["density"], comps)


# ============================ Material Library Manager ============================

class MaterialsLib:
    """Singleton-style material library manager -- manages NIST materials, custom elements, compounds, and mixtures."""

    # Element database: symbol -> (Z, atom_weight)
    _ELEMENT_DB: Dict[str, Tuple[float, float]] = {}

    GDML_OUTPUT_ENABLED = True  # Toggle GDML output

    def __init__(self):
        self._nist_materials: Dict[str, Dict[str, Any]] = {}  # name -> info
        self._nist_left_list: List[str] = []  # NIST material names (available)
        self._nist_right_list: List[str] = []  # NIST material names (selected)

        self._custom_elements: Dict[str, 'CustomElement'] = {}
        self._compounds: Dict[str, 'CompoundMaterial'] = {}
        self._mixtures: Dict[str, 'MixtureMaterial'] = {}

        self._counter_id = 0

        # Initialize default materials (matches cad2gdml)
        self._init_default_materials()
        self._init_default_local_materials()

    # ========== ID Generation ==========

    def _next_id(self) -> str:
        self._counter_id += 1
        return f"mat_{self._counter_id}"

    def generate_id(self) -> str:
        """Generate a unique material ID (public wrapper for _next_id)."""
        return self._next_id()

    # ========== Element Data ==========

    @classmethod
    def load_elements_from_xml(cls, xml_path: str) -> int:
        """Load element data from element.xml."""
        import xml.etree.ElementTree as ET
        count = 0
        cls._ELEMENT_DB.clear()
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for elem in root.findall(".//element"):
                # Use 'formula' as symbol (e.g. "He"), NOT 'name' (e.g. "He_element")
                symbol = elem.get("formula", "").strip()
                z_str = elem.get("Z", "0").strip()
                a_str = elem.get("a", "0").strip()
                if symbol and z_str and a_str:
                    cls._ELEMENT_DB[symbol] = (float(z_str), float(a_str))
                    count += 1
        except Exception:
            pass
        return count

    @classmethod
    def get_atom_weight(cls, symbol: str) -> Optional[float]:
        """Get atomic weight for an element symbol."""
        entry = cls._ELEMENT_DB.get(symbol)
        return entry[1] if entry else None

    @classmethod
    def get_atomic_number(cls, symbol: str) -> Optional[float]:
        """Get atomic number for an element symbol."""
        entry = cls._ELEMENT_DB.get(symbol)
        return entry[0] if entry else None

    @classmethod
    def get_all_elements(cls) -> Dict[str, Tuple[float, float]]:
        """Get all elements: symbol -> (Z, atom_weight)."""
        return dict(cls._ELEMENT_DB)

    @classmethod
    def element_exists(cls, symbol: str) -> bool:
        return symbol in cls._ELEMENT_DB

    # ========== NIST Materials ==========

    def load_nist_from_file(self, filepath: str) -> int:
        """Load G4_ materials from nist.txt into NIST list (matches cad2gdml)."""
        count = 0
        loaded_names: List[str] = []
        self._nist_materials.clear()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    name = line.strip()
                    if name and name.startswith("G4_"):
                        loaded_names.append(name)
                        self._nist_materials[name] = {"density": 0.0}
                        count += 1
        except Exception:
            pass
        if loaded_names:
            self._nist_left_list = loaded_names[:]
        return count

    # ========== Default Materials (matches cad2gdml) ==========

    def _init_default_materials(self):
        """Initialize default NIST materials (7 common materials as fallback)."""
        defaults = [
            ("G4_AIR", 0.001205, "Air (dry, near sea level)"),
            ("G4_Al", 2.699, "Aluminum"),
            ("G4_Cu", 8.96, "Copper"),
            ("G4_Si", 2.329, "Silicon"),
            ("G4_WATER", 1.0, "Water"),
            ("G4_POLYETHYLENE", 0.94, "Polyethylene"),
            ("G4_Galactic", 1e-25, "Galactic vacuum"),
        ]
        self._nist_left_list = [name for name, _, _ in defaults]
        self._nist_right_list = self._nist_left_list[:]
        for name, density, _ in defaults:
            self._nist_materials[name] = {"density": density}

    def _init_default_local_materials(self):
        """Initialize default local materials (matches cad2gdml)."""
        # Default compound: water (H2O)
        water_compounds = [
            CompoundItem(symbol="H", atom_count=2),
            CompoundItem(symbol="O", atom_count=1),
        ]
        water = CompoundMaterial(
            mat_id=self._next_id(),
            mat_name="water",
            density=1.0,
            components=water_compounds,
        )
        self.add_compound(water)

        # Default mixture: air_user
        air_components = [
            MixtureItem(symbol="N", mass_fraction=0.75),
            MixtureItem(symbol="O", mass_fraction=0.25),
        ]
        air = MixtureMaterial(
            mat_id=self._next_id(),
            mat_name="air_user",
            density=0.001205,
            components=air_components,
        )
        self.add_mixture(air)

    def get_nist_list(self) -> List[str]:
        return self._nist_left_list

    def get_nist_left_list(self) -> List[str]:
        return self._nist_left_list

    def get_nist_density(self, mat_name: str) -> Optional[float]:
        entry = self._nist_materials.get(mat_name)
        return entry["density"] if entry else None

    def is_nist_material(self, mat_name: str) -> bool:
        return mat_name in self._nist_materials

    # ========== Custom Elements ==========

    def add_custom_element(self, mat: CustomElement):
        self._custom_elements[mat.mat_id] = mat

    def get_custom_element(self, mat_id: str) -> Optional[CustomElement]:
        return self._custom_elements.get(mat_id)

    def get_all_custom_elements(self) -> List[CustomElement]:
        return list(self._custom_elements.values())

    def delete_custom_element(self, mat_id: str) -> bool:
        if mat_id in self._custom_elements:
            del self._custom_elements[mat_id]
            return True
        return False

    # ========== Compounds ==========

    def add_compound(self, mat: CompoundMaterial):
        self._compounds[mat.mat_id] = mat

    def get_compound(self, mat_id: str) -> Optional[CompoundMaterial]:
        return self._compounds.get(mat_id)

    def get_all_compounds(self) -> List[CompoundMaterial]:
        return list(self._compounds.values())

    def delete_compound(self, mat_id: str) -> bool:
        if mat_id in self._compounds:
            del self._compounds[mat_id]
            return True
        return False

    # ========== Mixtures ==========

    def add_mixture(self, mat: MixtureMaterial):
        self._mixtures[mat.mat_id] = mat

    def get_mixture(self, mat_id: str) -> Optional[MixtureMaterial]:
        return self._mixtures.get(mat_id)

    def get_all_mixtures(self) -> List[MixtureMaterial]:
        return list(self._mixtures.values())

    def delete_mixture(self, mat_id: str) -> bool:
        if mat_id in self._mixtures:
            del self._mixtures[mat_id]
            return True
        return False

    # ========== General Methods ==========

    def get_all_local_materials(self) -> List[Any]:
        """Get all user-defined local materials (for tree display)."""
        result: List[Any] = []
        result.extend(self._custom_elements.values())
        result.extend(self._compounds.values())
        result.extend(self._mixtures.values())
        return result

    def get_local_material_by_id(self, mat_id: str) -> Optional[Any]:
        """Look up a local material by mat_id across all material types."""
        if mat_id in self._custom_elements:
            return self._custom_elements[mat_id]
        if mat_id in self._compounds:
            return self._compounds[mat_id]
        if mat_id in self._mixtures:
            return self._mixtures[mat_id]
        return None

    def get_local_material_names(self) -> List[str]:
        """Get all local material names."""
        names = []
        for ele in self._custom_elements.values():
            names.append(ele.name)
        for mat in self._compounds.values():
            names.append(mat.mat_name)
        for mat in self._mixtures.values():
            names.append(mat.mat_name)
        return names

    def delete_material(self, mat_id: str) -> bool:
        """Try to delete a material by ID from all categories."""
        return (self.delete_custom_element(mat_id)
                or self.delete_compound(mat_id)
                or self.delete_mixture(mat_id))

    def clear_all_local(self):
        self._custom_elements.clear()
        self._compounds.clear()
        self._mixtures.clear()

    # ========== GDML String Generation ==========

    def to_gdml_string(self, mat_id: str, indent: str = "    ") -> str:
        """Generate a GDML <material> XML string for a local material by ID."""
        # Custom element
        elem = self._custom_elements.get(mat_id)
        if elem:
            formula = self._find_formula(elem.atom_weight)
            return (
                f'{indent}<material name="{elem.name}">\n'
                f'{indent}  <D value="{elem.density}" unit="g/cm3"/>\n'
                f'{indent}  <fraction n="{formula}" ref="{elem.symbol}"/>\n'
                f'{indent}</material>'
            )

        # Compound
        comp = self._compounds.get(mat_id)
        if comp:
            lines = [
                f'{indent}<material name="{comp.mat_name}">',
                f'{indent}  <D value="{comp.density}" unit="g/cm3"/>',
                f'{indent}  <composite n="1" ref="{comp.components[0].symbol}"/>',
            ]
            for c in comp.components[1:]:
                lines.append(f'{indent}  <composite n="{c.atom_count}" ref="{c.symbol}"/>')
            lines.append(f'{indent}</material>')
            return "\n".join(lines)

        # Mixture
        mix = self._mixtures.get(mat_id)
        if mix:
            lines = [
                f'{indent}<material name="{mix.mat_name}">',
                f'{indent}  <D value="{mix.density}" unit="g/cm3"/>',
            ]
            total = sum(c.mass_fraction for c in mix.components)
            for c in mix.components:
                frac = c.mass_fraction / total if total > 0 else 0
                lines.append(f'{indent}  <fraction n="{frac:.6f}" ref="{c.symbol}"/>')
            lines.append(f'{indent}</material>')
            return "\n".join(lines)

        return ""

    @staticmethod
    def _find_formula(atom_weight: float) -> str:
        """Guess simplified formula based on atomic weight (display only)."""
        if abs(atom_weight - 1.00794) < 0.01:
            return "1"
        return "1.0"

    # ========== JSON Serialization ==========

    def save_local_materials_to_json(self, filepath: str) -> bool:
        """Save all local materials to a JSON file."""
        try:
            data = {
                "custom_elements": [e.to_dict() for e in self._custom_elements.values()],
                "compounds": [c.to_dict() for c in self._compounds.values()],
                "mixtures": [m.to_dict() for m in self._mixtures.values()],
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def load_local_materials_from_json(self, filepath: str) -> int:
        """Load local materials from a JSON file. Returns count of loaded items."""
        count = 0
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            for d in data.get("custom_elements", []):
                self._custom_elements[d["mat_id"]] = CustomElement.from_dict(d)
                count += 1
            for d in data.get("compounds", []):
                self._compounds[d["mat_id"]] = CompoundMaterial.from_dict(d)
                count += 1
            for d in data.get("mixtures", []):
                self._mixtures[d["mat_id"]] = MixtureMaterial.from_dict(d)
                count += 1
        except Exception:
            pass
        return count
