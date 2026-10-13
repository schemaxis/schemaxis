# Smaller models, trusted recipes and workflow authoring

Completed 2026-09-29. Protocol: [frozen comparison design](2026-09-29-smaller-model-protocol.md).
[Readable agent transcripts](2026-09-29-smaller-model-transcripts.md) · [Machine-readable aggregate](../evidence/model-comparison-results.json).

**Main finding:** in this synthetic ParaView authoring task, Luna with Schemaxis matched Astra native’s complete artifact grade at about 91% lower estimated API cost, with 61% more elapsed time. All three smaller models passed both authoring rounds with Schemaxis and failed both native rounds. Procedure reliability and instruction compliance still differed.

## What this establishes

Cheaper models successfully operated the supplied Schemaxis recipes: all 88 prepared-recipe turns passed, covering 4,840 artifact checks. They also succeeded with native recipes. This supports delegating these qualified procedures to smaller models, but does not show that Schemaxis was necessary to achieve that prepared-task success.

Across the three Claude conversations per cell, Haiku with Schemaxis had median cost USD 0.1701 versus Opus native's USD 0.3886 (56.2% less), with similar elapsed time, 129.0 versus 127.5 seconds. In the single OpenAI comparison, Luna with Schemaxis cost USD 0.02774 versus Astra native's USD 0.89670 (96.9% less), but took 199.7 versus 141.5 seconds. These are complete four-turn totals and estimated API prices. The native smaller-model controls were also successful and generally faster than their Schemaxis counterparts.

The authoring comparison tests a different question: can a model construct the workflow through public interfaces without the full solution? Interpret its initial and revision results separately from prepared operation. Each authoring cell has one conversation; artifacts and turns are not independent model-level replicates.

The completed Claude authoring conversations show a cost/latency tradeoff: Opus with Schemaxis passed both turns in 227.8 s for USD 1.1867; Haiku passed in 827.6 s for USD 0.9423; Sonnet passed in 757.2 s for USD 2.4923. Lower token prices did not guarantee lower task cost. Opus also delivered a clearer rerun path and retained evidence. The unavailable Opus-native control prevents a clean Claude frontier-native authoring comparison.

The OpenAI authoring pair answers the main question directly within this task: Luna with Schemaxis and Astra native both passed all 110 artifact checks across two turns. Luna with Schemaxis cost USD 0.08146432 versus Astra native’s USD 0.882752 (90.8% less), taking 284.6 versus 177.2 seconds (60.6% longer). Both reused their parameter-driven procedures on revision and retained logs. This is one conversation per cell; it establishes this observed task result, not general capability equivalence.


## Prepared recipes: replicated Claude comparison

Each row represents three independent four-round conversations: initial, unchanged reuse, revision and repair. Times and costs are medians, with the full range in parentheses.

| Model | Method | Complete artifact passes | Seconds | Estimated USD |
| --- | --- | ---: | ---: | ---: |
| Haiku 4.5 | native | 3/3 | 79.1 (76.0–85.0) | 0.1025 (0.0909–0.1123) |
| Haiku 4.5 | schemaxis | 3/3 | 129.0 (126.2–195.9) | 0.1701 (0.1584–0.3096) |
| Sonnet 4.6 | native | 3/3 | 81.6 (76.1–105.6) | 0.2195 (0.2038–0.2780) |
| Sonnet 4.6 | schemaxis | 3/3 | 111.7 (93.9–153.1) | 0.2028 (0.1847–0.3395) |
| Opus 5.5 | native | 3/3 | 127.5 (125.2–131.8) | 0.3886 (0.3570–0.4207) |
| Opus 5.5 | schemaxis | 3/3 | 150.7 (140.8–162.5) | 0.4011 (0.3908–0.4289) |

## Prepared recipes: exploratory OpenAI follow-up

One fresh four-round conversation per row; these cells are not independently replicated. Compare within the provider because CLI tools and system prompts differ.

