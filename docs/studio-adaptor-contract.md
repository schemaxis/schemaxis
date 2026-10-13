# Studio adaptor contract

Use the [authoritative completion checklist](adaptor-completion.md) for new adaptors
and changes to existing operations, fields and routes.

An adaptor is ready for GUI authoring when users can discover, configure, insert,
understand, validate, inspect and publish its entire declared contract. A few
starter recipes are not complete operation coverage. This extends the
[adaptor architecture](adaptors.md) and [readiness requirements](adaptor-readiness.md).

## Required deliverables

- Register the version, routes, host-safe declarations, planning and native runner.
- Declare every supported operation, required/optional input port, option type,
  bounds, enum, nested proxy choice, default and command. Keep unsupported native
  settings and qualification gaps explicit. Never import the native application
  to browse, generate Help, export schemas or open an authoring form.
- Supply a validated `studio.json` with categories, starters, curated snippets,
  viewer support, descriptions and prerequisites. Test each recipe with filled
  host-plan values and ensure unfilled recipes report every placeholder address.
- The optional `studio.json` `helpGuide` selects an adaptor-owned default Help guide
  when it differs from the primary readiness route guide. Both must resolve locally.
- Cover every declared operation in the Add catalogue. Graph schemas with node
  alternatives and scene writer alternatives are projected automatically by
  `studio_catalogue.catalogue`. The optional manifest `studioCatalogue` binding
  supplies application-owned extra entries for controls/publication targets.
  Other document models must extend the projection to cover their model; do not
  pretend that an empty catalogue meets this requirement.
- Cover non-operation authoring features: publications, scenes, cameras/styles,
  scheduling, axes, settings, commands and any application-specific structures.
- Supply an application guide plus a complete generated operation reference in
  `docs/generated/<adaptor>-operations.md`. Include purpose, native identity,
  input/output kinds, every option, nested constraints, defaults, commands,
  meaningful examples, recovery guidance and qualification scope. Link guides
  and examples into Help. Regenerate `tools/generate_studio_help.py` and run its
  `--check`; context Help must resolve every operation to its own topic.
- Return structured faults with stable code, message, authored location, observed
  values and recovery. Locate missing keys at their intended address and type or
  domain failures at the offending value. Do not swallow errors into “value error”.
- Test completeness and schema validity, insertion targets, required placeholders,
  optional settings, nested forms, cancellation, atomic undo, Help links and
  diagnostics. Run bounded native acceptance for newly supported native options;
  distinguish host coverage from native qualification.

## Add catalogue entry format

The Studio adaptor response includes `addCatalogue` with `items` and
`definitions`. `definitions` are the literal schema's `$defs`. Each item has a
stable `id`, `title`, `description`, `group`, `schema` and RFC 6901 insertion `at`.
Use groups `inputs`, `sources`, `filters`, `outputs` or `presentation`. Include
`operation` for context Help, `coverage` for qualification/gaps, and port/binding
metadata where available.

`schema` describes the singular inserted value. Required fields become persistent
`$fill` markers when left empty. Optional fields are omitted until enabled.
Literal values are checked before insertion; native/semantic constraints remain
with the planner. Forms recursively expose objects, arrays, alternatives and enum
choices; free-form values retain JSON editing and schema Help.

For an insertion into an existing object, use placeholders in `at`, for example
`/scenes/{scene}/images/{image}/cameras/-`. Declare ordered `targets`:

```json
[
  {"name":"scene","collection":"/scenes","label":"Target scene"},
  {"name":"image","collection":"/scenes/{scene}/images","label":"Target image"}
]
```

Targets select array indices; `identity: true` selects a declared node ID for a
map key. Pointer segments must be escaped. Target choices refresh in order.
Reject missing targets and stale documents before insertion. A hook receives the
literal primary document schema and returns additional item dictionaries; it must
belong to the adaptor package. ParaView's implementation is
`schemaxis.adaptors.paraview.studio:catalogue`.

Shared forms assign unique IDs (and axis names), infer the primary required
input from selection/declaration kinds, and project `x-studio-reference` controls
from declared ports. Do not add application-name branches to shared form code.
The default name stays editable. Additional required ports remain explicit.

An adaptor can declare `studioInspect`, an adaptor-owned callable accepting
`(document, node, executable, directory, *, port=0, prepare=False)`. Studio runs it
as a tracked, cancellable native job through `/api/inspect-input`; discovery never
calls it. Return JSON metadata, not native handles. ParaView returns a Hierarchy
of labelled selector paths from `GetDataInformation().GetHierarchy()`, evaluates
only upstream dependencies, and refuses plugins or oversized/multiple-state
inspection. A separate worker protects the active preview. The block control is
declared in guidance as `{"kind":"blocks","input":"input"}`.

For reader setup, a catalogue hook can annotate an operation schema with
`x-studio-prepare` containing its user-facing explanation. On Add, Studio passes
the candidate node in a document to the same hook with `prepare=True`. The result
contains a prepared `value`, a `summary`, and optional explicit document `times`.
User-entered settings must be preserved. The candidate and any inferred time are
inserted together in one undoable draft edit; cancellation or a changed document
discards the result. ParaView currently uses this only for the curated `foam`
reader. Placeholder insertion remains available without native setup.

## Studio verification details

These checks implement the Help/examples/tests items in the canonical checklist.

