# CalculiX 2.23 bounded elastic beam acceptance

The qualified scope is a serial linear isotropic rectangular cantilever, with
automatic quadratic C3D20R solid meshes, measured area-mean tip Uz, actual clamp
force/moment equilibrium and interior native Gauss normal stress. Named limits
can reject numerically valid solves. This is not generic FEA, root/surface peak
stress, yield/fatigue, imported-deck, MPI or persistent editor qualification.

## Upstream and private runtime provenance

Official [solver](https://www.dhondt.de/) and
[project](https://www.calculix.de/) pages identify stable 2.23. The author's
[Linux binary](https://www.dhondt.de/ccx_2.23.tar.bz2) archive SHA256 is
`35d426fed5eb164fbbaaafa20819d13d22e30bc2b9bc9c6c4ed957e9468355dd`.
It was safely extracted into ignored private evidence using tarfile `filter=data`.
Its only missing dynamic dependency was libgfortran.so.4. The actual Ubuntu
[gcc-7 archive index](https://archive.ubuntu.com/ubuntu/pool/main/g/gcc-7/)
provided `libgfortran4_7.5.0-3ubuntu1~18.04_amd64.deb`, SHA256
`f89b2473bc251ba0c8eb9479ad31d5f96019e2ea1f8be466beea3a68b11b19fc`.
It was extracted privately; a local wrapper sets its local library directory for
that process only. No system installation, global PATH or incompatible soname
substitution occurred. No native build, MPI, profiler or ParaView was needed.

The native `-v` output is `This is Version 2.23`, exit 201. A trusted local
driver accepts only that exact version/convention under shared supervision.
Each solver launcher hashes the expected generated deck immediately before
owned exec. Verification reconstructs launcher/dispatch source and command
bindings, checks integer zero completion, logs and measured native output.

## Newly run native checks

Ignored research evidence is `evidence/2026-10-10-calculix-research`. The baseline
is L = 0.4 m, width/height = 0.02 m, E = 210 GPa, nu = 0.3 and Fz = -100 N. Separate native
12×2×2,24×2×2 and 24×4×4 meshes measured area-mean Uz
-0.000758282175,-0.000759317933333 and -0.00076016395625m. The independent
Euler–Bernoulli reference is -0.000761904761904762m; fine relative error is 0.2285%.
Actual fine reaction Fz is 100.00008972 N and clamp-centre moment My is
-40.00000144N m, balancing the signed applied force/moment.

Additional exploratory native boundary fixtures covered Poisson 0/0.35,
width/height 0.5/2, slenderness 20/40 and the maximum 24×3×3 base mesh with
48×6×6 fine mesh (1728 elements, 8869 nodes). Worst fine tip theory error was
0.5201%, separate axial change 0.2915% and transverse change 0.1954%. The maximum
mesh's final solve took approximately 1.42 s locally. These sampled corners are
evidence, not proof over the continuous authored domain.

The full native qualification tool passed in
`evidence/2026-10-10-calculix-native-1`: four independent baseline/material/load/mesh
cases with literal signed deflection/reaction expectations, artifact integrity,
native timeout and cancellation, unmet serviceability retention/blocking,
recovery, altered deck plus refreshed hash rejection, changed successful
submission status rejection and a two-state common analytic force study.
Every successful attempt also independently reopened the exact retained fine
deck and reproduced its complete DAT output. Host hardening after that first
kit made malformed numeric/runtime arguments structured and explicitly made
`verify(require_result=False)` reject unmet requirements. A fresh native unmet
attempt at `evidence/2026-10-10-calculix-research/final-unmet` confirmed
`PERFORMANCE_NOT_MET`, public verification `INCOMPLETE_EXECUTION`, and internal
completion-mode verification `PERFORMANCE_NOT_MET`.

The final full tool run passed in `evidence/2026-10-10-calculix-native-final`.
Its registered `native/qualification.json` receipt has source digest
`sha256:f4d3c7f1084710b56cbc56769d963bcf6e4ff8ddd2925751d1278cf8315a2f27`.
It records four newly rerun cases, runtimes, literal assertions, integrity and
lifecycle checks; the supplemental unmet/recovery/tamper/analytic checks also
passed on that source. Earlier
exploratory boundary results are kept separately above and are not inflated into
additional source-current receipt cases. Reproduce all supplemental native checks
with `tools/qualify_calculix.py` against a fresh output directory.

Independent review made 53 malformed retained-evidence/status probes, all rejected
with structured faults. Separate DAT mutations broke force equilibrium, changed
the support moment while preserving total force, and falsified coarse-mesh
convergence; each was rejected. Review evidence is retained under
`evidence/2026-10-10-independent-review/calculix-peer-review`.
The [beam-to-workbook integration](../docs/beam-workbook.md) additionally passed
on the same source with Calc 26.8.1.1, independently read native workbook extrema,
two reused jobs and separate producer/consumer requirement failures.

## Host and acceptance boundaries

Thirteen focused host tests cover closed schemas/physical limits, SI reference
values, consistent end-face weights and centroids, maximum mesh budgets,
independent literal native Gauss-point positions, stress/sign/reaction checks,
malformed/duplicate/missing DAT rows, measured requirement margins, pre-exec
deck hash binding, bounded regular evidence, structured runtime/output failures,
internal unmet rejection, common public analytic query and one-thread resources.
The app-specific guidance audit has 21 referenced records, no pending/stale
addresses. Host conformance and structural admission passed independently of
native qualification.

Fixed numerical acceptance is 3% fine area-mean tip/beam theory, 1% each separate
refinement relative to the independent theory scale, 5% interior Sxx error scaled
by its analytical section surface stress, 1e-4 force/moment residual and 1e-6
dimension-scaled native Gauss geometry. Stress comparison is only at actual
points with x/L in[0.3,0.7]; no division by near-zero neutral-axis stress occurs.
Stable publications are editable fine deck 0, finite numeric interior CSV 1 and
measured assessment 2. An unmet assessment is retained but cannot be reused or
consumed as a successful publication.
