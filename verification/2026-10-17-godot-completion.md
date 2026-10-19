# Godot static assembly completion — 17 October 2026

Changed scope: `schemaxis.godot/1` gains named `transformGroup` nodes and optional
`inputs.parent` on geometry/groups. Camera/light/sprite behaviour stays at the
root. No animation, physics, authored code or nested PackedScene instancing.

## Design and independent expectations

Groups contain local XYZ metre positions, intrinsic YXZ degree rotations and
positive dimensionless scales. Host planning validates all links, types and
cycles, then produces a stable dependency ordering. Material references still
require earlier declarations; flat plans preserve order. At most 16 parent links
and explicit world-position/basis magnitude limits bound accumulated transforms.
The native worker assigns root ownership after adding each child to its actual
parent. Fresh-process PackedScene reopening measures recursive membership,
parent/owner, local/global bases and world AABBs. The host independently composes
full affine transforms and original local mesh-AABB corners, retaining induced
shear. Group AABBs union descendant geometry; empty groups have null bounds.

The literal acceptance fixture applies outer T(10,0,0) Rz(90) S(2,1,1), inner
T(1,0,0) Rz(45) S(1,3,1), then a box at local (0,1,0), size (2,2,4).
For a = sqrt(1/2), world origin is (10−3a, 2−6a, 0), basis columns are
(−a,2a,0), (−3a,−6a,0), (0,0,1), and world bounds are
(10−7a,2−14a,−2,10+a,2+2a,2). The first two basis columns have dot product −4.5:
this case detects implementations that incorrectly discard shear. An independent
supervisor algebra review confirmed these values. Changed outer translation and
scale have separately authored literal expectations. Comparison uses the existing
1e−5 absolute and relative tolerance for Godot single-precision transforms.

## Fresh checks and evidence

Official latest release API reported `4.7.2-stable`; the isolated official Linux
binary reported `4.7.2-stable (official)`. No user installation or PATH changed.
Bulk results remain ignored under `evidence/programme-20261017`:

- `godot-completion-native/qualification.json`: native nested baseline, changed
  ancestor translation/scale, all-axis YXZ order and legacy flat primitive scene all built/reopened
  successfully. Independently derived literal world bases/origins/bounds and
  exact parents/owners matched. Empty and aggregate group bounds matched.
- Ten probes changed **both** build and reopen receipts identically; forged
  parent, owner, ownership Boolean, world/local transforms, geometry/group/empty
  bounds, inheritance and membership were all rejected by input-based checks.
- Live native cancellation and timeout retained failed/unverified results and
  build logs; neither published an artifact manifest. These are actual native
  processes, distinct from mocked lifecycle host tests.
- `test_godot_hierarchy.py`: seven host tests passed, including deterministic
  immutable/forward-parent plans, independent shear algebra, located
  missing/type/cycle faults, scale/depth/world magnitude limits, forbidden parent
  ports, optional-port schema, shared authored references and reusable inputs.
- `test_schemaxis_godot.py` with the native executable: twelve tests passed with
  two graphical tests explicitly skipped. This includes the original native
  readback/tampering regression and host lifecycle checks.
- `godot-legacy-native/qualification.json`: original all-primitive, imported
  asymmetric glTF, fixed-camera and main-scene playback qualifier passed; no
  preview was requested.
- Shared authored/effective binding executed and verified natively; the qualifier
  checked retained authored references against the resolved child document.
  Workflow execution and resume both verified; resume reused the same attempt.
- Actual CLI capability search for `assembly pivot` returned transformGroup.
- Source-bound common native conformance passed four cases: baseline, variant,
  hierarchy and hierarchy-variant, plus timeout/cancel and publication tamper
  checks (`godot-conformance-native/qualification.json`). Subsequent shared Help
  generation and final wording make that digest stale; final registration waits
  for the programme source freeze. No receipt freshness was edited or forged.
- Structural admission passed after shared generation (`godot-admission-final.log`).
  The five Godot production Studio search/contextual Help checks passed; seven
  shared Studio library tests passed.
- Guidance audit: 173 reviewed, 33 attributed records, zero pending/stale.

Shared generated reference/Help and admission checks passed at integration.
Final source-current common receipt registration remains coordinated at the
programme source freeze; this note does not present old receipts as fresh. Existing historical flat/graphical qualification remains
historical. New hierarchy acceptance is headless and does not qualify GUI editing,
mouse interaction, visual quality, animation or physics. Receipts are integrity
records, not signed attestations against a party able to rewrite all evidence.

## Completion checklist

| Item | Changed-slice delivery and check |
| --- | --- |
| registration | Existing manifest route/runtime/hooks preserved; transformGroup is declared through its existing declaration binding. Unsupported MPI, live editing and time batches remain explicit. |
| schema | Typed group options and optional typed parent ports; required material ports preserved; literal and shared authored-reference host tests pass. |
| semantics | Located orphan/type/cycle failures; finite positive scale, maximum depth and accumulated transform limits; deterministic planning. |
| native-mapping | Public Node3D local/global transforms, Node parent/root owner and PackedScene save/reopen; current official API pages reviewed (links below). |
| execution | Two distinct native processes; recursive readback independently checked, joint-forgery probes rejected, live timeout/cancellation failure evidence retained. |
| discovery | Application scope, curated operation terms and four reviewed multiword/synonym/ambiguous/negative search cases; actual CLI acceptance and five production Studio checks passed at integration. |
| guidance | Local coordinate semantics, defaults/units/order/scale limits, optional parents, ownership and pitfalls documented per changed field; audit clean. |
| help | Guide and actionable faults updated; operation/field guidance supplied for shared reference/Help generation. |
| examples | Editable nested standalone fixture, cyclic-parent negative readiness example and Studio two-block pivot starter; baseline/ancestor variant literals in readiness. |
| tests | Seven hierarchy host tests and legacy/native regression pass; new qualifier's native checks pass; seven shared Studio library tests and five production search/Help checks passed; generated freshness remains integration-owned. |
| qualification | Bounded fresh 4.7.2 headless evidence above; common source-bound conformance is run separately and final registered freshness remains integration-owned. |
| maintenance | Latest release checked; absorbed version remains 4.7.2, acceptance recipe/evidence extended for hierarchy. |

## Upstream sources reviewed

- [Node3D](https://docs.godotengine.org/en/stable/classes/class_node3d.html): local
  transforms relative to parent, intrinsic Euler order, global affine basis.
- [Node ownership](https://docs.godotengine.org/en/stable/classes/class_node.html#class-node-property-owner):
  owner must be an ancestor; set after add_child to retain PackedScene members.
- [PackedScene](https://docs.godotengine.org/en/stable/classes/class_packedscene.html):
  packing persists owned descendants; instantiate restores hierarchy.
- [Official latest release](https://api.github.com/repos/godotengine/godot/releases/latest):
  4.7.2-stable observed for this check.
