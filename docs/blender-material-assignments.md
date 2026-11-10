# Surface materials and linked Object palettes

`production.materialAssignments` gives one editable surface several named material
roles. Use a DATA layout for the shared face, spline or character mapping. Use an
OBJECT override when another linked Object needs different materials while
retaining the same geometry and element mapping.

```json
{
  "materialAssignments": [
    {
      "kind": "layout", "id": "finish", "object": "housing",
      "sharing": "shared",
      "slots": [
        {"id": "shell", "material": "paint"},
        {"id": "label", "material": "printedLabel"}
      ],
      "defaultSlot": "shell",
      "regions": [
        {"slot": "label", "selection": {"kind": "faceIndices", "indices": [1]}}
      ]
    },
    {
      "kind": "override", "id": "secondEdition", "object": "otherHousing",
      "layout": "finish",
      "slots": [
        {"id": "label", "material": "alternateLabel"},
        {"id": "shell", "material": "alternatePaint"}
      ]
    }
  ]
}
```

The named Objects and materials must be declared elsewhere. `otherHousing` must
share the exact actual data ID of `housing` after mesh edits, fields and explicit
layout copies. Equal geometry and matching material names on a separate Mesh do
not establish that identity. Override slot order is irrelevant: logical IDs map
back to the referenced layout's order. Every logical slot needs one material.

A layout explicitly replaces the source palette and every element index. It does
not infer native source slot ordering or names. Unselected elements receive
`defaultSlot`. Regions must select nonempty existing elements and be disjoint;
overlap refuses. `faceIndices`, `faceBox` and `faceNormal` operate on current base
Mesh faces after topology edits and before evaluated modifiers. Box and normal
coordinates are local, before Object transforms. `splines` uses authored classic
spline IDs; `splineIndices` uses ordered native indices, including imported curves.
`characters` uses inclusive `start` and exclusive `end` Unicode code-point
positions in a text body. Whitespace has a character record; shaping can produce
a different number of rendered glyphs. `all` selects the complete current domain.

`sharing: refuse` requires one data owner. `copy` isolates this target's data;
`shared` changes all remaining owners after explicit copies. Layouts reset
affected slots to DATA links. An Object palette uses OBJECT links and preserves
the shared element indices. Layout and override targets must be distinct. Use one
layout per shared data block, or explicit copies. Different asset selectors that
resolve to one Object refuse. Legacy `materialBindings` affecting the same data
also refuse; combine those decisions into the named layout and palettes.

For a captured asset, `sourceObject` selects a unique original native/glTF part.
An omitted selector needs exactly one supported geometric part. Layouts replace
captured palettes explicitly; Object overrides require a declared layout and
never treat caller-submitted slot readback as source provenance. Material graphs
can use distinct shaders and independent Workbench display images in each slot.
Images and active/render UV maps follow the [image guide](blender-image-preview.md).

Native verification reconstructs declared constructors and captured inputs before
opening a submitted project. Exact owner membership, shared data identity,
DATA/OBJECT links, material pointers and element indices are compared with that
fresh reference. Saved readbacks and witness metadata cannot authorise a different
source. General verification does not independently rerender arbitrary images.
For deliberate native edits, save a separate project and adopt it as a new
captured input; ordinary unchanged saves must continue to verify.

`INVALID_MATERIAL_ASSIGNMENT` needs valid, disjoint regions and a complete logical
palette. `SHARED_MATERIAL_DATA` needs an explicit copy/shared decision or one
coherent layout. `MATERIAL_LAYOUT_IDENTITY` needs a distinct genuinely linked
Object. `AMBIGUOUS_MATERIAL_TARGET` needs one unambiguous source part.
`RESOURCE_BUDGET_EXCEEDED` needs fewer elements, owners or assignments; aggregate
material readback is bounded, including repeated linked-owner palettes.
Full-domain box/normal selections also consume a scan-work budget before geometry
allocation; many sparse regions can use explicit indices without repeated scans.

This milestone remains under qualification. Painting, generated canvases, UDIM,
baking, per-element material animation and broader renderer families remain
unfinished. Grease Pencil stroke materials are a separate missing family.
The baseline is Blender 5.2.3 LTS; see the official
[material assignment](https://docs.blender.org/manual/en/5.2/render/materials/assignment.html)
and [text editing](https://docs.blender.org/manual/en/5.2/modeling/texts/editing.html)
chapters.
