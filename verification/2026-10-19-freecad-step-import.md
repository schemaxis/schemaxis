# FreeCAD checked STEP import, refine and hardened exports

Phase three, first increment, of the FreeCAD strengthening. It adds checked import
of one external STEP solid (`importSTEP`) with explicit units, orientation,
placement and analyst facts, plus an optional parametric refine. Every new
`schemaxis.freecad/1` run now gets hardened export verification. Saved
verification reads only retained source copies, for both `importSTEP` and legacy
`readSTEP`.

Earlier phases (parametric parts, PartDesign, sourced assemblies) stay accepted
and unchanged: authored contracts, defaults and the exact 17-example /
21-member baseline plans are preserved. This increment earns no additional
strengthening credit. Imported parts in the assembly route, defeaturing, face
selectors, healing, XDE/assembly STEP and live operation are out of scope.

User guide: [docs/freecad.md](../docs/freecad.md).

## Design decisions

- **Contract.** `importSTEP` takes `file`, `units` (mm/cm/m/inch, which must equal
  the length unit the file assigns), `orientation` (signed file axes for part
  +Z/+X, right-handed), `placement` (position and clocking) and `expect`. The
  expected facts are in the part frame (after units and orientation, before
  placement): volume, plus a centre of mass or at least one inside and one
  outside point. `refine` is optional. No authored option disables a check.
- **Admission.** A bounded ISO 10303-21 lexical scanner and reference walk runs on
  the host. It enforces:
  - 32 MiB, 100000 entities and 2000 oriented edges per loop;
  - token, string, list and nesting limits;
  - ASCII text; no duplicate or unresolved instances;
  - AP203/AP214/AP242 only;
  - exactly one shape definition, admitting either a direct advanced B-rep
    representation or one plain `SHAPE_REPRESENTATION_RELATIONSHIP`;
  - no product structure, transformation, external reference or unreferenced
    B-rep/representation/unit context;
  - a closed entity vocabulary.

  The unit comes from the context actually reached. Units are never assumed and
  never applied twice.
- **Source lifecycle.** Planning reads the authored path and binds the resolved
  absolute path, digest, schema and unit into the plan. Capture copies exactly
  the planned bytes and rescans the retained copy before any FreeCAD process
  starts.

  Saved verification plans with an explicit captured-source provider, which
  requires all of:
  - retained bytes that hash to the capture record;
  - a recorded path that agrees with the authored value (a relative value matches
    the recorded tail);
  - a replayed plan that equals the saved plan.

  It never reopens the original. New planning and resume still read the authored
  path, so a changed source is detected. The route provides the shared
  `retainedInputs` hook from that authenticated replay.
- **Native document.** The import is a `Part::Feature` holding the file-frame
  solid, with an editable `Placement` (placement × orientation) and a
  `SourceSHA256` property. The optional `Part::Refine` takes it as `Source` and
  keeps identity placement. The FCStd carries a minimal visibility record (output
  visible) so the FreeCAD GUI does not open every object hidden; it is verified
  strictly.
- **Facts.** Facts are measured on the exact B-rep. Each point needs its exact
  distance to the solid's boundary faces to be at least the declared guard before
  the inside test. A non-finite distance, an exception or a near-surface point
  refuses.
- **Export hardening (every new run).** Build and fresh reopen record exact
  native volume, area, curved-face area, bounds, centre and face count. The host
  integrates the binary STL in float64 about a local origin, checking signed
  volume, directed-edge closure, centre and bounds. Native `Mesh.Volume` is not
  used.

  The budget is: curved area × meshing deflection + area × √3·Rmax·2⁻²⁴ + float64
  roundoff, with the centre allowance derived from the same layer. This is a
  conditional estimate under OCCT's meshing contract. The established 0.5 % /
  1e-5 mm³ acceptance remains a ceiling on the host volume. Uninformative,
  negative or non-finite budgets are refused.

  The exported STEP must declare one millimetre solid under the same reference
  walk. Results report `exportChecks` with allowances and per-axis mirror
  discriminability.
- **Legacy evidence.** Runs without the new evidence fail with `RERUN_REQUIRED`;
  there is never an automatic downgrade. Old acceptance records remain historical
  and are not relabelled.

