# Reusable multi-case workflow proofs

Subsequent [actual AI pilots](2026-09-28-ai-workflow-pilots.md) now supplement
these deterministic proofs; their limitations and provider blockage are recorded
separately.

Four editable benchmark families now support ordinary native scripting and
template-assisted Schemaxis runs: RLC→Calc, FreeCAD→Gmsh→ParaView, CFD slices,
and a simple CSV→Calc control. The [guide](../docs/benchmarks.md) documents
preparation, repetition, revision, independent grading and future AI trials.
The [case list](../examples/benchmarks/cases.json) can be repurposed without
editing the native reference implementations or adding a framework parameter DSL.

## Fresh native results

| Method | Initial | Unchanged repeat | Revision |
| --- | ---: | ---: | ---: |
| Ordinary native reference | 8/8 | 8/8 | 9/9 |
| Schemaxis-assisted reference | 8/8 | 8/8 | 9/9 |

All **50 case-rounds pass** execution and the common independent artifact grader.
Revisions change inductance, box height, slice positions and one table value,
then add another circuit. There are 14 circuit outputs, 12 CAD/mesh outputs,
12 CFD case outputs containing 48 slices, and 12 table-control outputs.

The grader checks closed-form complex circuit response, actual workbook contents,
native reopened CAD, independently parsed MSH volume/boundary coverage/named faces,
VTU measurements and the ParaView integration table. CFD checks read published
VTP geometry and U/p values against independent analytic expectations. The public
CFD input is an eight-cell generated fixture with explicit provenance, not a
claimed solved flow. Producer success flags do not determine artifact grades.

All **10 selected falsification checks** pass: each method's outputs are copied,
then independently challenged with a wrong complex sign, wrong physical face name,
substituted later-time slice, wrong workbook value while CSV remains correct,
or missing case. The common grader rejects every mutation. Unit tests additionally
cover invalid case specifications, equal task/data digests, separate trial exports,
workbook/CSV corruption and MSH face/tag corruption.

Schemaxis reused **10/20 jobs** on the unchanged repeat: circuit, workbook, CAD
and mesh jobs reused; ParaView inspection/slice jobs reran. The revised round
reused **4/22 jobs** belonging to unchanged circuit/CAD/mesh documents. Attempts
are keyed by authored document hash. Changed documents start fresh because the
resume API requires an unchanged authored workflow; this is not evidence of
incremental recomputation across document edits. The ordinary reference deliberately
reruns scripts, so reference timings are not a fair performance comparison.

## Existing saved-field CFD case

The comparison uses a small tutorial case with saved solution fields (not
distributed), accessed read-only. A local copy is retained only in ignored
evidence; no private case data or account paths enter the public fixtures.
Redistribution permission has not been established. No remote builds, solver jobs or reconstruction ran.

The decomposed case contains four processor partitions and **10,720 cells**.
At saved time **500**, two local serial slices agree between direct ParaView and
Schemaxis in counts, bounds, area and U/p tuple distributions. They contain **332**
and **338** cells, with areas approximately **22.0300703113** and **22.0500740238**.
This demonstrates native post-processing equivalence using a shared ParaView
reader, not solver convergence, field-unit validation or independent flow physics.

Two real limitations remain recorded:

- Whole-workflow host inspection of the CAD→Gmsh handoff rejects an extensionless
  placeholder with `INVALID_RESOURCE`. Native execution resolves the produced
  STEP and passes. The enabled task instructions disclose this limitation.
- For this private decomposed tutorial, a requested time zero fails in Schemaxis
  with `TIME_UNAVAILABLE` despite explicit `skipZero: false`. The direct native
  reader exposes times 0 and 500. Only time 500 passes the private comparison;
  the exact cause of the time-zero failure remains unconfirmed.

## AI comparison readiness and verification

Both initial trial workspaces are staged with equal task/data digests, separate
instructions and measurement records marked `not-run`. **No autonomous AI
head-to-head trial has been scored.** The Schemaxis arm receives prepared templates,
so future results must identify it as template-assisted. The guide requires equal
models/budgets, isolated environments, retained transcripts, repeated trials and
held-out revisions. Token/cost data remains null until actually measured.

Fresh host regression: **770 passed, 22 skipped (792 total)** in **219.879 seconds**.
All **56 generated reference files** are current. All **14 previously registered
native receipts** remain source-current; no framework/adaptor implementation or
receipt was modified. This update adds coordinator tools, examples, tests
and documentation. Earlier receipt coverage remains bounded to its cited cases;
the two capability protocol checks were not rerun for these additions.

Passing evidence is retained under `evidence/benchmark-setup/`:

- `pack-qualified/`, `proof-qualified/report.json`: equivalent inputs and all six
  passing method/round reports.
- `challenges/report.json`: all ten rejected mutations on copied artifacts.
- `private-cfd-saved-time/report.json`: two passing saved-time slices.
- `private-cfd-qualified/`: retained failed 0/500 attempt, not a passing proof.
- `trials/ordinary-01/`, `trials/schemaxis-01/`: unrun initial AI trial packets.
- `unit.log`, `qualification-status.json`: regression and source freshness.
- `claude-request.txt`, `claude-response.json`: case-discovery provenance.

Earlier failed development runs remain available. They exposed coordinator bugs
and framework boundaries; they are neither successful acceptance runs nor AI
trial observations. Native runtime configuration and user PATH were unchanged.
