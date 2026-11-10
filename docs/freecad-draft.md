# Mould-release draft in editable Body histories

`bodyDraft` tapers selected faces of the current Body solid with native
PartDesign Draft. Use it before uniform walls, bosses, bores and finishing
features when an enclosure or cup needs a release slope. It retains the native
Draft feature, its selected faces, neutral plane and pull reference. It is
separate from the Draft workbench's 2D drafting tools.

```json
{
  "id": "release",
  "filter": "bodyDraft",
  "options": {
    "angle": 3,
    "faces": [
      {"surface":"plane", "normal":[1,0,0]},
      {"surface":"plane", "normal":[-1,0,0]},
      {"surface":"plane", "normal":[0,1,0]},
      {"surface":"plane", "normal":[0,-1,0]}
    ]
  },
  "inputs": {"base":"stock", "neutralPlane":"outline"}
}
```

`base` must be the current solid tip of its Body. `neutralPlane` is an earlier
profile owned by that Body; its plane stays fixed while the selected walls
change slope. A profile already used by a Pad is a valid neutral plane and is
not consumed again. This uses the profile's plane rather than its boundary
edges. A same-Body `datumAxis` may be supplied as input `axis` for the pull
direction. Otherwise FreeCAD uses the normal of the neutral profile plane.
Native property paths, face indices and authored code are not inputs.

`angle` is in degrees, strictly between zero and 90, and defaults to 3.
`reversed` changes the draft slope sign and defaults to false. For an XY outline
and +Z pull, the example's side walls narrow with increasing Z; reversed walls
widen. The neutral plane and pull direction determine this convention for other
frames. All coordinates, cylinder radii and downstream wall thicknesses are
millimetres. Native angle drivers are not exposed through the length-parameter
system; change the authored angle or edit the saved native Draft feature.

Each face intent must resolve to exactly one measured face:

| Intent | Selection |
| --- | --- |
| `surface: plane`, `normal: [x,y,z]` | Outward unit normal in the model frame. `position: outermost` selects the extreme matching plane in that direction; `innermost` selects the opposite extreme among faces with that same normal. Equal extremes remain ambiguous. |
| `surface: cylinder`, `axis: [x,y,z]`, `radius` | Select a cylindrical face by unit axis direction, axis line and pre-draft radius. `axisPoint`, default `[0,0,0]`, is any point on that line. Opposite axis directions describe the same cylinder. Multiple matching faces remain ambiguous. |

The selector's distance budget is 1e-6 mm and direction budget 1e-7, matching the
existing finite face-selection policy. Inputs require unit direction vectors
within 1e-8. These budgets identify geometric references; they do not relax
native validity, analytic acceptance or complete saved-source regeneration.
Every intent is resolved afresh, with the complete measured inventory retained
for host and saved-link comparison. Duplicate intents resolving to one face fail.
Saved-run verification needs a configured FreeCAD command executable. An isolated
geometry reader measures each stored base BREP and checks both saved face links
and recorded inventories against the authored selectors. It reads geometry only;
it does not restore the submitted FCStd document.
Each measured base is limited to 10,000 faces, with 100,000 faces across the
verification call; extracted base geometry and returned inventory each have a
64 MiB budget. A run exceeding these limits must be simplified or split.

[The moulded enclosure example](../examples/schemaxis/freecad-draft-enclosure.json)
composes four drafted walls, native uniform thickness, four attached bosses,
bores and a separate slotted lid. Existing length parameters still drive stock
height, wall, boss height and bore diameter. Check that bosses remain clear of
sloping walls over the intended parameter range: draft can change that clearance.
[The cylindrical cup](../examples/schemaxis/freecad-draft-cup.json) uses an
explicit translated pull axis, reversed cylindrical draft and uniform walls.
Both are available as ordinary CAD documents; Studio also provides the moulded
enclosure starter.

The native kernel must produce one valid solid after each feature. Start with
Draft before fillets where possible; tangentially joined or unsuitable surfaces
can fail native drafting. Missing/ambiguous references produce
`EMPTY_SELECTION`/`AMBIGUOUS_SELECTION`. `INVALID_DRAFT_SELECTION` identifies
non-unit or duplicate face intent, and `INVALID_BODY_OWNERSHIP` or
`INVALID_BODY_HISTORY` identifies incorrect neutral/pull references or a stale
base. Correct the geometry or references and rerun in a fresh output directory.

Only planar and cylindrical source-face selection is implemented. Conical,
spline and other surface selectors, arbitrary native neutral-face references and
broader feature extents remain missing. Native edits do not reverse-synchronise
into authored JSON. FCStd retains history; STEP/STL publish the selected final
solid and lose native feature semantics. This feature does not complete the
FreeCAD adaptor; broader Draft 2D, Helix, surfaces, BIM and other families remain
separately tracked.

The fixed baseline is [FreeCAD 1.1.4](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.4).
Native mapping follows the public [Draft properties and execution](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeatureDraft.cpp).
The dedicated native qualification covers the enclosure, cup and tilted-frame
solid, independent geometry, saved-state attacks, two native edits and fresh
reopens, assembly source copies and copied-history edits, standalone reopening,
and workflow reuse/recovery. See the [qualification record](../verification/2026-11-04-freecad-draft.md)
for its exact source identity and limits. Final integrated Help, packaging and
independent master acceptance remain separate gates.
