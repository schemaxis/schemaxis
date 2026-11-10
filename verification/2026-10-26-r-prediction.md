# R new-row prediction intervals completion review — 2026-10-26

## Changed scope

`schemaxis.r/1` `linearRegression` gains one optional `prediction` request for
declared **new, predictor-only** rows: `interval` (`confidence` for the fitted mean
or `individual` for one future observation, required, no default), `level`
(0.5–0.999, default 0.95) and `newdata` (1–64 rows of predictors in declared order
and units). It is a product hypothesis for calibration reports, not demonstrated
customer demand, and makes no model-selection, causal, clinical,
calibration-certificate or future-generalisation claim.

- Native: public `stats::predict.lm` on the genuine fitted `lm` and on `model.rds`
  reopened in a fresh R process, called with `interval = "confidence"` and
  `"prediction"` and `se.fit = TRUE`. Both types are always native-verified;
  `interval` selects what is published.
- Independent host meaning (not native `predict`): the existing column-scaled
  Householder QR and Student-t beta/bisection. `h = |R^-T x_scaled|²`,
  mean `fit ± t·sigma·sqrt(h)`, individual `fit ± t·sigma·sqrt(1+h)`.
- Publications: `prediction.csv` is appended after `inference.csv` (or the summary),
  columns `sample,x1..xN,prediction,lower,upper,halfWidth`; the summary gains a
  `prediction` block (input row identity, units, leverage, `outsideTrainingRange`,
  df, sigma with units, assumptions, limits). Legacy artifact indices and the
  five-argument native command are unchanged when `prediction` is absent.
- Guards before native: finite/budget, scaled-design overflow, existing
  conditioning guard, the existing residual-variance guard (`NO_RESIDUAL_VARIANCE`
  at `$.prediction`), projected overflow of prediction and interval, a leverage
  budget of 1e4 (arithmetic conditioning only) and a **per-row resolution guard**
  (`UNSUPPORTED_PREDICTION` at `$.prediction.newdata[i]`). A swap of interval types
  is undetectable when the independent half-width gap is within the comparison
  allowance `tol*(1+sum|x_scaled|)` plus the relative component, which the global
  1e4 cap ignored (review finding: 8 predictors, 512 rows, level 0.5, h near 1e4,
  sigma just above the variance floor). A row is now supported only if
  `halfIndividual - halfConfidence > 4*(allowance + 1e-5*halfIndividual)`; any
  bound or half width inside `allowance + 1e-5*halfIndividual` is accepted by the
  comparison, so the factor 4 is a margin over the proven necessary gap. This is a
  verification-resolution limit, not a model-validity test; no precision or
  confidence claim is made for a refused row, whose interval type cannot be
  verified. No existing numeric, variance or conditioning guard was loosened and no
  unit-free epsilon was added.
- Tolerances: fit within the response-roundoff allowance scaled by the new point's
  design magnitude (no unit-free floor); `se.fit`, sigma and half widths and bounds
  at 1e-5 relative (the variance guard bounds roundoff below 1e-6·sigma); critical
  value 1e-10 relative; `df`, `level` and sample order exact.

## Checklist

| ID | Result |
| --- | --- |
| registration | `adaptor.json` keywords/execution text only; version and route unchanged, `absorbedVersion` stays 4.6.1. |
| schema | `prediction` object in the declared options and authored schema; generated reference refreshed (`docs/generated/r*.json`, plus the shared aggregate schemas that embed it). Bad level, type, empty/oversized/extra/wrong-width/response rows are rejected (`tests/unit/test_r_prediction.py`). |
| semantics | Pre-native faults with exact codes and locations (`NO_RESIDUAL_VARIANCE`, `INVALID_TABLE`, `UNSUPPORTED_PREDICTION`, `MISSING_VALUE`, `UNSUPPORTED_VALUE_TYPE`, `RANK_DEFICIENT_DATA`, `ILL_CONDITIONED_DATA`) tested. |
| native-mapping | `predict.lm`, `se.fit`, `residual.scale`, `df` mapped and read back; new input `prediction-input.csv` is in the launcher input bindings; legacy command unchanged. |
| execution | Fresh-process RDS readback; hash-refreshed mutants of every ordinary mutable sidecar, native table, published table, summary and plan are rejected with intended messages; unrefreshed byte changes are separate integrity controls (`tools/qualify_r_prediction.py`). Timeout and cancellation: prelaunch and after-stage controls are kept and labelled as such; live timeout and cancellation use a qualifier-owned SIGSTOP race hold after the genuine reopen-stage R engine is observed. The stopped state is confirmed before triggering the runner, and termination must be SIGTERM or SIGKILL (PID/PGID, six-argument command, failed result, logs, process group gone and absence of success publication asserted; the hold does not establish a position inside predict.lm). |
| discovery | Operation keywords/semantics extended; search cases `prediction interval`, `future observation` (positive) and `conformal prediction sets` (negative) pass. |
| guidance | `guidance.json`: the six new addresses are reviewed explanations with sources, units, default meaning and pitfalls (AI-authored; human editorial/domain review is still required). |
| help | `docs/r.md` section "Prediction intervals". Generated Help could not be regenerated here: `tools/generate_studio_help.py` stops on the read-only Gnuplot dependency's missing `xarray.md#gnuplot-handoff`, which this allocation does not own. Help regeneration is left to the integrating step. |
| examples | `r-prediction.json`, `r-prediction-variant.json`, invalid `r-prediction-exact-invalid.json` and `r-prediction-response-invalid.json`, and the workflow `r-prediction-to-gnuplot.json`; Studio snippet `enable-prediction` and template `calibration-prediction`. |
| tests | `tests/unit/test_r_prediction.py` (host, plus native cases when `SCHEMAXIS_R` names Rscript). |
| qualification | See "Native evidence" below; the stored `qualification.json` receipt was **not** edited and is stale for the new source digest. |
| maintenance | `upstream.json` scope, evidence and acceptance recipe updated; `absorbedVersion` unchanged. |