| Model | Method | Complete artifact passes | Seconds | Estimated USD |
| --- | --- | ---: | ---: | ---: |
| GPT-5.6 Luna | native | 1/1 | 148.6 | 0.0250 |
| GPT-5.6 Luna | schemaxis | 1/1 | 199.7 | 0.0277 |
| GPT-6 Astra | native | 1/1 | 141.5 | 0.8967 |
| GPT-6 Astra | schemaxis | 1/1 | 148.2 | 0.8730 |

## Authoring without a complete recipe

One fresh conversation per row, with initial and revision turns. Agents received the task contract, public interfaces/documentation and bounded checker, but no complete recipe or prior conversation. A later success does not erase an initial failure.

| Model | Method | Initial | Revision | Artifact checks passed | Seconds | Estimated USD |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Haiku 4.5 | native | fail | fail | 22/110 | 629.2 | 1.0234 |
| Haiku 4.5 | schemaxis | pass | pass | 110/110 | 827.6 | 0.9423 |
| Sonnet 4.6 | native | fail | fail | 22/110 | 353.3 | 0.8123 |
| Sonnet 4.6 | schemaxis | pass | pass | 110/110 | 757.2 | 2.4923 |
| Opus 5.5 | native | unavailable | not run | — | — | — |
| Opus 5.5 | schemaxis | pass | pass | 110/110 | 227.8 | 1.1867 |
| GPT-5.6 Luna | native | fail | fail | 68/110 | 268.1 | 0.0471 |
| GPT-5.6 Luna | schemaxis | pass | pass | 110/110 | 284.6 | 0.0815 |
| GPT-6 Astra | native | pass | pass | 110/110 | 177.2 | 0.8828 |
| GPT-6 Astra | schemaxis | pass | pass | 110/110 | 305.0 | 2.4853 |

## Trust, correctness and procedure quality

The instruction explicitly tells agents to trust approved libraries, avoid routine implementation audits or replacement validators, and use the supplied bounded checker. It still permits diagnosis after execution/check failures. Across the 88 prepared turns, supplied recipe/checker bytes were unchanged, and the workspace/transcript audit found no replacement reference renderer or custom validator. Some agents added receipt/hash checks or image inspection. Final replies did not consistently state the checker's limits.

The distinction matters during authoring. Haiku native's initial supplied-checker result passed, but hidden grading rejected all 32 images; only its eight geometry/field artifacts passed. A representative image shows a substantially smaller surface than the reference, consistent with a camera/scale error. Its final reply nevertheless claimed correct cameras and a “production-ready” procedure. Haiku with Schemaxis passed all 40 initial artifacts, but also omitted the checker's image-semantic limits and left Schemaxis run receipts/native logs under ephemeral `/tmp`. Correct artifacts do not prove good evidence retention or honest verification reporting.

Sonnet’s initial Schemaxis submission also passed all 40 artifacts, and its final reply accurately described checker limits. Its final procedure used Schemaxis for every submitted artifact and retained run logs. However, it first performed three direct native inspections, including a slice probe. That deviates from the literal “all slicing through Schemaxis” instruction; it is an artifact success with an instruction-compliance caveat, not evidence of perfect adherence to the trust policy.

Sonnet’s Schemaxis revision produced all 70 correct artifacts via direct CLI execution and helper calls, but left its wrapper broken. It introduced an edit removing `DISPLAY`, observed a native X-connection error with empty `DISPLAY`, and ultimately disclosed that the wrapper still failed. Its proposed piping/X explanation is not an established cause. Thus artifact success is not a claim of a robust one-command reusable procedure. This authoring failure/recovery is separate from the four prepared-recipe display failures discussed separately.

Haiku’s Schemaxis revision also passed all 70 artifacts, after a targeted helper regenerated four PNGs missing from its first run. Its main parameter-driven script stayed unchanged, but this was not a recovery-free rerun. The retained evidence does not establish the cause of those misses. Both smaller native revisions still passed only the 14 geometry/field artifacts and failed all 56 images; both revision replies accurately stated the checker’s semantic limits.

