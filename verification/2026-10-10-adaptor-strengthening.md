# Adaptor strengthening and integration — 2026-10-10

Work was split among three implementation/review agents, with the architect
checking cross-adaptor behaviour, release runtimes, packaging and regression
coverage. All changes stay on `main`. Application policy remains inside its
owning adaptor; no new application-name branch or native dependency was added
to the shared host runtime.

## Delivered slices and qualification boundaries

| Adaptor | Result | Native evidence |
| --- | --- | --- |
| FFmpeg | Authored media requirements, whole-frame lossless encoding, bounded regular-file capture and native decode/probe input bindings. | Exact upstream 9.0.2 and retained 6.1.1; H.264/FFV1, timed sheets, nine nonuniform dimensions, unmet requirements and refreshed-metadata tamper rejection. [Details](2026-10-10-ffmpeg-bound-readback.md). |
| ngspice | Named sampled voltage/gain requirements, worst conditions and signed margins; unmet requirements block publication and consumers. | ngspice 47, 19 source-bound cases plus circuit requirement, finite-study and Calc handoff/reuse checks. [Details](2026-10-10-ngspice-performance.md). |
| Inkscape | Editable explicit and dependency-derived diagrams with page, clearance, routing and actual native text-fit checks. | Inkscape 1.4.4, four source-bound cases; extended layout, analytic-state, label recovery and concurrency checks. Sparse colour probes are not whole-image certification. [Details](2026-10-10-inkscape-flows.md). |
| Shotcut | Ordered frame-range timelines, native reload/render and relocatable editable project/media bundles. | Shotcut 26.9.27's MLT 7.41.0 engine, three cases with independent full-frame expectations and bundle relocation. GUI editing was not observed. [Details](2026-10-10-shotcut.json). |
| Premiere | Experimental read-only UXP sequence observation with exact tick strings, fresh bounded requests, nonce/hash checks and two matching observations. | Host tests execute the actual companion against explicit contract doubles. No installed Premiere execution, native qualification or absorbed release is claimed. [Details](2026-10-10-premiere.json). |
| CalculiX | Generated quadratic cantilevers, separate axial/transverse refinement, actual support force/moment equilibrium, beam-theory checks and measured serviceability requirements. | CalculiX 2.23, four source-current cases plus fresh deck reopening, unmet/recovery, status/deck tampering and native analytic force states. Interior sampled normal stress is not peak/root/yield certification. [Details](2026-10-10-calculix-beams.md). |
| R | Bounded additive numeric regression, independent scaled QR, actual conditioning, fresh native model reopening and named training/held-out requirements. | Exact R 4.6.1, four source-current cases; seven domain fixtures, three unmet cases, model/evidence tampering, scaled multi-predictor and signed prediction reviews, and Calc handoff/reuse. [Details](2026-10-10-r-regression.md). |
| Calc | Named cell bounds and weighted reconciliation measured independently in XLSX and reopened ODS; retained failed assessments and bounded input fingerprints. | LibreOffice 26.8.1.1, three source-current cases plus independent cached totals, explicit coefficients, invalid selections, formula/assessment tampering and blocked/reused workflows. [Details](2026-10-10-calc-requirements.json). |

Premiere was the editor named in the preceding product discussion. Its remaining
acceptance needs Windows/macOS with Premiere 26.5+ and the supplied panel. The
committed [native recipe](../tools/qualify_premiere.py) checks independently
prepared baseline/variant sequences and retained-evidence rejection. It does not
create/edit/save/export projects or certify pixels, effects or audio. Shotcut is
an additional native-tested editor slice.

## Integrated native workflow

The committed [example](../examples/schemaxis/diagram-to-edited-video.json) and
[recipe](../tools/qualify_diagram_video.py) were run using Inkscape 1.4.4,
FFmpeg 9.0.2 and Shotcut's MLT 7.41.0. Final evidence is retained under
`evidence/adaptor-growth-20261010/diagram-video-qualified/qualification.json`.

