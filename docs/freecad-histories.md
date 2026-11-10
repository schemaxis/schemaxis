# Editable FreeCAD design histories

The `schemaxis.freecad/1` route builds ordered native feature histories in one or
more Bodies. It keeps the existing part format and earlier origin-based
Pad/Pocket documents. This is a substantial mechanical-design foundation; it is
not complete FreeCAD coverage. See the [family inventory](freecad-capabilities.md).

## Model mechanical intent

Use `body` for each manufactured part. Give each rectangle, circle, polygon or
`sketch` its owning `body` input. Begin with `pad`, `bodyRevolve` or
`additiveLoft`; continue with explicit `base` links to the current solid tip of
that Body. A subsequent Pad adds a boss or rib to existing material. Pockets,
grooves and subtractive lofts remove material. [Mould-release Draft](freecad-draft.md)
tapers measured planar or cylindrical faces about an earlier profile plane and
composes with uniform walls, bosses and drilling. Fillets, chamfers and patterns
remain native PartDesign features. Each solid feature must leave one valid
positive-volume solid. Separate Bodies have independent histories; the selected
`output` publishes one final tip, while the FCStd retains all authored Bodies.
A Body container or datum axis cannot itself be the exported solid.

The [driven housing starter](../examples/schemaxis/freecad-driven-housing.json)
models a plate, face-attached boss and through bore. Its named stock thickness,
boss radius and boss height are native length parameters. Editing thickness in
FreeCAD moves the attached boss and bore profiles through their native support
links. It does not require manually changing their Z coordinates.

Inputs refer to earlier nodes. A feature cannot branch from a stale tip, use a
profile owned by another Body, reuse an already consumed profile, or pass a Body
member silently into a separate Part boolean. For exported assemblies, use the
[portable Body-history contract](freecad-body-history.md). It captures the whole
typed document, including other Bodies, while selecting the final output Body
for component geometry. Newer history families are not automatically qualified
assembly sources; their native vocabulary and complete reconstruction must be
admitted separately.

## Sketch frames and attachments

A Body may declare its own [Body-to-world layout](freecad-body-frames.md).
Its profile coordinates and attachment directions remain Body-local.
Every profile accepts XY, XZ or YZ plus an origin, or an explicit `frame` with
`origin`, `xAxis` and `normal`. Frame axes must be perpendicular unit vectors;
local Y is normal cross local X. Coordinates and offsets use millimetres. The
explicit frame is a persistent native placement, useful for angled brackets and
sections. It is not linked to another feature.

For dependent profiles, supply `inputs.support` and `options.onFace` together.
`onFace.face` names top, bottom, left, right, front or back in the owning
Body's Cartesian axes (world axes when its layout is identity); the adaptor selects exactly one extreme planar face with that outward
normal. The default anchor projects world origin onto the face plane; centroid anchoring
uses its area centre. Choose outermost (default) or innermost among faces with
that outward normal; top+innermost expresses an enclosure cavity floor. Equally
extreme faces remain ambiguous. The origin is optionally displaced by
`onFace.offset` along the outward normal. Local X is world X, except left/right
faces use world Y. The result uses a real native FlatFace attachment and an
editable attachment offset. Missing faces and equally extreme faces fail
explicitly; no face is silently ranked or chosen. Rotated/curved faces and
arbitrary subelement attachment modes remain gaps. Native topological references
can become invalid after edits that change face membership; recompute and inspect
after such an edit. An explicit frame and a face attachment are mutually
exclusive.

Pad and Pocket `direction` is forward along the profile normal, backward against
it, or symmetric about the profile plane. Omission preserves the earlier forward
contract. A top-face Pocket normally uses backward to enter its stock. Finite
Pocket extent needs a positive length; throughAll omits finite length. Symmetric
length is the total extrusion distance.

## General sketches

