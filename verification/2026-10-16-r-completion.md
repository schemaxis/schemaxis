# R coefficient inference completion review — 2026-10-16

**Architect closeout:** shared reference/Help generation, catalogue and workflow
guidance integration, admission checks, the full host suite and final native
qualification are complete. A fresh receipt is registered against the final
source. See the [integration verification](2026-10-16-architecture-integration.md).
The implementation-agent handoff below records its earlier state; its pending
central-integration items are now resolved. Application scope limits remain.

## Changed scope

`schemaxis.r/1` `linearRegression` gains opt-in classical ordinary least-squares
coefficient inference and one new requirement metric. Nothing else about the
supported model changed: additive, unweighted, numeric, full rank, 1–8 predictors,
explicit training/held-out rows, no authored formulas, packages or code.

- `inference: {"level": 0.5–0.999}` (default 0.95). Native values come from the
  public `stats::summary.lm`, `stats::confint` (lm method) and `stats::pf`.
  Outputs are per-coefficient estimate, standard error, t, two-sided p and confidence
  limits with units; residual standard error and degrees of freedom; centred or
  uncentred R² and adjusted R²; and the overall F test with its hypothesis stated.
  Assumptions (correct additive mean; independent, constant-variance, normal
  errors; fixed predictors) and limits (no multiplicity adjustment, prediction
  interval, causality or model validation) are recorded in the summary.
- `coefficientInterval` requirement: inclusive bounds on the lower/upper
  confidence limits of a named `term`, training scope only, gated like the
  existing requirements (`FIT_REQUIREMENT_NOT_MET` blocks success and reuse).
- New planning faults before native launch: `NO_RESIDUAL_VARIANCE` (`$.inference`;
  residual standard error below 1e6 × the native comparison roundoff allowance,
  for example an exact fit) and `UNSUPPORTED_INFERENCE` (residual sum of squares below
  1e-280). `INVALID_REQUIREMENT` now also covers interval misuse. The existing
  `INSUFFICIENT_DATA` (n ≤ p) and `RANK_DEFICIENT_DATA` remain the faults for
  undefined degrees of freedom and rank deficiency.
- `inference.csv` is appended after `regression-summary.json`. Existing artifact
  indices, including held-out index 2 used by the Calc example, never move.
  Documents without `inference` keep the same publication files and values; only
  the plan/summary `losses` wording changed, because it previously denied that
  intervals exist.
- Route deliverables that were missing: `studio.json` (two editable starters and four
  snippets), application/operation discovery metadata and adaptor-owned
  `search-cases.json`.

Unchanged legacy behaviour was re-run (all prior native gates) but was not
re-reviewed editorially beyond that evidence.

## Runtime and upstream

Observed **R version 4.6.1 (2026-06-24)**, reusing read-only the private build
recorded in `verification/2026-10-10-r-regression.md`. No runtime was installed,
and the historical tree was not modified. On 2026-10-16 the official CRAN R-4
source index listed `R-4.6.1.tar.{gz,xz}` (2026-06-24) as the newest release, so
4.6.1 remains the latest stable release and `absorbedVersion` is unchanged.
Calc handoffs used the same LibreOffice 26.8.1.1 private runtime as before. That
launch updated two directory timestamps inside the reused LibreOffice tree; no
file was added or changed there. Final requalification should use a private copy.

## Independent verification design

The host never trusts native inference. Python forms `R^-1` from its own
column-scaled Householder QR factor, giving `SE = sigma*||row_j(R^-1)||`, t, MSS
and RSS (R² = MSS/(MSS+RSS), centred only with an intercept) and F. Student-t and F
tails use a standard-library regularized incomplete beta (modified Lentz continued
fraction, complementary arguments supplied separately). Critical values use
monotone bisection. The checks are:

- confidence level read back exactly from R; degree-of-freedom counts exact;
  critical value within 1e-10 relative;
- sigma, SE, t, F and the complements of R² and adjusted R² within 1e-4 relative,
  plus absolute allowances derived from the existing coefficient tolerance. Under the
  residual-variance guard the worst-case roundoff is below about 2e-5 relative, and
  far below the sampling uncertainty of SE itself;
- each native p-value inside the independent p-values at the ends of its t/F
  tolerance interval (monotone image, 1e-10 evaluation slack);
- 17-significant-digit native inference tables (`write.table` keeps only 15
  digits, and with `scipen` it expands tiny p-values to hundreds of characters);
- fit versus fresh-process RDS reopen equality within 1e-12.

Tests and the qualifier add a third oracle: exact rational normal equations
(`fractions.Fraction`), independent of QR and of the distribution code.
Distribution accuracy was checked against closed forms (t with 1 and 2 degrees of
freedom, F with numerator 1 and 2, `qt` with 1 and 2 degrees of freedom at five
levels) to at most 3e-13 relative.

## Commands and results (newly run)

| Command | Result |
| --- | --- |
| `python3 -m unittest tests.unit.test_r_inference tests.unit.test_r_admission` | 29 passed (14 new, including Studio starter and search-case checks; 15 existing) |
| `python3 tools/studio_guidance.py --app r --check` | 22 reviewed, 23 reference, 0 pending, 0 stale, no missing sources |
| `python3 -m schemaxis readiness --app r --admission --check` | required checks pass (studio.library, discovery.application/terms/acceptance, completion.review); remaining unknowns are external links not fetched and behavioural lifecycle |
| `python3 -m schemaxis adaptor conform schemaxis.r/1` (host) | verified |
| `python3 -m schemaxis adaptor conform schemaxis.r/1 --native` | verified: 6/6 cases, including new `calibration-slope-interval` and `eight-point-ninety-percent`; timeout and cancellation probes pass; receipt registered |
| `python3 tools/qualify_r.py --executable … --calc …` | verified (details below) |
| `node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs` | live checkout: R cases OLS and uncertainty fail on Help only (stale packaged Help); scratch regeneration: all six R tests pass |

