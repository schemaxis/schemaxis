# FreeCAD → ParaView → Blender examples

These introductory examples use `box`, `cylinder`, `cut` and `fuse`.
The adaptor now has 18 operations; see the [expanded CAD and mesh workflows](cad-and-mesh-workflows.md). It builds a real editable FreeCAD feature tree, rather than
exporting a picture of a CAD model. Every operation executes in its own FreeCAD
process. Independent designs can use the existing resource-aware workflow scheduler;
MPI and splitting a single CAD document across workers are not supported.

## Examples to open or run

- [Mounting bracket input](../examples/schemaxis/freecad-bracket.json): 100 × 70 mm
  foot, 60 mm upright, 8 mm thickness, two 10 mm foot holes and two 12 mm upright holes.
- [Flanged pipe input](../examples/schemaxis/freecad-flange.json): 70 mm flange diameter,
  8 mm flange thickness, 36/24 mm outer/inner pipe diameters, 60 mm total height,
  four 7 mm bolt holes on a 54 mm pitch circle.
- [Complete CAD-to-render workflow](../examples/schemaxis/freecad-to-blender.json):
  independent CAD branches, native ParaView STL-to-glTF conversion, then two Blender
  views of each part. Native scenes and all intermediate artifacts are retained.

These are tutorial parts, not structural or pressure-rated designs.

```sh
PYTHONPATH=src python3 -m schemaxis describe --provider freecad
PYTHONPATH=src python3 -m schemaxis schema --provider freecad
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/freecad-to-blender.json
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/freecad-to-blender.json \
  --freecad /absolute/path/to/freecadcmd \
  --paraview-root /absolute/path/to/paraview \
  --blender /absolute/path/to/blender \
  --output-directory evidence/cad-gallery
PYTHONPATH=src python3 examples/schemaxis/check_freecad_gallery.py evidence/cad-gallery
```

Use a fresh output directory, or add `--resume` to the same unchanged workflow.
`FREECAD_CMD` is the optional alternative to `--freecad`. No host-native imports or
shell startup changes are needed. A single CAD document can also be run directly
with only `--freecad` and an output directory.

## What is checked

Output artifact indices are fixed: **0 STEP**, **1 STL**, **2 FCStd**. Dimensions
are in millimetres. The FCStd keeps named primitives and their boolean dependencies;
only the final output is visible on opening. Change primitive properties in FreeCAD
and recompute to edit the native model. Changing an input JSON regenerates a new run.

A second, fresh FreeCAD process reopens and recomputes the FCStd, checks native
feature types, dimensions, placements, axes and dependencies, and independently
reads STEP and STL. CAD readback must retain a valid, positive-volume single solid,
volume, area and bounds within relative 1e-7 / absolute 1e-6 tolerance. STL must be
watertight, have volume within 0.5 percent, and bounds within the declared chordal
mesh tolerance. The linear deflection defaults to 0.1 mm (examples use 0.05 mm).
File digests bind the checked artifacts to their retained receipt. These checks do
not establish exact BREP topological identity or arbitrary CAD fidelity.

The independent example checker additionally compares CAD volumes against analytic
formulas and checks the rendered Blender mesh's signed volume and bounds. The
workflow explicitly applies a -90° X rotation after the current glTF import and
scales millimetres to metres by 0.001. This restores the source engineering axes for
this verified bridge. STL contains no intrinsic unit metadata; the CAD receipt
records mm and the authored Blender transform makes the conversion explicit.
Do not assume other imported glTF assets require this rotation or scaling.

The saved-model edit check also passed: increasing the bracket upright from 60 to
80 mm in the native FCStd propagated through all boolean dependencies and increased
volume by exactly 16,000 mm³ within numerical tolerance. The source file was not
modified. The check is retained in
[check_freecad_edit.py](../examples/schemaxis/check_freecad_edit.py).

Qualification passed 381 unit tests plus the six-operation, fourteen-artifact native
workflow and resume check. See the
[compact evidence record](../verification/2026-09-19-freecad-gallery.json).

## Current boundaries

The original examples use four operations and the ParaView glTF bridge. New examples
also support sketches, sweeps, finishing and STEP input, plus a direct Blender STL
bridge. CAD options resolve to literal values; native Python, time visits, analytic
axes, assemblies, FEM and manufacturing constraints remain outside this contract.
`schemaxis inspect` now supports solid topology inspection for edge selection.

Pure CAD jobs have no external inputs and can reuse verified attempts on resume.
STEP reader jobs capture and fingerprint their source files.
The downstream ParaView reader follows the existing conservative policy and reruns;
changed downstream artifact paths cause the associated Blender render to rerun.
Only local execution has been qualified. The [Gmsh handoff](gmsh.md) now meshes
one STEP solid with named planar faces and verifies its ParaView publication;
solver setup and broader analysis remain separate future work.
