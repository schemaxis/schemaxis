# Named Gmsh face groups

The existing Gmsh adaptor now selects whole axis-aligned planar CAD faces by
world-coordinate plane, with unique names, explicit mm tolerance, deterministic
physical tags and a nonempty remainder boundary. Native CAD bounding boxes select
faces; the independent host verifier classifies every boundary triangle from its
coordinates and measures each group's area and bounds. Selected areas agree with
CAD; a fresh native process checks physical-group membership counts. MSH names and
VTU numeric tags survive the existing conversion.

The [public Gmsh API](https://gmsh.info/doc/texinfo/) and stable 4.15.2 installation
were checked. This is not arbitrary face selection or automatic solver conditions.
The [guide](../docs/gmsh.md) describes the precise limits and editable inputs.

## Fresh evidence

- Four native kit cases pass: original 1000/2000 mm³ boxes, two selected 100 mm²
  end faces on a cube, and translated 200 mm² end faces on a 2000 mm³ box.
  All 56 missing/tampered evidence probes and both lifecycle checks pass.
- FreeCAD STEP → Gmsh → ParaView passes for 20×10×5 and 20×10×7 mm parts.
  Selected end faces measure 50 and 70 mm². ParaView reads physical tags 2–4
  and independently integrates the expected 1000 and 1400 mm³ volumes.
  Unchanged CAD/mesh jobs are reused; corrupted captured STEP is rejected.
- Empty plane selectors, selection of every face (no remainder), and multi-solid
  STEP fail natively. Host tests reject colliding names, overlapping selector
  planes, invalid axes/tolerances, nonfinite coordinates and wrong face assignments.
- The deterministic public context/source/property/execute/inspect/refine loop
  runs all four kit cases. This uses the same editable input as human authoring;
  it is not an autonomous-model evaluation.
- Nine focused unit tests pass. Full regression: **739 passed, 22 skipped
  (761 total)** in 231.004 seconds. All 50 generated references are current;
  Gmsh development admission passes. A fresh source-current receipt is registered.

Reproduce with `tools/qualify_gmsh.py --config PRIVATE --output-directory NEW`,
then record `NEW/native/qualification.json`. Bulk results are retained under
`evidence/gmsh-faces-acceptance/`; the full regression log is
`evidence/gmsh-faces-unit.log`. No native user configuration or PATH changed.
