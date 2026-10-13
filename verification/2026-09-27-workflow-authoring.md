# Workflow authoring acceptance — 2026-09-27

M3's third production slice connects a workflow diagram to shared source/history,
agent tools and real artifact dependencies. It follows typed inspection `0ce4426`.
[Guide](../docs/workflow-authoring.md) · [Native report](2026-09-27-workflow-authoring.json)

## Changed behaviour

- Framework workflow documents now use the existing console authoring owner,
  recoverable JSON, property patches, file conflicts and shared undo. They are
  separate from native adaptor registration; dynamic adaptor entries remain live.
- The host planner produces operation nodes and exact `$artifact` handoff edges
  with JSON pointers. Scheduled readiness and serial declared order are distinct.
- Diagram selections open exact source values. Existing handoffs can be changed
  atomically after full host validation, with stale-revision rejection and one
  undo group. Invalid source removes the old diagram.
- `workflow-operation` references retain authored values and source provenance.
  They represent historical declarations, not successful native execution.
- Workflow `plan_draft` retains the existing task/provider budgets and stale-plan
  protections. Native console connection/preview shortcuts cannot bypass them.

## Host checks

Final full suite: **716 tests run, 22 skipped, no failures/errors**, 181.872 s.
Log: `evidence/workflow-2026-09-27/unit-final.log`. Public `discover` and all
**46** generated-reference checks pass.

Thirteen new tests cover graph/source parity, independent operations, serial order,
validated handoff replacement, atomic rejection of forward/self/missing references,
index validation, undo, stale revisions, retained invalid source and recovery,
typed historical operation references, framework/native separation, draft-linked
plans, scope enforcement, bounded graph paging, busy console ownership, example
creation preserving existing documents and empty draft/execution separation.

The fresh-interpreter guard now exercises workflow draft creation, graph inspection
and handoff editing while native imports/process launches are prohibited.
The existing dynamic-registry regression caught an initial copied-registry bug;
the final implementation uses a live `ChainMap` and that regression passes.
The 32-test console suite passed after the fix. JavaScript syntax and generated
reference checks also pass. The 18-test inspection suite additionally verifies
Unicode/CRLF offset conversion in both directions for diagram/source navigation; full-suite results are recorded below.

## Native acceptance

The deterministic public-agent client in `tools/qualify_workflow_authoring.py`:

1. Creates a workflow with an original producer (0–4), alternate producer (10–14)
   and a consumer that doubles values from the selected CSV.
2. Captures the original plan, rejects a self-reference, and retains an authored
   operation chip. Changes the consumer to the alternate producer through the
   graph handoff API.
3. Rejects execution of the stale captured plan, checks the old chip's staleness,
   and confirms the graph/source pointer both contain the alternate handoff.
4. Captures a new plan, executes with one worker, and reverifies **3 operations,
   3 jobs and 6 artifacts** using GNU Octave **11.3.0**.
5. Captures the verified consumer table as a snapshot and inspects exact y values
   **20, 22, 24, 26, 28**.

Final run: **26 requests**, **22,691 response bytes**, largest response **4,197
bytes**. Poll counts can vary. The first qualifier attempt executed and verified
successfully but its report lookup omitted the scheduled `/0` batch suffix; that
client lookup was corrected and the whole case rerun. The successful report is
`evidence/workflow-2026-09-27/native-final/report.json`.

This is one serial scheduled workflow, not MPI coverage, arbitrary artifact-type
compatibility or autonomous-model evaluation. No new native operation was added.

## Browser acceptance

The actual web console was checked in the desktop browser:

- Switching to Workflow study and creating the example retained the earlier
  document and displayed two operations with one real artifact edge.
- Selecting the consumer and opening its source focused `/operations/1`; opening
  the handoff focused `/operations/1/document/nodes/0/options/file`.
- Capturing an operation produced a correctly typed authored-declaration chip.
- Editing the handoff index advanced revision 3 → 4, updated the graph/selector,
  and disabled saving context containing the stale revision-3 chip.
- Shared source undo restored artifact index 0 at revision 5. Invalid source at
  revision 6 removed the diagram; a browser reload retained the invalid draft
  and displayed the repair/undo guidance. Undo restored the graph at revision 7.
- Navigating to a different operation preserved unsubmitted source text and
  required an explicit retain/reload before source navigation.
- A visual check confirmed the desktop diagram, source navigation and context
  layout. No mobile or large-graph layout qualification is claimed.

## Limits

The browser explicitly limits diagrams to 100 operations, 200 handoffs and a
65,536-byte response; the agent can page the full graph. Operation chips are
limited to 16,384 bytes. Host planning does not establish artifact availability or
native compatibility. Graph execution overlays, nested node editing, drag-to-connect,
custom layouts, reusable selectors, UML/concept maps and extraction remain open.