Compare Add operation IDs against declaration IDs, including writers; compare
option fields against exported schemas, including nested and optional settings.
Check every document control has an insertion route. Confirm all Help references
exist, all required blanks remain honest placeholders, duplicate IDs are handled
by the editor, and cancelled/stale configuration does not mutate the source.
Validate failures in nested lists and workflow documents with exact authored paths,
Unicode-aware source coordinates, and navigation to the containing object for
missing keys. Keep evidence in a compact verification note.

## Conceptual guidance is an adaptor deliverable

Ship `guidance.json` beside each `adaptor.json`, using the data-only protocol
`schemaxis.studio-guidance/1`. This is the preserved source for GUI conceptual
help, separate from native bindings and validation constraints. Explain why an
operation exists, when to choose it, what it produces and its assumptions. For
fields, explain the meaning, units/conventions, useful values/examples, the effect
of omission/defaults, and common mistakes. File inputs also need path resolution,
format and dataset ownership information. Cover every registered document route,
nested proxy choice, array item, dynamic-map value, publication and control.

```json
{
  "version": "schemaxis.studio-guidance/1",
  "operations": {
    "foam": {
      "status": "reference",
      "explanation": "Read an OpenFOAM case and make its mesh and fields available to downstream filters.",
      "sources": ["docs/paraview-guide.md"],
      "pitfalls": ["Choose the case layout that actually contains your results."]
    }
  },
  "routes": {
    "schemaxis/1": {
      "fields": {
        "/$defs/options-foam/properties/file": {
          "status": "reviewed",
          "explanation": "Choose the .foam marker in the case folder. Its parent holds the mesh and time data.",
          "fileExtensions": [".foam"],
          "sources": ["docs/studio-guide.md#choosing-an-openfoam-case"]
        }
      }
    }
  }
}
```

Field addresses are RFC 6901 pointers into the route's **literal schema**, rather
than pointers into one user's document. `$defs` records are stored once; property,
array, map and alternative addresses are inventoried recursively. The GUI preserves
annotations through authored expression/composition wrapping, then exposes them in
Add forms, property Help and schema descriptions. The catalogue supports the
registered node models even when the manifest's `graph` flag is false. For a
non-node document, its top-level fields become document-control forms.

`reviewed` means explicitly authored conceptual text. `reference` means text
carried forward from documented adaptor descriptions with provenance; its quality
can still benefit from editing. `pending` is an honest gap, not a completed
explanation. Do not mark generated type descriptions or native property names as
conceptual guidance. Optional record keys are `units`, `defaultMeaning`,
`pitfalls` (text array), `examples` (JSON array), `sources` (text array), `question`
and `fileExtensions` (extensions for existing input-file browsing). `label`
provides a readable field title without renaming its JSON key. An object record
may declare `control: {"kind":"line","start":"start","end":"end"}` to pair
two XYZ properties in the shared line selector; native Point1/Point2 objects use
those exact keys instead. Controls must describe the declared object fields.
These keys do
not change validation constraints, native defaults or qualification status.

The host projects declared native bindings into `x-studio-guide.binding`, with
the native operation, property path, authored key and constructor-setting flag.
Keep this projection consistent in Add forms, Properties and schema Help.
Native XML names can differ from Python property names; match captured property
documentation to the actual declared Python binding. Import unambiguous matches
as `reference`, preserve authored explanations, and retain the source pointer.

Run the following when adding or changing a contract:

```sh
PYTHONPATH=src python3 tools/studio_guidance.py --seed
PYTHONPATH=src python3 tools/studio_guidance.py --review evidence/guidance-review.json
PYTHONPATH=src python3 tools/studio_guidance.py --apply-review evidence/edited-subset.json
PYTHONPATH=src python3 tools/studio_guidance.py --derive
PYTHONPATH=src python3 tools/studio_guidance.py --check
```

Applying a review merges each record over the existing one: omitted keys such
as `fileExtensions`, `control` or `label` are kept, and an explicit `null`
removes a key. `--derive` fills structural records that share another record's
meaning: a pure `$ref` takes its definition's record (including its label), and
the literal branch of a two-branch value wrapper (literal or runtime expression)
takes the wrapped field's record without its label. Derived records end with a
`guidance:<address>` source and are refreshed when that origin changes; remove
that source to make a record independent. Pending origins stay pending.
A node variant record whose final source is `guidance:operation <id>` repeats
that operation record's status, explanation and pitfalls, so correcting the
operation record also corrects every node variant that runs it.

Operation references (`docs/generated/<adaptor>-operations.md` and the ParaView
operation reference) include each operation's explanation and pitfalls and each
option's explanation, so packaged Help and search carry the same text as the
forms. After changing guidance, regenerate them with `schemaxis reference`,
`tools/generate_paraview_guide.py` and `tools/generate_studio_help.py`.
`--check` also checks local source files, Markdown anchors, Python symbols/line
ranges and derived guidance origins. URL checks validate syntax without fetching
or establishing availability/relevance. Native provenance citations remain attributed
data; they are not mistaken for local files.

Seeding adds addresses and imports available descriptions without overwriting an
existing entry. The audit detects missing operations, missing fields, stale schema
addresses and retired routes. `--check` exits unsuccessfully while pending or stale
entries remain. `schemaxis readiness --admission` treats conceptual-help gaps as a
required unknown. Existing runtime support remains available during this migration.
A new adaptor is not admitted as GUI-ready with pending conceptual guidance.

Users can open a question mark and **Improve this explanation → Copy help request**
in a form. Their prose, examples and questions can be saved to the identified
adaptor/route/address record and reviewed without changing the executable contract.
Keep qualifications and evidence separate from conceptual-help completeness.
