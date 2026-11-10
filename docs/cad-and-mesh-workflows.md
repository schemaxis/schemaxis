# Expanded FreeCAD and Blender workflows

Schemaxis exposes typed CAD and Blender operations, with native examples that run
in the installed applications. The linked capability maps track the continuing
[FreeCAD](freecad-capabilities.md) and [Blender](blender-capabilities.md) programmes;
these milestones do not claim full application parity. Host discovery, planning
and schemas require no native application imports or third-party Python packages.

## FreeCAD: modelling, finishing and imported solids

| Family | Operations | Contract |
| --- | --- | --- |
| Primitives | `box`, `cylinder`, `sphere`, `cone`, `torus` | Literal dimensions in mm; explicit origin and supported axes |
| Boolean solids | `cut`, `fuse`, `common`, `multiFuse` | Native linked features; bounded multi-solid fusion; final output must be one valid solid |
| Profiles and paths | `sketch`, `polygon`, `rectangle`, `circle`, `slot`, `holeLocations`, `boltGrid`, `boltCircle`, `arcPath` | Typed constrained line/circle/arc sketches and dimensional intent; explicit frames and checked extreme planar-face attachments; rectangle and circle retain named constraints; [history guide](freecad-histories.md) |
| Editable Draft outlines | `draftProfile` | Closed straight-edged native Draft Wires with explicit planar frames and checked extrusion/boolean composition; [polygon profile guide](freecad-draft-profiles.md) |
| Bodies and linear features | `body`, `bodySeed`, `pad`, `pocket` | Independent editable Body histories, checked solid seeds, subsequent Pads, finite or through-all Pockets and persistent length relationships; [workflow guide](freecad-part-design.md), [seed guide](freecad-body-seeds.md) |
| Rotations and references | `datumAxis`, `bodyRevolve`, `groove` | Named datum axes, bounded native additive/subtractive revolutions and retained profile references |
| Helical features | `additiveHelix`, `subtractiveHelix` | Typed additive/subtractive Body helices with explicit axes, handedness and checked pitch/height/turns/growth modes; [history guide](freecad-histories.md), [measurement limits](freecad-measurements.md) |
| Repeated features | `linearPattern`, `polarPattern`, `mirror` | Native history features with checked membership, direction, count and material effects |
| Body blends and bends | `additiveLoft`, `subtractiveLoft`, `additivePipe`, `subtractivePipe` | Ordered profile sections and connected paths, retained orientation/guide/corner intent; [sweep guide](freecad-sweeps.md) |
| Machining and walls | `hole`, `shell`, `bodyDraft` | Unthreaded Hole depth/tip/recess intent and uniform Skin thickness with exact opening counts and face-selected mould-release taper; [Hole guide](freecad-drilling.md), [shell guide](freecad-shells.md) |
| General profile solids | `extrude`, `revolve`, `loft` | Linked profile sweeps; bounded ordered loft sections (optionally ruled) into one solid |
| Finishing | `fillet`, `chamfer`, `bodyFillet`, `bodyChamfer` | Geometric edge predicates with exact match counts, explicit indices, or native Body history finishing |
| Legacy import | `readSTEP` | One solid; captured immutable STEP input and saved verification; no authored source-unit assertion |
| Checked import | `importSTEP`, `importMesh` | Captured STEP solids or manifold STL triangles with declared units/orientation, checked part-frame expectations, editable placement and linked refinement; [STEP scope](freecad.md), [mesh-to-solid scope](freecad-mesh-preparation.md) |

Named `dimensions`, document references and the existing pure document-resolution
functions now work before CAD option validation. For example, use
`"height": {"$document": "/dimensions/height"}` in the native box options. These
resolve to literal feature values for each visit. The [common runtime](adaptor-runtime.md)
now supports finite analytic design variants, with independent native execution and
verification per state.

Sketches retain their geometry in FCStd and drive real native sweep features.
Polygon sketches keep geometry without dimensional constraints; rectangle and circle
sketches are fully constrained with named dimensions and fail with `CONSTRAINT_FAILED`
if the Sketcher does not report them fully constrained. STEP import retains the
BREP as a source feature; it does not reconstruct the originating CAD feature history.

Every successful CAD job still writes **STEP (artifact 0), STL (1), FCStd (2)**.
Optional [named measurements](freecad-measurements.md) add a JSON publication at
artifact 3, with units and verified values from selected solid nodes.
A fresh FreeCAD process reopens and recomputes the feature tree, checks native option
values and dependencies, and checks STEP/STL readback. CAD shape verification uses
validity, volume, area and optimal geometric bounds. Using optimal bounds avoids
inaccurate default bounding boxes on curved surfaces. It is not a proof of exact
BREP topological identity. The host independently checks STL signed volume, centre
of mass, bounds and directed-edge closure. Its conditional deflection/float32 error
estimate retains the 0.5% volume ceiling; native `Mesh.Volume` is not authoritative.
Runs without the hardened export evidence return `RERUN_REQUIRED`; their earlier
receipts remain historical records. See the [checked-import guide](freecad.md) for
the supported source structures, numerical assumptions and acceptance evidence.

Inspect native edges before authoring finishing operations:

```sh
PYTHONPATH=src python3 -m schemaxis inspect \
  examples/schemaxis/expanded/freecad-housing.json --node blank \
  --freecad /absolute/path/to/freecadcmd --output-directory evidence/housing-edges
```

