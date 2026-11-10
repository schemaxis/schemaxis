# Enclosure workflow acceptance — 4 November 2026

The [baseline and variant](../docs/enclosure-project.md) passed six connected
native stages on FreeCAD 1.1.4, Gmsh 4.15.2 and Blender 5.2.3 LTS: housing, lid,
portable named-boundary mesh, measured technical drawing, native FEM analysis and
unit-aware product presentation. This qualifies this representative workflow,
not whole-application strategic completion.

`tools/qualify_enclosure_project.py` retains the exact adaptor source identities
and independently checks the following outcomes:

| Outcome | Baseline | Parameter variant |
| --- | --- | --- |
| Housing volume, mm³ | `10128 + 60π` | `10212.5 + 52π` |
| Housing centre Z, mm | `(80472 + 414π) / volume` | `(84009.375 + 388π) / volume` |
| Lid volume, mm³ | `3(1176 − π)` | `3.5(1176 − π)` |
| Measured width / height / wall, mm | 40 / 20 / 3 | 40 / 22 / 2.5 |
| Pressure resultant Z, N | −38.4 | −32.5 |
| Maximum displacement, mm | approximately `3.14861e-5` | approximately `3.36022e-5` |
| Strain energy, N·mm | approximately `0.000524936` | approximately `0.000487877` |

Both cases passed independently checked floor/rim areas, mesh-volume budgets,
actual load/support membership, reaction force and moment balance, constitutive
stress bounds and strain energy versus work. The maximum force residual was
below `3e-7 N`; maximum moment residual was below `4e-6 N·mm`. Demonstration
material values and boundary conditions do not establish a design stress
allowance, safety factor or manufacturing tolerance.

The product stage consumes named STL assets, converts declared millimetres to
metres and applies one shared material graph. Three nonblank, changing turntable
frames passed; the selected-frame GLB's physical volume agrees with the analytic
combined part volume within the declared tessellation budget. The inferred pivot
is independently checked. Native CAD and Blender projects retain their supported
editable intent; the static GLB explicitly loses feature history, rigging,
animation and complete shader graphs. The actual render and native PDF sheet
were also inspected visually.

After successful execution, both workflows reused all six operations. Corrupting
the drawing SVG caused only the drawing operation to rebuild; CAD, portable mesh,
FEM analysis and rendering remained reusable and verified. The first full-chain
attempt exposed CalculiX's input-stem length limit in deep scheduled directories.
Passing the owned `Mesh` basename in its existing working directory repaired the
invocation without changing physical settings or verification tolerances.

Independent integrated checks also passed 179 FreeCAD host tests, 43 Blender
production host tests, eight Blender asset round-trip cases and four refreshed
scene-hash attacks against imported material roughness, an unsampled animation
key, UV coordinates and skin weights. These results are separate from older
qualification receipts and subsequent source changes.

The native qualifier's report records source digests, case outcomes and physical
readback. Shared schema/reference generation produced 178 artifacts after route
integration. Packaged Help, assessments, full host/Studio/package checks and
source-current canonical receipts remain part of the programme's later combined
acceptance epoch. New native behaviour requires its own qualification.

The [FreeCAD](../docs/freecad-capabilities.md) and
[Blender](../docs/blender-capabilities.md) family maps remain authoritative about
unfinished scope. Rich history-to-assembly correspondence, machining coverage,
further feature families and broader animation/simulation workflows remain open;
this project does not substitute a narrow denominator for strategic completion.
