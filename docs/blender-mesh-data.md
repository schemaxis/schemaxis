# Mesh fields and named texture coordinates

`production.meshData` attaches scientific fields and UV sets to mesh prototypes
before Geometry Nodes, animation and output evaluation. Use the standalone
[editable panel](../examples/schemaxis/blender-mesh-fields.json) to combine a
vertex displacement field, a colour shader, two UV sets and a physical GLB handoff.
It uses the existing production route and the same controls in Studio.

```json
{"object":"panel","sharing":"copy",
 "attributes":[
   {"name":"temperature","kind":"float","domain":"POINT","mode":"dense",
    "values":[300,310,320,310]},
   {"name":"zone","kind":"integer","domain":"FACE","mode":"constant","value":7},
   {"name":"selected","kind":"boolean","domain":"POINT","mode":"sparse",
    "default":false,"entries":[{"index":2,"value":true}]}],
 "uvMaps":[{"name":"Label","method":"planar","axis":"Z","size":[40,30]},
           {"name":"Atlas","method":"smart","pack":true,
            "textureSize":[1024,512],"paddingPixels":8}],
 "activeUV":"Label","renderUV":"Label"}
```

The example assumes four vertices and one face. Every dense field must match its
selected domain. Names are shared across attributes and UV maps and are limited
to63 UTF-8 bytes. Internal dot names and built-in topology attributes are refused.
At most128 attributes and8 UV sets can be authored per target, with bounded
mesh element and total value counts. The native project retains unrelated fields.

| Domain | Element order |
| --- | --- |
| POINT | Mesh vertices, in authored/source order |
| EDGE | Lexicographically sorted undirected vertex endpoint pairs |
| FACE | Mesh polygons, in authored/source order |
| CORNER | Every face's corners concatenated in polygon order |

Topology-changing source edits require remapping indexed fields. This is explicit
field storage on the original mesh; it does not promise stable selections through
arbitrary remeshing. Imported mesh counts are checked before any channel writes.

| Kind | Stored meaning |
| --- | --- |
| float | float32 scalar; scientific units belong to the field definition |
| integer | Signed32-bit categorical/index value |
| boolean | Native true/false selection |
| vector | Three original mesh-local components; displacement uses mesh coordinate units |
| colour | Linear RGBA in0–1 |
| byteColour | Integer sRGBA bytes0–255, with linear alpha and native quantization |
| vector2 | Two floats; CORNER uses `uvMaps` instead |
| quaternion | Normalized(w,x,y,z) rotation, not Euler angles |

`constant` repeats `value`. `dense` supplies ordered `values`. `sparse` requires a
`default` and unique indexed `entries`; missing scientific samples are never
silently assumed zero. A Geometry Nodes `namedAttribute` reader uses `dataType`
FLOAT, INT, BOOLEAN, FLOAT_VECTOR, FLOAT_COLOR or QUATERNION with the corresponding
typed output. Vector2 storage remains available; the supported native reader
has no FLOAT2 output. A shader `attribute` reader selects `properties.name` and
exposes colour/vector/factor/alpha. Authors choose the scientific colour mapping;
reading a temperature does not invent its scale or range.

## Selection and shared mesh data

`object` names a public mesh, mesh instance or asset root. A root containing
exactly one mesh can infer that prototype. For a packed native source with
several meshes, `sourceObject` selects its original Object name. For GLB/glTF it selects a unique named mesh node from the captured source JSON. The source name
must exist and must not have collided with an Object already loaded during append;
ambiguous post-append suffixes are refused. Rename the source Object or use a
unique source library. Other neutral formats currently infer a target only when they contain a single mesh. Duplicate or importer-renamed glTF node identities are refused.

`sharing` defaults to `refuse`: a Mesh with several Object owners requires an
explicit decision. `copy` isolates the selected Object's mesh. `shared` deliberately
updates every Object owner of that Mesh, including other collection prototypes.
All declarations are resolved and checked before mutation. Explicit copies are
isolated before shared writes; conflicting writes to the same remaining shared
Mesh are refused. Multiple selectors resolving to one Object are refused.

An Object occurring in several collection instances is still one prototype.
Copying its data affects all those occurrences; there is no per-instance mesh
edit promise. Collection ownership, source parents and instance references remain
intact. UV operators edit the selected Object in a temporary isolated scene and
return it to the original scene context. They do not flatten imported collections.

