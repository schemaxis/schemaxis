# FreeCAD: checked STEP import and reliable exports

The `schemaxis.freecad/1` route models solids in FreeCAD 1.1.x and publishes a
STEP file (artifact 0), an STL mesh (1) and a native FCStd document (2), with
optional measurements (3). Related guides:

- [CAD and mesh workflows](cad-and-mesh-workflows.md): primitives, booleans,
  sketches, sweeps and finishing.
- [General design histories](freecad-histories.md), [PartDesign parts](freecad-part-design.md) and
  [design parameters](freecad-parameters.md): editable sketch and feature history.
- [Assemblies](freecad-assemblies.md), [measurements](freecad-measurements.md),
  [semantic edge selections](freecad-selections.md),
  [design studies](freecad-design-studies.md) and [examples](freecad-examples.md).

The separate [solid elasticity guide](freecad-analysis.md) covers checked CAD →
editable native FEM material, mesh, geometric supports/tractions and CalculiX
results with independent physical verification.

This guide covers `importSTEP`, which brings an external STEP part into a model
with explicit units, orientation and placement, checks it against facts you
declare, and optionally merges coplanar faces. It also describes the export
checks that every new run of this route now passes.

## When to use importSTEP

Use it for a part that you did not model in Schemaxis, such as a supplier
bracket. You state:

1. which length unit the file assigns;
2. which file axes become the part's +Z and +X;
3. where the part goes in the model;
4. what you know about the part from its drawing or datasheet.

Then continue with the existing operations (for example a `cut` that drills a
mounting hole, a semantic `fillet`, `measurements`) and publish checked STEP,
STL and FCStd files. A Gmsh document can take the STEP through
`{"$artifact": "<operation>", "index": 0}`.

```json
{
  "version": "schemaxis.freecad/1",
  "nodes": [
    {"id": "bracket", "filter": "importSTEP", "options": {
      "file": "examples/schemaxis/freecad-import-step-bracket.step",
      "units": "inch",
      "orientation": {"z": "+Y", "x": "+X"},
      "placement": {"position": [100, 50, 0], "clocking": 90},
      "expect": {
        "volume": {"value": 10840, "relativeTolerance": 1e-6},
        "centreOfMass": {"value": [-0.80812, -0.24354, 5], "tolerance": 0.01},
        "points": {"inside": [[0, 0, 5]], "outside": [[15, 6, 5], [-9, -6, 5]], "guard": 0.5}
      },
      "refine": true}},
    {"id": "hole", "filter": "cylinder", "options": {"radius": 2, "height": 20, "origin": [108, 60, -5]}},
    {"id": "drilled", "filter": "cut", "inputs": {"base": "bracket", "tool": "hole"}}
  ],
  "output": "drilled"
}
```

The full example is
[freecad-import-step.json](../examples/schemaxis/freecad-import-step.json). A
relative `file` resolves against the directory you plan and run from (the
repository root for the examples).

## Options

| Option | Meaning |
| --- | --- |
| `file` | A plain ISO 10303-21 STEP file (AP203, AP214 or AP242) holding exactly one solid, or a workflow artifact reference to a verified STEP publication. |
| `units` | Required: `mm`, `cm`, `m` or `inch`. This is the length unit the file itself assigns to its shape. FreeCAD converts that unit to millimetres. `units` asserts what the file means and never rescales it. |
| `orientation` | `z` and `x` name the signed file axes (`+X … -Z`) that become the part's +Z and +X; +Y completes a right-handed frame. Defaults keep the file axes. `x` is required when `z` is not ±Z and must be perpendicular to it. A reflection cannot be expressed. |
| `placement` | `position` (mm, each within ±100000) and `clocking` (degrees about the part +Z, ±360), applied after orientation. |
| `expect` | Required facts in the **part frame**: after units and orientation, before placement. Details are below. |
| `refine` | Optional, default false. Adds a parametric `Part::Refine` output that merges coplanar and co-cylindrical faces. |

### Declared facts

`expect.volume` (mm³, relative tolerance 1e-9 to 0.01, default 1e-6) is required.
You must also give `expect.centreOfMass` (mm, tolerance 1e-6 to 1, default
0.01), or `expect.points` with at least one `inside` and one `outside` point.
Optional `expect.bounds` checks the part-frame bounding box.

Volume, area and bounds alone accept a mirrored or turned part: a part and its
mirror image have the same volume, area and box. The centre of mass and
inside/outside points are what tell them apart.

Each point must lie at least `guard` (mm, 1e-6 to 10) from every face. The exact
distance to the solid's boundary is measured before the inside test. A point on
or near a face is refused with `INVALID_ARGUMENT`, because a point on a surface
counts as both inside and outside.

**What the facts prove, and what they do not.** They check exactly the facts you
declared, measured on the exact solid. They are not a general proof of identity
or orientation:

- A part whose centre of mass lies on its own symmetry plane cannot reveal a
  mirror about that plane through its centre.
- Too few or badly placed points can miss a change.
- The FreeCAD reader can silently repair a file's face orientation. A
  hand-written file with wrong face senses reads back correctly, so readback
  alone cannot detect a broken file.

