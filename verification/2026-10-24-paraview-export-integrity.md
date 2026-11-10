# ParaView export integrity — 2026-10-24

Changed scope: verified-export value checks (`writers.py`), a new host module
`export_integrity.py` and its call from `job.verify_receipt`. Nothing else in the adaptor
changed. This note covers only that scope and is not a native qualification: the route's
`qualification.json` source digest is now stale and was not regenerated.

## What was found

A native baseline (ParaView 5.13.3, serial `pvbatch`, `OMP_NUM_THREADS=2`) exporting a
three-row table with a `nan` cell to CSV wrote the file and failed with
`VERIFICATION_FAILED: CSV cell differs from input` (row 1, column pressure), without
naming a nonfinite value. By code reading (the pre-change behaviour was not probed natively), receipt verification checked digests only and would not have detected an
unlisted file added to an export directory, an absent or `NaN`-bearing evidence record, a
changed comparison label, or an emptied member list. A missing export file would have escaped as an
unstructured file error.

## Observed after the change

New runs (fresh directories, tiny synthetic data, no CFD data), all through the registry's
`plan`/`run`/`verify` commands:

| Case | Result |
| --- | --- |
| Sphere + `pvCalculator` array → CSV (`paraview-export-integrity.json`) | run succeeded; `verify` verified, 1 artifact |
| Three-row finite CSV table → CSV | run and `verify` succeeded |
| Table with `nan` → CSV (`…-nonfinite.json`) | failed `NONFINITE_DATA`: array `pressure`, `Row Data`, tuple 1, component 0 |
| `paraview-writers.json` (XML polydata exact, XML parallel, STL geometry) | run and `verify` succeeded, 3 artifacts: no regression for exact/geometry paths |
| Nine tamper probes on the retained CSV and writers runs (`scripts/tamper.py`) | each refused with the codes in `docs/paraview-export-integrity.md` |

The first end-to-end verify after the new check wrongly refused every run because the
publication layer adds `<member>.metadata.json` after the native run; only that exact
sidecar name is now accepted, with a regression test.

Tamper probe limit: for the writers run, “comparison replaced with exact” was a no-op on
its first (exact) artifact and was not refused, correctly. It was refused for the CSV run.

## Host checks

`test_paraview_export_integrity.py`: 23 tests passed (finite values, readback faults,
CSV faults, every evidence-shape rule, member/sidecar/symlink/path cases and the shared
`verify_receipt` entry point). All `test_paraview_*.py` (238 tests with the new file; 6
pre-existing skips), `test_schemaxis_publication.py`, and writer/boundary/integration
globbed suites passed. The full host suite and the release gate were not run.
`readiness --app paraview --admission --check` still fails on `context.operations`,
`completion.review` and `discovery.*` unknowns; these are unchanged by this work and no
completion record or guidance was added.

## Not claimed

Nonfinite checks for `semantic`, `geometry` and `pixels` and the evidence-shape rules for
those comparisons are host-tested with stand-ins and the natively exercised writers run
(exact and geometry) only; no native semantic or pixel export was run here. No MPI.
Older receipts keep their shape; no historical receipt was re-verified. Scientific
accuracy of exported values is still established only by the recorded native comparison.

## Supervisor integration

Added this scoped completion record to readiness metadata and linked the integrity
guide from workflow references and the user guide. This does not resolve the broader
pre-existing catalogue discovery/guidance admission gaps. An extra host regression
rejects unlisted special files (for example a FIFO) without reading them.

A supervisor check reverified the three retained serial runs with the integrated
source and independently checked 50 CSV rows against `doubled = 2*Points.x + 1`
(maximum difference about 1e-11, below the declared 1e-6). A fresh run produced by
the unchanged pre-batch source 4667d94 published XML, multipart parallel XML, STL
and CSV; the strengthened verifier accepted all four artifacts. This establishes
that bounded baseline-source compatibility, not all historical receipt versions.
