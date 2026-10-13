# Shared authoring acceptance — 2026-09-27

M3's first production slice connects recoverable JSON source, properties, console
commands and agent plans. It builds on M1 `fb687d3` and M2 `39ba4b9`.
[Usage](../docs/shared-authoring.md) · [Native evidence](2026-09-27-shared-authoring.json)

## Changed behaviour

- Shared authoring transitions and atomic-storage primitives are extracted from
  console ownership. Existing sessions and native preview paths remain supported.
- Exact source, including invalid JSON, survives undo/redo and restart. Invalid
  current drafts cannot be presented as an earlier executable document.
- Property groups and commands share history; stale document/revision edits fail.
  Syntax faults have source coordinates. Source pointers and carets map both ways.
- Source writes compare recorded disk digests; undo cannot restore an obsolete
  file baseline. New destinations are created exclusively.
- Agent draft tools reuse the console's persisted authoring workspace. Captured
  plans/jobs retain draft identity, revision and source digest. Later source edits
  or history travel require a new plan before execution.
- The visual console has a source/property dialog using the same HTTP service.
  It retains dirty local text during polling, exposes invalid-source diagnostics,
  and routes property edits through revision-checked grouped history.

## Host checks

Full unit suite: **684 tests run, 22 skipped, no failures/errors**, 163.663 s.
Log: `evidence/authoring-2026-09-27/unit.log`.

The **18 new authoring tests** cover syntax/semantic invalid drafts, duplicate and
nonfinite JSON, recovery, grouped edits and rollback, expression preservation,
file conflicts, exact source saves, console/form/agent document-and-plan parity,
stale plan rejection after edits and undo, ownership and cross-client reopen,
budget-bypass rejection, escaped/Unicode pointer ranges, source limits, persistence
failure, busy-command rejection and authenticated HTTP/revision handling.

The existing service native-import/process guard now exercises draft creation,
source editing and draft planning in a fresh interpreter. Console, service,
reference and scheduling regressions also pass. JavaScript syntax, public
`discover`, all **46** generated-reference checks and whitespace checks pass.

## Native acceptance

`tools/qualify_authoring.py` drove the public local subprocess transport:

1. Create a 20 × 10 × 5 mm FreeCAD box draft and capture a plan.
2. Retain invalid JSON. Reject the old plan with `STALE_REVISION`, and reject a
   new plan of that source with `INVALID_DRAFT`, without consuming attempts.
3. Exit and restart the service. Recover the exact invalid source, then undo it.
4. Capture and execute the restored draft. Reverify **1,000 mm³**, three artifacts.
5. Exit the service. Use the actual terminal console on the same `authoring`
   workspace to set height to **7.5 mm**.
6. Restart the agent, reject its stale plan, capture the new draft revision and
   execute. Reverify **1,500 mm³**, three artifacts. Exactly two attempts consumed.

Both runs used **FreeCAD 1.1.3**. The client made **36 requests**, with three
intentional rejections, **20,007 response bytes** and a **681-byte** largest reply.
Counts include status polling and vary with runtime speed. Retained documents,
history, plans, jobs, receipts and outputs are under
`evidence/authoring-2026-09-27/native/`. This is deterministic serial acceptance,
not a broader agent evaluation or new native adaptor qualification.

## Browser checks

Checked the production local console in the in-app browser:

- Source loaded at its displayed revision.
- Pointer lookup found the height value and reported its source line/column.
- Applying height 8 advanced the revision and updated source in the same history.
- Retaining malformed JSON displayed a line-2 diagnostic and an invalid-draft label.
- Reloading the browser recovered that same invalid source; Undo restored valid
  source at a new revision.
- The final wide dialog was visually inspected. Property lookup focuses/selects
  source; caret lookup returns the same property. Native preview remained unavailable
  in this host-only browser fixture, as expected.

Browser checks are separate from native serial acceptance. This does not claim
new native geometry, image-picking or mobile-browser qualification.

## Remaining M3 work and limits

- Typed historical reference envelopes for text/table/series alongside geometry,
  trusted view/workspace registries and coordinated inspection panels remain open.
- Source/property authoring targets console-supported adaptor documents; workflow
  documents continue through existing direct planning. YAML remains deferred.
- Property edits preserve values and expressions, but reformat JSON. No concrete
  syntax tree preserves whitespace through structural/property edits.
- Independent console and agent processes hand off exclusive workspace ownership;
  the CLI does not yet multiplex both transports concurrently in one process.
- External file changes are checked immediately before atomic publication. There
  is no filesystem compare-and-swap or cross-file source/session transaction.
- Unsubmitted browser text survives dialog closure in its current tab, not a page
  reload; **Retain source** persists it, even when invalid.
- Broader held-out model evaluation and the pending extraction adaptor remain open.
  The other workspace's adaptor shortlist and root README were left untouched.
