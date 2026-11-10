# Gmsh named cylindrical walls — 10 November 2026

Scope `GMSH-PRACTICAL-MECH` revision 1: a finite practical scope for first-order, serial
meshes of small single-solid mechanical and thermal parts. It adds whole analytic
cylindrical wall groups (`tetrahedral.cylinderGroups`) with an independently proven
material side, a cylinder chord-deviation measure and refinement requirement, a typed CAD
surface inventory, an empty-remainder rule, and adopted/revised STEP inputs. It does not
claim Gmsh API coverage, solver readiness, other curved-wall families, saved-mesh
import, Netgen optimisation or VTU rendering in the artifact viewer.

## Completion checklist

| Item | Reviewed result |
| --- | --- |
| registration | Same isolated process route and `schemaxis.gmsh/1`; `acceptResource` and `capturedInputSchema` hooks added for `readSTEP.file`. No framework application branches. |
| schema | `cylinderGroups` (name, axis, centre, radius, side, tolerance, areaTolerance; combined limit 12 with `faceGroups`) and refinement `boundaryMaximumChordDeviation`, declared once and projected into the authored schema. New keys are dropped from plans when unused, so existing plans are unchanged. |
| semantics | Plan-time analytic validation for primitives (stale radius/axis/centre/side, duplicates, box/sphere, empty-remainder references) located at the selector. Native selection uses typed `Cylinder` properties and a side probe on the trimmed face. |
| native-mapping | `getEntityType`, `getEntityProperties`, `getParametrizationBounds`, `getValue`, `isInside` and `occ.getMass` on Gmsh 4.15.2; no sampling-based B-spline recognition. |
| execution | Fresh-process reopen and host verification unchanged; the host additionally classifies every boundary triangle from coordinates, proves each wall facet's material side (tetrahedron-oriented unrolled area with a flat-cosine determinacy floor and agreement), unrolled area (exact `2·π·r·h` for primitives) and chord deviation. |
| discovery | Search cases for hole wall, named cylinder, shaft surface, bore wall and chord deviation; the phrases live at operation level only, so each returns the tetrahedral operation. The kit and browser tests are source qualification, not independent acceptance. |
| guidance | 14 new field records and updated operation/field text; audit: 0 pending, 0 stale. |
| help | `docs/gmsh.md` sections on named walls, inventory, chord deviation, envelope and adoption; generated reference and packaged Help regenerated at integration. |
| examples | `gmsh-named-sleeve.json` (reference-driven), `freecad-gmsh-bores.json`, four snippets, three templates, readiness cases `named-sleeve-baseline` and `named-sleeve-changed-radius`. |
| tests | `test_gmsh_cylinders.py`, `test_gmsh_cylinder_plan.py`, extended `test_gmsh_allocation.py`, `tests/studio/gmsh-cylinders.browser.test.mjs`, and `tools/qualify_gmsh_cylinders.py`. |
| qualification | Bounded native evidence is source-bound and produced at the exact frozen source; see the retained acceptance report. |
| maintenance | `upstream.json` keeps absorbed 4.15.2; scope and acceptance updated. No upstream upgrade. |

## Findings that shaped the implementation

* FreeCAD-exported bores arrive with reversed face normals, so face-orientation flags cannot
  give the material side; the worker probes either side of the wall with the solid instead.
* A tetrahedron can have all four vertices on a cylinder, so an opposite-vertex radius test
  is undecidable; the side comes from the adjacent tetrahedron's orientation and the sign
  of the unrolled area, cross-checked against the flat facet normal.
* Flat facet area can exceed the cylinder's area (thin inscribed bands), so it is never gated;
  the unrolled area is the exact oracle.
* Distance-field sizing is only a prescription: a requested 0.9 mm gave a longest wall edge
  of 1.47 mm and unequal rims, so claims use measured rim edges and deviation.
* Gmsh's mesher adds interior vertices to flat faces, so a natural inscribed-flat mesh is
  not reproducible; the ambiguity is proven with a deterministic synthetic D-shaped solid.

## Retained limits

Only typed analytic cylinders on a world axis are selectable; oblique cylinders, cones,
spheres and B-spline cylinders are refused. Local size is bounded by the unchanged work
estimate (about 0.87 mm on a 60 × 40 × 8 mm plate). Studio shows summary, names, tags,
sides and deviation through its text path; geometry is inspected in Gmsh or an external
VTU consumer. `schemaxis revision checkout/prepare` support for completed scheduled FreeCAD → Gmsh
parents comes from the separate shared prerequisite and was exercised natively on the plate
(top 2 mm removed: volume 14400−192π, bores 48π each).
