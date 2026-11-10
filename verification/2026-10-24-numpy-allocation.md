# NumPy keyless handoff strengthening — 24 October 2026

Scope: `schemaxis.numpy/1`, `principalComponents`. One host-side boundary
repair; no new native mapping, option or format.

## Issue

A keyless run publishes its key column as `row` (integers 1..n) in
`reconstruction.csv`, but `row` was reserved for every column name. A second
NumPy run therefore had no valid declaration for that table: a keyless
consumer failed with `PCA_HEADER_MISMATCH` (no ignored columns) and a row key
named `row` failed with `PCA_INVALID_CONTRACT`. The documented
reconstruction-to-reanalysis handoff only worked for keyed sources.

## Change

A `rowKey` may now be named `row`. Channels still cannot be named `row`, and
`component`, `channelIndex` and `PC<n>` stay reserved everywhere, so published
column labels remain unambiguous. Only `adaptor.py` planning changed; the
native worker and oracle never used the reserved-name rule. `docs/numpy.md` and
the `rowKey.name` guidance explain the handoff and its limits (`scores.csv`
stays unconsumable because `PC<n>` is reserved).

## Evidence

- Before: `tests/unit/test_numpy_allocation.py`, 2 of 5 failing (plan of a
  `row` row key refused; collision case located at the wrong column).
- After: `tests.unit.test_numpy_allocation` and `tests.unit.test_numpy`,
  30 tests, all passing. New tests cover the published `row` header, parsing of
  a keyless reconstruction with a `row` key, independent host verification of
  the re-analysis, the unchanged `PCA_HEADER_MISMATCH` without it, and the
  remaining reserved and duplicate names.
- Guidance audit: 25 reviewed, 0 pending, 0 stale.
- Upstream: the latest stable release observed from the official GitHub
  release feed is NumPy 2.5.4, the absorbed version. `absorbedVersion` is
  unchanged.

## Limits

- **Native: unqualified for this change.** No NumPy runtime was available in
  this environment, so no native run was made. The qualified identity remains
  NumPy 2.5.4 / OpenBLAS 0.3.34 from the earlier receipt.
- **Stale implementation fingerprint.** Editing `adaptor.py` changes the
  implementation fingerprint, so runs saved by the previous implementation are
  refused by design (rerun them), and the source-bound qualification receipt
  needs native requalification and registration.
- The keyless handoff is host-verified only. No new example was added; the
  Calc and Gnuplot handoff limits are unchanged.
