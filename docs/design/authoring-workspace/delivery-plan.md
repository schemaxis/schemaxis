# Capability workspace delivery plan

2026-09-27 · staged implementation backlog. M1 is now implemented; see the
[verification record](../../../verification/2026-09-27-capability-discovery.md).
The M2 service and local agent transport now have
[native and agent-authored acceptance](../../../verification/2026-09-27-agent-service.md).
The first M3 [shared authoring slice](../../shared-authoring.md) now has recoverable
JSON drafts, revision-checked edits, shared undo and draft-bound agent execution.
The next [typed inspection slice](../../typed-inspection.md) adds immutable
text/CSV snapshots, numeric series, common references and trusted workspace presets.
[Workflow study](../../workflow-authoring.md) now connects operation/artifact
graphs to shared source, typed operation references and validated handoff edits.
Broader model evaluation, nested graph editing and reusable selectors remain open.

This plan implements the two equal purposes in [architecture.md](architecture.md):
AI-driven application use and human-authored reusable workflows. A GUI is optional
for agent work; templates are optional for exploratory work. Both use the same
capability contracts, declarations, execution and evidence.

## Existing foundations and actual gaps

| Foundation | Current location | Next work |
| --- | --- | --- |
| Adaptor metadata and operation discovery | `src/schemaxis/adaptors/registry.py` | Bounded summaries, categories, purpose metadata, canonical links, search and pagination |
| Hierarchical native help | `src/schemaxis/adaptors/paraview/mvp/hierarchy.py` | Reuse useful concepts; expose consistent adaptor-wide discovery without treating inventoried native properties as executable |
| Operation descriptions and schemas | `src/schemaxis/__main__.py`, `schema.py`, `schema_authoring.py` | Selected contract bundles with semantics, examples, units and prerequisite links |
| Planning, running, verification, workflow artifacts | Registry, adaptor implementations, workflow/dispatch modules | Common agent-facing request/result lifecycle; data-aware suggestions; visible conversion plans where supported |
| Data traits and compatibility | `docs/paraview-catalogue.md`, data-contract code | Shared resource descriptors, explicit unsupported/unknown state and bounded observations |
| Console state, jobs and visual references | `console_session.py`, `console_server.py`, `console_references.py` | Recoverable drafts, revision-aware edit service, resource references beyond geometry/images |
| Numerical/table adaptors | Octave and Calc; `docs/numerical-analysis.md` | Consumers for compatible extraction outputs; honour existing row/column/type limits |
| Log extraction | User's tools not yet supplied | Inspect real semantics and fixtures before implementing an adaptor |

The current top-level `discover` includes full operation-name lists. `query` can
match declared operation names or examine a document's requirements; it is not
yet semantic intent search. Current ParaView hierarchical help is a retained,
application-specific facility. There is no unified general agent tool server,
automatic conversion optimiser or generic text-extraction GUI established by this
design. The prototype's YAML serializer does not establish YAML input support.

## M1 — Progressive capability navigation

**Outcome:** a new client can find the relevant contract without receiving every
schema or needing to open a native application.

Work:

- Add catalogue views over the existing registry: task domain, application,
  capability group and curated interface. Start with small curated group maps;
  keep canonical operation identities and one authoritative declaration source.
- Add stable links/IDs, catalogue digest, bounded listings and deterministic
  pagination. Detail requests select schema, examples, requirements or evidence.
- Separate declared support, runtime availability, qualification and input
  compatibility. Missing catalogue information is labelled unknown.
- Add CLI access to the service first; existing commands remain compatible.

Acceptance:

- Starting from data-analysis or geometry intent, find a suitable current
  operation through search or breadcrumbs and retrieve its complete contract.
- A task already naming an operation can access it directly.
- Native libraries/processes are absent from discovery/planning.
- Unknown and ambiguous paths return useful parent/alternative links.
- Every required contract section can be fetched; truncated responses are explicit.
- Record bytes/tokens and navigation steps for representative tasks against the
  current flat discovery path. Agree a response budget before optimising; do not
  claim efficiency solely from a smaller-looking response.

## M2 — Headless agent loop with existing capabilities

**Outcome:** an agent discovers, plans, executes, examines and refines a bounded
task using the common service without a browser or manually authored template.

Work:

- Wrap existing plan/run/inspect/verify/job behaviour behind a small transport-
  neutral service. Add one supported agent tool transport after its contract is
  settled; GUI integration must not be a prerequisite.
- Publish resource IDs, captured document revisions, job status, artifact
  descriptors and bounded observations. Preserve structured native faults.
- Record task authorisation, attempts, execution budgets and stop conditions.
- Supply a short client guide and contract examples. Start with ordinary tool-
  using agents; fine-tuning is an optional later experiment, not required plumbing.

Acceptance:

- Complete a bounded existing FreeCAD or numerical-analysis task, inspect the
  result and make one deliberate revision using returned evidence.
- Complete a supported existing cross-adaptor handoff using resource/artifact
  references, with no ad hoc data-conversion script written by the agent.
- Missing runtime, incompatible input and verification failure produce distinct
  outcomes and actionable feedback. No false success based only on exit status.
- A repeated failed approach stops at a configured bound; cancelling retains
  authored intent and reports uncertain native state correctly.
- Measure completion, contract violations, context volume, retries and unsupported
  requests on held-out task variants. Record native qualification separately from
  host-only/tool-double checks. Domain understanding remains necessary.

