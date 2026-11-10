# Blender finite mesh editing acceptance checkpoint

Qualified 5 November 2026 against official Blender 5.2.3 LTS, build e13b728c6880.
Whole Blender and broad mesh-modelling coverage remain **INCOMPLETE**.

Execution/qualifier source: `649d72ab6fc9616febac5fd0344a60604b242c52`.
The native batch kept the entire runtime archive unchanged before/after every
component: `sha256:b3a8a1c82d488f2bb79e23c24ebcfb04c2873123f433a7e9328a9926e3451d22`.
Adaptor source fingerprint:
`sha256:193cd116053f668df74f38eeaf4b753fac97b13c0dfd55daf680ac7d24b5eb67`.
This documentation checkpoint does not relabel earlier epochs as current.

`tools/qualify_blender_mesh_edits.py` passed 22 native positive workflows and 7
structured refusals. Independent literal expectations cover staged extrusion/
inset volume 10.25, concave triangulation area 3, welded/split/deleted counts,
outward winding volume 8, closed bridge volume 8, tapered frustum volume 7, both
axis-aligned half volumes 4, an open five-face cut and a native diagonal
tetrahedron volume 4/3 with cap/source material contrast. Copy/shared instances,
original DAG reconstruction, original native material selection, part/carrier
material replacement, fields/UVs and procedural reuse compose with those edits.
Historical accepted CAD inputs retain independently parsed 7370 vertices/4604
faces and authored dimensions. Those bytes are input provenance, not fresh
FreeCAD producer qualification.

`tools/qualify_blender_mesh_edit_tamper.py` passed 11 refreshed-hash native
geometry/winding/shading/field/edge/UV/sharing/material mutations and 6 unchanged
native open/save controls on the same verifier path. An additional source-base
forgery moved native geometry and refreshed all observed companions, then forged
the original base. Host deterministic replay explicitly accepted that internally
consistent forgery; fresh trusted reconstruction from unchanged original/retained
source bytes rejected it. The identical unchanged-save/all-companion-refresh
control passed. Total: 12 semantic attacks and 7 unchanged-save controls. These
checks isolate native guards through the provider verifier after a full public
baseline check; they do not claim mutated framework companion hashes were valid.

`tools/qualify_blender_mesh_edit_lifecycle.py` passed 4 connected cases: the public
40×30×20 mm housing with 2 mm walls/3 mm floor (volume 8088 mm³), a 3 mm lid at z27
(volume 3600 mm³), independently parsed physical GLB; post-edit eight-vertex morph
with frame 1/6/11 top z2/3/4; a manual native edit adopted as a new source; and
packed field/UV reopen without the original source while receipt verification
correctly refused original absence and passed after restoration.

Prior native families were repeated at the same source: groups 5, assets 8,
motion 5, collections 10 plus 8 refusals, Boolean/quaternion field effects 2,
mesh-data 20 plus 4 refusals/93 type-domain-storage variants (both CAD inputs),
resource-main 13 plus 6 refusals and resource-assets 8. All passed.

All 119 Blender unit tests passed with the actual live-runtime variable configured,
zero skips. The earlier host-only run separately recorded 3 optional skips; it is
not substituted for this native-enabled run. Templates 3, schema/parser parity 5,
production conformance and 3 actual browser forms passed. The nested topology form
distinguishes 11 operations and 6 selectors and authors an inset box. Guidance has
5451 reviewed records/246 reference records, zero pending/stale; existing records
were preserved. Private Help generation/check passed 1522 topics/685 files and
all 8 search cases, including exact mesh-edit/field/resource guide discovery.
Shared generated Help, packaged readiness and installed-source acceptance remain
the integration owner's pending gates.

Failures were retained and repaired: a crossing five-point outline originally
triangulated despite self-intersection; polygon operations now admit bounded
nonadjacent boundaries explicitly. Post-edit morph Basis originally compared
against the pre-edit constructor; it now compares independently replayed edited
geometry. A local X1,000,000 plane extruded 0.001 originally verified with zero
thickness/volume after float32 collapse; actual written faces and shape-relative
coordinate precision now refuse that loss. Its recentered positive retains
0.001 thickness/0.004 volume under a 2 ppm oracle. A resume harness reused expected-
refusal directories and got OUTPUT_EXISTS; it now allocates fresh refusal paths.
Earlier failed records were not promoted into acceptance.

Verification establishes the declared finite replay and these independent
fixtures, not arbitrary mesh validity or unrestricted native-operator parity.
Individual convex inset, two closed equal-count bridge loops and complete
manifold halfspace cuts with simple unnested caps remain explicit limits.
Existing UV/custom-normal/attribute/edge data needs explicit discard; existing
weights/morphs refuse pending reviewed propagation. General selected bevel/
knife/dissolve/subdivide, rich curve/surface workflows, sculpt/paint and the other
major stable families remain required work, not exclusions. Source-curve
render-resolution budgeting is addressed by the separately scoped5November
curve-budget checkpoint; its receipts do not relabel this execution epoch.

Runnable example: `examples/schemaxis/blender-mesh-editing.json`; authoring and
recovery: `docs/blender-mesh-editing.md`. Compact receipts/logs and representative
outputs are retained in the programme evidence checkpoint; temporary execution
and mutation scratch is separate and is not a frozen source archive.
