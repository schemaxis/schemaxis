# R bounded regression acceptance — 2026-10-10

The new `schemaxis.r/1` adaptor fits declared numeric additive ordinary
least-squares models with 1–8 named predictors, optional intercept and separate
held-out observations. Native `stats::lm` results are checked against independent
RMS-scaled Householder QR coefficients, predictions and residuals. A numerical
rank guard and actual rectangular scaled-design infinity condition reject
unsupported designs. Named RMSE, maximum-absolute-error and signed selected
prediction requirements retain measured values, margins, sampled conditions and
next actions. Invalid intent, native/verification faults and valid unmet fits have
distinct faults; unmet fits retain evidence and block downstream success/reuse.

## Exact runtime and provenance

Observed **R version 4.6.1 (2026-06-24)** at
`evidence/adaptor-growth-20261010/runtimes/r-4.6.1-build/install/bin/Rscript`,
built privately from the official
[CRAN source](https://cran.r-project.org/src/base/R-4/R-4.6.1.tar.xz).
The source SHA256 is
`e4149581e151f3f1bc5edd6475e24ca1e2f452c08b6a22c29b570ce8abfe5783`.
The [official release page](https://www.r-project.org/) identifies 4.6.1 as the
current stable release on this date. Private build/dependency hashes and logs are
retained in `evidence/adaptor-growth-20261010/runtimes/r-4.6.1-build/provenance.json`.
No detached R-source signature was verified. Only base, stats and utils are used;
`--vanilla` prevents user startup/profile data. No system installation or PATH change.

Calc handoffs used the observed **LibreOffice 26.8.1.1** private executable
`evidence/adaptor-growth-20261010/runtimes/libreoffice-26.8.1/runtime/opt/libreoffice26.8/program/soffice`.

## Checks on frozen source

Both primary receipts bind source digest
`sha256:db268bc3fc369c42244b78118d3ea3a966323e57c4f5b2bd84fe8daa5f9c82f6`.

- `evidence/adaptor-growth-20261010/r-native-final/qualification.json`: native
  adaptor kit passes four independently known baseline/variant, no-intercept and
  eight-predictor cases, host admission and timeout/cancellation/corruption probes.
- `evidence/adaptor-growth-20261010/r-domain-1/qualification.json`: seven accepted
  scenarios include known calibration, changed slope, no intercept, eight
  predictors, predictor scaling, response scaling to 1e-100 and a two-visit finite
  requirement study. Three intentional misses (tight training error, changed
  held-out response and prediction lower bound) fail with
  `FIT_REQUIREMENT_NOT_MET`, including replay. Changed RDS or forged acceptance
  remains rejected after ordinary publication/evidence hashes are refreshed.
  Accepted held-out-table/Calc handoff preserves numeric bytes and reuses both
  jobs. Two fresh unmet producer attempts produce zero consumer attempts.
- `evidence/2026-10-10-independent-review/second-tranche/r-scaled-final-native-review.json`:
  independent six-model native review on the same frozen digest passes 1/3/8
  predictors with/without intercept and predictor scales 1e-8 to 1e8.
- `evidence/2026-10-10-independent-review/r-peer-review/`: 103 malformed retained
  evidence probes produce structured faults, with zero raw exceptions or accepted
  corruptions. An independent native signed two-predictor, no-intercept model
  reproduces coefficients 2/-3 and held-out predictions -16/-3; a tighter negative
  lower bound is correctly unmet. Source stayed unchanged through this review.
- All 15 dedicated host tests pass. All 33 schema fields and the operation have
  reference guidance, with zero pending/stale entries; selected-route host
  conformance passes. Public analytic-study query discovers the operation.

Fresh native reopen consumes the captured RDS; generated native-stage launchers
bind actual consumed worker/CSV/RDS bytes. Retained reads reject symlinks, FIFOs,
devices, oversized files and descriptor replacement using bounded nonblocking
regular-file reads. Total fit/reopen/verification deadline and cancellation remain
owned. This is ordinary evidence integrity, not protection against coordinated
forgery of every execution record.

Native comparison uses relative tolerance 1e-10 and the recorded response-scale
absolute allowance `128 * ulp(max(abs(training_response))) * max(1, scaled_condition)`.
Performance acceptance does not relax authored bounds, but does not certify
accuracy below that verification floor. Unit strings retain meaning without
conversion. Finite supplied observations do not prove statistical inference,
causality, reliable extrapolation, future generalisation or a continuous-domain
error envelope. RDS remains native evidence; only numeric tables and a labelled
summary are published.

## Named workbook requirements follow-up

The R-to-Calc workflow now independently requires residual minimum ≥ -0.21 V,
residual maximum ≤ 0.21 V and observed total minus prediction total minus residual
total to reconcile within 1e-10 V in both XLSX and reopened ODS. These units come
from the regression's declared response and summary; plain CSV labels do not
perform unit conversion.

Fresh `evidence/adaptor-growth-20261010/r-calc-requirements-domain-final/qualification.json`
passes the full seven-accepted/three-unmet R domain checks and all handoff gates
using the exact runtimes above. The recipe independently reads both workbook
formats' native caches: observed sum 25.9, prediction sum 26, residual sum -0.1,
residual minimum -0.2 and maximum 0.1, within 1e-12 relative/absolute comparison.
All three named checks pass independently in both formats; both jobs reuse.
Tightening only the workbook lower bound to -0.1 raises `REQUIREMENTS_UNMET`,
while the R producer stays verified. Retry reuses that producer and creates a
second fresh failed consumer attempt; both formats identify only the residual
lower-bound miss. Failed workbooks retain observations but no successful
publication receipt.

The report records current R/Calc source digests and exact recipe/workflow hashes.
The R adaptor remains frozen at the digest above; its native kit receipt remains
source-current. This follow-up changes only the example, recipe and explanatory
documents, not the fit implementation, authored schema or guidance.
