# Workflow study and shared drafts

The **Workflow study** console preset displays the actual operations and artifact
handoffs in a `schemaxis.workflow/1` document. Source, properties, console commands,
agent edits and handoff controls share one document revision and undo history.
The ordinary workflow diagram is a projection of the existing host planner, with
no native execution. The [editable designer](workflow-design.md) adds a separate
saved design document for new arrows, closed feedback groups and their settings.

## Try it

In any web console, choose **Workflow study**, then **New example workflow**. This
creates another document and retains existing documents. The example declares two
Octave stages: generate five samples and read/scale the published CSV. It is real
executable input, initially unexecuted. No native installation is needed to inspect
or edit it; native execution requires configured stage providers.

Alternatively, start with an empty workflow document:

```sh
PYTHONPATH=src python3 -m schemaxis console --provider workflow --workspace evidence/my-workflow --web
```

Choose **Workflow study** in the workspace menu. To load an existing workflow,
enter `open /absolute/path/workflow.json` in the command console. In an existing
session, `new "My workflow" workflow` creates a separate workflow document;
`use DOCUMENT_UUID` switches between retained documents. `list` and `inspect ID`
inspect its operations. Node-specific commands such as `add ID FILTER` are not
workflow-stage editors; use source or JSON property patches for structural edits.

1. Select an operation in the diagram or its keyboard-accessible button list.
2. **Edit operation source** opens the shared source/property editor at its exact
   `/operations/N` value. Edit a nested property or the complete JSON source.
3. Choose an artifact handoff and change its earlier producer or artifact index.
   **Apply handoff change** validates the complete draft and records one undo group.
4. **Edit handoff source** navigates to that exact `$artifact` value. Undo in the
   editor reverses a diagram edit; source edits refresh the diagram at a new revision.
5. **Reference operation** creates a typed chip containing the historical authored
   operation, its document/revision, source digest and host-planning scope.

Dirty, unsubmitted source is retained when navigating from a diagram. Retain or
explicitly reload it before selecting another source location. Invalid retained
JSON hides the diagram until repaired or undone; it never leaves an old graph
labelled as the current valid workflow. Workspace changes preserve drafts/history.
An empty workflow can be saved as a draft but cannot be planned for execution.

## What edges mean

Actual `$artifact`, output-value and cross-operation document references produce
graph edges. Artifact edges report the
producer operation, consumer operation, zero-based artifact index, and exact JSON
pointer. Independent operations have no invented data edge. The view also states
whether the planner uses scheduled execution or declared serial order; serial
operations run in declared order even without a data edge. Scheduled dependencies
constrain readiness, and the existing scheduler owns batching/resource policy.

A producer must appear earlier in the authored operation list. Forward references,
self references, missing producers and invalid indices are rejected before an edit
is published. These restrictions apply to ordinary executable workflow drafts.
The separate designer can retain cycles and compile acyclic graphs in dependency
order; cyclic native execution remains unavailable.
The controls replace existing artifact references; adding/removing operations or
new handoff fields uses ordinary source/property edits and existing contracts.

A successful host plan does **not** prove that an artifact index exists, its kind
is accepted by the reader, or its native contents are valid. The existing execution
path rechecks producer receipts and consumer requirements. A nonnegative but
unavailable index can therefore pass host planning and fail native execution.
The diagram explicitly reports host-planning scope, never native success.

Operation chips have kind `workflow-operation` and `replayable: false`. They retain
an authored declaration, not evidence of a successful native run. Any subsequent
document revision—including undo—makes that historical chip stale for new context.
The historical payload remains inspectable. Native results and text/table snapshots
continue through the separate verified job/resource/inspection methods.

## Agent access and execution

Use the same [local agent transport](agent-service.md). `create_draft` now accepts
`provider: "workflow"`, which denotes a framework document, not a native adaptor.
The native adaptor discovery/authorisation registry is unchanged.

| Method | Purpose |
| --- | --- |
| `workflow_graph(document_id, expected_revision, **page)` | Read the validated graph with ordinary bounded observation paging. |
| `rewire_workflow(document_id, expected_revision, pointer, source, artifact_index)` | Replace an existing graph edge through validated shared authoring. |
| `reference_workflow(document_id, expected_revision, operation_id)` | Capture a historical authored operation in the common reference store. |

Existing `draft`, `edit_draft`, `patch_draft`, `locate_draft`, undo/redo and file
conflict APIs work on workflow drafts. `plan_draft` captures the full workflow
under a task authorised for its actual stage providers, such as `octave` and
`calc`. It does not authorise a fictitious native `workflow` provider. Later draft
edits invalidate that plan for execution; capture a new plan at the task's next
revision. Existing execution budgets, cancellation and receipt verification apply.

The graph UI has no execution button in this slice. Use the agent's existing
`plan_draft` → `execute` → `observe` → `verify` lifecycle, or write the source and
use ordinary CLI `plan`/`run`/`verify`. Console `preview`, native `connect` and `live`
are explicitly unavailable for framework workflow documents.

## Limits and next work

The browser displays at most 100 operations, 200 handoffs and a 65,536-byte complete
graph response. Larger graphs give an explicit message; agent member/pointer
paging retrieves the full projection. Operation reference payloads are limited to
16,384 bytes; larger operations remain accessible through source slices. Source
retains the existing one-MiB authoring bound. Diagram focus is transient; the
selected workspace preset remains durable. SVG layout does not change the model.

This is an operation-level diagram. The editable designer now supplies connection
authoring and feedback configuration. Nested node graphs, graph execution status,
custom graph layouts and reusable authored selectors remain future work.

[Verification](../verification/2026-09-27-workflow-authoring.md) records host,
browser and native execution checks. Reproduce the native case with:

```sh
PYTHONPATH=src python3 tools/qualify_workflow_authoring.py --output-directory evidence/workflow-qualification
```
