# Multi-mode addition orientation and Name-lock investigation

Copyright (C) 2026 David L. F. Gaden.

## Delivered behaviour

Add instance captures edits, collapses earlier editors and positions the preceding
collapsed instance at the top of the scrollable list. The new expanded instance
sits directly beneath it. Short new editors fill the remaining viewport so the
scroll range permits this alignment even on a tall screen. Collapsing an editor
clears that temporary minimum height. Focus moves into the new instance without
scrolling away the preceding summary; toolbar and Apply/Cancel remain fixed.

## Name-lock finding

The reported unreferenced extract reproduced the existing distinction between
ordinary single-instance forms and saved multi-mode instances. Quick rows use
`readOnly: row.original`; their Properties windows receive
`lockName: state.original`. Batch application also requires original IDs to remain
unchanged. These are unconditional identity guards, not results of a reference
search. The prior text “Other nodes refer to this name” incorrectly implied that
consumers had been found.

Ordinary single-instance forms and the main text editor permit ID changes and do
not automatically rewrite consumers. A remembered batch reopens in multi-mode,
which explains why its individual Properties window also has a locked Name.
The help now accurately distinguishes these behaviours. The locking policy is
unchanged; consistent reference-aware renaming, including batch provenance and
Undo, is recorded in TODO. The inspected case was read only.

## Verification

Eleven Chromium checks passed across `multi-mode-add`, `multi-mode-names`,
`multi-mode`, and `multi-mode-choices`. The final layout adjustment was also checked
against available-name viewport sizing, instance Properties/default isolation,
and the fixed toolbar/footer scrolling test.

The addition test exercises 700-pixel and 1,100-pixel screen heights, the first
addition through fifteen instances, valid and invalid pending patterns, preservation
of named selections, adding after reopening an older editor, keyboard focus,
visible predecessor/new-editor geometry, and applying the resulting batch.
The tall layout was inspected as a rendered browser image.

The Name test uses an extract with a tyre-matching pattern and no downstream
references. It verifies successful ordinary single-instance renaming, the saved
multi-mode quick-row and Properties locks, accurate explanations, cancellation,
and preservation of the original input.

Modified production modules passed JavaScript syntax checks. `git diff --check`
and the generated Help freshness check passed; all 1,638 topics are current.
These are UI changes; native execution and the full host/release suite were not
rerun.
