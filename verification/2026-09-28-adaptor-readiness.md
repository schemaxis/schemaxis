# Adaptor structural readiness — 2026-09-28

Implemented a host-only `schemaxis readiness` audit and opt-in `--check` admission
gate over the existing installed registry. The report covers 10 adaptors and 12
routes, including both non-node routes. Stable checks carry sources, recovery
instructions and independent structural, entry-point, availability and qualification
states. Historical provider receipts remain separate from current qualification.

Delivery bundles now cover Octave, FFmpeg, FreeCAD solids and FreeCAD assemblies.
Octave and FFmpeg also publish curated operation purpose/semantics through the
existing progressive catalogue. Octave, FFmpeg and assemblies pass structural
admission; FreeCAD solids retain an operation-context gap. The
[dated matrix](../docs/design/adaptor-framework/AUDIT.md) records every route and
ranked gap. See the [contract and migration guide](../docs/adaptor-readiness.md).

## Newly run verification

- Full unit suite: **730 tests, 22 skipped, no failures/errors**, 169.960 seconds.
  Log: `evidence/adaptor-readiness/unit-tests.log`.
- Final focused readiness suite after MPI-mode and entry-point reporting refinements:
  **15 tests, no skips/failures/errors**, 2.111 seconds. Includes absent/malformed
  bundles, invalid examples, exact fault matching, contradictory profiles, missing
  contracts, broken links, unknown operations, wheel/source-root behaviour, public
  CLI gates, and per-provider failure isolation.
- Installed readiness audit blocks native imports, process launches and network
  connections in its conformance subprocess, recording attempted calls even when
  an adaptor catches the exception. All 12 routes report without such attempts.
- Progressive discovery tests: **19 passed**. Adaptor architecture/extension tests:
  **3 passed**, including discovery/routing/readiness of the independent fixture
  adaptor without changing shared routing.
- Capability protocol conformance: **2 passed**, 57.423 seconds. All registered
  operation declarations, bindings and option schemas remain reachable intact.
- Generated references: **46 checked**, no drift. Public discovery succeeds.
- CLI `readiness --app octave --app ffmpeg --check`: exit 0. FreeCAD gate: expected
  exit 1 with `ADAPTOR_NOT_READY` and the complete diagnostic report; its assembly
  route is complete while its solid route lacks some operation purposes.
- All **67 local links** in the touched guides/handoff/audit/receipt resolve. The matrix
  counts match the final machine report; `git diff --check` passes.

The first full-suite attempt exposed two old test assumptions: exactly two curated
domains and file references without heading anchors. The new media domain and
heading-aware reference check are now covered; the subsequent full suite passed.

## Scope limits

No new native acceptance was run and no absorbed upstream versions changed. Native
behaviour is unchanged. Linked native recipes and old receipts are delivery
materials, not fresh qualification. Structural passes do not establish semantic
sufficiency, schema/planner equivalence, lifecycle behaviour or complete data-trait
preservation. Runtime availability and current route/profile qualification remain
unknown. FFmpeg's editable planner example needs a real PNG path before execution.

The next work is the remaining context/delivery backlog, behavioural conformance,
scaffolding and complete agent/human acceptance. The other workspace's README
addition and candidate document were preserved and excluded from this commit.
