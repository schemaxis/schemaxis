# ParaView recipe onboarding comparison

This follows the [first ParaView comparison](2026-09-28-paraview-ai-pilot.md).
The question is whether a concise operating introduction with evidence, followed
by supplied output checking, reduces initial agent work without losing correctness.

## Results

All 24 model invocations completed. Every conversation passed all 10 case checks
and 220 artifact checks: 60/60 and 1,320/1,320 across the trial. No provider errors,
timeouts, permission denials or human corrections occurred in the scored run.
The supplied seeds and public checkers remained unchanged. Native agents wrote
derivative procedures; Schemaxis agents used the supplied framework recipe.

| Method | Introduction | Initial seconds | Initial USD | Four-turn seconds | Four-turn USD |
| --- | --- | ---: | ---: | ---: | ---: |
| native | baseline | 125.034 | 0.381830 | 281.968 | 0.939263 |
| schemaxis | baseline | 152.704 | 0.681806 | 353.100 | 1.382511 |
| native | brief | 164.644 | 0.522248 | 351.012 | 1.089393 |
| schemaxis | brief | 152.103 | 0.464282 | 320.808 | 1.065323 |
| native | checked | 135.792 | 0.466029 | 242.355 | 0.780484 |
| schemaxis | checked | 163.697 | 0.604383 | 337.871 | 1.243590 |

USD figures are provider list-price estimates, not subscription charges.

| Method / introduction | Initial s | Repeat s | Revision s | Repair s | Total output tokens | Total input tokens, including cache |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native-baseline | 125.034 | 51.837 | 56.012 | 49.086 | 20,526 | 915,033 |
| schemaxis-baseline | 152.704 | 63.624 | 62.717 | 74.056 | 21,853 | 1,738,877 |
| native-brief | 164.644 | 40.111 | 77.767 | 68.491 | 23,516 | 951,561 |
| schemaxis-brief | 152.103 | 31.691 | 63.021 | 73.993 | 21,126 | 1,147,441 |
| native-checked | 135.792 | 23.827 | 37.955 | 44.781 | 17,524 | 686,606 |
| schemaxis-checked | 163.697 | 20.719 | 95.293 | 58.162 | 23,102 | 1,494,664 |

Cached input totals count repeated reads, not unique prompt size. Different token
categories have different prices; output-token counts alone do not explain cost.

### Interpretation

The qualified introduction did not reduce Schemaxis first-turn elapsed time:
152.103 seconds versus 152.704 for baseline. It reduced that turn's estimated
cost by 31.9%, with input tokens including cache falling from 582,812 to 341,656.
Output tokens barely changed (10,650 baseline; 10,699 brief). The brief avoided
some context consumption, but the agent still authored substantial validation.

Across all four turns, Schemaxis brief used 9.1% less time and 22.9% less estimated
cost than Schemaxis baseline. Total input tokens including cache fell 34.0%;
output tokens fell 3.3%. This is the measured improvement in this sequence,
not a statistically established treatment effect.

Adding the partial checker did not improve Schemaxis initial time: it took
163.697 seconds and $0.604383. It helped unchanged reuse and repair, but the
agent still created pixel probes for properties the checker does not cover.
Its four-turn figures are also affected by the display recovery described below.

The matched brief pair favoured Schemaxis by 8.6% in total time and 2.2% in
estimated cost. However, native checked had the lowest complete-workflow time
and cost of all six conversations. Against that matched checked control,
Schemaxis checked took 39.4% longer and cost 59.3% more, including its display
recovery. These results do not establish a general framework advantage.

### Behaviour and failure audit

- Qualification hashes matched in the corrected brief/checked trial. The
  earlier ambiguous-hash attempt is excluded and retained separately below.
- Schemaxis brief ran the recipe without the baseline's broad source audit,
  then built a separate native reference renderer. That validator first used
  an unattached colour map and then had a first-render camera mismatch.
  The agent fixed its validator; the supplied recipe did not need changes.
