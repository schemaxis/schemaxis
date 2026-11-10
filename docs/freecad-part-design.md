# Mechanical parts with FreeCAD sketches and features

Start with a constrained sketch, give it thickness with a Pad, then remove material
with another sketch and a finite-depth or through-all Pocket. The published FCStd contains a real
PartDesign Body and editable feature history. Named dimensions can drive the sketch
and Pad, so a changed thickness keeps the hole through the whole part.

[The mechanical-part example](../examples/schemaxis/freecad-part-design.json) makes
an 80 × 50 × 5 mm plate with a 6 mm hole offset to (15, 10) mm. Its width, thickness
and bore radius remain shared, editable native length parameters.

```json
{
  "version": "schemaxis.freecad/1",
  "parameters": {
    "thickness": {"kind": "length", "value": 5, "minimum": 2, "maximum": 50}
  },
  "nodes": [
    {"id": "part", "filter": "body"},
    {"id": "outline", "filter": "rectangle", "inputs": {"body": "part"},
     "options": {"width": 80, "height": 50}},
    {"id": "slab", "filter": "pad", "inputs": {"body": "part", "profile": "outline"},
     "drive": {"length": {"terms": {"thickness": 1}}}},
    {"id": "bore", "filter": "circle", "inputs": {"body": "part"},
     "options": {"radius": 3, "centre": [15, 10]}},
    {"id": "finished", "filter": "pocket", "inputs": {"base": "slab", "profile": "bore"},
     "options": {"extent": "throughAll"}}
  ],
  "output": "finished"
}
```

Run the example through the usual commands:

```sh
schemaxis plan examples/schemaxis/freecad-part-design.json
schemaxis run examples/schemaxis/freecad-part-design.json \
  --freecad /absolute/path/to/freecadcmd --output-directory evidence/mechanical-part
schemaxis verify evidence/mechanical-part
```

The [general history guide](freecad-histories.md) extends this introductory
example to multiple Bodies, subsequent Pads, arbitrary typed sketches, frames,
native planar-face attachments, turned features, patterns, dress-ups and lofts.

## Choosing a modelling route

| Intent | Declaration | Native result |
| --- | --- | --- |
| A mechanical part with an editable sketch and feature history | `body`, owned `rectangle`/`circle`, `pad`, then `pocket` | PartDesign Body containing Sketcher sketches, first Pad and finite-depth or through-all Pockets |
| Construct or combine separate solids | Primitives, unowned profiles, `extrude`/`revolve`/`loft`, booleans | Linked Part features; see [CAD workflows](cad-and-mesh-workflows.md) |
| Reuse a dimension after native reopening | `parameters` and node-local `drive` | Typed native length properties and explicit expression relationships; see [parameters](freecad-parameters.md) |

A sketch's optional `inputs.body` selects ownership. Omitting it preserves the
existing Part-profile route. The Body is a container, not a solid output. The first
Pad requires its Body and an earlier profile in that Body. Each Pocket takes the
current solid tip as `base` and a fresh profile in the same Body. Select the final
Pad or Pocket as `output`; the saved Body's Tip points to that feature.

This introductory example uses one Body, a first Pad and a linear Pocket chain.
The current route also supports explicit subsequent Pads and separate Bodies;
branches, reused profiles and implicit cross-Body links are refused.
Owned profiles/features cannot feed Part booleans or sweeps; use the separate Part
route for those models. A Body with no features or an unused owned sketch can be
retained while authoring if another unowned solid is the output. An empty Body is
never accepted as a solid, and adding an unused sketch does not replace the Tip.

## Dimensions and geometry

All lengths are millimetres. This example attaches Body sketches to the origin
XY plane with zero offset. The route also accepts explicit frames and checked
planar-face attachments; see the history guide. The Body itself stays at the
world origin, and the example Pad grows along +Z. A Pocket uses one side, reversed relative to its XY sketch normal so it removes
material along +Z from the origin XY face. Choose `extent: "throughAll"` (the
default) for native **Through all**, with no `length`. Choose `extent: "length"`
with an explicit positive `length` in mm, at most 100000, or `drive.length` for
native **Length**. There is no default finite depth. The saved extent and finite
depth are verified separately from geometry: a same-current-shape cut with different
intent does not satisfy the declaration.

Rectangles are centred and fully constrained by named `width` and `height`
constraints plus centring expressions. Circles are centred by default. An explicit
`centre: [x, y]` creates signed `centreX` and `centreY` constraints, in local sketch
coordinates, each within ±100000 mm. Zero and negative coordinates are allowed.
The native constraints can be edited after reopening; coordinate drivers are not
yet exposed. Width, height and radius can use `drive`, as can Pad `length` and finite-depth
Pocket `length`. `throughAll` refuses a literal or driven length.

