# Blender scene-production milestone — 4 November 2026

This is a broad implementation milestone in the strategic completion programme,
**not a claim that the Blender adaptor is Done**. The
[capability-family map](../docs/blender-capabilities.md) retains important open
workflows, including linked/cache project reuse, reusable node-group interfaces,
complete attributes/UV workflows, broader simulation and portable caches,
sculpt/paint/Grease Pencil and native sequencing/tracking.

## Delivered behaviour

The existing mesh/material DAG composes with typed named assets, nested
collections, shared/independent object-data instances, collection instances,
parenting, explicit mesh topology/UVs, editable text/curves/lights/cameras,
object/bone animation, armatures and explicit skin weights, reviewed constraints,
curated shader/Geometry Nodes/compositor graphs, rigid bodies and cloth.

An inferred-pivot turntable intent lowers selected geometry/hierarchy roots into
an editable native control, parent relationships and linear motion. Its pivot is
derived from actual geometry bounds, and an independent host rotation oracle
checks the resulting native matrices. This adds reusable product-presentation
intent above native channel/socket records.

Selected-frame PNGs and evaluated STL/PLY/OBJ/GLB/USD geometry are published with
explicit membership, frames, units and losses. GLB/USD use physical metres;
OBJ/PLY/STL retain source numerical units. Geometry is independently decoded on
the host and imported again natively. Neutral files retain evaluated frame
geometry, not native rig/procedural history or complete material appearance.

Production verification opens the **current** project bytes using trusted current
code and a caller-configured Blender executable. Receipt executable paths are not
execution authority. Auto-execution and project scripts are disabled; linked
libraries are refused. Missing configuration is an explicit
`VERIFICATION_RUNTIME_REQUIRED` fault. Legacy scene verification retains its
previous compatibility contract.

## Native evidence and limits

The target is the official Blender5.2.3 LTS stable release of22October2026,
installed from the primary distribution with its published SHA256 checked.
The existing local launcher actually reported4.5.14 LTS and was not used as
proof of5.2 behaviour. Upstream sources:
[release](https://www.blender.org/releases/5-2/),
[distribution](https://download.blender.org/release/Blender5.2/),
[API](https://docs.blender.org/api/5.2/).

Seven connected native cases passed:

1. Instanced collection/hierarchy asset, checker shader, linear motion, three
   rendered frames and GLB/OBJ publications; literal world translations0,2,4.
2. Geometry Nodes transformation and compositor exposure, rendered PNG and PLY;
   independent literal transformed bounds.
3. Explicit armature/skin deformation and STL; a local-Y pose translation of a
   world-Z rest bone produces the independent expected world-Z deformation.
4. Rigid-body fall; sequential centres decrease and agree with an independent
   ballistic equation within the stated discrete-solver tolerance.
5. Pinned cloth; an initially flat grid sags while retaining its declared pins.
6. Off-centre product turntable; inferred pivot4.5 and a quarter-turn placement
   agree with an independent rigid-rotation calculation.

7. All twelve reviewed constraint constructors/settings persist, including IK;
   copy-location and local location limits have independent literal matrix checks.

Each case saves/reopens the native project, re-evaluates its frame samples and
performs fresh current-byte verification. Seventy-three reviewed node
constructors/defaults/properties/socket literals also passed native save/reopen.
That catalogue check establishes mapping compatibility, not an independent effect
proof for every possible graph. Cross-family effect checks use the connected
cases above. Bézier interpolation retains native automatic handles; independent
host intermediate interpolation covers linear/constant tracks.

A native animation endpoint was altered and the project publication hash was
refreshed. Verification still rejected it through fresh native readback.
Independent export tests additionally reject refreshed-hash geometry changes.
Physics acceptance is bounded serial evaluation/replay, not convergence proof or
portable cache publication.

## Completion checklist

| Item | Reviewed delivery |
|---|---|
| Registration/schema | Existing version/routes preserved; typed optional production records and finite reviewed node/constraint/channel catalogues. |
| Semantics | Reference/cycle/type/frame/topology/UV/skin/constraint checks and conservative procedural expansion limits precede native assignment. |
| Native mapping | Shared descriptors drive assignment/readback; observed5.2 API changes use native compositing groups and current sockets. |
| Execution | Isolated processes, inherited deadlines/cancellation, captured image inputs, persistent project state, fresh verification and exact output membership. |
| Discovery | Application-level strategic terms, curated terms for all37 legacy operations and adaptor-owned synonym/multiword/ambiguous/negative cases. |
| Guidance/Help | Production conceptual glossary and field guidance, user guide, family map; root integration regenerates shared references/Help. |
| Examples/Studio | Editable connected production starter and Studio template; standalone production, node-catalogue, output and tamper qualification tools. |
| Tests | Host scene/node semantics and output/intent checks; configured native/live regressions and connected acceptance. The focused host/live/scaffold/completion suite ran73tests with zero skips;
  Studio search/library ran549tests with zero skips. Final shared generated checks
  and full integration results are recorded separately. |
| Qualification | Actual5.2.3 acceptance is separate from legacy source-bound receipts; integration must register fresh canonical route receipts. |
| Maintenance | Latest-stable target5.2.3 and acceptance obligations updated; assessment remains an uncertain whole-application estimate, never a completion certificate. |

The source-bound final conformance receipts and shared generated assets are an
integration obligation. The strategic programme continues after this milestone.


## Direct production and editable asset reuse follow-up

`schemaxis.blender.production/1` accepts typed production records directly without
an authored placeholder graph. Original input and route/schema provenance remain
exact; deterministic application-owned lowering reuses the existing executor.
The product presentation starter exposes units, appearance and inferred-pivot
turntable intent as one reusable scene task.

An additional connected acceptance creates a textured UV mesh and instance,
weighted armature and animated child hierarchy, then reuses it through seven
source formats: packed local blend, GLB, embedded-resource glTF, STL, PLY, OBJ and
bounded static baked USD. Each reuse publishes three frame PNGs and all five
geometry formats, saves and reopens the editable project, and performs fresh
current-byte native verification. Literal pivot and frame-six bounds distinguish
the native rig/child motion from evaluated static neutral geometry. Geometry-only
formats have explicit appearance losses; linked/stateful caches and general USD
composition remain open.

Imported-state fidelity is finite and read-only: admitted native object, node,
modifier and constraint classes capture actual mesh/UV/attribute/weight data,
rest/pose bones, complete animation key/handle payloads, shader values/links and
packed image bytes. Unsupported classes, external ownership and NLA fail
explicitly. Refreshed-hash material roughness, unsampled animation-key, UV and skin
mutations are separate negative controls. Whole-application coverage remains the
conservative 35% subjective breadth estimate, with important families open.

The follow-up focused configured suite ran79tests with zero skips; Studio search/library retained549passing tests. All three routes passed structural admission with3367reviewed guidance records,246inherited references and zero pending/stale records. Imported native collection-instance dependencies currently fail explicitly; authored collection instances and descendant publications remain supported.
