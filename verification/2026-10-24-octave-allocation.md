# Octave planning-time numerical contract, 24 October 2026

Scope: the `schemaxis.octave/1` route's `plan()` boundary. No new operation,
option, native mapping or format; the absorbed version (11.3.0) is unchanged.

**Defect.** Planning accepted literal documents that the numerical contract
forbids (for example `fft` on x=[0,1,2,4], `derivative` on repeated x, a smoothing
window longer than the data, `linearFit` on constant x, or more than 100000
intermediate samples). `schemaxis plan` succeeded; `run` then created the output
directory and failed, and the fault had no node location or recovery.

**Repair.** `plan()` evaluates, with the existing independent host reference, each
node that does not depend on a `readCSV` file; planning still reads no files and
starts no process. The same faults now carry the node id and recovery text at run
time for CSV-dependent nodes. A Studio fixture (`add-fft`) gained a valid
eight-sample base document, since the former five-sample base is no longer a
valid FFT input. Verification, tolerances and published receipts are unchanged.

Host tests (`tests/unit/test_octave_allocation.py`): seven checks covering
each violation with location and recovery, budget, run refusing before creating
output, published examples still planning, no file reads, literal branches
checked beside a CSV branch, and a structured runtime fault for CSV-dependent
nodes. Eleven subtests failed before the repair; all pass after. With the
existing numeric-analysis tests, the other suites that mention Octave and the
completion and capability suites, 265
tests pass (10 native skips without a configured runtime).

| Completion item | Result |
| --- | --- |
| registration, schema, native-mapping | Unchanged. |
| semantics, execution | Data-dependent numerical constraints enforced at planning for literal tables; run-time check retained for CSV-dependent nodes. |
| discovery, guidance | Requirement text and readiness constraints/recovery updated; no new field. |
| help, examples | New `docs/octave.md`; published examples still plan. Shared Help/reference regeneration is the integrator's. |
| tests | Seven new host tests above. |
| qualification | A separate serial check with a retained Octave 11.3.0 passed the existing signal/regression/calibration tamper test and a CLI run/verify of the signal example. This is not a new source-bound qualification receipt; the existing receipt predates this source change and is stale until requalified. |
| maintenance | The official download page still lists 11.3.0 as the latest stable release. |
