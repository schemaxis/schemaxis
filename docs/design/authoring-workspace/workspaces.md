# Task-oriented GUI workspaces

Production status: [typed inspection](../../typed-inspection.md) now supplies three
built-in presets with text, table, series and existing native views.
[Workflow study](../../workflow-authoring.md) adds a fourth preset with real
operation/artifact diagrams, source linkage and validated handoff edits. The broader
catalogue below remains a design direction, including graph editors and extraction.

2026-09-27 · design proposal. The current prototype implements a CAD-oriented
interaction study only; this catalogue does not advertise shipped workspaces.

## Four independent concepts

| Concept | Responsibility | Example |
| --- | --- | --- |
| Adaptor | Application/backend integration and executable contracts | FreeCAD, ParaView, Octave |
| Capability group / curated interface | Progressive navigation to relevant operations | Sampling, solid modelling, a bounded extraction interface |
| Workspace preset | Arrange tools and panels for a task | Log extraction: text + stages + results |
| Editor / inspection panel | Read or edit a specific representation | Source editor, table, timeline, graph, 3D viewer |

Workspaces can span adaptors. An adaptor can contribute capabilities to several
workspaces. A workflow may move between workspaces as the task progresses without
changing its underlying document, input bindings or history. The agent-facing
protocol works regardless of whether any graphical workspace is open.

Examples such as modelling, sculpting, rigging and animation motivate different
arrangements of tools. They do not imply Schemaxis currently exposes all those
operations or should recreate each native application's full interface.

## Initial catalogue

| Workspace | Main arrangement | Useful interaction | Implementation boundary |
| --- | --- | --- | --- |
| Capability explorer | Task/application breadcrumbs + operations + contract/example detail | Find a capability, inspect requirements, insert a declared operation | Build on the real registry; distinguish inventory from executable support |
| CAD / geometry study | Feature/dependency tree + geometry + parameters + source | Inspect geometry, name picks, connect compatible operations, expose parameters | Existing CAD prototype is illustrative; native integration remains required |
| Text / log extraction | Source text + ordered extraction stages + match/results table | Highlight records/captures, refine patterns, trace output back to source | Execution contract awaits the author's extraction tools |
| Tables / spreadsheet data | Data grid + column/type inspector + transformation steps | Select columns/cells, inspect conversions, review missing or rejected values | A table viewer is not a general spreadsheet formula engine; honour Calc's bounded contract |
| Signals / 1D and 2D analysis | Plot + series/table browser + analysis options | Select intervals, compare series, inspect extraction/analysis results | Declare axes, units and coordinate mapping; qualify each operation |
| Workflow construction | Operation graph + resource edges + selected contract + run/evidence panel | Connect compatible ports, find a failing step, inspect a handoff | Edits change the real workflow document through the shared service |
| Structure / UML / class views | Typed diagram + attributes/relationships + associated source | Inspect classes, associations or collaboration relationships | Requires an explicit structural-model contract; no arbitrary code round-trip promise |
| Concepts / mind maps | Topic map + notes + linked evidence | Explore ideas and attach references; promote a branch into a workflow proposal | Non-executable planning data until an explicit declared transformation is applied |

Animation/timeline, image-region extraction and other specialist arrangements can
be added through the same mechanism once their data and operation contracts exist.
Do not install placeholder workflows that look executable when support is absent.

## Interaction model

Offer a workspace switcher separate from the adaptor selector. A user can choose
the task directly; the active resource or operation can also suggest a useful
workspace. Keep suggestions explainable and preserve explicit user choices.

Common controls remain recognisable: source, parameters/properties, help,
capability search, commands, agent context, execution history and evidence.
Presets select which panels are initially visible, their arrangement, the focused
resource and relevant tool groups. Allow a user to save a personal arrangement.
Avoid showing every possible editor simultaneously.

Switching workspaces must preserve:

- Source drafts, including invalid/incomplete text, and their undo grouping.
- Document/resource identities and revisions; active jobs continue independently.
- Named and historical references, with stale and incompatible states explicit.
- Agent task context and any pending proposal's base revision.

View changes, zoom, column width, node position and panel focus belong to UI/session
state. They do not advance the executable document revision unless a particular
view operation explicitly edits authored intent, such as setting a saved camera.
Keep portable presentation preferences optional and separate from execution input.

## Editors are reusable, with explicit write capabilities

A panel contract declares:

