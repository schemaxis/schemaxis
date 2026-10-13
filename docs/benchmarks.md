# Repeated workflow comparisons

This suite prepares reusable tasks for an ordinary AI workflow and the same AI
with Schemaxis available. Four task families exercise multi-case inputs, an
unchanged rerun, and a later revision. The coordinator supplies equal input data
and grades neutral files with the same independent checks for both arms.

**The supplied reference runs are deterministic engineering proofs, not AI
trials.** They establish that a task is achievable, its template can be reused,
and its grader detects selected errors. They do not measure AI success rates,
token savings or productivity. The separate saved-field CFD case comparison is
also not a scored trial.

## Task families

| Family | Initial cases | Required work | Revision |
| --- | --- | --- | --- |
| RLC → workbook | Two different circuits | Native AC frequency sweeps, complex voltage/magnitude/phase, editable ODS and netlist | Change one inductance; add a third circuit |
| CAD → mesh → ParaView | Two box specimens | Editable CAD/STEP, named Gmsh volume/end faces/remainder, MSH/VTU and integrated volume | Change one specimen's height |
| CFD post-processing | Two analytic OpenFOAM datasets | Two times and two slice positions per case, with cell U/p preserved | Move one case's slice planes |
| Table control | Two numeric CSVs | Preserve headers/values in CSV and editable ODS | Change one table entry |

There are eight initial cases, eight repeat cases and nine revised cases: **25
case-rounds per arm**, or 50 across both deterministic reference implementations.
The CFD datasets have different dimensions and time-dependent uniform fields on
eight cells. Their provenance explicitly says **generated analytic data, not a
solved flow**. They provide exact expected slice areas and field values without
requiring someone else's simulation data.

[The case list](../examples/benchmarks/cases.json) is the editable input surface.
Change parameter values or add uniquely named cases of a supported family.
[Templates](../examples/benchmarks/templates/) are ordinary Schemaxis JSON; the
coordinator fills their existing options and artifact references. The case-list
format is a benchmark manifest, not a new application input language or framework
runtime feature. The templates stay in the repository; private runtime locations
remain in the ordinary ignored configuration.

## Prepare and prove

From the repository root, use fresh output directories:

```sh
PYTHONPATH=src python3 tools/benchmark_workflows.py prepare \
  --output-directory evidence/my-benchmark-pack

PYTHONPATH=src python3 tools/benchmark_workflows.py prove \
  --package evidence/my-benchmark-pack \
  --config /absolute/private-runtime-config.json \
  --output-directory evidence/my-benchmark-proof
```

`prepare --cases /path/to/my-cases.json` repurposes the same templates. `prove`
accepts repeated `--family rlc`, `--family mesh`, `--family cfd` or `--family table`
selectors for smaller checks. The complete proof needs the existing ngspice,
FreeCAD, Gmsh, ParaView and Calc runtimes. No simulation, application installation
or MPI run is needed. Individual native subprocess trees have a 180-second bound;
failure logs and partial publications remain on disk.

The ordinary reference uses native scripts without importing Schemaxis. The
Schemaxis reference uses the generated workflows and preserves native attempt
history across repeat/revision rounds. Each authored workflow hash has its own
attempt: unchanged documents resume, changed documents start fresh. The resume
API rejects changed authored workflows; this suite does not claim incremental
recomputation across document edits. It reports actual per-job reuse; it does
not assume every provider can reuse inputs. Native ParaView file-reader jobs may
rerun. Changes in external input paths can also invalidate reuse. The ordinary
reference deliberately reruns its scripts; an AI in the real baseline may build
its own cache. **Do not use these reference timings as a performance comparison.**

`report.json` retains all six arm/round reports, native failures, elapsed seconds,
job reuse observations and independent grades. Correct files and successful
execution are both needed for a reference proof to pass.

## Stage actual AI trials

Export just one arm and one round into a fresh trial workspace:

```sh
PYTHONPATH=src python3 tools/benchmark_workflows.py stage \
  --package evidence/my-benchmark-pack --round initial --arm ordinary \
  --output-directory /absolute/trials/ordinary-01

PYTHONPATH=src python3 tools/benchmark_workflows.py stage \
  --package evidence/my-benchmark-pack --round initial --arm schemaxis \
  --output-directory /absolute/trials/schemaxis-01
```

Both exports contain `TASK.md`, `task.json`, identical input bytes and a
`trial-record.json` whose status starts as `not-run`. The Schemaxis arm additionally
gets materialised starting workflows. Thus the initial suite measures
**template-assisted Schemaxis use**. A separately labelled discovery-only arm can
omit those templates; do not combine those conditions into one reported score.

Give the ordinary agent normal native APIs, scripting, documentation and the same
installed runtimes. Give the enabled agent those tools plus Schemaxis. Keep the
model/version, reasoning setting, task budget and starting state equal. Do not
give either agent coordinator reference scripts, graders, the other arm's files,
or the undisclosed revision. Runtime configuration may be supplied to both arms
as a private file; it is not part of the public fixtures.