## Native qualification (FreeCAD 1.1.4, OCCT 7.8.1)

`tools/qualify_freecad_step_import.py` passed 14 check groups in 65 s, with the
same FreeCAD source digest at start and end (`sha256:3eaf3f6f…`). Its STEP inputs
are written without a CAD kernel, with exact closed-form facts:
- a 40×30×10 mm block with an asymmetric notch and square hole (10840 mm³);
- a revision of it (10520 mm³);
- void, split-face and two-solid variants;
- a box with a radius-3 cylindrical through-hole.

| Group | Result |
| --- | --- |
| Baseline | Native volume and placed centre equal the oracle to 1e-9. STL host error 0 (allowance 0.048 mm³); x and y mirrors are detectable by the centre, z is not (symmetric in z). |
| Revision | The revised file under the baseline facts fails `EXPECTATION_FAILED` at `part.options.expect.volume`; with updated facts it verifies. |
| Units | inch, cm and m files each give 10840 mm³. Mm numbers labelled inch fail `UNIT_MISMATCH` at planning with 0 native launches. |
| Orientation | A Y-up file with `z: +Y` verifies. Unmapped, it fails on the centre of mass. A missing `x` fails `INVALID_AXIS` with 0 launches. |
| Wrong identity | Mirror and 180° files (same volume, area and bounds) fail on the centre and on points. Volume-only facts are refused at planning. A point 0.2 mm from a face fails the 0.5 mm guard. |
| Topology | The void (same volume and bounds) fails on the centre. The open shell fails `INVALID_GEOMETRY` natively. Two solids are refused at planning. |
| Refine | 7 faces become 6, with volume unchanged. A headless edit of the source placement moved the refined output, survived save and fresh reopen, and refine kept identity placement. |
| Curved (independent writer) | Native volume and centre equal π-based closed forms (error 0 and 8e-17); native curved area equals 2πRH. STL host volume error 0.117 mm³ at deflections 0.05, 0.01 and 1.0 (allowances 9.4, 0.95 and 94 mm³; the 58.6 mm³ ceiling governs at 1.0). |
| Far placement | At (99950, 99950, 99950) native `Mesh.Volume` reported 570425344; the host integral erred 0.143 mm³ within a 50 mm³ allowance. |
| Relationship | The plain `SHAPE_REPRESENTATION_RELATIONSHIP` fixture verified natively. |
| Admission | Orphan unit context, missing length unit, transformation, a 2002-edge loop and 100001 padding entities were each refused with 0 native launches; a strings/comments trap was admitted as mm. |
| Refreshed-hash mutants | 12 mutants with refreshed digests were refused with `VERIFICATION_FAILED`: inverted, mirrored, turned and dropped-facet STL; metre-relabelled STEP; forged centre, curved area and placement; refreshed retained source; FCStd digest, refine link and GUI record. Three no-downgrade mutants (evidence removed from the build, removed from the receipt, or given an old version) gave `RERUN_REQUIRED`. A symmetric block's mirrored STL is accepted, as its stated limit, and reported as not detectable. |
| Source lifecycle | After the source was deleted, the run and a schema-aware exported copy both verify, and `retainedInputs` is unchanged; new planning reports `RESOURCE_NOT_FOUND`. A relative path planned in one directory verifies from another. Legacy `readSTEP` verifies without its original. |
| Workflow | Unchanged resume reuses the job; a changed source reruns it. Forged scheduler input hashes fail workflow verification. |
| Timeout | A 0.5 s whole-run budget gives `RUNNER_TIMED_OUT` with a failed result. |

**Actual GUI** (`tools/qualify_freecad_step_import_gui.py`, private Xvfb display
and settings, one GUI process and copies only): 15 of 15 checks passed.
- At first open only the refine output is visible and it renders. It is linked to
  the source with identity placement.
- An edit of the source placement through the document property moved the
  refined output.
- Saving, reopening in the GUI and a separate fresh command-line reopen all kept
  the placement and refine linkage.
- Screenshots are retained with the evidence.
- No human pointer interaction or camera contract is claimed.

## Checks run

