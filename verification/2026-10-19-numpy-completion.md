# NumPy principalComponents completion review — 19 October 2026

## Final technical acceptance

Root completed independent-review reconciliation, shared portability integration,
generated reference and Help, full host and Studio suites, admission checks and
final source-current common native receipt registration. The app browser tests
passed. Fresh full numerical qualification passed 25 semantic cases plus the
documented invalid-record, export, workflow, study and lifecycle checks.

Technical acceptance is limited to NumPy 2.5.4 with OpenBLAS 0.3.34 and the
domain and numerical limits below. Programme delivery credit remains pending
the parked paired PrusaSlicer strengthening. See the [final closeout record](2026-10-19-closeout.md).

## Earlier implementation and review record

The following records the earlier assignment stage. Statements that generation,
browser checks, integration or receipt registration were pending are historical;
those gates are closed by the final acceptance above. Numerical, cross-host and
untested-consumer limits still apply.

Scope: `schemaxis.numpy/1`, `principalComponents`. Bounded, unit-aware principal component
analysis of one numeric ASCII CSV:
- explicit centring and scaling (`none`, `standardise`, `declared`);
- retention by component count or explained-variance fraction;
- `components` or `subspace` output;
- host-owned requirement and certification decisions.

The native target is exactly NumPy 2.5.4 linked to OpenBLAS 0.3.34 (one thread), exercised
with Python 3.12.15 on Linux. Host discovery, planning and verification are
standard-library only.

This note records the owner's implementation and focused qualification. It is **not** a
delivery or integration acceptance. An independent review of the app implementation found
no app-level blocker. Root still owns:
- the shared generated reference and packaged Help;
- final integration of the shared run relocation that the export results below rely on;
- the browser, full host, Studio and release checks;
- final source-bound qualification registration.

The numerical contract follows an independent design review; its decisions are listed under
"Root design decisions applied" below.

## Twelve-item review

| Item | Result and evidence |
|---|---|
| registration | `adaptor.json` declares a document route, isolated process runtime, scheduled workflow, composition, `table` artifact acceptance and the `--numpy` interpreter option. It also records explicit unsupported decisions for native inspection, MPI, time batches, live editing, conversion and native save. The registry stays data-driven: no framework edits and no imports from other adaptors. |
| schema | All fields are declared in the closed declaration grammar, and the schema is derived from the declarations. Closed objects replace the design's open maps: each channel carries an optional `scale`, and `reconstructionRMS` is an array of `{channel, maximum}`. Unknown keys fail. Host tests check schema/declaration parity, required fields and immutable planning. |
| semantics | Before native launch the planner checks identifiers, reserved names, units, unit sharing for `none`, declared-scale presence and finiteness, single retention choice, component count and requirement channels. The capture is then fully parsed and its statistics checked. Every fault is located. |
| native-mapping | `numpy.linalg.svd(full_matrices=False)` (LAPACK `gesdd`) on centred, scaled data. Eigenvalues are S²/(n−1), padded to p. Loadings are sign-canonicalised. Scores are Z·V and the reconstruction is μ + s·(TVᵀ) or μ + s·(ZP). `eigh` and `eigvalsh` serve only as diagnostics and native Ritz values. The worker checks the NumPy version, the mapped OpenBLAS library and one-thread environment variables. |
| execution | Trusted worker copied to the run and launched from the run directory as exactly `python -I -B native-worker.py <stage>`, with POSIX resource caps. One total deadline covers the run, with owned process-group cancellation. Native compute and a separate readback process are followed by the host verification artefact `pca-verification.json`. Captures, configuration, implementation fingerprints, consumed-input bindings, submissions, logs and fault records are retained. After ordinary verification, the `retainedInputs` hook reports the original source path with the digest of the retained capture, cross-checked against the authored document, the plan, the native consumed-input record and the host record. |
| discovery | Eight reviewed adaptor-owned cases across all four surfaces: acronym, multiword, synonym, ambiguous and two negative cases (`linear regression` and `Fourier spectrum`). Actual Studio and Help search regressions need root's shared generation and Studio suite. |
| guidance | The operation and all 24 literal-schema addresses are reviewed (`studio_guidance.py --app numpy --check`: 25 reviewed, 0 pending, 0 stale). The records cover units, defaults, η as a sine-angle bound, and the scaling and degeneracy pitfalls. |
| help | `docs/numpy.md` covers the contract, examples, outputs, handoffs, tolerances, faults and API links, and every guidance anchor resolves. A scratch generation of the operation reference and schemas succeeded. The packaged Help and `docs/generated` refresh are pending root's shared generation. |
| examples | Baseline (`numpy-sensors.json`) and variant (`numpy-sensors-standardised.json`) carry exact rational expectations. The remaining examples are a synthetic captured-style drift case, two planner-invalid cases, a NumPy-to-NumPy denoise workflow and a host-planned Calc handoff. Two Studio starters provide a required CSV picker. |
| tests | `tests/unit/test_numpy.py` has 24 host tests. It covers grammar and range bounds, plan faults, schema parity, the import boundary, the exact fixture covariance, Jacobi certificate soundness, decision rules and three-state logic. It also runs the full verifier on a standard-library-built publication with semantic and range mutants, native-refusal mapping, outcome faults, reuse identity, and Studio templates and undo. Further tests cover the exact run-relative launch command, the `executablePathDigest` binding, location-independent but digest-bound publication checks, and the `retainedInputs` hook. The hook tests cover a removed or changed original, the shared route through `adaptor.json`, and 15 partial, missing, malformed or foreign capture bindings, each refused rather than returning an empty map. `tests/studio/numpy.browser.test.mjs` covers discovery, operation Help and cancellation, a typed `scaling` edit with host validation and atomic undo, and the located faults; it is authored but not executed (see limits). |
| qualification | `tools/qualify_numpy.py` passed against the frozen source. It ran the shared kit (2 literal cases, 34 integrity probes, timeout and pre-launch cancel) and 25 semantic cases with outcomes fixed in advance. It also ran native fault injection, 21 hostile saved-evidence mutants, a native workflow handoff with reuse, invalidation and forged scheduler provenance, an unmet producer blocking its consumer, a two-state study, and in-flight timeout/cancel. The export checks covered single runs, a workflow and a study, using the shared schema export and the `schemaxis storage` CLI backup with the original sources removed. They also ran 10 exported-run mutants and 4 exported-workflow handoff mutants. The receipt is not registered; root registers the final receipt. |
| maintenance | `upstream.json`: latest-stable from the official GitHub release feed, with 2.5.4 absorbed for exactly this bounded scope. A new NumPy or BLAS build requires fresh bounded acceptance; other builds are refused (`PCA_UNSUPPORTED_RUNTIME`). |

