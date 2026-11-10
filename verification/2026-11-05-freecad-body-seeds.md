# Imported-solid Body history bridge — accepted milestone

This milestone targets checked imports feeding a native PartDesign BaseFeature,
editable ordered Body history, explicit source/Body/component coordinate systems,
and portable sourced assembly copies. Whole FreeCAD completion remains open.

Implementation and authority are distinct from product acceptance. Current owner
proofs cover a refined STL stock and cylindrical through Pocket, a noncommuting
source-Z/Body-Y/component-Z frame variant, exact source-asset embedding and strict
source-copy assembly, standalone fresh verification after producer/original asset
removal, repeated native saves, STEP import, live source/Body edits, colliding
asset basenames, read-only configured GUI inspection and pinned-input workflow
adoption/recovery. The scoped independent review and exact integrated/package
acceptance are complete at the checkpoints below. Peer source reviews remain
narrower than native or package acceptance.

Source-labelled owner evidence:

- `5523109`: 302 FreeCAD host checks and actual refined-STL seeded Body plus
  two linked assembly instances pass. Independent analytic volume and transformed
  bounds distinguish local assembly shape from the world part export.
- `c785007`: 41 affected assembly hosts and actual producer/original-asset removal
  pass. A held-out source clock31°, Body tilt35°, grounded component17° and
  joint clock29° passes independent volume, area, centre and corner-bound checks
  before/after native recompute, plus STEP world geometry and preserved Body layout.
- `745b977`: legacy unchecked readSTEP is refused throughout seeded graphs.
  Seven focused admission/role hosts pass. First native unchanged-save proof
  fails strict BREP binding because native restore normalizes diagonal direction
  numbers; the failed epoch is retained.
- `0eb1a2b`: the existing finite trusted-reference save lifecycle also applies to
  typed seeded Bodies. Only fresh generated references are opened, never submitted
  FCStd documents. Whole initial or whole first-save SID/map/XML/payload binding
  remains mandatory, following independent saved-source facet measurements.
  Both layouts pass first/second/third save and original-state alternation (12
  controls). Forty authority controls pass: original-asset owner/property/type/
  member/bytes/role, seed link/expression, cached geometry and coforged local
  volume/frame witnesses, plus 22 individually mixed persistent-map line changes
  and restored positives. Incomplete attack-harness attempts are retained and are
  not counted as source-authority proof.
- `29f3af7`: actual source Placement and Body-layout edits persist through four
  fresh native readbacks in the part and its copied assembly. Independent volume,
  area, centre and corner bounds distinguish the noncommuting transforms. These
  edits are not claimed to match the original authored run.
- `8300961`: all three public STL/turned-STL/checked-STEP examples build and verify
  with independent analytic volumes. The aggregate copy proof fails on colliding
  included-file basenames; its failed result is retained.
- `4beb497`: direct staging from independently admitted original ZIP bytes plus
  FreeCAD's explicit `(filePath, copiedMember)` assignment passes two different
  original assets with the same basename, two definitions, three instances and
  two joints. Five refreshed copied-owner/member/bytes/resource attacks refuse;
  restored positives and an ordinary unseeded assembly regression pass.
- `413da05`: the public configured-GUI endpoint passes after mandatory handoff of
  the verifier's checked native digest. A meaningful host mutation between
  verification and GUI inspection refuses before request creation or GUI launch.
  Its timeout-tail display classification failure is retained and repaired.
- `2444c37`: the affected tail passes with the current installed GUI archive:
  actual FreeCAD 1.1.4 worker cancellation, bounded disappearance of worker,
  private D-Bus and Xvfb PIDs, stale successful-readback refusal for a zero-exit
  nonworker, and normal GUI recovery with unchanged native bytes and public
  verification. Actual paused-native timeout passes in the preceding labelled
  tail. An immediate cancellation PID-disappearance assertion in that preceding
  tail failed and is retained; it is not counted as a passed cleanup check.