- Both checked methods supplemented the public checker with custom pixel
  checks. Schemaxis checked also inspected renderer implementation. Their
  explicit remaining uncertainty concerned camera, colour mapping and time.
- Both checked methods reused unchanged publications after baseline/hash
  and additional checks. Baseline Schemaxis instead wrote a receipt-hash
  checker, revalidated, regenerated and compared outputs, taking more work.
- Native baseline's validator missed the substituted image during repair;
  a comparison with a fresh render found it. Schemaxis brief noticed its
  validator skipped a slice's images when its VTP was missing, supplemented
  it with retained native-output comparisons, and regenerated all outputs.
- Both supplied-checker methods identified the wrong image by saved hashes
  despite its plausible dimensions/content. Schemaxis checked regenerated
  field-a and field-b and retained field-c. Native checked regenerated all
  into a staging folder. Both compared final bytes with the pre-damage manifest.
- Schemaxis checked hit `bad X server connection. DISPLAY=:99` during the
  revised field-c render. The same recipe succeeded on a one-case retry.
  Cause is unconfirmed; raw timing/cost includes diagnosis and recovery.
  No guessed correction was subtracted. This same class of display failure
  previously affected ordinary scripting, so this is not established as a
  framework-specific defect. No initial turn had this observed failure.
- Tool-error counters omit some native failures hidden by shell pipelines.
  The two reported tool errors were a failed baseline image self-check and
  a no-op edit request, not a complete inventory of unsuccessful commands.

### What to improve next

A concise introduction with checkable identity and bounded qualification is
useful, but reassurance did not remove the first-turn engineering work here.
The next implementation target is a complete operating procedure for a named
task: run, inspect, validate the promised properties, and report unsupported
properties explicitly. That should reduce custom validator authoring without
suppressing warranted investigation or treating hashes as semantic proof.
The receipt-hash/publication checks should be reusable through the normal
interface rather than rebuilt by each agent. These benchmark additions do
not yet provide a general product onboarding service.

Keep the native-recipe control, measure independent fresh conversations, and
resolve or separately characterise the intermittent display connection issue
before drawing stronger timing conclusions. These results do not justify
model-specific training as the next step.

## Frozen protocol

Tested replacement source: `903b329`, following initial harness `0d128cd` and its
digest-presentation correction. No product runtime or recipe execution changes were made
for this comparison. The new files are a benchmark coordinator, a bounded public
checker, operating guidance and focused tests. Both native and Schemaxis recipes
are the same procedures used in the preceding comparison.

Six fresh conversations cross two recipe methods with three introductions:

- `baseline`: the previous recipe instructions, with preflight results withheld.
- `brief`: exact invocation, supported inputs, routine operating guidance and
  qualification evidence from an actual independently graded namespace preflight.
- `checked`: the same introduction plus a supplied output checker and saved
  task/input/publication hashes for detecting changes during reuse and repair.

Every conversation performs initial, unchanged-repeat, revision and repair turns.
All six receive identical task/input bytes for a given round. Cases have fresh
dimensions, offsets, slice positions and colour ranges; the task structure remains
two initial cases (40 publications) and three revised cases (70 publications).
The initial/repeat/revision/repair sequence yields 10 case checks and 220 artifact
checks per conversation. These counts are not independent statistical trials.

The method order within each introduction is balanced over four rounds, and the
declared six-method order reverses/rotates. There is one conversation per cell;
this is neither independent replication nor a fully counterbalanced experiment.
Initial introduction order is baseline, brief, then checked; between-introduction
differences therefore also retain an order/time confound.
The baseline conversations are fresh controls in this trial, rather than timings
borrowed from the earlier run.

Claude settings remain `claude-opus-5-5`, high effort, 600 seconds per invocation
and CLI `--max-budget-usd 6`. Separate homes, workspaces and process namespaces use
the same ParaView runtime, private Xvfb and Mesa software rendering. Only the
Schemaxis methods receive product source/docs. The native recipes receive equivalent
introduction/checker treatment. No human corrections or hidden-grader feedback are
provided. All model prompts, supplied introductions and workspaces are retained.

