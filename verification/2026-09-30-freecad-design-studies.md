# Bracketed CAD target-study verification — 2026-09-30

The FreeCAD solid route now reuses the application-independent feedback controller
for one bounded CAD length and one named scalar geometric target. It requires
explicit target units, absolute tolerance and response direction, validates both
parameter endpoints on the host, and retains verified native observations before
using a candidate to update the bracket.

The independent rounded-prism volume oracle is
`(20*10 - (4-pi)*radius^2) * height`. The 1000 ± 0.1 mm³ example accepted a height
of 5.021484375 mm and measured volume 999.986395922616 mm³ after twelve candidates.
This is first acceptance inside a declared band, not an optimisation or general
constraint-solver claim.

`tools/qualify_freecad_design_studies.py` covers increasing and decreasing controls,
a linked rectangular profile driving extrusion, explicit unbracketed/response/
iteration/parameter-limit outcomes, native invalid geometry, two analytic target
values, corrupted rejected evidence and reports, chosen CAD/value handoff to Gmsh
and Octave, workflow reuse, and blocking downstream consumers after unmet targets.

Host tests independently simulate nonlinear increasing and decreasing responses,
including convergence to sqrt(2), first-endpoint acceptance, response violation,
unbracketed targets, both limits, invalid controls and units, changed sources and
live-study rejection. A mocked clock/runner test verifies that native build and
reopen receive decreasing remaining budgets and that late verification cannot
publish a successful run.

The controller samples a declared response assumption; it cannot prove global
monotonicity or continuity. It changes one resolved scalar option and lets native
links recompute. Other resolved options remain fixed. Partial history continuation,
general multi-parameter constraints, persistent GUI search and solver/material
adequacy are outside this change.

Final host verification passed **862 tests, with 22 skips**. Native verification
used FreeCAD 1.1.3 and passed against source digest
`sha256:5eae73a317984b786379929d18bc5136f9ecda5a431b3452cb5822d3e74aff9b`.
Local retained evidence (git-ignored):

- `evidence/freecad-design-studies-20260930-03/report.json`: all target-study cases,
  analytic visits, corruption rejection and three-job CAD → Gmsh/Octave handoff;
  all three successful jobs reused on the second workflow execution.
- `evidence/freecad-selections-final-20260930-07/report.json`: semantic selection
  regression, including owned live-session object reuse and ambiguity rollback.
- `evidence/freecad-measurements-final-20260930-08/report.json`: named measurement
  regression, live rollback, public inspection and analytic cross-adaptor handoffs.
- `evidence/freecad-design-conformance-20260930-09/qualification.json`: solid-route
  conformance, native timeout and cancellation. The registered solid receipt was
  refreshed; the older assembly receipt was not requalified by these checks.

The target-study evidence directory also retains the host, native qualification
and final regression logs. HTML report contents and integrity were checked through
replay verification; rendered browser layout was not visually qualified.
