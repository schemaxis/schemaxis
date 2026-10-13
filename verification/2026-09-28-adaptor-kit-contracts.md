# Adaptor development contracts and conformance

Milestone 1 establishes route-specific delivery materials, bounded public agent/CLI
context, an explicit optional-feature decision matrix, independent acceptance
recipes and reusable host/native conformance. FreeCAD's complete operation surface
now has curated purpose/semantic guidance. Numerical, solid, non-node assembly and
video routes have development contracts; this does not qualify every operation.

New checks:

- Full unit suite: 742 tests, 22 skipped, no failures/errors (170.327 seconds).
- Kit tests: 11 passed. Readiness tests: 15 passed.
- Host conformance passes on Octave, FreeCAD solids, FreeCAD assemblies and FFmpeg:
  schema/parser fixtures, exact invalid faults, deterministic plans, typed defaults
  and distinct baseline/variant effective inputs.
- Exploratory native conformance passes on Octave 11.3.0 and the configured FreeCAD
  1.1.3 build for analytic derivative, box-volume and fixed-assembly cases. Each
  exercised two inputs, independent expectations, publication and authored/plan
  tampering, missing-file detection, timeout and pre-launch cancellation.
- The first FreeCAD native run exposed unstructured missing-publication errors.
  Both CAD verifiers now preserve structured errors and translate malformed/missing
  saved evidence into VERIFICATION_FAILED. The repaired native runs passed.

Bulk logs and exploratory receipts: `evidence/adaptor-kit/`. They are not registered
as current-source qualification; final kit acceptance will be rerun after the
remaining framework changes. No MPI, general live-editing or exhaustive native
qualification is inferred. Runtime dependency requirements are unchanged;
`jsonschema` is optional developer tooling required for explicit conformance.

Next milestone: generated source overlays and their isolated extension proof,
followed by public-protocol/human reuse acceptance and final scoped receipts.
