# Clean AI comparison: RLC circuits to workbooks

A fresh pair completed with valid configuration and a successful native
preflight. **Both methods passed all seven case-rounds. Schemaxis was 9.3% slower
overall and had 23.4% higher estimated list-price usage cost in this pair.** This simple task provides no
observed efficiency win for Schemaxis in the completed clean trial.

## Results

| Round | Ordinary scripting | Schemaxis required | Artifact grades |
| --- | ---: | ---: | --- |
| Initial two circuits | 93.38 s | 118.55 s | Both 2/2 |
| Unchanged repeat | 80.96 s | 68.78 s | Both 2/2 |
| Changed inductance and new circuit | 24.17 s | 29.69 s | Both 3/3 |
| **Total** | **198.52 s** | **217.01 s** | **Both 7/7** |

| Usage metric | Ordinary scripting | Schemaxis required |
| --- | ---: | ---: |
| Input tokens, including cache reads/writes | 350,494 | 453,940 |
| Output tokens | 11,971 | 12,574 |
| Estimated list-price cost | $0.4713 | $0.5817 |
| Tool calls | 23 | 22 |
| Corrective human interventions | 0 | 0 |

Timing covers each complete agent invocation: reading, authoring, debugging,
execution, self-checks and final response. It excludes coordinator staging,
native preflight and independent grading. The repeat round includes implementing
reuse and testing it, so its duration is not the native cost of a cached rerun.
Costs come from Claude's reported list-price estimates, not subscription billing.
Cumulative conversation costs were not double-counted.

## What actually ran

Both conversations used `claude-opus-5-5`, high effort and Claude Code 2.1.284.
Native runtimes were ngspice 47 and LibreOffice 26.8.0.3. Each invocation had the
same 300-second wall bound and `--max-budget-usd 3` CLI setting. All six invocations
completed without timeouts, provider errors or permission denials.

The initial pair had two circuits, including a negative source amplitude. The
undisclosed revision doubled one inductance and added a third circuit with a
different sweep. Initial Schemaxis templates were not regenerated. The
coordinator-owned task/data digests match between methods in every round.

The ordinary agent wrote a reusable procedure calling ngspice and LibreOffice
directly. It added reuse checks covering the netlist, CSV frequency grid and
values, workbook contents and completion log. It also fixed two problems with
running an archived copy of its own script: finding runtime configuration and
attempting to copy itself onto itself.

The enabled agent authored ordinary Schemaxis workflow documents and invoked
`python3 -m schemaxis run` for both application stages. For reuse it called
`schemaxis verify`, checked hashes against published artifacts and independently
compared CSV/ODS values to the analytic circuit response. It implemented the
case-selection/reuse wrapper itself; this was not a demonstration of the
workflow executor's `--resume` path.

Both agents reused the two unchanged cases, then regenerated the changed case,
kept the unchanged one and generated the newly added case. Neither needed a code
change for the final revision. Schemaxis genuinely executed the enabled method's
simulation/workbook steps; this is distinct from the earlier availability pilot,
where the agent chose direct native scripting.

The same independent grader checked every requested complex response, magnitude,
phase, frequency and actual workbook value against closed-form expectations.
Producer success claims and framework receipts did not determine these grades.
Model procedures, native outputs and transcripts support the separate method-use
review. The two agents had separate filesystem/process namespaces, with the
coordinator, grader, future revision and other method's files absent.

## Friction exposed

The enabled agent made two failed exploratory launches before its successful
first workflow:

1. A fresh nested output path whose parent did not exist failed with `INVALID_INPUT`.
2. Creating the final directory then failed with `OUTPUT_EXISTS`.

Creating only the parent and selecting a fresh final directory succeeded. This
was a concrete CLI usability issue. A subsequent
[workflow output-directory fix](2026-09-28-workflow-output-directory.md) addresses
both cases; these original benchmark measurements remain unchanged. The prior invalid-config
mistake was absent; native preflight and the versioned configuration were valid.
No implementation or instructions were changed to help the agents mid-trial.

The raw automatic `toolErrors` count is zero for both methods, but shell pipelines
masked inner failures. It must not be interpreted as zero failed commands or zero
debugging. The transcript records the failures above and the ordinary agent's
script-copy fixes. Neither method received human repair hints.

## Scope and next test

This is one exploratory pair in fixed ordinary-then-Schemaxis order, not balanced
replication or a statistical comparison. It measures cold agent use with initial
templates supplied only to the Schemaxis method. It establishes a narrow result
for straightforward circuit/workbook automation, not performance across all
adaptors or a general rejection of declarative workflows.

The next useful challenge is ParaView work involving several datasets and times,
cell/point field associations, consistent colour ranges/cameras and later changes
to slices or presentation settings. Its common grader must cover those requirements
before model runs begin. The known private-case time-zero failure remains a
separate documented gap; this RLC trial neither tests nor fixes it. Repeat with
new parameter variants and balanced order before claiming an overall advantage.

## Evidence and reproduction

Fresh evidence: `evidence/ai-rlc-required-clean-02/`.

- `report.json`: raw six-round execution, usage and independent grades.
- `measurements.json`: corrected token/cost totals.
- `adjudication.json`: method compliance, equal task digests and limitations.
- `ordinary/` and `schemaxis/`: prompts, transcripts, graded publications and
  per-round workspace snapshots; final trial records are marked completed.
- `schemaxis/native-preflight.log`: successful actual two-application dispatch.

The tested product source commit is `d99e3e5`. Follow the
[runner instructions](../docs/benchmarks.md#running-the-actual-rlc-ai-pilot) with a
fresh output directory to repeat. Earlier optional-use, config-confounded and
provider-blocked attempts remain in the [historical pilot record](2026-09-28-ai-workflow-pilots.md).
No framework/adaptor source, native configuration or user PATH changed during
the measured trial. The subsequent directory fix and its separate verification
are linked above; it was not part of these timings.
