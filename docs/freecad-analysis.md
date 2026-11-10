# FreeCAD solid elasticity

`schemaxis.freecad.analysis/1` takes a checked CAD solid and expresses a material,
a tetrahedral mesh, displacement supports and face tractions. It publishes an
editable native FEM analysis, the actual CalculiX input and output files, and a
verified engineering summary. Use it for small-displacement linear static studies
of one homogeneous isotropic solid. Other analysis types remain programme gaps.

## Physical intent

`source` uses the same geometry boundary as drawings: a plain STEP file with an
asserted assigned unit, or one explicitly named stored shape in an FCStd file.
Declare independent expected volume, bounds and centre of mass in millimetres.
The host captures the input and extracts only the selected BREP from FCStd; it
never restores the producer's scripts or Python proxies. Parent links and
assembly placements are not reconstructed. Export positioned STEP when needed.

`material` declares `youngModulusMPa`, `poissonRatio`, `densityKgPerM3` and an
optional name. Stress units are MPa = N/mm². The solver uses mm and N; density,
when written, converts to tonne/mm³. Static elasticity does not include gravity
or inertia. Density is retained in the editable material even when the native
static writer omits its unused deck card.

`mesh.sizeMM` sets the maximum size. `order` is 1 (C3D4) or the default 2 (C3D10).
Quadratic geometry uses straight midsides, so curved CAD boundaries are
approximated by the discrete surface. `volumeTolerance` bounds the relative
mesh/CAD volume difference (default 1%, maximum 5%); refine for narrow walls and
small bores. `maxNodes` and `maxElements` bound the admitted mesh after generation.
The native process also needs an external memory/time bound.

Each support has an `id`, a geometric `face`, and `displacementMM` with X/Y/Z
components. Zero fixes a component, a number prescribes its displacement and
`null` leaves it free. The default `[0,0,0]` clamps the face. The support set must
remove rigid motion. A nonzero solver exit or nonphysical response fails.

A force load declares `kind: "force"` and a three-component `forceN`, distributed
as a constant traction over the selected discrete face. A pressure load declares
`kind: "pressure"` and `pressureMPa`: positive acts inward and negative outward.
Both select the same directional extreme planar-face vocabulary as attached
sketches (`top`, `bottom`, `left`, `right`, `front`, `back`; `position` can select
an inner extreme). Exactly one face must match; ambiguous selections fail.
These supports/loads do not accept geometric offsets. Multiple records sum.

Straight quadratic edge midsides can lie off a curved analytic CAD edge. The
native writer's geometric node search can consequently omit them. Schemaxis
materialises the reviewed supports and tractions on actual boundary triangles:
T3 constant traction weights each corner by area/3; T6 weights its three
midsides by area/3 and its corners by zero. Native face references remain editable
in the FCStd; the delivered deck is the authoritative discretised load record.
Selected discrete face area must agree with CAD within 2%.

## Verification and interpretation

A verified run establishes the following numerical and persistence facts:

- Captured CAD volume, bounds and centre agree with the independent source facts.
- Native material, solver, mesh, geometric references and displacement/traction
  settings survive a fresh process reopening. A closed whitelist permits only
  the known native FEM proxy classes with null saved state before restoration.
- The actual solver deck contains the requested material, tetrahedral cell type,
  node geometry, connectivity (including midside edge ownership), supports and
  per-node traction weights or per-element pressure faces. Arbitrary deck input,
  macro code, external includes and unsupported physical keywords are refused.
- Independently parsed DAT and FRD displacement fields agree; saved native result
  caches agree with the solver's FRD fields. Six-component nodal stress stays within the incident elements’ independently extrapolated constitutive stress envelope (rounding budget: 0.01% of the global component scale, minimum 1e−7 MPa). This permits native averaging weights without accepting an arbitrary co-forged field. Forces and moments balance. Integrating
  strain energy from displacement gradients agrees with half the external work. DAT RF is total external nodal force; true constrained reactions subtract applied nodal traction before equilibrium and prescribed-displacement work are evaluated.
- The mesh meets the declared CAD volume approximation and resource budgets.

`analysis.json` reports displacement, strain energy, force/moment residuals,
mesh volume, load areas and `maxVonMisesMPa`. The latter is calculated independently
at tetrahedral integration points from DAT displacements and the material law;
it is **not** the native extrapolated/smoothed nodal stress maximum. Reported
`maxStrain` is the largest absolute Cartesian strain component at these points.
Sharp supports and corners may have singular stresses. A mesh refinement study
and appropriate engineering interpretation are still required for a design claim.

Optional named `limits` compare `maxDisplacementMM` or `maxVonMisesMPa` with a
positive `maximum`. A calculation can verify while `limitsSatisfied` is false;
that distinction remains in the published values. Numerical verification does
not establish load realism, material suitability, support realism, convergence
or a certified design margin.

The five publications are `analysis.FCStd` (artifact 0), `Mesh.inp` (1),
`Mesh.dat` (2), `Mesh.frd` (3), and `analysis.json` (4). Retained verification reads
the captured source, so deleting the original input does not break verification.
Workflow resource admission, input invalidation, resume and value references use
the common framework. An edited analysis must be re-solved before its results can
support a changed design; changing only a cached property is rejected.

## Examples and qualification

`examples/schemaxis/freecad-enclosure-analysis-workflow.json` constructs the
parametric housing and analyses a 0.1 MPa rim pressure with its bottom face
clamped. Those assumptions represent a numerical demonstration. The chosen
support/load case is not a mounting-bolt service-load model.

Run `tools/qualify_freecad_analysis.py OUTPUT --freecad /absolute/freecadcmd`.
Controls include an axial bar with independent FL/EA, stress, reaction and energy
oracles; T4/T10 and refinement variants; pressure compression; Poisson coupling;
a deliberately unmet displacement limit; the enclosure and refinement; native
material/load edits, second solves and fresh reopening; and refreshed-digest
saved-setting/proxy/solver-field attacks.

The initial bridge uses FreeCAD 1.1.x with its installation-bundled Gmsh and
CalculiX 2.23 executables. No global preferences or launchers are changed. Missing
bundled engines produce an explicit interpreter fault. Other installations and
solver versions need qualification before claiming the same evidence.

Public API sources: [FreeCAD FEM object factories](https://freecad.github.io/SourceDoc/dc/de2/group__FEM.html),
[FreeCAD FEM source](https://github.com/FreeCAD/FreeCAD/tree/releases/FreeCAD-1-1/src/Mod/Fem),
and [CalculiX developer documentation](https://www.dhondt.de/).

Contact, nonlinear materials, large deformation, multi-material interfaces,
assemblies, beam/shell elements, curved loads, modal/buckling, thermal and dynamic
analyses remain explicit important gaps. This route adds a useful cross-family
workflow; it does not complete the whole FEM workbench or FreeCAD.