Luna’s initial Schemaxis procedure passed all 40 artifacts and retained native logs/receipts. It also searched implementation files for camera/background/schema properties during discovery. Its result therefore does not establish strictly black-box use or complete adherence to the no-internals instruction. The published procedure uses Schemaxis for all slicing/rendering.

No hidden-grader feedback or manual code correction was supplied to the contestants. Ordinary authoring failures remain scored; later revisions do not erase them. Automated audit flags are candidates for manual review, not instruction-violation counts. [Audit notes](../evidence/model-comparison-audit-notes.json) and [candidate evidence](../evidence/model-comparison-audit-candidates.json) retain those distinctions.

## Display failures, exclusions and unavailable control

Four failed prepared-recipe attempts reported `bad X server connection. DISPLAY=:99`: two during Haiku Schemaxis revision in replicate 2, one during its replicate-3 revision, and one during Sonnet Schemaxis repair in replicate 3. All recovered and passed, with recovery included in time/cost. The twelve standalone probes had passed. The cause remains unconfirmed, and earlier native scripting also exhibited this class of failure; this experiment does not establish a framework-specific cause or a fix.

The first OpenAI attempt, `ai-paraview-openai-01`, is excluded in full because the namespace omitted Codex's companion command-tool executable. Its three completed calls cost an estimated USD 0.0777122; an interrupted fourth had no final usage total. Those are infrastructure records, not model-capability failures. After fixing the read-only executable mount, fresh Luna/Astra probes rendered real images, and the complete replacement used fresh conversations. [Infrastructure adjudication](../evidence/ai-paraview-openai-01/adjudication.json).

The requested Opus 5.5 native-authoring control is unavailable. Claude Code recorded a provider `model_refusal_fallback` event, classified the request as `cyber`, and substituted Opus 4.8. The identity gate excluded that attempt before its diagnostic grade was obtained; no retry or prompt change attempted to force the unavailable control. The off-protocol run took 222.571 seconds, cost USD 0.8602363, and diagnostically passed 39/40 artifacts while its supplied checker passed. It is neither an Opus 5.5 result nor a planned Opus 4.8 comparison. [Substitution adjudication](../evidence/ai-paraview-authoring-claude-01/adjudication.json). Opus 5.5's Schemaxis authoring identity was verified normally.

## Image-grading tolerance limitation

Luna’s initial native result exposes a limit even in the hidden grader: all 16 later-time PNGs were byte-identical to the corresponding time-zero images. Its code advanced reader/filter time but did not set the view time. Fourteen of these images exceeded the comparison tolerance and failed; two passed the pixel thresholds despite this repeated-image defect. Artifact-pass counts therefore mean passes under the stated analytic/pixel checks, not a guarantee that every possible semantic error is detectable. The public checker accepted all 40 files.

## A visible example of the silent image failures

These are the same first initial-task image (`field-a`, time index 0, slice index 0, appearance 0, camera 0). The requested appearance is Grayscale. Hidden grading checks all requested images, not just these examples.

| Independent reference | Haiku native | Sonnet native | Haiku with Schemaxis |
| --- | --- | --- | --- |
| ![Reference](../evidence/paraview-model-package-03/initial/reference/field-a/slice-0-0-appearance-0-camera-0.png) | ![Haiku native](../evidence/ai-paraview-authoring-claude-02/haiku-native/initial/workspace/submission/field-a/slice-0-0-appearance-0-camera-0.png) | ![Sonnet native](../evidence/ai-paraview-authoring-claude-02/sonnet-native/initial/workspace/submission/field-a/slice-0-0-appearance-0-camera-0.png) | ![Haiku Schemaxis](../evidence/ai-paraview-authoring-claude-02/haiku-schemaxis/initial/workspace/submission/field-a/slice-0-0-appearance-0-camera-0.png) |

## Evidence and limits

