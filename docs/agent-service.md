# Headless execution and local agent tools

The shared `ExecutionService` connects progressive discovery to captured plans,
verified execution, bounded observations and managed artifact references. Humans
and agents submit the same authored JSON accepted by the existing CLI. The service
uses the existing registry, workflow scheduler, native dispatchers and verifiers;
it does not introduce another graph language or execution engine.

Start the local tool transport from the repository root:

```sh
PYTHONPATH=src python3 -m schemaxis agent --workspace evidence/my-agent-session
```

This is `schemaxis.agent/1`, a dependency-free **JSON-lines subprocess transport**.
It is not MCP, a model provider or a network listener. A client keeps stdin open,
sends one JSON request per line and receives one response with the same ID:

```json
{"id":1,"method":"methods"}
{"id":2,"method":"capabilities.search","params":{"query":"extrusion","scope":"domain/geometry"}}
```

The `methods` response describes the available methods and parameter names/defaults.
Successful replies are `{"id":1,"ok":true,"result":...}`; unsuccessful replies are
`{"id":1,"ok":false,"fault":...}` with the existing structured fault envelope.
Requests are limited to one MiB, IDs to 128 characters, and malformed requests do
not discard the service session. EOF requests cancellation, waits for active work
to finish and closes ownership. Keep the process open to execute, poll and cancel.
Do not pipe an execute request and immediately close stdin expecting detached work.

The transport is intended for a trusted local client. Provider scope records the
caller's authorisation and bounds the task's provider choices; it is not an OS
sandbox or proof that a human approved an arbitrary new task. The client must map
its user's existing authorisation to the task. Runtime paths come from the normal
private configuration, not authored tool code. No arbitrary Python, shell text or
native reflection method is available through this transport.

## Common lifecycle

1. Use `capabilities.browse`, `capabilities.search`, `capabilities.describe` and
   `capabilities.schema` to retrieve the relevant existing contracts.
2. `create_task(objective, allowed_providers, budget?)` records the authorised scope
   and fixed budgets. It returns a task ID with revision 0.
3. `plan(task_id, document, expected_revision, bindings?)` validates ordinary JSON
   through the existing host planner. It captures the document and complete plan,
   advances the task revision and returns a plan ID, digest and provider summary.
4. `execute(plan_id, expected_revision)` starts the **current** captured plan and
   returns a job ID immediately. It does not re-read a client file or execute an
   earlier plan under a newer revision. It rechecks the host plan before dispatch;
   changed planning results require a new revision (`STALE_PLAN`).
5. `job(job_id)` returns small status without waiting for native execution.
   `observe(job_id=..., section=...)` retrieves bounded retained evidence. Inspect
   the verification scope and the values relevant to the objective.
6. Revise ordinary document values and call `plan` with the new expected revision.
   The earlier request, job and artifacts remain independently inspectable.
7. `verify(job_id)` rechecks actual artifacts and receipts. Report the evidence
   against the objective; a succeeded job is not automatically a satisfied goal.

For example, these are successive requests using IDs returned by earlier replies:

```json
{"id":3,"method":"create_task","params":{"objective":"Produce a 1500 mm3 box","allowed_providers":["freecad"],"budget":{"maxAttempts":2,"maxElapsedSeconds":180}}}
{"id":4,"method":"plan","params":{"task_id":"TASK_ID","expected_revision":0,"document":{"version":"schemaxis.freecad/1","nodes":[{"id":"body","filter":"box","options":{"length":20,"width":10,"height":5}}],"output":"body"}}}
{"id":5,"method":"execute","params":{"plan_id":"PLAN_ID","expected_revision":1}}
{"id":6,"method":"job","params":{"job_id":"JOB_ID"}}
{"id":7,"method":"observe","params":{"job_id":"JOB_ID","section":"verification"}}
```

A caller can inspect the returned volume, change height using the observed ratio,
and submit revision 2 within the already-authorised task. Approval is not inserted
at each step. A wrong or stale revision, unauthorised provider, exhausted attempt
budget or repeated unchanged failure stops execution with a distinct fault.

## Budgets, cancellation and persistence

Default task budgets are:

| Field | Default | Meaning |
| --- | ---: | --- |
| `maxAttempts` | 4 | Total execution attempts, including failures and cancellations. |
| `maxRepeatedFailures` | 2 | Stop re-executing the same captured document digest after this many failures with the same fault code. |
| `maxElapsedSeconds` | 600 | Elapsed wall time beginning at the first execution; includes idle time between attempts. |
| `timeoutPerStageSeconds` | 120 | Timeout passed to existing native execution stages. |

Attempt/repeated-failure limits accept integers 1–100; time budgets accept positive
finite seconds up to 86,400. An adaptor may enforce a smaller native-stage timeout.
Budgets cannot be silently expanded on an existing task. A new task requires a new
caller authorisation record. Failed planning is not a native execution attempt and
does not advance the current successful-plan revision.

Existing authored workflow execution budgets still govern job concurrency, thread
counts, MPI requests and resource reservations. This service serialises top-level
jobs, while a workflow may schedule its internal operations normally. These are
scheduler reservations and response bounds, not a new hard CPU/memory/disk sandbox.
The elapsed token reaches native dispatch and scheduled workers. Host planning and
verification are cooperative Python work, not forcibly interrupted mid-function.
An expired/cancelled attempt cannot be published as successful afterward.

`cancel(job_id)` reports `cancellation-requested` while dispatch terminates the
process tree. Terminal cancellation retains authored input and partial evidence,
sets `verified: false`, and reports `nativeState: unknown`. It does not imply a
rolled-back filesystem or guaranteed recovery of a live native application's state.
Normal console commands now share the serial job owner used by this service;
scheduled workflows inherit their caller's cancellation token.