- `59e0133`: 313 focused FreeCAD host tests pass. The public qualification tool
  builds all three pinned STL/turned-STL/STEP examples after deleting their
  original files, verifies independent analytic volumes within the unchanged
  `1e-7` guard, and builds the configured-GUI two-definition, three-instance
  sourced assembly with colliding original basenames. All four workflow jobs
  reuse; native assembly damage rebuilds only that job. A changed authored pin
  refuses with `RESUME_MISMATCH`, physical snapshot corruption refuses with
  `RESOURCE_MISMATCH`, and restoring bytes permits reuse. Standalone assembly
  verification passes after removing every producer packet and snapshot; the
  restored whole workflow verifies. The current installed constructor/verifier
  also passes the forty historical-packet authority/map controls with restored
  positives. Seven core planner and two complete Studio catalogue tests pass;
  FreeCAD guidance has zero pending or stale records.
- The browser test added after that runtime epoch passes actual imported-stock
  starter validation, seed discovery/form ownership, validation and atomic undo.
  Its first setup attempted to create an incomplete snippet construction context
  before inserting its seed; the API correctly refused it. That failed result
  remains retained, and the browser-only retry starts from a complete valid
  imported-stock document. No provider change or admission waiver was needed.

Reproduce the focused pinned-input workflow from the repository root:

```bash
PYTHONPATH=src python3 tools/qualify_freecad_body_inputs.py \
  --freecad /absolute/path/to/freecadcmd \
  --freecad-gui /absolute/path/to/freecad \
  --output-directory /absolute/path/to/a/new/qualification-directory
```

The command creates and damages only its own copied fixtures and run packets.
Broader geometry, edit, authority and save-state epochs above retain their own
source bindings; this command does not claim to repeat all those phases.

These historical epochs do not qualify subsequent product metadata or the exact
integrated package. Blender's independent `4a7217d` source-authority review and
root's finite copy-name and subsequent GUI/source delta reviews found no new
actionable bypass within their recorded source-only scope. Independent native
and exact package results are recorded separately below. The main part route
accepts supported typed Part solids too; portable assembly sources currently use
the separately recognized checked-import seed history vocabulary. Broad foreign
FCStd admission, Draft-to-Body conversion and a source-world assembly mode remain
missing. No geometry tolerance or general included-file/map policy is relaxed.


Independent seed-only stock correction (`579167e`, `99229be`):

- An independent ordinary first/final `bodySeed` project produced valid stock but
  assembly planning safely refused its native empty inline string table. The
  repair recognizes only checked-import seed-only histories, with exact empty
  attributes, no strings or SID payload, and complete literal map, owner, alias,
  shadow and postfix dictionary inventories. A table-less assembly requires
  every retained source to pass this predicate and binds the whole freshly
  regenerated archive; the general hashed-history binder is unchanged.
- The affected tilted copy exposed small nonzero `Face.Volume` values for open
  faces. Fresh ordered history measurements now use the sum of actual Solid
  volumes for enclosed material, with zero for lower-dimensional entities. Native
  orientation, area, complete geometry and topology remain bound. The existing
  64-ULP comparison and analytic `1e-7` guard are unchanged; no value is clamped.
- Owner current verification of historical inline and machined hashed sources,
  actual pure-inline and mixed-hashed configured-GUI assemblies, independent
  volume/centre and full transformed box corners pass. Twenty-four refreshed
  Part/assembly string/member/asset/map/postfix/BREP/orientation mutations refuse;
  restored positives and three actual same-basename forced-recompute saves
  alternating with their original state pass. The private receipt-lookup,
  incomplete L-region oracle and relocated-packet setup failures are retained,
  excluded from guard evidence, and corrected without repeating passed phases.
- Independent review on clean `99229be` uses the original pinned centimetre STL,
  permuted/clocked source and rational full-3D Body frame. Current source verify,
  fresh two-instance assembly, private GUI, native recompute, independent world
  and Body-local volume/area/centre/eight-corner geometry, and same-basename save
  pass. Refreshed coforged local witnesses, nonempty inline table, Face flag and
  nonzero source BREP mutations refuse. Standalone assembly verification passes
  after original file, producer packet and pinned snapshot removal, preserving
  the native SHA; restored positives pass. Its private Part-versus-assembly
  artifact-index error is retained separately. This closes the reported gap in
  the reviewed scope; whole FreeCAD and integrated package acceptance remain open.