Take the facts from an independent source (drawing, datasheet or an earlier
verified run), never from the file being checked.

## What happens at planning, run and verification

**Planning** reads the file (read-only, at most 32 MiB). A bounded ISO 10303-21
scanner tokenises strings, comments and lists, builds the instance table and
follows the single `SHAPE_DEFINITION_REPRESENTATION`. It accepts either an
advanced B-rep representation, or a shape representation linked to one by a
plain `SHAPE_REPRESENTATION_RELATIONSHIP`. It refuses, before FreeCAD starts:

- product or assembly structure (`NEXT_ASSEMBLY_USAGE_OCCURRENCE`), instancing
  (`MAPPED_ITEM`) and transformed relationships;
- external references;
- entity types outside the supported solid subset, including presentation and
  colour records;
- any representation, unit context or B-rep that is not reached from the shape
  definition;
- more than one solid;
- two legitimate STEP forms outside this bounded subset, reported as unsupported
  forms rather than corrupt files: a `SHAPE_REPRESENTATION` that holds the solid
  directly without a relationship, and faceted B-rep (`FACETED_BREP`) solids.
  Re-export them as an advanced B-rep representation;
- more than 100000 entities or 2000 oriented edges in one loop;
- nesting, string and token limits;
- non-ASCII text and compressed files.

The assigned length unit comes from the representation context actually reached;
unit text elsewhere in the file is ignored. The plan records the resolved
absolute path, the SHA-256 digest, the schema and the unit. A changed file
therefore changes the plan, and resume reruns the job.

**The run**:
1. copies exactly the planned bytes to a run-owned `import-N.step`
   (`INPUT_CHANGED` if the file changed after planning);
2. rescans that copy;
3. starts FreeCAD, which reads only the copy. FreeCAD must find one valid solid
   whose shells are all closed (`INVALID_GEOMETRY` otherwise; no repair is
   attempted);
4. measures the declared facts on the exact solid (`EXPECTATION_FAILED` at the
   failing field);
5. saves, exports, and reopens everything in a separate process.

One total deadline (default 300 s) starts before planning. It covers the source
scan, capture, the FreeCAD processes and verification, and an overrun stops the
FreeCAD process tree. Cancellation and the deadline are checked before each
FreeCAD process starts, after verification, and cooperatively inside the long
host loops:
- every 2048 STEP instances or records while scanning;
- every 65536 facets while integrating the STL;
- every MiB while hashing retained copies.

A stop raises `RUNNER_CANCELLED` or `RUNNER_TIMED_OUT`.

Workflow resource estimation validates the document without reading STEP
sources. A scheduled workflow therefore still verifies after an original is
removed, while a new run, reuse or resume reads the current file and refuses an
absent or changed one. Read time depends on the geometry, not
only on file size. The entity and loop limits bound the measured worst case: a
valid 6000-edge face took 397 s, and 2000 edges took about 14 s.

**In the native document**, the import is a `Part::Feature`. Its `Placement` is
the editable orientation plus placement, and a `SourceSHA256` property records
the digest. With `refine`, a `Part::Refine` object takes that feature as its
`Source` and keeps identity placement. Moving the source in the FreeCAD GUI moves
the refined part with it. This survives saving and reopening.

**Saved verification** never opens the original file. It replays planning from
the retained copy: the copy must hash to the capture record, the recorded path
must match the authored path, and the replayed plan must equal the saved plan.
It then:
- checks the FCStd's `SourceSHA256` and refine link;
- re-evaluates the declared facts from both native observations (build and
  fresh reopen);
- runs the export checks below.

A moved, exported or archived run still verifies after the original STEP is
gone. The FreeCAD route also reports its verified, retained source digests to
the workflow scheduler (`retainedInputs`).

## How imported geometry differs from modelled parts

A PartDesign part has constrained sketches, features and parameters, so editing
a dimension regenerates it. An imported part is a fixed B-rep solid: it has no
sketches, constraints, parameters or feature history, and none is recovered from
STEP. Names and colours are not imported.

You can still edit:
- its placement;
- operations you add after it, such as the parametric refine and later cuts.

`importSTEP` cannot share a document with a PartDesign Body, and live preview
does not support it.

## Export checks for every new run

Every new run of this route (constructor solids, PartDesign parts, imports and
legacy `readSTEP` documents) records exact native facts of its output in the
build and in the fresh reopen: volume, area, curved-face area, bounds, centre of
mass and face count. Verification then checks the published files.

**STL.** The host reads the binary STL itself, in double precision about a local
origin. It requires:
- every directed edge to pair with its reverse (a closed, consistently oriented
  mesh);
- a positive signed volume, so an inside-out mesh is refused;
- the volume, centre of mass and bounds to agree with the native solid within a
  stated budget.

FreeCAD's own mesh volume is not used: it is computed in single precision about
the world origin and fails for parts placed far from it.

**The budget** is a conditional engineering estimate, not a rigorous bound for
every topology. It assumes OCCT's meshing contract: vertices on the surface,
exact planar faces, curved faces within the meshing deflection `d` (half of
`linearDeflection`).

