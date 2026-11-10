# Elmer FEM layered solid conduction — 2026-11-04

This adds `schemaxis.elmer/1` / `steadyHeat`: a complete bounded serial workflow
for insulation stacks and uniformly heated solid slabs. Public scope excludes
fluid-flow/CFD execution and CFD-specific setup. The capability-family map in
`docs/elmer.md` separates this product workflow from Elmer's much broader thermal,
mechanical, electromagnetic, acoustic and multiphysics application. Coverage is
an editorial estimate, independent of native qualification.

## Upstream and reproducible runtime basis

Primary upstream release/tag review on 2026-11-04 found stable **26.2.1**, tagged
2026-04-29, commit `a19504ac53ec222e3355e182b08f2ff280c2203a` (annotated tag object
`38fbce9fa264cb4b6f740cc045f1e8fbb876e06e`). The full release list and tagged source
agree. GitHub's `/releases/latest` endpoint instead returns 26.2; the policy uses
the release list pattern to retain the newer published stable patch. Upstream's
tag message says the microversion updates the Zenodo author list; CMake retains
26.2, so the actual binary reports `26.2-unknown`, revision unknown for a source
archive build. Patch identity is **source provenance**, never native readback.

Downloaded official tag archive:
`https://github.com/ElmerCSC/elmerfem/archive/refs/tags/release-26.2.1.tar.gz`,
SHA-256 `2271444cabdc9ae6185df961d939359062d43b1940ac9a7463a2b8adf7e0009b`.
A fresh isolated-prefix Release build used GNU 15.2, system BLAS/LAPACK, bundled
UMFPACK, MPI/GUI disabled. The bounded build completed with about 1.2 GiB peak;
all CMake build/install output was retained in the session home log. No native
source or runtime binaries are committed. The models/solver manual URLs returned
HTTP200 during deliberate primary-source review. Normal admission remains offline.

Primary mapping sources are the tagged HeatSolve module, ModelDescription
SaveResult/LoadRestartFile, ElmerSolver execution and ResultOutputSolve sources,
plus the public models and solver manuals. Sources are linked from `docs/elmer.md`
and the delivery API bundle.

## Completion checklist

| Item | Implemented / verification scope |
| --- | --- |
| registration | Data-only registry manifest; isolated process family 26.2, supported/unsupported feature decisions, explicit source/property/workflow/composition hooks. No shared framework application branches or native host imports. |
| schema | Closed typed document with nested material/source/mesh/end/limit records; declarations and literal schema agree. Required/optional/default values, unknown fields, bool/nonfinite numbers, missing keys and exact locations are covered. Native scripts, decks, meshes and reflection are never authored. |
| semantics | Unique material names,512-cell bound, stiffness contrast, anchored temperatures, end-family cross-fields, physical nonnegative continuum kelvin including internal extrema, ordered literal limits, exported-coordinate separation and numeric scale checks run before launch. |
| native-mapping | Native202/101 mesh, bodies/materials/density-one sources, HeatSolver direct UMFPACK and fixed/natural/film ends. Outward authored flux is negated for the native load. Bandwidth optimisation is disabled; saved node/solver pairs must be identity. Full-precision native saved temperatures feed publications. |
| execution | Total deadline, owned cancellation, failed/incomplete result, all stage logs/submissions and trusted replay sources retained. Hashes and exact membership, authored/plan agreement and generated inputs are reconstructed. Fresh Elmer process reads native ASCII restart with HeatSolver Exec Solver Never and exports temperature; independent result/XML readers and expliciteight-significant-digit VTU rounding cross-check it. Verifier normalises malformed retained input/runtime to VERIFICATION_FAILED. |
| discovery | Reviewed Fourier synonym, heat-loss multiword, conductivity ambiguity and unsupported negative cases cover capability, adaptor, Add and Help surfaces. Curated terms describe solid conduction; no broad multiphysics suitability claim. |
| guidance |26 explicitly reviewed conceptual operation/field records cover meaning, SI units, defaults, all boundary choices, signs, limits, assumptions and mistakes. No pending or stale fields. |
| help | Local guide, generated operation reference and contextual Help; stable recovery for missing runtime, unavailable dependencies, unsupported family, native process failure, unanchored/ill-conditioned/export-loss models, unmet sampled criteria and verification faults. |
| examples | Seven standalone physical examples plus editable conductivity study and one-operation workflow, five Studio starters and two snippets. Eight native canonical cases include baseline/changed conductivity, series resistance, source, two films and both flux/value/film orientations. Invalid examples cover unanchored, boundary-family, type and arbitrary-code inputs. |
| tests | Focused host semantics/mapping/schema/Studio library and parser tests; canonical host/native conformance; actual Studio search cases; refreshed-hash raw/permutation/input/log/submission/replay/runtime tamper controls; public agent+terminal reuse and stale-plan rejection. Shared host/generated checks run separately. |
| qualification | Source-bound native receipt lists precisely the eight cases and observed 26.2 binary identity. Qualification, local installation availability and documentation coverage stay separate. Serial-only, no MPI or exhaustive upstream claim. |
| maintenance | Latest-stable release-list source, absorbed 26.2.1 after native acceptance, source/binary precision distinction, repair recipe and current editorial breadth/abstraction scopes. Historic assessments remain unchanged. |