- **Host.**
  - 105 FreeCAD host tests, including the new `test_freecad_step_import.py`:
    scanner traps and bounds, located planning faults, retained-source lifecycle,
    capture and cancellation, export error model and no-downgrade.
  - The exact 17-example old-plan comparison.
  - Guidance: 401 reviewed, none pending or stale.
- **Mutation checks.** A lenient hardened-evidence check, a removed
  orphan-context refusal, and removal of both capture-digest layers each make the
  host tests fail.
- **Native regressions on the frozen source** (results in the completion report):
  the PartDesign, parameter, measurement, selection, design-study and
  sourced-assembly qualifiers.
- **Known shared-test conflict.** `tests/unit/test_schemaxis_freecad.py` builds a
  pre-hardening receipt and still expects `verified`. Under the no-downgrade rule
  it now receives `RERUN_REQUIRED`. That root-owned test needs updating.
- **Pending root regeneration.** Packaged Studio search/Help, generated
  references and readiness freshness still need regenerating for the new
  operation. Host discovery already finds `importSTEP` for "supplier STEP part",
  "vendor part" and "refine faces".

## Follow-up: archive boundary and discovery (host-only)

**Archive boundary.** Root reproduced a corrupt archive bug with a refreshed
digest and regenerated metadata. When `model.FCStd` was an invalid ZIP or held a
malformed `Document.xml`, saved verification raised bare `BadZipFile` or
`ParseError`.

The FCStd readers now map one explicit tuple of archive and XML decoding errors
to `VERIFICATION_FAILED` at `model.FCStd`. This covers the saved-provenance check,
the parameter reader and the PartDesign reader. The tuple is ZIP, large-ZIP,
zlib, EOF and XML parse errors; programmer errors are not included.

New host tests:
- A valid control verifies, before and after the cases below.
- An invalid or truncated ZIP, malformed XML, a missing, duplicate, oversized or
  DOCTYPE/entity `Document.xml`, and a corrupt compressed member each give the
  located fault.
- A historical run still gets `RERUN_REQUIRED` first.
- A programmer error still propagates.

Removing the mapping reproduces the four bare decoder errors.

**Discovery.** The application purpose and keywords, and the `importSTEP`
keywords, now name the supported checked supplier/vendor STEP import ("supplier
STEP part", "vendor part"). The production Studio search acceptance test passes
193 of 193 without changing assertions or phrase matching.

No numerical budget, geometry check, source capture or expectation changed. No
native process was run for this follow-up.

**Archive edge follow-up (host-only).** The bounded member reader is shared by
`Document.xml` and `GuiDocument.xml`, and checks each member before decoding:
- the member must occur exactly once and within its size bound;
- the encrypted, patched-data, strong-encryption and masked-header flags are
  refused, as is any compression other than stored or deflate;
- the local header must agree with the central directory;
- only that member read maps the library's own `RuntimeError` and
  `NotImplementedError`.

A stdlib expat pre-parse refuses any DOCTYPE or entity declaration in every
accepted encoding (UTF-8, UTF-16 with either byte order) and refuses unknown
declared encodings. Nothing is expanded.

FreeCAD-written FCStd files (stored or deflated, flags 0) still read; 587
retained files were checked. Root's encryption, method-99, strong-encryption and
UTF-16 entity probes now each give `VERIFICATION_FAILED` at `model.FCStd`.
Programmer errors and `RERUN_REQUIRED` are unchanged. No native process was
started.

## Limits

- The declared facts check exactly those facts. Symmetric parts and poor points
  can hide a mirror, turn or different part. OCCT silently repairs file face
  orientation, so readback cannot reveal it. Same-kernel readback (FCStd reopen,
  STEP re-read, `isInside`) is self-consistency only.
- The export budget is a conditional engineering estimate; it is not rigorous for
  arbitrary topology.
- Only planar and cylindrical inputs were checked against independent writers;
  B-spline and other surfaces are native-observed only.
- Read time is bounded by the entity and loop limits for the measured driver only.
  The whole-run deadline with process-tree termination remains authoritative.
- Imported solids have no recovered sketches, parameters or history. Names,
  colours and product structure are not imported.
- Only FreeCAD 1.1.4 on Linux is qualified; locale variations are untested.
- No native Gmsh or other consumer was run. The Gmsh handoff example is checked
  by host planning only.