Inspection prunes to the selected solid and its dependencies. The output includes
edge indices, lengths, centres, bounds, endpoints and curve types, plus face areas
and surface types. Edge indices belong to that particular topology: regenerate the
inspection after changing upstream features. General persistent face/edge repair remains open. Separate routes provide
[fixed assemblies](freecad-assemblies.md), [technical sheets](freecad-drawings.md)
and [linear static solid analysis](freecad-analysis.md), each with its own
source-admission, verification and loss limits.

[Semantic edge selections](freecad-selections.md) can resolve curve type,
direction, plane and length predicates afresh after parameter changes, with an
explicit expected count. Inspection also accepts a selected analytic visit.

## Blender: direct inputs, processing and reusable outputs

New operations are `readSTL`, `readPLY`, `join`, `applyTransform`, `shadeSmooth`, `weld`,
`weightedNormal`, `voxelRemesh`, `bend`, `twist` and `shrinkwrap`.

- STL/PLY imports preserve the authored Y-forward/Z-up frame. `scale` is explicit
  and constructor-only: use **0.001** for the FreeCAD mm-to-Blender-metre examples.
  Imports require one polygon mesh; point-only PLY is not supported.
- Mesh inputs are copied into the attempt directory, and both retained and original
  digests are checked. The existing glTF reader now gets the same input capture.
- `join` combines evaluated geometry in world coordinates and retains material
  assignments and smooth flags. It is not a boolean union. It does not preserve UV
  maps, vertex groups, custom attributes or arbitrary custom normals.
- `applyTransform` bakes world transforms into mesh coordinates while preserving the
  world-space shape. Use it before modifiers when dimensions/deformation should act
  on the already-scaled geometry. Otherwise modifiers retain native object-local
  semantics. Subdivision now exposes `CATMULL_CLARK` and `SIMPLE` methods.
- `bend` and `twist` angles are **radians**, following their native modifier properties.
  The workshop includes a three-state analytic twist sweep, with native object reuse.
- `voxelRemesh` rejects requests exceeding eight million estimated bounding-grid
  cells before assigning the requested voxel size. This is a conservative workload
  guard, not an OS memory limit or a guarantee of a particular RAM footprint.
- Fresh-process scene checks now include shading flags and evaluated corner normals.
- Camera near/far clipping follows the model size. This fixes small CAD parts being
  cut by Blender's default near plane after conversion to metres. Clipping settings
  are checked in the pipeline and saved-scene rendering receipts.

A Blender scene may now declare `"meshes": ["finishedNode"]`. Each selected node
publishes an evaluated binary STL per state. The native exporter is followed by
native import; oriented triangles must agree exactly after float32 conversion.
A second Blender process repeats readback, and the host independently parses and
checks the STL triangles. Triangle ordering and starting vertices may change;
winding and coordinates must agree. Publication is limited to one million triangles.

STL explicitly loses materials, normals, UVs, attributes and unit metadata. Its
coordinates remain in Blender world units. Exported mesh artifacts can feed another
Blender operation or ParaView. The image/mesh/scene artifact order for each state is:
all images, `meshes` in authored order, then the saved blend. `prepareOnly` omits
images but still publishes requested meshes and the saved scene. Existing documents
without `meshes` keep their original artifact ordering.

## Runnable examples

1. [Direct CAD gallery](../examples/schemaxis/expanded/cad-direct-to-blender.json): a
   filleted housing with drilled posts, STEP reimport and a vent cut; a chamfered
   extruded rail; a revolved connector. Each goes directly to Blender through STL.
   There is no ParaView conversion step in this workflow.
2. [Blender mesh workshop](../examples/schemaxis/expanded/blender-mesh-workshop.json):
   weighted normals, bend, three twist states, joining/welding, voxel union,
   shrinkwrap and scaled PLY import. Every state retains a blend, PNG and verified STL.
3. [Blender → ParaView](../examples/schemaxis/expanded/blender-to-paraview.json): a
   scaled PLY tetrahedron becomes a Blender STL artifact, then a native ParaView
   mesh with cell-size information. It demonstrates the reverse application bridge.

```sh
PYTHONPATH=src python3 -m schemaxis run \
  examples/schemaxis/expanded/cad-direct-to-blender.json \
  --freecad /absolute/path/to/freecadcmd --blender /absolute/path/to/blender \
  --output-directory evidence/direct-cad
```

Run examples from the repository root; the PLY workshop fixture uses a repository-relative
path. All workflows use local process scheduling with explicit resource budgets.
FreeCAD does not use MPI. A completed process alone is never accepted as verification.

Reproduce the full qualification:

```sh
PYTHONPATH=src python3 tools/qualify_adaptor_expansion.py \
  --freecad /absolute/path/to/freecadcmd \
  --blender /absolute/path/to/blender \
  --paraview-root /absolute/path/to/paraview \
  --output-directory evidence/adaptor-qualification
```

The tool compares eight CAD fixtures with independent analytic volume formulas,
verifies the three workflows, checks scale/orientation and mesh changes, and tests
rejection of an excessive voxel request and an absent CAD edge. Retained logs,
replay scripts, runtime archives and receipts identify the code that actually ran.
See [qualification evidence](../verification/2026-09-19-adaptor-expansion.json).

## Persistent part dimensions

[Named native length parameters](freecad-parameters.md) drive primitive, extrusion, sketch and Pad
dimensions across batch variants and remain editable in the published
FCStd. They preserve explicit affine relationships, with unchanged publication
indices. Live sessions and scalar design studies reject these drivers.
