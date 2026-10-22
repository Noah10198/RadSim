# 02 · GDML Pipeline

> Source: `core/gdml_parser.py`, `core/gdml_tree.py`, `core/gdml_evaluator.py`,
> `core/gdml_writer.py`, `core/materials_lib.py`, `core/collision_detector.py`, `core/gdml_agent.py`

## Contents

- [1. Pipeline overview](#1-pipeline-overview)
- [2. GdmIParser](#2-gdmlparser)
- [3. GdmlNode and Placement](#3-gdmlnode-and-placement)
- [4. GdmIEvaluator](#4-gdmievaluator)
- [5. GdmlWriter](#5-gdmlwriter)
- [6. MaterialsLib](#6-materialslib)
- [7. CollisionDetector](#7-collisiondetector)
- [8. Units and precision](#8-units-and-precision)
- [9. Known limitations](#9-known-limitations)

## 1. Pipeline overview

```
.gdml file
   │  GdmIParser.parse_file()
   ▼
GdmlNode tree (VOLUME_NODE logical volumes + PHYVOL_NODE placements + SOLID_DEF)
   │  ├─ GdmIEvaluator      evaluates attribute expressions
   │  ├─ VtkSolidFactory → VtkScene   3D rendering
   │  └─ GdmlAgent         the single facade (singleton)
   ▼
GdmlWriter.write()  →  merged / overridden .gdml (what the solver reads)
```

Design stance: **whatever is parsed must be writable back without loss**. Every node therefore
keeps, besides its structured parameters (`solid_params`), the original XML fragments
(`raw_solid_xml`, `raw_define_xml`, …). Writing prefers the original text and only regenerates
what the user actually changed, so complex solids such as `polycone`, `xtru` and the boolean
solids survive a round trip untouched.

## 2. GdmIParser

### Parse sequence

`GdmIParser.parse_file(filepath) -> GdmlNode`:

1. parse `<define>` → collect constants, positions and rotations;
2. parse `<materials>` → record material name and density (simplified for the MVP);
3. parse `<solids>` → one `SOLID_DEF` node per solid, parameters normalized to **mm**;
4. parse `<structure>` → one `VOLUME_NODE` per `<volume>` (the logical-volume store),
   each `<physvol>` expanded into a `PHYVOL_NODE` placement;
5. parse `<setup>` → record the world reference.

### Solid parsers

| Method | GDML tag |
|---|---|
| `_parse_box` | `box` |
| `_parse_sphere` | `sphere` |
| `_parse_orb` | `orb` |
| `_parse_tube` | `tube` |
| `_parse_cone` | `cone` (G4Cons) |
| `_parse_torus` | `torus` |
| `_parse_ellipsoid` | `ellipsoid` |
| `_parse_polycone` | `polycone` (keeps the raw `<zplane>` XML) |
| `_parse_tessellated` | `tessellated` |

Every other solid type produces no structured parameters, but is recorded and its original XML
kept verbatim, so writing back copies it as it was.

### Instantiation semantics (key design)

Modelled on Geant4's two-level scheme:

- `VOLUME_NODE` = `G4LogicalVolume`: it exists only in the store and is **never rendered
  directly**;
- `PHYVOL_NODE` = `G4PVPlacement`: `_clone_volume_instance()` / `_clone_physvol()` clone the whole
  subtree recursively, so every instance carries its own `Placement`.

A logical volume placed N times therefore yields N independent instances in the tree, each of
which can be moved, shown or hidden on its own — exactly matching what the 3D view shows.

`<assembly>` is handled by `_parse_assembly()` and produces nodes of type `ASSEMBLY_NODE`.

### Error handling

- a root element that is not GDML raises `ValueError`;
- a missing XML declaration, an unevaluable constant or a missing vertex degrade silently instead
  of aborting the whole import;
- unsupported solid types are merely recorded (`_unsupported_solids`) and surfaced to the UI by
  `GdmlAgent.get_unsupported_solids()`.

## 3. GdmlNode and Placement

`GdmlNode` derives from `QObject` and carries `data_changed = pyqtSignal()`, the single trigger for
refreshing the UI.

| Attribute | Meaning |
|---|---|
| `node_type` | `GdmlNodeType` |
| `name` / `entry_id` | name and unique id (`GDM_xxx`, used to look up overrides) |
| `gdml_tag` / `gdml_attrs` | original tag name and original XML attributes |
| `solid_params` | parsed numeric parameters (**mm / deg**) |
| `material_name` | material name |
| `placement` | `Placement`, meaningful for `PHYVOL_NODE` only |
| `file_transform` | `Placement`, meaningful for `GDML_FILE` only: whole-file translation/rotation |
| `ref_name` | the referenced name of `volumeref` / `solidref` |
| `vtk_actor` / `visible` | render object and visibility |
| `raw_*_xml` | original XML fragments (declaration / define / materials / setup / solid) |
| `parent` / `children` | the tree structure |

`GdmlNodeType` values: `DONT_CARE`, `ROOT_NODE`, `GDML_FILE`, `DEFINE_NODE`, `MATERIAL_NODE`,
`SOLID_DEF`, `VOLUME_NODE`, `PHYVOL_NODE`, `ASSEMBLY_NODE`, `WORLD_NODE`, `BOOLEAN_NODE`,
`AUX_NODE`. Of these, `DEFINE_NODE` / `MATERIAL_NODE` / `BOOLEAN_NODE` / `AUX_NODE` are reserved
values that the parser does not currently produce.

`Placement` is a dataclass: `x/y/z` (mm), `rot_x/rot_y/rot_z` (deg), `unit`, `rot_unit`.

Tree API: `add_child` / `remove_child` / `get_child_count` / `is_leaf` / `get_all_descendants` /
`get_leaf_nodes` / `find_node_by_name`.

## 4. GdmIEvaluator

GDML attributes may be expressions, e.g. `2.*pi`, `9825-DOFFSET`, `PCOLL2_THICK/2+5`.

- predefined constants: `pi`, `PI`, `HALFPI`, `TWOPI`;
- user constants: `set_constant` / `set_constants` (from `constant` elements in `<define>`);
- arithmetic, parentheses and unary minus are supported;
- substitution walks names in **descending length order** so that `PI` cannot be damaged by the
  substring rule for `HALFPI`;
- evaluation runs sandboxed through `eval(expr, {"__builtins__": {}}, math.__dict__)`, with
  builtins disabled.

⚠️ **An undefined identifier is replaced by `0`** rather than raising. That lets dirty GDML files
be imported, but silently hides a broken reference — when a dimension looks wrong, suspect this
first.

## 5. GdmlWriter

```python
writer.write(root_node, placement_overrides, filepath, mat_lib=None)
```

| Mechanism | Notes |
|---|---|
| Single vs multiple files | `_export_single` writes one GDML file; `_export_multi` merges several into one (collecting each file's world, solids and defines, then de-duplicating) |
| Placement overrides | `placement_overrides` maps `entry_id → Placement`; `_get_effective()` prefers the override and marks the overridden physvol with a comment for manual checking |
| File-level transform | when a file node has a `file_transform`, `_wrap_world_volume()` emits a wrapping world volume that carries the whole-file translation/rotation |
| De-duplication | the three sets `_used_names` / `_written_vols` / `_written_solids` prevent writing the same volume or solid twice |
| Local materials | `_append_local_materials()` writes user-defined elements, compounds and mixtures into `<materials>` |
| Unit declarations | always `lunit="mm"`, `aunit="deg"`, position `unit="mm"`, rotation `unit="deg"` |
| Numeric precision | `_fmt()` uses `f"{v:.6g}"`, six significant digits |

> Note: `GdmlWriter` and `MaterialsLib` are currently referenced from inside `core/` only — the UI
> layer is not wired to them yet. They are *implemented but not yet integrated*.

## 6. MaterialsLib

Data sources:

- `data/element.xml` → the element database `_ELEMENT_DB: symbol → (Z, atom_weight)`;
- `data/nist.txt` → the NIST material list (the `G4_` prefix);
- fallback: seven built-in common materials (`G4_AIR`, `G4_Al`, …) and a default compound (water).

Three kinds of user material:

| Kind | Class | Expressed as |
|---|---|---|
| Custom element | `CustomElement` | name, symbol, density, atomic weight, atomic number |
| Compound | `CompoundMaterial` + `CompoundItem` | atom-count ratio |
| Mixture | `MixtureMaterial` + `MixtureItem` | mass fraction (normalized to six decimals) |

Main API: `load_elements_from_xml`, `load_nist_from_file`, `get_atom_weight`,
`get_atomic_number`, `get_nist_list`, `get_nist_density`, `add_custom_element` / `add_compound` /
`add_mixture` with the matching `get_all_*` / `delete_*`, and `generate_id()`. Every class
implements `to_dict()` / `from_dict()` for serialization.

Density is in **g/cm³**, atomic weight in **g/mole**.

## 7. CollisionDetector

`core/collision_detector.py` provides AABB (axis-aligned bounding box) pre-filtering:

| Function | Purpose |
|---|---|
| `compute_half_size(node)` | derive the half size from `solid_params` |
| `compute_world_aabb(node, ...)` | transform the eight corners into world space with the VTK matrix and take the bounding box |
| `compute_world_transform(node, override_provider=None)` | accumulate translation and Euler angles up the parent chain, returning `(tx,ty,tz,rx,ry,rz)` |
| `aabb_overlap(a, b)` | box-box intersection test |
| `generate_full_pairs(nodes)` | all-pairs combination |
| `generate_sampled_pairs(nodes)` | random sample of about 5 % (minimum 2, maximum 50), guaranteeing at least one cross-file pair when several files are loaded |

`GdmlAgent` uses it to compute the scene, volume and world bounding boxes. Full pairwise collision
detection is not wired into the UI yet — it is a reserved capability — and
`GdmlAgent._local_aabb` holds an equivalent local AABB implementation, so the two overlap.

## 8. Units and precision

| Item | Convention |
|---|---|
| Length | **mm** internally; `_LENGTH_UNITS` converts cm/m/um/nm/km on parse |
| Angle | **deg**; rad is converted automatically |
| Write-back | declares `lunit="mm"` and `aunit="deg"` explicitly |
| Density | g/cm³ |
| Atomic weight | g/mole |
| Numeric output | six significant digits; change threshold `1e-9`, rotation threshold `1e-6` |

## 9. Known limitations

- `<materials>` parsing records only the name and density; the internal composition of a material
  is not parsed;
- an undefined identifier in an expression silently becomes `0`;
- `GdmIEvaluator` caches nothing, so frequent calls re-evaluate;
- `GdmlAgent` reuses a single `GdmIParser` instance and the parser holds mutable state, so
  `parse_file_only` is thread-safe only as long as calls stay serial (today there is one
  background thread);
- `get_all_descendants()` recurses the whole tree on every call — mind the call count on very
  large models.
