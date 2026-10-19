# Schemaxis JSON input — current reference

Updated 2026-10-17 against the current working code. This page covers the input
language; the generated appendices cover every registered option.

A file declares an application task or workflow; graph routes use
**nodes → connections → outputs**. Use ordinary JSON: double
quotes, no comments, no trailing commas. Omitted options use declared defaults.

[Basic examples](#2-complete-paraview-example) · [All options](#7-complete-option-reference) ·
[Scenes](#8-scenes-cameras-and-publication-rules) · [Times](#9-simulation-times) ·
[Composition](#10-document-reuse-and-authored-calculations) ·
[Runtime expressions](#11-runtime-values-and-observations) ·
[Workflows](#12-workflows-files-and-verification) · [Schemas](#13-generated-schemas-and-extension-framework)

## 1. Basic structure

The adaptors and workflow envelope accept the document versions below.
Choose the version before choosing fields; these are not interchangeable
schemas.

| `version` | Application / purpose | Main document fields |
| --- | --- | --- |
| `schemaxis/1` | ParaView data pipeline | `nodes`, `scenes`; optional axes, times and authoring data |
| `schemaxis.blender/1` | Blender mesh/material pipeline | `nodes`, `scenes`; optional axes, times and authoring data |
| `schemaxis.blender.render/1` | Render cameras from a saved Schemaxis Blender scene | `sceneFile`, `cameras`; optional `size`, `render` |
| `schemaxis.freecad/1` | FreeCAD features and solids | `nodes`, `output`; optional `units`, `linearDeflection`, `dimensions`, `definitions`, `settings` |
| `schemaxis.freecad.assembly/1` | FreeCAD fixed-joint assembly | `parts`, `components`, `grounded`, `joints`; optional `units`, `dimensions`, `definitions`, `settings` |
| `schemaxis.godot/1` | Godot editable 3D project | `nodes`; optional `units`, `preview` |
| `schemaxis.aseprite/1` | Aseprite editable sprite/animation | `nodes`, `output` |
| `schemaxis.ffmpeg/1` | PNG/sprite-sheet video publication | Exactly one `nodes` entry; optional `deliverable` requirements |
| `schemaxis.inkscape/1` | Measured editable technical diagrams | `operation`, page `width`/`height`, `boxes`, optional `links` and layout budgets; see [diagram guide](inkscape.md) |
| `schemaxis.shotcut/1` | Verified cuts and editable video project bundles | One `editTimeline` node with named `assets` and ordered `clips`; see [timeline guide](shotcut.md) |
| `schemaxis.premiere/1` | Experimental read-only sequence inspection; native qualification pending | `sequenceContract` checks ordered source ranges; `sequenceLayout` checks complete named tracks, timeline ranges and coverage requirements; see [Premiere guide](premiere.md) |
| `schemaxis.cantera/1` | Ideal-gas thermodynamics, TP/HP equilibrium and closed adiabatic reactor histories | Two ordered `nodes`, `output`; see [chemistry guide](cantera.md) |
| `schemaxis.ngspice/1` | Linear DC/AC circuits and first-order RC transients | `operation`, `circuit`, sweep parameters, optional sampled `requirements`; see [circuit guide](ngspice.md) |
| `schemaxis.gmsh/1` | Single-solid tetrahedral meshing | `units: "mm"`, two ordered `nodes`, `output`; see [meshing guide](gmsh.md) |
| `schemaxis.calculix/1` | Checked linear-elastic cantilever | `operation: "cantileverBeam"`, `beam`, `material`, `load`; optional `mesh`, `requirements`; see [structural guide](calculix.md) |
| `schemaxis.qgis/1` | Bounded vector GIS | `nodes`, `output`; optional `preview` |
| `schemaxis.octave/1` | Bounded 1D numerical analysis | Ordered `nodes`, selected `outputs`; see [analysis guide](numerical-analysis.md) |
| `schemaxis.r/1` | Checked additive numeric regression and optional classical coefficient inference | `operation: "linearRegression"`, `predictors`, `response`, `training`; optional `heldout`, `intercept`, `inference`, `requirements`; see [regression guide](r.md) |
| `schemaxis.calc/1` | Recalculated XLSX/ODS numeric workbook | One `nodes` entry; optional named `requirements`; see [workbook guide](calc.md) |
| `schemaxis.kicad/1` | Two-layer board inspection, DRC and Excellon drills | `operation`, `board`; operation-specific finding limits and drill options; see [board guide](kicad.md) |
| `schemaxis.imagej/1` | Calibrated grayscale particle measurements | `operation: "analyzeParticles"`, `image`, `calibration`, `threshold`; optional connectivity, hole, edge and area settings; see [imaging guide](imagej.md) |
| `schemaxis.prusaslicer/1` | Bounded FFF slicing with independent G-code checks | `operation: "sliceModel"`, `model`, `printer`, `material`, `print`; see [slicing guide](prusaslicer.md) |
| `schemaxis.pandoc/1` | Structured report to HTML and DOCX | `operation: "report"`, `title`, ordered `sections` with paragraph/table/image blocks; see [report guide](pandoc.md) |
| `schemaxis.gnuplot/1` | Numeric CSV plots to SVG and PNG | Declared series, axes, units and optional symmetric errors; see [plot guide](gnuplot.md) |
| `schemaxis.sqlite/1` | Typed relational summaries | `operation: "summarise"`, captured table declarations, keys and bounded join/filter/group query; see [SQLite guide](sqlite.md) |
| `schemaxis.mupdf/1` | Ordered PDF page review | `operation: "review"`, `source`, `pages`, `dpi`, `rotation`; see [PDF guide](mupdf.md) |
| `schemaxis.qpdf/1` | Bounded PDF page assembly | `operation: "assemble"`, named `sources` and ordered `pages` with repeats and relative quarter turns; see [assembly guide](qpdf.md) |
| `schemaxis.imagemagick/1` | Exact PNG preparation and sheets | `operation: "raster"`, `images`, explicit colour/alpha policy and optional `sheet`; see [raster guide](imagemagick.md) |
| `schemaxis.sox/1` | PCM16 audio assembly | `operation: "assemble"`, ordered `clips` with source frames, gain and fades; see [audio guide](sox.md) |
| `schemaxis.graphviz/1` | Automatic directed graph layout | `operation: "layout"`, named `nodes` and `edges`, optional rank direction and cycle policy; see [graph layout guide](graphviz.md) |
| `schemaxis.meshio/1` | ASCII VTU/VTK mesh interchange | `operation: "convert"`, `source`, explicit source/target formats and coordinate units, strict loss policy; see [mesh interchange guide](meshio.md) |
| `schemaxis.gdal/1` | Georeferenced raster windows | `operation: "window"`, `source`, source window and output grid dimensions, matching CRS/units/nodata assertions; see [raster window guide](gdal.md) |
| `schemaxis.openscad/1` | Dimensioned plates and spacers | `operation: "plate"` or `"spacer"`, matching dimensions, `units: "mm"`, optional polygon segments and translation; see [part guide](openscad.md) |
| `schemaxis.workflow/1` | Verified artifact/value handoffs between supported pipelines | `operations`; optional `execution`, `dimensions`, `definitions`, `settings`, `axes`, `maxStates` |

The shared graph format below applies to **ParaView and Blender pipelines**.
FreeCAD, Godot and Aseprite have their own ordering and output rules, described
after the Blender example. Workflow membership is narrower than standalone
adaptor support; see [section 12](#12-workflows-files-and-verification).

| Key | Meaning |
| --- | --- |
| `version` | `schemaxis/1` for ParaView; `schemaxis.blender/1` for Blender |
| `nodes` | Required nonempty list of sources, materials and processing operations |
| `scenes` | Required nonempty list: what to show/export, and how to photograph it |
| `axes` | Optional parameter sweeps |
| `definitions` | Optional reusable JSON data, accessed with `$document` |
| `dimensions`, `views`, `settings` | Optional named authoring data for dimension-driven inputs |
| `times` | Optional ParaView simulation times, e.g. `[0, 1, 2]` |
| `maxStates`, `maxPublications` | Optional limits on expansion/output counts |

Each node has a unique `id`, a declared `filter`, and optional `inputs` and `options`:

```json
{"id":"rounded", "filter":"bevel",
 "inputs":{"input":"box"}, "options":{"width":0.1, "segments":3}}
```

`rounded` is your name; `bevel` is Schemaxis's operation name; `input` is its port
name; `box` names another node. Some operations use other ports, such as
`material`, `seed` or `operand`. In the shared ParaView/Blender graph, unused nodes
do not execute. This pruning rule does not describe the other adaptors' ordered
feature or mutation lists.

## 2. Complete ParaView example

Slice a generated dataset, save its geometry, and render an image:

```json
{
  "version": "schemaxis/1",
  "nodes": [
    {"id": "data", "filter": "wavelet"},
    {"id": "cut", "filter": "slice", "inputs": {"input": "data"},
     "options": {"normal": [0, 0, 1], "origin": [0, 0, 0]}}
  ],
  "scenes": [{
    "id": "section",
    "geometry": ["cut"],
    "visible": {"cut": {"colour": "steelblue"}},
    "images": [{"id": "view", "size": [640, 480],
                "cameras": [{"direction": [1, -1, 1]}]}]
  }]
}
```

ParaView scene fields:

| Field | Example / purpose |
| --- | --- |
| `geometry` | `["cut"]` — export native dataset geometry |
| `visible` | `{"cut":{"colour":"steelblue"}}` — objects and appearance |
| Field colouring | `{"cut":{"field":["POINTS","RTData"],"range":[0,300]}}` |
| `images` | Image writers; `size` is `[width, height]` in pixels |
| `cameras` | List of views; `direction` specifies the side to view from; framing is automatic |
| `measurements` | `[{"node":"cut"}]` — export point-field tables |
| `gltf` | `true` — export the visible scene using the bounded glTF exporter |
| `exports` | Declared writer publications with explicit node, writer, options and readback contracts; see the [catalogue guide](paraview-catalogue.md) |

For geometry-only work, omit `visible` and `images`.

## 3. Complete Blender example

Create a material, a cube and a bevelled result; save a `.blend` and image:

```json
{
  "version": "schemaxis.blender/1",
  "nodes": [
    {"id": "paint", "filter": "material",
     "options": {"colour": [0.05, 0.3, 0.8, 1], "roughness": 0.35}},
    {"id": "box", "filter": "cube", "inputs": {"material": "paint"},
     "options": {"size": 2}},
    {"id": "rounded", "filter": "bevel", "inputs": {"input": "box"},
     "options": {"width": 0.1, "segments": 3}}
  ],
  "scenes": [{
    "id": "demo",
    "visible": ["rounded"],
    "render": {"device": "CPU", "samples": 16},
    "images": [{"id": "view", "size": [640, 480],
                "cameras": [{"direction": [1, -1, 1]}]}]
  }]
}
```

Blender uses a **list** for `visible`; appearance comes from material nodes.
Currently it accepts one scene and one image writer, with multiple cameras.
Use `"device":"OPTIX"` on the installed NVIDIA setup, or `"CUDA"`; CPU is the default.

`scenes[0].meshes` optionally lists nodes to export as native STL publications.
`prepareOnly:true` skips image rendering but still needs the image writer and
cameras to establish the saved scene. It publishes `.blend` files and any declared
STLs. See [CAD and mesh workflows](cad-and-mesh-workflows.md).

### Saved Blender scenes

`schemaxis.blender.render/1` takes `sceneFile` (a saved Schemaxis batch `.blend`),
1–1000 literal `cameras`, optional `[width,height]` `size` (default `[320,240]`,
each dimension 32–2048), and optional `render`. It has no `nodes`, `scenes`, axes
or time visits. Within a workflow, `sceneFile` may be an `$artifact` reference to
a scene publication. This contract renders images without rebuilding geometry;
it is not a general importer for arbitrary Blender files or console live saves.
See [saved-scene render groups](parallel-execution.md#blender-prepare-once-render-view-groups).

### FreeCAD features and assemblies

`schemaxis.freecad/1` accepts 1–200 nodes in dependency order. Every input must name
an earlier node of the declared kind. `output` names the result; normal batch
planning requires a solid. `units` defaults to `mm` and accepts only `mm`.
`linearDeflection` is 0.001–1 mm, default 0.1, for tessellation. Pure authored
references/functions resolve before typed feature validation; runtime sweep
markers and the shared graph's inline node construction are not part of this
feature contract.

There are 16 declared operations: primitive solids, booleans, polygon and
constrained rectangle/circle sketches, extrusion, revolution, fillet/chamfer and
STEP import. Profile outputs are supported by the live console's preview path;
that does not make a profile-only document a solid batch publication. Solid runs
produce verified `model.FCStd`, `model.step` and `model.stl` files. See
[FreeCAD examples](freecad-examples.md) and the
[operation reference](generated/freecad-operations.md).

`schemaxis.freecad.assembly/1` is a separate envelope, with 1–32 primitive `parts`,
2–32 linked `components`, one `grounded` component and a rooted tree of fixed
`joints`. Inputs use mm; joints reference declared component cap faces rather
than assuming native `FaceN` numbering. It produces an editable assembly FCStd,
not the ordinary feature pipeline's STEP/STL set. Optional CLI `--freecad-gui`
adds native GUI task-editor setup and image evidence. Other joint types, imported
parts and live assembly execution are unsupported. See the complete
[assembly contract and example](freecad-assemblies.md).

### Godot scenes

`schemaxis.godot/1` accepts 1–128 literal nodes, optional `units:"m"` and optional
Boolean `preview` (default false). Inputs reference earlier nodes. Declare at
least one geometry or sprite node and exactly one camera; every material must be used.
Node IDs match `[A-Za-z][A-Za-z0-9_]{0,63}`. Coordinates are metres with Y up.
The nine operations are `material`, `box`, `sphere`, `cylinder`, `plane`,
`readGLTF`, `sprite3D`, `camera` and `directionalLight`. `readGLTF` requires an absolute
`.gltf` path and the adaptor's bounded import contract; GLB is unsupported.

Runs retain an editable project and scene, with a fresh-process native reopen.
`preview:true` additionally captures a PNG in a graphical process; headless
construction alone does not provide a screenshot. There is no authored script,
general physics or shared graph expression contract. Scheduled workflows are supported;
`sprite3D` consumes PNG image/sprite-sheet artifacts (see [media workflows](media-workflows.md)).
See [Godot input, output and preview details](godot.md).

### Aseprite sprites and animation

`schemaxis.aseprite/1` accepts only `version`, `nodes` and `output`. Start with one
`sprite` node; every later node's `inputs.sprite` must reference the immediately
preceding node, and `output` must name the final node. The eight operations are
`sprite`, `layer`, `frame`, `palette`, `pixel`, `rect`, `circle` and `tag`.
Canvas coordinates are zero-based pixels; frame and tag indices are one-based.
Colours are integer RGBA bytes, restricted to opaque colour or transparent
`[0,0,0,0]`. Branching, partial alpha and authored Lua are unsupported.

Limits include 256 nodes, 256×256 canvas, 16 layers, 32 frames and 262144 total
canvas×layer×frame pixels. Runs publish `sprite.aseprite`, first-frame
`preview.png`, horizontal `sheet.png` and `sheet.json`; verification compares
native readback with an independent host raster model. See the
[complete sprite contract](aseprite.md).

## 4. Vary a parameter

For a ParaView or Blender pipeline, add this top-level field:

```json
"axes": [{"name":"height", "values":[-2, 0, 2]}]
```

Then replace the slice's `origin` option with:

```json
"origin": [0, 0, {"$axis":"height"}]
```

This produces three states. Options referencing the **same axis** change together;
different axes produce combinations. A regular sequence can use
`"series":{"start":-2,"end":2,"count":3}` instead of `values`.

Alternatively, put a sequence directly in an option:

```json
"size": {"$analytic":{"type":"linear", "start":1, "end":3, "count":3}}
```

Add the same `"sync":"shape"` inside multiple `$analytic` specifications to
advance them together. See [the synchronized Blender example](../examples/schemaxis/blender-showcase.json).

## 5. Useful value forms

| Value | Meaning |
| --- | --- |
| `{"$axis":"height"}` | Current value of a named axis |
| `{"$time":true}` | Current selected time |
| `{"$observe":"box","path":["bounds",0]}` | Upstream minimum X coordinate |
| `{"$calc":"midpoint","args":[{"$observe":"box","path":["bounds"]}]}` | Upstream bounding-box centre |
| `{"$sample":"probe","association":"POINTS","field":"pressure","index":0}` | A field tuple from a ParaView node |

Bounds are `[xmin,xmax,ymin,ymax,zmin,zmax]`. Runtime calculations use declared
functions, not Python. For reusable documents and composition, see
[section 10](#10-document-reuse-and-authored-calculations).

## 6. Find options and check your file

From the repository root:

```bash
export PYTHONPATH=src
python3 -m schemaxis describe slice
python3 -m schemaxis describe bevel --provider blender
python3 -m schemaxis describe rectangle --provider freecad
python3 -m schemaxis describe box --provider godot
python3 -m schemaxis describe sprite --provider aseprite
python3 -m schemaxis discover
python3 -m schemaxis query my-input.json
python3 -m schemaxis plan my-input.json
```

`describe` gives exact ports, option types, defaults and limits. `discover` also
lists the eight provider contracts and their declared operations. `query` reports
declared adaptor requirements, not installation availability or native success.
`plan` checks the file without starting a native application.
See the [command reference](quick-reference.md) for `run` and `verify`.

For several application steps, use `version: "schemaxis.workflow/1"` with an
`operations` list. Each entry has an `id` and a complete `document`; later steps
can reference earlier outputs with `{"$artifact":"stepId","index":0}`.
See [the ParaView → Blender example](../examples/schemaxis/paraview-to-blender.json).

## 7. Complete option reference

The following pages are generated from the **current code**, including every
registered operation, input port, option, type, constraint and default:

- [All ParaView operations](generated/paraview-operations.md)
- [All Blender operations](generated/blender-operations.md)
- [All FreeCAD feature operations](generated/freecad-operations.md)
- [All Godot operations](generated/godot-operations.md)
- [All Aseprite operations](generated/aseprite-operations.md)
- [FreeCAD fixed assembly contract](freecad-assemblies.md)
- [Camera, appearance, rendering and runtime functions](generated/settings.md)

These pages describe Schemaxis's supported subset of each application. Use the JSON
option names shown, not native GUI labels. For example ParaView transform uses
`translate`/`rotate`; Blender transform uses `translation`/`rotation`.

### Names, types and connections

In the shared ParaView/Blender graph, node, scene, writer and axis names match
`[A-Za-z][A-Za-z0-9_-]*`; names are
case-sensitive. Nodes and axes are unique within the pipeline; scene names are
unique; image-writer names are unique within their scene. Nodes may refer forward
to later nodes, but cycles and missing references fail. Input kinds must match:
a Blender material cannot be used where a mesh is expected.
FreeCAD also uses this identifier spelling, but requires earlier-node inputs;
Aseprite requires a linear chain. Godot uses the stricter identifier rule given
above. Do not assume that all providers accept forward references or inline inputs.

A multi-input port takes a nonempty list, e.g. `"inputs":{"input":["a","b"]}`
for ParaView `append`. Single ports take one name. Explicit and inline forms are:

```json
"inputs": {
  "input": {"$object":"box"}
}
```

```json
"inputs": {
  "input": {"$create":{"filter":"sphere", "options":{"radius":2}}}
}
```

An inline `$create` may include an `id`; otherwise Schemaxis generates one. Reusing
an explicit ID requires an identical construction. Inline inputs can nest.

Unknown keys are errors. `null` does not request a default. Numbers must be finite;
booleans are not numbers. Integer options require integer JSON tokens (`3`, not
`3.0`). Constructor options such as reader filenames cannot vary with axes,
observations or time; authored document references may resolve them to constants.

### Direction and colour spellings

Options marked with the `direction` conversion accept a three-number vector,
an axis token (`x`, `x+`, `xp`, `+x`, `x-`, `xm`, `-x`, and equivalents for y/z),
or a direction object. Choose one of `axis`, `vector`, or angles
`azimuth`/`elevation` (an omitted angle defaults to zero); `up` accepts an axis
token or vector and defaults to `z+`.
Azimuth is measured anticlockwise about up, from x+ (y+ when up is along x).
A zero direction is invalid. Camera direction/up also accept these direction spellings.

ParaView colours accept palette names, RGB/RGBA vectors, hex RGB/RGBA (including
short hex), and greyscale strings. Numeric vectors normally use 0–1; all-integer
vectors with a component above 1 use byte notation. Alpha multiplies `opacity`.
Blender material colour is specifically four numbers in 0–1. List names with
`python3 -m schemaxis colours`.

## 8. Scenes, cameras and publication rules

The generated [settings reference](generated/settings.md) lists every camera,
ParaView style and Blender render control. Additional behaviour:

- Camera `direction` points from the focal point **towards the camera**. `up` is
  a view-up reference; the two vectors must be nonzero and nonparallel.
- `bounds` overrides the framing box; `focalPoint` overrides its centre;
  `distance` sets the camera distance. `parallel:false` selects perspective.
- `scale` controls orthographic framing: ParaView uses vertical **half-height**;
  Blender uses horizontal **full-width**. It does not set perspective field of view.
- ParaView image size defaults to 640×480, with each dimension 32–8192.
  Blender defaults to 320×240, with each dimension 32–2048.
- A ParaView field is `["POINTS","name"]` or `["CELLS","name"]`.
  Colour `component:-1` means magnitude; nonnegative values select a component.
  Omitted `range` uses the data range; a constant range is expanded slightly.
  `logScale:true` requires positive colour-range values.
- `preset` is a native ParaView colour-map name; unavailable presets fail at run
  time. `legend` and `legendTitle` control its scalar bar. Solid-colour objects
  do not use field-only settings.

### Appearance and camera sequences

ParaView `appearances` is a nonempty list of overrides for already-visible nodes:

```json
"appearances": [
  {},
  {"cut":{"colour":"tomato", "opacity":0.5}}
]
```

Each entry overlays the base `visible` styles. Membership does not change.
Each appearance is rendered with every image writer and camera. Geometry and
measurement exports occur once per geometry state, not once per appearance/view.

`cameras` and ParaView `appearances` can themselves be `$analytic` sequences.
Use `values` for explicit entries; a camera orbit example is:

```json
"cameras": {"$analytic": {
  "type":"orbit", "start":0, "end":270, "count":4, "elevation":25
}}
```

Angles are degrees; elevation must be strictly between −90 and 90. Orbit cameras
use z-up. These publication sequences cannot use `sync`. Node-option analytics
may use `values` or `linear` (and any built-in sequence whose values fit the option).
Linear endpoints can be finite scalars or matching nonempty vectors. `count:1`
requires equal endpoints. Synchronized option sequences must have equal lengths.

### Expansion and ordering

Only axes used by active node options execute. Multiple independent active axes
form a Cartesian product; the first declared axis varies fastest. Presentation
expressions may reference an axis only if an active node already uses it. Use a
camera sequence for camera-only variation. Observation references add dependencies
and can activate otherwise-unused upstream nodes.

Default budgets: `maxStates:10000`, `maxPublications:10000`. State count is selected
times × active-axis combinations. Publication counts per state:

- ParaView: geometry outputs + measurements + appearances × (glTF output + all
  camera views across all image writers) + declared writer exports. The publication
  budget sums all scenes.
- Blender: one `.blend` + all camera images + declared STL mesh exports;
  `prepareOnly:true` omits the camera images.

Order is time → scene → geometry state → geometry/measurements → appearance →
glTF/images/cameras. The planner reports counts before execution. Shared nodes
retain identity; changed upstream data invalidates dependants. This sweep mechanism
is not Blender keyframe animation.

## 9. Simulation times

`times` defaults to `[0.0]`. Supply a nonempty array of finite values for explicit
times. ParaView also accepts an inspection request against a declared source
exposing native `TimestepValues`, including an OpenFOAM reader:

```json
"times": {"source":"case", "select":{"latest":2}}
```

`select` accepts the string `"latest"` or `"first"`, or an object containing
exactly one selector:

| Selector | Meaning |
| --- | --- |
| `"latest":2`, `"first":2` | Last/first n stored times |
| `"values":[0.1,0.5]` | Nearest stored times; optional `tolerance` limits difference |
| `"valueRange":[0.1,0.5]` | Inclusive time interval |
| `"indices":[0,3]` | Zero-based stored-time positions |
| `"indexRange":[0,3]` | Inclusive index interval |

Duplicate selected times are removed. Empty selections fail. `plan` reports
`TIME_INSPECTION_REQUIRED`; `run` inspects the source, resolves the selection and
checks the final budget. Blender has explicit visit times but no corresponding
native animation-time binding. Temporal-statistics filters use their own native
available-time semantics, not an implicit restriction to outer publication times.

## 10. Document reuse and authored calculations

The [common adaptor runtime](adaptor-runtime.md) supplies document references,
closed expressions and finite analytics across registered application routes.
Workflow envelopes accept shared `dimensions`, `definitions` and `settings`,
plus bounded `axes` and `maxStates`. A reference with `"scope":"workflow"`
selects this shared context. Arbitrary authoring containers remain unsupported.

Top-level `definitions` stores reusable JSON. A marker replaces a complete value:

```json
"options": {"$document":"/definitions/sphereOptions"}
```

Pointers address **this document**, not files or URLs. Absolute paths use JSON
Pointer escaping: `~1` for slash, `~0` for tilde. `./` and `../` are relative to the
marker's containing object/array at its definition site. References retain their
JSON type; cycles, missing targets and excessive expansion fail. Expansion is
bounded to 100000 visited values and depth 128.

`$expr` computes authored values **before** graph planning. It is distinct from
runtime `$calc`/`$call`. Every current authored operation takes exactly two `args`:

```json
"options": {"$expr": {
  "op":"overlay",
  "args":[{"$document":"/definitions/sphereOptions"}, {"radius":2}]
}}
```

| `op` | Behaviour |
| --- | --- |
| `overlay` | Shallow object overlay; right wins |
| `merge` | Recursive object merge; arrays/scalars are atomic |
| `omit` | Remove direct keys listed by an array or object's keys |
| `get` | Object-key or nonnegative array-index lookup |
| `concat` | Concatenate two strings or two arrays |
| `namedMerge` | Merge arrays of objects by their `name` member; preserve left order, append new names |
| `namedGet` | Get a named object from such an array |
| `add`, `subtract`, `multiply`, `divide` | Scalar arithmetic |

`merge`/`namedMerge` accept `"conflict":"left"` (default), `"right"` or `"error"`.
Named collections reject duplicate names. These names are a composition convention;
they are not automatically node `id` values. Neither expression mechanism executes
Python, imports code, or reads external documents.

### Regular axis series

An axis `series` supports `start`, `end`, `spacing`, `count`, `padding` and
`paddingFraction`. Normally supply exactly three of the first four to derive the
fourth; all four is an error. A one-position series can use one endpoint and
`count:1`. Schemaxis's explicit axes supply no dataset bounds: missing endpoints
cannot be inferred from geometry, and the padding controls have no bounds to inset.
`padding` and `paddingFraction` are alternatives. With start/end/spacing, spacing
is oriented towards the end and the last sample stops short if the interval is
not an exact multiple. Use `values` for irregular positions, or start/end/count
to include both endpoints.

## 11. Runtime values and observations

This section describes the shared ParaView/Blender geometry graph, not every
adaptor's native readback or receipt format.

`$observe`, `$sample`, `$calc` and `$call` work inside node options; presentation
styles/cameras can also query current upstream results. Constructor options are
constant. Blender does not support `$sample`. Render settings are literal after
composition, not runtime expressions.

`$calc` uses positional `args`:

| Operation | Arguments | Result |
| --- | --- | --- |
| `vector` | Three finite scalars | Three-component vector |
| `midpoint`, `boundsMin`, `boundsMax` | One six-value bounds array | Three-component vector |
| `add`, `subtract`, `multiply`, `divide`, `min`, `max` | Two values | Scalar or matching component array; scalar broadcasting supported |

`$call` uses **named** arguments and a registered typed function:

```json
{"$call":"boundsCentre", "args":{
  "bounds":{"$observe":"sphere","path":["bounds"]}
}}
```

Functions include `boundsCentre`, `vectorLength`, `sinDegrees`, `rangeCentre`
and the spatial helpers listed below; exact arguments/results are in the generated settings reference
and `python3 -m schemaxis functions`.

Observations available to `path`:

| Provider/object | Members |
| --- | --- |
| ParaView dataset | `points`, `cells`, `bounds`, `fields` |
| `fields.POINTS.<name>` / `fields.CELLS.<name>` | `components`, `range` (or null for a nonfinite/empty range) |
| Blender mesh | `kind`, `points`, `cells`, `bounds`, `signedVolume`, `geometrySha256` |
| Blender material | `kind`, `colour`, `shaderColour`, `shaderAlpha`, `roughness`, `metallic`, `ior` |

`path` is a list of dictionary keys/array indices, e.g.
`["fields","POINTS","pressure","range",1]`; omitted path selects the whole
observation. `$sample` additionally accepts `component` and a `block` path of
zero-based multiblock indices. Tuple indices are not persistent physical IDs.
Blender volume is evaluated signed mesh volume; it is not a general solid-validity
check. Degenerate, overlapping or open meshes require care interpreting it.

## 12. Workflows, files and verification

A workflow accepts `version`, `operations` and optional `execution`, `dimensions`,
`definitions`, `settings`, `axes` and `maxStates`. Every
operation accepts `id`, a complete `document`, and optional per-operation
`execution`. Permitted application versions are derived from each registry route's
`workflow` flag; this includes FreeCAD assemblies. Nested workflows are unsupported. Registration does not establish
native qualification; see [the common runtime](adaptor-runtime.md).

`$artifact` must name an earlier operation and a nonnegative index in its ordered
verified artifact list. The list is concatenated in batch order, not completion
order. Handoffs recheck producer receipts and hashes before supplying filenames;
native object handles never cross processes. Artifact kinds must match consumers:

| Consumer | Accepted handoff |
| --- | --- |
| ParaView or Blender geometry pipeline | `geometry` or `gltf`, including declared Blender STL mesh exports |
| FreeCAD feature pipeline | `cad`, such as STEP from a prior FreeCAD operation |
| Blender saved-scene renderer | `scene`, supplied as `sceneFile` |
| Godot | Bounded `gltf`; PNG `image` or `spriteSheet` |
| FFmpeg | PNG `image`/`spriteSheet`; `spriteMetadata` JSON |
| QGIS | Single-layer `geospatialVector` GeoPackage |

A `.blend` from a Blender geometry operation can therefore feed a saved-scene
renderer. Godot accepts `image`/`spriteSheet` PNGs and bounded `gltf`; FFmpeg accepts
`image`, `spriteSheet` and `spriteMetadata`. QGIS accepts `geospatialVector`.
See [media workflows](media-workflows.md) and [QGIS](qgis.md) for ordered publications. Check the producer's ordered receipt
rather than assuming artifact index zero has the desired type.

### Scheduling and execution settings

Without an explicit concurrency budget, the default is one worker. Independent
operations may overlap when `execution.maxWorkers` is increased; jobs wait for
all referenced producer operations to complete and verify. The authored operation
list remains a dependency order, not a mandatory serial schedule.

| Location | Keys and defaults |
| --- | --- |
| Workflow `execution` | `maxWorkers:1`, `cpus`: host logical CPU count, `memoryMB:8192`, `gpus:1` (only 0 or 1) |
| Operation `execution` | `threads`: 1 for ParaView/FreeCAD or Blender render threads; `ranks:1`; optional absolute `mpiexec`; `memoryMB:1024`; `gpus`: 1 for GPU rendering, otherwise 0; optional `timeChunkSize` |

Blender's thread reservation must match `render.threads`. MPI ranks greater than
one are supported only for qualified ParaView pipelines and require `mpiexec`.
Memory and CPU reservations guide admission; they are not OS-enforced memory or
affinity limits. `timeChunkSize` splits explicit ParaView/Blender geometry times
into contiguous batches after checking the full expansion budget. It does not
split analytic axes, inspect times automatically, or apply to CAD/saved-scene
render jobs.

On failure, the scheduler stops admitting jobs and cancels running siblings,
retaining completed verified attempts. `schemaxis run WORKFLOW --output-directory
EXISTING_RUN --resume` requires the unchanged authored workflow and rechecks
reusable attempts; it is not a general-purpose cache for external datasets.
See [execution, retries and native MPI limits](parallel-execution.md) and
[the complete camera-group workflow](../examples/schemaxis/blender-render-groups.json).

Use absolute input paths for replay. Relative resource paths are not automatically
relative to the JSON file. VTM resources must accompany their master file. Readers
have format-specific limits; the Blender glTF reader accepts one mesh object from
glTF 2.0 JSON with embedded buffer/image resources. No physical-unit inference or
lossless CFD-field transfer through glTF is promised.

Use a fresh output directory for a new `run`; an existing directory is used only
through the supported workflow `--resume` path. Creating the parent explicitly
works across adaptors. Keep the complete
run directory: input, plan, runtime snapshot, receipts and artifact companions.
ParaView XML exports are reopened and compared; Blender scenes are reopened in a
fresh process. Images are checked for dimensions/content, not artistic correctness.
`verify` rechecks retained evidence and file hashes; it does not rerun the native
applications. `inspect --node NAME --visit N` obtains native observations for that
node's selected dependency closure; its visit index is local to that selection.
An inspection result is not a publication verification receipt. CLI node
inspection is supported for ParaView, Blender geometry and FreeCAD features,
not Godot, Aseprite, FFmpeg, QGIS, saved-scene rendering, assemblies or workflow envelopes.

### Console documents and native checkpoints

`schemaxis console` (alias `schemaxis`) provides durable, multiple-document authoring
for the registered adaptors; `--web` adds the loopback visual companion. Draft authoring
is not a substitute for the complete provider plan required by a native preview.
Persistent live sessions are available for FreeCAD features, Blender and ParaView;
other native previews use their provider's batch path. Assemblies have a batch
preview path, not a live assembly worker.

Only a current, verified native checkpoint can be saved as a native artifact.
Authored JSON, live geometry snapshots, PNGs and native scenes have different
verification scopes. In particular, live `.blend` save checks native library
membership, and `.pvsm` save checks state structure/proxy membership; the latter
references external datasets without copying them. These do not imply the batch
pipeline's full independent-reopen contract. See the [user guide](user-guide.md),
[console command guide](console.md) and [visual console guide](visual-console.md)
for lifecycle, revision, save and recovery rules.

## 13. Generated schemas and extension framework

The [schema guide](schema-guide.md) explains export, expansion and regeneration.
Operation option schemas and the full option reference derive from the same
Python dictionaries used by the runtime. Camera, style and render schemas likewise
reuse their actual declarations. Adding an operation option updates the next export.

For editor validation of authored input, export the standalone umbrella covering
all ten routed versions, or select one provider/version:

```bash
schemaxis schema --all > schemaxis-authored.schema.json
schemaxis schema --authored --provider blender > blender-authored.schema.json
schemaxis schema --authored --version schemaxis.workflow/1 > workflow-authored.schema.json
schemaxis schema --authored --version schemaxis.freecad.assembly/1 > assembly-authored.schema.json
```

The umbrella contains its references within one file. Authored schemas include
composition only where the parser supports it; they do not enable expressions in
Godot, Aseprite or saved-scene rendering. Workflow schemas restrict embedded
documents to the four pipeline types listed above, with artifact handoffs and
execution settings. An umbrella schema does not make all ten types legal
workflow children.

Without `--all`, the compatibility default is expanded input; `--expanded` makes
that choice explicit. Expanded input has document composition, inline construction
and analytics resolved, but retains runtime markers such as `$axis` and `$observe`.

```bash
schemaxis schema --expanded --provider paraview > paraview-expanded.schema.json
schemaxis schema --expand INPUT.json > expanded.json
schemaxis schema --section execution > workflow-budget.schema.json
schemaxis schema --section operation-execution > operation-budget.schema.json
```

Use `--version` to select a non-default document type. Other section exports include
`workflow`, `composition`, `analytic`, `assembly`, `saved-scene-render`, `camera`,
`style`, `render`, `series` and `time-selection`; `--operation NAME` selects an
operation's options rather than a complete node. Schema defaults are annotations;
Schemaxis supplies actual defaults. Configure an editor's external schema association
instead of adding a `$schema` root key to input (unknown root keys are rejected).
For integer options, write `3`, not `3.0`: JSON Schema's integer semantics are
broader than the parser's integer-token requirement.

Schemas check structure and declared values. `plan` remains authoritative for
dependency graphs, kinds, axis membership, uniqueness, cross-option relationships
and budgets. `run` checks actual devices, files, native properties and output data.
No generated schema can establish those native facts.

## 14. Dimension-driven authoring

The newer [human-input guide](human-input.md) and
[vehicle template](../examples/paraview-vehicle-demo/humanInput.json) describe
`dimensions`, `views` and `settings`. Use `$document` to reference these values
and `$value` to call a typed function during document resolution:

```json
{"$value":"boundsSize", "args":{"bounds":{"min":[0,0,0],"max":[4,2,1]}}}
```

Spatial functions include `directionVector`, `boundsCentre3D`, `boundsSize`,
`boundsExtend`, `boundsUnion`, `boundsFrame`, `slicePositions`, `fitCamera` and
`orbitCameras`. `$value` evaluates authored data before graph construction;
`$call` evaluates runtime arguments. See the generated settings reference for
exact contracts. Camera direction/up now accept axis and angle spellings too.

Use `schemaxis query INPUT.json` to query adaptor requirements and
`schemaxis reference --check` to check generated documentation. Implementations live
under `schemaxis.adaptors.paraview`, `.blender`, `.freecad`, `.godot` and `.aseprite`;
older ParaView/Blender top-level imports remain compatibility wrappers. For
installation and interactive use, start with the [user guide](user-guide.md).
