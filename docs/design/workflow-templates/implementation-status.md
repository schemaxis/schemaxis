# Workflow foundation milestone

2026-10-03. Milestone record following approval of the architecture.

## Delivered first subset

| Area | Delivered scope |
| --- | --- |
| Template binding | Strict `load_template`, atomic `bind_values`, shared `prepare_template`; captured manifest/body identity, defaults, constraints, source map and output-alias shape checks |
| Resource capture | Bounded file/file-set/directory copying into exclusive snapshots, canonical constituent hashes and independent verification |
| Artifact handoff planning | Explicit deferred artifact/value planning; resolved input/resource validation before consumer dispatch; full-operation checks for time batches |
| Integration | Shared CLI/service/JSON-lines preparation, cross-entry-point tests, documentation corrections, whole-Chapter-2/STSC design extension and integration review |

Exact first-subset contracts are [template-contract.md](template-contract.md) and
[resource-contract.md](resource-contract.md). The broader architecture remains a
roadmap. Resource capture is a Python foundation; it is not yet wired into template
parameters or workflow execution.

The CLI now provides `template inspect`, `template bind` and `template plan`.
The service provides `prepare_template`. Both use the same binder and emit an
ordinary workflow plus provenance. `bind --document-only` emits only the workflow.
All are host-only. See [example commands](examples/README.md).

## Review and verification

Focused tests cover binding parity for both cases, defaults, stale identity and
digest rejection, malformed values, atomic failures, path confinement, resource
changes and incomplete publication, deferred STEP inputs and resolved preflight
failures. A separate review covered resource capture; directory durability, path
aliasing and malformed-depth handling were corrected before milestone acceptance.

The original `design-checks.json` remains unchanged as review-baseline evidence.
New integration results are recorded separately in the milestone verification
record at [verification/2026-10-03-workflow-foundation.json](../../../verification/2026-10-03-workflow-foundation.json).
The full suite ran 966 tests successfully (22 skipped); the final focused resource
suite ran 30 tests successfully. The initial broader run caught resource-default
and stale-reference regressions, which were corrected and rechecked before commit.
No native template acceptance or numerical coupling qualification is
claimed by these host checks.

## Workflow designer milestone

The subsequent milestone prioritised flowchart authoring and activating a
feedback selector when a closed loop appears. The console now has a separate
`schemaxis.workflow-design/1` authoring document: data arrows overlay a captured
ordinary workflow, runtime dependency cycles form explicit groups, and settings
belong to each exact group. Humans and agents share source, revisions, undo and
saved configuration. See [the designer guide](../../workflow-design.md).

Fixed point and constant relaxation can be configured. Settings do not enable
native coupled execution: a cyclic design is rejected before task or job mutation.
Other numerical methods display their implementation/participant requirements.
Acyclic designs compile into separately retained ordinary workflow drafts, using
the existing host planner and executor contracts. This is a delivered part of D2,
not completion of the numerical controller roadmap.

The complete host suite ran 1,003 tests with no failures (22 skipped). Browser
checks cover mouse and keyboard arrows, cycle-triggered focus, saved settings,
scroll retention and stale replies. A separate production UI/service check
verified reload persistence, blocked cyclic compilation and successful acyclic
compilation. The [designer verification record](../../../verification/2026-10-03-workflow-designer.json)
separates these checks from unavailable native numerical execution.

## Remaining acceptance and next milestone

This completes a foundation slice of D0/D1, not all of D1. Remaining D1 work:
captured run provenance tied automatically to the template/case; native resolution
and validation of named outputs; resource binding/staging integration; and two-case
native acceptance. Rich metadata schemas and GUI parameter forms remain D2.

Next connect the design to template packaging, parameter forms and captured
case/run ownership in the shared service. Use the existing capability search and
shared authoring contract. Keep result snapshots separate from editable case values.
Selections/view controls, native CFD qualification and installation milestones
retain the ordering in [delivery-plan.md](delivery-plan.md).

Live numerical coupling follows its own participant/checkpoint qualification
sequence in [numerical-coupling.md](numerical-coupling.md). No current adaptor has
been newly certified for step doubling, derivative callbacks or STSC by this work.
