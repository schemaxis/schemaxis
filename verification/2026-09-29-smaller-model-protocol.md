# Smaller models with trusted Schemaxis recipes

Protocol recorded 2026-09-29. This is a benchmark addition, not a product runtime
change.

## Primary comparison frozen before model timing

Six cells cross Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), Sonnet 4.6
(`claude-sonnet-4-6`) and Opus 5.5 (`claude-opus-5-5`) with native ParaView and
Schemaxis recipes. Exact IDs were exercised in isolated access probes. CLI 2.1.284,
requested effort `high`; this flag does not imply equal reasoning mechanisms or
compute across model generations. No fallback model is configured. Observed usage
model IDs are retained and checked. Fresh Opus runs are the comparator; historical
onboarding results are context only.

All cells receive equivalent operating instructions, qualification evidence and
the same bounded public checker. The instruction explicitly forbids routine source
audits, custom validators and reference renderers, while allowing investigation
of execution/check failures and requests outside the documented scope. Agents
must report verification limits rather than claim independent image semantics.
The hidden grader still checks geometry, fields and decoded image camera, colour
and time. It and future reference outputs are absent from agent filesystems.

Each independent conversation has initial, unchanged repeat, revision and damaged
publication repair rounds, with 10 case checks and 220 artifact checks. The unit
of replication is a four-round conversation, not an artifact. First run a
24-turn pilot, inspect harness validity, then extend to three conversations per
cell (72 turns total) if no protocol correction is necessary. Pilot results are
retained regardless of outcome. Infrastructure defects require explicit
adjudication; do not discard ordinary model failures to improve scores.

Each replicate uses new dimensions and field offsets, identical across its cells.
Across all three replicates, each cell occupies every serial position twice;
native/Schemaxis order reverses twice within every four-round replicate. Model
runs execute serially to avoid competing native rendering loads. Shared provider
prompt caching remains possible; fresh conversations do not mean cold caches.

Per invocation: 600-second wall timeout. Claude CLI budget flag: USD 6, with
resumed-session accounting retained. These are list-price estimates, not account
subscription charges. A provider error blocks further model dispatch; a model
timeout/budget failure retains and grades its outputs. No human corrections or
hidden grader feedback go to contestants. First-task exact-input qualification
and recipe/checker preparation are excluded from model timing and reported
separately, not represented as free correctness. This tests prepared recipe
operation, not general capability or deployment reliability.

## Verification and display characterisation

Run focused harness tests, new-task native proof, and the unchanged grader's eight
corruption challenges before model timing. Separately execute twelve isolated
render invocations: native/Schemaxis × initial/revised × three repeats. Retain
exit codes, logs, elapsed times, actual artifact grades and display-error markers.
A clean sample does not establish that the previously intermittent X failure is
fixed. Retain all such failures and recovery costs during the model trial.

## Planned secondary comparisons

After validating the Claude pilot, add GPT-5.6 Luna versus GPT-6 Astra using Codex
CLI with the same namespace boundaries, tasks, grader and trust policy. Local
Codex 0.157.1 supports explicit model selection and resumed JSONL sessions. Verify
access, actual session model, continuation and token accounting before scoring.
OpenAI API list-price estimates must distinguish input, cached input, cache writes
and output and must not be represented as subscription billing. Keep provider
comparisons separate because client tools and system prompts differ.

Add a bounded fresh-conversation authoring test, without the complete recipe,
to determine whether successful operation extends to assembling the workflow.
Freeze that secondary protocol before launching its model calls. Do not infer
broad model equivalence from universal success on a supplied procedure.

## Outcomes and evidence

Primary outcome: all four rounds independently pass, with the required method
actually used. Also report per-round success, silent incorrect publications,
repair, wall time, usage, cost and evidence of instruction compliance. Report
three replicate values and ranges, not statistical equivalence from this sample.

Source, recipe, checker, task, input and executable digests, model settings,
commands, prompts, raw transcripts and workspace snapshots are retained locally.
Bulk evidence stays ignored. Published summaries link readable transcripts.
Existing unrelated edits to the previous transcript index are preserved.

Pricing references inspected 2026-09-29:
[Claude](https://platform.claude.com/docs/en/about-claude/pricing),
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).

## Secondary protocol frozen before its model calls

