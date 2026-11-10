# Blender geometry resources

Reuse a prototype, collect an assembly or modify selected asset parts without
flattening their native ownership. Whole Blender coverage remains incomplete.

`production.geometryResources` declares at most256 typed aliases:

```json
[{"id":"housing","kind":"object","object":"cad",
  "sourceObject":"housingView-exchange"},
 {"id":"assembly","kind":"asset","asset":"cad"},
 {"id":"fixtures","kind":"collection","collection":"parts"}]
```

Object aliases fill Object sockets; collection/asset aliases fill Collection
sockets. Their IDs must differ from public Object/collection IDs and other
aliases. `objectInfo` takes `values.object` and `values.asInstance`;
`collectionInfo` takes `values.collection`, `values.separateChildren` and
`values.resetChildren` (which requires separate children). Both select
`properties.space`: ORIGINAL(default) or RELATIVE. Realise instances for mesh
output. Public Object/collection IDs can also fill these sockets. Typed group
interfaces support defaults/overrides and actual native pointer verification.

An Object alias without sourceObject resolves the public Object itself. An
asset's carrier Empty does not implicitly collect ordinary child geometry; use
kind:asset for its actual owned collection. sourceObject selects an original
native Object or unique glTF mesh-node name, using the captured pre-import name
and collision proof shared with mesh fields. It identifies a prototype, not one
collection occurrence. Whole native assets retain their selected scene/view-layer
projection. `geometryBindings` accepts object plus optional sourceObject; omitted
asset selectors require one mesh. Distinct parts of one public asset may have
different modifiers; selectors resolving to one Object twice refuse. Modifiers
are Object-owned; fields retain their separate copy/shared Mesh policy.

ORIGINAL Object Info reads local geometry. A metre mesh remains numerically
metre-sized in a millimetre consumer. RELATIVE preserves source world placement
relative to the consumer, including parent/asset scale. A selected prototype
does not inherit every collection occurrence's placement; use the whole asset.
ORIGINAL Collection Info includes collection offset; RELATIVE preserves relative
placement. Reset children removes per-instance transforms and places geometry
at the consumer origin in either space. Qualification includes translated
sources/consumers with rotations/nonuniform scale, nested instances and nonzero source collection offsets.

Before modifier attachment, real native source, collection, parent, constraint
and modifier dependencies are checked for cycles. Resources participate in the
two-million conservative vertex budget, including source modifiers, instance
multiplication and every shared-child collection occurrence. Reachable typed
group defaults/overrides are finite pointer candidates: all participate in cycle
admission; linked resource inputs use the largest candidate cost. Remove unused
cyclic/expensive defaults explicitly. These are conservative preallocation bounds,
not exact mesh-count predictions.

Supported numeric source topology controls are bounded over their key values,
Bézier handle hulls and timeline endpoints, including linear extrapolation.
This catches future count changes and overshoot before attaching a graph.
Curve render sampling and builtin-font sampling use the maximum of viewport,
render and applicable spline resolution, including supported key/Bezier
envelopes. A cheap viewport can otherwise hide expensive native render geometry.
Reduce the source's render resolution when RESOURCE_BUDGET_EXCEEDED refuses it;
render resolution0 follows preview sampling. This conservative admission covers
both contexts before attaching procedural modifiers. Referenced Curve sections
and taper dependencies participate in cycle/depth admission; section sampling
multiplies the path bound. Builtin-font Object/custom-quarter profiles use the
same section-expansion policy with a conservative glyph outline bound. Planar
CDT intersection growth is bounded quadratically. See [editable spline
construction](blender-splines.md) for profile controls and native geometry limits.
Array caps, all mirror axes/bisect cuts, source corners/edges and conservative
Boolean intersection growth participate. Topology drivers, layered/NLA topology,
curve modifiers and unreviewed interpolation require an explicit reviewed bound
and currently refuse. Ordinary transform/pose/deformation animation remains
available. Animated enum topology policies such as array fit mode refuse.

Imported modifier families without reviewed expansion bounds refuse
UNSUPPORTED_RESOURCE_TOPOLOGY. Imported arbitrary Geometry Nodes, caches, volumes
and other resource types still need broader intent/budget coverage; they are
implementation gaps, not application-wide exclusions.

Native save/reopen keeps editable pointers, fields, modifiers and hierarchy.
Neutral formats retain existing evaluated-geometry/physical-unit losses and do
not promise editable bindings/scientific fields. Adopt native edits as a new
source. Packed adopted projects reopen without the original source, but receipt
verification deliberately checks both original and retained input bytes. Restore
the original to verify that receipt; a native project reopen is a separate check.
DEPENDENCY_CYCLE requires removing recursive references;
RESOURCE_BUDGET_EXCEEDED requires reducing expansion; AMBIGUOUS_MESH_TARGET
requires one source selector. Do not weaken verification after refusal.

Baseline5.2.3LTS: [Object Info](https://docs.blender.org/manual/en/5.2/modeling/geometry_nodes/input/scene/object_info.html)
and [Collection Info](https://docs.blender.org/manual/en/5.2/modeling/geometry_nodes/input/scene/collection_info.html).
Runnable [example](../examples/schemaxis/blender-geometry-resources.json).