Rectangle/circle/slot shortcuts create fully constrained native dimensional sketches;
use them for ordinary editable stock, round features and capsule mounting slots.
For slot, length is straight centre-to-centre span, radius is half its width and
overall length is length+2*radius. Named native span/radius dimensions accept
persistent drivers; tangency and equal radii are created automatically. `polygon` closes a
simple ordered vertex loop and fixes its individual lines with native Block
constraints. `sketch` accepts named line, circle and circular-arc geometry,
including construction geometry. Lines use start/end coordinates; circles/arcs
use centre/radius; arc angles are degrees measured from local +X and must form a
positive sweep less than360 degrees.

`constraintMode: fixed` is the default: each complete geometry element has a
named Block constraint, retaining its authored coordinates and shape. Use
`constraintMode: solve` with named relations for a dimensionally constrained
sketch. References name geometry plus start, end, centre or whole, rather than
requiring native numeric geometry indices. The relation catalogue covers
coincident, horizontal, vertical, parallel, perpendicular, tangent, equal,
distance, distanceX, distanceY, radius, diameter, angle and block. Dimensional
relations need `value` in millimetres or degrees; geometric relations omit value.
The sketch must solve without remaining freedom. Initial coordinates are solver
seeds in solve mode; they need not equal the solved geometry. Host verification
independently checks supported geometric/dimensional residuals as well as native
constraint identity, driving status and saved settings. Ellipses, splines,
external geometry, three-geometry symmetry and general constraint driving
expressions remain open work.

## Native feature catalogue

| Intent | Operation | Important conventions |
| --- | --- | --- |
| Add stock/boss/rib | `pad` | body/profile, optional current base; length in mm |
| Uniform walls/openings | `shell` | native Skin thickness; inward/outward; exact planar openings; see [shells](freecad-shells.md) |
| Drilled holes/head recesses | `hole` | one Body-owned circular layout; diameter/depth/tip/recess intent; see [drilling](freecad-drilling.md) |
| Bore/recess | `pocket` | current base/profile; finite or through-all |
| Turned part | `bodyRevolve` | body/profile; optional base; angle in degrees |
| Turned recess | `groove` | body/profile/current base; angle in degrees |
| Reusable rotation axis | `datumAxis` | Body-owned origin and direction; reference with the feature's axis input |
| Round/bevel Body edges | `bodyFillet`, `bodyChamfer` | current base; semantic edge selector or explicit one-based indices; equal-distance chamfer |
| Repeat a sketch feature | `linearPattern`, `polarPattern` | current base plus original feature; count includes original; positive total span |
| Reflect a sketch feature | `mirror` | current base plus original feature; XY/XZ/YZ Body origin plane |
| Add/remove changing sections | `additiveLoft`, `subtractiveLoft` | body and ordered section profiles; optional/current base; ruled or smooth |

Revolve/groove use a Body origin X/Y/Z axis by default, or a `datumAxis` input for
an arbitrary axis. A datum stays editable and does not advance the solid tip.
Patterns currently repeat one Pad/Pocket/Hole/Revolution/Groove feature; they do not
repeat the complete Body. Linear axes and polar axes are Body origin X/Y/Z;
linear length is first-to-last span. A full360-degree polar pattern distributes
count instances around a complete circle. General datum-based patterns,
multitransforms, threaded/tapered Hole modes, general spatial/spline sweep paths,
variable-thickness/surface offsets, Helix and wider feature extents remain
open in this programme.

## Verification and losses

A build and a fresh native process both read back ownership, Group/Tip links,
profile geometry and constraints, frame/attachment semantics, feature settings
and expressions. Host code also reads the FCStd XML directly and compares it
with the declared plan and native observations. Semantic selectors retain their
measured inventories. STEP is reread and STL has independent signed-integral,
volume, centre and geometry checks. Native FCStd retains editable history;
STEP/STL retain geometric handoffs and lose that history. A changed source or
receipt cannot reuse unrelated qualification automatically.

Batch parameter variants and native editing are supported. Live Body sessions,
general reverse synchronisation into authored JSON, scalar PartDesign
`designStudy`, arbitrary imported FCStd editing and whole-workbench coverage
remain incomplete. Use the native acceptance scripts for the exact currently
qualified version and cases; a passing model is not proof that every valid CAD
combination will succeed in the kernel.