The tabulated correctness outcome is independent artifact grading under the stated tolerances, not an agent self-report. The grader reads geometry/fields and decoded images, including camera, colour and time. Method compliance and verification claims require the separate transcript audit. The public checker only covers analytic geometry/fields, image structure/nonblank content and optional saved hashes.

Claude costs use differences of resumed-session list-price totals, cross-checked against token/cache categories. Codex token totals are also cumulative: the transport subtracts previous totals before recording per-turn usage. OpenAI estimates use ordinary input, cached input, cache writes and output separately. These figures are API list-price estimates, not subscription charges. [Frozen rates and official source links](../evidence/model-pricing-2026-09-29.json).

Agent wall time includes reading, execution, checking, responses and recovery. Exact-initial-input qualification, fixture/reference generation, grading, recipe/checker development and coordinator work are outside those figures. Preparation is retained separately in each report. The prepared-recipe qualification is stronger than general release-fixture qualification; it is not free correctness.

Three Claude replicates and one OpenAI/authoring conversation per cell do not establish statistical equivalence or a general model ranking. Shared provider prompt caches remain possible despite fresh sessions. Requested high effort is not equal compute across different models. These small synthetic serial ParaView cases do not establish large/private CFD, MPI or arbitrary-version behaviour.

The explicit trust instruction was applied equally to native and Schemaxis dependencies. Historical onboarding results are context, not a randomised no-trust control, so a causal trust-prompt speedup is not established.

## Reproduction and verification

The runner is [run_paraview_model_pilot.py](../tools/run_paraview_model_pilot.py), with [Codex transport/accounting](../tools/model_pilot_codex.py), [aggregation](../tools/summarise_model_pilots.py) and [transcript export](../tools/export_model_pilot_transcripts.py). Each experiment retains its actual harness snapshot, source/recipe/checker/runtime digests, commands, prompts, raw logs, qualifications, workspace snapshots and grades. Bulk evidence stays ignored.

Fifteen focused host tests passed using `PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_paraview_benchmark.py`. Fresh Schemaxis native proof passed all 110 publications, and the unchanged hidden grader rejected all eight corruption challenges. Twelve isolated native/Schemaxis rendering probes passed, but subsequent model runs reproduced the intermittent display failure; no fix is claimed. Product runtime was unchanged; no fresh full-suite regression is claimed.

The display probe measured median recipe execution of 1.68 s native versus 6.09 s Schemaxis on initial inputs, and 2.00 s versus 9.20 s on revisions. This excludes agent work. [Probe report](../evidence/paraview-model-display-probe/report.json).

- [ai-paraview-models-01 report](../evidence/ai-paraview-models-01/report.json): 24 turns; complete.
- [ai-paraview-models-02 report](../evidence/ai-paraview-models-02/report.json): 24 turns; complete.
- [ai-paraview-models-03 report](../evidence/ai-paraview-models-03/report.json): 24 turns; complete.
- [ai-paraview-openai-02 report](../evidence/ai-paraview-openai-02/report.json): 16 turns; complete.
- [ai-paraview-authoring-claude-02 report](../evidence/ai-paraview-authoring-claude-02/report.json): 10 turns; complete.
- [ai-paraview-authoring-codex-01 report](../evidence/ai-paraview-authoring-codex-01/report.json): 8 turns; complete.

Final integrity audit confirmed 106 scored turns across 31 conversations, with 106 readable transcripts and 950 tool calls accounted for. Product/checker hashes and requested model identities matched; no contestant timed out or received human corrections. The scored calls total USD 16.5350 at the frozen API list rates, excluding coordinator work, access probes and excluded attempts. [Integrity record](../evidence/model-comparison-final-integrity.json) · [Totals](../evidence/model-comparison-final-totals.json).

Whole experiments adjudicated as excluded are also rejected by the aggregation tool, including older reports without per-invocation eligibility flags. This reporting safeguard has a regression test. All model dispatch has finished.