## Root design decisions applied

1. **Host-owned decisions.** The native summary contains measurements and residual
   diagnostics only, with no status, overall or tolerance. `pca-verification.json` is the
   sole final record. It binds the source and parsed-data digests, every native
   publication digest, the plan digest, the observed runtime and the implementation
   fingerprints. The runtime binding's `executablePathDigest` hashes the interpreter's
   path string, not its bytes; it is advisory path-string provenance, not a binary
   identity or authentication mechanism. Saved verification recomputes the whole record
   and requires equality, so stale, foreign or altered records fail even after ordinary
   hashes are refreshed.
2. **Certification.** The native early refusal is kept (native β, no multiplier). A host
   certification failure becomes `PCA_RECONSTRUCTION_UNCERTIFIED` at `$.channels[j]`. The
   recovery text gives uncertainty/(η × deviation) and the smallest η that would certify.
   Unmet or indeterminate requirements fail as `PCA_REQUIREMENT_NOT_MET` or
   `PCA_REQUIREMENT_INDETERMINATE` after all evidence is written. Saved verification
   reproduces the same fault, and workflows cannot consume the run.
3. **Bounds and postconditions.** Range, dimensional, offset and scaled-spread bounds and
   native postconditions are kept, as are strict readback (finite, ±1e100, integer
   indices, strict JSON) and first-order residual, gap and subspace bounds. Covariance pairs
   are assigned symmetrically from one computed value on host and native.
4. **Wording.** η is described as a sine-angle bound (loading 2-norm distance ≤ √2·η).
   Budgets are called empirical and the bounds first-order; the drift data is labelled
   synthetic; the runtime claim is exact.
5. **App-owned grammar.** The strict CSV grammar is app-owned; shared tabular parsing is
   unchanged.

## Verification performed (actual native executions)