## Native evidence

The earlier 2026-10-26 review (`69-and-root-review-r1`) recomputed 17 native
prediction directories independently (largest error 2.5e-10 of the half width) and
found two P2 and two P3 items. This repair changes `reference.py` (resolution
guard), the summary tolerance block, guidance/readiness/docs text,
`tests/unit/test_r_prediction.py` and `tools/qualify_r_prediction.py`. The complete
native pass after the final source freeze, with its raw commands, PIDs, source
hashes and BEFORE/AFTER manifests of all owned, generated and read-only files, is
under the allocation's `69-repair-evidence` directory (`FINAL.md`, `final-*`
directories and logs); the earlier `69-evidence` pass and the immutable review
source are retained unchanged and are not relabelled. Runtimes: privately built R
4.6.1 (source checksum local only, no independent publisher checksum, MD5 URL 404
retained), Gnuplot 6.0.5 private build (state passed), LibreOffice/Calc 26.8.1.1
private build.

- `tools/qualify_r_prediction.py`: closed-form two-df intervals; both interval types
  native-compared; changed level/type/newdata/response scale; predictor scale
  1e-6/1e6, translation and response offset; exact-rational leverage; a true
  eight-predictor case against an independent literal oracle (orthogonal Hadamard
  design, h=(1+sum x²)/16, df 7, literal t, exact rational leverage); the
  resolution-guard counterexample refused before any R process and a same-leverage
  case with more scatter accepted and natively verified; inference/held-out indices
  preserved; hash-refreshed mutants (all ordinary mutable bindings, receipts,
  sidecars and publication metadata refreshed and metadata verification passing
  before the attack is asserted) rejected with exact messages and locations;
  `wrongZeroFit` is a genuine zero while the former +1e-3 shift is now named
  `shiftedFit1e-3`; integrity controls kept separate; prelaunch-timeout and
  after-stage-cancellation controls kept; live reopen-stage timeout and cancellation.
- `tools/qualify_r.py`: legacy qualification including R→Calc handoff, reuse and
  unmet-requirement gates on R 4.6.1 and Calc 26.8.1.1.
- `tools/qualify_r_prediction_gnuplot.py`: unchanged workflow qualifier; the
  Gnuplot adaptor's own SVG/PNG verification and an affine recomputation of the
  error endpoints; no separate R-side pixel decoder; 45-character legend label.
- `schemaxis adaptor conform --native` for the R readiness cases. The stored
  `src/schemaxis/adaptors/r/qualification.json` (2026-10-17) was not edited,
  registered or counted.

These are named-case evidence only, not exhaustive coverage. Generated Help cannot
be refreshed in this tree: the read-only Gnuplot dependency doc links to a missing
`xarray.md#gnuplot-handoff`, so `tools/generate_studio_help.py --check` fails here
independent of R. The R topic and `index.json` were regenerated in a scratch copy
whose only difference was that one link neutralised as plain text. Packaged Help is
therefore not claimed current as a whole and must be regenerated after the union.

## Limits

Only unweighted additive full-rank OLS; no formulas, packages, weights, GLM,
interactions or model import. Intervals assume fixed, error-free predictors, a
correct additive mean and independent homoscedastic normal errors; the level is
nominal, not a coverage guarantee. Extrapolation is reported, never validated or
excluded, and new rows are not held-out validation. With eight predictors
`prediction.csv` has 13 columns, more than Gnuplot's 12-column budget (the consumer
refuses it).

The resolution guard also refuses some legitimate rows whose interval type is
simply not verifiable (large offsets with small scatter, uncentred predictors, a far
row with many predictors). Such a row publishes nothing rather than an interval of
unverified type, and the guard says nothing about whether the model is valid. Native
cancellation and timeout were qualified with a live R engine in the reopen stage; the
position inside `predict.lm` was not instrumented and is not claimed. The 13-column
eight-predictor table cannot feed the Gnuplot adaptor (12-column consumer limit) and
that limit is an accepted disclosure.
