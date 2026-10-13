# ParaView catalogue and extension declarations

Schemaxis now has 61 curated ParaView interfaces plus 535 generated source/filter
and 44 writer bindings, plus five typed resources, for the installed ParaView
5.13.3 catalogue. These overlap: the total of 645 identifiers does not mean 645
distinct native algorithms. Generated bindings
use `pv` followed by the public native constructor, and retain native property
and input names. Existing curated interfaces retain their names and defaults.

```sh
PYTHONPATH=src python3 -m schemaxis describe pvClip
PYTHONPATH=src python3 -m schemaxis schema --operation pvClip
PYTHONPATH=src python3 -m schemaxis coverage
```

For example, a nested shape is a typed declaration, not a Python expression:

```json
{"id":"cut","filter":"pvClip","inputs":{"Input":"sphere"},"options":{
  "ClipType":{"type":"Plane","options":{"Origin":[0,0,0],"Normal":[1,0,0]}},
  "Invert":false
}}
```

`examples/schemaxis/paraview-catalogue.json` is a runnable mesh example.
`examples/schemaxis/paraview-catalogue-table.json` reads the accompanying CSV, exports
and reopens a VTK XML table, converts rows to points, and writes numeric row
measurements. Run these examples from the repository root. Table strings survive
the XML round trip; numeric measurement CSVs contain numeric columns only.
Numeric `$sample` expressions also accept the `ROWS` association.

## What the inventory establishes

The fresh capture contains 262 source definitions, 289 filter definitions and 45
writer definitions. 535 source/filter definitions compile to bindings. Six
Python/programmable operations remain excluded from the authored-input language.
Ten more are recorded as unsupported because they are provably unusable: seven
need `vtkGenericDataSet` input, which no 5.13.3 reader, source or filter produces;
the two interpolator base proxies connect nothing to their required port 0; and
the classless internal `SelectionSourceBase` is documented "Do not use".
44 data writers compile to explicit scene exports. The native animation writer
requires a separate view/animation lifecycle and is recorded as unsupported.

This is **binding coverage**, not exhaustive native qualification. Each generated
operation declares its missing properties and `qualification: not-run`. A native
fixture establishes only its recorded inputs and settings. See the [verification summary](../verification/2026-09-16-catalogue-expansion.json) for actual native tests; the generator does not promote an
operation to universally supported because one example passed.

Other native groups (views, representations, animation and so on) are counted in
`coverage` but are not imported as pipeline filters. The current renderer and
publication interface remain the interface for those functions. Additional output
ports are selected with `{"node":"producer","port":1}` in a filter input;
the producer retains its graph identity, lifetime and invalidation dependencies.
Tables, hyper-tree grids, partitioned datasets and AMR have verified XML output
paths. Graph publication, MPI, specialised reader fixtures and exhaustive
format-specific writer verification need further work. A generated
filter can therefore be usable in a pipeline while its output cannot yet be
published through Schemaxis's verified geometry writer. Unsupported publication
formats fail explicitly.

## Explicit data exports

Scene `exports` entries select a writer, its native options and an optional
readback reader. Schemaxis owns filenames and the selected timestep. For example:

```json
{"id":"mesh","node":"surface","writer":"pvWriteXMLPolyDataWriter",
 "options":{"DataMode":"Binary","CompressorType":"ZLib"}}
```

Every export must pass readback verification. `exact` compares data structure,
connectivity, values and storage types. Lossy comparisons require explicit
`acceptLosses`: `geometry` verifies exterior geometry, `pixels` verifies image
samples, `table` verifies tabular values, and `semantic` verifies mesh geometry
and original fields while permitting container and storage changes. Numerical
tolerance is explicit; process success alone never qualifies an export.
`resources` maps a writer's typed resource input to a graph node; the receipt
checks that the writer retained that exact native identity. For example, the
PLY writer accepts `"resources":{"LookupTable":"colours"}`.
`readback` can select a declared reader and its options; its filename is managed.
This matters for particle formats requiring coordinate-array selections.

See `examples/schemaxis/paraview-writers.json`, `paraview-output-ports.json` and
`paraview-specialised-data.json`. Run `tools/qualify_paraview_writers.py` with
an explicit `--paraview` executable and `--output-directory` to record isolated
native fixtures. Native format bugs, unsupported data and crashes remain failed
receipts; declarations do not imply all fixtures pass.

