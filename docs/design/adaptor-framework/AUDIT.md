# Installed adaptor readiness audit

Snapshot: **2026-09-28**, after named Gmsh faces, Cantera thermochemistry, ngspice AC RLC circuits and a scoped circuit receipt refresh.
Reproduce with `PYTHONPATH=src python3 -m schemaxis readiness --admission --check`.

**All thirteen adaptors and all fifteen routes pass development admission and host
conformance.** All 765 declared operations have selection guidance. ParaView has
655 identifiers, including overlapping curated and generated native interfaces;
this is not a count of distinct algorithms or native-qualified operations.

Fourteen routes have source-current scoped native receipts. The latest refresh freshly
ran the ngspice route; the other thirteen native receipts remain current from
the preceding refresh after the shared release-parser change. One further route,
since moved out of this repository into a separately installed adaptor package,
had host qualification only. No failed run was recorded as success.

The structural audit itself never executes native code or certifies installation
availability. Read registered qualification separately through `adaptor context`.
See the [migration evidence](../../../verification/2026-09-28-existing-adaptor-migration.md)
[Gmsh face groups](../../../verification/2026-09-28-gmsh-face-groups.md) and
[Cantera growth evidence](../../../verification/2026-09-28-cantera-growth.md),
[ngspice growth evidence](../../../verification/2026-09-28-ngspice-growth.md) and
[the native refresh](../../../verification/2026-09-28-whole-number-releases.md).

| Document route | Model | Admission | Pass / fail / unknown / N/A | Scoped native receipt |
| --- | --- | --- | --- | --- |
| `schemaxis.aseprite/1` | node | complete | 31 / 0 / 2 / 4 | [source-current](../../../src/schemaxis/adaptors/aseprite/qualification.json) |
| `schemaxis.blender.render/1` | non-node | complete | 27 / 0 / 3 / 4 | [source-current](../../../src/schemaxis/adaptors/blender/qualification.json) |
| `schemaxis.blender/1` | node | complete | 38 / 0 / 3 / 1 | [source-current](../../../src/schemaxis/adaptors/blender/qualification.json) |
| `schemaxis.calc/1` | node | complete | 31 / 0 / 3 / 3 | [source-current](../../../src/schemaxis/adaptors/calc/qualification.json) |
| `schemaxis.cantera/1` | node | complete | 39 / 0 / 2 / 4 | [source-current](../../../src/schemaxis/adaptors/cantera/qualification.json) |
| `schemaxis.ffmpeg/1` | node | complete | 28 / 0 / 3 / 3 | [source-current](../../../src/schemaxis/adaptors/ffmpeg/qualification.json) |
| `schemaxis.freecad.assembly/1` | non-node | complete | 26 / 0 / 2 / 5 | [source-current](../../../src/schemaxis/adaptors/freecad/qualification.json) |
| `schemaxis.freecad/1` | node | complete | 47 / 0 / 3 / 1 | [source-current](../../../src/schemaxis/adaptors/freecad/qualification.json) |
| `schemaxis.gmsh/1` | node | complete | 34 / 0 / 3 / 3 | [source-current](../../../src/schemaxis/adaptors/gmsh/qualification.json) |
| `schemaxis.godot/1` | node | complete | 32 / 0 / 3 / 3 | [source-current](../../../src/schemaxis/adaptors/godot/qualification.json) |
| `schemaxis.ngspice/1` | non-node | complete | 59 / 0 / 2 / 4 | [source-current](../../../src/schemaxis/adaptors/ngspice/qualification.json) |
| `schemaxis.octave/1` | node | complete | 44 / 0 / 3 / 3 | [source-current](../../../src/schemaxis/adaptors/octave/qualification.json) |
| `schemaxis/1` | node | complete | 48 / 0 / 3 / 0 | [source-current](../../../src/schemaxis/adaptors/paraview/qualification.json) |
| `schemaxis.qgis/1` | node | complete | 39 / 0 / 3 / 2 | [source-current](../../../src/schemaxis/adaptors/qgis/qualification.json) |

## Findings and remaining scope

- ngspice adds a real non-node document provider with independently verified
  DC networks, AC RL/RLC responses, first-order RC transients, Calc handoff and
  terminal draft reuse. The latest [RLC acceptance](../../../verification/2026-09-28-ngspice-rlc.md)
  covers fifteen circuit cases, including six new inductive cases.
- The catalogue now retains 49 qualified cases, 532 corruption probes and 28
  timeout/pre-launch cancellation probes across fourteen routes.

- Cantera adds independently verified frozen thermodynamics and TP/HP equilibrium,
  analytic/reference cases, a Calc table handoff and public/terminal draft reuse.
- Gmsh now selects named disjoint planar faces with independently checked triangle
  membership and areas; arbitrary face selection and solver conditions remain out of scope.

- Gmsh proves the completed kit on a new provider: one box/STEP solid, independent
  tetrahedral verification and a native FreeCAD → Gmsh → ParaView handoff. QGIS
  adds projected polygon centroids with exact native coordinate checks.
- No required structural or development gaps remain. Non-required unknown checks
  retain their honest scope: the auditor cannot establish every native profile,
  runtime installation, data trait or semantic property merely from metadata.
- ParaView publishes installed native help with explicit provenance and reviewed
  limitations where native help is absent. The CFD selection example now specifies
  one time for host planning and explains that execution needs a real case and
  prior time inspection. No planner precondition was removed.
- Saved-scene Blender rendering uses a small committed self-contained native
  fixture with documented provenance; it remains a distinct non-node route.
- Every route records lifecycle, formats/traits/losses, inspection and authoring
  boundaries, optional features, valid/invalid examples and baseline/variant cases.
- Fresh native receipts prove their named serial fixtures only. They do not
  upgrade every generated ParaView binding, specialised reader, GPU backend, MPI
  configuration, live-editing path or licensed vendor runtime to qualified support.
- For new work, use the [development kit](../../adaptor-development.md). Extend
  shared contracts only for concrete requirements and retain independent evidence.
