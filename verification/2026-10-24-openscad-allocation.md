# OpenSCAD allocation review — 24 October 2026

Scope: one bounded host-side correction to `schemaxis.openscad/1` clearance
planning. No new operation, native mapping, format or verification tolerance.

## Defect and repair

The documented minimums (0.5 mm hole-to-edge, 0.5 mm hole-to-hole, 1 mm spacer
outer-minus-bore) were compared with a bare `<` on floating-point values. A
nominal clearance of exactly the minimum was refused when decimal rounding put it
a few ulps below: spacer 4.6/3.6 (0.9999999999999996), 8.2/7.2, a hole centred at
0.95 with diameter 0.9, and a pair of 1.1 mm holes at 5 and 6.6 mm, while
neighbours such as 3.3/2.3 passed. The fault carried no measurement.

Planning now forgives only a 1e-9 mm rounding artefact (far below the 0.5 mm
feature minimum and 4e-5 mm STL tolerance). Real shortfalls (for example 0.9999
mm) still raise `INVALID_CAD_CLEARANCE` at the same locations, now with `measured`,
`required` and `units` observed fields and the measured value in the message.

## Evidence

`tests/unit/test_openscad_allocation.py` (6 tests) failed before the repair
(5 failing tests, 6 errors with subtests) and passes after. It covers boundary
spacer, edge and separation cases, genuine violations with measurements, numeric-only
generated SCAD, unchanged published fixtures and an independently constructed
exact 4.6/3.6 mm annulus accepted by the stdlib geometry verifier. With
`tests/unit/test_openscad.py`, 18 host tests pass. Verification tolerances,
receipt reading and retained legacy receipts are unchanged; previously valid
documents plan identically.

## Native and upstream scope

The official latest-release API still reports `openscad-2021.01`, the absorbed
version. No OpenSCAD runtime was available, so no native run was made and native
qualification is unchanged and not refreshed by this note. The 0.5 mm minimum-wall
spacer geometry was natively qualified in the 17 October review; a 4.6/3.6 mm
case was not natively run here. Output remains draft geometry for human review,
not strength or printer suitability certification.