`examples/schemaxis/paraview-native-times.json` selects timesteps from a generated
time-aware source. Native metadata is inspected after configuring source options.
Automatic XML publication suppresses the writer-added `TimeValue` field so that
exact data verification still compares the original fields; the publication
receipt retains the selected time.

## Declared commands

Captured no-argument native commands are separate from value settings. A node can
request `"onVisit":["ResetFieldCriteria"]`, for example, to invoke a declared
command before its update on every selected state. Commands run in authored order
after property assignment, preserve the producer identity, and force downstream
invalidation even when time and options are unchanged. The receipt verifies the
command/update event sequence. Unknown command names are rejected before execution;
the language does not accept arbitrary Python or native method names.

`examples/schemaxis/paraview-commands.json` exercises this with two downstream
transform positions. Refresh/Reload and streaming commands appear only on
operations whose captured property explicitly declares a native command.

## Shared native resources

`pvResourcePVLookupTable`, `pvResourcePiecewiseFunction`, `pvResourceImageTexture`,
`pvResourceTexture` and `pvResourceTransferFunction2D` are typed objects in the same dependency graph. Filters
can reference their node names through declared resource inputs. Several consumers
can share one resource; changing its options invalidates its consumers while
preserving its identity. Resources cannot be published as datasets or selected by
a numeric data output port.

The resource examples `paraview-resources.json` and `paraview-textures.json` cover
colour mapping, opacity-function connections, texture files and pipeline-backed
textures. `paraview-writer-resources.json` exercises a writer's lookup table.
The inventory includes these five definitions in addition to the 596
standard source/filter/writer definitions. Native property gaps remain explicit,
including the reduction filter's pre/post-gather helper proxies and a multi-server
dependency-link hook. Grouped values such as colour control points and 2D boxes
must contain complete native tuples; the schema exposes `x-schemaxis-tupleSize`
and the planner enforces it.

The static-mesh filter's `ForceCacheComputation` property has no elements, so
invoking it as a command sends no message; assigning it would push the XML command
`SetCacheComputation`, which `vtkForceStaticMesh` lacks (it has
`SetForceCacheComputation`), and that aborts the native process. It is therefore a
coverage gap, and Schemaxis cannot force the cache to recompute. The earlier native
receipt `static-mesh-command` (the same graph with the no-op command) kept radius-1
bounds at radius 2; `paraview-static-mesh.json` was edited afterwards and has not
been rerun.
The cell-grid attribute selector has a
scalar string binding, but `paraview-cellgrid-probe-unqualified.json` deliberately
records a failing fixture: the installed native runtime finds containing cells
and returns nonfinite parametric coordinates and values. The native-only
`tools/reproduce_paraview_cellgrid.py` reproduces that failure without Schemaxis.

## Data capability and cost contracts

Every input carries the captured native type domain and a separate cost contract.
Runtime checks use the native input domain after upstream data has updated.
Contracts may additionally require general traits, evaluated by
`schemaxis.data_contracts.assess`:

```json
{
  "requirements":{"indexing":["row-column"]},
  "cost":{"rating":"unknown","basis":"no benchmark"}
}
```

Assessment distinguishes `supported`, `unsupported`, and `unknown`. It reports
missing traits and incompatible traits separately. Conditional `fast` or `slow`
ratings require both a stated basis and applicability conditions; no conversion
is inserted. Native observations describe semantic traits such as structured or
unstructured topology, implicit or explicit coordinates, and row/column indexing.
Contiguity and iteration efficiency are unknown unless established separately.
There is no performance benchmark database or automatic conversion optimiser yet.

The captured `contract.composite` is `false` (composite data not supported), `true`
(composite data supported), `"required"` (the native domain sets
`composite_data_required`, so the input must be a composite dataset, for example a
multiblock of hyper tree grids) or `null` (no type domain was captured).

Native domain metadata also includes UI hints. Data-dependent bounds are not
universally hard validity constraints: clipping outside dataset bounds can be
meaningful. Static scalar bounds and vector cardinalities are validated before
assignment; input type/array requirements are checked after upstream updates;
assigned values and nested proxy identities are read back. Not every specialised
property-domain interaction has an interpreter yet.

