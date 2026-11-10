# Studio CFD authoring audit actions

Implementation checklist for the CFD post-processing input authoring workflow.
Each item includes related observations from the GUI audit; speculative layouts
are resolved using the audit's final preference for a side guide.

- [x] A01 — Use one path browser, collapse it after selection, retain an obvious reopen control, and offer the browser when saving input files.
- [x] A02 — Make string-list entry unambiguous (including `U`, `p`); provide deferred all/regular-expression selection for reader regions and arrays.
- [x] A03 — Offer metadata-only preview separately from live data; inspect a selected reader/upstream pipeline despite unfinished downstream nodes; explain unavailable data and preserve the draft.
- [x] A04 — Make the toolbar/editor split draggable and collapsible with independently scrollable controls.
- [x] A05 — Fix section-template insertion so a click persists; distinguish orthogonal single slices from arrays of slices and describe insertion/undo.
- [x] A06 — Expose editor undo/redo, separate saved revision history, and make diagnostic notifications open Problems.
- [x] A07 — Standardise hierarchical controls: expand/collapse all, depth, subtree expansion and generous disclosure hit targets.
- [x] A08 — Add component references, scalar expressions inside vectors, and editable AABB volumes with bounds-derived points, inflation, wake regions and camera guidance.
- [x] A09 — Make variable names start empty; support renaming/moving existing values while maintaining or explicitly protecting their references.
- [x] A10 — Explain filename tokens/key-value naming and offer naming presets; explain workers and role restrictions instead of an unexplained disabled value.
- [x] A11 — Explain native availability and workbench Validate/Preview/Run; distinguish Studio help from adaptor help.
- [x] A12 — Follow the editor cursor in the pipeline guide, enable node actions at nested locations, and offer Guide / Library / Hidden sidebar modes.
- [x] A13 — Add visible sidebar/bottom-panel controls and notification suppression without discarding Problems/Log history.
- [x] A14 — Add schema search, select/copy and hierarchical navigation controls.
- [x] A15 — Audit remaining listed controls and document the resulting authoring flow; verify meaningful host and browser regressions and run the release checks.

## Verification

Implemented all 15 action groups in Studio and the ParaView adaptor. Focused
checks and bounded native acceptance passed. The broad host suite was stopped
at its 20-minute budget and is inconclusive.

Key implementation choices:

- Metadata preview reads at most 64 KiB per candidate OpenFOAM header, with no
  native process. Unavailable metadata is an explicit result, not an HTTP error.
- Native inspection prunes downstream input before resolving references, retains
  original pointer addresses, and loads only the selected upstream closure.
  Live data is a bounded snapshot refreshed explicitly after draft changes.
- Adding a reader performs optional header inspection rather than launching
  ParaView. Deferred name selection remains in the authored input.
- The final side-guide preference supersedes the tentative overhead/new-tab
  sketches. Guide, Library, both, and hidden modes are available.
- Existing documented title-bar search, connection, role/theme controls,
  document-section navigation and viewer tabs remain supported; the audit's
  explanatory questions are covered in the Studio guide.
- Variable moves preserve explicit/relative reference meaning and parameter
  targets. Cross-scope sweeps and moving exposed parameters out of shared scope
  are explicitly protected with recovery instructions.
- Conceptual-help records were remapped by function identity when the two new
  volume helpers changed schema choice indices. Existing explanations and
  provenance were retained.

Verification so far:

- 859 JavaScript unit tests passed; the additional shared-workflow inspection
  regression also passed in the focused five-test regression suite.
- All 17 focused browser scenarios passed across the final runs. Two exposed
  defects and passed after repair; the final inspection and variable-authoring
  scenarios were rerun after the last functional changes.
- 103 focused Studio host tests passed, with one existing skip. The broad host
  suite was interrupted at its time budget without a final result; it is not
  claimed as passing.
- 21 conceptual-guidance tests passed; ParaView, Blender and workflow guidance
  audits report no pending or stale entries.
- A generated one-cell OpenFOAM case passed serial ParaView acceptance: header
  names, native reader names, deferred selections, exact unit-cube bounds and
  live surface geometry, while downstream input was invalid.
- Discovery and the release privacy gate passed. Native acceptance is limited
  to this serial synthetic case; MPI and large production meshes were not
  qualified.

The acceptance recipe is `tools/verify_studio_cfd.py`. The Studio guide documents
all new controls, value types, selection syntax and limitations.

## Round 2 — alternative pass (9 November)

A second implementation pass over the same audit plus the round 2 notes. It
builds on the round 1 work above rather than replacing it; where the two
differ, this section describes the current behaviour.

To compare or return to round 1: the working tree as round 1 left it is the
branch `backup/sol-gui-audit-2026-11-09`; this pass is
`backup/alt-gui-audit-2026-11-09`. The difference between them is exactly this
pass. Nothing was committed to `develop`.

- [x] B01 — One row for window tabs and Workbench actions; the title row is
  gone (the tab carries the name). The toolbar stays inside its window in the
  DOM and is drawn in the tab row; below 1150 px it is its own row.
- [x] B02 — Removed the hierarchy toolbar that was injected at the top of every
  window. The Schema view keeps its own.
- [x] B03 — Removed the view-controls row. Sidebar contents and hide moved into
  the sidebar header, with a restore button beside the view tabs. **Live data**
  moved beside **Run**. **Controls** hides the Add and editing rows. The
  draggable splitter is gone: with the rows this short it had nothing to do.
