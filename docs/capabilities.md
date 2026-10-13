# Schemaxis capabilities in detail

Schemaxis describes repeatable ParaView, Blender, FreeCAD, Godot, Aseprite, FFmpeg,
Inkscape, Shotcut, QGIS, Gmsh, CalculiX, Cantera, ngspice, Octave, R and LibreOffice Calc pipelines
in JSON or optional YAML, executes them
in native application processes, and retains plans, editable artifacts and verification
evidence. It is David Gaden's independently developed project with bounded application adaptors.
For CFD post-processing of OpenFOAM-format cases, start with the [CFD guide](cfd-guide.md)
for setup, demonstration commands and qualification boundaries.

For CFD post-processing, follow the [step-by-step ParaView guide](cfd-postprocessing.md)
and its [copyable inputs](../examples/cfd-postprocess/README.md). [CFD-README.md](../CFD-README.md)
provides the wider demonstration map and schemas.

For reusable multi-case proofs and ordinary-AI versus Schemaxis-assisted trial
setup, see the [workflow benchmarks](benchmarks.md) and
[editable case list](../examples/benchmarks/cases.json).

Start with the [ten-minute walkthrough](getting-started.md), then the
[user guide](user-guide.md). For authoring, use the
[JSON input reference](json-input.md) and [schema guide](schema-guide.md).
For interactive work, see the [console commands](console.md) and
[Studio guide](visual-console.md). The [quick reference](quick-reference.md),
[AI guide](ai-guide.md), [developer guide](developer-guide.md),
[adaptor completion checklist](adaptor-completion.md) and
[coverage report](coverage.md) provide additional detail.

[YAML authoring](yaml.md) uses the same schemas and execution engine,
with the optional `schemaxis[yaml]` extra for host parsing and comment-preserving
Studio edits. [Durable schedules](scheduling.md) let humans and agents register
future work for an independent worker. [Output metadata](output-metadata.md)
adds verified size and spatial companions to published artifacts, including
four image-edge coordinates for supported planar slice projections.