```text
identity + representation version
accepted resource/document kinds
observation requests and pagination/sample limits
supported selection/reference kinds
read-only, annotation-only, or authored-edit capabilities
available actions -> declared operation/edit-service IDs
staleness rules and error/unsupported-state presentation
UI-state serialisation independent of authored document serialisation
```

Read-only resource display is the default. To make a grid editable, declare how a
cell change affects a source table, a literal document value or a transformation
operation. To make a graph editable, define valid node/edge kinds and their mapping
to the document. An image/geometry annotation does not automatically edit the
native object. Edits require expected document/resource revisions and share the
same validation and undo rules as commands and AI requests.

Use registered trusted panel implementations. A workspace configuration selects
those implementations and their declared options; input files must not load
arbitrary JavaScript, Python or remote panel code. Share rendering components where
useful without conflating the semantics of different document kinds.

## Selection, provenance and cross-panel links

Use a common selection envelope with typed payloads. For example:

| Pick | Identity that must be retained | Example linked view |
| --- | --- | --- |
| Log span/capture | Source snapshot, encoding, line/byte span, extraction stage | Highlight contributing text for a result row |
| Table cell/row | Table revision, row/column identity and source lineage | Show captures and parse conversions |
| Plot interval | Series revision, domain/sample range and units | Filter corresponding rows without modifying raw data |
| CAD subelement | Native object/subelement and source revision | Populate a compatible operation argument |
| Workflow node/edge | Authored operation/port/artifact identity | Focus source, properties, run state or evidence |
| UML element | Structural model ID, element kind and model revision | Focus its declared attributes or linked source |
| Mind-map topic | Concept document/node identity and linked evidence | Add explicit context to an agent request |

The composer can include any compatible reference chip. An agent can request the
referenced evidence without the whole resource being pasted into its context.
Shared references do not imply interchangeable types: a text selection cannot
silently become an executable operation or a CAD surface.

Keep lineage separate from screen location. An output table row may derive from
several text spans; the relationship must survive scrolling and reordering. A
plot pixel is not a scientific value until an explicit axis/series mapping resolves
it. A clicked diagram node is not an arbitrary native object reference.

## Diagrams: common renderer, distinct meaning

- **Workflow graph:** nodes are declared operations; edges express actual typed
  dependencies or artifact handoffs. Dependency validation and execution order
  come from the engine, not the arrangement on screen.
- **Class/UML/collaboration diagram:** nodes and relationships describe a structural
  or interaction model. Decide supported semantics and source mappings before
  offering editing or generation. A collaboration diagram does not itself imply
  a multi-user collaborative editing service.
- **Mind map:** nodes organise ideas, notes and evidence. Turning a branch into an
  executable workflow is an explicit proposal with discovered capabilities,
  unresolved questions and validation; free-form arrows never execute by accident.

Each diagram can coexist with source, inspector, references and AI. They should
not share an untyped catch-all graph document merely because they look similar.
Multi-user synchronisation is a separate future capability; current local session
ownership and revision checks remain in effect.

## How workspaces support both main purposes

In human authoring, the workspace helps construct and understand a reusable
procedure. In AI-driven work, it provides observability and precise human feedback:
the user can indicate a face, log block, unexpected table row or conceptual node.
The agent continues through the common discovery/execute/observe protocol.

Workspaces can expose available evidence representations to agents, but selecting
a graphical arrangement must not be necessary for headless execution. An agent
asks for table summaries or text matches through observation contracts; it does
not need to operate the grid with mouse clicks to obtain the same information.

## Delivery order and acceptance

1. Define preset/panel/reference contracts alongside shared authoring, using
   existing geometry plus synthetic text/table fixtures to expose hidden CAD
   assumptions. Keep synthetic data labelled until the real extraction code lands.
2. Implement capability exploration and two genuinely different workspace layouts:
   geometry study and text extraction. Connect the latter to the supplied tools
   once their semantics have been qualified.
3. Add reusable table/plot panels and a real workflow graph. Qualify explicit edits,
   dependency errors and source synchronisation, not just diagram rendering.
4. Introduce concept maps and structural/UML tooling as bounded document types
   when actual workflows justify them. Add specialist timelines and other panels
   through the same registry rather than building separate application shells.

Acceptance requires switching layouts without data loss, linked source/evidence
selection, compatible-action suggestions, correct stale states and accessible
keyboard alternatives. A second, non-geometric workspace is a requirement for
claiming the framework is general. Native/application qualification is independent
of GUI layout quality.