OpenAI recipe follow-up: Luna and Astra × native/Schemaxis, one independent
four-round conversation per cell (16 turns). Use replicate-1 task bytes, the same
600-second limit and requested `high` effort. This is an exploratory follow-up;
its one-conversation cells do not acquire the Claude matrix's three replicates.
Both access probes passed and a separate Luna continuation probe established that
Codex's `turn.completed.usage` is session-cumulative. Account for cache writes,
cache reads and ordinary inputs separately. Preserve session-context model IDs;
stop for adjudication on a model mismatch or a request above the 272K pricing
threshold. The CLI has no matching USD budget flag; its runs are wall-time bounded.

Authoring follow-up: all five tested models × native/Schemaxis, one fresh
conversation per cell, initial then revision (20 turns across two provider runs).
Use replicate-3 task bytes, fixed before authoring sessions. No complete recipe,
previous conversation, hidden grader, reference image or benchmark solution is
provided. The coordinator still preflights runtime/checker but removes the seed
script and seed-specific qualification statement before the first model call.
Both methods get the task contract and public checker. Native gets its public
ParaView Python API; Schemaxis gets existing public documentation, CLI/schema
entry points and a note explaining artifact identity/path publication. Neither
gets task-specific implementation code. Interface discovery and authoring are
allowed; routine library audits and custom validators remain discouraged.

Use 600 seconds per turn, requested high effort, and the same Claude budget flag.
Keep provider comparisons separate. A first-round failure stays scored even if
the second round succeeds. No grader feedback enters the revision request. This
is a harder diagnostic of workflow construction in the same task family, not an
unseen-domain benchmark or a replicated comparison of general intelligence.

## OpenAI runner correction, before replacement scoring

The first OpenAI attempt (`ai-paraview-openai-01`) is excluded in full. The
namespace mounted the Codex executable without its sibling `codex-code-mode-host`.
A language-only access probe passed, but the actual command tool could not start.
The model correctly reported that it could not read the task; this is a harness
infrastructure failure, not a capability failure. The partial transcripts, costs
and explicit adjudication remain retained. The coordinator was stopped before
continuing this defective trial; the completed Claude matrix is unaffected.

The correction mounts the existing companion executable read-only beside Codex.
Fresh isolated Luna and Astra tool probes each executed ParaView and produced an
actual rendered sphere image successfully. A regression test now classifies the
missing-host error as infrastructure failure even when the CLI emits a final
reply and exits zero. The complete replacement uses fresh conversations and
workspaces under `ai-paraview-openai-02`; tasks, grading and model instructions
are unchanged. Source snapshots distinguish the transport correction. All
thirteen focused harness tests passed after the correction.

## Authoring provider substitution and unavailable cell

The first Claude authoring invocation requested Opus 5.5. Its transcript records
`model_refusal_fallback`: Anthropic classified the request as `cyber`, stopped the
Opus 5.5 response, and Claude Code automatically switched the session to Opus 4.8.
All observed task-working assistant messages were Opus 4.8. No fallback was
explicitly configured by this experiment. The model-identity gate stopped the
coordinator; `ai-paraview-authoring-claude-01` is retained as an off-protocol
observation, not an Opus 5.5 result. Its 222.571 seconds and USD 0.8602363 estimate
remain recorded separately. Diagnostic hidden grading failed despite the supplied
checker passing; that grade was obtained after the identity-based exclusion.

The Opus 5.5 native-authoring cell is marked unavailable due to provider refusal
and substitution. It is not retried or relabelled as Opus 4.8 in the planned matrix.
The remaining five Claude cells use fresh conversations in
`ai-paraview-authoring-claude-02`, with `--omit-arm opus-native`; their prompts,
tasks, budgets and grading are unchanged. Model substitution now retains a
separate diagnostic grade, marks that cell unscored, skips its remaining rounds,
and allows the other predeclared cells to proceed. No prompt or provider guard
setting is changed to force an answer. OpenAI authoring remains the two-model,
two-method comparison as declared. The loss of this Claude control is explicit;
it is not replaced with historical data or inferred from the other cells.

## Completion

The comparison finished with 106 scored turns across 31 conversations. See the
[results and method audit](2026-09-29-smaller-model-results.md) and
[readable transcripts](2026-09-29-smaller-model-transcripts.md). The authoring
Opus native cell remained unavailable as declared. Fifteen focused unit tests
passed after adding a reporting safeguard against aggregating whole excluded
experiments. No product runtime changed, and no further model run is active.