## UV construction and packing

Each `uvMaps` entry names a coordinate set and chooses a method:

- `coordinates`: one2D coordinate per face corner, including separate seam values.
- `planar`: object-local XY(Z), XZ(Y) or YZ(X) projection. Subtract `origin`, then
  divide by the two positive `size` spans in original mesh coordinate units. It does not fit
  automatically to the bounding box.
- `box`: project each face along its dominant normal axis using XYZ `size` and
  `origin`. Ties use X, then Y, then Z. Coordinates can overlap intentionally.
- `smart`: native angle splitting, with `angle` in radians(default66degrees) and
  `areaWeight` from0 to1.
- `unwrap`: seam-based native CONFORMAL(default), ANGLE_BASED or MINIMUM_STRETCH
  solving. `seams` lists unique real mesh-edge endpoint pairs. `fillHoles`
  defaults true; `iterations` bounds the minimum-stretch solver.

Seam flags belong to the Mesh, so unwrap sets on one Mesh must agree on the seam
list. Omitting seams clears them for the unwrap. Object transforms and modifiers
are not applied to the original topology when mapping it. Imported mesh coordinates retain their source numerical units; a metre-valued GLB inside a millimetre scene still uses metre-valued local projection spans. Parent/asset scale is intentionally excluded from mesh-local fields and UV projection.

`pack:true` packs islands in tile0–1. `textureSize` supplies intended raster
width,height(default1024×1024); `paddingPixels` defaults4. The smaller dimension
converts pixels to a conservative tile-space margin. `rotate:false` preserves
island orientation during packing. Packing changes coordinate scale and placement,
including explicit/projection coordinates. It cannot repair self-overlapping
parameterizations or invent seam cuts for a closed surface. Texture baking, UDIM
layout, sculpting and painting remain separate unfinished workflow families.

Production verification checks unit-tile bounds and deterministic native packing
from the retained recipe. Independent pixel clearance and non-overlap are qualified
on the bounded disconnected-island fixtures across the three unwrap solvers,
including non-square textures. This is not an independent clearance proof for
arbitrary authored polygons or self-overlapping parameterizations.

`activeUV` selects the editable set; `renderUV` selects the default shader set.
Both default to the first declared map. A shader `uvMap` reader can name another
set explicitly through `properties.name`, feeding `uv` into image/checker/mapping
vectors. The older mesh constructor's single `uv` array still represents UVMap
and is checked independently of which newer set becomes active.

## Save, edit and handoff

All channels and coordinate sets are saved as ordinary native mesh data. Current
project bytes are reopened in a fresh trusted Blender process during verification;
changing a field, seam, coordinate, sharing relationship or reader binding cannot
be accepted by merely refreshing the file hash. Adopt a deliberately edited native
project as a new input rather than pretending its old recipe is unchanged.

Native `.blend` keeps editable channels and topology. Evaluated GLB/USD/OBJ/PLY/STL
publications keep their declared geometry and unit policy; arbitrary scientific
attributes, quaternion fields, UV sets and materials are not promised across all
formats. Keep the native project alongside neutral geometry when those channels
are required downstream. Exports bake evaluated deformation; a successful export
does not establish scientific-field preservation in a format that drops it.

`INVALID_MESH_DATA` means fix channel names, shapes, domain indices, quaternion
normalization or mapping controls. `SHARED_MESH_DATA` requires an explicit copy or
shared decision and one coherent write per shared Mesh. `AMBIGUOUS_MESH_TARGET`
requires a unique native source selector or a single-mesh neutral asset.
`UV_MAPPING_FAILED` retains the native log; simplify topology/seams and retry in a
fresh run. Do not relax verification after a native mapping error.

API basis: [Mesh attributes](https://docs.blender.org/api/current/bpy.types.Attribute.html),
[UV operators](https://docs.blender.org/api/current/bpy.ops.uv.html),
[UV layers](https://docs.blender.org/api/current/bpy.types.UVLoopLayers.html), and
[Named Attribute](https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/input/named_attribute.html).
The recorded implementation baseline is Blender5.2.3 LTS; rolling URLs do not
change that pinned qualification baseline.
