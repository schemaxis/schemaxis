# Editable splines, profiles and paths

Use a `production.objects` record with `kind: "spline"` for editable classic Curve
geometry. The earlier `kind: "curve"` single polyline remains available. A spline
object contains one or more locally named `POLY`, `BEZIER` or `NURBS` splines. These
are classic Curve data, distinct from modern hair Curves, Surface and Metaball data.

Each control has a required local `position`, a nonnegative `radius` multiplier
and `tilt` in radians. Local coordinates use production units before Object,
parent or imported-asset transforms. Spline IDs identify ordered declaration
records; Blender does not provide native names for individual splines. Set
`closed` for a cyclic contour. `reverse` reverses its direction and exchanges
Bézier left/right handles while preserving the geometric curve. `smooth` controls
surface shading. Bézier/NURBS `sampling: 0` inherits object preview sampling;
positive values set that spline's preview subdivisions. Object `sampling.render`
zero uses preview sampling; a positive value selects render subdivisions.

Bézier controls have independent `left` and `right` handle choices. `AUTO` derives
a smooth tangent; `VECTOR` produces straight adjoining segments. `FREE` includes
an explicit handle position. `ALIGNED` also includes a position and requires the
opposite explicit handle to be collinear, nonzero and facing the other direction.
Blender must not silently rotate an invalid authored handle pair. Radius and tilt
interpolation are `LINEAR`, `CARDINAL`, `BSPLINE` or `EASE` for Bézier splines.
POLY/NURBS forms omit these Bézier-only interpolation selectors. POLY uses its
straight segments and omits an ineffective subdivision selector.

NURBS controls additionally have positive rational `weight`. `order` is degree
plus one, between two and six, and cannot exceed control count. `endpoint` clamps
the ends; periodic cyclic curves disable endpoint and Bezier-knot flags. Quadratic
or cubic `bezierKnots` require complete spans. For example, controls `(1,0)`,
`(1,1)`, `(0,1)` with weights `1,sqrt(0.5),1`, order three and endpoint knots form
an exact unit quarter circle. Changing the middle weight changes the curve even
when its bounds stay unchanged.

`dimensions: "2D"` requires all controls and explicit handles in local XY with z
zero. `fill: "AUTO"` means `BOTH` for planar curves and `FULL` for spatial curves.
Planar fill also permits `NONE`, `BACK` and `FRONT`; spatial fill permits `BACK`,
`FRONT` and `HALF`. Planar `fillRule` chooses crossing parity or nonzero winding;
`fillSolver` chooses sweep-line or CDT, the latter supporting self intersections.
NONZERO requires CDT: the sweep-line backend ignores the nonzero rule.
`offset` is a planar outline offset. `extrude` extends each side along local Z,
so an extrusion of one has total thickness two.

Choose `bevel.kind` as `none`, `round`, `profile` or `object`. Round/profile depth
is a local distance and resolution controls section sampling. Profile `points` define an editable normalized quarter section, from `(1,0)` to
`(0,1)`, inside the unit square. Each control chooses `AUTO` smooth handles or
`VECTOR` sharp handles. Even-length and straight-edge sampling are independent.
This expresses custom diamond, square, chamfered or curved sections directly; the
native UI preset selector needs a separate reset callback and is not mapped by
an ineffective preset-property assignment. Object profiles reference a public Curve Object or an object alias in
`geometryResources`, including a uniquely selected native asset member. They use
planar local XY section data. Blender consumes section X/Y scale and ignores its
translation and rotation; the sweep follows the target curve's frame. Profile
Object modifiers do not define the section. `caps` requests native end filling.
`trim` selects start/end factors with independent resolution/segment/spline mapping.

A `taper.object` references one open planar Curve spline. Local X maps along the
path, and local Y controls radius; `mode` replaces, multiplies or adds to control
radii. `mapTrim` chooses whether taper mapping follows the trimmed portion. Taper
requires swept geometry. Reference cycles, incompatible types and conservative
expansion beyond two million vertices or64 dependent Objects refuse before evaluation. Bounds include
preview/render sampling, source profile sampling and dependencies; CDT planar
intersection growth receives a quadratic bound. Remove unnecessary subdivisions
or simplify contours after a budget refusal.

