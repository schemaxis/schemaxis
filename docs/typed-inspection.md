# Typed evidence and inspection workspaces

The console and local agent service share immutable text/CSV snapshots and typed
historical selections. The production console now has **Geometry study**, **Text
inspection** and **Tables and signals** presets. Switching presets changes saved
presentation state, without editing the authored document, its undo history or
captured execution plans. Existing native node inspection remains available.

## Try the console

```sh
PYTHONPATH=src python3 -m schemaxis console --provider freecad --workspace evidence/my-inspection --web
```

Use the printed loopback URL. Choose **Text inspection** or **Tables and signals**
in the workspace selector. **Load synthetic fixtures** supplies a labelled log
and CSV; these are UI examples, not results from an extraction engine. Alternatively,
enter a local UTF-8 file path, explicitly choose text or table, and capture it.
A capture retains bytes in the workspace; subsequent external file changes do not
update it automatically. Local paths are trusted access, not an OS sandbox.

Select text and add a reference; click a table cell or enter a row/column range to
capture a table reference. **Plot columns** explicitly maps numeric x/y columns.
Use the row range and **Reference row interval** to capture its sample interval.
Reference chips coexist with native geometry/image picks in the context composer.
Click a chip to inspect its payload and retained evidence. Saving a request stores
local context; it does not submit a request to a model or execute an operation.

The source/property editor and its shared undo remain available in every preset.
The selected preset and snapshot survive restart. Browser table pages, axis choices
and plots are transient. The browser inventory shows at most 100 snapshots; the
agent listing remains pageable. Table pages display the first 16 columns, while
manual ranges and plot axes can address all columns. Column paging is available
through the service. There is no cell editing or spreadsheet formula engine.

## Agent tools

Run the [local JSON-lines service](agent-service.md), then use the methods returned
by `methods`. Console and agent state can be handed over sequentially as described
in [shared authoring](shared-authoring.md); the agent's console workspace lives at
`WORKSPACE/authoring` and has one exclusive process owner.

| Method | Purpose |
| --- | --- |
| `inspection_workspace(preset?, resource_id?)` | Read trusted panel/preset contracts and optionally save presentation. |
| `inspection_resources(**page)` | List snapshot descriptors using bounded observation paging. |
| `capture_inspection(filename, kind, resource_id?, expected_revision?)` | Capture local UTF-8 text or CSV; optionally replace the current revision of an existing resource. |
| `snapshot_resource(resource_id, kind)` | Capture a verified job publication after checking publication and receipt digests. |
| `inspect_snapshot(resource_id, revision, view, ...)` | Read a text slice, table rows or an explicitly mapped series. |
| `reference_snapshot(resource_id, revision, kind, selection)` | Retain a selection against the current snapshot revision. |
| `selections(**page)` | List common typed reference envelopes and their current staleness. |
| `inspect_selection(reference_id, **page)` | Read exact retained selection evidence, including an old snapshot after replacement. |

For example, use the returned resource identity and revision in subsequent calls:

```json
{"id":1,"method":"capture_inspection","params":{"filename":"/absolute/path/data.csv","kind":"table"}}
{"id":2,"method":"inspect_snapshot","params":{"resource_id":"SNAPSHOT_ID","revision":"REVISION","view":"series","x_column":0,"y_column":1}}
{"id":3,"method":"reference_snapshot","params":{"resource_id":"SNAPSHOT_ID","revision":"REVISION","kind":"series-interval","selection":{"rowStart":1,"rowEnd":4,"xColumn":0,"yColumn":1}}}
{"id":4,"method":"inspect_selection","params":{"reference_id":"refA"}}
```

Use an actual returned reference ID for the last request. Snapshots and verified
execution resources have different identities. `snapshot_resource` creates an
inspection resource from a verified execution resource and retains the link to its
producer, captured document and receipt. Later inspection describes the captured
bytes; call `verify` to recheck the producer's current files.

## Selection semantics and limits

A `schemaxis.reference/1` envelope declares `kind`, `target`, `payload`, provenance
and `replayable: false`. Existing geometry/image fields remain for compatibility;
their target is a document/revision, while snapshot targets are resource/revision.
No model-space coordinates are invented for text or tables.

| Kind | Payload coordinates |
| --- | --- |
| `text-span` | `start`/`end`: zero-based, half-open Unicode code-point offsets; retained UTF-8 byte bounds and one-based line numbers. |
| `table-range` | `rowStart`/`rowEnd`, `columnStart`/`columnEnd`: zero-based, half-open data ranges; header is not a data row. |
| `series-interval` | Half-open data-row range and explicit `xColumn`/`yColumn`; `domain` gives first/last selected sample x values. |
| `native-subelement` | Existing revision-bound object/subelement and tessellation pick. |
| `image-pixel` | Existing image digest, dimensions and pixel point. |

Text bytes, CRLF line endings, quoted CSV newlines, empty cells and string values
are preserved. The browser translates normalised textarea/UTF-16 positions back
to original source coordinates. CSV needs unique nonempty headers, at most 128
columns and 50,000 data rows, with rectangular records. Header names are limited
to 256 characters; the Python CSV reader's field-size limit also applies.

Series require two distinct columns of finite decimal numbers and strictly
increasing x. Missing/nonnumeric values, infinities, duplicate x values and unordered
x are rejected. There is no implicit sorting, zero filling or unit inference.
Conversion to binary floating point may round large integers or decimal fractions.
The original CSV strings remain inspectable. A sampled interval does not promise
continuous interpolation or define a reusable domain selector.

Inputs are limited to one MiB. `inspect_snapshot` pages accept `offset` and `limit`
(up to 16,384 text code points, 100 table rows or 200 series samples), and table
`columns` selects up to 16 distinct indices. Replies have a 65,536-byte budget,
return `nextOffset`, and never split a CSV row silently. Oversized complete metadata
or a row produces an explicit fault. `inspect_selection` uses ordinary bounded
observations; navigate member pointers or inspect smaller snapshot slices when a
selected scalar is too large. Keep the revision fixed while paging.

Replacing a resource requires its current revision. Old references then become
stale, their retained evidence remains readable, and saving new context with them
is rejected until a current selection is made. Editing an unrelated authored
document does not make a text/table snapshot stale. Retained blobs are digest
checked on inspection and before saving referenced context.

## Extension boundaries

`workspaces.py` supplies trusted built-in view contracts. `resource_inspection.py`
owns snapshot reads and selection semantics; the existing `inspection.py` retains
native node inspection. Layout files and authored documents cannot load remote
panel code. The console HTTP endpoint is `POST /api/inspection` with an `action`
and `params` object, under the existing token/origin checks.

The next [Workflow study slice](workflow-authoring.md) adds authored operation
graphs, source linkage, handoff edits and typed operation references.

This M3 slice supplies inspection and annotation. Extraction stages await the
actual user tools and record/alignment semantics. Replayable authored selectors,
nested graph editing, custom layouts, UML/concept-map semantics, YAML input and broader
model/provider evaluation remain future work.

[Verification](../verification/2026-09-27-typed-inspection.md) includes host, browser
and native numerical acceptance. Reproduce the native case with:

```sh
PYTHONPATH=src python3 tools/qualify_inspection.py --output-directory evidence/inspection-qualification
```
