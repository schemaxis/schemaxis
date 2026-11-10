# Schemas and automatic reference generation

Schemaxis exports standalone JSON Schema Draft 2020-12 contracts for registered document
versions routed by `schemaxis`. Exporting uses only the Python standard library, without
starting or importing native applications. References in ordinary standalone exports are internal.
The optional ParaView bundle below explicitly uses relative file references.
Associate schemas externally in your editor: do not add `$schema` to input documents,
whose parsers reject unknown root keys.

Runs retain their contracts through the [shared schema store](schema-storage.md).
That guide covers workspace boundaries, legacy snapshots, portable export,
integrity checks and index recovery.

## Editor setup

For a first exercise, use the [getting-started walkthrough](getting-started.md).
Use the **authored** schema when editing an input, including literal-only inputs.
The expanded schema is intended for resolved documents.

### Choose a whole-document schema

For a complete ParaView input, including
[`humanInput.json`](../examples/paraview-vehicle-demo/humanInput.json), choose
[`paraview.authored.schema.json`](generated/paraview.authored.schema.json).
It includes analytics, document references, authored calculations and runtime
expressions in their supported locations. For inputs spanning different adaptor
versions, choose [`schemaxis-authored.schema.json`](generated/schemaxis-authored.schema.json).

`analytic.authored.schema.json` describes **one analytic expression**, for example:

```json
{"$analytic":{"type":"linear","start":0,"end":1,"count":3}}
```

It does not describe a full input file. Associating it with a pipeline correctly
reports that `$analytic` is required or that the document does not match the
expression schema. Likewise, `composition.schema.json` describes an expression
fragment. Do not associate these section schemas alongside the whole-document
schema to enable extra features; the whole-document authored schema includes them.

### VS Code

Open the repository folder containing `pyproject.toml`. The checked-in
[workspace settings](../.vscode/settings.json) already associate the generated
authored umbrella with `input.json` at the workspace root, JSON files under
`inputs/` and `*.schemaxis.json` files and top-level Schemaxis examples.

For your own project folder, export a schema there using your installed `schemaxis`
command (or `PYTHONPATH=/absolute/schemaxis/src python3 -m schemaxis`):

```bash
schemaxis schema --all > schemaxis-authored.schema.json
```

Merge this entry into that project's `.vscode/settings.json`, preserving any
existing settings and schema associations:

```json
{
  "json.schemas": [{
    "fileMatch": ["/input.json", "/inputs/**/*.json", "**/*.schemaxis.json", "**/*.schemaxis.json"],
    "url": "./schemaxis-authored.schema.json"
  }]
}
```

For a single application, export `schemaxis schema --provider freecad --authored`
to a schema file and use its path as `url` instead. This narrows completions.
Enter `version` first, then request completion with Ctrl+Space. For a quick
diagnostic check, open `freecad-bracket.json` and temporarily set a cylinder
`radius` to zero. Restore it after checking the error. Keep the file in JSON language mode.

