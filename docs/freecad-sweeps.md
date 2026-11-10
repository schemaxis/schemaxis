# Editable paths, sweeps and flanged elbows

`additivePipe` and `subtractivePipe` sweep closed, same-Body profile wires along
one connected sketch wire, preserving native PartDesign histories. They can use
constant sections, ordered changing sections, a second orientation guide or a
world binormal. An additive sweep can start a Body or join its current tip;
a subtractive sweep must remove material from the current tip. The original
profile and extra sections are consumed once; paths can be shared, for example
by the outer and inner sweeps of a hollow elbow.

The [flanged elbow](../examples/schemaxis/freecad-flanged-elbow.json) expresses
bend radius, outer radius, wall thickness and flange dimensions once. Native
length relationships drive both circular sections, the dimensioned path, attached
flanges and both machining bores. The [simple elbow](../examples/schemaxis/freecad-sweep.json)
is a smaller starting point. Both publish editable FCStd plus checked STEP/STL.

## Dimensioned bend intent

`arcPath` removes the need to author radial construction geometry or constraint
indices. `bendRadius` is positive mm (default 10); `sweepAngle` is 1–359 degrees
(default 90). In the path's local frame it starts at the origin, tangent to +Y,
with centre at (−radius, 0), and turns counterclockwise. Its endpoint is
(radius·(cos(angle)−1), radius·sin(angle)). Ordinary profile frames and checked
planar attachments apply. Set the path frame so its initial tangent crosses the
section plane: the example uses xAxis (−1,0,0), normal (0,1,0), making its initial
world tangent +Z and its 90° outlet tangent +X.

The native sketch retains one named bendRadius length and one sweep angle,
construction radii and solved endpoint/centre relations. `drive.bendRadius`
accepts a persistent affine length relationship. Native angle editing is retained;
a general angular-driver document contract remains open. A complete closed path
uses a general circle sketch; general fixed or solved line/circle/arc sketches
can also supply connected paths. Arbitrary 3D wires and spline families are not
yet authored by this profile contract.

## Section orientation and corners

`orientation` selects normal (default, native Standard), fixed, frenet, auxiliary
or binormal. Normal/Frenet follow the native path frame. Fixed keeps the section
orientation while translating along the path: an oblique sweep's volume depends
on projected section area, rather than simply section area times path length.
Auxiliary requires `inputs.auxiliary`, a distinct connected same-Body guide.
`auxiliaryEquivalence` defaults true (arc-length correspondence); false uses the
native corresponding guide-plane method. Arc-length matching can incline a section
when paired guide points lie at different axial positions; area times centreline
length is therefore not a universal volume formula. It applies only to auxiliary mode.
Binormal requires a nonzero world XYZ direction in `options.binormal`; the
compiler converts it to the actual native feature frame and readback converts it
back. No native coordinate-frame guess is left to the author.

`transition` selects transformed (default), miter or rounded. Transformed requires
a tangent-continuous path; sharp junctions are refused because the native kernel
can silently lose a leg. Miter makes the common sharp pipe-corner construction.
Rounded retains native round-corner intent, but some sharp circular corners in
FreeCAD 1.1.4 change volume during STEP export; the ordinary geometric round-trip
check rejects those outputs. Smooth rounded-transition bends pass. No export
budget is enlarged to admit a damaged handoff.

Optional `inputs.sections` supplies ordered additional closed, unused same-Body
profiles and selects native Multisection transformation. The initial profile is
supplied separately and must not be repeated in sections. Constant transformation
is selected when sections are absent. Unimplemented native transformation entries
are not exposed. Matching section topology, valid geometric placement and one
connected remaining solid are still required.

## Persistent face centroids and verification

A new plan containing `onFace.anchor: centroid` records the native centre-of-mass
attachment policy. Its sketch uses the fixed native AttachEnginePoint engine and
CenterOfMass mode, retaining the actual selected face link and a Cartesian
orientation/normal offset. The centre follows changes to the selected face's
boundary and position through native recompute, save and reopening. This repairs
the earlier FlatFace plus static-offset materialisation, which could leave a
moving elbow flange behind. Retained old plans without the policy marker still
have their older explicit FlatFace interpretation; new plans cannot verify a
forged downgrade. Rebuild older centroid publications to obtain the new policy.
`projectOrigin` retains its projected-origin FlatFace contract. Selections still
require one unambiguous extreme Cartesian planar face; arbitrary rotated/curved
support selectors and general topological repair remain open.

Verification checks native and saved link types, exact section/path memberships,
orientation/transition/transformation flags, binormal coordinates, editable sketch
geometry/constraints and Body history. Native reopening must preserve these
records. The dedicated sweep qualifier independently checks analytic volumes and
centres, wall/void samples, implicit torus surfaces, corner geometry, two stages
of direct native edits and fresh reopening, refreshed-digest saved mutations and
workflow reuse/invalidation. STEP/STL lose the feature history; STL retains its
explicit tessellation budgets. This advances the mechanical feature family;
[whole-application completion](freecad-capabilities.md) remains open.

Public basis: [FreeCAD AdditivePipe documentation](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_AdditivePipe.md),
[stable Pipe API](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/PartDesign/App/FeaturePipe.cpp)
and [stable attachment API](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Part/App/Attacher.cpp).
