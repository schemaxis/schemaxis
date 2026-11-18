# Studio selection and multi-mode follow-up

Copyright (C) 2026 David L. F. Gaden.

## Behaviour

- Overview title clicks toggle selection immediately, including rapid successive
  clicks. Double-click editing and its help text have been removed. Edit remains
  available in the sticky header. Clearing selection defers construction of the
  whole document schema until the Schema tab is opened.
- A remembered extractBlock batch reopens with its surviving members in their
  original authored order. Deleted members are omitted; unrelated extracts are
  never inferred as members. Applying edits retains the omitted identities in
  browser-local provenance so Undo can restore membership. Existing members
  retain their names, document positions and references.
- The available block names have their own scrolling viewport, sized up to 35%
  of screen height with 180–420 pixel bounds. The headings, filtering, help and
  bulk-selection controls no longer consume a shared 180-pixel height limit.
  Smaller sets use only the space they need. The instance list scrolls while the
  toolbar and Apply/Cancel stay visible.
- The Studio guide, multi-mode design, authoring prompt and packaged Help reflect
  these behaviours.

## Verification

21 browser checks passed in Chromium: nine across `workbench-sidebars`,
`multi-mode` and `multi-mode-choices`, plus twelve across
`compact-comprehension`, `gui-audit`, `settle` and `workbench`.
The opt-in native FreeCAD preview check was skipped.

Coverage includes real successive clicks, sticky-header boundaries, Edit and Undo,
the document Schema tab after deselection, saved batch reload, deleted-member
recovery, applying changes without resurrecting deleted nodes, leaving an
unrelated extract untouched, and restoring deleted membership through Undo after
a batch edit. Layout checks cover 29 names at 1440 × 960 and 600 × 700, including
scrolling to and selecting the last name and reaching Cancel. The larger layout
was also inspected visually; all 29 names fit in the expanded names area.

25 JavaScript unit checks passed across `authoring-groups`, `element-authoring`,
`workbench-model`, `pipeline-authoring` and `workbench-provenance`. These include
missing first/middle/last members, a lone survivor, no survivors, duplicate
identities, wrong operation types, document scope and reference preservation.
Modified production JavaScript passed syntax checks; `git diff --check` and
`tools/generate_studio_help.py --check` passed for all 1,638 Help topics.

A local Chromium timing probe on the same 80-node sphere document measured five
synchronous deselection clicks before and after the change:

| | Click duration | Schema details present after deselection |
|---|---|---|
| Before | 472.7–519.3 ms | 18,618 |
| After | 2.5–3.7 ms | 121, retained from the selected node |

These are local measurements of the synchronous click handler, not a cross-machine
performance guarantee. Whole-document schema construction still runs when the
user requests it in the Schema tab.

## Scope

Membership still requires an explicitly recorded batch in the same Studio browser
origin and document scope. Older/imported untracked nodes retain their individual
settings; membership cannot be reconstructed reliably from matching names or
settings. Native execution and the full host/release suites were not rerun for
these UI changes.