- Four successful jobs publish ten artifacts. The two diagram jobs can run
  concurrently with independent native Inkscape application IDs and profiles.
- Two 400 × 200 PNGs become six frames at 12 fps. The final five-frame video
  selects inclusive source ranges `[1,2]` followed by `[0,2]` in that exact order.
  Native receipt dimensions/rate/frame counts, the named MLT timeline and its
  exact ordered producer/range entries are checked independently.
- Resume returns all four expected successful jobs as reused.
- Changing the producer PNG fails verification with `INVALID_IMAGE`; restoring
  it verifies again.
- Requiring seven frames from the six-frame encoding produces
  `DELIVERABLE_NOT_MET`. The retained assessment identifies only the frame-count
  requirement as unmet, and the dependent edit never launches.
- Source, authored example and recipe hashes accompany the observed runtimes.
  Duration uses the declared API's default 0.002-second tolerance; decoded RGB
  error is required to be zero.

The individual native qualification receipts for FFmpeg, Inkscape, Shotcut and
ngspice are registered against current source digests. Their scope remains the
named cases and lifecycle checks, rather than general application qualification.

## Host, review and packaging evidence

After the first tranche, all 18 registered routes passed the native-free conformance kit in
`evidence/adaptor-growth-20261010/final-frozen-host-conformance`. The five selected
adaptors have complete conceptual record coverage with no pending/stale addresses:
32 FFmpeg, 86 Inkscape, 21 Shotcut, 205 ngspice and 14 Premiere reference records.
These sourced records are not claimed human-reviewed.

Independent review exercised 1,560 malformed Shotcut/circuit planner mutations
and 192 Premiere planner mutations without raw exceptions. It also checked the
Premiere public CLI/config transport, documented UXP call shapes and actual
companion JavaScript with host-only doubles. Review findings led to regular-file
fingerprints, analytic query fixes, structured retained-result/output-directory
faults and pre-transport request byte limits. Bulk review records are in
`evidence/2026-10-10-independent-review`.

The initial full-suite baseline was 1,147 tests with one existing failure and
31 skips. Its failing blanket admission test requires complete Studio guidance
for every old provider; that pre-existing backlog remains visible. The gate was
not relaxed. Another test that incorrectly required guidance to remain incomplete
was corrected to require exact coverage and reject pending/stale records.

The first tranche's frozen-source suite ran **1,213 tests: 1,181 pass, 31 skip, one failure,
zero errors**, in 227.968 seconds. The sole failure is the same baseline test,
`test_adaptor_migration.AdaptorMigrationTests.test_every_installed_route_passes_development_admission_and_host_conformance`.
Its remaining required unknowns are the older providers' guidance records; none
is introduced by the selected adaptors. The full log is
`evidence/adaptor-growth-20261010/final-frozen-host.log`. Parser/schema parity
still detects extra and missing root fields while accepting supported declaration
forms and descriptive annotations. Intentionally invalid registered fixtures must
fail both schema validation and the planner with their declared fault. Shared
input/analytic tests still exercise every route; unsupported workflows are checked
at their public entrypoint. Premiere has ten focused host tests.

At that milestone, all 65 generated reference files passed the freshness check. Twelve edited guides
and summary files contain 165 checked local links with no missing targets.
That package included the Premiere panel's manifest, HTML and JavaScript. An
isolated Python process with site packages disabled builds the 16-provider
capability catalogue, discovers all 18 routes and plans the three new adaptors
from the extracted wheel. All 1,526 packaged source/resource files match the
checkout. Wheel/source comparison and dependency metadata checks are retained
in `evidence/adaptor-growth-20261010/wheel-verification.json`.
The host still has no required third-party Python dependency; YAML remains optional.

## Second-tranche integration and independent review