| Case group | Outcome |
|---|---|
| Analytic baseline and variant (shared kit) | Exact eigenvalues 1024/63, 256/63, 64/63, 16/63; loadings ±½; correlation eigenvalues 4d²/Σd²; projector entries ½/0; RMS √0.3125 mV; requirements met. |
| Near-zero RMS (full retention, bounds 1e-15 and 1e-300) | `indeterminate` in components and subspace output; a 1e-9 bound is `met`. |
| O1 (bounds ±0.4 and ±3 host tolerances) | indeterminate, indeterminate, met, unmet. |
| P3 (gap 1e-10·T, η = 1e-2; bounds ideal × (1 ± 1e-6), ideal × (1 ± 1e-3)) | indeterminate, indeterminate, met, unmet, in both output modes. |
| E1, E2, E3 (declared cross ratios 1e7, 1e9, 1e10) | Accepted; host certification refusal at `$.channels[1]`; native early refusal. |
| Repeated and rank-deficient spectra | Refusals as declared; subspace K=2 accepted. |
| Synthetic drift | Accepted. A quiet channel beyond the offset limit is refused. |
| Host-only refusals (range, quotes, nan, digit separator, scaled spread) | Refused before any native launch. |
| Hostile saved evidence (21, in place) | Host-record status, tolerance and outcome edits; a foreign record; a status added to the native summary; stale reconstruction; tilted and self-consistent tilted subspaces; eigenvalue denominator; mean and declared-scale edits; projector edit; rehashed capture; readback failure and foreign BLAS; runtime change; an unmet run promoted to success; an absolute worker path, missing `-I` and a foreign interpreter in the recorded command; and edited worker bytes. Each is rejected by its intended check, with ordinary hashes refreshed; the self-consistent tilt is rejected only by the independent Jacobi spectrum. |
| Portable export (baseline and variant) | Fresh runs from disposable sources record exactly `-I -B native-worker.py <stage>`. Each was exported twice: with the shared schema export and with a confirmed `schemaxis storage` backup. The sources were then removed. Every copy passes normal saved verification through both the registry and `schemaxis verify`, and the hook reports the original path with the captured digest. The originals still verify, and reuse refuses the missing source. |
| Exported-run mutants (10) | Applied to independent exports, with every ordinary digest and the publication metadata refreshed and the recorded locations kept, then verified normally. An unmodified export verifies. The rehashed source capture, edited publication, flipped and foreign host decisions, changed interpreter path digest, three changed commands and edited worker bytes are each rejected by their intended check. |
| Saved workflow and study source lifecycle | A saved workflow verifies after its source is edited, and resuming reruns both jobs. Scheduler records forged to claim the next source bytes, while the retained capture keeps the old bytes, fail with `job input hashes differ from verified retained inputs`, and resuming starts a fresh native attempt. After the source is removed, the original and exported workflow and study verify normally, including through `schemaxis verify` and a CLI backup. |
| Exported workflow handoffs (4) | The consumer's retained capture equals the producer's recorded handoff path and digest. Each of the following, in independent exported copies, is rejected by its intended check: an edited producer publication with refreshed hashes; an edited consumer capture with refreshed hashes; forged consumer input hashes; and a forged handoff digest. |
| Earlier receipts | A run saved by the previous implementation, exported canonically, is refused because the implementation changed. |
| Fault injection (native) | Intermediate, policy, published and summary postconditions and contract checks raise structured located faults, including a missing thread cap. Readback rejects `inf`, 1e101, a float index and whitespace; strict JSON rejects NaN. |
| Workflow | A rank-2 denoise feeding a re-analysis keeps only the first two analytic eigenvalues. Unchanged input is reused; changed bytes at the same path invalidate; an unmet producer blocks its consumer. |

## Limits and pending work

- **Exact runtime only.** Any other NumPy or BLAS build is refused. The qualification
  budgets are empirical, and the a posteriori bounds are first-order engineering bounds,
  not interval proofs.
- **Accuracy scope.** Eigenvalue accuracy is relative to total variance. There is no
  measurement, sampling or statistical-significance claim; the analysis concerns the
  parsed binary64 data.
- **Practical scaling limit.** The cross-channel scaled-spread limit is
  conditioning-dependent, roughly 1e8–1e9 at η = 1e-6.
- **Portable export (focused, pending integration).** The export and source-removal
  passes above were observed with root's shared run relocation and `retainedInputs`
  support, which were still under focused shared tests. They become final only when
  root integrates that shared work and reruns the full checks. Earlier focused
  attempts recorded exported runs failing in the shared publication-metadata and
  attempt-directory checks; those failures are retained as history.
- **Cross-host scope.** Saved verification elsewhere reruns only the standard-library
  verifier. It uses binary64 arithmetic, correctly rounded `fsum` and `sqrt` and
  CPython's own `hypot`, with no other libm call, but has not been exercised across
  hosts or Python versions; a last-bit difference fails rather than accepts. Native
  qualification covers this host only; OpenBLAS kernels can differ on other processors.
- **Untested handoffs.** The Calc handoff is host-planned only; LibreOffice was not run.
  Gnuplot reads files, not artifacts.
- **Browser test.** `tests/studio/numpy.browser.test.mjs` was not executed, because
  launching a browser is outside this assignment's native authorisation. The equivalent
  host validation diagnostics were checked.
- **Pending shared work (root):**
  - regenerate `docs/generated` and the packaged Studio Help, then run the `--check`
    commands;
  - run the Studio search and browser regressions;
  - integrate the shared run relocation and retained-input support, then rerun the
    full host, Studio and release checks;
  - integrate and register a final source-bound qualification receipt.
- **Data.** Fixtures are exact constructions or synthetic; no real user capture has been
  analysed.

Reproduce with:

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_numpy -q
PYTHONPATH=src python3 tools/studio_guidance.py --app numpy --check
PYTHONPATH=src python3 tools/qualify_numpy.py --numpy /absolute/numpy-env/bin/python --output-directory fresh-evidence
```
