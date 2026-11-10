# Technical line illustrations with Freestyle

`production.npr` defines reusable line styles and line sets for logical view
layers. It composes with faced meshes, material assignments, camera settings and
collection exclusions. The public rendering engine is Cycles on the fixed
Blender 5.2.3 baseline. Freestyle is separate from Grease Pencil Line Art.

Start with [the occluded plate](../examples/schemaxis/blender-freestyle-plate.json)
or [the material-split sphere](../examples/schemaxis/blender-freestyle-sphere.json).
Both use white emission surfaces, an orthographic camera and a foreground
occluder so the line colours and hidden-edge selection are easy to inspect.

```json
{
  "viewLayers": [{"id": "technical", "passes": ["combined"]}],
  "npr": {
    "styles": [
      {"id": "outline", "colour": [0, 0, 1, 1], "width": 3},
      {"id": "hidden", "colour": [1, 0, 0, 1], "width": 2,
       "dash": [{"length": 7, "gap": 3}]}
    ],
    "layers": [{"layer": "technical", "lineSets": [
      {"id": "outside", "style": "outline", "edges": ["silhouette", "border"],
       "visibility": {"kind": "visible"},
       "scope": {"kind": "objects", "objects": ["source"]}},
      {"id": "occluded", "style": "hidden", "edges": ["silhouette", "border"],
       "visibility": {"kind": "range", "minimum": 1, "maximum": 1},
       "scope": {"kind": "collection", "collection": "parts"}}
    ]}]
  }
}
```

All references are declared logical IDs. A line set names one reusable style and
selects silhouette, border or material-boundary edges using an inclusive object
list or collection. Selection combines edge types with “any”. The visibility
choices are `visible`, `hidden`, or an inclusive quantitative-invisibility
`range` from 0 to 64. A range of 1–1 selects edges behind exactly one occluding
surface. The native line renderer determines stroke endpoints; a dash is not
phase-locked to a user-authored screen coordinate.

Widths are absolute pixels, from 0.1 to 64. Colours are linear RGBA channels in
0–1. The public style uses butt caps, plain same-object chaining and at most one
positive integer dash/gap pair (1–1024 pixels each). The complete smooth view map
is retained; culling and inverse selection are unavailable in this finite slice.
Every style must be used. Limits are 32 styles, 16 view layers, 16 line sets per
layer, 64 line sets overall and 4096 object-scope links overall.

For a material-boundary line, select `materialBoundary` and set the style's
`colourSource` to `materialLine`. Declare `npr.materials` with logical `material`,
linear RGBA `colour`, and integer `priority` (0–32767). Blender chooses the
higher-priority adjacent Material's line colour. These properties belong to the
**Material owner**: changing a shared Material affects all its users. They are
not a per-line-set palette or a per-object override. Duplicate aliases to the
same native owner are refused rather than assigned conflicting values.

Layer exclusions remain authoritative. An object-list line set uses a private,
unlinked membership collection; it does not add its objects back into an
excluded scene collection. Collection scopes bind the complete selected subtree
and exact logical mesh membership. Current NPR admission requires ordinary
faced meshes without modifiers or collection/repeated captured instances. The
native scene budget is 4096 objects, 100000 faces and 200000 vertices. Curves,
Grease Pencil, scripted styles, texture-based style modifiers, arbitrary RNA,
native-name references, inverse scopes, and additional feature-edge families are
not part of this public slice.

Saved projects keep editable native Freestyle styles and line sets. A native
style edit does not rewrite the old typed declaration: verification must refuse
it against the original intent. Change the typed width or colour and run a new
project to create a corresponding verified publication. Verification compares
current native state with a freshly reconstructed expected source; replacing
readback receipts and refreshing hashes does not authorise a new style, owner,
collection membership or line-set pointer.

Raw file inputs retain their original-path dependency contract. For portable
source retirement, adopt a PLY into a pinned snapshot and reference it through a
workflow's public Engine input handling. Keep the snapshot; the old PLY and its
producer may then be retired. Do not pass a resource-reference dictionary to the
low-level adaptor's literal-path `run` function.

The public qualification entry points are:

```sh
python tools/qualify_blender_freestyle.py --blender /path/to/blender --output /path/to/new-raster-suite
python tools/qualify_blender_freestyle_lifecycle.py --blender /path/to/blender --suite /path/to/new-raster-suite --output /path/to/new-lifecycle-suite
```

Use the repository's bounded runner for native qualification. The first tool
checks projected edge positions, pixel widths, hidden dashes, material priority,
an asymmetric curved mesh and exclusion. The second exercises actual native
width edits and fresh reopen, refreshed native/readback/publication attacks,
pinned-source retirement and workflow reuse, cancellation and recovery. Each
records its executed source, runtime and tool identities. A tool's existence is
not a claim that a particular source revision has passed it.

Upstream references:
[Freestyle line sets](https://docs.blender.org/api/5.2/bpy.types.FreestyleLineSet.html),
[line styles](https://docs.blender.org/api/5.2/bpy.types.FreestyleLineStyle.html),
[Material line colour](https://docs.blender.org/api/5.2/bpy.types.Material.html#bpy.types.Material.line_color).
