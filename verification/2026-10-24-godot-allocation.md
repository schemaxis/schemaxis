# Godot saved-scene hierarchy verification — 24 October 2026

Changed scope: offline `verify` (and `run`'s final verification) of
`schemaxis.godot/1`. No operations, options, native mappings or supported formats
were added; `absorbedVersion` stays 4.7.2.

## Issue and repair

Hierarchy, ownership and transform evidence came only from the two native
receipts, and `scene.tscn` was bound only by SHA-256 values held in the same
directory. A scene edited so that a group was reparented or a block moved, with
`artifacts.json` and `verification.json` regenerated, verified as the authored
assembly. `verify` now reads the retained text scene with a bounded stdlib reader
(`tscn.py`) and checks node membership, Godot types, full parent paths, absence of
foreign owner/instance/group attributes, local group and geometry transforms,
camera direction and declared positions against the plan.

## Faults

| Condition | Code |
| --- | --- |
| Scene contradicts the plan | `VERIFICATION_FAILED`, location `scene.tscn`, line in recovery |
| Not UTF-8, missing header, unreadable node/transform, duplicate or second root | `SCENE_MALFORMED` at `scene.tscn:<line>` |
| Embedded resource over 4 MiB | Accepted by streamed structural scan; existing import limits unchanged |
| Edit without refreshed manifests | existing `Artifact changed` failure |

## Evidence

- Before: the reparent cases were accepted (one passing and three failing
  subtests in `test_godot_allocation.py`).
- After: `test_godot_allocation.py` (six host tests) rejects reparenting,
  moved/retyped/added/removed nodes, foreign ownership and instancing and a flipped
  camera. It also separates malformed scene text and the size limit, and accepts a
  genuine Godot 4.7.2 scene. Host: 13 tests with `test_godot_hierarchy.py` pass.
- Official latest release API reported `4.7.2-stable`; the available official
  Linux binary reported `4.7.2.stable.official`. Serial native checks on it passed:
  `test_schemaxis_godot.py` (12 tests, two graphical skipped),
  `qualify_godot.py` and `qualify_godot_hierarchy.py` (no preview), nested
  hierarchy, primitive, lighting and parented sprite/omni/spot scenes verified, and
  a native hierarchy directory with a reparented scene and regenerated
  manifests is rejected at `scene.tscn`.
- These are bounded acceptance runs, not a refreshed source-bound conformance
  receipt; graphical preview, GUI editing, animation and physics were not run.

## Limits

The text-scene check does not compare materials, mesh resources, light or camera
settings, which remain native-receipt evidence. Hashes and receipts are integrity
records, not signed attestations. No retained pre-change native directory was available to re-verify;
the check reads only fields Godot's PackedScene always writes, and the fresh
native scenes above passed.

## Checklist

registration, schema, native-mapping, discovery, guidance: unchanged, no new
declarations. semantics, execution, tests, help: verification boundary, faults and
guide updated as above. examples: existing hierarchy example exercised. qualification
and maintenance: bounded runs only; upstream.json untouched.

Independent review found ignored whitespace headers, multiline transforms and root placement. Follow-up regressions reproduced five unchecked edits; the reader now recognises whitespace headers, refuses incomplete node assignments and placement aliases, and requires identity root placement. Fourteen hierarchy/structural host checks pass. Native serial recipes are repeated after this repair; graphical scope is unchanged.
