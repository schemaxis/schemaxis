# CalculiX six-resultant rectangular members — completion review

Date: 3 November 2026. This review covers all fields of `schemaxis.calculix/1`
and its expanded, supported rectangular elastic-member product. Completion of
that product does not claim coverage of the full CalculiX application. The whole
application capability-family map is in `docs/calculix.md`.

## Scope and independent acceptance

The retained `cantileverBeam` operation now accepts axial force, biaxial transverse
forces, torque and biaxial end bending couples. Consistent quadratic end-face
shape-function/first-moment quadrature preserves all force and moment resultants.
Clamped members support superposition; pure axial `axialSlide` members allow
Poisson contraction. One solid rectangular section family remains explicit.

Every active area-mean translation and section twist is compared with independent
axial/Euler–Bernoulli/Saint-Venant theory. Every interior Sxx sample is compared
with the combined normal-stress solution; a shear-parity projection isolates
torsional shear for comparison with the independently differentiated Prandtl
stress-function series. The analytic solution does not use native outputs or
inferred solver compliance. Native von Mises uses the six actual stress components.
Tests contain separately authored literal square-section J, translation, rotation
and reaction witnesses. Native acceptance requires two independent mesh changes,
force/moment equilibrium and exact fine-deck reopening. Existing 3% response,
1% refinement, 5% scaled stress and 1e-4 equilibrium tolerances remain unchanged.

As documented, this verifies a bounded continuous domain and named test points;
it cannot establish correctness for every possible superposition. Bending local
shear fields, surface/root stress peaks, stability and material failure are not
certified. Cancelling loads retain absolute-contribution response scales.

## Completion checklist

- **intent:** six global SI resultants and two explicit compatible restraint
  models, named measured requirements and useful adjustment/recovery guidance.
- **contracts:** closed literal/authored schemas, defaults, nonfinite/type/range
  checks, small strain/translation/twist and load/restraint compatibility before
  native launch. No arbitrary native commands, deck cards or reflection.
- **physical consistency:** face resultants, section orientation/right-hand signs,
  exact Gauss membership/coordinates, normal/shear series, native equilibrium,
  separate convergence and independent literal conformance assertions.
- **faults:** invalid physical intent, numerical disagreement, native execution,
  unmet measurement and altered evidence remain distinguishable. Rejected
  measurements retain signed margins and block reuse/downstream acceptance.
- **discovery:** application and operation meanings, practical axial/torsion/end
  resultant terms, reviewed synonym/multiword/ambiguous/negative cases covering
  CLI capability, adaptor selection, Studio Add and Help.
- **guidance:** operation and every schema field reviewed; no pending or stale
  conceptual text. Meaning, units, signs, omission/defaults, support limits,
  sampled-measurement semantics and recovery are explained.
- **examples/Studio:** standalone axial, biaxial force/couple, square/wide/tall
  torsion, combined, sliding and cancellation documents; complete Studio starters
  share those physical studies and plan without native imports. The default
  console template is a valid combined study, including corrected quantity names.
- **artifacts/composition:** existing deck/CSV/assessment order and numeric-table
  workflow handoff retained. Requirements use actual native measurements;
  publication/evidence verification reconstructs intended semantics.
- **lifecycle:** isolated serial processes, bounded total deadline, cancellation,
  retained stdout/stderr/command submissions and exact saved-deck readback.
- **maintenance:** official solver-author site checked live, stable2.23 retained;
  qualification is source-bound and distinct from editorial assessment. The
  prior dated review remains historical; new evidence is recorded here.

MPI, interactive native inspection/editing/save, conversion and time-dependent
batches are explicitly unsupported in readiness metadata. The ordinary editable
native deck and fresh batch readback fulfil this product's persistence contract.
Shared generated reference/Help/index regeneration belongs to integration and
makes worker receipts stale; qualification must be refreshed after integration.

## Observed checks

Native development probes used CalculiX2.23 and passed axial tension, lateral y
bending, pure y/z couples, torque, combined loading and sliding axial compression.
The combined fine mesh measured translation approximately
(4.75397e-6,1.23541e-4,-2.85033e-4)m and twist2.20011e-4rad; literal references are
(4.76190e-6,1.23810e-4,-2.85714e-4)m and2.20181e-4rad. Pure torque twist was within
0.077% of theory; interior projected torsional shear was within1% of its stress
scale. Sliding axial compression recovered -4.761905e-6m and interior Sxx=-2.5MPa.
These observations are newly run, independently from the October10 receipt.

The final acceptance kit, host checks and admission outcomes are recorded below
once completed. The acceptance kit exercises all14 native cases, lifecycle,
missing/tampered publications, measured twist/von-Mises failures, recovery, native
shear tamper, torque reversal and changed stiffness. No MPI claim is made.

Final worker checks:18 CalculiX host tests passed, including all standalone and
Studio documents, all six resultants, cancelling loads, support compatibility,
finite extreme-stress fault handling and measurement controls. Conceptual guidance
has27 reviewed records, zero pending/stale. Admission passed82 checks with zero
failures and zero required unknowns. The release gate reported zero hits.

The complete native acceptance kit passed all14 cases and its additional semantic,
status and shear-tamper controls. Torque reversal produced exactly opposite
measured twist (+/-2.2001178979166666e-4rad); doubling E produced
1.1000589104166665e-4rad. Twist and sampled-von-Mises requirement violations both
returned PERFORMANCE_NOT_MET and blocked verify/reuse. Unsupported torque with
axialSlide returned INVALID_BEAM before creating an attempt directory. Wide/tall
rectangles passed at twist errors0.1924%/0.0671%, interior torsion stress errors
1.1164%/1.1126%, and transverse-refinement changes0.8463%/0.8480%.

Fresh14-case native conformance also passed after adding finite numeric-range
fault handling. The final metadata rounding correction is bound by a further
conformance receipt. Receipts remain local in evidence directories; integration
must regenerate and requalify shared source/Help before registering portability
claims. The adaptor's prior source-package receipt remains explicitly historical.

Production Studio discovery assertions passed adaptor selection and Add. Three
new Help assertions (axial, torsion, end resultants) correctly failed against
unchanged packaged Help; stress ambiguity, negative unsupported scope and the
contextual Help link passed. Shared reference/Help regeneration and full integrated
search rerun are assigned to integration, with no weakened assertion. The isolated
full global unit suite was deliberately stopped through its owned supervisor as
requested by integration, retaining its log and making no pass claim. The focused
host tests and complete native proof passed independently.