These exports are **directory separation, not an OS sandbox**. For a controlled
trial, use separate checkouts/containers or an equivalent runner that restricts
filesystem access. Freeze the coordinator's tasks and fixtures before starting;
never grade against a contestant-edited task or modified expected input. Preserve
transcripts and actual model usage. Unknown token/cost fields stay null.

After the initial result, request an unchanged rerun in the same agent's workspace,
then disclose the revision task and inputs. Allow both arms to reuse their own
code and artifacts. Grade all three rounds separately. Repeated independent
conversations and held-out parameter variants are needed before claiming a
success-rate or efficiency advantage. Development/debugging runs are not trials.

`benchmark_workflows.py` prepares trials and grades outputs; it does not launch a
model, collect provider billing automatically, or enforce the model's token budget.
`trial-record.json` provides explicit fields for those measurements. A host runner
or coordinator must fill them from real observations, with missing values retained.

## Running the actual RLC AI pilot

A separate Linux runner now executes both methods with an already authenticated
Claude CLI, bubblewrap, and the same configured ngspice/Calc installations:

```sh
PYTHONPATH=src python3 tools/run_rlc_ai_pilot.py \
  --config /absolute/private-runtime-config.json \
  --output-directory evidence/my-ai-rlc-pilot \
  --model YOUR_EXACT_AVAILABLE_MODEL --schemaxis-mode required

python3 tools/summarise_ai_pilot.py evidence/my-ai-rlc-pilot/report.json \
  --output evidence/my-ai-rlc-pilot/measurements.json
```

Each method has its own model conversation, home and working directory. Both get
identical cases and native runtimes. Only the enabled namespace contains Schemaxis
and initial templates. Neither namespace contains the coordinator, frozen revision,
grader or other method's workspace. The runner mounts the existing Claude credential
file for authentication; it does not copy credentials into the trial artifacts.
Network access remains available. The Linux filesystem layout in this first runner
expects `/usr` and systemd-resolved; inspect the two preflight logs before a trial.

The three turns are initial, unchanged repeat and revised cases. Each has a
300-second wall bound by default; the CLI receives the same model, `high` effort
and `--max-budget-usd 3` flag for both conversations. The runner retains transcripts,
workspace snapshots, raw usage and independent grades. Provider API errors stop
the run and are recorded as blocked rather than scored as model task failures.
Scheduled round prompts
are part of the task; corrective human hints are not supplied.

`--schemaxis-mode available` lets the agent choose whether to use Schemaxis.
`required` requires Schemaxis for simulation and workbook handoff, while allowing
ordinary scripts for authoring and inspection. Keep those conditions separate:
our first availability pilot chose direct native scripts and therefore did not
measure Schemaxis execution. Review the transcripts and generated procedure for
method compliance even when all artifact checks pass.

The summariser uses invocation `usage` for tokens and differences of cumulative
conversation costs for per-turn cost estimates. It reports provider list-price
estimates, not an invoice or actual subscription charge. Tool error counts are
observed failed tool results, not a complete count of semantic retries.

The [clean RLC comparison](../verification/2026-09-28-ai-workflow-clean-rlc.md)
passed 7/7 case checks for both methods: ordinary scripting took 198.5 seconds,
Schemaxis 217.0 seconds. It showed no efficiency advantage in this single pair.
The [historical AI pilots](../verification/2026-09-28-ai-workflow-pilots.md) retain
the optional-use and configuration-confounded results separately.
These are exploratory pairs; repeat with balanced order and new cases before
making a general efficiency claim.

## Common independent grader

The [ParaView recipe comparison](../examples/benchmarks/paraview/README.md) adds a
separate three-method pilot: native scripting from scratch, a reusable native
Python recipe and a reusable Schemaxis recipe. It exercises time/slice expansion,
point/cell association, fixed colour ranges, multiple cameras, revisions and
damaged-output recovery. Its analytic/decoded-image grader is separate from the
original family grader below. See the [preflight defect and fix](../verification/2026-09-28-paraview-render-time.md).
The [completed twelve-turn comparison](../verification/2026-09-28-paraview-ai-pilot.md)
passed 10/10 case checks with each supplied recipe and 6/10 from scratch. Schemaxis
took 6.6% longer and cost an estimated 40.8% more than the native recipe overall;
its combined follow-up turns were cheaper/faster. These are exploratory results
from one conversation per method, not a general efficiency claim.

The [onboarding comparison](../verification/2026-09-28-paraview-onboarding.md)
then completed 24 turns across both supplied recipes and three introductions:
baseline, scoped qualification brief, and brief plus bounded output checker.
All six conversations passed 10/10 case checks. The Schemaxis brief reduced observed
four-turn time by 9.1% and estimated cost by 22.9% against its baseline, while
first-turn elapsed time stayed essentially unchanged. Agents continued adding
image validators; native with the supplied checker had the lowest overall time
and cost. One Schemaxis revision includes native X-server recovery. The report
preserves that caveat and the excluded ambiguous-digest attempt.