The [structural workflow](../examples/schemaxis/calculix-to-calc.json) and
[native recipe](../tools/qualify_beam_workbook.py) passed with CalculiX 2.23 and
LibreOffice 26.8.1.1. Its receipt is
`evidence/adaptor-growth-20261010/beam-workbook-final/qualification.json`.
The observed area-mean tip displacement is −0.00076016395625 m, compared with the
independent Euler–Bernoulli value −0.0007619047619047619 m. Native root reactions
balance 100 N and −40 N m. Both workbook formats independently report 1,280
interior Gauss samples and Sxx extrema ±18,769,820 Pa, matching the captured CSV.
All four named workbook requirements pass. Both jobs are reused after verification.
A tighter beam limit blocks the workbook; a tighter workbook stress limit keeps
the successful beam while rejecting the consumer with both native observations.

The [regression workflow](../examples/schemaxis/r-to-calc.json) now has three
named workbook checks: residual minimum/maximum bounds and observed sum minus
prediction sum minus residual sum. The native recipe independently reads both
workbook formats' literal totals/extrema, then tests an unmet consumer and retry.
Successful retries reuse both jobs. An unmet R requirement makes two fresh failed
producer attempts and launches no workbook; an unmet workbook requirement reuses
the verified R producer and makes two fresh failed consumers. This final domain
run is retained under
`evidence/adaptor-growth-20261010/r-calc-requirements-domain-final`.
Both application source digests remained unchanged during that workflow extension.

Independent second-tranche review exercised 304 R, 272 Calc and 240 CalculiX
planner mutations without raw exceptions. Six separate exact-model native R
fixtures cover one, three and eight predictors, with/without an intercept and
predictor scales from 1e-8 to 1e8; the largest observed training residual is
1.42e-14. A separate peer review rejects 103 malformed R evidence variants and
checks a signed two-predictor model and a failed lower prediction bound.
CalculiX's peer review rejects 53 malformed/status variants, altered actual
force balance, changed support moment with unchanged total force, and falsified
coarse-mesh convergence. Earlier independent load/sign/stiffness explorations are
retained separately from the final source-bound kit. These bounded reviews do
not claim exhaustive malformed-input or scientific-domain coverage.

The selected eight adaptors now have complete sourced guidance: FFmpeg 32,
Inkscape 86, Shotcut 21, ngspice 205, Premiere 14, Calc 42, R 34 and CalculiX 21
records, with no pending/stale addresses. They are not claimed human-reviewed.
All 20 registered application routes pass native-free conformance. Seven selected
providers have source-current native receipts; Premiere remains explicitly
unqualified. All 71 generated reference files pass the freshness check.

The final frozen-source suite ran **1,249 tests: 1,217 pass, 31 skip, one failure,
zero errors**, in 215.667 seconds. The sole failure remains the baseline blanket
admission test named above: older providers still have incomplete required Studio
guidance. None of the eight selected adaptors has a required guidance unknown.
The complete transcript and compact counts/hash record are
`evidence/adaptor-growth-20261010/second-tranche-final-host.log` and
`evidence/adaptor-growth-20261010/second-tranche-final-host-summary.json`.
An independent documentation audit resolves 210 local links/anchors and plans
29 selected or related examples through the public registry/workflow paths.

The final wheel was built from a clean staging copy after an initial incremental
build exposed obsolete files in the workstation's older ignored build directory.
Every one of the clean wheel's **1,547 packaged source/resource files** matches
the current checkout. An isolated Python process with site packages disabled
builds the 18-provider catalogue, discovers 20 application routes and plans six
selected providers from their registered valid fixtures. The four Premiere UXP
assets remain packaged. There is still no required third-party host dependency.
The final wheel SHA256 is
`7b8ecbccbb7463d7b7aaaa49ca086dc28bf8c02ca944ec21b98dba9809e2baaf`;
comparison evidence is
`evidence/adaptor-growth-20261010/wheel-second-final-verification.json`.

Bulk native outputs, private runtime builds and test logs remain ignored under
`evidence/`, together with the FFmpeg and R build transcripts. No system
installation, PATH change, ParaView invocation or modification of existing Studio
state was performed.