## M3 — Shared authoring and typed inspection

**Outcome:** forms, source, commands and agents can collaborate on one document;
task-oriented workspaces assemble editors and inspection panels by resource kind.

Work:

- Extract the revision-aware authoring service from current session behaviour.
  Add recoverable invalid drafts, located diagnostics, grouped undo and file
  conflict detection. An edit preserves authored expressions.
- Define observation/reference envelopes for native geometry, images, text spans,
  tables and series. Keep historical picks distinct from reusable selectors.
- Define a trusted view registry and minimal text/table/geometry rendering
  contracts. Prototype text inspection with clearly synthetic fixtures until the
  user's extraction tool contract is available; do not advertise an adaptor early.
- Add a workspace-preset registry using the contracts in [workspaces.md](workspaces.md).
  Start with CAD inspection and text extraction as contrasting layouts, then a
  table/plot arrangement. Switching layouts must preserve drafts, revision identity,
  jobs and typed selections. Panel focus and layout preferences are not model edits.
- Implement JSON authoring first. Decide YAML parser/dependency and source-
  preservation policy, then qualify equivalent input and editing behaviour.

Acceptance:

- Equivalent edits through form, command and agent paths yield the same authored
  document and host plan. A stale client edit is rejected with current context.
- Invalid drafts survive recovery and cannot trigger execution of an earlier
  document under a misleading current-draft label.
- Selecting a source location focuses its property control and vice versa.
- A geometry pick and a text-span reference use a common envelope with distinct
  typed payloads and correct staleness behaviour. Neither is coerced into the other.
- A workflow diagram uses real operation/artifact dependencies; layout changes do
  not execute operations. Concept maps and future UML views remain explicitly
  distinct from executable graphs unless a declared transformation connects them.
- JSON/YAML equivalents produce equivalent plans once YAML support is enabled;
  diagnostics and source-preserving editing are tested separately.

## M4 — Log extraction: human and agent acceptance case

**Dependency:** the author's extraction code plus representative inputs/expected
outputs. Until supplied, M1–M3 can continue using existing capabilities and clearly
labelled text-view fixtures.

Intake needs: stage ordering semantics, grep/regex dialect and flags, record
boundaries, cross-line associations, numeric formats, encoding, missing values,
file sizes, expected outputs and at least one troublesome case. Preserve useful
behaviour already present in the author's implementation.

Work:

- Wrap bounded operations with declared input/output types, stage semantics,
  resource limits and verification. Avoid arbitrary shell fragments in authored
  inputs. Test timeout/cancellation for problematic patterns.
- Build coordinated source / extraction-stages / results views. Include match
  highlighting, named captures, rejected records, source provenance and an optional
  series plot. Display sample coverage and full-input status separately.
- Expose exactly the same stages, samples and diagnostics to agents. Text and
  extracted content are task data, never tool instructions.

Acceptance:

- Human path: highlight an example block, construct/edit stages, see captures and
  typed results, trace a row to its source, then run on a second representative log.
- Agent path: browse to the extraction capability, request a bounded sample,
  produce a request, inspect matches/misses, correct a fault and run the full input.
- Exercise zero matches, multiple matches, absent fields, malformed numbers,
  repeated record headers, differing line endings and changed source snapshots.
- Where applicable, exercise scientific-number notation and repeated-run/restart
  blocks; expected association rules must come from the supplied tool contract.
- A compatible output passes through an existing table consumer with declared
  units and shape. Unsupported missing-value/multi-series shapes fail explicitly.
- The agent never needs the complete large log in its context or a custom parsing
  script to achieve the supported extraction task.

## M5 — Promote successful work into reusable templates

**Outcome:** an exploratory human/agent run can become a comprehensible reusable
tool without rewriting the working procedure.

Work:

- Expose chosen values as parameters with labels, units, descriptions, bounds and
  relationships. Keep case bindings separate from procedure defaults.
- Generate a focused run form, retain executable source, and show dependency and
  handoff relationships. Validate another case before claiming reusability.
- Distinguish reusable selectors from example-file line numbers or native face
  numbering. Preserve the original example and its evidence as documentation.

Acceptance: the same procedure runs on multiple qualified cases through GUI, CLI
and agent paths. Parameter changes propagate without erasing expressions. Inputs,
procedure version and output evidence make case comparisons interpretable.

## M6 — Distribution and additional integrations

Detect/configure existing applications, then add qualified managed downloads and
licence-aware choices. Keep native installs and project resources separate. Add
more agent/AI transports only through the common service. Verify each provider's
actual integration/authentication terms before promising subscription support.
Circuit-design and other new adaptors follow real demand and native qualification.

## First concrete development slice

Start with M1 and a narrow M2 proof using existing operations. This establishes
the AI capability-environment purpose before investing further in CAD-specific
GUI polish. Extract shared contracts that M3 will also consume; the initial CLI
implementation is not a disposable second backend.

Use a registered operation's current declarations, one small purpose/category map,
bounded browse/describe responses and one complete agent run as the first reviewable
increment. Keep a coverage matrix linking every advertised capability to its
actual declaration, documentation, tests and qualification scope.

Do not block this slice on the extraction code, a universal installer, all AI
providers, full conversion planning or model training. Those are later dependencies
or independent product increments, not requirements for proving the shared protocol.
