# Headless agent lifecycle — 2026-09-27

M1 was committed as `fb687d3` before this work began. M2 now has a transport-neutral
`ExecutionService`, a local JSON-lines tool transport and native serial acceptance.
It uses the existing authored JSON, registry/workflow execution and verification
contracts. No application-specific operation or third-party dependency was added.

[Usage and protocol](../docs/agent-service.md) ·
[Machine-readable evidence](2026-09-27-agent-service.json)

## Implemented

- Captured documents and complete plans, immutable IDs/digests and expected-revision
  checks. Executing an older plan against the latest task revision is rejected;
  the host plan is recomputed before dispatch to detect changed declarations.
- Caller-authorised provider scope, fixed attempt/repeated-failure/time budgets,
  asynchronous job status, cancellation and interrupted-owner recovery.
- One serial job owner shared with the console. Existing workflows retain their
  scheduler, with parent cancellation now propagated into scheduled workers.
- Exact bounded JSON observations for documents, plans, results, faults and
  verification; publication descriptors tied to producer and receipt digests.
- Digest-checked resource byte reads, small JSON/CSV inspection and explicit
  resource-ID bindings into existing standalone file options. Existing workflow
  `$artifact` handoffs remain managed by the original scheduler.
- Local `schemaxis agent --workspace DIRECTORY` transport with correlated tool
  requests, discoverable method signatures and no network listener. This is a
  documented JSON-lines protocol, not MCP or a model-provider integration.

Principal files: `execution_service.py`, `agent_transport.py`, `jobs.py`,
`observations.py`, additive CLI integration, console job-owner wiring and the
scheduler cancellation fix. Tests and `tools/qualify_agent_service.py` provide
host and native acceptance. Generated module indexes are updated.

The other workspace's `docs/design/adaptor-candidates.md` and README changes were
observed and left to that workspace; they are not part of this implementation.

## Verification

- Full unit suite: **664 tests run, 22 skipped, zero failures/errors**, 166.573 s.
  Log: `evidence/agent-service-2026-09-27/unit-final.log`.
- Focused service suite: **20 passed**, including publication-failure recovery
  checks added during the final full run. Discovery/planning also passes in a
  fresh process that rejects all native imports and process creation.
- Console server: **7 passed**. Existing asynchronous commands, cancellation,
  token/origin controls and visual-reference behaviour remain covered.
- Scheduler: **13 passed**, including a new parent-cancellation propagation test.
- `schemaxis discover`, all **46** generated reference checks and whitespace pass.

Host checks cover stale plans, changed captured requests, scope rejection,
immutable observations, artifact/receipt tampering, incompatible resource bindings,
missing-runtime faults, exhausted attempts/deadlines, repeated unchanged failures,
process cancellation (including cancellation during evidence publication),
workspace ownership, restart and uncertain-publication recovery, malformed state,
pointer/byte bounds and correlated transport errors. A real Python child process
is used for process-cancellation testing; this is separate from application-native
qualification.

## Scripted native transport acceptance

The qualifier communicates through the public subprocess transport and retains
its service workspace, authored inputs, plans, native outputs and receipts under
`evidence/agent-service-2026-09-27/native-final/`.

| Case | First observed volume (mm³) | Refined target/result (mm³) | Attempts |
| --- | ---: | ---: | ---: |
| 20 × 10 × 5 box | 1,000 | 1,500 | 2 |
| 7 × 11 × 3 box | 231 | 693 | 2 |
| 12 × 8 × 4 box | 384 | 960 | 2 |

FreeCAD **1.1.3** verified all six native executions. Each refined height was
computed from the previous observed volume; each native volume matched an
independent analytic expectation. Every attempt retained and reverified FCStd,
STEP and STL publications.

A separate **GNU Octave 11.3.0 → LibreOffice Calc 26.8.0.3 → Octave 11.3.0** workflow
used the existing declared `$artifact` handoffs. Verification covered three jobs,
three operations and eight artifacts. The inspected readback spectrum preserved
the expected **frequency-8 peak (per input-domain unit), with amplitude 2**. No agent-authored conversion script
bridged the applications. Another standalone job consumed the verified table via
a service resource ID and passed verification. A table-to-CAD binding was rejected
with `TYPE_MISMATCH` before execution.

The scripted client made **157 requests**, receiving **92,274 bytes** of JSON
responses; its largest response was **5,531 bytes**. One deliberately incompatible
request was rejected. Counts include status polling and therefore vary with native
runtime speed. These are transport bytes, not model-token measurements. The three
box variants were fixed acceptance cases, not a blinded model-evaluation dataset.

## Direct agent-authored numerical refinement

A separate live tool session exercised a new numerical case
without the scripted qualifier:

1. Search for and retrieve the declared Octave `sequence` and `scale` contracts,
   including required document fields.
2. Author a five-sample sequence from 2 to 14. Execute it and inspect the returned
   statistics and table through resource IDs: observed mean **8**, domain and
   values **[2, 5, 8, 11, 14]**.
3. From that observation, choose scale factor **20 / 8 = 2.5**, add the declared
   scale operation and capture a new plan revision.
4. Execute and independently reverify the revised request. Inspect mean **20**
   and values **[5, 12.5, 20, 27.5, 35]**, with the original domain preserved.

The native runtime was **GNU Octave 11.3.0**. All **18 tool requests** succeeded;
the task consumed exactly its two-attempt budget. Authored documents, receipts,
resource digests and job history remain in
`evidence/agent-service-2026-09-27/agent-live/`. This demonstrates one actual
agent-authored feedback case. It does not establish general model reliability,
held-out success rates or cross-provider agent compatibility.

## Limits and next work

- Native coverage here is serial FreeCAD and numerical/spreadsheet workflows.
  No new MPI, GPU, exhaustive application or GUI qualification is claimed.
- The local transport supports a trusted subprocess client. A provider-specific
  client/MCP integration and broader held-out agent evaluation remain open M2 work.
- Execution captures and revisions are separate from the console's editable draft
  history. M3 should join the shared draft/edit/undo service to this lifecycle while
  retaining the existing authored document model and native-state ownership.
- Resource IDs are durable within their workspace, not portable native handles.
  General conversion planning, arbitrary format inspection and large log extraction
  are not implemented. JSON/CSV structured inspection is limited to one MiB.
- Budgets bound attempts, elapsed native dispatch and responses; they are not a
  hard host-memory/disk sandbox. Host planning and verification are cooperative.
- Cancellation/interruption preserves requests and partial outputs but reports
  uncertain native state. It does not roll back files or silently resume attempts.
- Captured verification is historical evidence. `verify` performs a fresh check,
  and resource reads/bindings recheck digests rather than assuming files unchanged.
- YAML parsing, the new authoring GUI and the forthcoming extraction adaptor remain
  deferred. The other workspace's adaptor-candidate design remains independent.
