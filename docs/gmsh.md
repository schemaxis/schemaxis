# Gmsh: a solid to a verified tetrahedral mesh

`schemaxis.gmsh/1` meshes one box or single-solid STEP input in an isolated Gmsh
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
Declare `units: "mm"`, one `box` or `readSTEP` node, and one `tetrahedral` node whose
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
  Empty or overlapping selections fail; at least one remainder face is required.
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
and execute a fresh revision. The text panel exposes summary evidence; inspect VTU
through ParaView or a mesh viewer. No native Gmsh live editor, arbitrary scripts,
high-order elements, MPI, arbitrary/nonplanar face selectors or general mesh importer is
provided. Positive cells and volume agreement are useful checks, not a proof that
a mesh is adequate for a particular simulation.

`INTERPRETER_NOT_FOUND` needs the configured Gmsh Python. `RESOURCE_LIMIT` needs a
larger target size or smaller source. Native failures retain build/reopen logs;
check that the STEP contains one valid solid. A volume-tolerance failure requires
refinement or investigation of the CAD. Do not weaken verification to accept it.

Run `tools/qualify_gmsh.py` with the private runtime configuration for analytic
baseline/variant meshes, the CAD handoff and public authoring verification. The
kit also challenges every publication, authored/plan evidence and lifecycle.

## Native acceptance

Qualified on Gmsh 4.15.2 with analytic 10×10×10 and 20×10×10 mm boxes.
The FreeCAD handoff checks 20×10×5 and 20×10×7 mm parts; ParaView independently
integrates their volumes and reads both physical tag arrays. Multi-solid STEP
is rejected; changing captured STEP bytes invalidates verification. A public
context/source/property loop inspects the same summary used by a human.

```sh
PYTHONPATH=src python3 -m schemaxis run examples/schemaxis/gmsh-minimal.json \
  --gmsh /absolute/path/to/gmsh-python --output-directory new-mesh
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

Available requirements are maximum tetrahedral edge length, minimum tetrahedral
mean ratio, maximum relative CAD-volume discrepancy, and
`boundaryMaximumEdgeLength: [{"boundary":"fixed","maximum":0.9}]`.
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
mesh. A workflow consumer cannot proceed with it. The Python inspection call
`refinement.verify(directory, require_acceptance=False)` verifies such a completed
unmet study without claiming that its mesh requirements passed.

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