Generated top-level options have no injected defaults: omitted options use native
initialisation. Nested properties omitted on a later update retain their native
values. Specify the relevant nested settings explicitly when varying shapes.
Do not assume these defaults are interchangeable with curated Schemaxis defaults.

## Repeatable intake

Use the native application only for explicit capture. Compilation, discovery,
schema generation and documentation generation use host Python without importing
ParaView:

```sh
PV=/absolute/path/to/ParaView
"$PV/bin/pvpython" tools/capture_paraview_catalogue.py /tmp/native.json
PYTHONPATH=src python3 tools/import_paraview_catalogue.py /tmp/native.json /tmp/catalogue.json
```

Review the generated package and its gaps before replacing
`src/schemaxis/adaptors/paraview/paraview_catalogue.json`. Then run `python3 -m schemaxis reference`, the
host unit suite, and bounded native qualification:

```sh
PYTHONPATH=src python3 tools/qualify_paraview_catalogue.py \
  --paraview "$PV/bin/pvbatch" --output-directory /tmp/new-qualification
```

The runner isolates fixtures with timeouts and retains inputs, logs, artifacts,
receipts and a frozen runtime archive. Round-trip equality is necessary but does
not prove that every algorithm produced the scientifically intended answer.
The separate existing acceptance suite checks analytic integrals, samples,
ordering, invalidation and expected failures.

Captured metadata is derived from ParaView's public server-manager API. The
upstream notice is retained in `src/schemaxis/adaptors/paraview/ParaView-Copyright.txt`. The compiled
package includes a canonical capture hash and native version. Raw captures and
bulk native results stay in the local `evidence` directory.

## Plugins and custom filters

A declaration package uses `schemaxis.paraview-catalogue/1`. Each operation carries
its native identity, typed options, property bindings, input contracts and gaps.
Nested proxy choices recursively use the same option language. Ordinary input
JSON cannot specify Python imports, arbitrary native attribute paths, or plugin
paths. Extension packages are trusted developer-installed code/configuration.

Capture a reviewed XML extension or native binary plugin explicitly:

```sh
"$PV/bin/pvpython" tools/capture_paraview_catalogue.py /tmp/extended.json \
  --xml-extension examples/schemaxis/extensions/schemaxis-shrink.xml
PYTHONPATH=src python3 tools/import_paraview_catalogue.py \
  /tmp/extended.json /tmp/schemaxis-shrink.json \
  --extension-against src/schemaxis/adaptors/paraview/paraview_catalogue.json
```

`--plugin /absolute/path/to/plugin.so` supports a native plugin in place of XML.
Its binary is not redistributed in the generated package; the recorded path must
exist and its SHA-256 must match at execution. XML content is retained in the
package with its checksum. Native dependencies load only during native execution,
not host discovery. The XML mechanism has a native acceptance example; arbitrary
binary plugins still require their own ABI and behaviour qualification.

Install a reviewed package as `src/schemaxis/adaptors/paraview/paraview_extensions/NAME.json`, regenerate
references, and rebuild/install the Python package when distributing it. The
runtime archive and wheel package include installed extension JSON. Duplicate
operation identifiers and different captured native versions are rejected.
Dependencies are checksum-checked before loading and proxy identities after
construction. Remove that package file to remove its declarations.

The supplied `examples/schemaxis/extensions/schemaxis-shrink.json` and `pipeline.json`
demonstrate this process. The example is not installed by default. A temporary
installation was used for its native acceptance; that run retains its own runtime.

## Development context and current admission

All declared identifiers have selection guidance through the public capability
catalogue. Generated bindings use retained public server-manager documentation;
`native-context.json` identifies native text versus reviewed scope/limitation text.
No captured documentation is a native qualification claim. The bundled
`ParaView-Copyright.txt` covers the derived native documentation. Refresh it with
`tools/capture_paraview_context.py` in the matching pvpython and review the new file
before replacement. Ordinary discovery never invokes ParaView.

The [development kit](adaptor-development.md) now admits this route. Its editable
[analytic line example](../examples/schemaxis/paraview-admission.json) has two
independent endpoint/bounds cases, publication readback and lifecycle/integrity
checks. The serial kit receipt does not qualify the full catalogue or MPI.
See the [installed audit](design/adaptor-framework/AUDIT.md) for current scope.
