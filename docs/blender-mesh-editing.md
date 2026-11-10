# Blender selected mesh editing

Build an enclosure, cut a section, repair a polygon boundary or prepare an adopted
mesh before adding [scientific fields and UV maps](blender-mesh-data.md) and
[procedural resources](blender-geometry-resources.md). Whole Blender and general
mesh-operator coverage remain incomplete.

`production.meshEdits` contains up to256 targets. Each target identifies a public
mesh/instance `object`, or an imported `object` plus its original `sourceObject`
name, and one to64 ordered `steps`. Each step has a distinct `id`, a reviewed
`kind`, a `selection`, and that operation's typed controls. No native property
path or executable expression is accepted. The
[enclosure example](../examples/schemaxis/blender-mesh-editing.json) creates a
40×30×20mm open housing with2mm walls/3mm floor, a separate3mm lid atz27,
temperature and a named UV map. The native result is editable geometry; these
steps do not create a Blender feature-history tree.

```json
{"object":"panel","steps":[
  {"id":"wall","kind":"extrudeFaces","selection":{"kind":"all"},
   "offset":[0,0,20],"keepBase":true},
  {"id":"rim","kind":"insetFaces",
   "selection":{"kind":"normal","direction":[0,0,1]},"distance":2}
]}
```

Selections use the current stage, after earlier steps. Omitted `domain` uses
POINT for merging, EDGE for bridging/boundary selection, and FACE otherwise.
Normal/material selections use FACE. Explicit incompatible choices refuse.
`all` selects all current elements; `indices`
takes distinct current indices. EDGE indices follow sorted unique vertex pairs,
including loose edges. `box` selects element centres inside inclusive minimum/
maximum coordinates; `test:contained` requires every incident vertex inside.
`normal` selects faces within `angle` radians of a nonzero `direction` (default
angle0); `material` selects faces by material-slot indices. `boundary` selects
open-boundary and loose edges in EDGE domain. `invert:true` complements any
selection in that domain. Empty selections and out-of-range indices refuse.

All geometric distances, box coordinates, offsets, plane points and pivots are
in the mesh's local coordinates, before Object/parent/asset transforms. An
imported metre-valued mesh inside a millimetre asset still uses metres locally.
Angles are radians. Selections do not inspect evaluated modifier results.

| Step kind | Controls and supported behavior |
| --- | --- |
| transform | Translate/rotate/scale the vertices incident to selected elements. XYZ Euler rotation and nonzero scale act around `pivot`, then translation. Negative scale is permitted here; use the normals step when winding must change. |
| extrudeFaces | Extrude an oriented manifold face region by nonzero local `offset`. Boundary edges form sides. `keepBase:false` replaces selected faces; `true` keeps a reversed base only for an isolated region whose edges are all boundary edges. |
| insetFaces | Inset each selected convex planar polygon by positive physical `distance`. Creates its rim and inner face. Concave/nonplanar or collapsing insets refuse; this is an individual-face inset. |
| splitFaces | Duplicate each selected face's vertices, disconnecting its boundary. No automatic orphan deletion. |
| triangulate | Deterministically triangulate selected simple planar polygons, including concave polygons. Nonplanar/degenerate/unsupported self-intersecting inputs refuse. |
| bridgeLoops | Connect exactly two selected closed boundary or loose-edge loops with equal vertex counts. `twist` offsets the correspondence; `smooth` controls new faces. Existing face winding guides orientation. Open/unequal/multiple loops and intermediate cuts remain gaps. |
| bisect | Keep the positive or negative side of local `point`/`normal` for selected complete manifold components. `cap:true` requires closed consistently outward source components and simple unnested cap loops, then checks closed positive-volume output. `capMaterial` sets new cap slots. `cap:false` permits open results; `tolerance` is a local distance. Coplanar/tangent zero-thickness caps refuse. Cutting while retaining both sides, nested-hole caps and UV interpolation remain gaps. |
| mergeVertices | For selected POINT vertices, map each vertex within `distance` to the earliest surviving representative. The radius test is against that representative, not a transitive cluster/centroid. Collapsed polygons are removed. |
| delete | Delete selected elements and their dependent polygons. `deleteOrphans:true` also removes unused vertices; otherwise they remain. |
| normals | Set consistent face winding, outward winding for closed nonzero-volume components, or flip selected winding. This edits polygon winding, not custom split normals. |
| shade | Set selected faces' `smooth` flag. Geometry remains unchanged. |

Extrusion/inset/triangulation/split/bisect/normals/shade require FACE selection;
bridge requires EDGE; merge requires POINT. Each intermediate mesh is bounded
to100000 vertices, edges, faces and corners, with a one-million aggregate source/
result budget. Merge comparisons and polygon triangulation also have finite work
limits. RESOURCE_BUDGET_EXCEEDED requires simplifying/splitting the workflow.

Native Mesh coordinates use single precision. Edited face areas must remain
nondegenerate after writing; topology/material/shading records compare exactly,
and coordinate error is bounded to one millionth of the mesh span, independent
of its origin. A very large local origin can lose small features and refuses
NATIVE_VALUE_MISMATCH. Recenter/rescale the model for adequate native precision;
very large world origins also affect evaluated exchange precision.

Choose `sharing:copy` to give the target its own Mesh, or `sharing:shared` to edit
every Object using the prototype Mesh. The default `refuse` prevents accidental
shared writes. Distinct selectors that resolve to the same Object refuse even
when their strings differ. A selected asset part is a prototype, not one
collection occurrence. Copy targets are resolved before shared targets.

Mesh editing precedes field/UV authoring, Geometry Nodes, shape keys, rigs and
motion. Later field lengths and morph counts refer to the edited topology.
Existing UVs, custom normals, user attributes and edge flags require explicit
`dataPolicy:discard`; the default refuses these losses even for a transform-only
recipe because editing rebuilds the base Mesh. Existing vertex groups and shape
keys always refuse: interpolation/propagation is unfinished. Author supported
fields, maps, weights and shape keys after edits. Face material slots and smooth
flags are retained through replay; a later material binding can replace slots.

Save/reopen verification reconstructs original DAG/native/neutral inputs from
authored intent and captured input bytes, then replays the finite geometry
algorithm and compares current saved geometry, ownership and fields. A mutable
saved pre-edit witness is not the source of truth. Native sources are loaded with
scripts disabled. Adopt manual native edits as a new source; receipt verification
continues to require its original and retained source bytes. Neutral exports
retain the established evaluated-geometry/unit policy and do not promise field,
recipe, hierarchy or modifier editability.

INVALID_MESH_SELECTION or EMPTY_MESH_SELECTION requires selecting existing
elements of the operation's domain; INVALID_MESH_EDIT requires correcting geometry or unsupported operation
conditions. UNSUPPORTED_MESH_EDIT_DATA requires an explicit supported loss choice
or a new source without unsupported data. SHARED_MESH_DATA requires an ownership
choice. General bevel/knife/dissolve/subdivide/slide, rich selection tools and
topology data interpolation remain required strategic work. Existing separate
whole-object modifiers do not complete those selected mesh editing workflows.

Baseline5.2.3LTS comparison sources: [mesh editing index](https://docs.blender.org/manual/en/5.2/modeling/meshes/editing/index.html),
[native bridge variants](https://docs.blender.org/manual/en/5.2/modeling/meshes/editing/edge/bridge_edge_loops.html)
and [native merge variants](https://docs.blender.org/manual/en/5.2/modeling/meshes/editing/mesh/merge.html).
The typed semantics and limits above define the implemented subset.
