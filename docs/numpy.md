# NumPy principal component analysis

Use `schemaxis.numpy/1` with `operation: principalComponents` to find the dominant
correlated patterns in a captured table of numeric measurement channels: for example
several thermocouples, strain gauges or pressure transducers recorded together. The
route centres every channel at its mean, scales the channels as you declare, and
computes principal components by singular value decomposition in an isolated NumPy
process. It publishes labelled tables (spectrum, loadings and scores, or a
retained-subspace projector, and a reconstruction in the channels' own units) plus an
independent host verification record. Requirements you declare are decided by that
host verifier as **met**, **unmet** or **indeterminate**; only met results are
accepted deliverables.

This is a bounded measurement-table workflow, not a statistics package. There is no
significance testing, confidence interval, factor rotation, robust or median PCA,
missing-value imputation or physical interpretation of components. ParaView's
generated catalogue also lists a principal component analysis statistics filter
(`pvPrincipalComponentAnalysis`); it is an unqualified transcription with native
defaults and multiblock output. This route is the unit-aware, independently verified
measurement-table alternative.

## Start with the analytic sensors

[numpy-sensors.json](../examples/schemaxis/numpy-sensors.json) analyses
[numpy-sensors.csv](../examples/schemaxis/numpy-sensors.csv): four millivolt
channels with a time key, built exactly as offsets plus `H d Rᵀ` from Hadamard
columns, `d = (4, 2, 1, 0.5)` and `R` equal to the 4×4 Hadamard matrix divided by
two. The n−1 covariance is therefore exactly `R diag(64 d²/63) Rᵀ`, so the expected
eigenvalues are 1024/63, 256/63, 64/63 and 16/63, the loadings are the columns of
`R`, and keeping two components leaves an RMS reconstruction residual of
√0.3125 ≈ 0.559 mV in every channel. Replace `source` with the absolute path of the CSV.

```sh
schemaxis plan numpy-sensors.json
schemaxis run numpy-sensors.json --numpy /absolute/numpy-env/bin/python --output-directory fresh-pca
schemaxis verify fresh-pca
```

[numpy-sensors-standardised.json](../examples/schemaxis/numpy-sensors-standardised.json)
standardises the same channels (correlation PCA, eigenvalues 4d²/Σd²) and publishes the
projector onto the retained subspace.
[numpy-pressure-drift.json](../examples/schemaxis/numpy-pressure-drift.json) analyses
[a synthetic captured-style record](../examples/schemaxis/numpy-pressure-drift.csv):
six pressure transducers near 101325 Pa with drift, a common oscillation, noise and
0.01 Pa quantisation, at offset ratios of 6–8×10⁵. It is clearly synthetic and makes
no claim about real instruments. The invalid examples
[mix units without scaling](../examples/schemaxis/numpy-unit-mismatch-invalid.json) and
[omit a declared scale](../examples/schemaxis/numpy-declared-scale-invalid.json).
Studio offers covariance and correlation-subspace starters with a CSV picker.

## Input CSV and range contract

The source is an absolute local regular `.csv` file of at most 8 MiB (no symlink, URL
or wildcard). Its header must equal the optional `rowKey` followed by the `channels`,
in order; there are no ignored columns. Bytes must be ASCII without a byte-order mark,
comma-separated, with LF or CRLF line ends. Quotes, blank lines, ragged rows and
surrounding whitespace are refused. Every cell is a plain decimal number such as
`-12`, `0.25` or `1.5e-3`; `nan`, `inf`, hexadecimal, digit separators (`1_000`),
non-ASCII digits and locale decimals are refused with their line and column. Empty
cells are refused: missing values are never imputed. The shared tabular reader's
more lenient float parsing is not used.

`rowKey` is optional. When present it must increase strictly; it is carried into the
scores and reconstruction but not analysed. Without it rows are numbered 1..n and the
key column is called `row`. Names are identifiers (a letter, then letters, digits or
underscores, at most 40 characters); `row`, `component`, `channelIndex` and `PC<n>`
are reserved because they label published columns. The one exception is a `rowKey`
named `row`, which is how a run consumes the `row` column that a keyless run publishes
(see the handoffs below); no channel may be named `row`.

Limits: 2–32 channels, 3–10000 rows, at most 160000 analysed cells and at most 10
retained components. Values are checked after parsing to IEEE binary64:

| Rule | Bound | Fault and location |
| --- | --- | --- |
| Raw values | zero or magnitude within [1e-48, 1e48] | `PCA_VALUE_RANGE`, `line N column J` |
| Channel spread | sample deviation > 0 and largest magnitude ≤ 1e6 × deviation | `PCA_CHANNEL_SPREAD`, `$.channels[j]` |
| Scaled spread | deviation / scale within [1e-48, 1e48] | `PCA_SCALE_RANGE`, `$.channels[j]` |
| Every published number | finite and within ±1e100 | `PCA_VALUE_RANGE`, `published:` or `intermediate:` location |

The decimal `9.999999999999999e-49` parses to the same binary64 value as `1e-48` and is
accepted. The offset-ratio limit means a channel must vary by at least a millionth of
its magnitude: subtract a known offset upstream for absolute temperatures or
pressures beyond that. All checks run on the host before the native process starts,
and again natively.

## Scaling, units and centring

Every channel is centred at its arithmetic mean (corrected two-pass natively, exact
fsum on the host). The variance denominator is always n − 1. `scaling` is required:

- `none`: covariance PCA. Every channel must declare the same unit, otherwise
  `PCA_UNIT_MISMATCH`. Eigenvalues are in that unit squared and scores in that unit.
  The scaled-spread rule then bounds each deviation to [1e-48, 1e48].
- `standardise`: divide by each n−1 sample deviation (correlation PCA). Results are
  dimensionless and every scaled spread is exactly 1.
- `declared`: divide each centred channel by its `scale`, a finite positive value in
  that channel's unit such as a nominal range or resolution. Every channel needs a
  scale; a scale with another scaling mode is refused rather than ignored.

Units are labels: nothing is converted. Covariance PCA is dominated by the channels
with the largest spread, which is intended only when units and spreads are
commensurable. Extreme ratios between declared scales make the small channels'
reconstruction uncertifiable. In practice, cross-channel scaled-spread ratios beyond
roughly 1e8–1e9 at loadingTolerance 1e-6 are refused with
`PCA_RECONSTRUCTION_UNCERTIFIED`. That is a conditioning-dependent example, not a
separate hard limit.

## Retention, resolution and repeated eigenvalues

`retention` holds exactly one of `components` (1–10, at most the channel count) or
`minimumExplainedVariance` (the smallest number of components, at most 10, whose
cumulative fraction reaches the value). Components are ordered by descending
eigenvalue, and each loading's sign makes the first channel within 2η of its largest
magnitude positive.

The resolution threshold θ is 4·c·u/η times the total variance, where
c = 16 + 48p + 8(n + p) and u = 2⁻⁵³. It is a declared policy chosen so that
qualification-budget eigenvalue differences correspond to loading changes of at most
η/4. It is not a LAPACK guarantee.

- `output: components` requires every kept eigenvalue to be at least θ (otherwise
  `PCA_COMPONENT_BELOW_RESOLUTION`, covering rank deficiency and noise floors). It
  also requires separation of at least θ from both neighbours (otherwise
  `PCA_DEGENERATE_COMPONENT`).
- `output: subspace` publishes only the projector onto the kept subspace, so repeated
  eigenvalues inside the kept set are allowed. The cut must not split a cluster
  (`PCA_RETENTION_SPLITS_CLUSTER`).
- A deciding quantity within the borderline band is refused as
  `PCA_SPECTRUM_BORDERLINE`. For explained-variance retention it is refused as
  `PCA_RETENTION_BORDERLINE`. More than 10 needed components gives
  `PCA_RETENTION_UNREACHABLE`.

No arbitrary basis is ever published for a repeated eigenspace: different correct
algorithms return different vectors there, while agreeing on the subspace.

## Requirements and the host verification record

`requirements` is optional. `minimumExplainedVariance` bounds the kept fraction of
total variance. `reconstructionRMS` lists `{channel, maximum}` pairs bounding the
root-mean-square difference between a captured channel and its reconstruction, in the
channel's unit, with denominator n.

The intent is the ideal kept PCA of the captured data: the exact retained eigenspace
of the exact covariance, with the exact mean and published scales, of the parsed
binary64 values. The host verifier measures the published reconstruction and bounds
its distance from that ideal with an effective per-channel tolerance. The tolerance
is the sum of four parts:

| Part | Meaning |
| --- | --- |
| affine floor | Rounding of the published mean + scale × projection. |
| mean | First-order effect of the computed mean; vanishes when every component is kept. |
| subspace (first order) | Validated distance β between the published and ideal retained subspace, times the scale and √((n−1)λ₁/n). |
| evaluation | Rounding of the RMS itself. |

A requirement is **met** when it holds after allowing the tolerance, **unmet** when it
fails after allowing it, and **indeterminate** otherwise. With every component kept the
ideal residual is exactly zero, yet a bound below the rounding floor (about 1e-13 of
the data magnitude) is indeterminate, never met by luck. A tolerance above 1e100 is
recorded as `null`, and its requirement is then indeterminate.

`pca-verification.json` is the only final requirement and tolerance record. It binds
the captured source digest, parsed-data digest, every native publication digest, the
plan, the observed runtime identity and the implementation fingerprints. The runtime
binding's `executablePathDigest` is the SHA-256 of the configured interpreter's path
string (UTF-8), not of the interpreter's bytes; the observed NumPy, BLAS and Python
versions and the exact launch command are checked separately. It is advisory
path-string provenance, not a binary identity or authentication mechanism. The native
`pca-summary.json` contains measurements and residual diagnostics only, never a
status. A run with unmet or indeterminate requirements, or an uncertified
reconstruction, keeps all evidence including the record. It then fails with
`PCA_REQUIREMENT_NOT_MET`, `PCA_REQUIREMENT_INDETERMINATE` or
`PCA_RECONSTRUCTION_UNCERTIFIED`, so workflows cannot consume it. Saved verification
reproduces the same fault.

## Outputs and workflow handoffs

Publication order is fixed for each output mode:

| Index | components | subspace |
| --- | --- | --- |
| 0 | `spectrum.csv` (table) | `spectrum.csv` (table) |
| 1 | `loadings.csv` (table) | `projector.csv` (table) |
| 2 | `scores.csv` (table) | `reconstruction.csv` (table) |
| 3 | `reconstruction.csv` (table) | `pca-summary.json` (text) |
| 4 | `pca-summary.json` (text) | `pca-verification.json` (text) |
| 5 | `pca-verification.json` (text) | — |

Each output has a fixed layout:
- `spectrum.csv`: `component,eigenvalue,varianceFraction,cumulativeFraction` for all p
  eigenvalues.
- `loadings.csv`: `component,<channels>`.
- `scores.csv`: `<rowKey or row>,PC1..PCK`. Scores are defined as the scaled data
  times the published loadings.
- `projector.csv`: `channelIndex,<channels>`.
- `reconstruction.csv`: `<rowKey or row>,<channels>`, in channel units.

Index columns are integer literals, and numbers are shortest round-trip binary64
text. There is no `.npy`, pickle or object output.

[numpy-denoise-workflow.json](../examples/schemaxis/numpy-denoise-workflow.json) reduces
the sensors to a two-dimensional subspace and analyses that reconstruction (artifact
2) again: only the first two analytic eigenvalues remain.

A keyless
run publishes its key as the integer column `row`. To analyse that run's
`reconstruction.csv` (index 3 in `components` mode, index 2 in `subspace` mode),
declare `rowKey` with the name `row` and a unit such as `count`; without it the header
is refused as `PCA_HEADER_MISMATCH`. The second run then publishes `row` again, now
holding the key values. `scores.csv` cannot be re-analysed because its `PC<n>` column
names are reserved.

Calc accepts the `table`
artifacts. [numpy-calc-workflow.json](../examples/schemaxis/numpy-calc-workflow.json)
hands the scores to Calc; that handoff is checked by host planning only.

Consumer limits still apply:
- Calc reads at most 64 columns and 10000 rows.
- Gnuplot reads CSV files rather than artifacts. It needs strictly increasing x
  (scree plots from `spectrum.csv`, or scores against a strictly increasing row key)
  and accepts at most 2048 rows and 12 columns. Its unit alphabet has no `^`.

Host compatibility is not qualification of a downstream native handoff. Source byte
digests participate in workflow reuse, and edits at the same path invalidate it.

## Verification, tolerances and limits

A separate native readback process re-parses every publication. It confirms that the
values are finite and within ±1e100, have integer indices, round-trip bit-for-bit to
the computed float64 arrays, and that scaled data times the loadings reproduce the
scores bit-for-bit. That exactness is a same-runtime property; the host verifier is
tolerance-based.

The host verifier uses only the Python standard library. It re-parses the captured
bytes with the same strict grammar and recomputes means, deviations and covariance
with correctly rounded `math.fsum` (each symmetric pair assigned from one value). It
solves the spectrum with its own cyclic Jacobi method. It then checks structure,
internal consistency, source statistics and the spectrum, and recomputes every
decision.

Two kinds of tolerance are reported separately:

- **Qualification budgets** for agreement between NumPy and the host are
  declared empirical budgets. Eigenvalues must agree within (16 + 4p·max(12,
  sweeps) + 8(n+p))·u·T. Other budgets cover orthonormality, scores, total variance
  and means. They are not proven bounds on LAPACK `gesdd`; another BLAS or build that
  exceeded them would be refused, not trusted.
- **A posteriori bounds** are computed in each run from host residuals under stated
  hypotheses:
  - eigenvalue errors from the Jacobi residual and orthogonality (Weyl and Ostrowski);
  - the covariance's distance from the exact covariance of the parsed data;
  - each loading's **sine angle** to the exact eigenvector (Davis–Kahan, residual
    form);
  - the retained-subspace distance β.

  Their floating-point evaluation uses first-order rounding allowances, not interval
  arithmetic: they are careful engineering bounds, not machine-checked proofs.