Both native runs and the receipt bind source digest
`sha256:43e1fd06eec9e4eaa3c267726d41ea821eeca12a157b23e1e079712eafb57904`.
Bulk results are in `evidence/architect-20261016/r/` (`qualification-1/`,
`conform-native/`, `conform-host/`, logs, scratch generator simulation).

Native qualifier gates (R 4.6.1 + Calc):

- Closed-form calibration (df 2): slope SE √0.005 V/degC, t 20√2,
  p = 2/(s(s+t)) with s = √802 (also the F p-value), 95% critical value
  0.95·√(2/(1−0.95²)), centred R². Artifacts are the existing four plus
  `inference.csv` last.
- Eight-point 90% variant (df 6): slope SE √(0.08/6/168), F 113400.
- Levels 0.5, 0.99 and 0.999: exact native level readback, with critical values
  matching the df-2 closed form to 1e-12.
- Through the origin: uncentred R² 120/120.04, F 9000 with numerator 1.
- Correlated three-predictor design with predictor scales 1, 1e3 and 1e-3
  (condition about 9.9) and a 1e8 predictor scale: these agree with exact
  rational normal equations; native SE differs from exact by at most 2e-15
  relative across all inference cases.
- Unmet: interval [1.9, 2.1] with an estimate of exactly 2 gives
  `FIT_REQUIREMENT_NOT_MET` on run and replay. The data cannot establish that
  precision.
- Negative: the exact-fit example gives `NO_RESIDUAL_VARIANCE` at `$.inference`
  before any directory or native process is created. A forged native p-value
  (fit and reopen, ordinary hashes refreshed) is rejected.
- All earlier gates re-pass: seven accepted models, three unmet fits, RDS/acceptance
  forgery rejection, the Calc handoff with reuse, and an unmet producer blocking
  the consumer.

## Checklist

- **registration**: native identity extended to `summary.lm`/`confint`; the
  manifest is unchanged otherwise; unsupported features have specific
  `notApplicable` reasons. Pass.
- **schema**: `inference` object, `term`, a third `oneOf` requirement alternative
  (scope const training, term pattern, either bound). Schema/planner parity is
  tested on seven invalid variants. Generated reference drift is pending the
  architect's regeneration.
- **semantics**: exact-location faults for level range, unknown keys, interval
  misuse, unknown or disabled `intercept` term, n ≤ p, rank deficiency, zero
  residual variance and underflow, all before native launch.
- **native-mapping**: public `summary.lm`, `confint` and `pf`; fixed symbols; level
  passed as an exact `repr` and read back; bounded native acceptance passed.
- **execution**: same isolated runner, deadline and cancellation; new native
  tables are in evidence digests and launcher bindings are unchanged; tamper
  probes pass.
- **discovery**: application label/purpose/keywords and curated operation terms;
  five reviewed cases cover all kinds and surfaces. The ambiguous case
  "uncertainty" is expected to reach this operation (coefficient uncertainty) and
  makes no suitability ranking claim. The negative "logistic regression" was
  checked to be absent from every R projection and Help text.
- **guidance**: 11 new addresses reviewed, operation/requirement records updated
  so they no longer deny confidence intervals; 0 pending. The prose was written by
  the implementing agent from the R documentation and standard OLS theory; an
  independent statistician's review is still recommended.
- **help**: `docs/r.md` section, faults/recovery and API links added. The
  generated `docs/generated/r-operations.md` and packaged Help are stale until the
  shared generators run.
- **examples**: `r-inference` (baseline), `r-inference-variant`,
  `r-inference-exact-invalid` (expected `NO_RESIDUAL_VARIANCE`, schema-valid);
  Studio starters plan with filled values.
- **tests**: listed above; the full host suite is left to the parent.
- **qualification**: new native receipt registered for the current source.
  Implementation, documentation and native axes are reported separately.
- **maintenance**: `upstream.json` scope, evidence and acceptance recipe updated;
  `absorbedVersion` stays 4.6.1 (still latest stable).

## Remaining gaps

- Shared regeneration (`python3 -m schemaxis reference`,
  `python3 tools/generate_studio_help.py`) is needed for the R reference and
  packaged Help. Until then, two R Help-surface search cases fail in the live
  checkout.
- The receipt digest includes shared framework files. Any shared integration
  change makes it stale; rerun native conformance and `tools/qualify_r.py`, then
  re-register.
- Not offered: prediction or tolerance intervals, heteroscedasticity-robust
  standard errors, residual diagnostics/plots, multiplicity adjustment, weighted or
  categorical models. A Calc handoff of `inference.csv` was not separately
  exercised; the existing held-out handoff was re-run.
- Distribution functions are validated against closed forms and native R for the
  tested degrees of freedom, not exhaustively. Numerical tolerances are fidelity
  limits, not statistical claims.
- The 2026-10-10 receipt and note are retained unchanged as history. The new
  receipt replaces the registered route record.
