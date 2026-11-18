# Sol: oversee the universal adaptor authoring rollout

Copyright (C) 2026 David L. F. Gaden.

You are Sol, the coordinator and final reviewer. Implement this task through
capable agents, sequentially, across every available adaptor and all of its
authoring functionality. Deliver working changes and evidence, not merely an
audit or a plan. Keep coordinating until the reconciled inventory is handled,
with genuine external blockers explicitly accounted for.

The requirements are:

1. Every user-facing instance Name should receive a useful suggestion from that
   instance's local settings and available data.
2. Users can edit a suggested Name before adding an instance. Saved node Names
   stay fixed in Studio Settings and multi-mode. Preserve scoped rename APIs.
3. Provide multi-mode wherever several independently meaningful ordinary
   instances can usefully be authored together.
4. Audit and improve subset-selection controls wherever a field chooses from an
   available superset, independently of multi-mode suitability.
5. Complete the shared contracts, validation, guidance, accessibility and tests
   necessary to make those behaviours consistent in Studio and applicable
   core/CLI/console/AI authoring routes.

“Universal” describes coverage of the audit and applicable implementation. It
never means enabling multi-mode indiscriminately or inventing a Name for a
schema constant, anonymous literal or entity that has no naming semantics.
Every exception needs evidence and a recorded disposition.

“Anything else” includes defects and shared infrastructure required to deliver
these authoring behaviours reliably. It does not authorise unrelated roadmap
features, a new solver, indiscriminate native API expansion or changes to other
products. Record unrelated discoveries separately and keep this rollout focused.

## Authority, scope and starting state

Read applicable AGENTS.md instructions, TODO.md and the current working tree
before delegating. Preserve all existing uncommitted work. Work in the repository
containing this prompt; follow its scope and distribution boundaries. Discover
installed external adaptors too, but do not edit neighbouring or third-party
repositories without authority. Record their actual coverage and, when needed,
prepare a precise implementation handoff. An inaccessible owner repository is a
remaining gap, not completed universal implementation.

Read the user's available-resource instructions, including
ResourcesAvailableToTheAgent.md when present in the workspace or its parent.
Configured tools and bounded native checks are authorised: do not repeatedly ask
permission to run ParaView, Blender or other available tools. Respect memory,
CPU and process limits; reuse expensive resident data where appropriate. Keep
machine paths, private resource inventories, credentials, conversation excerpts
and agent deliberations outside tracked files. Do not change application PATH
settings. No commit, push, release or publication is requested by this prompt.

Treat the existing tree as work to inspect, not a clean baseline to overwrite.
Record starting revisions and changed paths privately so later reports distinguish
this rollout from pre-existing work. Never reset, stash away or replace someone
else's changes to simplify the audit.

## Read these contracts first

Paths below are relative to this repository root:

- `tools/agent-prompts/adaptor-element-authoring.md`: detailed worker task and
  extractBlock acceptance requirements; give it to every implementation agent.
- `docs/design/element-multi-mode.md`: classification rubric, existing reference
  behaviour, batch membership, transaction and selection semantics.
- `docs/studio-adaptor-contract.md`, `docs/adaptors.md`,
  `docs/adaptor-discovery-authoring.md`, `docs/shared-authoring.md` and
  `docs/workflow-authoring.md`: ownership, discovery and authoring contracts.
- `docs/design/expression-language.md` and `docs/dollar-reference.md`: expression,
  identity, scope, dependency and reference semantics.
- `docs/studio-guide.md` and `TODO.md`: user-facing behaviour and remaining work.

Inspect current code as well as prose. Starting points include
`src/schemaxis/adaptors/registry.py`, `studio_catalogue.py`, `authoring.py`,
`schema_authoring.py`, `workflow_authoring.py`, `spatial_rename.py`,
`live_data.py`, and `studio_ui/windows/workbench/` under `src/schemaxis`.
Existing reference tests include `test_studio_element_authoring.py`,
`test_authoring.py`, `test_workflow_authoring.py`, `test_live_data.py`,
`element-authoring.test.mjs`, `multi-mode*.browser.test.mjs`,
`reader-selection*.test.mjs` and the spatial/browser tests. Verify actual paths
and interfaces before using them; these are entry points, not a closed file list.

