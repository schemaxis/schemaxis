# Studio sidebar and subset-selection verification

Copyright (C) 2026 David L. F. Gaden.

This records the initial iteration. The [selection follow-up](2026-11-15-gui-selection-follow-up.md)
supersedes its double-click behaviour and adds deleted-member batch recovery and
a larger available-names viewport.

## Delivered behaviour

- The view row retains its views, puts Controls and a matching Case data toggle
  at the right, and omits file/diagnostic summaries. Left and right sidebar
  visibility persist independently. Old Both preferences migrate to Overview.
- Overview and Templates replace Guide/Library/Both. A second title click
  deselects; real double-click opens full settings, including remembered batches.
  Each expanded node encloses its details and has a sticky title with Edit,
  Duplicate and Delete. The header leaves with the end of its own properties.
- Case data provides section Copy and Export CSV, plus Copy all and complete CSV
  export. Section copy appends missing values to a compatible list in one edit,
  or copies a JSON list. Copy all preserves section identity in a JSON object.
  Filtering does not truncate exports. CSV preserves quotes, commas, newlines
  and supplied time order. Clipboard errors produce an explicit failure message.
- Block selection has Select All/Deselect All, filtered Select shown/Deselect
  shown, Shift-click ranges, Ctrl/Cmd-click toggles and mouse box selection
  (Ctrl/Cmd-drag toggles). It retains unshown choices and dynamic patterns, works
  in single-instance and multi-mode settings, and avoids repeated full-list scans
  for large exact selections. Deselect All deliberately clears pending entries,
  patterns and exclusions too.
- The adaptor rollout backlog, design rubric and reusable authoring prompt now
  require independent subset-selection audits for every relevant operation/field.
  Studio guidance and packaged Help describe the new interactions.

## Checks run

All commands below passed with the final implementation.

```bash
node --test --test-concurrency=2 src/schemaxis/studio_ui/tests/{gui-features,workbench-sidebars,reader-selection,multi-mode,compact-comprehension,gui-audit,gui-audit3,settle,studio-audit,studio-integration,workbench}.browser.test.mjs
```

27 passed; the opt-in native FreeCAD preview was skipped. Real Chromium tests
cover both light/dark workbench editing, actual CSV file downloads, clipboard
success/failure, JSON/YAML insertion and one-step Undo, physical double-clicks
(including a selected sticky title), sticky header boundaries, dependent deletion
and restoration, independent panel toggles/reload, box selection, keyboard
selection, saved multi-mode reopening and viewer-reference integrity.

```bash
node --test src/schemaxis/studio_ui/tests/multi-mode-choices.browser.test.mjs
node --test --test-concurrency=2 --test-name-pattern='nested validation|nested sourced assembly' tests/studio/workflow-validation.browser.test.mjs tests/studio/freecad-assembly-sources.browser.test.mjs
```

Three additional browser checks passed: bulk selection in actual extractBlock
single/multi-mode forms, instance/input isolation, and workflow-scoped validation
after removal of the view-row diagnostic summary. Total: **30 browser checks**.

```bash
node --test src/schemaxis/studio_ui/tests/{gui-features,reader-selection,pipeline-authoring,element-authoring,authoring-groups,workbench-model,workbench-provenance,gui-audit2}.test.mjs
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_studio_guidance.py -q
PYTHONPATH=src python3 tools/generate_studio_help.py --check
git diff --check
```

37 JavaScript checks and 22 Python checks passed. Selection coverage includes
10,000 loaded names, pattern exclusions, retained full paths, empty selections
and ordering. All 1,638 packaged Help topics were current. Modified JavaScript
modules passed `node --check`. The Overview and selection screens were also
inspected as rendered browser images.

## Scope

These are authoring/UI changes; native execution and the full host/release suites
were not rerun. Existing leaf-name ambiguity and the distinction between case
header hints and native input inspection remain as documented. No broader
adaptor rollout or native qualification is claimed.
