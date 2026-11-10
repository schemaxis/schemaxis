# Prepare an STL mesh as a Part solid

`importMesh` converts one closed STL into a faceted native Part solid. Use it to
prepare a triangulated casting, scan-derived closed solid or exchanged mesh for
Part booleans and STEP handoff. It preserves the admitted triangles before any
optional face refinement. It does not recover analytical surfaces or the original
feature history.

```json
{"version":"schemaxis.freecad/1","nodes":[
  {"id":"casting","filter":"importMesh","options":{
    "file":"casting.stl","units":"mm","refine":true}},
  {"id":"drill","filter":"cylinder","options":{
    "radius":2.5,"height":30,"origin":[21,10,-5]}},
  {"id":"bracket","filter":"cut","inputs":{
    "base":"casting","tool":"drill"}}
],"output":"bracket"}
```

STL does not assign length units. Required `units` scales file coordinates from
`mm`, `cm`, `m` or `inch` into millimetres. This differs from `importSTEP`, where
units assert what the STEP file declares. Binary STL coordinates have their
original single-precision quantization; conversion cannot recover lost precision.
ASCII STL accepts finite decimal/exponent numbers. Declared normals and binary
colour attributes do not establish the solid: vertex winding does.

`reverseWinding: true` reverses every triangle. Use it for a consistently inverted
mesh. It does not repair mixed local winding. Outer shells must face outward and
cavity shells inward. The host refuses open, repeated, degenerate or nonmanifold
facets and disconnected vertex fans. Native valid-solid and BOP checks also
refuse disconnected solids, intersecting shells and incorrect cavity orientation.
No automatic healing or remeshing occurs.

`orientation` maps file axes into part axes. Its `z` is required when changing
up direction; supply a perpendicular signed `x` axis for a non-Z up direction.
`placement.position` then translates the part in world millimetres and
`placement.clocking` rotates it about world Z in degrees. For example:

```json
{"orientation":{"z":"+Y","x":"-X"},
 "placement":{"position":[45,-20,13],"clocking":31}}
```

The native source is a static `Part::Feature` with editable Placement. Optional
`refine: true` adds a linked `Part::Refine` to merge redundant coplanar faces;
verification checks that its material set stays unchanged. Subsequent native
Part cuts, unions and intersections retain their ordinary feature links. Editing
the original STL requires a new authored run. Source capture retains exact bytes,
so verification and reuse keep working after the original file is removed.
Native edits form changed designs and do not make an old receipt valid for them.

Each STL is bounded to 32 MiB, and all mesh imports together to 20,000 facets.
Converted coordinates must stay within 100,000 mm on each axis. These are
admission ceilings; difficult geometry can still exhaust the configured run
budget. A timeout or invalid solid is a refusal, never a partial verified result.

Saved verification reads only bounded geometry payloads from the submitted FCStd.
It binds each unrefined triangle, vertex and winding to independently parsed
captured STL, including the saved BREP's Placement. A trusted installed worker
also reconstructs the complete typed Part graph and binds saved object/property
roles, topology names and geometry payloads to that reconstruction. Editable
measurement receipts do not establish saved geometry. The binary64 serialization
allowance is 64 ULPs with a unit-scale floor; existing geometry/export tolerances
are unchanged. A configured FreeCAD command executable is required for this
verification; it is never selected by saved receipts.

Try [the bracket](../examples/schemaxis/freecad-mesh-bracket.json), its
[dimensional variant](../examples/schemaxis/freecad-mesh-variant.json), and the
[placed cavity](../examples/schemaxis/freecad-mesh-cavity.json). Studio's
**Prepare an STL bracket for machining** starter uses the repository bracket
fixture by default; select your existing STL before running elsewhere and adapt
the drill position, radius and reach to that geometry.

Mesh repair, decimation, point-cloud registration/fitting, reverse engineering,
mesh-feature dependencies, recovered colours and a PartDesign Body-seeding or
assembly-history bridge remain missing capabilities. FreeCAD adaptor completion
remains open. The native mapping uses the fixed FreeCAD 1.1.4 public
[`makeShapeFromMesh` implementation](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Part/App/TopoShapePyImp.cpp)
and [Part shape construction](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Part/App/TopoShape.cpp).
