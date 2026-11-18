# Adaptor element authoring audit and implementation task

Copyright (C) 2026 David L. F. Gaden.

Implement meaningful instance naming, editable existing Names and suitable element multi-mode for the
specified adaptor scope, following `docs/design/element-multi-mode.md`.

For a sequential rollout across every adaptor, use
[the Sol coordinator prompt](adaptor-authoring-coordinator.md); this document is
the detailed per-slice worker brief.

Inputs to this task: adaptor ID(s), route/version scope, requested native
qualification environment and any explicit exclusions. Read repository and nested
instructions first. Preserve existing uncommitted work and current ownership and
licence notices. Keep private machine configuration and working notes out of
tracked files. Do not commit or push unless requested.

## Begin with evidence and a complete inventory

Inspect discovery, declarations, literal schemas, conceptual guidance and current
Studio controls. Enumerate **every** operation in scope, including generated native
operations and route-specific document items. Reconcile inventory counts against
the registered catalogue. Produce a reviewable table with operation, route,
source evidence, suitability classification, rationale, proposed shared/per-row
fields, naming candidates and required native checks. Distinguish conditional,
unsuitable and not-yet-investigated; absence of an existing GUI control is not
proof that an application cannot support a feature.

Use the rubric's independent-sibling, collection, stateful, singleton and
side-effect distinctions. Never turn a list into sibling elements without explicit
user action and evidence that each sibling has independent meaning. Identify
output destination collisions and reference/ownership hazards before coding.
Assess useful naming on every node, including nodes unsuitable for multi-mode.
Record one ordered set of distinguishing settings per operation or family.
Use it for Name suggestions and compact rows, inheriting the remaining settings
from the starting instance. Record any deviations and their rationale.
Saved node Names stay fixed in Studio Settings and multi-mode. Preserve existing
scoped checked rename support.

Audit subset selection independently for every node and field across readers,
sources, filters, outputs and sinks. Wherever users choose from a superset of
available values, apply the extractBlock reference controls carefully: Select
All/Deselect All; filtering with Select shown/Deselect shown; toggleable names;
Shift-click ranges; Ctrl/Cmd-click toggles; and mouse box selection with
Ctrl/Cmd-drag to toggle. Consider per-section Select/Deselect or +/− controls
when meaningful groups are declared. Record choice provenance/completeness,
ordering, empty/default/All meanings, patterns, exclusions, full-path ambiguity
and stale input handling. Preserve unshown and manually entered selections;
explain snapshots of loaded choices. Cover single-instance, multi-mode quick
settings and Batch actions where applicable. Do not claim rollout from the
reference implementation alone.

## Implement within the common contract

Use adaptor-owned authoring policies and the shared catalogue/UI implementation.
Preserve operation explanations, units, defaults and pitfalls. Add no
adaptor-name branch in shared core. If the current one-option `exact-list` mode
cannot express the required semantics, propose a bounded general extension with
validation and tests; do not misuse an unrelated policy or silently broaden scope.

Expose the same Multi-mode action and row controls as the reference extractBlock
implementation: completed instances show Name and selected groups compactly,
the header itself is a keyboard-accessible expand/collapse button, and quick
Name/selection edits update the summary live without Apply/Done. Open an empty
starter expanded and retain loaded choices for its input. Provide Add instance,
confirmed Delete, transactional Properties, and secondary Batch actions. Show
available chips directly in quick settings, with exact entries/patterns in a
separate disclosure. Show batch-selection checkboxes only while Batch actions is
open, preserving their checked state when hidden.
Sort offered names naturally without reordering authored selections or instances.
Adding an instance captures edits, collapses prior editors and focuses the new
one; invalid pending text must refuse the action without losing the editor.
Provide the explicit batch-selection action. Four exact selected items must
produce four instances from a fresh starter; preserve edited groups, user Names,
existing IDs and references. Deduplicate only equivalent full configurations,
including inputs and settings. Never silently snapshot patterns or exclusions.
Keep ordinary single-element authoring available as a distinct mode. Activation
captures immutable starting settings once and replaces the full single form with
an exclusive instance view. Row Properties affect only that row; new instances
and explicit resets always use starting settings. Use a fixed compact toolbar,
independently scrolling rows and a visible outer footer. The batch panel contains
an independent selection editor, never a duplicate full settings form. Respect explicit
user names from the first input event, retain all existing names on reopen, derive
useful new names from actual configuration, resolve automatic collisions
predictably and refuse explicit collisions. Match the adaptor's identity schema
and reference contracts, including any leading-digit restrictions.

Stage edits locally; apply all rows and shared metadata atomically. Cancel must
leave the document unchanged, one Undo must remove the batch, and Redo must restore
it. Preserve the original node's identity and downstream references. Reuse schema
controls and expression validation. Group only when grouping semantics and common
settings agree; retain full selectors where duplicate leaf names are ambiguous.
Reuse Studio's explicit browser-local batch membership for reopening from Overview
and Edit settings. Preserve each saved member's identity and position when a
batch is edited. Reopen only surviving members of that recorded batch; omit
deleted instances, retain their provenance for Undo, and never absorb unrelated
elements. Membership is scoped to the document/operation and is not part of native
input. Do not guess batches from similar names or options; imported
untracked nodes remain individual until explicitly authored as a batch.

## Verify and deliver

Add meaningful policy/naming tests and a real browser test covering ordinary Add,
Edit, selected-row settings, explicit grouping, invalid inputs, name ownership,
collisions, cancellation, stale-document refusal, undo/redo and persistence.
Test batch selected-item creation, repeated-action deduplication, retained edited rows, compact
group summaries, pointer/keyboard header toggling, empty activation and save,
confirmed deletion, Properties cancellation, and settings/inspection retention.
Verify at least twelve instances scroll without moving toolbar/footer, no hidden
single form is reread, and a row changed from input A to B is followed by a new
instance still using input A. Available-name chips
must toggle selections consistently; test exact entries and the adaptor's pattern,
exclusion and All semantics, explicitly explaining any necessary snapshot.
Include workflow nesting and source-format coverage where the adaptor supports
it. Run existing relevant tests and required repository checks.

Run bounded native acceptance for every newly enabled semantic class. Inspect
actual outputs and independent identities, not just process status. Record missing
native environments or unqualified modes as limitations. Do not generalize one
serial example into exhaustive or MPI qualification.

Deliver the complete inventory, implementation, durable contract updates, exact
test commands/results and any remaining gaps. Clearly separate what is delivered
from future proposals. Keep the report factual; do not claim every node is covered
unless the reconciled inventory and tests support that claim.
