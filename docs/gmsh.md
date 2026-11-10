# Gmsh: a solid to a verified tetrahedral mesh

`schemaxis.gmsh/1` meshes one box, cylinder, hollow cylinder, sphere or single-solid STEP input in an isolated Gmsh
4.15.x Python process. The host needs no Gmsh or numerical Python dependencies.
The [editable workflow](../examples/schemaxis/freecad-gmsh-paraview.json) is
FreeCAD STEP → Gmsh → ParaView inspection. This prepares a
mesh for further work; it does not assign materials, loads or solver conditions.

Install Gmsh in a separate Python environment and configure that interpreter with
`schemaxis configure` or pass `--gmsh /absolute/path/to/python`. Gmsh is GPL licensed;
see its [official distribution and licensing information](https://gmsh.info/).
The [public API and mesh format](https://gmsh.info/doc/texinfo/) define the native
calls and MSH subset used here. No GUI is launched or required.

## Editable input

Start from [the cube example](../examples/schemaxis/gmsh-minimal.json).
Declare `units: "mm"`, one primitive (`box`, `cylinder`, `hollowCylinder`, `sphere`) or `readSTEP` node, and one `tetrahedral` node whose
`inputs.input` references the solid. `output` selects the mesh node.

- `box`: `size` is three positive extents; `origin` defaults to [0,0,0].
- `readSTEP`: `file` is an absolute local `.step` or `.stp` path, at most 16 MiB.
  The OCC importer normalises STEP length units to millimetres. Exactly one solid
  is required; source feature history and labels are not imported as group names.
- `tetrahedral`: `size` is the target edge length in mm (default 3).
  `volumeName` and `boundaryName` default to `domain` and `boundary`; they must be
  distinct ASCII names starting with a letter. The volume group contains the whole solid; the boundary group contains faces
  left after optional `faceGroups` selection (the whole exterior by default).
- `faceGroups`: up to twelve objects with unique `name`, `axis` (`x`, `y`, `z`),
  `coordinate` in world mm and optional `tolerance` (default 1e-6 mm, range
  1e-6–1e-3). Each selects entire CAD faces whose bounding boxes lie on the plane.
  Empty or overlapping selections fail; at least one remainder face is required unless
  [cylinder groups](#named-cylindrical-walls) name the rest of the boundary.
  Tags are 3, 4, … in declared order; tag 2 always means remainder.
  See [editable face groups](../examples/schemaxis/gmsh-face-groups.json) and the
  [FreeCAD face-group workflow](../examples/schemaxis/freecad-gmsh-faces-paraview.json).
  `volumeTolerance` is the maximum relative volume discrepancy from CAD (default
  0.01, maximum 0.02). Refine the mesh when curved boundaries exceed it.

The mesher uses first-order serial tetrahedra. A preflight bounding-box estimate
limits requested work; actual output is capped at 50,000 nodes and 200,000 cells.
These limits and process timeouts bound this workflow, not arbitrary CAD memory
use. Tiny elements, invalid CAD, disconnected solids and unsupported formats fail.

## Publications and meaning

The ordered artifacts are:

1. `result.msh`, kind `mesh`: ASCII MSH 2.2 with named physical volume and boundary.
2. `volume.vtu`, kind `geometry`: tetrahedra, with per-cell numeric `physicalTag`.
3. `boundary.vtu`, kind `geometry`: triangles, with per-cell numeric `physicalTag`.
4. `mesh-summary.json`, kind `text`: names/tag mapping, mm units, counts, bounds,
   cell volumes, CAD volume, relative error and conversion losses.
   `boundaryGroups` additionally reports each surface area in mm², bounds and
   triangle count. A face name does not apply a load or constraint.

Keep the summary with either VTU: names and units are not encoded in those files.
Linear meshing approximates curves and loses CAD feature history. The VTU exporter
preserves selected nodes, connectivity and group IDs exactly; it is a deliberately
bounded conversion, not an arbitrary MSH converter. MSH 2.2 is chosen to make its
linear subset independently auditable without a host dependency.

## Inspection, verification and recovery

**Inspecting a result.** Gmsh nodes do not support the CLI `inspect` command (it refuses
with `UNSUPPORTED_INSPECTION`); there is no native inspector. Inspection means reading
the saved summary JSON: names, tags, units, volumes, areas, quality and (for named walls)
`cylinderChecks` and `cadSurfaces` are all in `mesh-summary.json`, and a refinement study
adds `study-summary.json`. For a standalone run these sit in the output directory; in a
workflow they sit in the operation's attempt directory (for example
`results/run/mesh/batch-0/attempt-0001/`). Read them with any JSON tool:

```sh
python3 -m json.tool results/run/mesh/batch-0/attempt-0001/mesh-summary.json
python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['cylinderChecks'])" results/run/mesh/batch-0/attempt-0001/mesh-summary.json
```

**`verify` versus `run`.** `schemaxis verify DIRECTORY` is offline retained-evidence
verification: it re-parses the retained MSH/VTU, repeats every independent host check and
checks hashes and the authored/plan agreement. It needs no Gmsh path and does not start
Gmsh. The fresh native MSH reopen happens during `run` and its readback is retained as
`reopened.json`, which `verify` re-checks. Use `--backend native` (with a configured or
`--gmsh` Gmsh) to execute locally instead of the default managed container backend.

A fresh Gmsh process reopens MSH and checks counts, names, bounds and cell volumes.
An independent host parser measures signed tetrahedral volumes, rejects inverted
or degenerate elements, checks full boundary coverage and closed manifold edges,
and compares the result against CAD volume and bounds. Every triangle is
independently classified against the authored planes, selected planar areas are
compared to CAD, and native physical-group membership counts are read back.
No unstable CAD face number is used in authored input. VTU is parsed back and
compared with the selected MSH coordinates, connectivity and physical tags.
Published files, native evidence, retained STEP and authored/plan agreement are
checked on every verification. Original STEP files need not remain for offline
verification; their current digests still control workflow reuse.

Use shared source/property authoring to change dimensions or mesh size, then plan
and execute a fresh revision. The text panel exposes summary evidence; the artifact
viewer does not render VTU geometry, so open `result.msh` in Gmsh or the VTU files in
any VTK-capable tool such as meshio or ParaView. No native Gmsh live editor, arbitrary
scripts, high-order elements, MPI, arbitrary-direction or non-cylindrical curved
selectors or general mesh importer is provided. Positive cells and volume agreement are useful checks, not a proof that
a mesh is adequate for a particular simulation.

Native-stage refusals keep distinct stable codes, each with a location and recovery
text: `INTERPRETER_NOT_FOUND` (no absolute interpreter configured),
`NATIVE_UNAVAILABLE` (that Python cannot import `gmsh`), `UNSUPPORTED_RUNTIME`
(Gmsh is not 4.15.x), `UNSUPPORTED_RESOURCE` (the STEP does not hold exactly one
solid), `INVALID_RESOURCE` (OpenCASCADE reports no positive volume),
`INVALID_SELECTION` (an empty or overlapping face selector, or no remainder face)
and `RESOURCE_LIMIT` (the work estimate or actual mesh exceeds its bound; increase
the size or mesh a smaller solid). Anything else is `NATIVE_EXECUTION_FAILED`
with the exception type; the host trusts only these allow-listed codes from the
worker's fault file. Native failures retain build/reopen logs and a failed
`result.json`, never a published mesh. A volume-tolerance failure requires
refinement or investigation of the CAD. Do not weaken verification to accept it.

Run `tools/qualify_gmsh.py` with the private runtime configuration for analytic
baseline/variant meshes, the CAD handoff and public authoring verification. The
kit also challenges every publication, authored/plan evidence and lifecycle.

## Native acceptance

The named-wall scope is accepted by `tools/qualify_gmsh_cylinders.py` (see
[Named cylindrical walls](#named-cylindrical-walls)); the paragraphs below record the
earlier box, cap and STEP acceptance.

Qualified on Gmsh 4.15.2 with analytic 10×10×10 and 20×10×10 mm boxes.
The FreeCAD handoff checks 20×10×5 and 20×10×7 mm parts; ParaView independently
integrates their volumes and reads both physical tag arrays. Multi-solid STEP
is rejected; changing captured STEP bytes invalidates verification. A public
context/source/property loop inspects the same summary used by a human.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/gmsh-minimal.json \
  --backend native --gmsh /absolute/path/to/gmsh-python --output-directory new-mesh
PYTHONPATH=src python3 -m schemaxis verify new-mesh
PYTHONPATH=src python3 tools/qualify_gmsh.py \
  --config /path/to/private-config.json --output-directory new-acceptance
```

See [acceptance evidence](../verification/2026-09-28-gmsh-growth.md) for scope,
versions and reproducible checks. No native GUI inspection or solver readiness is
implied by these serial fixtures.

## Meshing intent near named boundaries

Use [the boundary-sizing example](../examples/schemaxis/gmsh-boundary-sizing.json)
to prescribe finer resolution near a declared face group:

```json
"nearBoundaries": [
  {"boundary": "fixed", "size": 0.75, "distance": 2}
]
```

These are `tetrahedral` options. All lengths are millimetres. `boundary` selects an
existing `faceGroups` name or the remainder `boundaryName`; native entity numbers
are resolved inside Gmsh. `size` must not exceed the global target size. The target
interpolates from the local size at the named surface to the global size at the
specified distance. Multiple rules combine by their minimum size. Distances use
Gmsh's sampled surface-distance field, so this is a sizing prescription rather
than an exact distance or achieved-edge guarantee. Native field types, settings,
surface lists and global bounds are read back and verified.

The work estimate conservatively uses the smallest prescribed size throughout the
bounding box. This can reject a locally refined request that would fit in practice;
it avoids promising an unbounded native meshing job. Named face selection remains
the existing bounded planar subset, including an explicit remainder.

## Independent quality assessment

Every successful mesh now publishes `quality` in `mesh-summary.json`:

- `meanRatio`, `minimumEdgeLength`, `maximumEdgeLength` and `volume` distributions
  expose minimum, p05, median, p95, maximum and mean. Percentiles interpolate
  linearly between sorted observations.
- `boundaries` exposes distributions of each boundary triangle's maximum edge
  length, identified by the declared name and physical tag.
- A ten-bin mean-ratio histogram and up to twenty `worstCells` expose spatial
  locations, quality, size and volume. `cellIndex` is the zero-based tetrahedron
  order in `volume.vtu`; it is not a persistent CAD identity.
- `volume.vtu` carries `meanRatio`, `maximumEdgeLength` and `volume` cell arrays
  for colouring and locating poor elements. Verification recomputes every array
  from retained MSH coordinates. Global edge extrema also agree with native Gmsh
  measurements before and after reopening.

For a positive linear tetrahedron, the dimensionless mean ratio is
`12 * (3 * volume)^(2/3) / sum(squared edge lengths)`. A regular tetrahedron scores
one; flattening drives it towards zero. The formula and analytic tests are
independent of Gmsh's quality implementation. See the
[reference implementation's documented measure 3](https://people.math.sc.edu/Burkardt/cpp_src/tet_mesh_quality/tet_mesh_quality.html).
The diagnostic count below 0.2 is labelled explicitly and does not establish a
universal acceptance threshold. These shape metrics do not certify discretisation
error, physics, boundary conditions or solver convergence.

## Bounded refinement under explicit requirements

The [global refinement example](../examples/schemaxis/gmsh-refinement.json) adds a
top-level policy:

```json
"refinement": {
  "maxIterations": 4,
  "reductionFactor": 0.7,
  "minimumSize": 1,
  "maxTetrahedra": 20000,
  "requirements": {
    "maximumEdgeLength": 3,
    "minimumMeanRatio": 0.1
  }
}
```

The first candidate uses the authored global size. Each independently verified
candidate is assessed against every requirement. The study accepts the first
passing candidate. Otherwise it multiplies size by `reductionFactor`, with one
last candidate at `minimumSize` if necessary. Boundary sizes scale with global
size, with a 0.001 mm floor; transition distances stay fixed. A smaller target
size is **not** assumed to improve shape quality.

Available requirements, by key, are `maximumEdgeLength` (mm), `minimumMeanRatio`,
`maximumVolumeRelativeError` (relative CAD-volume discrepancy, at most the native
`volumeTolerance` ceiling of 0.02),
`boundaryMaximumEdgeLength: [{"boundary":"fixed","maximum":0.9}]` and
`boundaryMaximumChordDeviation: [{"boundary":"bore","maximum":0.05}]`.
See [boundary refinement](../examples/schemaxis/gmsh-boundary-refinement.json).
All comparisons are inclusive. Requirements must be nonempty and named boundary
requirements must refer to existing, distinct groups.

The study stops on acceptance, iteration limit, minimum size, exceeded cell
acceptance budget or the native work estimate. `maxIterations` is bounded to
1–20. `maxTetrahedra` controls acceptance and stops further refinement when
exceeded; an attempted candidate may exceed that requested budget, but remains
subject to the separate native hard limit. The timeout covers the whole study,
including final verification. Native invalidity, failed readback and cancellation
are execution faults, not ordinary rejected candidates. In particular, the native
`volumeTolerance` remains a hard verification limit; a stricter study volume
requirement can distinguish valid candidates inside that limit.

Each `attempt-00000` directory retains its native evidence. `study-summary.json`
and `study.html` explain the measured checks, decisions and stopping reason.
Verification reconstructs every proposal, rechecks every attempted mesh (including
rejected ones), re-evaluates decisions and verifies the rendered report. Changing
CAD source bytes between attempts fails the study. Offline verification uses
retained source bytes, as before.

A successful study exports the chosen candidate's four ordinary artifacts in
unchanged order, followed by the JSON and HTML study reports. Cross-adaptor value
references can therefore select artifact 3 and a quality pointer such as
`/quality/maximumEdgeLength/maximum`. A study with unmet requirements raises
`STUDY_REQUIREMENTS_NOT_MET`, retains an auditable report and exports no candidate
mesh. A workflow consumer cannot proceed with it. The CLI `verify` reports such a study
as unmet; the Python call `from schemaxis.adaptors.gmsh import refinement;
refinement.verify(directory, require_acceptance=False)` verifies a completed unmet study
without claiming that its mesh requirements passed. `plan` gives no work-estimate warning
for refinement, so an unreachable requirement shows up only after the run, as
`STUDY_REQUIREMENTS_NOT_MET` with its stop reason.

Unchanged successful workflow studies support normal scheduler reuse. A failed
study requires a fresh attempt; this does not add in-place continuation of partial
studies or a claim that the selected candidate is globally optimal.

The shared expressions, document references and analytics also apply to these
new controls. The [analytic refinement example](../examples/schemaxis/gmsh-analytic-refinement.json)
evaluates an expression over referenced edge limits of 4.5 and 3 mm. Each analytic
visit runs its own bounded refinement and retains a separate decision history.
This separates an outer design study from the inner mesh-acceptance procedure.

See the [new native acceptance record](../verification/2026-09-30-gmsh-studies.md)
for quality, feedback, handoff and failure checks. Reproduce with
`tools/qualify_gmsh_studies.py --config /path/to/private-config.json --output-directory new-study-acceptance`.

## Curved primitives and discretisation

`cylinder`, `hollowCylinder` and `sphere` construct complete solids without a CAD
file. They share the existing `solid` input contract, named boundaries, local
sizing, quality measurement and bounded refinement. Every authored length is mm.

- `cylinder`: `origin` is the starting cap centre (default [0,0,0]), `axis` is a
  positive world direction (`x`, `y`, `z`; default `z`), `radius` defaults to 5 mm
  and `height` to 10 mm. This is a full right circular cylinder.
- `hollowCylinder`: the same placement and dimensions, plus `innerRadius`
  (default 3 mm). It subtracts a coaxial through cylinder and requires exactly
  one annular solid. The wall `radius-innerRadius` must be at least 0.001 mm.
  This is a reusable tube/sleeve decision, not arbitrary native boolean scripting.
- `sphere`: `centre` defaults to [0,0,0] and `radius` to 5 mm. It creates a full
  ball, without polar cuts or shell thickness. It has no planar face groups.

The host computes analytic primitive volume and bounds without Gmsh and compares
these with OpenCASCADE readback. It checks every mesh node against the analytic
bounds, spherical/cylindrical radius and, for sleeves, the bore radius. Box bounds
remain exact; sampled curved mesh extrema can lie inside the analytic extrema.
Every boundary triangle must have all vertices on one analytic cap, cylinder wall, sphere or box face; a dent inside the envelope is refused. Straight chord interiors remain the declared approximation. Cap CAD areas are also compared to analytic disk or annulus areas.

A planar circular cap has a curved perimeter. Its linear mesh cannot have the
exact CAD area, even though every triangle lies on the plane. `faceGroups` now
accepts `areaTolerance`: the maximum relative difference
`abs(meshArea-CADArea)/CADArea`, from 1e-10 (the unchanged strict default) to 0.02.
An absolute 1e-8 mm² allowance handles numerical roundoff. Keep the strict default
for polygon faces. Choose an explicit area-loss budget for circular or annular
caps, then refine `size` if it fails. The budget applies equally to primitive and
STEP caps; it does not relax plane membership, topology, node containment or
`volumeTolerance`. It measures net selected area, not Hausdorff distance, local
chord deviation or simulation accuracy. A thin annulus can have compensating
inner/outer area errors; inspect resolution as well as its net area.

`boundaryAreaChecks` in `mesh-summary.json` publishes each selected group's CAD
area and measured mesh area in mm², relative error, authored relative tolerance and the separate `absoluteTolerance` numerical floor (1e-8 mm²).
The remainder boundary still holds all unselected surfaces. Name a tube's inner
and outer walls with [`cylinderGroups`](#named-cylindrical-walls). Arbitrary
directions, general CSG trees and standalone surface meshing remain outside this
route.

Start with [a translated cylinder](../examples/schemaxis/gmsh-cylinder.json),
[an annular sleeve](../examples/schemaxis/gmsh-hollow-cylinder.json) or
[a ball](../examples/schemaxis/gmsh-sphere.json). Matching editable Studio templates
and Add snippets are supplied. The cap examples explicitly accept at most 2%
area loss and the meshes at most 2% volume error; these are demonstration budgets,
not universal engineering tolerances.

## Meshing decisions

`tetrahedral.algorithm` selects `delaunay` (default, `Mesh.Algorithm3D=1`) or `hxt`
(`=10`); both generate linear tetrahedra under the same resource and verification
contracts. `optimise` defaults to true and sets `Mesh.Optimize`; false disables
that option. Algorithm-internal improvement can still occur, especially in HXT.
The native worker records readback of algorithm, optimisation, order and single
thread, and host verification compares it to the plan. Select based on observed
quality and cost; neither choice guarantees a maximum edge length or mean ratio.
See the [official mesh options](https://gmsh.info/doc/texinfo/#Mesh-options).

Run `tools/qualify_gmsh_primitives.py --gmsh /absolute/path/to/python
--output-directory new-primitive-acceptance` for analytic baseline and changed
axis/radius/height cases, curved STEP cap regression, strict-budget refusals and
integrity challenges. Shared native conformance additionally checks source-bound
receipts, every publication and lifecycle cancellation/timeouts.

## Named cylindrical walls

`tetrahedral.cylinderGroups` names the cylindrical walls of a single solid so loads,
constraints or heat flux can later be applied to a bore or a shaft **by name**. Start
from [the fully named sleeve](../examples/schemaxis/gmsh-named-sleeve.json): two caps
(`start`, `end`), `bore` and `outer`; the remainder group is empty and absent. A
[FreeCAD plate with two bores](../examples/schemaxis/freecad-gmsh-bores.json) shows an
imported STEP with `fixedBore`, `loadBore`, a planar `base` and local sizing near one bore.

```json
"faceGroups": [{"name": "start", "axis": "x", "coordinate": 1, "areaTolerance": 0.02}],
"cylinderGroups": [
  {"name": "bore", "axis": "x", "centre": [1, 2, 3], "radius": 2, "side": "inner"},
  {"name": "outer", "axis": "x", "centre": [1, 2, 3], "radius": 4, "side": "outer"}
]
```

Each entry has a unique `name`, a world `axis` (`x`, `y`, `z`), `centre` (any point on the
axis, in mm; the component along `axis` is ignored, so a primitive's `origin` can be
pasted or referenced), `radius` (mm), `side` and optional `tolerance` (default 1e-6 mm,
1e-6 to 1e-3) and `areaTolerance` (default 1e-9, up to 0.02).
`side: "outer"` means material lies inside the radius (shaft, sleeve exterior);
`side: "inner"` means material lies outside it (the wall of a bore).

- **Tags and caps.** Tags are 1 volume, 2 remainder, `faceGroups` from 3, then
  `cylinderGroups` in declared order. Documents without `cylinderGroups` keep exactly
  their previous tags, plans, summaries and refusals. `faceGroups` plus `cylinderGroups`
  together may not exceed 12, which preserves the 14-name MSH limit and the 13-entry
  sizing limits.
- **Empty remainder.** With at least one cylinder group, planar and cylinder groups may
  name the whole boundary. Tag 2 is then reserved but absent from the MSH and summary,
  and a sizing rule or requirement that names the empty remainder is refused with
  `INVALID_SELECTION` (at plan time for primitives, natively for STEP). Without cylinder
  groups a nonempty remainder is still required.
- **One cylinder, one side.** A cylinder met by material on both sides (a pin and a hole
  of equal radius on one axis) cannot be named per side: two groups on the same cylinder
  are refused at planning, and the native selector refuses a cylinder whose opposite-side
  wall would stay in the remainder, because the independent classifier cannot tell them
  apart.
- **Native selection.** The worker reads typed analytic geometry from OpenCASCADE
  (`getEntityType` and `getEntityProperties`) and selects every **whole** face that is a
  `Cylinder` with a parallel axis (either direction), the authored axis line and radius
  within `tolerance`, and the authored side. The side is found by classifying two probe
  points a small step either side of the wall with the solid itself, taken at a point
  that lies on the trimmed face, because face orientation flags differ between CAD
  sources (FreeCAD bores arrive with reversed normals). A wall whose side cannot be
  decided is listed as not selectable and refused with its own message. Arbitrary partial faces, cones, spheres,
  B-spline cylinders and oblique cylinders are **not** selectable and are refused with
  actionable candidates, never approximated.
- **Planning for primitives.** A `cylinder` or `hollowCylinder` selector is checked
  analytically before any native start. A stale radius, axis, centre or side, a duplicate
  selector, or any cylinder group on a box or sphere is `INVALID_SELECTION` at
  `<mesh>.options.cylinderGroups[i]`. Reference one value with `$document` from both the
  solid and the selector so a dimension edit keeps them together; a changed literal is
  refused rather than silently selecting nothing.
- **Independent proof.** The host never trusts native face numbers. It classifies every
  boundary triangle from coordinates in both directions: a triangle whose three vertices
  lie on an authored plane belongs to that plane group; otherwise one whose vertices lie
  on a cylinder at its radius and span a nonzero axial range is that wall; anything else
  is remainder. Each physical tag must match, so a missed or wrongly included face fails.
  An axis-normal rim triangle with all vertices on the circle is a cap triangle, never a
  wall; "axis-normal" means an axial extent no larger than the selector's `tolerance`, so
  at the maximum tolerance (1e-3 mm) a wall facet shorter than that axially is treated as
  remainder and refused. The default tolerance never matters at realistic sizes. A flat face genuinely inscribed in a selected cylinder (for example a D-shaft
  flat meshed with one element across) is geometrically indistinguishable from a coarse
  wall facet and is **refused**, with the recovery to refine the mesh there. Each wall
  triangle must have vertices within `tolerance` of the radius, an unwrapped angular
  range below π (so the axis lies outside its projection), and the authored material
  side from its adjacent tetrahedron: the facet is oriented so its normal points away
  from that tetrahedron, and the sign of the unrolled `(r·θ, axial)` area is the side
  (positive `outer`, negative `inner`). The flat facet's own outward normal must give
  the same sign through its cosine with the radial direction at the centroid, and that
  cosine must exceed 1e-6 in magnitude; a nearly tangent sliver, or a facet whose two
  forms disagree, is **refused** as indeterminate rather than guessed. The proof never
  compares the radius of a tetrahedron's fourth vertex, which is undecidable when every
  vertex of the tetrahedron lies on the cylinder.
- **Area.** The sum of unrolled triangle areas equals the exact wall area for a primitive
  (`2·π·r·h`, checked to 1e-9) and the CAD wall area for STEP faces with axis-normal
  rims; `areaTolerance` bounds the difference for other STEP rims. This identity proves
  single, fold-free coverage of the wall. The *flat* facet area is not bounded by the
  cylinder's area in either direction (a thin band of inscribed facets can exceed it),
  so it is never gated; deviation, not area, measures how far the facets sit from the
  curve. Planar groups with circular mouths (a plate face with bores) need an explicit
  `areaTolerance` for the inscribed holes, as circular caps do.

`mesh-summary.json` gains `cylinderChecks`, one entry per group with `side`, `triangles`,
`cadArea`, `unrolledArea`, `areaRelativeError`, `maximumVertexResidual`,
`maximumChordDeviation`, `chordSegmentsEquivalent`, `maximumAngularSpan` and `axialRange`.
Name, tag and group-area information stay in `groups` and `boundaryGroups`.

### CAD surface inventory

Every run publishes `cadSurfaces` in `mesh-summary.json`: a bounded, aggregated list of
the solid's planes (`axis` and `coordinate`) and cylinders (`axis`, `centre`, `radius`,
`side`, `faces`, `area`, `selectable`), plus other surface types by count and area.
It contains no native entity numbers and is native readback for authoring only, not
independent proof. For an unfamiliar STEP, run once with no groups, read the inventory
in the text panel, then author selectors from it. An unmatched selector fault also lists
the selectable candidates (bounded so the fault stays within its 2000-character record).

### Chord deviation and refinement

**Chord deviation** of a wall is the largest gap between the true cylinder and its flat
facets: for each triangle, the radius minus the nearest approach of the triangle's
projection (perpendicular to the axis) to the axis, maximised over the wall, in mm. For a
regular N-sided prism it is `r·(1-cos(π/N))`; `chordSegmentsEquivalent` reports the N that
matches the measured value. It is measured from the mesh coordinates alone, is distinct
from `maximumVertexResidual` (vertices sit on the wall), and cannot cancel between an
inner and an outer wall as net volume or area can.

Refinement accepts `boundaryMaximumChordDeviation: [{"boundary": "loadBore", "maximum": 0.08}]`
(cylinder group names only). The existing coarse-to-fine loop applies unchanged: the
first candidate whose every requirement passes is selected, otherwise the study ends
with `STUDY_REQUIREMENTS_NOT_MET` and exports no mesh. Deviation falls roughly with the
square of the edge length, and a smaller size does not guarantee better cell shape.

### Useful size envelope

The existing work estimate charges the smallest local size across the whole bounding
box, so the smallest admissible local size for a 60 × 40 × 8 mm plate is about 0.87 mm
and an Ø8 bore resolved with at least 16 angular segments is only practical on small
parts (a bore of about 1/15 of the longest dimension, so up to roughly 100 mm across).
**The 16-segment criterion used for acceptance** is: each rim loop of the sized bore has at
least 16 edges counted directly from the mesh, and the measured chord deviation is at most
`r·(1−cos(π/16))`, 0.0769 mm for r = 4 (that deviation implies every wall edge spans
22.5° or less). `chordSegmentsEquivalent` is reported alongside but is not the criterion:
the widest wall edge is usually a diagonal, so it understates the rim count. With local
size 0.9 mm the example bore had 28 and 20 rim edges on its two ends (chord-equivalent
19.2 segments) and a longest wall edge of 1.47 mm, against 9 and 9 rim edges (8.3
equivalent, deviation 0.28 mm, 7% of the radius) for the untreated bore at the global
size 3 mm. Local sizing is a target: the achieved edge length exceeded the request by
about 1.6 times and the far rim was coarser than the near rim, because the distance
field is sampled at a fixed 20 points per surface. Inspect `quality.boundaries` and
`cylinderChecks` rather than assuming exact spacing. A named bore meant to carry a
load or constraint needs its own sizing rule or a deviation requirement, because
naming alone does not refine it. The caps are unchanged (50,000 nodes, 200,000 cells).
An unattainable deviation limit ends a refinement study with `STUDY_REQUIREMENTS_NOT_MET`
and the stop reason `work_estimate_limit`; no coarser mesh is substituted.

### Adopted STEP inputs

`readSTEP.file` accepts a pinned, digest-checked snapshot, so an edited STEP can be
adopted and meshed in a child workflow while the parent stays untouched:

```sh
python3 -m schemaxis input adopt edits/part.step snapshots/part-001
# put the printed {"$resource": ...} reference in the mesh operation's readSTEP file
python3 -m schemaxis run workflow.json --backend native --output-directory results/child
python3 -m schemaxis verify results/child
```

Changed snapshot bytes, a removed snapshot or a corrupted mesh fail verification.

### Revising a STEP produced by an earlier step

For a completed FreeCAD → Gmsh workflow, the shared revision commands check out the
STEP that the mesh operation consumed, adopt your edited copy and rerun the downstream
work as a child, leaving the parent untouched:

```sh
python3 -m schemaxis revision checkout results/parent --consumer mesh \
  --pointer /nodes/0/options/file --destination edits/work.step
# open edits/work.step in FreeCAD, edit and save it
python3 -m schemaxis revision prepare results/parent --consumer mesh \
  --pointer /nodes/0/options/file --replacement edits/edited.step \
  --snapshot snapshots/edit-001 --reason "top removed" --output revisions/edit-001.json
python3 -m schemaxis run revisions/edit-001.json --backend native --output-directory results/edit-001
python3 -m schemaxis verify results/edit-001
```

The child keeps your named selectors literally, so an edit that changes a selected
radius or axis is refused at the selector; choose edits that keep the selected
cylinders and planes, or author a new document. See the user guide's revision section
for the parent limits (completed scheduled parents with one native visit per operation).
Pass the document version `schemaxis.gmsh/1` to `adaptor context`; the bare provider name
`gmsh` is refused with `UNSUPPORTED_VERSION`.
Re-run `tools/qualify_gmsh_cylinders.py --output-directory new-cylinder-acceptance` with
the private runtime configuration (configure Gmsh, FreeCAD and meshio) for the literal
sleeve, plate, deviation, rod, meshio-consumer, adoption and adversary cases.

## Capability-family map

| Family | Supported product scope | Remaining upstream breadth |
| --- | --- | --- |
| CAD construction/import | Boxes, complete axis-aligned cylinders and annular sleeves, balls, one-solid captured STEP | General sketches, transforms, arbitrary boolean graphs, assemblies and multiple domains |
| Meshing | Bounded serial first-order 3D tetrahedra; Delaunay/HXT and standard optimisation choice | Standalone 1D/2D, structured/recombined, high-order, hybrid and parallel meshes |
| Boundary intent | Disjoint axis-aligned whole planar groups, named whole analytic cylinders on a world axis (bores, shafts, sleeve walls) with proven material side, explicit cap-area budgets, a possibly empty remainder | Cones, spheres, B-spline or oblique cylinders, arbitrary planes, partial-face selection, source label preservation, interfaces |
| Resolution and decisions | Named-boundary size/distance envelopes, independent shape/edge/volume metrics, independent cylinder chord deviation and bounded requirement-driven refinement | Anisotropic/general fields, curvature sizing, Netgen optimisation, adaptive solver error estimation, solver setup |
| Exchange/verification | Named ASCII MSH, independently checked VTU volume/boundary and quality arrays, STEP surface inventory, adopted STEP inputs, explicit loss map | General MSH import (including MSH 4.x), general import/export conversion and interactive native editing |

The completed supported scope is these connected workflows and verification
contracts. It is a limited subset of the entire Gmsh application and API.
