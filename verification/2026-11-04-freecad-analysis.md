# FreeCAD static-solid analysis bridge — 4 November 2026

This milestone adds `schemaxis.freecad.analysis/1`: a bounded CAD-to-linear-static
isotropic solid workflow, not completion of the FEM workbench or all FreeCAD.
The source and complete strategic family denominator remain documented in
`docs/freecad-capabilities.md` and `docs/freecad-analysis.md`.

Public native APIs are ObjectsFem analysis/material/mesh/constraint/solver
factories, GmshTools, FemToolsCcx, and native result import. The qualified target
is FreeCAD 1.1.4 with its installation-bundled Gmsh and CalculiX 2.23.
No producer FCStd proxy/history is restored; only a captured selected BREP enters
the analysis. Before restoring the generated FEM document, a closed host policy
checks types, null proxy states/classes, extensions, links and archive payloads.

Independent checks read the actual solver deck and DAT/FRD files, check the native
mesh geometry/connectivity and saved result caches, integrate tetrahedral strain
energy, compare external work, and balance forces and moments. Geometry budgets
and loads/supports use explicit units. The reported von Mises maximum is at
integration points, not the native extrapolated nodal maximum. A verified
calculation may have unmet declared response limits.

A native writer issue was detected rather than tolerated: straight T10 midsides
on circular bore edges were omitted by the analytic face-node search. The bridge
now materialises support and traction records on the selected discrete boundary
triangles, including all midside nodes. It verifies those concrete records,
including the zero corner / area-third midside constant-traction weights.

Qualification is reproducible with `tools/qualify_freecad_analysis.py` and
`tests/unit/test_freecad_analysis.py`. Final source-frozen run results are recorded
below when complete. The host controls include skewed affine tetrahedra and exact
quadratic-field strain-energy integrals; native controls include axial FL/EA,
stress, reaction and energy, both orders, refinement and pressure sign.

Native edit/re-solve/fresh-reopen, enclosure refinement and hostile persistence
checks passed in the development r6 suite. The constrained-load overlap control
explicitly prescribes nonzero end displacement while applying traction on the
same face: true reactions subtract applied traction from CalculiX total RF before
equilibrium and displacement work. Solver nodal stresses also stay inside
incident-element constitutive extrapolation envelopes; a co-forged all-zero
FRD stress field plus matching native caches is rejected. Canonical/source-frozen
receipt details follow after the final run. Contact,
large deformation, nonlinear materials, multi-material, shell/beam, thermal,
modal, transient and curved-face load workflows remain important open families.

## Final source-bound evidence

Native full suite `completion-freecad-fem-final-r2` passed all eight analysis
cases, eleven refreshed-digest attacks, two direct native edits/re-solves with
fresh reopening, original-source removal, and workflow reuse/CAD invalidation.
The final host suite passed 166 FreeCAD tests, including twelve analysis-specific
controls and cooperative expired-budget checks. The canonical development kit
passed its independent 100 N and held-out 150 N bar cases, publication integrity,
timeout and cancellation checks; its portable receipt is registered.

Source digest: `sha256:e989d8f8035624980bfaa5881281285959f8ad10f202e67a7ef381e6fe09ecac`.

The 20 × 4 × 4 mm, E=70,000 MPa, ν=0 axial bar under 100 N gave
0.001785714 mm displacement against FL/EA, and 0.08928568571601662 N·mm energy against F²L/(2EA).
The nonzero imposed-displacement case simultaneously applies traction to the
same supported end face and checks reaction subtraction and displacement work.

The wall=3 mm enclosure rim has area 384 mm²: 0.1 MPa inward pressure
produces −38.4 N. Its 12404-node coarse mesh and 24346-node refined mesh
gave maximum displacements 3.1466905611567304e-05 and 3.14878447334997e-05 mm;
relative change 0.0006649906371686327. This is a numerical response-refinement check,
not a converged stress or physical service-load certification. Both meshes passed
independent force/moment, constitutive stress-envelope, energy/work and CAD
volume-approximation checks.