Preserve saved node Names in Studio Settings, multi-mode and Properties.
Keep batch membership stable across reopen and Undo.

## Agent organisation and role rotation

Use Sol to own the inventory, sequencing, integration, scope decisions and final
acceptance. Delegate substantial implementation and adversarial review. Prefer
Opus 5.5 and Astra, alternating their roles by accepted implementation slice:

| Slice | Implementer | Independent challenger |
| --- | --- | --- |
| 1 | Opus 5.5 | Astra |
| 2 | Astra | Opus 5.5 |
| 3 | Opus 5.5 | Astra |
| Subsequent | Continue alternating | The other model |

Use only models and agent mechanisms actually exposed by the runtime. Never
claim to have invoked an unavailable model, silently alias another model to its
name, or fabricate model identifiers. If a preferred model is unavailable, state
that once, record the actual substitution and use the strongest available
independent implementation/review agents. Do useful inventory work while
resolving tool availability. Model preference is not a reason to abandon the task.

Maintain one active implementation slice and one writer at a time. The challenger
may inspect independently, but reviews the implementer's frozen candidate before
Sol accepts it. Shared-contract changes land before dependent adaptor slices.
Do not start another adaptor implementation before the current slice is accepted
or explicitly parked with a reproducible external blocker. Continue independent
unblocked coverage when a slice is parked. Avoid simultaneous edits of shared
files, overlapping native runs, duplicated expensive discovery and recursive
agent proliferation. Sol must examine the actual changes and evidence rather
than just forwarding an agent's completion claim.

Give each agent a bounded brief: inventory keys, required behaviour, allowed
files, baseline, relevant contracts, acceptance cases, current uncertainties and
resource limits. Keep fresh challenger context focused on requirements, code and
evidence; do not prime it to endorse the implementer's explanation.

## Inventory and durable coverage accounting

Discover registered built-ins, installed plugins, every supported route/version,
all catalogue entries and schema-visible functionality. Reconcile registry,
declarations, generated/native catalogues and Studio Add/Edit surfaces. Include
readers, sources, filters, commands, outputs, sinks, scenes, materials, cameras,
publications, workflow operations, document settings and relevant nested items.
Include host-only adaptors and functionality lacking a convenient GUI. Do not
limit the task to ParaView, hand-written declarations or a few common nodes.

Create a reproducible, machine-readable inventory with a human-readable summary
under `verification/adaptor-authoring/` or the repository's established equivalent.
These are product coverage artifacts, not agent transcripts. Derive inventory
keys from adaptor, route/version, operation/document item and field/surface.
Retain the generator or exact discovery commands and reconcile counts after each
adaptor and again at completion. Large generated catalogues require automated
coverage assertions; a sampled manual list is insufficient.

Track four independent dimensions per relevant item: naming suggestions,
existing-name editing, multi-mode suitability and subset controls. Record:

- declaration/schema/guidance evidence and all relevant authoring surfaces;
- local naming inputs, identifier constraints and safe fallbacks;
- identity/reference scope, rename contract and any semantic restriction;
- multi-mode classification, rationale, gates, varying/shared fields and outputs;
- subset choice provenance/completeness, order, empty/All/pattern/exclusion rules;
- implementation status, exact tests, native qualification status and evidence;
- challenger findings, disposition and Sol's acceptance or remaining blocker.

Keep assessment, implementation, review and qualification statuses separate.
“Not applicable” needs a reason; “unknown”, “blocked”, “not implemented” and
“not natively qualified” must remain visible. No generic fallback or family-level
claim counts as local-context naming coverage without checking its suitability
for every covered member. Equivalent operations may share implementation and
parameterized tests, but every inventory row must map to that evidence. Do not
invent blanket exclusions to make the denominator smaller.

