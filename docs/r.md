# R: measured numeric linear regression

The `schemaxis.r/1` route fits a small, additive, unweighted ordinary least-squares
model with R's public `stats::lm` API. Use it for numeric calibration or a bounded
regression study where declared training and separate held-out observations have
known meaning. Optional [coefficient inference](#coefficient-inference) adds
classical standard errors, t tests and confidence intervals under stated error
assumptions. It does not assess causal effects, prediction intervals or future
generalisation. No authored R scripts, formulas, native functions, external
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
Every cell must be finite and within ±1e9. No missing, categorical or text cells.

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