For proposed expansion, see the [candidate adaptors, conversion and workflow-template
design](design/adaptor-candidates.md). It distinguishes future candidates from
implemented and qualified capabilities. The new [Gmsh workflow](gmsh.md)
meshes a FreeCAD STEP solid and publishes named volume/planar-face meshes for ParaView.
It also supports named-boundary sizing, independently measured mesh quality and
bounded refinement under explicit acceptance requirements, using the shared
[feedback controller](feedback-studies.md). Each attempt retains its inputs,
measurements and decisions; only an accepted mesh is published to later operations.
[Cantera thermochemistry](cantera.md) adds verified ideal-gas properties and
TP/HP equilibrium tables, with a Calc workbook handoff.
[ngspice circuits](ngspice.md) adds independently checked DC networks, AC RLC
frequency responses and first-order RC transients, with shared authoring and a Calc handoff.
Named sampled requirements report worst voltage/gain conditions and signed margins;
an unmet requirement blocks downstream publication without claiming continuous-envelope coverage.
[CalculiX cantilevers](calculix.md) check native equilibrium, separate mesh
refinements, beam-theory agreement and named serviceability requirements.
[R regression](r.md) checks numeric linear fits against an independent QR
solve, reopens saved native models, and assesses finite training/held-out limits.
[Calc requirements](calc.md) enforce named cell bounds and weighted
reconciliations in both XLSX and reopened ODS. The
[beam-to-workbook example](beam-workbook.md) connects structural observations
to independently checked workbook requirements.
[Inkscape diagrams](inkscape.md) publish editable SVG and measured PNG output
from explicit boxes or named dependency flows, with native text-fit checks.
[Shotcut timelines](shotcut.md) trim, reorder and repeat named video ranges,
retaining an editable MLT project and verifying every rendered frame.
[Media deliverables](media-workflows.md) can require exact dimensions and
frame counts, timing within a specified tolerance, a byte budget and a measured
reconstruction-error limit.
The [diagram-to-video example](diagram-video.md) connects all three, including
verified reuse and rejection of a producer that misses its deliverable requirements.
[Premiere sequence inspection](premiere.md) is experimental: a read-only UXP
companion checks existing sequence structure against declared requirements.
Native qualification requires Premiere on Windows or macOS and is still pending.
[QGIS centroids](qgis.md#projected-polygon-centroids) add verified planar polygon centres.
[FreeCAD semantic selections](freecad-selections.md) identify finishing edges
by geometric predicates and an explicit match count, re-evaluated for each design
variant with retained native selection evidence.
[Named CAD measurements](freecad-measurements.md) publish geometric quantities
with units, supporting verified CAD → Gmsh/Octave value and artifact handoffs.
[CAD target studies](freecad-design-studies.md) search one bounded length for
a named geometric target, retaining every candidate and an explicit acceptance
or unmet outcome.

The [workflow-template foundation](design/workflow-templates/template-contract.md)
provides `template inspect`, `template bind` and `template plan`, with the same exact
case binding through the local service. Schemaxis Studio now exposes this contract
through Workflow Designer template export and Case Runner's typed parameter form,
planning, asynchronous execution, verification and named output views. Start with
the [sample-and-scale Studio walkthrough](../examples/studio/README.md), or inspect
the [larger editable template example](design/workflow-templates/examples/README.md).

The registered adaptors accept these document versions: ParaView `schemaxis/1`, Blender
`schemaxis.blender/1` and `schemaxis.blender.render/1`, FreeCAD `schemaxis.freecad/1` and
`schemaxis.freecad.assembly/1`, Godot `schemaxis.godot/1`, Aseprite `schemaxis.aseprite/1`,
Gmsh `schemaxis.gmsh/1`, CalculiX `schemaxis.calculix/1`,
Cantera `schemaxis.cantera/1`, ngspice `schemaxis.ngspice/1`,
FFmpeg `schemaxis.ffmpeg/1`, Inkscape `schemaxis.inkscape/1`, Shotcut `schemaxis.shotcut/1`,
QGIS `schemaxis.qgis/1`, experimental Premiere `schemaxis.premiere/1`,
Octave `schemaxis.octave/1`, R `schemaxis.r/1`, Calc `schemaxis.calc/1`,
and the cross-operation envelope `schemaxis.workflow/1`. See the
[version and field table](json-input.md#1-basic-structure) before choosing a
template; file handoff kinds remain explicitly scoped per route.

## Name

The product, installable package and command are **Schemaxis**. Use `schemaxis`
or `python3 -m schemaxis`; Python imports use `schemaxis.*`. Input versions,
schema filenames, environment variables and browser integration also use this
name.

## Run

Follow [installation and private configuration](installation.md) to record your
application locations. [Latest-release maintenance](updates.md) explains the
scheduled update report, work estimates and generated AI repair briefs.

Host Python 3.10+ needs no third-party runtime package. Historical native qualification uses
ParaView 5.13.3 `pvbatch`, Blender 5.2.2, FreeCAD 1.1.x, Godot 4.x or
Aseprite 1.3.x, FFmpeg/FFprobe or a configured QGIS Python runtime, depending on
the adaptor. Bounded numerical and structural qualification uses Octave 11.3.0,
R 4.6.1, Calc 26.8.1.1 and CalculiX 2.23. Godot's optional PNG preview additionally
needs a graphical display. Pass the selected runtime with `--paraview-root`,
`--blender`, `--freecad`, `--godot`, `--aseprite`, `--ffmpeg`,
`--qgis`, `--gmsh`, `--calculix`, `--cantera`, `--ngspice`, `--octave`,
`--r` or `--calc`.
Configure the `inkscape` and `shotcut` executable locations for workflows;
their standalone runs also accept the generic `--executable` override.
The experimental Premiere panel uses the separate `--premiere-bridge` folder option.
Serial ParaView does not require NumPy; distributed fingerprinting uses ParaView’s bundled NumPy.

```bash
export PYTHONPATH=src
python3 -m schemaxis describe
python3 -m schemaxis describe streamTracer
python3 -m schemaxis colours
python3 -m schemaxis plan examples/schemaxis/branching.json
python3 -m schemaxis run examples/schemaxis/branching.json \
  --paraview-root /path/to/ParaView/install --output-directory new-run
python3 -m schemaxis verify new-run
```

Alternatively install this project with `pip install .` and use the `schemaxis`
command. Workflow runs create missing parents and accept a new or empty output
directory. Use workflow `--resume` for an existing unchanged run. Standalone
adaptors retain their own output contracts; use a new destination with an
existing parent for portability across them. File/stdin
input, scoped document references, composition and typed defaults use the shared
Schemaxis input machinery. The existing `python -m schemaxis.adaptors.paraview.mvp` MVP remains available.

`plan` is application-free. A time selector requiring source inspection returns
`TIME_INSPECTION_REQUIRED`; `run` performs the metadata inspection, resolves times,
checks the final expansion budget, and retains both stages before executing data.

For bounded capability navigation, start with `schemaxis capabilities browse` or
`schemaxis capabilities search 'plane'`. Retrieve complete operation details with
`schemaxis capabilities describe operation/paraview/slice`; large document schemas
are navigable through `schemaxis capabilities schema`. See
[progressive capability discovery](capability-discovery.md) for status, caching,
pagination and the shared Python service. Discovery does not check native readiness.

For editor schemas, `schemaxis schema --all` exports a standalone authored umbrella
covering the registered input versions. Use `schemaxis schema --authored --provider blender`
for one adaptor, or `--authored --version schemaxis.workflow/1` for an exact document
type. The compatibility default without `--all` is expanded input (`--expanded`).
Schemas check structure, not native success; follow with `schemaxis plan INPUT.json`.
See the [JSON schema reference](json-input.md#13-generated-schemas-and-extension-framework)
and [schema guide](schema-guide.md) for the validation boundary.

VS Code workspace associations are included for `input.json`, `inputs/**/*.json`,
`*.schemaxis.json` and top-level Schemaxis examples. Open this repository as the workspace;
see [editor setup](schema-guide.md#editor-setup) for other workspaces and IDEs.

## Pipeline ownership and execution

The registered application routes share document references,
pure value functions, expressions and finite analytic studies. Workflows also support
references to other operation documents and verified values from JSON/numeric-table
publications. See [the common runtime](adaptor-runtime.md) for scoping, iteration,
execution modes and qualification limits. Native graph reuse remains available in
ParaView and Blender; other routes execute isolated native visits.

For ParaView and Blender geometry, `DefinitionGraph` validates the entire description and dependency graph, including
hidden dependencies introduced by observations or samples. It creates no native
objects. Duplicate names, unknown ports/references, invalid options and cycles
fail explicitly. The resolved plan includes defaults, declarations and a digest.

`RuntimeClosure` takes the dependency closure of visible objects and explicit
output roots. Unused nodes and their iteration axes do not execute. Across scenes,
shared nodes survive while unneeded nodes are deleted in reverse dependency order.
Each active logical node owns one native proxy. There is no proxy aliasing between
distinct logical nodes.

Independent axes vary fastest-first in their declared order. Multiple properties
can reference one axis for coordination. Direct parameter changes are all applied
before explicit pipeline updates; observation-dependent changes follow fresh
upstream observations. Dirty state propagates downstream. Identical effective
values do not trigger redundant updates. No output is published between partial
changes. A failed transition poisons that active instance; it must be closed.

Publication order is time → scene → geometry state → geometry/measurement outputs
→ appearance → glTF/image writer/camera. Geometry is not multiplied by camera or
appearance changes. Geometry-only jobs do not create render views.

The host checks membership, order, effective settings, proxy reuse and dependency
invalidation against native receipts. Cleanup is part of successful completion.

## Dictionary-driven filters

The dictionaries above classes in `src/schemaxis/adaptors/paraview/filters.py`,
`extra_filters.py` and `more_filters.py`
declare constructor names, input ports, property paths, types, defaults, conversion
and cross-property requirements. Most classes contain only `declaration = ...`.
The same descriptions drive validation, discovery, native assignments and readback.
Runtime property paths come from trusted declarations, never arbitrary input code.

The curated ParaView catalogue declares 61 operations:

- Sources: wavelet, sphere, line, cone, cylinder, plane, disk, OpenFOAM,
  VTP/VTU/VTI/VTS/VTR/VTM, STL and PLY readers.
- Additional selection/analysis: ID generation, array selection, curvature and
  structured subset extraction.
- Calculation and selection: calculator, cell-to-point, point-to-cell, block
  extraction, grouping, merging, threshold, connectivity.
- Geometry: slice, contour, surface extraction, normals, reflection, clip,
  streamline with a separate seed input, tube, outline, edges and feature edges.
- Additional processing: vector/scalar warp, shrink, clean, clean-to-grid,
  Delaunay 2D/3D, elevation, gradient/divergence/vorticity/Q criterion, cell size,
  decimation, smoothing, triangulation, dataset/geometry append, transform,
  resampling, temporal statistics, integration and line sampling.

An additional 535 generated source/filter bindings, 44 explicit writer bindings
and five typed resource bindings expose native property names,
including nested proxy choices and typed input contracts. They overlap the curated
operations. See the [catalogue and extension guide](paraview-catalogue.md) for
coverage status, qualification limits, output-port selection, hierarchical data,
verified exports and trusted plugin packages.

These are bounded option sets, not complete wrappers of every native property.
`describe` is the exact executable declaration. Native acceptance covers the
supplied examples; it does not certify every option combination or input type.
Temporal statistics uses the native filter's available-time semantics, rather
than silently restricting its internal aggregation to the outer publication times.

## Input example

```json
{
  "version": "schemaxis/1",
  "nodes": [
    {"id": "data", "filter": "wavelet"},
    {"id": "cut", "filter": "slice", "inputs": {"input": "data"},
     "options": {"normal": "z+", "origin": [0, 0, {"$axis": "height"}]}}
  ],
  "axes": [{"name": "height", "series": {"start": -2, "end": 2, "count": 3}}],
  "scenes": [{"id": "sections", "geometry": ["cut"],
    "visible": {"cut": {"colour": "xkcd:sky blue"}},
    "images": [{"id": "report", "size": [640, 480],
                "cameras": [{"direction": [1, -1, 1]}]}]}]
}
```

An axis accepts `values` or a scalar `series`. To move a pair of seed endpoints
together, use object-valued axis entries and select each endpoint with
`{"$axis":"seed","path":["start"]}` and `..."end"`.

Runtime inputs are explicit:

- `{"$time":true}` is the current selected time.
- `{"$observe":"mesh","path":["bounds",0]}` selects current metadata. Bounds
  order is xmin, xmax, ymin, ymax, zmin, zmax; fields include associations, components
  and ranges. Observation references create hidden graph dependencies.
- `{"$sample":"probe","association":"POINTS","field":"pressure","index":0}`
  selects a scalar or vector tuple. Optional `component` chooses a component;
  `block` is an explicit sequence of multiblock indices. Tuple position is not a
  persistent physical identity. Sampling records the exact selection and value.
- `{"$calc":"midpoint","args":[{"$observe":"mesh","path":["bounds"]}]}`
  computes a box midpoint. Other runtime operations include boundsMin/boundsMax,
  vector, add, subtract, multiply, divide, min and max. Arithmetic supports scalar
  broadcasting and matching component arrays; it does not evaluate Python.

Authored `$document` and `$expr` preserve Schemaxis's definition-site scoping. Dictionary
overlay/merge/omit, key/index lookup and arithmetic remain available. `namedMerge`
and `namedGet` explicitly operate on ordered arrays of uniquely named objects;
merge retains left order and appends right-only names. Duplicate names fail, and
conflicts accept left/right/error policies. Ordinary arrays are still atomic.

Times can be explicit finite numbers or a native inspection request:

```json
"times": {"source": "case", "select": {"latest": 2}}
```

The selector also supports first/latest, explicit values with tolerance,
value ranges, indices and index ranges through the existing Schemaxis time contract.
Any declared source exposing native `TimestepValues` can supply this metadata;
it is not restricted to OpenFOAM. Sources without discrete times fail explicitly.
Reader variants and fields are not guessed. The examples use serial pvbatch on
decomposed OpenFOAM inputs; this is not an MPI certification.

## Colours, scenes and outputs

The retained Matplotlib 3.11.1 palette contains 1,163 names, including CSS,
Tableau and XKCD names. Names are case-insensitive. Hex RGB/RGBA, short hex,
greyscale strings and numeric RGB/RGBA are supported. Integer vectors containing
a component above one use byte notation; other numeric vectors use 0..1.
Colour alpha multiplies opacity. Matplotlib is only needed to regenerate the
palette with `tools/export_colours.py`; its licence is retained beside the data.

Appearance options include solid colour, field association/name, component or
magnitude, opacity, colour range, native palette preset, logarithmic scale, legend
title and supported representation.
Appearance entries coordinate all visible objects; missing fields fail rather
than falling back. Each image writer owns dimensions and ordered cameras, with
direction/up, focal point, parallel/perspective, scale, distance, bounds and padding.
Appearance values and camera settings may use runtime observations and samples;
their dependencies remain active even if invisible. Camera lists may be literal
or authored analytic publication sequences.
Camera-only variation belongs in those lists rather than multiplying geometry
through a presentation-only axis. `examples/schemaxis/data-framing.json` demonstrates
data-dependent ranges and a close-up framed by an invisible bounds object.

Plan version 2 includes presentation and the complete resolved document in its
digest. Host verification re-evaluates recorded appearance/camera values against
the authored request and current observations. Older version-1 receipts remain
readable with their narrower verification scope and retained declarations.

Geometry chooses a native XML format by output type: VTP, VTU, VTI, VTS, VTR or
VTM. It is reopened and compared across numeric arrays, coordinates, topology,
grid layout and block names. File digests include multiblock sidecars. There is
one explicit normalisation for VTK char/signed-char storage of masks.

Measurement outputs write/re-read field tables as CSV with an explicit association.
They do not infer scientific units. Integration and probe examples have independent
analytic checks. `gltf: true` exports a scene per appearance, with inline buffers,
structural checks and a nonempty native reopen. glTF verification is weaker than
the XML scientific-data round trip; its receipt states field/unit losses.

PNG verification checks decoding, dimensions, nonuniform pixels and native
appearance/camera settings. This is not a perceptual quality metric or solver
validation. Review representative images as well as their receipts.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
SCHEMAXIS_PARAVIEW_ROOTS=/path/to/ParaView/install PYTHONPATH=src \
  python3 -m unittest discover -s tests/conformance -q
PYTHONPATH=src python3 examples/schemaxis/acceptance.py \
  --paraview-root /path/to/ParaView/install --output-directory acceptance-run \
  --case /path/to/first/case.foam --case /path/to/second/case.foam
```

The acceptance runner covers filter exports, branching, samples, glTF, native scene
switching, analytic integrals/probes, and expected failures. Optional real cases
must supply U/p on the cell association. Failed runs keep incomplete evidence.
Each run retains its authored/effective input, plan, an exact runtime zip, submitted
script, receipt and artifacts. Direct replay uses recorded paths; rerun the CLI
with a fresh destination to preserve existing results.

## The showcase and application handoffs

The shared input context now reads typed primitive values or full live objects.
`ObjectRegistry` distinguishes unknown, not-yet-produced, wrong-kind and retired
objects; `InputContext.get` applies defaults only to absent entries. Inline input
construction uses `{"$create": {"id": "source", "filter": "wavelet"}}` and an object
reference uses `{"$object": "source"}`. Inline constructions are lifted into the
master graph before execution and retain their identity on repeated reads.

A parameter can carry its own analytic without a separate authored axis:

```json
{"radius": {"$analytic": {
  "type": "linear", "start": 1, "end": 3, "count": 8, "sync": "shape"
}}}
```

Scalar or matching vector endpoints are supported. `values` supplies an explicit
sequence. Any number of members may share a `sync` name, but their lengths must
match; independent groups form a Cartesian product. Developer lookups register
bindings by owner and member path and return the current ordinary value.
`analytic-bindings.json` retains those associations for submitted runs. Explicit
axes precede generated axes; first encountered analytic groups vary fastest.

Camera lists can use `{"$analytic":{"type":"orbit","start":0,"end":330,
"count":12,"elevation":25}}`. Appearance lists can use a `values` analytic.
These sequences belong to their publication loops and do not multiply geometry.
Analytic factories are explicitly registered by trusted application code.

`python3 -m schemaxis functions` describes typed runtime calls. For example,
`{"$call":"boundsCentre","args":{"bounds":{"$observe":"source",
"path":["bounds"]}}}` queries freshly observed bounds. Nested calls work.
The in-process function registry also supports typed object arguments/results;
these preserve live identity through `InputContext`. Serializable pipeline value
expressions currently expose the registered pure numeric/vector functions.
Effectful arbitrary Python calls are not scheduled by this interface.

Authored `$expr` composition includes explicit `concat` for two strings or two
arrays. Existing `merge` conflict behaviour remains unchanged. Application
bindings and function import paths are not accepted from authored input.

`schemaxis.workflow/1` chains named operations. A reader argument can reference
`{"$artifact":"earlierOperation","index":0}`. Before reopening it, Schemaxis checks
the producer's receipt and artifact hashes. The index addresses the producer's
ordered artifact list. Geometry and glTF handoffs are supported; saved Blender
scenes can feed `schemaxis.blender.render/1` camera groups. Workflow `plan` reports provisional plans
with artifact resolution deferred; `verify` checks the chain against authored
inputs. This does not transfer live objects across application processes.

Workflow operation documents accept ParaView, FreeCAD solids, Blender geometry/rendering,
Godot, Aseprite, FFmpeg, QGIS, Octave and Calc versions. FreeCAD assemblies also participate through the common runtime. Optional workflow and operation
`execution` settings enable bounded scheduling; the default is one worker.
See [workflow fields, handoff kinds and execution settings](json-input.md#12-workflows-files-and-verification).

See [geometry expansion](adaptor-expansion.md) and
[numerical analysis and spreadsheets](numerical-analysis.md) for the newest
operations, qualified versions and runnable cross-application examples.

## Blender vertical slice

The experimental Blender adaptor uses the same master/active graph, typed object
lookup, analytic bindings, runtime expressions and invalidation rules. Its 37
operations cover materials, primitives, mesh modifiers and assembly, transforms,
and glTF/STL/PLY/CSV import. Current native verification and execution target
Blender 5.2.2. Procedural grids, disks, tubes and rotational profiles are included.
No Blender imports occur during discovery or planning.

```bash
python3 -m schemaxis discover
python3 -m schemaxis describe --provider blender
python3 -m schemaxis plan examples/schemaxis/blender-showcase.json
python3 -m schemaxis run examples/schemaxis/blender-showcase.json \
  --blender /path/to/blender --output-directory blender-run
python3 -m schemaxis verify blender-run
python3 -m schemaxis inspect examples/schemaxis/blender-showcase.json --node rounded \
  --visit 1 --blender /path/to/blender --output-directory inspected
python3 -m schemaxis run examples/schemaxis/paraview-to-blender.json \
  --paraview-root /path/to/ParaView/install --blender /path/to/blender \
  --output-directory application-bridge
```

`SCHEMAXIS_BLENDER` can supply the executable. Blender currently accepts one scene
and one image writer, supports CPU/CUDA/OPTIX Cycles rendering, and saves a `.blend` per geometry
state after its final camera view. Bevel width is measured in the mesh's local
coordinates. Automatic orthographic framing accounts for image aspect ratio and
checks projected bounds. An explicit Blender camera `scale` is its horizontal
orthographic span; ParaView's scale convention is different. CPU is the default; select GPU using scene `render.device`. Discovery lists render
settings. Native animation keyframes, arbitrary modifiers and geometry nodes are
not exposed yet.

`scenes[0].meshes` declares STL exports. `prepareOnly:true` skips image rendering
while retaining scene preparation and verification; saved batch scenes can feed
separate `schemaxis.blender.render/1` camera groups.

Saved scenes are reopened in a fresh Blender process. Receipts compare evaluated
mesh geometry, material/shader state for declared materials, transforms and the
saved camera; images are decoded and checked for dimensions/nonuniform pixels.
Host checks include authored values, camera direction/position/projection,
publication counts/hashes, object reuse and lifecycle/invalidation events.
This is bounded scene verification, not perceptual rendering certification.

The bridge imports a single-mesh glTF 2.0 JSON scene with embedded resources.
Blender performs its glTF coordinate conversion; no physical unit inference or
lossless transfer of CFD fields is claimed. The demonstration verifies a radius-two
sphere's world bounds and volume, not every possible glTF material or transform.

The `inspect` command also works on ParaView input documents. It returns native
observations for an explicit node and zero-based selected visit, without rendering
or exporting geometry. Its result is an observation record, not a publication
verification receipt.

## Showcase acceptance

`examples/schemaxis/showcase-acceptance.json` combines input composition, an inline
object, three synchronized members, an independent slice sequence, runtime
function-derived positioning, two appearances and twelve orbit views. The native
run produced exactly 24 geometry exports and 576 images. Independent checks:

```bash
python3 examples/schemaxis/check_showcase.py path/to/showcase-run
python3 examples/schemaxis/check_blender.py path/to/blender-run
python3 examples/schemaxis/check_blender.py path/to/bridge/presentation --bridge
```

The expanded implementation also passed the existing seven-run native acceptance
suite, including both real CFD cases, and its seven expected-failure scenarios.
See `verification/2026-09-15.json` and the dated session note for exact evidence.

## Remaining parity and production work

This is a substantial working expansion, not a claim of complete coverage.
Remaining work includes wider option/type coverage per filter, richer legends and
lighting, runtime-dependent sequence lengths and scene membership, additional readers and writers,
remaining native helper-proxy bindings, broader MPI qualification and large-scale performance work.
See AGENTS.md for current development boundaries. Historical reference notes are
not a retrospective clean-room provenance claim.

### Human input and adaptor discovery

The [vehicle human template](../examples/paraview-vehicle-demo/humanInput.json)
keeps seven measured coordinates in `dimensions` and derives wake bounds, slice
positions and camera framing with declared spatial functions. It zooms without
clipping. Read the [human-input guide](human-input.md).

Application implementations are grouped under `schemaxis/adaptors/paraview`,
`blender`, `freecad`, `godot` and `aseprite`. Shared validation, cameras and artifact packaging remain
in the core; earlier import paths are compatible aliases. Each app owns an
`adaptor.json` manifest. Installed adaptor folders are discovered automatically;
CLI, schemas, workflows and console operations use the same registry. Adding an
app does not require editing framework routing tables.

`schemaxis query INPUT` reports required adaptors; `schemaxis query --operations foam
slice contour` searches declared capabilities. `schemaxis reference` rebuilds schemas,
references and a static module index; `schemaxis reference --check` checks drift.
See [adaptor development and discovery](adaptors.md).

Adaptors for private or third-party applications can be installed separately as
[external adaptor packages](adaptor-development.md); the registry discovers
them in the same way as the adaptors shipped here.

### Bounded parallel execution

Workflows can now opt into resource-aware concurrent operation scheduling, contiguous
explicit-timestep batches and verified retries with `schemaxis run --resume`. Blender
supports preparing a saved scene once and rendering separate camera groups from it.
ParaView MPI now supports a qualified CFD pipeline with native distributed volume
and slice publication, global reductions and verified parallel-file handoff. The
1.23-million-cell 004 tutorial passed on two local ranks. See
[parallel execution](parallel-execution.md) for runnable examples, resource
settings, evidence and current limits.

### FreeCAD solids and cross-application examples

A bounded FreeCAD 1.1.x feature adaptor exposes primitive solids, booleans,
sketches, extrusion/revolution, fillet/chamfer and STEP input. It retains an editable
native feature tree, exports STEP and STL from solid outputs, and
reopens all three in a fresh process. The mounting bracket and flanged pipe examples
continue through ParaView to Blender with explicit coordinate and unit conversion.
See [examples, commands and verification](freecad-examples.md).

### Expanded CAD and mesh workflows

FreeCAD exposes 18 feature operations including polygon and constrained
rectangle/circle sketches, extrusion, revolution, loft, list unions, fillet/chamfer, solid intersection
and STEP input. Its separate assembly document supports linked parts and fixed
joint trees. Blender exposes 37 operations,
including direct STL/PLY import, mesh joining/welding, deformation, shrinkwrap and
voxel remeshing. Native STL publication enables Blender → ParaView handoff.
The new examples cover a housing with a STEP editing stage, extruded and turned
parts, a mesh-processing workshop and an analytic deformation sweep.
See [CAD and mesh workflows](cad-and-mesh-workflows.md).

## Schemaxis Studio and the multi-adaptor console

`PYTHONPATH=src python3 -m schemaxis console --workspace .schemaxis-studio --web`
starts **Schemaxis Studio**, a local browser interface over the same durable
multi-document session used by the terminal console. Open its printed loopback
URL with the session token. The interface has light/dark themes, role modes,
a command palette, Problems and Jobs panels, and separate windows for each task.

ParaView's **Add Input**, **Add Source**, **Add Filter**, **Add Output** and
**Presentation & controls** catalogue exposes every declared operation in
Workbench and Schema Editor. Configuration windows expose required and optional
settings, nested proxy choices and inline Help; blanks remain fillable placeholders.
Adaptor-owned `guidance.json` now connects conceptual descriptions, assumptions
and examples to Add forms and property Help across registered adaptors. Missing
text remains explicit and can be exported for review; see the
[guidance coverage and contribution guide](studio-guidance-review.md).
Diagnostics include JSON addresses and line/column. Start with the
[Studio guide](studio-guide.md); adaptor authors must follow the
[Studio adaptor contract](studio-adaptor-contract.md).

**Workflow Designer** connects instances through named ports, exposes parameters,
and exports reusable template bundles. **Adaptor Workbench** combines input JSON,
schemas, snippets, properties and declared viewers. **Schema Editor** opens JSON,
saves workspace drafts and exports files. **Case Runner** binds an exact template
case, plans it, executes through the existing workflow scheduler, verifies it and
presents named outputs. **Application Setup** locates native applications in the
Admin interface mode; role modes are not separate security accounts.

Canvas changes and explicit editor saves use revision-checked workspace history.
Standalone source and case writes detect external changes. Viewers support 3D,
images, tables and text/grep within their declared formats. Workbench pick chips
carry inspectable selection metadata; they do not imply a universal native
selection contract or execute natural-language instructions.

Acyclic designs compile to ordinary workflows. Feedback loops can be drawn and
configured, but native coupled-loop execution remains design-only pending a
separate review and qualification. Sample attachments stay in their window and
are excluded from exported templates.

See the [Studio guide](visual-console.md),
[runnable Studio starter](../examples/studio/README.md) and
[console command guide](console.md) for launch, save behaviour, configuration,
security and current limits. Omit `--web` to use the terminal console.

New bounded adaptors cover [Godot scenes](godot.md) and
[Aseprite sprites/animation](aseprite.md). FreeCAD additionally supports
constrained rectangle/circle sketches and [fixed assemblies](freecad-assemblies.md).

### Media and geospatial workflows

Scheduled Aseprite/Godot handoffs now support image and sprite-sheet publications.
Godot embeds PNGs as editable Sprite3D textures with fresh-process pixel readback.
A bounded FFmpeg adaptor publishes H.264/FFV1 videos from PNG sequences or timed
sprite sheets and checks native decoded pixels, frame order/count and duration.
See [media workflows](media-workflows.md).

A bounded QGIS adaptor imports single-layer GeoJSON/GeoPackage, reprojects,
buffers in projected metre coordinates and clips to a rectangle. It publishes an
editable QGIS project, verified GeoPackage and optional PNG map. See
[QGIS contracts and examples](qgis.md). This is vector GIS, not raster/terrain
or complete QGIS coverage. Qualification is recorded separately under `verification`.

### ParaView authoring reference

The [detailed ParaView adaptor guide](paraview-guide.md) covers inputs,
outputs, execution flow charts and examples. Its [complete operation appendix](paraview-operation-reference.md)
lists all 645 registered identifiers and their typed options. The separate
[shared dollar syntax reference](dollar-reference.md) covers authoring
references, calculations, analytics and verified workflow handoffs.