`loadingTolerance` η (default 1e-6, within [1e-9, 1e-2]) is the sine-angle accuracy
each published loading or projector must demonstrate. After sign alignment the
loading 2-norm distance is then at most √2·η. Each channel's reconstruction must also
be certified to at most η times its sample deviation. Eigenvalue accuracy is relative
to the total variance, not to each small eigenvalue. The analysis concerns the parsed
binary64 data: decimal input rounding, sampling uncertainty and measurement error are
outside the claim.

### Saved runs, removed sources and portable export

Each stage is launched from the run directory as exactly `<interpreter> -I -B
native-worker.py compute` (then `readback`), where `native-worker.py` is the trusted
worker copied into the run. Saved verification requires that exact command with the
recorded interpreter and the current worker bytes, so an absolute worker path, a
missing `-I`, another interpreter or an edited worker is refused even after ordinary
hashes are refreshed.

Saved verification reads only the retained capture (`source.csv` with
`capture.json`), never the original CSV. Removing or editing the original therefore
does not affect verification of an existing run, but reuse refuses a missing source
(`PCA_INVALID_SOURCE`) and changed bytes invalidate it. A run saved by an earlier
adaptor implementation is refused; rerun it.

For saved workflows, the adaptor's `retainedInputs` hook reports the original source
path with the SHA-256 of the retained `source.csv`. It runs only after ordinary
verification has passed, never rereads the original, and refuses a missing, partial
or inconsistent capture binding. The capture must agree with the authored document,
the plan, the native consumed-input record and the host verification record. Shared
workflow verification compares that map with the scheduler's saved input hashes. A
saved workflow therefore verifies after its original source is edited or removed,
while resuming still checks the current source bytes and reruns when they changed.
Scheduler records that claim different source bytes from those retained fail
verification, and resuming then starts a fresh native attempt instead of reusing the
old one.