VS Code documents partial support for Draft 2020-12, so editor diagnostics and
completions may not cover every constraint. Always follow editing with `schemaxis plan`.
See [VS Code's JSON schema documentation](https://code.visualstudio.com/docs/languages/json#_json-schemas-and-settings)
for schema mappings and dialect support.

### Other editors and keeping schemas current

Use your editor or JSON language server's external schema mapping to associate
the input file with a local authored schema. Choose a Draft 2020-12-capable
validator for full structural checking. Avoid mapping every `*.json` file in
the project: receipts, generated schemas and native assets have other formats.
Inputs can have any filename; the patterns above are an editor convention.

Schemas and option tables are generated from the active adaptor registry and
declarations, with maintained schemas for document envelopes. They are not a
second hand-maintained list of options. After changing declarations or enabling
a trusted extension, refresh the repository artifacts:

```bash
PYTHONPATH=src python3 -m schemaxis reference
PYTHONPATH=src python3 -m schemaxis reference --check
```

For a schema exported into another project, repeat the original export command
after upgrading Schemaxis or changing its registry. Generation is explicit; there
is no background schema watcher. Never hand-edit the generated schema.

## CLI contract

Run from the repository root with `PYTHONPATH=src`:

```bash
python3 -m schemaxis schema --all > schemaxis-authored.schema.json
python3 -m schemaxis schema --all --expanded > schemaxis-expanded.schema.json
python3 -m schemaxis schema --provider paraview --authored
python3 -m schemaxis schema --version schemaxis.freecad.assembly/1 --authored
python3 -m schemaxis schema --provider aseprite --operation pixel
python3 -m schemaxis schema --section workflow --authored
python3 -m schemaxis schema --section operation-execution
python3 -m schemaxis schema --expand examples/schemaxis/primitives.json
```

`--all` defaults to the authored umbrella. Other exports default to expanded/literal
input; select `--authored` for authoring conveniences. `--expanded` and `--authored`
are mutually exclusive. `--version` selects an exact document version; `--provider`
selects the provider's primary version. `--operation` exports an option dictionary,
not a node. `--expand FILE` expands conveniences without certifying graph correctness.

Sections: `camera`, `style`, `render`, `series`, `time-selection`, `saved-scene-render`,
`assembly`, `workflow`, `execution`, `operation-execution`, `composition`, `analytic`.
Authored operation exports add composition, not graph-local analytics/runtime context;
use full document schemas for those scopes.

Python API: `export_schema(provider='paraview', operation=None, section=None, *,
authored=False, version=None, all_versions=False)`. Unlike the CLI convenience,
Python callers explicitly select `authored=True` with `all_versions=True`.

## Portable captures and ParaView category bundles

For repeated evidence capture, keep one content-addressed schema store instead of
copying the whole schema into every case directory. This is explicit capture,
not an automatic cache that could hide changed declarations or extensions:

```bash
PYTHONPATH=src python3 -m schemaxis.schema_snapshots capture evidence/schema-store \
  --name acceptance-before --version schemaxis/1
PYTHONPATH=src python3 -m schemaxis.schema_snapshots capture evidence/schema-store \
  --name acceptance-after --version schemaxis/1
PYTHONPATH=src python3 -m schemaxis.schema_snapshots read \
  evidence/schema-store/acceptance-before.snapshot.json > retained-paraview.schema.json
```

Capture defaults to authored input; use `--expanded` for the expanded contract.
To retain an existing exported schema **byte for byte**, add
`--input path/to/paraview.schema.json --version schemaxis/1` and accurately choose
the authored/expanded flavour. Existing files are never migrated or deleted.
Each `*.snapshot.json` manifest records the provider, document version, flavour,
SHA-256, byte count and relative `schemas/<sha256>.json` reference. Identical bytes
share one object; a changed schema gets a new identity. Capture names are immutable
and safe to retry. Writes publish complete files atomically, including concurrent
identical captures. Reads check hashes, byte counts and the literal document
version without generating a replacement or loading native applications. Hashes
check retained content; they do not authenticate the person who created a manifest.
Copy the **whole store directory**, including `schemas/`, when moving evidence.
A snapshot manifest is an evidence reference, not a JSON Schema.

ParaView also offers an explicit category bundle for tools that support relative
JSON Schema references:

```bash
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.schema_bundle evidence/paraview-bundle
PYTHONPATH=src python3 -m schemaxis.adaptors.paraview.schema_bundle evidence/paraview-bundle --check
```

The default is authored input; add `--expanded` at generation for expanded input.
Choose a new output directory after declarations change. Associate the generated
`paraview.schema.json` entry point with a whole input document. Keep every bundle
member alongside it when copying the bundle. Existing `schemaxis schema` output,
checked-in standalone schemas, Studio and capability-schema pointers keep their
existing contracts; they do not transparently switch to this bundle.

| Member | Contents and validation shape |
| --- | --- |
| `common.schema.json` | Shared runtime, composition, analytic and JSON definitions; a definitions library, not a whole-input validator. |
| `readers.schema.json` | File readers without upstream input ports, reader options and readback declarations; its entry point validates **one reader node**. |
| `filters.schema.json` | Filters, resource operations and source generators such as `sphere`; its entry point validates **one node**. |
| `rendering.schema.json` | Presentation, images, cameras, appearances and scene settings; its entry point validates **one scene**. |
| `writers.schema.json` | Writer options and publication variants; its entry point validates **one scene export**. |
| `paraview.schema.json` | Full document envelope, referring to the category members. |
| `bundle.json` | Provider, document version, flavour, entry point and hashes/byte counts for every schema member. |

These are structural categories, not scientific workflow classifications. A
reader requires no input ports and a declared constructor file option; source
generators are grouped with filters. A file-driven operation with upstream inputs
remains a filter. Rendering scenes may refer to writer exports; authored inline
nodes may refer to readers or filters. Those links remain explicit and share the
common definitions. Category validators retain their normal runtime/composition
syntax; they cannot establish native compatibility or resolve graph references.

The bundle preserves the complete standalone constraints, including the distinct
ID requirement for authored inline nodes. Generation and `--check` inspect every
relative reference and JSON pointer offline, including definitions not selected by
a particular example. `--check` also rejects missing or changed member bytes.
Validation needs a Draft 2020-12 implementation with a local resource registry or
local-file resolver; no network retrieval is necessary. The snapshot store and
bundle have separate manifests: the first retains exact whole-schema captures,
while the second provides category entry points. Automatic cache invalidation,
rewriting existing execution receipts, and deduplicating runtime archives or plans
are outside these commands.

## Document coverage

| Required literal version | Contents | Authoring conveniences |
| --- | --- | --- |
| `schemaxis/1` | ParaView nodes, axes, times, scenes, images, appearances, measurements, exports | Composition, inline inputs, scoped analytics, runtime expressions |
| `schemaxis.blender/1` | Blender nodes, axes, scenes, rendering, images, mesh publications | Composition, inline inputs, scoped analytics, runtime expressions |
| `schemaxis.freecad/1` | Features, output and CAD settings | Composition; literal resolved features |
| `schemaxis.freecad.assembly/1` | Parts, components, grounding and joints | Composition; literal resolved assembly values |
| `schemaxis.blender.render/1` | Saved scene, cameras, render settings | Literal only outside workflow artifact handoffs |
| `schemaxis.godot/1` | Scene nodes and optional preview | Literal only |
| `schemaxis.aseprite/1` | Sprite nodes and output | Literal only |
| `schemaxis.ffmpeg/1` | PNG sequence/sprite-sheet video | Literal plus workflow artifact handoffs |
| `schemaxis.qgis/1` | Vector nodes, output and optional map preview | Composition plus workflow artifact handoffs |
| `schemaxis.workflow/1` | Operations, execution budgets, artifact handoffs | Composition inside supported operation documents, not the envelope |

`version` remains literal and required even inside workflow operations: dispatch
precedes composition. Whole-root substitutions cannot replace required headers.
Metadata accepted by each composing parser (`definitions`, `dimensions`, `settings`,
and provider-specific `views`) uses explicit recursive JSON rather than an untyped
placeholder schema.

Workflow operations support ParaView, FreeCAD solids, Blender scenes and saved-scene
Blender rendering, Godot, Aseprite, FFmpeg and QGIS. FreeCAD assemblies remain
standalone. The separate retained
`schemaxis.adaptors.paraview.mvp` MVP uses `documentVersion/resources/steps/outputs` and its own catalogue;
it is not an additional Schemaxis CLI format. Native glTF files, extension capsules, receipts
and capture catalogues are resources/outputs, not routed authoring documents.

## Recursive authoring grammar

- `{"$document":"/definitions/radius"}` is an exact-key reference. Absolute and
  relative (`./`, `../`) pointers and JSON-pointer escapes are represented.
- `{"$expr":{"op":"add","args":[1,2]}}` uses typed, two-argument operations:
  `add`, `subtract`, `multiply`, `divide`, `concat`, `merge`, `overlay`, `omit`, `get`,
  `namedMerge`, `namedGet`. Only merge/namedMerge accept `conflict` (left/right/error).
  The payload, operation and args may themselves compose: resolution happens first.
- `{"$value":"FUNCTION","args":{...}}` selects a registered side-effect-free
  function with declaration-derived arguments. Arguments compose recursively; the
  function name does not. There is no import path or arbitrary Python surface.
- ParaView/Blender input ports support `{"$object":"nodeId"}` and inline
  `{"$create":{"filter":"sphere",...}}`, with optional ID. Targets and complete
  inline subtrees may compose before graph compilation.
- Option-local `{"$analytic":{...}}` supports `values` (nonempty list), `linear`
  (start/end/positive count), and `orbit` (scalar start/end/count, optional elevation).
  Linear endpoints may be vectors. Values/linear option sequences support `sync`;
  orbit and publication sequences do not. Parameters and payloads may compose.

Analytics may nest inside non-constructor node-option arrays and runtime arguments,
but cannot replace the options dictionary or enter constructor values. A whole
image-camera or ParaView appearance sequence may be analytic; arbitrary nested
presentation members do not gain analytics. Separate option-runtime and
presentation-runtime definitions preserve this boundary.

Expanded documents retain `$axis`, `$observe`, `$time`, `$calc`, `$call`, and ParaView
`$sample`. Calculation arguments use a recursive data/runtime grammar. Malformed
nested markers are rejected; runtime result types and observed values remain deferred.

## Execution and publications

Only workflows have root `execution`: `maxWorkers`, `cpus`, `memoryMB`, `gpus`.
Operation execution accepts `threads`, `ranks`, `memoryMB`, `gpus`, `timeChunkSize`,
`mpiexec`. MPI ranks above one require an absolute launcher; at one rank the parser
ignores `mpiexec`, so the schema does too. Standalone ParaView has no root execution.

Workflow-only `{"$artifact":"earlierOperation","index":0}` objects are closed,
with a required nonnegative index. They occupy file-value positions before handoff.
Producer order, artifact existence/format, budget fit, adaptor execution support,
render-thread agreement, GPU requirements and useful chunking need semantic checks.

ParaView writers/readback readers derive from the active catalogue. `readback` may
be null or a closed reader/options object. Eligible readers have no inputs and
exactly one constructor file-list property. The verifier owns that filename, which
is absent from authored properties and required options. Unknown readers/options and
authored managed filenames are rejected. Comparison/loss/tolerance relationships
and native fidelity still require planning and independent verification.

Aseprite document and operation schemas share the lossless RGBA restriction: opaque
RGB colours or transparent black, not partial alpha. FreeCAD required file arguments
and identifier patterns apply to default exports as well as the umbrella.

## Configured extensions

Schemas describe the **active declaration registry**, not every shipped example.
ParaView loads trusted pinned-version JSON capsules from `schemaxis/adaptors/paraview/paraview_extensions`
in installed package resources. There is no schema-specific extension environment
variable. Configure a capsule before exporting; regenerate after registry changes.

`examples/schemaxis/extensions/pipeline.json` uses `pvSchemaxisShrink`. Stock schemas
intentionally reject it. A separate regression installs its capsule into an isolated
resource lookup, checks acceptance and rejects invalid extension options. This does
not load native plugins or establish native qualification. Editors using old stock
schemas need a regenerated schema. Capsule version/hash/dependency validation is
separate from authoring-document structure.

## Verification boundary

Schemas check unknown structural keys, declaration types/enums/bounds, required
properties, marker shapes and versions. A valid reference can still resolve to an
invalid value. Use `schemaxis plan` for reference existence/cycles, unique IDs, graph
dependencies, compatible kinds, computed types, matching analytic shapes, axes,
source times, cross-option comparisons, publication limits and resource availability.
A schema pass is neither native execution nor independent reopen verification.

Cross-field declaration checks remain `x-schemaxis-checks`/`x-schemaxis-requires` annotations
where not expressible in JSON Schema. Defaults are annotations, not mutations.
JSON Schema regards `3.0` as an integer; Schemaxis requires an integer token, so use `3`.
Duplicate keys, finite-number parsing and expansion limits remain parser checks.
Schemas cover accepted grammar, not every semantic condition.

Discriminator guards short-circuit irrelevant catalogue branches without weakening
their grammar. Tests include recursive examples, nested analytics, negative cases
and a complex-input performance regression.

## Generated artifacts and maintenance

The [authored umbrella](generated/schemaxis-authored.schema.json) is the editor entry
point; the [expanded umbrella](generated/schemaxis-expanded.schema.json) checks expanded
documents. Provider `*.schema.json` files retain expanded meaning; corresponding
`*.authored.schema.json` files cover authoring. Assembly, saved-scene render and
workflow also have standalone files. Execution/composition/analytic sections accompany
the operation references and shared settings.

```bash
PYTHONPATH=src python3 -m schemaxis reference
PYTHONPATH=src python3 -m schemaxis reference --check
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
```

Edit declarations/schema sources, not generated files. `argument_schema()` projects
one declaration; `arguments_schema()` projects a closed option dictionary. Supported
types are string, integer, number, boolean, enum, array, object and union. Maintained
parser-envelope schemas have positive, negative and parser-parity tests.

Conformance tests use optional developer package `jsonschema` and explicitly skip
when unavailable. Production export remains dependency-free. `reference --check`
detects schema/reference/static-module-index drift. See [human input](human-input.md)
for the dimension/view/settings authoring layer.