- [x] B04 — Snippet categories fold into **Snippets & templates**; the Add row
  is one line. A category button opens its tray if it is closed.
- [x] B05 — Disclosure buttons are two narrow buttons left of the label. The
  second opens everything below a closed item and closes an open one.
- [x] B06 — Case names are usable while editing: a **Case data** panel beside
  Properties (click adds to the list under the cursor), editor suggestions, and
  the entry list in the settings window. Names load when a case is opened.
- [x] B07 — **Browse…** opens the desktop's Open window through the existing
  `/api/input-file` route and falls back to Studio's own Open window. A user
  setting turns the desktop window off. Save uses Studio's window.
- [x] B08 — A reader is named after its marker file, or its folder for a
  generic `case` marker, until the name is typed.
- [x] B09 — Help text has its own colour token (`--help`) in both themes.
- [x] B10 — Regions and arrays are **All** or a list of entries, each an exact
  name or a regular expression, with Add/Edit/Delete and live match counts.
  The authored form gained mixed lists, `["internalMesh", {"pattern": "…"}]`.
  With no entries the setting is left out rather than left to fill.
- [x] B11 — The settings window has **Settings** and **Final values** screens,
  moves by its title bar, and Enter no longer closes it. **Add operation**
  works from either screen, so existing flows are unchanged.
- [x] B12 — **Edit…** (or a double-click) in the pipeline guide reopens the
  settings window for an existing node and applies it as one undoable edit.
- [x] B13 — The fill window moves by its heading and stays where it is put.

Decisions a later pass may want to revisit:

- The toolbar is absolutely positioned out of its window so that scoped
  selectors such as `.wb-workbench [data-action]` keep working. Moving it into
  the shell is cleaner and breaks those selectors.
- **Edit…** covers pipeline nodes only. Scene exports, axes and document
  settings still have no settings window to reopen.
- Case data holds header names. The block chooser for `extractBlock` still
  needs a live inspection; the two are not connected.
- Final values offers plain inputs by field type. It does not offer the
  expression forms of the editor's fill window.

Verification on this pass:

- 863 JavaScript unit tests passed, including four new ones for naming,
  entries, case names and suggestions.
- 37 Workbench browser scenarios: 34 passed and 3 skipped for want of a native
  application. A run of the wider Studio browser suite passed except for
  `concept-guidance`, `guided-authoring` and `help`, which fail the same way on
  the round 1 tree.
- 191 focused host tests passed except `test_generated_reference_has_no_drift`,
  whose 75 failures are also present on the round 1 tree: `docs/generated` has
  not been regenerated since round 1 began. The broad host suite was not run.
- The ParaView guidance audit reports no pending or stale entries. The release
  privacy gate passed.
- No native ParaView run was made. The mixed-list resolver is covered by host
  tests only.
- Browser tests now start Studio with `SCHEMAXIS_DESKTOP_CHOOSER=0`, so a test
  run cannot open a file window on the desktop.

## Round 3 — 9 November, later

Source: the third audit note. Round 2 is the starting tree; its snapshot branch
is unchanged.

- [x] C01 — An expression is no longer added while it is typed. Counting the
  open values read each control, and reading the name list committed its text
  box. Reading is now free of side effects; typing only previews the match.
- [x] C02 — **About this operation**, **? Operation reference** and
  **Suggest a correction** take the help colour.
- [x] C03 — **Edit settings…** above the input and in Properties reopens the
  settings window for the node at the cursor.
- [x] C04 — **Save as…** and **Open…** beside **Save**. The file name shows
  beside the revision. Saving over an existing file asks first. The reported
  loss of a saved file did not reproduce: saving to another folder through
  Studio's window wrote the file in a clean workspace.
- [x] C05 — `/api/documents` gained `open`: a saved file joins the workspace
  under the adaptor its version names, or its existing document is shown.
- [x] C06 — **Start** has a card per authoring application with New, Open and
  recent documents. `files.recentCount` sets how many, zero for none.
- [x] C07 — **Load names** and **Live data preview** sit beside the screen
  names. Each name list has its own Load names, and the names in the case are
  always in view under the entries.
- [x] C08 — `help.expert` folds help text in settings windows behind **?**.
  Settings shows the Files and help group, which also holds the desktop Browse
  setting that round 2 added without listing it.
- [x] C09 — `extractBlock` selectors are entries: a selector or bare block
  name, `{"pattern"}` or `{"exclude"}`. The settings window and Properties use
  the same entry list as reader regions, fed by the case headers, so no live
  inspection is needed to choose blocks. The tree chooser is removed.
- [x] C10 — The fill window accepts plain names, separated by commas, where a
  list is expected.

Not done, with reasons:

- Schedules stays in this repository. Moving it to the database integration
  repository changes two repositories and their licensing boundary.
- The Schema Editor was not examined beyond its Start card.
- Recent items are the workspace's documents. A per-application
  remember/forget setting was not added; one count covers all three.
- The reader offers regions and cell arrays. Point and Lagrangian arrays are
  reader properties the curated `foam` operation does not declare.
- Final values still offers plain inputs by field type.

Verification on this pass:

- No native ParaView run was made. Block patterns and exclusions resolve in
  `block_choices.py`, covered by host tests; the hook in `native.py` that reads
  the input's hierarchy has not run against ParaView. The live block test in
  `pipeline-authoring.browser.test.mjs` was rewritten for the entry list and
  has not run either.