The NumPy checks do not bind the run's location: publications are compared by order,
name, kind and current digest, and the recorded location is not trusted for content.
With the current shared run relocation, a single run, a workflow or a study passes
normal saved verification after export with the original source removed. Here,
export means the shared schema export or a confirmed `schemaxis storage` backup, and
normal verification means `schemaxis verify` or the registry. Exported workflow
handoffs keep their recorded producer publications and digests.

Saved verification on another computer reruns only the standard-library verifier.
That verifier uses binary64 arithmetic, correctly rounded `math.fsum` and
`math.sqrt`, and CPython's own `math.hypot`; it calls no other libm function. It has
not been exercised across hosts, operating systems or Python versions. Any last-bit
difference changes the recomputed record, so verification fails rather than
accepting. Native qualification covers only the host where it ran. OpenBLAS can
select different kernels on other processors, so runs there are unqualified, although
the same budgets and host checks still apply to each run.

## Faults and recovery

| Fault | Meaning and recovery |
| --- | --- |
| `PCA_INVALID_SOURCE` | Select an absolute regular `.csv` file of at most 8 MiB, not a link. |
| `PCA_INVALID_CONTRACT`, `PCA_UNIT_MISMATCH` | Correct the located declaration; convert units upstream or choose standardise/declared scaling. |
| `PCA_INVALID_CSV`, `PCA_HEADER_MISMATCH`, `PCA_MISSING_VALUE`, `PCA_INVALID_NUMBER`, `PCA_ROW_KEY_ORDER`, `PCA_DIMENSIONS`, `PCA_RESOURCE_LIMIT` | Correct the located line, column or limit; values are never silently repaired. |
| `PCA_VALUE_RANGE`, `PCA_CHANNEL_SPREAD`, `PCA_SCALE_RANGE` | Rescale or subtract an offset upstream, choose other scales, or remove a constant channel. |
| `PCA_COMPONENT_BELOW_RESOLUTION`, `PCA_DEGENERATE_COMPONENT`, `PCA_RETENTION_SPLITS_CLUSTER`, `PCA_SPECTRUM_BORDERLINE`, `PCA_RETENTION_BORDERLINE`, `PCA_RETENTION_UNREACHABLE` | Retain fewer components, use subspace output, or relax loadingTolerance only if that accuracy is defensible. |
| `PCA_RECONSTRUCTION_UNCERTIFIED` | The recovery text gives the uncertainty divided by (η × deviation): use standardise scaling, less extreme scales, or a defensibly larger η. |
| `PCA_REQUIREMENT_NOT_MET`, `PCA_REQUIREMENT_INDETERMINATE` | Inspect `pca-verification.json`; the evidence is retained but is not an accepted deliverable. |
| `PCA_UNSUPPORTED_RUNTIME`, `INTERPRETER_NOT_FOUND` | Configure an isolated Python with exactly NumPy 2.5.4 linked to OpenBLAS 0.3.34. |
| `VERIFICATION_FAILED` | Retain the evidence and investigate; never relabel it verified. |

