# Workflow diagrams and feedback settings

The Workflow study workspace now supports editable data arrows and saved feedback
groups. Numerical settings belong to a closed group of runtime data dependencies;
an ordinary one-way chain has no feedback settings. Visiting the same adaptor
again, such as FreeCAD → Gmsh → FreeCAD, does not itself create a feedback loop.

## Use the designer

Start the visual console and select **Workflow study**:

```sh
PYTHONPATH=src python3 -m schemaxis console --provider workflow --workspace evidence/my-design --web
```

Open an existing ordinary workflow or choose **New example workflow**, then create
an editable design. The original document remains in the session. Operations can
be added or changed through the existing source/property editor; the diagram
projects those exact operation documents.

Choose a producer output and a consumer input in the diagram, or use the equivalent
form controls. Select an artifact handoff or numeric value, its zero-based artifact
index and, for a value, its JSON pointer within the artifact. A connection replaces
the selected existing consumer input. Artifact availability, type and value units
still require native receipt validation; drawing an arrow is not that validation.

When an arrow closes a runtime data loop, the feedback panel opens for that group.
Choose fixed point or constant relaxation and save the iteration bound and absolute
and relative tolerances. Constant relaxation also requires a factor greater than
zero and at most one. These are coupled-variable convergence settings, distinct
from a native solver's own tolerances. Convergence must eventually be tested using
the raw feedback residual, before applying relaxation; a small damped step does
not establish convergence.

Each closed group has its own settings. Removing an arrow removes any group it
breaks. Changing the group's wiring or model invalidates settings for the old
group. Graph edits and configuration saves each form one undo group. Undo, redo,
source saving and session recovery use the same durable revision history as other
console documents. Invalid source never leaves the last valid diagram presented
as current.

## Current execution boundary

**This milestone implements design and configuration, not native coupled-loop
execution.** Fixed point and constant relaxation can be configured and saved.
Aitken, quasi-Newton, step doubling and STSC appear with their outstanding
requirements and cannot be selected as implemented methods. Step doubling is
time/parameter-step error control, rather than a general algebraic-loop solver.
STSC requires qualified source-contribution interfaces in the participating
adaptors. No adaptor acquired those interfaces through this milestone.

An acyclic design can be compiled into a separate ordinary workflow draft. The
compiler applies arrows, orders operations by their real data dependencies and
uses the existing host planner. Use the normal authorised execution service for
that compiled workflow. A cyclic design fails compilation and execution planning
with `FEEDBACK_EXECUTION_UNAVAILABLE`, even after its configuration is saved.
Saving, inspecting, drawing arrows and compiling never launch a native app.

## Saved design and agent access

New designs are `schemaxis.workflow-design/2` JSON documents; saved
`schemaxis.workflow-design/1` designs remain readable. Both contain an ordinary
`workflow` body, explicit `connections`, and `controllers` keyed by the derived
feedback-group identity. Version 2 also declares operation `ports`, exposed
`parameters`, named `outputs`, output `naming` and canvas `layout`, and its
connections join `{operation, port}` ends. It is an authoring document, separate from the executable
`schemaxis.workflow/1` and parameter manifest `schemaxis.workflow-template/1`.
Existing template manifests and case values retain their current contracts.
Automatic template packaging and resource staging remain separate milestones.

A version 1 connection declares `id`, `source`, `target`, `targetPointer`, `kind` and
`artifactIndex`; `kind: "value"` also declares `valuePath`. The target pointer is
relative to the target operation's document. Connections address existing inputs,
not operation identities, versions or output declarations. Model identities and
internal wiring determine feedback-group identity; the browser never supplies
its own cycle classification.

Create a blank design with `new "My design" workflow-design`. To reopen a saved
design, select that provider before `open /absolute/path/design.json`. Use the
shared source editor or `write /absolute/path/design.json` to save it.

The [agent service](agent-service.md) exposes the same functionality:

| Method | Result |
| --- | --- |
| `create_workflow_design` | New design capturing the current ordinary workflow; original retained |
| `workflow_graph` | Bounded projection, available input targets, closed groups and algorithm catalogue |
| `connect_workflow` / `disconnect_workflow` | One validated, undoable connection edit |
| `configure_workflow_feedback` | Validated settings for the exact current closed group |
| `compile_workflow_design` | New host-planned ordinary workflow, for acyclic designs only |

All take the current document identity and expected revision. Existing draft
source, patch, reference, undo/redo and file-conflict APIs also apply. A direct
`plan_draft` of an acyclic design requires explicit compilation first. A direct
plan of a cyclic design cannot bypass the missing feedback executor.

The browser retains its 100-operation, 200-edge and 64 KiB projection limits;
agent paging can inspect larger projections. This is an operation-level designer.
Native geometry/region parameter selection, automatic adaptor insertion, numerical
execution histories and editable layout positions remain future work.
