# Agent transcript index

Generated 2026-09-29 from retained Claude CLI logs. These are local transcripts of the benchmark agents.

Each readable transcript contains the exact invocation prompt, public assistant messages, tool calls/results and final reply. Tool payloads use expandable sections. Supplied task files, frozen workspaces and raw JSONL are linked. Binary image payloads are represented by a note; the corresponding image remains in the workspace. Internal reasoning and transport metadata are not included in the readable view.

The raw logs and generated readable transcripts stay in ignored local evidence. The links work in this checkout; copying only this repository will not copy the evidence.

Suggested reading: the scored Schemaxis baseline, brief and checked initial turns; then the native checked control and both checked repair turns. The excluded brief shows how the ambiguous digest caused unnecessary work.

## Completed onboarding comparison

[Report](../evidence/ai-paraview-onboarding-02/report.json) · [Adjudication](../evidence/ai-paraview-onboarding-02/adjudication.json)

| Conversation | Initial | Repeat | Revision | Repair |
| --- | --- | --- | --- | --- |
| native-baseline | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-baseline/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-baseline/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-baseline/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-baseline/repair.md) |
| native-brief | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-brief/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-brief/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-brief/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-brief/repair.md) |
| native-checked | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-checked/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-checked/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-checked/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/native-checked/repair.md) |
| schemaxis-baseline | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-baseline/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-baseline/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-baseline/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-baseline/repair.md) |
| schemaxis-brief | [Re>ad](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-brief/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-brief/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-brief/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-brief/repair.md) |
| schemaxis-checked | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-checked/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-checked/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-checked/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-02/schemaxis-checked/repair.md) |

## Earlier three-method comparison

[Report](../evidence/ai-paraview-recipes-02/report.json) · [Adjudication](../evidence/ai-paraview-recipes-02/adjudication.json)

| Conversation | Initial | Repeat | Revision | Repair |
| --- | --- | --- | --- | --- |
| ordinary | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary/repair.md) |
| ordinary-template | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary-template/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary-template/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary-template/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/ordinary-template/repair.md) |
| schemaxis | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/schemaxis/initial.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/schemaxis/repeat.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/schemaxis/revision.md) | [Read](../evidence/readable-agent-transcripts/ai-paraview-recipes-02/schemaxis/repair.md) |

## Excluded ambiguous-digest attempt

[Report](../evidence/ai-paraview-onboarding-01/report.json) · [Adjudication](../evidence/ai-paraview-onboarding-01/adjudication.json)

**Excluded in full.** Three initial turns completed; the fourth was interrupted. Its raw report still says `running` because the coordinator was stopped. The adjudication is authoritative: this attempt is not active and must not be scored or resumed.

| Conversation | Initial | Repeat | Revision | Repair |
| --- | --- | --- | --- | --- |
| native-baseline | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-01/native-baseline/initial.md) | — | — | — |
| native-brief | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-01/native-brief/initial.md) | — | — | — |
| schemaxis-baseline | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-01/schemaxis-baseline/initial.md) | — | — | — |
| schemaxis-brief | [Read](../evidence/readable-agent-transcripts/ai-paraview-onboarding-01/schemaxis-brief/initial.md) | — | — | — |

## Useful companion evidence

- [Onboarding results](2026-09-28-paraview-onboarding.md)
- [Earlier ParaView results](2026-09-28-paraview-ai-pilot.md)
- [Render-time defect and fix](2026-09-28-paraview-render-time.md)

Raw files are preserved; readable files are derived views and do not replace the recorded grades or adjudications.