Final owner product epoch `290dd20` passes 317 focused FreeCAD hosts and the
expanded public qualifier: four pinned STL/turned-STL/STEP/first-seed producers,
a three-instance machined-stock assembly and a separate two-instance seed-only
assembly. The latter explicitly checks the native empty inline tables and
independent volume, area, centre and transformed eight-corner bounds at `1e-7`.
All six workflow jobs reuse; damaging the machined assembly rebuilds only it.
Changed pins and physical snapshot bytes refuse, restored snapshots reuse, and
both assemblies verify after every producer and snapshot is retired. The restored
workflow and historical ordinary unseeded source/assembly verify with the current
binder. The exact runtime archive content differs from independently reviewed
`99229be` only in editorial `assessment.json`; execution modules are unchanged.

Private Help generation verifies all 1,597 topics current, and all FreeCAD search
cases pass. Final owner evidence is copied and rehashed under
`evidence/freecad-body-seeds/epochs/290dd20/manifest.json` (465 records), alongside
the separately retained independent `99229be` review. The earlier `59e0133`
manifest and failures retain their original scope. Shared integration assets and
exact installed-package qualification passed at the root checkpoint below.


Integrated milestone acceptance (`bff99cd`, 5 November 2026):

- The complete 36-commit imported-Body/source-bridge queue is integrated. All
  98 FreeCAD provider Python files match the reviewed owner checkpoint `afdfa4b`
  byte for byte. The independent `99229be` native authority and GUI checks retain
  their original source scope; the later owner runtime differs only in assessment
  metadata. Those checks are reused on this stated basis, rather than relabelled
  as new integrated executions.
- The integrated delivery passes 317 FreeCAD and 87 shared/readiness/HDF5/Blender
  host checks, the current imported-stock browser case, all four adaptors'
  guidance/readiness checks, generated references/Help/MCP parity and the
  unchanged private source gate. Main-route guidance now accurately describes
  checked seed histories and the narrower portable assembly-source vocabulary.
- The public six-job native qualifier passes all nine workflow groups on the
  exact integrated source: four pinned producers and two assemblies, independent
  geometry, complete reuse, damage recovery, changed-pin and changed-snapshot
  refusals, restored reuse, both assemblies verified after every producer and
  snapshot is removed, and restored workflow verification. Its first invocation
  used the wrong working directory and failed before native execution; that
  diagnostic is retained separately from the successful run.
- The fresh wheel has SHA-256
  `598cb445aa1591e6576d5eafda1ec228e2f86e953fc1ff282f011e22f2a3ce2b`.
  Every packaged file matches the integrated source and every runtime Python
  module is present. A fresh isolated installation passes discovery, starters,
  bundled Help and native-import-free host discovery for all four adaptors,
  installed browser authoring and the unchanged wheel gate.
- The installed FreeCAD probe builds an imported/machined Body and a two-instance
  sourced assembly. Independent part volume is 6021.825229575319 mm³ and assembly
  volume is twice that value, using the existing `1e-7` comparison. Fresh workflow
  verification, standalone assembly verification after the original STL and
  producer packet are physically removed, and restored workflow verification
  pass. Installed HDF5 NULL/uint64/selected-field editing with an independent
  consumer and Zstandard round-trip/source-removal checks also pass.
- The first installed probe selected the wrong private STL fixture. Root stopped
  its own job after noticing the mismatch; it is incomplete, with no native
  success credited. The corrected run reused the exact clean-source wheel only
  after checking every package byte and runtime module, then used a fresh install
  and new output directory. Product source and tolerances were unchanged.
- Native and installed evidence, failed/incomplete diagnostics, exact drivers,
  wheel and receipts are retained with rehashed file and decoded archive records.
  This acceptance-note-only change is outside the package and leaves the executed
  provider source digest and wheel bytes unchanged.

This accepts the imported-solid Body/source-bridge milestone. Whole FreeCAD
remains **INCOMPLETE**: CAM drilling/tool families, Helix precision and the other
required application-wide inventory gaps still need implementation and proof.
No package version bump, release or general foreign-FCStd admission is implied.
