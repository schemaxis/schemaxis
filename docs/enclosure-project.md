# Parametric enclosure: CAD, drawing, mesh and product rendering

The [baseline workflow](../examples/schemaxis/enclosure-manufacturing-rendering-workflow.json)
and [design variant](../examples/schemaxis/enclosure-manufacturing-rendering-variant.json)
connect editable mechanical design to technical documentation, a portable mesh,
native structural analysis and an animated product scene. Configure FreeCAD, its GUI launcher, Gmsh's Python
interpreter and Blender before execution. Native qualification targets FreeCAD
1.1.4, Gmsh 4.15.2 and Blender 5.2.3 LTS.

```sh
python3 -m schemaxis run examples/schemaxis/enclosure-manufacturing-rendering-workflow.json --output-directory enclosure
python3 -m schemaxis verify enclosure
```

The housing is 40 × 30 × 20 mm, with a 3 mm wall and floor, four hollow mounting
bosses and a separate vented lid. Both CAD operations reference the same authored
history and parameter definitions. Their selected outputs differ; each native
FCStd retains both editable Body histories. Wall, floor, overall height and boss
height remain native parameters. The variant changes all four and carries its
own independent geometric expectations and measured drawing selections.

The workflow publishes:

- STEP, STL and editable FCStd for the housing and lid;
- a tetrahedral Gmsh mesh with named mounting-floor and lid-rim boundaries;
- an editable TechDraw page, measured width/height/wall dimensions, SVG and PDF;
- an editable native FEM analysis with its own quadratic tetrahedral mesh,
  material, supports, pressure, CalculiX deck and displacement/stress results;
- an exploded product scene with materials, editable turntable animation, three
  frame images and a static GLB at the middle frame.

The native design remains in millimetres. The direct Blender production route
declares each STL asset's source units and derives the 0.001 conversion into its
scene in metres. A shared material graph binds to both named asset roots without
requiring a mesh-processing graph. The lid's original modelling position
is translated into an exploded position above the housing. A turntable intent
derives its pivot from the combined geometry rather than an assumed origin.
GLB contains the evaluated geometry at frame 7; its declared losses include
editable CAD features, procedural history, constraints, animation, rigs and full
shader graphs. The saved native projects retain the supported editable intent.

The mesh declares a 0.3% volume budget and a 0.2% mounting-floor area budget.
The latter accommodates faceting of circular holes; the planar rim remains
subject to its stricter default. That portable Gmsh mesh is a separate handoff
from the FEM analysis's native mesh. The demonstration elasticity calculation
clamps the bottom and applies 0.1 MPa pressure to the top rim, using E=70,000 MPa
and Poisson ratio 0.3. Independent checks cover the actual nodal constraints and
loads, material units, equilibrium, constitutive stress bounds and strain
energy versus external work. The baseline rim is 384 mm², giving 38.4 N downward;
the variant rim is 325 mm², giving 32.5 N downward. These demonstration results
establish neither a stress allowance nor a safety factor. The drawing does not
specify manufacturing tolerances or certify a process.

`tools/qualify_enclosure_project.py` runs both variants and checks independent
analytic volumes, centre of mass, boundary areas, measured dimensions, physical
GLB volume, turntable pivot, nonblank frame output and motion, plus structural
resultants, reaction balance and energy. It then requires
complete reuse and proves that damaging a drawing publication reruns that branch
while preserving the verified CAD, mesh, analysis and rendering branches. The exact
adaptor source identities are recorded separately from the native results.

This is the first cross-family acceptance project in the
[strategic completion programme](adaptor-strategic-completion.md). Assembly and
CAM integration remain separate programme work until
implemented and verified. The broader FreeCAD and Blender family inventories
remain the completion denominator.
