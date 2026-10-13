# Actual AI workflow pilots

Two pairs of autonomous Claude conversations completed the RLC→workbook task.
Both methods passed every independent artifact check: **28 case-rounds** across
the two pairs. These are actual model runs, distinct from the earlier deterministic
reference proofs. A subsequent [clean comparison](2026-09-28-ai-workflow-clean-rlc.md)
completed with valid configuration; the historical pairs below retain their
original exclusions.

## Conditions and method

All conversations used **Claude Opus 5.5** (`claude-opus-5-5`), `high` effort,
Claude Code **2.1.284**, ngspice **47**, and LibreOffice **26.8.0.3**. Each method
received two initial circuits, an unchanged repeat, then a revised inductance and
a third circuit: seven case-rounds per method. Initial templates were available
only to the Schemaxis method and were not regenerated for the revision.

Bubblewrap supplied separate homes/workspaces, identical native applications and
an isolated process namespace. The ordinary namespace could not import Schemaxis;
only the enabled namespace contained its source, selected product documentation
and starting templates. Neither could access the grader, frozen future revision,
other method's workspace, repository evidence or reference solutions. Network
access remained available. Transcripts show local work with no coordinator hints.

The same 300-second wall bound and `--max-budget-usd 3` CLI flag applied to both
methods. Each retained its own conversation and code across three rounds. Runs
were serial in fixed ordinary-then-enabled order; this exploratory order is not
balanced replication. No human corrected either contestant's code during a run.
Independent grading happened against coordinator-owned tasks after each response.

## Availability pair: Schemaxis was not adopted

| Method | Case checks | Total response wall time | Output tokens | Estimated list-price cost |
| --- | ---: | ---: | ---: | ---: |
| Ordinary native scripting | 7/7 | 157.6 s | 11,146 | $0.4523 |
| Schemaxis available, optional | 7/7 | 134.2 s | 11,436 | $0.4494 |

The enabled agent read the templates but implemented direct ngspice and Calc
subprocesses. Both agents subsequently added their own verified artifact reuse.
This pair tests availability/adoption; **it does not measure a Schemaxis execution
advantage**. Its timing difference must not be attributed to the framework.

Evidence: `evidence/ai-rlc-pilot-01/`. `adjudication.json` records the observed
method choice. Raw reports and transcripts remain unchanged.

## Required-use diagnostic pair: functional success, timing confounded

A fresh pair explicitly required Schemaxis for the enabled method's simulation
and workbook handoff. It complied, authoring reusable workflows and invoking
`python3 -m schemaxis run`; the ordinary method used native subprocesses.

| Method | Initial | Repeat | Revision | Total wall time | Output tokens | Estimated list-price cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ordinary | 2/2, 112.6 s | 2/2, 60.6 s | 3/3, 29.1 s | 202.3 s | 13,351 | $0.5291 |
| Schemaxis required | 2/2, 134.9 s | 2/2, 67.6 s | 3/3, 31.6 s | 234.1 s | 13,980 | $0.7579 |

**Exclude this pair from a fair efficiency conclusion.** The coordinator supplied
`runtime.json` without the required `version: 1` field. This only affected the
Schemaxis method, whose agent diagnosed the configuration fault and generated a
valid configuration. That extra work and conversation context penalised it.
It was a benchmark setup error, not a Schemaxis defect. Its successful artifact
grades and actual framework execution remain useful functional evidence.

Both agents created reusable procedures, passed the unchanged repeat and handled
the changed circuit plus newly introduced case. CSV values and actual ODS contents
were checked independently against the closed-form complex response at every
frequency. Actual native netlists, workbook outputs and framework dispatch records
are retained; producer claims were not used as the numeric oracle.

Evidence: `evidence/ai-rlc-required-01/`, including per-round workspace snapshots.
The coordinator error and exclusion are explicit in `adjudication.json`.

## Corrected rerun: provider blocked

The runner now generates schema-valid native configuration and exercises a real
Schemaxis ngspice→Calc workflow in ephemeral storage before starting a model.
That native preflight passed for the corrected rerun.

The provider then returned **HTTP 429**, a temporary usage limit, with zero model
usage for every attempted turn; a later retry after the limit reset succeeded.
No model work executed in this corrected pair. Its absent-file grades are **not
model task failures** and must not enter the comparison. The original loop
attempted six turns before this was diagnosed; the updated runner stops at the
first provider API error. The CLI can report `subtype: success` while also
returning `is_error: true` and `terminal_reason: api_error`; classification now
checks those error fields.

Evidence: `evidence/ai-rlc-required-clean-01/`. Its raw report is retained alongside
`adjudication.json`, which marks the pair provider-blocked and unscored.

## Accounting, reproduction and next work

Claude's invocation `usage` counters and cumulative conversation `modelUsage`/
`total_cost_usd` counters differ. The summariser sums invocation tokens but uses
differences of cumulative cost for each round; it does not sum cumulative costs
as though they were individual charges. Costs above are provider list-price
estimates, not actual subscription billing. Wall time covers each CLI invocation,
including inference and native execution, and excludes coordinator staging/grading.

Tool-result error flags are retained but do not count every failed command or
semantic retry: shell pipelines can return success after an inner command fails.
Transcripts are the authority for detailed retry/compliance review. No claim of
zero semantic retries is made.

Use [the pilot runner instructions](../docs/benchmarks.md#running-the-actual-rlc-ai-pilot)
with a fresh directory. The corrected required-use RLC pair is now complete;
see the linked clean comparison. Next investigate stateful ParaView or CAD/mesh
work with a common independent grader, new parameter variants and balanced
repeated conversations. Keep optional
availability, required use and discovery-only conditions separate.

Five focused runner/accounting tests and six existing benchmark tests pass. They
cover real configuration loading, cumulative cost accounting, unknown usage and
the CLI's contradictory API-error envelope. No application adaptor or framework
runtime source changed. The preceding full regression remains 770 passed and
22 skipped; it was not rerun for these coordinator-only additions.