```sh
PYTHONPATH=src python3 tools/benchmark_workflows.py grade \
  --task evidence/my-benchmark-pack/initial/ordinary/task.json \
  --submission /absolute/trials/ordinary-01/submission \
  --config /absolute/private-runtime-config.json \
  --output-directory evidence/ordinary-01-grade
```

Use the **coordinator-owned** task for either arm. Grades include a task/data
digest to check that results refer to equivalent inputs. Grading never calls
`Schemaxis.verify` or trusts a contestant's `verified` flag. It checks:

- RLC values against a closed-form transfer function at every frequency, including
  complex sign, magnitude and phase. It independently reads the actual ODS data
  sheet; an extra statistics sheet is allowed, duplicate matching data sheets are not.
- STEP and editable FreeCAD volume through native reopening, positive tetrahedral
  volumes and physical face membership/areas. A separate MSH parser checks names,
  tags, element counts, volume, boundary coverage and degenerate/inverted elements.
  A VTK reader measures the published VTU files, and the ParaView integration table
  must match the analytic box volume.
- Actual CFD VTP geometry, area, location, cell-array shape, velocity and pressure
  at each requested time. A plausible image or a successful process is insufficient.
- Table headers, every numeric value, row/column counts, and workbook contents.

Artifact grades do not prove which tool produced a file. Check native-tool usage,
workflow editability, human intervention and rule compliance from the transcript
and retained procedure as separate rubric items. Numeric correctness alone is not
an overall AI trial win. The grader is bounded scientific checking, not a hostile
file-parser security boundary or proof of every possible output property.

Run selected falsification checks on copies of a passing proof:

```sh
PYTHONPATH=src python3 tools/benchmark_challenges.py \
  --package evidence/my-benchmark-pack --proof evidence/my-benchmark-proof \
  --config /absolute/private-runtime-config.json \
  --output-directory evidence/my-benchmark-challenges
```

For each arm, these change a complex sign, physical face name, time-slice field
or workbook value, and remove a case. All ten mutations must be rejected despite
an added success claim. These challenges target the supplied example suite.

## Known Schemaxis planning limitation

Host inspection of the entire CAD → Gmsh workflow currently substitutes an
extensionless placeholder for the not-yet-produced STEP. Gmsh's correct STEP path
validation rejects it with `INVALID_RESOURCE`. Executing the workflow succeeds
because native handoff supplies the real `.step` file. Stage-by-stage planning
after the producer runs is another supported route. This limitation is explicit
in the enabled task instructions and has a regression check; validation was not
weakened to conceal it. A future shared typed-artifact planning fix needs its own
qualification.

## Existing private CFD cases

`tools/benchmark_private_cfd.py` compares ordinary ParaView and Schemaxis outputs
from an existing reconstructed or decomposed OpenFOAM/HELYX case:

```sh
PYTHONPATH=src python3 tools/benchmark_private_cfd.py \
  --case-file /absolute/private-case/case.foam \
  --case-type 'Decomposed Case' --times 500 --fractions 0.5 0.505 \
  --config /absolute/private-runtime-config.json \
  --output-directory evidence/private-cfd-comparison
```

Choose times that exist in that case. Both inputs explicitly request inclusion
of time zero. On the tested decomposed tutorial, however, Schemaxis rejects time
zero as unavailable while the direct reader exposes it; only saved time 500
currently passes this private comparison. The failed 0/500 attempt remains
recorded as a limitation, not a successful multi-time proof.
The tool inspects available times, domain bounds and fields, then compares actual
slice areas, bounds, counts and U/p tuple distributions. The two arms share the
native ParaView reader; matching results establish post-processing equivalence,
not independent validation of the original numerical solution. The check does
not certify convergence, field units, turbulence modelling or physical accuracy.

A small tutorial case with saved solution fields (not distributed) was copied
only to ignored local evidence. No colleague/customer case contents, account
details or private paths belong in these public templates. Case redistribution
permission remains separate from local testing. No remote job,
compilation, reconstruction or solver run is part of this proof.

## Smaller-model ParaView comparison

The [2026-09-29 model comparison](../verification/2026-09-29-smaller-model-results.md)
uses actual isolated Claude and Codex conversations. It separates operation of
qualified recipes from authoring through public interfaces, and compares native
ParaView with Schemaxis using the same tasks and independent artifact grader.
The [frozen protocol](../verification/2026-09-29-smaller-model-protocol.md) records
model IDs, trust instructions, replication, budgets and exclusions. The
[transcript index](../verification/2026-09-29-smaller-model-transcripts.md) links
public assistant messages and tool I/O, including excluded attempts.

All 88 prepared-recipe turns passed, including the smaller-model native controls.
Authoring results must also be read alongside the procedure and instruction
audit: correct artifacts alone do not establish reliable reuse, complete evidence
retention or adherence to the trust instruction. Costs are API list-price
estimates, not subscription charges. These are synthetic serial ParaView tasks,
not general model-equivalence or production-CFD claims.