`path` declares enablement, duration, tangent following, radius and deformation
stretch/bounds policy. A `followPath` constraint accepts spline objects with its
fixed `factor` and optional tangent following. Ordinary hierarchy, material,
Object motion, Geometry Nodes reuse and evaluated exports compose with these
objects. A curve component copied into a Mesh Object needs an explicit
`curveToMesh` node to produce observable Mesh geometry; an empty/unconverted
procedural result refuses with `INVALID_SCENE`. An unprofiled curveToMesh can
retain an editable wire result for sampled control-shape handoffs. Animated constraint-factor authoring, broader selected-point editing,
per-spline material assignment and independent free profile handles remain required work.

## Native verification and geometric limits

Fresh verification compares every native spline, homogeneous NURBS weight,
control coordinate, handle type/coordinate, radius, tilt, knot flag, sampling,
fill/sweep/path setting and actual profile/taper pointer. Automatic handles and
quarter-profile controls are reconstructed by trusted constructors, with separate analytic
qualification of representative geometry. Persisted custom properties are not
control-geometry authority. Position comparison uses shape-relative local precision;
recenter or rescale controls when float32 storage loses a small local feature.
Native asset capture also records custom profile settings and points. Imported
FREE/ALIGN quarter-profile handles refuse because their independent handle
coordinates lack a reviewed public readback mapping; AUTO/VECTOR profile controls
remain available. This is an unfinished fidelity variant, not an exclusion.

These editable native settings do not promise arbitrary solid validity. In
Blender 5.2.3 capped object-profile sweeps depend on section winding: the qualified
clockwise rectangular profile has consistent volume; reversing it produces
inconsistent cap/side winding despite unchanged bounds. Use the spline `reverse`
control to choose the intended section direction. Nonzero-filled nested contours
can retain internal extrusion walls: planar fill area and valid opposite-winding
extrusion solids are qualified separately. Check manufacturing topology and
orientation independently before using exported geometry as a solid. Native
control fidelity does not prove arbitrary self-intersecting curve equivalence.

See [the runnable starter](../examples/schemaxis/blender-splines.json),
[resource ownership and bounds](blender-geometry-resources.md) and
[mesh editing](blender-mesh-editing.md). The whole Blender adaptor remains
incomplete, including broader curve editing, surfaces, modern hair, implicit
metaballs, typography, sculpt/paint, simulation and sequencing workflows.

Upstream reference: fixed Blender 5.2
[Curve API](https://docs.blender.org/api/5.2/bpy.types.Curve.html) and the
[5.2.3 RNA declarations](https://github.com/blender/blender/blob/v5.2.3/source/blender/makesrna/intern/rna_curve.cc).

Resource admission precedes mesh-data operators, because entering UV edit mode can
evaluate unrelated scene curves. A second check after hierarchy setup precedes
material resolution and procedural attachment. This keeps profile expansion and
dependency limits ahead of those evaluations.

Position admission checks each adjacent control edge, including the closing edge
of a cyclic contour, and each explicitly positioned handle offset. A distant
control cannot hide a collapsed short segment in the same spline. Edge-vector
error is limited to one part per million of that edge's largest component; an
authored zero handle offset stays zero. Overall position error also remains
bounded relative to the spline span. Recenter or rescale controls when native
float storage cannot preserve those features. Saved readback applies the same
local feature checks against fresh trusted controls.

An Object section uses native Curve control geometry; a downstream Array modifier
on the section does not create multiple sweep sections in Blender 5.2. Apply the
desired section construction to its control data instead. The direct authored
spline budget covers those constructors; it does not establish a total memory
bound for every instance and baked export in an arbitrary large scene. Broader
scene-wide aggregate admission remains unfinished.

Blender 5.2 partial trimming can retain an untrimmed endpoint radius when point
radii vary, producing different rings at the same cut position even without
caps. This combination refuses with `INVALID_SPLINE`. Keep point radius constant
along each spline, or shorten the control geometry before sweeping. Full sweeps
with varying radius remain available. Taper remapping with constant point radius
remains distinct: disabled uses the original path range; enabled spans the taper
over the trimmed geometry. Sparse polyline samples can limit taper detail.

Native source fidelity currently binds classic Curve point/handle selection and
hide flags. Selecting points and saving can therefore be refused even when the
rendered image is unchanged. Preserve the original output and capture a deliberate
edited `.blend` as a new native asset input; replacing verification witnesses does
not authorise the edit. This conservative boundary remains a usability gap.
