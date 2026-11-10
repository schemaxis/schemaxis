# Gmsh primitive geometry and meshing decisions — 3 November 2026

The changed supported scope adds complete right circular cylinders, coaxial annular
sleeves (a bounded single-solid OCC cut) and complete balls, sharing the existing
solid-to-tetrahedral workflow. It adds independently verified analytic geometry,
explicit planar-cap area budgets and Delaunay/HXT plus optimisation decisions.
The capability-family map in `docs/gmsh.md` distinguishes this product scope from
Gmsh's much wider geometry, meshing and post-processing API.

## Completion checklist

| Item | Reviewed result |
| --- | --- |
| registration | Existing isolated process route and native-free registry preserved; no framework application branches or cross-adaptor imports. New primitives emit the same typed solid contract. Serial, first-order, one-volume resource bounds remain. |
| schema | Complete typed origin/centre, radius, axis, height, bore radius, algorithm, optimise and nested face areaTolerance; authored schema derives from declarations. Defaults and invalid scalar/cross-field values are checked. |
| semantics | Full sphere/cylinder only; positive axis x/y/z, mm lengths, bore leaves at least 0.001 mm wall. Analytic bounds drive preflight cell budget for every primitive. AreaTolerance is separately bounded from plane and volume tolerance. |
| native-mapping | Official Gmsh 4.15.2 manual reviewed 2026-11-03: occ.addCylinder/addSphere/cut, consuming boolean tools then synchronizing; exactly one volume required. CAD mass/bounds are compared with host analytic formulae; every mesh node satisfies analytic bounds/radii/bore. Mesh.Algorithm3D (1/10), Mesh.Optimize, ElementOrder and thread count are read back against the plan. |
| execution | Native generation and fresh-process MSH reopening remain isolated. Host checks signed cells, manifold boundary, named plane membership, primitive geometry and analytic boundary vertex membership, area and volume budgets, numeric physical tags, VTU connectivity/quality, hashes and immutable plan. Rehashed native CAD/meshing evidence is challenged separately. |
| discovery | Curated round-bar, sleeve, spherical-specimen and HXT phrases target distinct operations; solver-negative assertions cover every new operation. Domain and native API terms retain bounded scope. |
| guidance | Every changed operation and field has reviewed conceptual explanation, units, defaults, bounds, omissions and likely mistakes; structural records retain provenance. Area budget is net area, explicitly not pointwise chord/solution error; thin-annulus cancellation is documented. |
| help | Local guide explains primitives, cap policy, meshing decisions, inspection and recovery with official API links. Root integration regenerates shared reference/Help and verifies drift. |
| examples | Three editable standalone examples and matching Studio templates/Add snippets; baseline/changed dimension, axis, placement and method native cases with independent literal volumes/bounds/cap areas. Invalid wall fixture has exact INVALID_ARGUMENT expectation. |
| tests | Scoped host tests, native seven-case primitive/STEP acceptance, budget refusals and rehashed evidence tamper checks. Final shared assessment/reference/Help parity and full host/release checks run during integration. |
| qualification | Gmsh 4.15.2 is the observed native runtime; native qualification is separately source-bound and must be refreshed after shared generation. Runtime availability and documentation admission remain separate axes. |
| maintenance | upstream.json retains absorbed 4.15.2 and adds the primitive acceptance recipe and evidence. Updated editorial assessment keeps explicit whole-app gaps; no claim of exhaustive API support or solver readiness. |

## Numerical policy

Polygonal face groups retain default relative area tolerance 1e-10 with the existing
1e-8 mm² numerical allowance. Circular/annular caps can declare up to 0.02 relative
CAD/triangle area discrepancy. All triangle plane membership, manifold topology,
primitive node containment and independent volume checks remain strict and
independent. CAD primitive cap areas are checked against pi*r² or pi*(R²-r²).
STEP cap areas use native CAD readback; imported arbitrary CAD has no independent
analytic shape oracle. Area/volume tolerances measure integrated discrepancies,
not pointwise deviation or suitability for a particular finite-element problem.

The sleeve remainder contains both curved walls. Separate inner/outer wall names,
arbitrary cylinder axes, general CSG trees, standalone 1D/2D meshes, high-order,
multi-domain and MPI work remain explicitly outside this supported scope.

## Retained acceptance

`tools/qualify_gmsh_primitives.py` completed seven real-native cases (each new
primitive baseline/changed dimensions plus captured cylindrical STEP), four actual
native budget refusals (strict circular caps, tight cap area, tight volume, strict
STEP caps), and four rehashed-evidence adversaries (method, CAD volume, CAD cap
area and an inward boundary vertex perturbation with fully refreshed native
snapshots, VTU, summary and hashes). Successful runs are independently reopened and verified after restoring
each adversary. Literal expectations are analytic dimensions, not producer values.
The acceptance report and logs are retained locally under
`evidence/2026-11-03-gmsh-primitives-final/`; bulk evidence is not committed.

Final source-current native conformance passed 10 cases, 48 literal output
assertions, 140 integrity challenges, runner timeout and pre-launch cancellation.
The sanitised package receipt is recorded; shared Help regeneration during
integration intentionally makes it stale and requires root requalification.
All 31 focused Gmsh host tests pass. The complete Studio host subset passes;
curated host search passes all nine cases. Production UI search reports missing
new operation Help until shared generation; documentation admission likewise has
only the packaged Help failure. Guidance audit is clean: 77 reviewed, 16 reference
records, zero pending/stale. The actual assessment-index check reports the expected
stale generated output; root regenerates and runs its parity test. The full global
host run was stopped at root request, with its partial log retained; root runs
the integrated full suite after generation. Release gate and diff whitespace
checks pass.