- volume allowance = curved area × d + area × δ32 + roundoff
- δ32 = √3 · (largest coordinate) · 2⁻²⁴, the single-precision rounding of each
  written vertex
- the centre allowance follows from the same layer and the part's extent

The established acceptance of 0.5 % relative or 1e-5 mm³ absolute volume
difference remains an additional ceiling, now applied to the host volume. A
budget that is not finite, is negative, or is not smaller than the volume is
refused. The host check holds the whole mesh in memory. At the cap of 2000000
facets, measured on one host, it took about 11 s and peaked at about 980 MiB.
Its final closure comparison (one sort) runs between checkpoints. A mesh that
cannot meet the checks fails with advice to reduce
`linearDeflection`.

The verify result reports `exportChecks`:
- the level (`hardened`);
- the measured errors and their allowances;
- `mirrorDiscriminability`: for each axis, whether mirroring the part about its
  bounds centre would move the centre of mass beyond twice the allowance. A
  symmetric part reports `false`. This is a per-run statement, not an identity
  guarantee.

**STEP.** The exported STEP must declare one millimetre solid (checked by the
same reference walk). Its readback in the fresh process must match volume, area,
bounds and centre. That readback uses the same kernel, so it is self-consistency
only. The independent checks are the host STL integrals, the host STEP scan and
your declared facts.

**Runs made before these checks** lack the new evidence. Their verification now
fails with `RERUN_REQUIRED` (`exportChecks: unqualified-for-hardened-verification`);
it never succeeds in a downgraded form. Their old receipts remain historical
evidence. Run the document again to obtain verifiable publications.

## Faults

| Code | Typical location | Meaning and recovery |
| --- | --- | --- |
| `UNIT_MISMATCH` | `<id>.options.units` | The file assigns another unit; state the unit the file declares. |
| `UNDECLARED_UNIT` | `<id>.options.file` | The file assigns no length unit, or more than one. Re-export it with units. |
| `UNSUPPORTED_UNITS` | `<id>.options.file` | The unit is not mm, cm, m or inch (for example foot). |
| `UNSUPPORTED_SOURCE` | `<id>.options.file` | Assembly, transformed, presentation, external or unreferenced structure, unsupported schema or encoding, symbolic link, or a Body in the same document. |
| `RESOURCE_LIMIT` | `<id>.options.file` | Size, entity, loop, nesting or string limits. Simplify or split the source. |
| `INVALID_GEOMETRY` | `<id>.options.file` or `<id>` | Not exactly one valid solid with closed shells. |
| `INVALID_AXIS` | `<id>.options.orientation.x` | Missing or non-perpendicular x axis. |
| `INVALID_ARGUMENT` | `<id>.options.expect…` | No orientation-sensitive fact, invalid bounds, or a point within `guard` of a face. |
| `EXPECTATION_FAILED` | `<id>.options.expect.<fact>` | The imported part differs from a declared fact. Check the file revision, units and orientation. |
| `PREPARATION_CHANGED_GEOMETRY` | `<id>.options.refine` | Refine changed volume or centre, or added faces. |
| `INPUT_CHANGED` | `<id>.options.file` | The source changed after planning. Plan and run again. |
| `RERUN_REQUIRED` | run directory | The run predates hardened export checks. Rerun the document. |

## Measurements and selectors on pointed or spherical solids

Edge inventories keep the native topology numbering, including degenerated edges: the poles
of a sphere and the apex of a pointed cone. They are recorded as curve `Degenerate` with
their measured length (at most 1e-7 mm) and are never matched by `curve`, `onPlane`,
`length` or `parallelTo` predicates, so `{"curve": "circle"}` on a pointed cone selects only
its base circle. Explicit one-based indices still address them. A native edge with a real
length but no analytic curve is refused with `UNSUPPORTED_EDGE` (the fault names its index);
select explicit indices that avoid it, or simplify the source solid. Run directories made
before this note keep their original inventories and verify unchanged. This is host-side
selection semantics; it adds no native option and no new format.

## Qualification and limits

`tools/qualify_freecad_step_import.py` writes every STEP input itself, with no CAD
kernel, so its volumes, centres and point membership are exact closed forms. The
inputs include planar solids with an asymmetric notch and hole, a void, a
split-face block and a box with a cylindrical hole. The qualifier then checks
units, orientation, refine, curved surfaces, far placement, the relationship
structure, the admission refusals, tampered publications, source removal with a
schema-aware export, relative paths, legacy `readSTEP`, workflow reuse and a
timeout. The [verification note](../verification/2026-10-19-freecad-step-import.md)
records the qualified scope.

Not supported in this release:
- assemblies or several solids from one file;
- names and colours;
- feature recognition or face selection on imports;
- defeaturing and healing;
- live preview;
- imported parts in the assembly route.

Only FreeCAD 1.1.4 with OCCT 7.8.1 is qualified, and only B-spline-free curved
inputs (planes and cylinders) were checked against independent writers.

[Native spreadsheet dimensions](freecad-spreadsheets.md) retain editable mixed-unit
input cells and affine formula aliases that drive part histories. Broader table,
angular, nonlinear and cross-document workflows remain open.