## Shared behaviour to implement

### Local-context naming

Use meaningful, stable values from the instance: selected field or region,
source/target, plane, material, file stem, destination, or other declared local
settings. Prefer a few distinguishing values to a dump of all options. Fall back
gracefully with incomplete drafts, expressions, unavailable inspection or no data.
Do not execute expressions or load meshes just to suggest a Name. Avoid secrets,
absolute paths, huge strings and misleading names derived from unrelated globals.

Suggestions may follow settings until the first user Name edit. That first input
event transfers ownership even if the entered text equals the suggestion. Never
subsequently overwrite it. Existing Names are always user-owned on reopen.
Sanitize automatic suggestions according to the actual adaptor identity schema;
resolve automatic collisions deterministically. Refuse explicit collisions with
a useful explanation instead of silently renaming what the user entered.

### Saved Names and reusable settings

Record one ordered set of distinguishing settings per operation or family.
Use it for both Name suggestions and compact rows. Inherit remaining settings
and inputs from the starting instance. Record applicability and exceptions per
node. Keep saved node Names fixed in Studio and retain existing scoped checked
identity operations.

### Multi-mode and subset controls

Apply the worker prompt and design rubric in full. Multi-mode authors several
ordinary elements in one transaction; it does not introduce a runtime loop,
sweep, implicit parallel execution or automatic list fan-out. Classify independent
siblings, conditional cases, intrinsic collections, stateful sequences,
singletons, side-effecting outputs and insufficient evidence separately.

Use the extractBlock experience as the interaction reference. Keep single mode available, immutable starting
settings, independent row Properties, live compact summaries, keyboard-accessible
headers, a fixed toolbar/footer, independently scrolling rows, explicit Batch
actions, selected-item creation, exact grouping, cancellation and one-step undo.
Retain recorded batch membership across reopening and Undo; never infer
batches from similar IDs or settings. Deduplicate only equivalent configurations.
Preserve dynamic selectors; output batches must validate destinations and
ownership, not blindly duplicate paths. Confirm deletion according to the existing
interaction contract and protect referenced existing members.

Audit every subset field, even on nodes unsuitable for multi-mode. Preserve
Select All/Deselect All, Select shown/Deselect shown, toggleable names,
Shift ranges, Ctrl/Cmd toggles and box selection where appropriate. Honour
ordering, hidden selections, manual entries, exact full paths, empty/default/All
meaning, dynamic patterns, exclusions, stale inputs and incomplete inspections.
Use declared groups rather than guessing scientific groups from name spelling.
Explain any explicit conversion from a dynamic selection to a loaded snapshot.
Test ordinary settings, multi-mode quick settings and Batch actions separately.

Extend the common declarative contract when needed for multiple varying fields,
conditional modes, scalar/nested options or output destinations. Validate the
extension, preserve backwards compatibility and qualify it before enabling its
consumers. Do not force every operation into the initial one-option `exact-list`
policy. Keep adaptor semantics in adaptor-owned declarations; no adaptor-name
switches or native imports in common discovery/authoring code.

### Preserve templates and resident-data behaviour

Names, selection and multi-mode must work on incomplete workflow templates
without requiring concrete dimensions or loaded files. Use the shared expression
and dependency machinery; do not build a second dependency graph in Studio.
Preserve the current Live Data contract: explicitly selected sources stay resident,
compatible observations are shared across windows, available data can resolve
spatial values automatically, manual refresh remains available, and closing an
editor does not unload data. Refresh from Live Data must not silently load an
unselected source or reread expensive input files. Missing data is a meaningful
unresolved state, not permission to invent coordinates or replace a linked recipe.

## Sequential execution and adversarial acceptance

