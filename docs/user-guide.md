# Schemaxis user guide

For a completed OpenFOAM-format CFD case, use the dedicated
[CFD post-processing tutorial](cfd-postprocessing.md), with reusable inputs,
execution order, filters, camera windows and numerical exports.

Schemaxis describes application work as JSON, runs it through bounded native
adaptors, and retains editable outputs and evidence. The package and executable
are named **Schemaxis**: use `python3 -m schemaxis` or the installed `schemaxis` command.
The `schemaxis console` command also accepts `schemaxis schemaxis` as a subcommand
alias. The terminal and browser consoles use the same durable session model.

This guide covers the current implementation. Use `discover`, `describe`,
`schema --help` and console `help` from your checkout for exact available contracts.
The adaptors expose declared subsets of their native applications; a registered
operation is not a guarantee that every native property or workflow is supported.

New here? Follow the [ten-minute walkthrough](getting-started.md) first and
enable [editor completion and validation](schema-guide.md#editor-setup).

## Contents

1. [Choose a working mode](#1-choose-a-working-mode)
2. [Set up and complete a first run](#2-set-up-and-complete-a-first-run)
3. [Understand JSON input](#3-understand-json-input)
4. [Validate: schema, plan, run and verify](#4-validate-schema-plan-run-and-verify)
5. [Choose a document family](#5-choose-a-document-family)
6. [Reuse values, vary parameters and select times](#6-reuse-values-vary-parameters-and-select-times)
7. [Connect jobs and run them in parallel](#7-connect-jobs-and-run-them-in-parallel)
8. [Use the terminal console](#8-use-the-terminal-console)
9. [Configure native applications and manage documents](#9-configure-native-applications-and-manage-documents)
10. [Use the visual console](#10-use-the-visual-console)
11. [Save, recover and verify work](#11-save-recover-and-verify-work)
12. [Troubleshoot](#12-troubleshoot)
13. [Find deeper documentation](#13-find-deeper-documentation)

## 1. Choose a working mode

| Mode | Use it for | What runs |
| --- | --- | --- |
| JSON `plan` | Check input, dependencies and publication budgets | Host Python; no native application |
| JSON `run` | Repeatable publications, sweeps and file handoffs | Separate native application processes |
| Terminal console | Incremental authoring, undo/redo, multiple documents and checkpoints | Host session; native work on explicit commands |
| Browser console | The same commands, visual inspection, references and retained requests | Loopback server plus explicitly started native work |
| Console `live`, then `preview` | Inspect supported documents in a retained native client | Persistent FreeCAD, Blender or ParaView client |

Use a JSON run when you need a repeatable, checked publication. Use the console
when developing a document interactively, then save its authored JSON for batch
execution. A live checkpoint has its own, narrower verification scope: it does
not automatically acquire the batch adaptor's independent-reopening guarantees.
Neither console is an unrestricted Python interpreter or a general
natural-language modelling agent.

## 2. Set up and complete a first run

### Host and native applications

The host requires Python 3.10 or newer and has no third-party runtime Python
dependencies. From the repository root, use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
export PYTHONPATH=src
python3 -m schemaxis --help
python3 -m schemaxis discover
```

Optionally install the checkout in editable mode within that environment:

```bash
python3 -m pip install -e .
schemaxis --help
schemaxis console --help
```

Installation may need the build tools declared in `pyproject.toml`. The checkout
form with `PYTHONPATH=src` avoids that installation step. All examples below use
`python3 -m schemaxis`; installed users can substitute `schemaxis`.

Native applications are separate installations. Registered runtime families include
ParaView 5.13.3, Blender 5.2.2, FreeCAD 1.1.x, Godot 4.x and Aseprite 1.3.x,
plus FFmpeg/FFprobe and QGIS Python.
Discovery reports declared requirements, not whether an installation is available.
Supply explicit absolute locations for reliable reproduction:

| Application | CLI execution option | Location |
| --- | --- | --- |
| ParaView | `--paraview-root` | Installation root containing the native executables |
| Blender | `--blender` | Blender executable |
| FreeCAD | `--freecad` | `freecadcmd` command-line launcher |
| FreeCAD assembly GUI evidence | `--freecad-gui` | Optional GUI launcher, in addition to `--freecad` |
| Godot | `--godot` | Godot executable |
| Aseprite | `--aseprite` | Separately installed Aseprite executable |
| FFmpeg | `--ffmpeg` | Video encoder; matching `ffprobe` must be beside it |
| QGIS | `--qgis` | Python launcher configured for the QGIS runtime |
| KiCad | `--kicad` | `kicad-cli` executable |
| ImageJ | `--imagej`, `--imagej-jar` | Full JDK's `java` executable and ImageJ core `ij.jar` |
| PrusaSlicer | `--prusaslicer` | `prusa-slicer` console executable |

See [installation](installation.md) for numerical, structural, workbook and other runtime setup.

Replace `/absolute/path/to/...` placeholders with your installation. Run repository
examples from the repository root. Some use relative resources; case/import
templates may contain machine-specific paths that must be changed.

### First batch publication

```bash
python3 -m schemaxis query examples/schemaxis/freecad-bracket.json
python3 -m schemaxis plan examples/schemaxis/freecad-bracket.json
python3 -m schemaxis run examples/schemaxis/freecad-bracket.json \
  --freecad /absolute/path/to/freecadcmd \
  --output-directory evidence/my-first-bracket
python3 -m schemaxis verify evidence/my-first-bracket
```

For standalone adaptor runs, choose a **new output directory** with its parent
already present for portability. Workflow runs create missing parents and also
accept an existing empty directory. Do not reuse an old run directory by deleting
individual receipts or artifacts. Workflow `--resume` is described later.

Require successful verification under the adaptor's contract, then open the
native model or image and check that it is what you intended. Keep the complete
output directory: input, plan, logs, receipts and companion resources matter.
Verification establishes declared checks, not engineering correctness,
manufacturability or subjective visual quality.

### First console session without native execution

```bash
python3 -m schemaxis console --workspace .schemaxis-guide
```

At the `schemaxis>` prompt:

```text
rectangle profile 80 50
extrude plate profile 6
inspect plate
save plate-intent.json
status
quit
```

The default provider is FreeCAD. These commands retain authored intent without
launching FreeCAD. Console `inspect` shows authored data, not native topology.
Saving JSON saves intent, not an FCStd model.

## 3. Understand JSON input

Use ordinary JSON: double-quoted strings, no comments or trailing commas, and
finite numbers. Avoid duplicate keys. A typical graph node is:

```json
{"id":"rounded","filter":"bevel","inputs":{"input":"box"},"options":{"width":0.1,"segments":3}}
```

`id` is your identifier; `filter` names a declared operation. `inputs` connects
named ports to other nodes; `options` configures the operation. Names are
case-sensitive and provider-specific. FreeCAD `cut` uses `base` and `tool`,
whereas Blender `boolean` uses `input` and `operand`.

Omitted options use declared defaults; `null` is not a request for a default.
Unknown keys and wrong types are errors. Write `3`, not `3.0`, for an integer
option. A JSON boolean is not a number.

| Document version | Purpose | Main structure |
| --- | --- | --- |
| `schemaxis/1` | ParaView scientific data pipelines | `nodes`, `scenes`; optional axes and times |
| `schemaxis.blender/1` | Meshes, materials, modifiers and rendering | `nodes`, one scene; optional axes and explicit visit times |
| `schemaxis.blender.render/1` | Render a prepared Schemaxis Blender scene | `sceneFile`, `cameras`, optional `render` and `size` |
| `schemaxis.freecad/1` | CAD feature graphs | `nodes`, solid `output`, millimetre units |
| `schemaxis.freecad.assembly/1` | Native fixed-joint assemblies | `parts`, `components`, `grounded`, `joints` |
| `schemaxis.godot/1` | Editable Godot 3D project | `nodes`, exactly one camera; optional PNG `preview` |
| `schemaxis.aseprite/1` | Editable sprites and animation frames | Linear sprite-node chain and final `output` |
| `schemaxis.ffmpeg/1` | Video from PNG sequences or sprite sheets | One node |
| `schemaxis.qgis/1` | Bounded vector GIS | Ordered `nodes`, final `output`, optional `preview` |
| `schemaxis.workflow/1` | Dependencies between application jobs | `operations`, optional execution budgets |

Do not copy one family's root keys into another. Assemblies have no modelling
node graph; Godot and Aseprite do not use ParaView's scenes/axes contract.
ParaView/Blender graphs can resolve forward references and prune unused nodes.
FreeCAD inputs must refer to earlier nodes; Godot materials precede their
consumers; Aseprite mutations form one linear chain. Use each family's planner.

## 4. Validate: schema, plan, run and verify

There are three layers. Passing an earlier layer does not replace a later one.

| Layer | Question it answers | What it cannot establish |
| --- | --- | --- |
| Schema | Is the document structurally consistent with the declared input language? | Resolved graph semantics, installed native capabilities or correct output |
| `plan` | Do the resolved names, dependencies, types and publication requests form a supported job? | That native files, plugins, GPUs or geometry will work at execution time |
| `run` and `verify` | Did native execution produce artifacts satisfying the adaptor's recorded checks? | Fitness for manufacture, simulation validity, or unsupported native properties |

### Export a schema for your input

The public schema CLI exports JSON Schema Draft 2020-12 without starting native
applications. `--all` means the **eleven Schemaxis CLI document versions** in the
table above. It does not cover the retained `python3 -m schemaxis.adaptors.paraview.mvp` parser's
distinct `documentVersion` / `resources` / `steps` / `outputs` format.

```bash
# All eleven Schemaxis document versions, authored syntax by default:
python3 -m schemaxis schema --all > schemaxis-authored.schema.json

# One exact document version, including its supported authoring conveniences:
python3 -m schemaxis schema --version schemaxis.freecad/1 --authored > cad.schema.json
python3 -m schemaxis schema --version schemaxis.workflow/1 --authored > workflow.schema.json

# Expanded/literal input instead of authored composition:
python3 -m schemaxis schema --all --expanded > schemaxis-expanded.schema.json
python3 -m schemaxis schema --provider blender --expanded > blender.schema.json

# A particular option dictionary, not a complete document:
python3 -m schemaxis schema --provider blender --operation bevel > bevel.schema.json
python3 -m schemaxis schema --section camera > camera.schema.json
```

`--authored` and `--expanded` are mutually exclusive. Without `--all`, the
default is expanded input. Select `--version` when the provider alone is
ambiguous, for example FreeCAD features versus FreeCAD assemblies. An authored
schema admits only the authoring constructs supported by that document family;
it is not permission to use every marker everywhere.

`--expand` is a different action: it expands an **input file**, rather than
selecting a schema dialect:

```bash
python3 -m schemaxis schema --expand design.json > expanded.json
python3 -m schemaxis plan design.json
```

Configure your editor or external validator to associate the appropriate schema
with the file; see [ready-to-use editor settings](schema-guide.md#editor-setup).
Do not insert a `$schema` property into Schemaxis input: closed root
contracts reject unknown keys. Schema defaults are annotations; Schemaxis applies
its own declared defaults. JSON Schema considers `3.0` an integer value, whereas
Schemaxis integer options require an integer token such as `3`.

Reference existence, cycles, resolved expression values, cross-option relations,
active axes, time availability, publication budgets and native capabilities need
the planner or runner. `x-schemaxis-checks` and related metadata are not additional
standard JSON Schema keywords that an external validator automatically enforces.
See the [schema guide](schema-guide.md) for exact exports and native guards.

Schemas describe the active declaration registry. An example that needs a trusted
ParaView extension capsule can be rejected by a stock schema until that capsule
is configured and the schema is regenerated. Exporting the schema does not load
or qualify the native plugin. Duplicate keys, non-finite numbers and expansion
limits also remain parser checks, not guarantees supplied by an editor's schema.

For an optional command-line schema check, install `jsonschema` in your development
virtual environment (`python3 -m pip install jsonschema`). After exporting
`schemaxis-authored.schema.json` as above, run this Python snippet from the directory
containing that schema and your `design.json`:

```python
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from schemaxis.core.documents import load_document

schema = json.loads(Path("schemaxis-authored.schema.json").read_text())
document = load_document(Path("design.json").read_text())
if not Draft202012Validator(schema).is_valid(document):
    raise SystemExit("Schema check failed; inspect editor diagnostics and run schemaxis plan.")
print("Structure accepted. Run schemaxis plan before native execution.")
```

The Schemaxis package must be installed or `PYTHONPATH=src` set for its strict input
loader. This optional validation package is not needed for normal Schemaxis planning,
execution or schema export.

### Plan before running; retain the evidence

```bash
python3 -m schemaxis describe --provider freecad
python3 -m schemaxis query design.json
python3 -m schemaxis plan design.json
python3 -m schemaxis run design.json --freecad /absolute/path/to/freecadcmd \
  --output-directory evidence/design-001 --timeout 300
python3 -m schemaxis verify evidence/design-001
```

`describe` is the operation catalogue; `query` reports the document's declared
requirements. Neither proves that your native installation satisfies them.
`plan` does not load the native application. `run` creates the publication and
its evidence; `verify` checks an existing evidence directory under its adaptor
contract. Read the structured fault and native log if either fails. A PNG alone,
or a native process exiting with code zero, is not a verified job.

## 5. Choose a document family

The following starter documents are complete inputs unless marked as fragments
or templates. Save one to a JSON file and run `plan` first. Longer examples are
linked for features that need more context.

### FreeCAD: constrained sketch to solid

```json
{
  "version": "schemaxis.freecad/1",
  "units": "mm",
  "nodes": [
    {"id": "profile", "filter": "rectangle", "options": {"width": 80, "height": 50}},
    {"id": "plate", "filter": "extrude", "inputs": {"profile": "profile"}, "options": {"length": 6}}
  ],
  "output": "plate"
}
```

FreeCAD dimensions are millimetres. Rectangle and circle operations construct
declared constrained sketches; this does not imply arbitrary polygon sketches
are fully constrained. The console permits a sketch-only draft and can display
its native edges with zero triangles. A batch feature publication requires a
solid output. The standard batch artifacts are `model.step`, `model.stl` and
`model.FCStd` in that order; the editable native document is the last of these.

Boolean features use named inputs, for example `cut` has `base` and `tool`.
Edges used for fillets or chamfers are one-based native topology selections;
inspect the current shape rather than assuming an old Edge number survives an
edit. CLI native inspection is different from console authored inspection:

```bash
python3 -m schemaxis inspect examples/schemaxis/freecad-bracket.json --node blank \
  --freecad /absolute/path/to/freecadcmd --output-directory evidence/bracket-inspect
```

`linearDeflection` controls tessellation, not CAD dimensions. See the
[bracket](../examples/schemaxis/freecad-bracket.json),
[flange](../examples/schemaxis/freecad-flange.json) and
[CAD/mesh guide](cad-and-mesh-workflows.md).

### FreeCAD assembly: components and fixed joints

Assemblies use `schemaxis.freecad.assembly/1`, not a feature-node graph. The complete
[assembly example](../examples/schemaxis/freecad-assembly.json) declares reusable
box/cylinder `parts`, component instances, one `grounded` component, and a rooted
tree of fixed joints. Joints identify parent/child component connectors using
`top` or `bottom`; offsets are in the parent component frame. Component rotation
is a yaw angle in degrees. These are bounded native fixed-joint assemblies, not
a general kinematic mechanism or arbitrary joint solver.

```bash
python3 -m schemaxis plan examples/schemaxis/freecad-assembly.json
python3 -m schemaxis run examples/schemaxis/freecad-assembly.json \
  --freecad /absolute/path/to/freecadcmd \
  --output-directory evidence/assembly-001
```

Optional `--freecad-gui /absolute/path/to/FreeCAD` enables the supported GUI
evidence path. In the console, `open` the assembly JSON and edit complete fields
with `set document`; feature-node commands and live assembly execution are not
supported. Assemblies are not workflow child documents. See
[FreeCAD assemblies](freecad-assemblies.md).

### ParaView: data pipelines and publications

```json
{
  "version": "schemaxis/1",
  "nodes": [{"id": "ball", "filter": "sphere", "options": {"radius": 2}}],
  "scenes": [{
    "id": "view",
    "visible": {"ball": {"colour": "steelblue"}},
    "images": [{"id": "front", "size": [640, 480], "cameras": [{"direction": [1, -2, 1]}]}]
  }]
}
```

Run with `--paraview-root /absolute/path/to/ParaView`. Nodes connect scientific
datasets to declared filters. A scene's `visible` object maps node names to
appearance settings; geometry and image publications are explicit. Use
`describe --provider paraview` for readers, filters and their exact option names.
For example, the OpenFOAM reader uses `file`, while some mesh readers use a
`files` array: do not interchange them.

Scalar colouring needs the correct array name and point/cell association from
the actual data. A generated catalogue entry does not guarantee a plugin exists
in every ParaView build. Source-time selection requires discrete native
`TimestepValues`; static sources do not acquire time steps merely because a
times section is present. Decomposed-case reading by a serial process is not
the same as distributed MPI execution.

### Blender: editable meshes and rendered scenes

```json
{
  "version": "schemaxis.blender/1",
  "nodes": [
    {"id": "paint", "filter": "material", "options": {"colour": [0.1, 0.4, 0.8, 1]}},
    {"id": "block", "filter": "cube", "options": {"size": 2}, "inputs": {"material": {"$object": "paint"}}}
  ],
  "scenes": [{
    "id": "view",
    "visible": ["block"],
    "images": [{"id": "front", "size": [640, 480], "cameras": [{"direction": [1, -2, 1]}]}]
  }]
}
```

Run with `--blender /absolute/path/to/blender`. Blender uses a visible **list**,
not ParaView's visible/style mapping. Material colours use floating-point RGBA;
the console material example below shows object-reference input syntax. The
pipeline supports one scene and one image publication containing multiple
cameras. CPU is the default rendering path; requesting CUDA or OPTIX does not
silently fall back when the requested backend is unavailable.

Transform rotations are XYZ degrees; bend/twist angles have their own declared
radian units. Modifier distances operate in object-local coordinates. Bake
transforms when you need those distances in the transformed geometry's units.
`join` is not a solid Boolean union. Requested mesh publications are evaluated
world-coordinate STL; STL itself carries no unit metadata. A CAD millimetre to
metre handoff commonly requires an explicit `0.001` scale.

Use `prepareOnly` for the supported scene-preparation path; its input still
requires the declared publication/camera configuration. See the
[mesh workshop](../examples/schemaxis/expanded/blender-mesh-workshop.json) and
[CAD/mesh guide](cad-and-mesh-workflows.md) for modifiers and handoffs.

### Blender saved-scene render

`schemaxis.blender.render/1` renders a prepared Schemaxis `.blend` instead of rebuilding
a node graph. Its root contains `sceneFile`, `cameras`, and optional `render` and
`size`. Use an absolute native scene path, or a workflow artifact reference.
This is not an arbitrary `.blend` automation interface: the runner requires
Schemaxis's saved scene metadata and a supported self-contained scene. Linked
libraries and unpacked external images are rejected by the batch contract.

See [render groups](../examples/schemaxis/blender-render-groups.json) for a complete
preparation/render workflow. Keep the preparation receipt to identify the exact
scene artifact rather than guessing a filename or artifact index.

### Godot: editable 3D projects

```json
{
  "version": "schemaxis.godot/1",
  "units": "m",
  "nodes": [
    {"id": "paint", "filter": "material", "options": {"colour": [0.12, 0.42, 0.85]}},
    {"id": "block", "filter": "box", "options": {"size": [2, 1, 1]}, "inputs": {"material": "paint"}},
    {"id": "view", "filter": "camera", "options": {"position": [6, 4, 8], "target": [0, 0, 0]}},
    {"id": "sun", "filter": "directionalLight"}
  ]
}
```

Run with `--godot /absolute/path/to/godot`. Godot uses metres and a Y-up scene.
Materials must precede their consumers; every declared material must be used.
A complete scene requires geometry and exactly one camera. Declared primitives,
materials, light, orbit camera and a restricted `.gltf` import are supported,
not arbitrary GDScript, physics or general transform hierarchies.

Keep the whole generated project, including `project.godot`, `scene.tscn` and
the supplied orbit script. Default execution is headless. Root `"preview": true`
requests an actual native PNG through the isolated Xvfb/OpenGL path and needs
its system prerequisites, including `xvfb-run`. Console drafts may be incomplete,
but preview requires a complete scene. No retained live client, CLI `inspect`,
workflow child or single-file native `save` is offered for this provider. See
[Godot](godot.md) and [primitives](../examples/schemaxis/godot-primitives.json).

### Aseprite: pixel art and animation

```json
{
  "version": "schemaxis.aseprite/1",
  "nodes": [
    {"id": "canvas", "filter": "sprite", "options": {"width": 8, "height": 8}},
    {"id": "square", "filter": "rect", "inputs": {"sprite": "canvas"}, "options": {"layer": "base", "x": 1, "y": 1, "width": 6, "height": 6, "colour": [30, 130, 230, 255]}},
    {"id": "cutout", "filter": "circle", "inputs": {"sprite": "square"}, "options": {"layer": "base", "x": 3, "y": 3, "radius": 1, "colour": [0, 0, 0, 0]}}
  ],
  "output": "cutout"
}
```

Run with `--aseprite /absolute/path/to/aseprite`. The sprite graph is one linear
mutation chain. Pixel coordinates start at zero; authored frame numbers start
at one. Colours are integer RGBA channels: the declared subset supports opaque
pixels or fully transparent black, not arbitrary partial alpha. Appending a
frame creates an empty frame; it does not implicitly copy the preceding one.

Outputs include `sprite.aseprite`, a first-frame composite `preview.png`, a
horizontal `sheet.png` and `sheet.json`. Layers, frames, palette changes and tags
have declared operations; arbitrary Lua, indexed modes, layer groups, blend
modes, fonts and general imports are not implied. There is no live client, CLI
`inspect` or workflow-child support. See [Aseprite](aseprite.md) and
[animation](../examples/schemaxis/aseprite-animation.json).

### FFmpeg and QGIS

Use [media workflows](media-workflows.md) for video from PNG sequences or sprite
sheets, and [the QGIS guide](qgis.md) for the supported vector pipeline. These
families accept literal inputs and explicit workflow artifact handoffs. Their
options and verification contracts differ from ParaView and Blender graphs.

## 6. Reuse values, vary parameters and select times

Start with a literal document. Add authoring conveniences only where the selected
family supports them; use `schema --authored`, `schema --expand` and `plan` to
inspect what they mean. The [JSON input guide](json-input.md) and
[human input guide](human-input.md) cover the full syntax.

For example, the following is an **option-value fragment**, not a whole job:

```json
{"$document": "/dimensions/plateThickness"}
```

Place the number in the root `dimensions` object and use that reference for a
supported option. `$document` uses document paths, not filesystem imports.
`definitions` and `settings` can retain reusable authored data. Pure `$expr`
operations and registered `$value` functions compose values without running
arbitrary Python. List the declared functions with `python3 -m schemaxis functions`.
Inline `$create` / `$object` construction and `$analytic` sequences are separate
authoring tools, not interchangeable with native reference chips in the console.

ParaView and Blender axes describe parameter visits. Values sharing an axis
advance together; independent active axes form a Cartesian product. Unused axes
do not justify executing unused branches. Increasing two independent counts can
multiply the work: check the plan's visits and publication budget first.

Analytic camera sequences are useful for repeatable views. This **fragment**
produces three orbit directions in a supported `cameras` position:

```json
{"$analytic": {"type": "orbit", "start": 30, "end": 150, "count": 3, "elevation": 25}}
```

Camera `direction` points from the focal point towards the camera. Shared camera
names do not erase native differences: ParaView's parallel scale is a vertical
half-height, while Blender's orthographic scale is a horizontal full width.
Use the generated settings reference rather than transferring numbers blindly.
Browser orbit/walk controls do not edit these authored cameras.

For time-dependent ParaView input, choose from times actually exposed by native
sources. Blender visit times are explicit, not discovered OpenFOAM times. See
[parallel timesteps](../examples/schemaxis/parallel-timesteps.json) for a complete
example. Plan-time acceptance does not prove a reader has the requested native
time or array; those checks occur when the application loads the data.

## 7. Connect jobs and run them in parallel

A `schemaxis.workflow/1` document lists named `operations`, each containing a child
`document`. Supported child versions are exactly `schemaxis/1`, `schemaxis.freecad/1`,
`schemaxis.blender/1`, `schemaxis.blender.render/1`, `schemaxis.godot/1`,
`schemaxis.aseprite/1`, `schemaxis.ffmpeg/1` and `schemaxis.qgis/1`. FreeCAD assemblies
remain standalone. See [media workflows](media-workflows.md) and [QGIS](qgis.md).

An artifact reference is an **input-value fragment**:

```json
{"$artifact": "surface", "index": 0}
```

It selects the zero-based publication index of an earlier operation named
`surface`. It is not a filename glob. Artifact type and consumer restrictions
still apply. Inspect the producer's plan and receipts: enabling images or mesh
publications can change which artifact an index denotes. A FreeCAD batch feature
job publishes STEP at index 0, STL at index 1 and FCStd at index 2; choose the
format the next reader actually accepts.

Try the complete [ParaView-to-Blender workflow](../examples/schemaxis/paraview-to-blender.json):

```bash
python3 -m schemaxis plan examples/schemaxis/paraview-to-blender.json
python3 -m schemaxis run examples/schemaxis/paraview-to-blender.json \
  --paraview-root /absolute/path/to/ParaView --blender /absolute/path/to/blender \
  --output-directory evidence/handoff-001
python3 -m schemaxis verify evidence/handoff-001
```

The [direct CAD handoff](../examples/schemaxis/expanded/cad-direct-to-blender.json)
and [Blender-to-ParaView workflow](../examples/schemaxis/expanded/blender-to-paraview.json)
show other supported boundaries. Handoffs do not preserve every material, unit,
topological identifier or external dependency across formats.

### Adopt a saved application file or directory

A file you saved from an application becomes workflow input through a copied,
digest-pinned snapshot rather than the live save location:

```bash
python3 -m schemaxis input adopt saved/surface.vtp snapshots/surface-001
python3 -m schemaxis input adopt saved/blocks snapshots/blocks-001 \
  --kind directory --max-files 100
python3 -m schemaxis input verify snapshots/surface-001 --digest <digest>
```

Save a stable checkpoint first; adoption refuses ordinary concurrent changes and
existing destinations. `--kind file-set --member PATH` captures an explicit list.
The command prints a `reference` to place where the reader expects a path:

```json
{"$resource": "/absolute/snapshots/blocks-001", "digest": "<64 hex>",
 "member": "blocks.vtm", "origin": "saved after review"}
```

Planning, every run and `verify` recheck the exact snapshot membership and bytes
and compare its manifest digest with the digest pinned in the workflow. Each run
checks again after the consuming application returns, so a snapshot edited while
it was being read fails the workflow instead of succeeding. Changed or tampered
content is refused; adopt a new snapshot and update the workflow to accept a
change. `--max-files`/`--max-bytes` chosen at adoption are kept in the reference
as `maxFiles`/`maxBytes` and bound every later check. Move a
snapshot only together with its reference. Run evidence (`handoffs`) records the
snapshot, member, digest, reader policy and optional origin. Units and coordinate
frames are recorded as `unknown`.

The consuming adaptor decides what each reader may open. ParaView accepts a file
or a captured member for single-file readers (`readSurface`, `readUnstructuredGrid`,
`readImageData`, `readStructuredGrid`, `readRectilinearGrid`, `readSTL`,
`readPLY`). `readMultiBlock`, `readParallelPolyData` and
`readParallelUnstructuredGrid` need a directory or file-set snapshot whose XML
piece references all resolve to captured members. The selected member must be a
`.vtm`, `.pvtp` or `.pvtu` (any letter case) of the reader's type. Every referenced
document's `VTKFile` type is read from a bounded header and must match its name
(`.vtp`, `.vtu`, `.vti`, `.vts`, `.vtr` or a parallel/multiblock container), so
renamed containers and unsupported names such as `.dat` are refused; containers
are traversed, leaf payloads are not parsed. Container metadata is limited to
16 MiB per file, 64 MiB across the closure, 65,536 reference occurrences
(including repeats) and 128 nested XML elements. Repeated references reuse the
header check while retaining each parallel reader's piece-type requirement.
`foam` needs the whole case
directory, accepted only within an include-free subset. A selected name beginning
with `controlDict` is refused, because the reader would then treat the parent
directory as the case. The selected member and every file, whatever its name or
suffix, under `system`, `constant`, `processor*` and any top-level directory whose
name does not start with a letter (or starts with `inf`/`nan`) are scanned. Gzip is
detected by magic, and scanning stops at 512 MiB decompressed per file and 2 GiB
per case. Any active `#` (every `#include` variant and other directive), binary
format, control bytes, quoted strings over 1000 bytes, and ambiguous or
unterminated strings and comments are refused. `#` in comments and short quoted
strings is allowed. This scope is a conservative superset of the case layout read
by ParaView 5.13.3's OpenFOAM reader (`system`, `constant` and its region meshes,
`processor*` and time directories starting with a digit, `+` or `-`). Other
top-level files and letter-named directories (logs, scripts, `postProcessing`) are
not scanned, since that reader does not open them. Other readers or versions may
differ. Other adaptors and options refuse
`$resource` until they declare a policy. ParaView resume reruns readers of
captured inputs rather than claiming reuse. To edit an intermediate result, use
an explicit revision (below) rather than editing a snapshot in place.

A reference may also be defined once in an operation's `settings` or the
workflow's `definitions` and placed at a reader option with an ordinary
`$document` reference, for example `"settings": {"case": {"$resource": ...}}`
with `"file": {"$document": "/settings/case"}`. Reader policy, digest checks and
evidence then apply at that reader option; the definition itself is left
unchanged and is never treated as a reader. A definition that no reader uses is
not opened, and a `$document` that places a reference at an
unsupported option is refused.

Workflow and workflow-design schemas, and Studio's editor for an operation inside a
workflow, offer `$resource` with field help at exactly these reader positions;
malformed digests, members, limits or extra keys are refused as you type. A
standalone document cannot consume a captured input, so Studio asks you to run
such an operation from its workflow instead of creating a standalone preview.
Adoption itself is still a command or API step.

### Edit one intermediate artifact as an explicit revision

A completed workflow can hand one verified producer artifact to you for editing
in its application, then run the downstream work again as a new child revision.
The parent result is never edited or resumed:

```bash
python3 -m schemaxis revision checkout evidence/handoff-001 --consumer consume \
  --pointer /nodes/0/options/files/0 --destination edits/surface.vtp
# open edits/surface.vtp in the application, edit and save it
python3 -m schemaxis revision prepare evidence/handoff-001 --consumer consume \
  --pointer /nodes/0/options/files/0 --replacement edits/surface.vtp \
  --snapshot snapshots/surface-edit-001 --reason "smoothed the inlet edge" \
  --output revisions/surface-edit-001.json
python3 -m schemaxis plan revisions/surface-edit-001.json
python3 -m schemaxis run revisions/surface-edit-001.json \
  --output-directory evidence/handoff-001-edit-001
python3 -m schemaxis verify evidence/handoff-001-edit-001
```

`--pointer` is a JSON pointer inside the consumer operation's document and must
select a direct `{"$artifact": ..., "index": ...}` reference at a reader field
whose adaptor declares a captured-input policy. The parent must be a verified,
successful workflow without studies and without workflow-level `settings`,
`definitions`, `dimensions`, `axes` or `execution`, or operation-level
`execution`. It may be a serial
result or a simple scheduled one: adaptors such as FreeCAD and Gmsh are always
run by the scheduler, so a two-operation FreeCAD to Gmsh workflow qualifies even
though you never wrote any `execution`. Every operation must then be one
batch with one native visit, so an operation that carries its own `axes` study of
several states is refused wherever it sits (a study of a single state
qualifies). The consumer's recorded handoff must show it received the selected
artifact at the selected field. The producer
must have a single visit, and the selected artifact must be one regular file
whose bytes match its receipt. A scheduled parent is re-verified in full by the
scheduler's own checks, and the producer's recorded attempt is re-verified with
its provider. `selection.file` is then relative to the producer's directory and
names that attempt, for example `batch-0/attempt-0001/part.step`. Multi-visit,
multi-file, distributed, unverified, unfinished or revision-chain parents, and
those with authored execution, composition or studies, remain refused.
`checkout` copies that file to a new working copy. `prepare` adopts the saved
copy as a pinned single-file snapshot and writes a closed
`schemaxis.revision/1` document recording the parent directory and authored
digest, the producer, artifact index, owned file and SHA-256, the consumer
pointer and its original reference, the replacement reference, the working copy,
the reason, the derived child workflow digest, and `unknown` units and frame.

`plan`, `run` and `verify` each verify the parent again, rederive the child
workflow from it and compare every recorded identity; a changed parent,
selection, pointer, replacement or child workflow fails. The run writes its
record and `result.json` in the output directory and the child workflow under
`workflow/`, rechecks the snapshot before and after its consumer, and reruns
every operation: `result.json` lists them under `rerun`, with `reused` empty.
Failed or cancelled children keep their partial evidence. The working copy,
snapshot, revision document and child output must each be outside the parent
result and must not contain it; symlinked spellings are resolved before any
write. A revision result cannot yet be the parent of another revision, so
verification never follows a lineage chain. `--resume` does not apply to
revisions, and ordinary `--resume` still requires an identical workflow.
If preparation is refused after adoption, its newly created snapshot is removed
so a corrected request can retry at the same destination. Existing snapshots are
never removed by a refused request.

The revision record is provenance, not a signature, and does not show that the
edited data is scientifically equivalent to the original. Selective continuation
(reusing untouched operations), multi-file or directory edits, composed
`$document`/`$value` inputs, multiple visits, parents with authored scheduler
execution and Studio editing of revisions are not implemented yet. Every
operation of a scheduled parent is rerun in the child, including the producer
whose output you replaced.
The revision also depends on the retained parent and adopted snapshot at their
recorded absolute paths. Backing up or relocating only the child result is not a
self-contained backup; retain those dependencies separately.

Workflow root `execution` budgets constrain concurrent workers, CPUs, memory and
GPU slots. Per-operation `execution` requests threads, ranks and other declared
resources. Memory budgets are scheduling estimates, not operating-system memory
limits. GPU scheduling is bounded to the supported slot model, not a cluster
scheduler. ParaView MPI is an explicit supported subset and requires a suitable
MPI launcher; more than one rank is not automatically valid for every pipeline.
See [parallel execution](parallel-execution.md) before enabling concurrency.

New workflow runs accept a nonexistent or empty output directory and create
missing parents automatically. Files, symlinks and directories containing any
entries (including hidden files) are refused without replacing retained results.
An exclusive authored-input record reserves the destination before execution.

Use `run ... --resume` only for the supported workflow path, with the unchanged
workflow and the same output directory. Resume rechecks retained evidence; it
does not mean “trust any files already there”. A failed standalone run is not
made resumable by adding this flag. Preserve failure logs and choose a fresh
output directory when changing the job.

## 8. Use the terminal console

Start a durable workspace from your shell:

```bash
python3 -m schemaxis console --workspace .schemaxis
```

An existing workspace restores its documents; the initial `--provider` default
does not replace them. At the console prompt enter **console commands**, without
the `python3 -m schemaxis` prefix. Commands use shell-style quoting but do not run a
shell. Enclose JSON arguments in single quotes and paths containing spaces in
quotes. `#` begins a comment outside quotes.

### Build and edit a plate

```text
new "Plate design" freecad
rectangle profile 80 50
extrude plate 6
inspect plate
set plate length 8
preview
save "plate-intent.json"
undo
redo
status
```

`rectangle` selects its new profile, so `extrude plate 6` uses that selection.
Use `extrude plate profile 6` to name it explicitly. `set plate length 8` edits
the extrusion's declared length, not an arbitrary native property. With no
configured executable, `preview` produces a plan checkpoint, not a native model.

For a hole through the plate, continue with:

```text
circle hole 3
add bore extrude '{"length":10}' '{"profile":"hole"}'
add cut cut '{}' '{"base":"plate","tool":"bore"}'
show cut
inspect cut
```

Each candidate edit is validated before becoming the authored document. Remove
consumers before removing nodes they depend on. Undo/redo restore authored
content but advance the workspace revision; they do not make old picks current.
The bounded sentence `draw a rectangle 80 x 50 mm centred on the origin` is also
recognised. This convenience is not general natural-language modelling.

### Command reference

| Command | Purpose |
| --- | --- |
| `help` | Show exact supported command forms |
| `new [NAME] [PROVIDER]` | Create another document without discarding the old ones |
| `provider PROVIDER` | Activate an existing document for that provider, or create one |
| `use DOCUMENT_UUID` | Switch to a specific retained document |
| `configure PROVIDER LOCATION` | Retain a provider configuration without switching documents |
| `connect [LOCATION]` | Configure the active provider |
| `live EXECUTABLE_OR_ROOT` | Start a supported retained native client |
| `open FILE` | Replace active authored content from JSON; undoable |
| `add ID FILTER [OPTIONS_JSON] [INPUTS_JSON]` | Add a declared operation |
| `set ID OPTION JSON` | Change one operation option |
| `set document FIELD JSON` | Replace one complete top-level field, except `version` or `nodes` |
| `remove ID` | Remove an unconsumed node |
| `show ID` | Change the FreeCAD output or first Blender/ParaView visible scene |
| `select ID` | Change selection without editing model content |
| `box ID LENGTH WIDTH HEIGHT` | FreeCAD box convenience |
| `rectangle ID WIDTH HEIGHT` | FreeCAD constrained rectangular profile |
| `circle ID RADIUS` | FreeCAD constrained circular profile |
| `extrude ID [PROFILE] LENGTH` | FreeCAD profile extrusion |
| `undo`, `redo` | Navigate authored edit history |
| `preview [DIRECTORY]` | Produce a plan or verified native checkpoint, according to connection mode |
| `geometry` | Request current live native geometry, not an authored approximation |
| `image [FILE]` | Obtain/export the supported current native image |
| `save FILE` | Save authored JSON or a supported verified native artifact |
| `inspect [ID]` | Inspect authored records; unlike CLI `inspect`, does not run a topology inspection |
| `list` | List current nodes or assembly components |
| `history` | Show authored edit history |
| `artifacts` | Show retained artifact information |
| `status` | Show document, revision, configurations and checkpoint status |
| `unload` | Close the active document's live client; keep its configuration |
| `disconnect` | Also remove the active provider configuration |
| `quit` | Exit the interactive terminal and close its clients |

Aliases include `ls` for `list`, `?` for `help` and `rect` for `rectangle`.
`quit`/`exit` are terminal-loop controls, not remote browser command jobs.

### Other provider drafts

The console uses provider-specific declarations, not one universal node grammar:

```text
new "Mesh design" blender
add paint material '{"colour":[0.1,0.4,0.8,1]}'
add cube cube '{"size":2}' '{"material":{"$object":"paint"}}'
preview
new "Game scene" godot
add paint material
add block box '{}' '{"material":"paint"}'
add camera camera
preview
new "Pixel sprite" aseprite
add canvas sprite '{"width":16,"height":16}'
preview
```

Blender/ParaView draft graphs may lack publications; the first renderable node
creates a default scene. Resources do not automatically become visible. ParaView
does not automatically add image publications. `preview` still needs a complete
provider publication plan. For assemblies, open the assembly JSON and replace
whole `parts`, `components` or `joints` fields instead of using `add`.

### Editing, history and scripted commands

On a real terminal, optional standard-library `readline` supplies line editing,
Up/Down history and Tab completion for commands, node IDs, document UUIDs and
providers. The latest 500 command-history entries persist in the workspace.
Platforms without readline use plain input. Console `history` is the separate
authored edit history, not the input-line history.

For repeatable host-only authoring, pass multiple `--command` options from the
shell. They execute in order and print results, then exit unless `--web` is set:

```bash
python3 -m schemaxis console --workspace .schemaxis-scripted \
  --command 'rectangle profile 80 50' \
  --command 'extrude plate 6' \
  --command 'save plate-intent.json'
```

Use a new workspace for that exact example: replaying it into an existing
document can conflict with its node IDs. Paths are resolved by the server/console
process, not by a browser file picker. `open` accepts authored Schemaxis JSON; it
does not import an arbitrary `.FCStd`, `.blend` or native GUI session.

## 9. Configure native applications and manage documents

Configuration and a running connection are different states. The following
commands retain locations without changing the active document:

```text
configure freecad /absolute/path/to/freecadcmd
configure blender /absolute/path/to/blender
configure paraview /absolute/path/to/ParaView
configure godot /absolute/path/to/godot
configure aseprite /absolute/path/to/aseprite
```

Executable locations must be absolute executable files; ParaView also accepts an
installation root. Configuration is persisted in the workspace. `connect` is
the active-provider convenience. Do not confuse the FreeCAD batch command-line
launcher with the GUI-capable launcher used for `live`:

```text
provider freecad
live /absolute/path/to/FreeCAD
preview
geometry
image
```

| State | What `preview` does | What you can expect |
| --- | --- | --- |
| No executable and no live client | Host planning | Authored input and plan; no invented native geometry/image |
| Configured executable, no live client | Batch native execution | Adaptor verification and published artifacts |
| Supported live client | Apply/recompute and snapshot in retained application | Current native geometry/image and explicitly scoped live evidence |

Live clients are supported for FreeCAD feature documents, Blender and ParaView.
Godot, Aseprite and FreeCAD assemblies use the supported batch preview path.
For ParaView live work, use its supported Python executable or installation
root; a generic Python interpreter is not a replacement.

Multiple documents can retain independent native clients and caches. Switch with
the UUID returned by `status` or the browser document list. `provider freecad`
does not guarantee selection of a particular FreeCAD document when several
exist; use its UUID. `unload` affects the active client's residency and geometry,
not the authored document or saved provider configuration. `disconnect` also
removes the active provider configuration; other documents' retained clients
are not globally torn down.

The authored document remains the source of intent. Editing the native GUI does
not reverse-synchronise its changes into JSON. When native state diverges,
geometry/reference guards can reject it, and an uncertain client may be
discarded. Re-establish the intended state with a new supported live preview;
do not treat the last mesh still on screen as current.

## 10. Use the visual console

### Start and connect

```bash
python3 -m schemaxis console --workspace .schemaxis --web --port 8765
```

Open the printed loopback URL, including its `?token=...` query. Omitting `--port`
uses an available port. The token authorises local API requests; do not publish
it, place it in documentation, or expose this server through an untrusted
network proxy. The server binds locally and is not a multi-user hardened service.
Closing the browser tab does not stop the console server. Stop it from its
owning terminal when finished; shutdown also requests active-operation
cancellation.

The panels show the workspace/documents, native 3D geometry, current PNG, command
history and a rich request composer. The command log scrolls internally and
retains expandable details; a large JSON result should not need to displace the
viewport. On smaller displays, scroll the page/panels to reach the composer.

Enter the same console commands in the command field. `live`, followed by
`preview`, provides supported native geometry. A batch screenshot and a live
tessellation are distinct capabilities: a valid PNG does not imply a 3D mesh is
available. If WebGL is unavailable, the 3D viewer cannot render; the textual
console and other available panels remain useful.

### Orbit, section and walk through geometry

| Control | Action |
| --- | --- |
| Default Orbit, drag | Rotate around the model |
| Shift-drag or right-drag | Pan |
| Wheel in Orbit | Zoom |
| Fit / `F` with viewport focused | Fit the native bounds |
| Isometric | Return to the standard view |
| Section axis and position | Clip the view along X, Y or Z for interior inspection |
| Walk mode, drag | Look around with a perspective camera |
| Walk `W` / `S`, `A` / `D` | Move forward/backward and sideways |
| Walk `Q` / `E` | Move down/up along the viewer's Z axis |
| Walk wheel / speed control | Move along the view / adjust movement speed |

Focus the viewport before using navigation keys. Walk permits movement past
surfaces and into interiors; it has no collision or physical clearance model.
Section clipping removes geometry beyond the selected plane for display and
picking; it does not create a new CAD cut, cap face or referenceable surface.
These controls change the browser view, not the authored geometry or native
publication camera. Use Fit if you lose the model.

Native edge polylines and vertices are rendered as well as face triangles.
A fresh sketch can therefore be a real native wire loop with **zero triangles**.
An empty triangle list alone does not mean that no geometry exists.

### Compose a sentence with exact references

1. Place the caret where the reference should appear in the request composer.
2. Click a visible native face, edge or vertex, or choose an available element
   from the element list. The pick is checked against current native geometry.
3. The returned reference is inserted as an atomic chip at the retained caret.
   Its readable label identifies the object/element; details retain the exact
   point, units, document and revision.
4. Continue typing around the chip, or type `@` to reuse an existing reference.
   Use the chooser's arrows and Enter/Tab; Escape dismisses it.
5. Select **Save request** to retain the sentence and reference segments.

For example, type “Increase the clearance beside ”, pick a face, then finish
“ while preserving the outside dimensions.” The chip might identify `refA` and
`plate.Face1`; it is not editable prose pretending to be a reference. Backspace
or Delete next to a chip removes the whole token. Merely typing `refA` into
ordinary text does not create a reference segment.

Face points are native tessellation picks, edge points lie on native segments,
and vertex picks retain native points. They are revision-bound selections, not
permanent topological names. Hidden/clipped geometry is not a shortcut for
inventing a pick. If only a previous-revision mesh is available, the UI can retain
it for context but blocks current picking.

### Refer to a PNG pixel honestly

Click within the drawn image, not the blank margins around it. The browser maps
the contained image rectangle back to integer native pixels, with `(0, 0)` at
the top left. The reference retains image size, `px` units and the exact PNG
digest. It says “image preview pixel (x,y)”, not “CAD face at this screen point”.
An Aseprite preview pixel is not automatically a particular layer or authored
animation frame; it references the displayed image.

Image metadata is fetched before loading the digest-bound PNG. If the current
image/document changes during a pick, stale selection is rejected. Zooming the
browser or resizing the pane does not change the underlying pixel coordinate
system. PNG and 3D references can coexist in the same composed sentence.

### Staleness, drafts and saved requests

Model edits advance the revision. Old chips are visibly stale, and saving a
request containing stale references is disabled. Refresh the native preview and
replace/re-pick the affected references; undo does not make an old revision
current again. Image references additionally depend on the exact PNG digest.
The server also guards against native GUI divergence before accepting model
references.

Saving captures the composer document UUID, current revision and segments
together. A delayed response must not attach prose to a different document after
you switch. Saving a request **retains intent only**: it does not execute arbitrary
natural language, modify the model or submit the sentence as a console command.

The collapsible saved-requests section lets you revisit retained requests and
their reference details. Restore brings a request back into the matching
document's draft; it is not re-execution and does not refresh old references.
Historical saved requests retain their original identity and revision.

Unsaved drafts are retained per document in browser local storage, using
workspace/document identity and plain text/reference-ID segments, never the
authentication token. Switching documents and reloading the same origin can
recover them. Browser storage is not a backup: clearing it, private browsing,
another browser, or a different port can make a local draft unavailable. Use a
stable port if you rely on reload recovery, and save important requests to the
server workspace. Saved requests and authored JSON are separate records;
`save design.json` does not embed the request history.

### Long-running commands and Cancel

Submitting a command starts a job. The UI polls that job until it succeeds or
fails and exposes expandable result/fault details. Avoid submitting the same
edit again merely because it is slow. If the UI offers Refresh to resume polling,
it follows the existing job rather than creating another one.

**Cancel current operation** requests cancellation of the active job, disables
repeat cancellation and continues polling until the final result. Cancellation
is not an undo or an immediate success response. An operation can finish before
the request takes effect. Uncertain native state after cancellation or timeout
may cause the affected client to be discarded; the authored document and
previous verified checkpoint remain separately tracked. Read the final status
before previewing or saving again.

See [visual console](visual-console.md) for the detailed UI/API contract.

## 11. Save, recover and verify work

### Know what is being saved

| Target | Meaning and requirements |
| --- | --- |
| `save design.json` or `save design.schemaxis` | Authored input; no native application needed |
| `save model.FCStd` | Matching verified current FreeCAD feature/assembly checkpoint |
| `save scene.blend` | Matching verified current Blender scene artifact |
| `save state.pvsm` | Matching verified current ParaView state artifact |
| `save sprite.aseprite` | Matching verified current Aseprite artifact |
| Godot project | Keep the full published project directory; no standalone native-file save |
| Save request in browser | Retained sentence/reference history, not an executable model edit |

Native save is not “copy whichever file was written last”. The console checks
document identity, revision, authored digest, receipt, artifact digest and
containment. After an edit, run a successful matching native preview before
saving native output. Existing destination files are not overwritten; choose a
new name. If several native artifacts are plausible, an ambiguity fault is safer
than silently choosing the wrong one.

A native file can still depend on other files. ParaView state may refer to
external datasets; a live Blender scene can depend on external resources. Keep
the evidence directory and dependencies, not just a renamed native file.

### Batch evidence and live evidence are different

Batch adaptors perform their declared native publication/reopen checks. Live
snapshots have deliberately narrower scopes. In particular, a FreeCAD live
snapshot's `nativeLiveSnapshot` scope records `independentReopen: false`; ZIP/XML
container and digest checks are not an independent geometric reopen. Live
Blender checks native library/object/material membership, and live ParaView
checks state/proxy membership, not an independent reload of every dataset.
Read the actual receipt scope rather than assuming all previews are equivalent.

For reproducible release evidence, save authored JSON and run the appropriate
batch job into a fresh directory, then verify it. Do not describe a successful
live screenshot as a full native qualification of every feature.

### Workspace recovery

The workspace retains documents, edit history, provider configurations,
checkpoint provenance, references and saved requests. Session persistence uses
a checksum and an advisory workspace lock. Only one console should own a
workspace at a time. Do not delete a lock file to bypass a running owner.

After restart, the authored documents and retained evidence are available, but
live native processes and geometry caches are not silently resurrected. Start
the required live client and preview again. Interrupted attempts are recorded as
interrupted, not successful. A failed retry does not turn the last successful
checkpoint into a success for a different revision; check both the latest attempt
and the last successful preview.

If persistence reports an error with `published: true` but `durable: false`, some
state may already have been published. Inspect/reconcile the workspace before
blindly retrying the action. Preserve a damaged workspace for diagnosis rather
than editing its checksum or deleting receipts. Back up the complete workspace
and external publication directories when they contain work you need to retain.

## 12. Troubleshoot

Start with the fault code/message and the affected document/revision. Expand the
browser result details, inspect `status`/`artifacts`, or retain CLI stderr and
native logs. Do not assume that the most recent visible image is current.

| Symptom or fault | What to check next |
| --- | --- |
| `No module named schemaxis` | Activate the intended virtual environment; install editable or set `PYTHONPATH=src` from the repository root |
| `schemaxis: command not found` | Use `schemaxis console`, `schemaxis schemaxis`, or `python3 -m schemaxis console`; there is no separate installed `schemaxis` executable |
| Unknown key, type or option fault | Check `version`, exact operation declaration and authored/expanded schema choice; use integer tokens where required |
| Schema passes but plan fails | Resolve duplicate IDs, missing inputs, wrong kinds, cycles, expression results and publication constraints |
| `INTERPRETER_NOT_FOUND` or launch failure | Supply the correct absolute native executable/root, check executable permissions and registered runtime requirements |
| `preview` returns only a plan | No usable native configuration/client is active; configure the provider or start supported `live` mode |
| `NO_GEOMETRY`, previous-revision mesh | Start/recompute a supported live preview; a batch PNG is not a live tessellation; never pick stale geometry |
| Sketch shows no shaded solid | A native profile may contain only edges/vertices; extrude it for a solid, or inspect the wire loop |
| `NO_PREVIEW`, no image | Produce a native image; ParaView needs an image publication, and Godot's PNG path requires `preview: true` and its display prerequisites |
| `STALE_REFERENCE`, disabled Save request | Refresh/re-pick stale chips for the current document/revision/image; restoring history does not refresh references |
| `INVALID_SELECTION` | Pick an actual current element or a pixel inside the drawn image; do not infer a CAD face from a PNG |
| `NATIVE_DIVERGENCE` | Native GUI state differs from authored intent; recreate the supported live preview rather than assuming reverse synchronisation |
| `UNSUPPORTED_LIVE` / `UNSUPPORTED_SAVE` | Check provider and document-family capabilities; use batch output or keep the full Godot project |
| `OUTPUT_EXISTS` | Select a new output directory/file, or use the supported unchanged-workflow resume path |
| `AMBIGUOUS_ARTIFACT` | Inspect receipts; multiple candidate images/scenes cannot safely be chosen implicitly |
| `WORKSPACE_LOCKED` | Find the owning console and close it normally, or use another workspace; do not bypass the lock |
| `RECOVERY_FAILED` | Preserve the workspace and inspect recovery details; do not fabricate a checksum or success receipt |
| `RUNNER_CANCELLED` / `RUNNER_TIMED_OUT` / `LIVE_TIMEOUT` | Read the final attempt and native-state status; a fresh client/preview may be necessary |
| Browser `ACCESS_DENIED` | Reopen the current server's printed token-bearing URL; old tokens are not a substitute for the new one |
| Busy job or slow command | Continue polling the existing job or request Cancel; avoid duplicate submissions |
| CUDA/OPTIX, plugin or native import failure | Check the exact installed native build and requested feature; declared support is not installation discovery |
| Restored browser draft missing | Check browser origin/port and storage; server-saved requests are separate from local drafts |

Do not “fix” a failure by inventing geometry, changing a receipt, pretending an
image pixel is a surface, or silently falling back to a different execution mode.
If a capability is outside the declared subset, retain the input and fault and
use the native application directly or request an explicit adaptor extension.

## 13. Find deeper documentation

- [JSON input](json-input.md): authoring syntax and document examples.
- [ParaView export integrity](paraview-export-integrity.md): finite comparison data, retained member checks and refusal recovery.
- [Schema guide](schema-guide.md): exact export modes, validation boundaries and native guards.
- [Human input](human-input.md): dimensions, settings and reusable authoring constructs.
- [Console](console.md): session commands, persistence and live/batch behaviour.
- [Visual console](visual-console.md): viewer, composer, references and API.
- [Console audit](console-audit.md): tested behaviour and remaining boundaries.
- [CAD and mesh workflows](cad-and-mesh-workflows.md): native geometry and format handoffs.
- [FreeCAD assemblies](freecad-assemblies.md), [Godot](godot.md), [Aseprite](aseprite.md): provider-specific contracts.
- [Parallel execution](parallel-execution.md): scheduling, time chunks, MPI and resume.
- [Example inputs](../examples/schemaxis/): complete jobs; check resource paths before execution.

For declarations matching your checkout, use `schemaxis discover`,
`schemaxis describe --provider PROVIDER`, `schemaxis schema --help`, `schemaxis functions`
and `schemaxis colours`. `schemaxis reference --check` checks generated reference drift;
it does not qualify an installed native application.