## What the supplied evidence means

Before model timing, each exact recipe runs in its actual namespace on initial
inputs. The coordinator independently checks its geometry and decoded images,
then removes the outputs from the contestant workspace. Brief/checked methods
receive a small statement with task/input, recipe, source and native executable
digests and observed native version. Baseline methods receive the same preflight
but no statement. Future revised-task references and the grader remain hidden.
Qualification is local evidence for the initial task, not a signature or a general
promise that arbitrary revisions will work.
This exact-input preflight is stronger than a library release's fixture-based
qualification and has a real compute cost. Any measured saving applies to assisted
execution of a prepared procedure; it is not evidence of free correctness or
general problem-solving gains. The revised inputs are not covered by the initial
qualification statement.

The public checker uses VTK inside pvbatch to read actual publications. Geometry
checks cover plane, bounds, area and every point/cell scalar against the analytic
fixture. Image checks cover decoded dimensions/components and nonblank surface
and background content. Optional baseline checking also compares task, input and
publication hashes. Failed checks cannot overwrite a saved good manifest.

The checker explicitly does not establish image camera, colour mapping or image
time correctness. An initial wrong-camera image can pass this limited check;
substitution after recording a correct baseline is rejected by hash mismatch.
The hidden grader still checks all those image properties. This is a portable
checker for these analytic examples, not a general scientific image verifier or
a new product-wide recipe API.

Model wall time includes reading, execution, self-checks and responses. Coordinator
preflight and hidden grading are excluded and preflight times are retained
separately (39.350 seconds for the six-namespace preparation in the scored run).
Costs use per-invocation usage and differences of resumed-session
cumulative list-price estimates; they are not subscription billing. Recipe/checker
development and qualification costs are not amortised into those model figures.

## Preparation and verification

- Seven focused host tests passed, including refusing failed qualification claims,
  rejecting changed task/input/publication baselines and balancing method order.
- Fresh native initial/revised proof passed all 110 artifact checks.
- The unchanged hidden grader rejected all eight deliberate corruptions: wrong
  time, plane, association, camera, image time, colour range, missing image and case.
- Public checker native acceptance passed good and unchanged outputs; all eight
  corrupted batches were rejected against a saved baseline, without overwriting it.
  A wrong-camera image without a baseline passed within its declared limited scope.
- No full host regression was rerun for these benchmark-only additions. The
  preceding product-change regression remains 786 passed and 22 skipped.

## Reproduction and retained evidence

See the [recipe commands and scope](../examples/benchmarks/paraview/README.md).

- `evidence/paraview-onboarding-package/`: fresh frozen tasks, inputs and references.
- `evidence/paraview-onboarding-proof/`: deterministic native Schemaxis proof.
- `evidence/paraview-onboarding-challenges/`: eight rejected hidden-grader mutations.
- `evidence/paraview-onboarding-checker/`: actual public checker acceptance and limits.
- `evidence/ai-paraview-onboarding-01/`: excluded attempt: ambiguous task digest
  presentation caused the brief recipient to infer stale qualification. Three
  completed initial turns and a fourth interrupted turn are retained, not used
  in onboarding performance conclusions. The canonical JSON digest differed from
  raw file SHA256 even though the task was identical. The correction supplies
  an explicitly named raw-file hash, canonical hash and algorithms for each digest.
  The three completed diagnostic turns total $1.280256 in estimated usage cost;
  the interrupted fourth turn has no complete usage result. Those costs are
  outside the replacement trial's tables, not claimed as savings.
- `evidence/ai-paraview-onboarding-02/`: frozen source, per-method preflight,
  exact prompts/introductions, transcripts, snapshots, grades, measurements and
  `adjudication.json` with the completed audit and explicit caveats.

These synthetic fixtures test state handling and publication contracts. They do
not establish large CFD, MPI, HPC, arbitrary native-version compatibility or a
general model ranking. No model training, installs or cluster work were performed.