Parameter bounds establish a supported range of affine lengths, not a guarantee
that every combination is geometrically valid. A hole outside the stock, excessive
radius, or a cut leaving multiple solids fails native acceptance. Each Pocket must
remove positive volume, and the selected output must be one valid positive-volume
solid. No manufactured-part strength, tolerance or material claim is implied.

Use `$analytic` values in a parameter's `value` to run a finite family, for example
thicknesses 5 and 20 mm. Each state produces its own FCStd, STEP and STL. The Body
route and persistent drivers are batch-only; live sessions and scalar `designStudy`
reject them explicitly. Assembly improvements and broader imported-geometry
preparation remain separate follow-on work.

## Editing and verification

Open the FCStd in FreeCAD to inspect the Body, Pad and Pocket. **Design parameters**
contains length properties such as `dim_thickness`; editing one recomputes bound
features. The sketches retain editable named constraints. These native edits do
not change the authored JSON. Keep an edited copy, or change the source and run
into a fresh directory to create new Schemaxis evidence.

Build and fresh-process reopening verify Body ownership, ordered Group and Tip,
Origin helper roles/types, XY attachment, placements, active driving constraint
names/types/endpoints, expressions and feature settings. Saved FCStd metadata is
checked independently, including literal models without parameters. Geometry,
STEP and STL retain the existing checks and publication order: STEP 0, STL 1,
FCStd 2, and optional measurements 3. STEP and STL do not retain feature history.

`tools/qualify_freecad_part_design.py` independently checks volume, surface area,
bounds, centre of mass, cylindrical faces and point membership for the offset-hole
example. It changes every driver at its bounds, directly edits the unbound centre
constraints, saves a separate model and reopens it in a further process. A
same-current-shape fixed-depth Pocket is rejected and then distinguished by a
thicker stock edit. Corrupted files, altered ownership, attachment, constraints,
Body placement and feature semantics are negative cases. This qualifies the
bounded workflow, not arbitrary Sketcher geometry or all FreeCAD features.

## Blind pockets and counterbores

[The counterbore example](../examples/schemaxis/freecad-counterbore.json) makes an
80 × 50 × 12 mm plate with a 6 mm diameter through bore at (15, 10) mm and a
12 mm diameter counterbore 4 mm deep from the origin XY face. The first Pocket
uses `throughAll`; the second uses `length`, driven by `counterboreDepth`. Both
sketches have the same centre. The radius and stock thickness also remain native
drivers. [The variant](../examples/schemaxis/freecad-counterbore-variant.json)
changes all three dimensions to 20 mm stock, 8 mm depth and 8 mm recess radius.
[The blind-pocket example](../examples/schemaxis/freecad-blind-pocket.json)
omits the small through bore and leaves an 8 mm floor above the 4 mm cavity.
Studio offers **Through bore with a counterbore** with an editable depth control.

A finite depth does **not** guarantee a blind cavity. These sketches start at
Z = 0 and cut towards +Z; the cavity opens on the origin XY face. A length equal
to or greater than the stock thickness cuts through. When stock later becomes
thicker than that length, the finite cut leaves material above its floor, while
`throughAll` keeps cutting through. Native parameter bounds ensure positive
lengths, not a relationship between cut depth and stock or a manufacturing safety
margin. Choose bounds and geometry that reflect your intended stock family.

Use a distinct unused profile for each cut and continue from the current tip.
A counterbore must overlap and remove material from that tip; a second cut wholly
inside an existing void fails `INVALID_GEOMETRY`. `INVALID_POCKET_EXTENT` means
supply `length` or `drive.length` with `extent: "length"`, or remove that depth
for `throughAll`. [The invalid example](../examples/schemaxis/freecad-counterbore-invalid.json)
demonstrates the conflicting intent. Fix the declaration, then rerun into a fresh
evidence directory. The feature chain, ownership, constraints, STEP/STL handoff
and batch-only restrictions above apply to both extents.

The counterbore volume is `80*50*t - pi*3^2*t - pi*(R^2-3^2)*min(d,t)` mm³.
`tools/qualify_freecad_finite_pocket.py` adds independent surface area, bounds,
centre of mass, point membership and cylindrical-face oracles; checks depth,
stock and radius edits at their bounds; edits both unbound centres directly;
saves and freshly reopens the native document and STEP; and rejects changed
saved extent, depth, property type, expression, direction and base links even
with refreshed artifact hashes. Its thicker-stock control distinguishes finite
and through-all cuts that initially have the same shape. These are geometric
checks, not machining, fit, tolerance or structural certification.

See [the capability-family map](freecad-capabilities.md) for the supported product
workflows and the substantial upstream workbenches still excluded.