Timeout and cancellation stop the owned native process group. Retry in a new output
directory.

## Runtime, public API and maintenance

Configure an isolated Python containing NumPy with `schemaxis configure numpy
/absolute/python`, `--numpy /absolute/python` or `SCHEMAXIS_NUMPY`. Do not install
NumPy into the Schemaxis host environment: discovery, planning and verification never
import it.

The worker runs with `-I -B`, one BLAS/OpenMP thread, a 4 GiB address space, 60 CPU
seconds and 64 MiB per output file. It observes the mapped OpenBLAS library. Exactly
NumPy 2.5.4 linked to OpenBLAS 0.3.34 is qualified (exercised with Python 3.12.15 on
Linux); any other build is refused with `PCA_UNSUPPORTED_RUNTIME` rather than assumed
compatible. No broader NumPy 2.x compatibility is claimed.

The native mapping uses
[`numpy.linalg.svd`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.svd.html)
(LAPACK `gesdd`, singular values descending, no sign convention). It also uses
[`eigh`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.eigh.html) and
[`eigvalsh`](https://numpy.org/doc/stable/reference/generated/numpy.linalg.eigvalsh.html),
for diagnostics and the native Ritz values only. The latest stable release is
[NumPy 2.5.4](https://github.com/numpy/numpy/releases/tag/v2.5.4). A new release or BLAS
build needs fresh bounded native acceptance with `tools/qualify_numpy.py` before the
pinned identity changes.

See the [completion review](../verification/2026-10-19-numpy-completion.md) for
verification scope, and the generated operation reference for the complete schema.