An exclusive workspace lock prevents two service owners. `agent.json` contains
checksummed task/plan/job/resource records. Captured JSON uses the console's atomic
publication machinery. Plans are immutable files; execution uses fresh job
directories. Opening a workspace after an unclean exit marks unfinished jobs
`interrupted`, with uncertain native state. It never automatically resumes or
advertises their artifacts as verified. `list_tasks` and `task` recover IDs,
revisions and budget usage after reconnecting.

## Bounded observations

`observe` accepts exactly one of `job_id` or `plan_id`, plus a section:

| Section | Content |
| --- | --- |
| `document` | Exact captured authored JSON, including resolved external resource bindings. |
| `plan` | Complete retained planner output, accessed progressively. |
| `result` | Captured successful execution response. |
| `verification` | Captured successful verifier response. |
| `resources` | Publication descriptors from verified receipts. |
| `fault` | Structured failure, or null if absent. |

`pointer` selects an RFC 6901 JSON Pointer. The default budget is 8,192 bytes;
`max_bytes` accepts 2,048–65,536. A fitting value is returned in full as `mode: value`.
Larger objects/arrays return `mode: members`, with complete child pointers, up to
`limit` members (default 12, maximum 100), and `page.nextOffset`. Follow the same
pointer with `offset` to continue, and pass the returned `revision` digest to detect
changed evidence. Small child values may be included as a convenience. Larger
scalar values are rejected explicitly, never silently truncated.

Captured result/verification observations describe a particular completed attempt;
they are not a fresh check of external files. Call `verify` for a fresh check.
Failed reverification invalidates the job's successful status and blocks its
resources. Missing runtime, unsupported/incompatible input and verification failure
retain their own structured codes rather than becoming a generic success flag.

## Managed artifact references and inspection

Resources have a stable service ID, producer job/operation, captured document
digest, artifact kind, byte size, SHA-256 digest, and receipt identity/digest. Units
remain `unknown` unless declared by a future inspection contract; the service does
not infer them from application names. IDs survive service restart in the same
workspace. They are local durable references, not portable native handles.

`resource(resource_id, offset?, length?)` rechecks both publication and receipt
and returns a byte range encoded as base64. Length defaults to 4,096 and is capped
at 16,384 bytes. `nextOffset` explicitly marks remaining content.

`inspect_resource(resource_id, pointer?, offset?, limit?, max_bytes?, revision?)`
reads JSON or CSV publications of at most one MiB and returns bounded structured
observations. JSON values retain their types. CSV inspection reports header columns
and rows as **strings**, with unknown units; it performs no numerical conversion.
Other formats return `UNSUPPORTED_INSPECTION`, and larger files return
`INSPECTION_LIMIT` with the bounded byte-read alternative. This is small-publication
inspection, not the forthcoming log-extraction adaptor or arbitrary file parsing.

[Typed inspection](typed-inspection.md) additionally captures immutable text/CSV
snapshots, maps explicit numeric series and retains typed selections. Use
`snapshot_resource` to preserve a verified publication with its provenance, then
`inspect_snapshot`, `reference_snapshot` and `inspect_selection`. Workspace presets
change presentation independently of draft and task revisions.

A follow-up standalone plan can bind a previously verified publication into an
existing file option without adding syntax to the authored document language:

```json
{"id":20,"method":"plan","params":{"task_id":"TASK_ID","expected_revision":0,"document":{"version":"schemaxis.octave/1","nodes":[{"id":"data","filter":"readCSV","options":{"file":null,"xColumn":"x","yColumn":"y"}}],"outputs":["data"]},"bindings":{"/nodes/0/options/file":"RESOURCE_ID"}}}
```

The binding resolves before host planning. The consumer's declared accepted
artifact kinds must match. Resource/provenance digests are checked at planning,
before dispatch and after execution. The resolved ordinary document and the binding
record are retained. An unsupported handoff fails; no implicit conversion script
is generated. Within a workflow, continue using existing `$artifact` references,
which the existing scheduler resolves against reverified producer receipts.
External service bindings currently apply to standalone documents only.

## Python client and qualification

```python
from schemaxis.execution_service import ExecutionService

with ExecutionService("evidence/my-service") as service:
    task = service.create_task("Authorised box study", ["freecad"])
    # service.plan(...), service.execute(...), service.job(...), service.observe(...)
```

`locations=` is a trusted Python constructor override for configured runtime paths;
it is not an authored tool parameter. The same service is callable by a future GUI
or another transport. [Shared authoring](shared-authoring.md) now exposes the
console's editable document history through draft tools. Use `plan_draft` to bind
execution to the current draft identity/revision; ordinary `plan` remains available
for standalone requests and workflows. [Workflow drafts](workflow-authoring.md)
now support the same draft-bound lifecycle, with bounded graph inspection and
revision-checked handoff editing.

The [workflow designer](workflow-design.md) adds `workflow-design` drafts,
`create_workflow_design`, `connect_workflow`, `disconnect_workflow`,
`configure_workflow_feedback` and `compile_workflow_design`. The same graph method
reports cycles and settings. These are host authoring methods; configured cycles
cannot execute until a qualified feedback executor is implemented.

```sh
PYTHONPATH=src python3 tools/qualify_agent_service.py \
  --output-directory evidence/agent-qualification
```

The qualifier talks only through the public agent subprocess, constructs and refines
three dimension variants, verifies an Octave → Calc → Octave handoff, inspects its
spectrum, and reuses a publication through a service binding. It records request
counts, response bytes, attempts, rejections and actual verification scope. It is a
deterministic client proof, **not an autonomous-model evaluation**, and does not
establish MPI or exhaustive native coverage. See
[the implementation verification](../verification/2026-09-27-agent-service.md).
