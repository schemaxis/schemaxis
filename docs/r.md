# R: measured numeric linear regression

The `schemaxis.r/1` route fits a small, additive, unweighted ordinary least-squares
model with R's public `stats::lm` API. Use it for numeric calibration or a bounded
regression study where declared training and separate held-out observations have
known meaning. Optional [coefficient inference](#coefficient-inference) adds
classical standard errors, t tests and confidence intervals under stated error
assumptions, and optional [prediction intervals](#prediction-intervals) report the
uncertainty of the fitted mean or of one future observation at declared new
predictor rows. It does not assess causal effects, validate a model or establish
future generalisation. No authored R scripts, formulas, native functions, external
packages or imported models are accepted.

[Start with the calibration example](../examples/schemaxis/r-regression.json).
It fits an independently known intercept of 10 V and slope of 2 V/degC. Four
training residuals are orthogonal to the intercept and predictor: their sum and
predictor-weighted sum are zero. The training RMSE is `sqrt(0.025)` V. Two
held-out observations have errors 0.1 and -0.2 V. The
[variant](../examples/schemaxis/r-regression-variant.json) changes the known slope
to 3 while preserving the same residual/error budgets.

## Authored model

Declare `operation: "linearRegression"`, 1–8 `predictors`, a `response`, and
4–512 `training` rows. Each predictor/response has a distinct lowercase `name`
and plain `unit` label; `intercept` is reserved as a coefficient label. Unit labels
preserve interpretation, but do not convert units or validate calibration.
Rows contain predictors in declared order followed by the observed response.
Every cell must be a finite JSON number within ±1e9. Missing and non-numeric
cells are rejected before native launch and are never dropped, imputed or coerced:

| Cell | Fault | Recovery |
| --- | --- | --- |
| `null`, `NaN`, or text such as `"NA"`, `"N/A"`, `""` | `MISSING_VALUE` | Remove the incomplete row (a complete-case decision you document) or supply the measurement. |
| Other text (including numeric strings such as `"1.5"`) or a boolean | `UNSUPPORTED_VALUE_TYPE` | Supply a plain number; categorical or boolean-coded predictors need an explicit numeric encoding this route does not choose. |
| Infinity, or magnitude above 1e9 | `INVALID_ARGUMENT` | Supply a finite value within range. |

The fault location is the cell (`$.training[i][j]`, zero-based row and column)
and its observed detail names the predictor or response. The
[missing-cell example](../examples/schemaxis/r-missing-invalid.json) shows the
first case. Dropping rows changes the training sample, so check that the
remaining rows still represent the design you intend.

`intercept` defaults to true. The number of training rows must exceed the number
of coefficients, and the chosen design must have full rank. Optional `heldout`
contains 1–512 separately declared rows in the same order, including observed
responses. The adaptor never silently reuses training observations as held-out
validation, performs a random split or chooses a model for you. Predictions
outside the training range are still only finite supplied observations, not proof
of reliable extrapolation.

Internally each design column is scaled to unit root-mean-square magnitude; the
intercept has scale one. Fixed native symbols `x1`…`xN` and `y` avoid interpreting
authored names as R syntax. Native coefficients are converted back to original
predictor scales. Python's independent Householder QR checks coefficients,
predictions and residuals. It computes the actual rectangular scaled-design
infinity-norm condition `||A||inf * ||A+||inf` from QR solves for each unit vector,
not a diagonal-ratio estimate. A condition above 1e6 is unsupported. The rank
threshold is a residual column norm of 1e-10 times sqrt(training-row count), a
separate numerical rank guard. The scaled condition is a numerical-design limit,
not a statistical-quality score. Projected input/prediction/residual overflow and
values outside the numeric-table budget are rejected during planning.

## Named acceptance requirements

Optional `requirements` contains 1–32 uniquely named finite checks. Each selects
`scope: "training"` or `"heldout"` and one metric:

| Metric | Bound | Meaning |
| --- | --- | --- |
| `rmse` | Nonnegative `maximum` | Square root of mean squared native residual over all declared scope rows. |
| `maxAbsoluteError` | Nonnegative `maximum` | Largest absolute native residual; first row wins ties. |
| `prediction` | `minimum`, `maximum` or both | Inclusive signed native prediction bounds at the required zero-based `sampleIndex`. |
| `coefficientInterval` | `minimum`, `maximum` or both | Inclusive bounds on the lower/upper confidence limits of the named `term`; needs `inference` and `scope: "training"`. |

Error and prediction bounds use the response's authored units. Coefficient
interval bounds use the coefficient's units: response units for `intercept`,
response unit per predictor unit for a slope. Every requirement must pass. Lower
prediction margins are `observed - minimum`; upper/error margins are
`maximum - observed`. Negative margins are unmet. The summary retains the actual
observed metric, signed margins, a sampled condition and an explained next action.
For RMSE the condition is the largest-absolute-residual row as a diagnostic; RMSE
itself remains an aggregate over the whole declared scope.

Native computation and independent verification run before acceptance. A valid
regression failing a declared bound fails as `FIT_REQUIREMENT_NOT_MET`, retains its
measurements/model and blocks downstream publications and successful reuse.
`INVALID_REQUIREMENT` instead means invalid names, scopes, indices or bounds.
`RANK_DEFICIENT_DATA`, `ILL_CONDITIONED_DATA` and `INSUFFICIENT_DATA` need a better
supported design; adding arbitrary rows cannot fix dependent predictors.

Comparison fidelity uses relative tolerance 1e-10 plus a response-scale absolute
roundoff bound `128 * ulp(max(abs(training_response))) * max(1, scaled_condition)`.
The actual bound is recorded in `verificationTolerance`. The zero-response case
uses the smallest representable floating-point ULP, not a fixed physical-unit
floor. Native observed response serialization has a tighter 1e-14 relative or
128-ULP allowance; sample indices match exactly. These are numerical verification
limits. Performance bounds compare actual native results without relaxing them;
accepting a requirement does not certify accuracy below the verification limits.

## Coefficient inference

Add `"inference": {"level": 0.95}` (or `{}` for 0.95) to request classical
ordinary least-squares inference from R's public
[`summary.lm`](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/summary.lm.html),
[`confint`](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/confint.html)
and `pf`. `level` is a two-sided confidence fraction from 0.5 to 0.999. With `n`
training rows and `p` coefficients the residual degrees of freedom are `n - p`
(at least one, because rows must exceed coefficients). For each coefficient the
summary reports the estimate, standard error `SE = sigma * sqrt(diag((X'X)^-1))`,
`t = estimate / SE`, the two-sided Student-t p-value and the interval
`estimate ± t(1 - (1 - level)/2, n - p) * SE`, with units (response unit for the
intercept, response/predictor unit for a slope). It also reports the residual
standard error `sigma = sqrt(RSS / (n - p))`, R² = 1 - RSS/TSS, adjusted R² and
the overall F test. With an intercept, TSS is centred on the mean and F tests that
every predictor coefficient is zero. Without an intercept R² is uncentred (about
zero), is not comparable with an intercept model, and F tests that every
coefficient is zero.

The results are valid only when the declared additive linear mean is correct, the
errors are independent with constant variance and normally distributed (exact
t/F levels depend on normality) and the predictors are fixed and measured without
error. p-values are per coefficient and unadjusted for multiple comparisons.
Coefficient intervals are not prediction intervals for new observations and do
not validate the model choice.

`inference.csv` is published **after** the summary, so existing artifact indices,
including the held-out table used by the Calc example, never move. Columns are
coefficient index, estimate, standard error, t, p, lower and upper limits.

A `coefficientInterval` requirement bounds the confidence limits of one `term`
(`intercept` or a predictor name). The lower margin is `lower - minimum` and the
upper margin is `maximum - upper`. With both bounds this is an equivalence-style
check: each bound is a one-sided test at `(1 - level)/2`, so level 0.90 is two
one-sided 5% tests. The [inference example](../examples/schemaxis/r-inference.json)
reuses the calibration data: RSS = 0.1 V² on two degrees of freedom, so
`sigma = sqrt(0.05)` V, slope SE = `sqrt(0.005)` V/degC, t = 20√2, and the 95%
critical value is `0.95 * sqrt(2 / (1 - 0.95²)) ≈ 4.3027`. The slope interval
[1.6958, 2.3042] V/degC lies inside the required [1.5, 2.5]. Tightening the bounds
to [1.9, 2.1] is unmet even though the estimate is exactly 2: the data cannot
establish that precision. The [variant](../examples/schemaxis/r-inference-variant.json)
uses eight points at 90% with slope 3, SE = `sqrt(0.08 / 6 / 168)` V/degC.

Inference needs measured scatter. If the residual standard error is below 1e6
times the native comparison roundoff allowance (an exact or synthetic fit, such as
[this one](../examples/schemaxis/r-inference-exact-invalid.json)), planning fails
with `NO_RESIDUAL_VARIANCE` at `$.inference` before R starts. A residual sum of
squares below 1e-280 is `UNSUPPORTED_INFERENCE`; rescale the response. A
`coefficientInterval` without `inference`, with held-out scope, an unknown term or
`intercept` when the intercept is disabled is `INVALID_REQUIREMENT`.

Independent verification never trusts native inference. Python computes `R^-1`
from its own Householder QR factor, then standard errors, t, R² and F, and
evaluates Student-t/F tails with a standard-library regularized incomplete beta
continued fraction. Critical values come from monotone bisection and must match
R within 1e-10 relative. The confidence level is read back exactly from R; degree
of freedom counts must match exactly. sigma, standard errors, t, F and the R²
complements must match within 1e-4 relative, with additional absolute allowances
derived from the coefficient comparison tolerance. Under the residual-variance
guard, these allowances are far above roundoff and far below the statistical
uncertainty of the estimates themselves. Each native p-value must lie inside the
independent p-values at the ends of its t or F tolerance interval. Native
inference values use 17 significant digits, and fresh-process RDS replay must
reproduce them within 1e-12.

## Prediction intervals

`prediction` is an optional request for intervals at new rows whose responses are
unknown:

```json
"prediction": {"interval": "individual", "level": 0.95, "newdata": [[0], [1], [3]]}
```

- `interval` is required and has no default: `confidence` bounds the fitted mean
  response at the row, `individual` bounds one future observation there. Both are
  always computed natively and verified; `interval` selects what is published.
- `level` is a fraction in [0.5, 0.999], default 0.95, independent of
  `inference.level`.
- `newdata` holds 1–64 rows of predictor values only, in declared predictor order
  and units. A response is never required or accepted (a wrong-width row is
  `INVALID_TABLE` at `$.prediction.newdata[i]`). These rows are not held-out
  validation; use `heldout` for observed rows.

With fitted coefficients `b`, residual standard error `sigma`, residual degrees of
freedom `df`, Student-t critical value `t` and leverage `h = x'(X'X)^-1 x`, the
mean interval is `fit ± t·sigma·sqrt(h)` and the individual interval is
`fit ± t·sigma·sqrt(1+h)`. This is distinct from the coefficient intervals of
[inference](#coefficient-inference), which describe uncertainty in `b`, not in new
responses. Native `stats::predict.lm` (both `interval = "confidence"` and
`"prediction"`, `se.fit = TRUE`) runs on the genuine fitted model and again on the
`model.rds` reopened in a fresh R process. The host recomputes everything
independently from its column-scaled Householder QR (`h = |R^-T x_scaled|²`) and
its Student-t bisection, not from native `predict`. Fit is compared with response
roundoff scaled by the new point's design magnitude; `se.fit`, `sigma`, half widths
and bounds are compared at 1e-5 relative, justified by the residual-variance guard
that keeps roundoff below 1e-6·sigma; the critical value at 1e-10 relative; `df`,
`level` and sample order exactly. Two separate limits refuse a new row with
`UNSUPPORTED_PREDICTION` before any native process, both verification-resolution
limits and neither a test of model validity. A leverage budget `h > 1e4` keeps the
arithmetic well conditioned; it does not by itself make the interval types
distinguishable, because the comparison allowance `tol*(1+sum|x_scaled|)` grows with
the response magnitude and the design size. The per-row resolution guard therefore
also compares the independently computed half widths with the actual comparison
allowance and relative component: a row is supported only when
`halfIndividual - halfConfidence > 4*(allowance + 1e-5*halfIndividual)`. Any
native bound or half width inside `allowance + 1e-5*halfIndividual` of the
independent value is accepted, and presenting one interval type as the other shifts
each of them by exactly that gap, so the factor 4 is a margin over a swap that could
not be detected. The fault is raised at `$.prediction.newdata[i]` with the
observed gap, required gap, allowance and relative component. The usual cause is
residual scatter that is small relative to the response magnitude and design scale
(a large offset, uncentred predictors, many predictors with a far point); more
scatter, a centred response, or a row nearer the training design resolves it. The
type of a published interval cannot be verified for such a row, so none is
published and no precision or confidence claim is made for it. Zero or roundoff-level
residuals fail `NO_RESIDUAL_VARIANCE` at `$.prediction`; rank, conditioning and
cell faults are those of the training fit.

The new artifact `prediction.csv` is appended after `inference.csv` (or the
summary), so every existing artifact index is unchanged and runs without
`prediction` publish exactly what they did before. Its numeric columns are
`sample,x1..xN,prediction,lower,upper,halfWidth`: `xK` is the K-th declared
predictor, `halfWidth = (upper - lower)/2` is the symmetric error for plotting, and
the first `sample` column is the zero-based row index. At eight predictors this is
13 columns (the Gnuplot adaptor accepts at most 12, so an eight-predictor table is refused by that consumer; this is accepted and disclosed, not worked around). `regression-summary.json` gains a
`prediction` block with row identity (named inputs with units), prediction, bounds,
half width, `standardErrorOfFit`, `leverage`, `outsideTrainingRange`, `residualDF`,
`criticalValue`, `residualStandardError` with units, the verified interval types,
assumptions and limits.

Assumptions: fixed predictors measured without error, a correct additive linear
mean (including at the new rows), and independent, constant-variance, normal
errors. The level is nominal, not a reliability or coverage guarantee, a
calibration certificate, model selection, a causal claim or future
generalisation. Rows outside the training predictor range are listed in
`outsideTrainingRange`: extrapolation is observed, never validated or excluded.
Examples: [individual](../examples/schemaxis/r-prediction.json),
[mean confidence at level 0.9](../examples/schemaxis/r-prediction-variant.json),
[exact fit](../examples/schemaxis/r-prediction-exact-invalid.json) and
[response supplied](../examples/schemaxis/r-prediction-response-invalid.json).
The closed-form check: the existing four-row calibration has `df = 2`,
`sigma = sqrt(0.05)`, `h = 0.25 + x²/10` and `t = 0.95·sqrt(2/(1-0.95²))`.

Primary references: the public
[predict.lm documentation](https://stat.ethz.ch/R-manual/R-patched/library/stats/html/predict.lm.html)
and the released R 4.6.1 `stats` `predict.lm` source (preferred over later patched
behaviour). Upstream R source is not modified.

## Native model, inspection and trusted handoffs

Configure an absolute Rscript executable; the qualified target is R 4.6.1 with
only base, stats and utils. `--vanilla` disables user profiles/startup data. A fresh
native process reads the generated `model.rds` and repeats its coefficients,
predictions, fitted values and residuals. Generated launchers hash the exact
worker/CSV/model inputs before each owned native stage; ordinary refreshed hashes
cannot pair a changed RDS with stale reopen evidence. Retained reads use bounded
nonblocking regular descriptors, with symlink/device/FIFO rejection. This is
ordinary evidence integrity, not a signed defence against coordinated forgery of
all execution records. RDS is native replay evidence, not cross-machine interchange.

Publications, in order:

1. `coefficients.csv`, numeric `table`: coefficient index and estimate. Names and
   predictor/response unit labels are retained in the summary; the intercept is
   first when enabled.
2. `training.csv`, numeric `table`: sample index, observed response, prediction and
   signed residual (`observed - prediction`).
3. `heldout.csv`, numeric `table`, only when held-out rows were authored: same columns.
4. `regression-summary.json`, `text`: labels, model/rank/conditioning, native metrics,
   comparison tolerance, optional inference, requirements and limits. It follows the
   tables, so its artifact index differs when no held-out table exists.
5. `inference.csv`, numeric `table`, only when `inference` was authored: coefficient
   index, estimate, standard error, t, p-value, lower and upper confidence limits.

Keep the summary with CSV to preserve units and coefficient identity. The
[R → Calc example](../examples/schemaxis/r-to-calc.json) sends held-out table index
2 to a workbook with independent numeric readback. Three named workbook checks
require residual minimum at least -0.21 V, residual maximum at most 0.21 V and
observed total minus predicted total minus residual total to reconcile within
1e-10 V in both XLSX and reopened ODS. The CSV retains plain numeric labels; the
response unit comes from this declared regression intent and its summary. A
workbook miss is `REQUIREMENTS_UNMET` even when the regression is accepted; retry
reuses the verified producer and creates a fresh failed workbook attempt.
Native RDS remains in the
producer's evidence directory. The
[finite requirement study](../examples/schemaxis/r-requirement-study.json) evaluates
two explicit budgets through the shared analytic runtime; it is not automatic
model selection or an uncertainty/generalisation proof.

```sh
PYTHONPATH=src python3 -m schemaxis configure r /absolute/Rscript
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/r-regression.json \
  --output-directory new-regression
PYTHONPATH=src python3 -m schemaxis verify new-regression
PYTHONPATH=src python3 tools/qualify_r.py --executable /absolute/Rscript \
  --calc /absolute/soffice --output-directory new-r-qualification
```

Verification of a retained directory reports malformed, missing, oversized or
unplannable retained evidence (including an `authored.json` that no longer plans,
or pathologically nested JSON) as `VERIFICATION_FAILED`. The original planning fault
is kept in `observed.authoredFault`; it is not reported as a fresh input fault.

Planning/discovery use only the host standard library. Fit/reopen share one total
native deadline, cancellation ownership and a final CPU-verification deadline
check. Every file is bounded at 8 MiB; declared row/predictor limits bound the
generated input and model. Logs and failed evidence remain inspectable.

Public API basis: [linear models](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/lm.html),
[prediction](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/predict.lm.html),
[model summaries](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/summary.lm.html),
[confidence intervals](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/confint.html),
[model serialization](https://stat.ethz.ch/R-manual/R-devel/library/base/html/readRDS.html),
[official R releases](https://www.r-project.org/).