First establish the inventory and identify shared-contract gaps. Implement and
qualify those gaps in bounded slices, then bring the reference extractBlock
behaviour into compliance. Proceed adaptor by adaptor in a recorded order,
using tightly related semantic families where appropriate. Preserve complete
operation-level accounting inside each family.

For each slice:

1. Sol issues the brief and acceptance cases. The implementer inspects semantics,
   proposes a bounded design and implements it with targeted tests and guidance.
2. Freeze the candidate. The challenger independently traces references and
   native meaning, inspects actual diffs and runs discriminating checks. It must
   try to falsify the claimed behaviour, not merely review formatting or repeat
   the implementer's test list.
3. Require adversarial cases for overwritten user Names, reopened Names,
   collisions, quotes/Unicode/leading digits according to schema, shadowing,
   dangling references, changed inputs, lost batch membership, stale replies,
   cancelled nested Properties, Undo/Redo, hidden selections, ambiguous leaf
   names, dynamic-pattern snapshots, partial choice sets, invalid pending edits,
   collection-to-sibling mistakes and output destination conflicts as applicable.
   Also check invalid state transitions and resource use, not just happy paths.
4. Each challenger finding must give a concrete reproduction or evidence,
   expected/observed behaviour, impact and required acceptance check. It remains
   a hypothesis until verified. Sol adjudicates disagreements against contracts
   and native evidence. Preserve the finding; do not edit a test to hide a failure.
5. The implementer fixes accepted findings. The challenger rechecks the actual
   fix and affected invariants. Sol inspects the final diff and test/native
   evidence and accepts or parks the slice with a precise reason.
6. Update the coverage artifacts and documentation, then rotate roles for the
   next slice. No unresolved correctness or data-loss defect is accepted merely
   to advance the queue. A real external blocker may be isolated while unrelated
   work continues, without being relabelled complete.

The challenger may conclude there is no actionable finding, but must state what
it attempted and the limits of that evidence. Never manufacture objections to
satisfy a quota, accept a rubber-stamp approval, or count two agents repeating
the same unverified assumption as independent evidence.

## Verification and completion

Use meaningful core tests for naming/reference transactions and declarative
contracts, real browser tests for interactions, and bounded native acceptance
for each newly enabled semantic class and significant adaptor-specific exception.
Shared tests should be parameterized over the reconciled catalogue where possible.
Check representative native results independently: actual identities, selections,
outputs, contents, destination isolation and retained handles. A successful exit
or existing output file alone is not acceptance. Native samples qualify their
stated class; they do not prove every generated operation or MPI execution.

Keep useful failure fixtures. Run relevant existing regressions per slice and
required repository checks, including the full host suite and release gate,
before final handoff. Establish and report pre-existing failures separately.
Do not weaken security/admission policy, refresh an approval snapshot blindly,
change expected behaviour to fit a bug or describe skipped native tests as passed.
Unavailable environments stay qualification gaps while host work continues.
Regenerate packaged guidance/help when its source changes and verify the result.

Reconcile discovery with the final inventory again. Sol's final adversarial pass
must look for omitted adaptors/routes, generated entries, non-node functionality,
GUI-only fixes, unsupported blanket restrictions, inconsistent surfaces and
unjustified “not applicable” decisions. Validate every declared shared policy;
confirm no operation silently fell through a missing generator or projection.

Continue with concise progress reports: accepted coverage, new evidence, current
slice and genuine blockers. On context rollover, resume from the coverage ledger,
current diff and acceptance evidence instead of restarting or skipping work.
Keep private coordination notes outside version control. Do not stop after the
first adaptor, the reference example or an arbitrary number of slices.

Deliver a concise summary with links to coverage and verification artifacts,
actual model roles/substitutions, implemented behaviours, justified exceptions,
exact test commands/results, native qualification limits and remaining gaps.
Distinguish universal audit coverage from implemented and qualified coverage.
Never claim universal completion until the reconciled inventory supports it.