## Independent expectations and actual native observations

The initial full native acceptance (`evidence/elmer-acceptance-1`) passed all eight
canonical cases with publication/authored/plan removal/corruption, prelaunch
cancellation and timeout controls. The independent literals are:

| Case | Literal basis | Expected |
| --- | --- | --- |
| baseline | `k ΔT/L`, area 1 m2 | right heat 5000 W |
| conductivity variant | halve k | right heat 2500 W |
| composite | resistance `.1/10+.1/1=.11` | right heat`10000/11`W |
| source | `300+QL²/(8k)` | sampled peak 312.5 K |
| left flux/right film | film 310 K plus slab 10 K | maximum 320 K |
| two films | resistance `.01+.02+.01=.04` | right heat 2500 W |
| left flux/right value | imposed1000W/m2 through`.2/10` | maximum 320 K |
| left film/right flux | left 390 K, slab drop 20 K | minimum 370 K |

All native nodal fields and derived midpoint fluxes also satisfy independent exact
piecewise-quadratic transfer equations. Source-corrected end/interface/global
balances use native gradients. The source example generated 50 W over area .5 m2,
with 25 W leaving each end. Native outputs, assumptions and signed margins remain
inspectable. Full-precision restart and eight-significant-digit VTU exports have explicitly different
precision promises.

Specialised acceptance rejected literal maximum 399.99999999 K against the 400 K
baseline, refreshed-digest native values/permutation/mesh/SIF/log/submission/replay/
version tampering and malformed saved authored input. Successful restoration was
verified after each adversarial probe. Public service and terminal clients reused
one durable draft: baseline heat 5000 W, edited conductivity heat 2500 W, stale plan
refused, unanchored model refused. Shared workflow resume reused all outputs and
three conductivity states were independently verified. Optional Calc handoff is
available behind `--with-calc`; it is not claimed by the default acceptance.

## Reproduction and limits

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_elmer_admission.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app elmer --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.elmer/1 --output-directory evidence/elmer-host
PYTHONPATH=src python3 tools/qualify_elmer.py --elmer /absolute/path/to/ElmerSolver --output-directory evidence/elmer-native
PYTHONPATH=src python3 -m schemaxis adaptor record evidence/elmer-native/native/qualification.json
PYTHONPATH=src python3 -m schemaxis readiness --app elmer --admission --check
node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs
```

Observed scope is one-dimensional constant-area serial solids with perfectly
contacting layers, constant isotropic conductivity and uniform source. Flux is
derived from native temperature, not a claimed recovered native nodal flux.
Sampled design limits do not certify continuum extrema, mesh convergence or all
input combinations. No transient, radiation, nonlinear/coupled/general geometry,
mechanical/electromagnetic/acoustic, native GUI editing/conversion or MPI claim.
The source-bound receipt must be refreshed when shared generated assets change
at combined integration; retained older receipts remain dated evidence.

## Final focused verification checkpoint

The owner completed 17 focused Elmer host tests, two shared Studio catalogue tests
(including every packaged starter/snippet and unfilled pointer), seven Studio
library tests, and the real generated assessment-index parity test. Actual CLI
and public agent search responses matched for all four Elmer discovery cases.
The production Studio search regression passed 518/518 cases with no skips.
Reference (169 files), assessment-index and packaged Help (1,477 topics) check
modes passed after generating in reference → assessment → Help order; admission
reported structurally complete. Upstream updates reported Elmer current with no
updates or attention items.

The final specialised native launcher passed in `evidence/elmer-acceptance-final`;
its exact observed scope includes all eight canonical cases, lifecycle/integrity
checks, eleven additional negative controls, public draft/console reuse, workflow
resume and the three-state study. A later fresh canonical receipt was generated
and registered after the final source/Help freeze. Registration preserves native
major/minor identity and redacts only installation paths in the public receipt;
full local receipts remain in ignored evidence. Root integration intentionally
regenerates shared assets and refreshes this conservative source-bound receipt.

An extra full-host-suite attempt was stopped by its tracked supervisor PID at the
integrator's request to avoid duplicating the integrator's complete suite. Its
partial log is retained, and it is not claimed as a pass. Final integrated host
and release checks belong to the root integration receipt.
