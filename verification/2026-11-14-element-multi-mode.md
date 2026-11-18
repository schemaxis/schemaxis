# Element multi-mode reference qualification

Copyright (C) 2026 David L. F. Gaden.

Scope: Studio's shared element-authoring policy and ParaView `extractBlock`.
This is a bounded reference implementation, not an audit of all adaptors.

## Native serial acceptance

Command (set the environment variable to the chosen ParaView installation):

```sh
SCHEMAXIS_PARAVIEW_ROOTS="$PARAVIEW_INSTALLATION" PYTHONPATH=src \
  python3 -m unittest discover -s tests/conformance \
  -p test_paraview_element_multi_mode.py -v
```

Ran successfully with ParaView 5.13.3's precompiled Linux MPI distribution in a
single serial process. The test builds four spatially separated spheres, groups
them as `internalMesh`, `WT_wall_XP`, `WT_wall_XM` and `Inlet`, then executes four
ordinary `extractBlock` nodes plus one extract selecting both walls.

All five geometry publications passed the runner's independent file reopening,
content-digest and receipt checks. Each independent extract contains its expected
named block and 1,056 cells. Their x-centres are respectively 0, 4, 8 and 12. The
grouped extract contains both wall names and 2,112 cells. These checks demonstrate
independent outputs and explicit grouping semantics, not merely process success.
The fixture also uses the numeric-leading instance name `004_031_9d_case` for
one source and connects it to the group, qualifying that name through native
execution as well as host validation.

The OSMesa installation could not launch because a system `libglapi` dependency
was unavailable; another local build lacked its MPI library. The successful run
used the precompiled distribution without changing the application PATH. This
qualification does not claim MPI execution, CFD correctness, every selector
expression or production-case coverage.

The opt-in browser workflow also passed against the same installation with a
temporary local Studio configuration:

```sh
SCHEMAXIS_CONFIG="$LOCAL_TEST_CONFIG" SCHEMAXIS_LIVE_PARAVIEW=1 \
  node --test src/schemaxis/studio_ui/tests/pipeline-authoring.browser.test.mjs
```

That workflow generates a small OpenFOAM case, explicitly chooses All regions,
checks the `fixture_case` reader Name, inspects native `walls`/`internalMesh`
blocks, creates `extractBlock_walls`, validates its references, and exercises
pipeline browsing, duplication, dependent deletion and Undo. The configuration
is external to the repository; application PATH and personal configuration were
not changed.

## Host and browser coverage

The reference tests are:

- `tests/unit/test_studio_element_authoring.py`: host-only catalogue projection,
  invalid metadata rejection, and schema-path/type checks before rendering.
- `src/schemaxis/studio_ui/tests/element-authoring.test.mjs`: configuration names,
  collisions, ordinary node expansion, reference preservation and grouping rules.
- `src/schemaxis/studio_ui/tests/authoring-groups.test.mjs`: explicit browser-local
  memberships, document/operation scoping, Undo/Redo membership versions, missing
  and ambiguous members, and noncontiguous existing-node updates without rewiring.
- `src/schemaxis/studio_ui/tests/multi-mode.browser.test.mjs`: real Studio Add/Edit,
  automatic and explicitly owned Names, independent rows, split/group actions,
  selected-only settings, conflicting grouping, collisions, cancellation,
  stale-document refusal and editor Undo/Redo. Its six browser cases also cover
  four batch selections producing exactly four compact instances, repeated-action
  deduplication, full-group summaries, clickable headers, retained edited groups and Names,
  and per-row inspection preserving inputs independently of other rows. Empty
  activation retains loaded choices and opens quick settings; tests select and
  save from that state, toggle the header by keyboard, hide/show batch checkboxes
  without losing their selection, retain choices after adding an instance, cancel and confirm deletion, and cancel full Properties without
  changing the instance. Twelve-instance geometry checks keep the toolbar and
  footer fixed while rows scroll, and changing an original row's input in
  Properties leaves later additions on the captured starting input. The five
  pure authoring tests cover the same split policy with different inputs/settings
  and explicit pattern refusal.
  The saved-batch case reopens from a different member, changes that member in
  place, checks one Undo, saves the file, reloads Studio and reopens all four rows.
- `tests/unit/test_node_instance_names.py`: numeric-leading instance names in
  schema, planning, selected output ports, observations and quoted expressions.
- `src/schemaxis/studio_ui/tests/reader-naming.browser.test.mjs`: the requested
  parent/file naming examples and explicit user ownership, including entering
  the current automatic suggestion as the user's chosen Name.
- `src/schemaxis/studio_ui/tests/document-history.browser.test.mjs`: complete
  document changes preserve JSON source boundaries and one Undo/Redo in JSON
  and YAML. The editor preserves the terminal newline outside native text edits
  to avoid corrupting Chromium's Redo range.
- `src/schemaxis/studio_ui/tests/block-inspection.browser.test.mjs`: native
  choices use the selected input, survive shared-header refreshes, clear when
  the input changes and discard late replies for the former input.
- `src/schemaxis/studio_ui/tests/reader-selection.test.mjs` and
  `reader-selection.browser.test.mjs`: offered names toggle exact selections,
  pattern-selected blocks use precise exclusions, exclusion-only groups retain
  their baseline, and individual reader deselection materialises affected All or
  pattern selections. The browser checks keyboard activation, retained focus,
  selected state and the notice explaining the change to exact names.
- `src/schemaxis/studio_ui/tests/multi-mode-add.browser.test.mjs`: Add instance
  minimises earlier editors, preserves Names and pending valid selections, refuses
  invalid pending text, and focuses/scrolls the new editor in a short viewport.
- `src/schemaxis/studio_ui/tests/workbench-sidebars.browser.test.mjs`: long Guide,
  Library/Both and Case data scroll without moving header buttons or Edit settings.
  Guide selects the complete node; full settings editing and one Undo work. The
  duplicate inline Properties panel is absent. Offered regions and arrays sort
  naturally, while time and authored-selection order remain unchanged.
- `src/schemaxis/studio_ui/tests/multi-mode-choices.browser.test.mjs`: entering
  multi-mode before choosing anything retains header names and opens a working
  empty draft. Native choices are shared by input identity, survive header loads,
  remain isolated when another instance input changes, and seed new instances. Full
  Properties can change one instance's Name, input and selectors without editing
  the document before the outer Apply. The mode title changes, ordinary settings
  leave the layout, and later additions still use the captured starting input.
  The Properties Apply action explains that it returns to multi-mode.

Targeted pipeline (23), state-bundle (41), guidance (22), schema/parser parity
(5), source-time (5), authoring-policy (3) and instance-name (3) host tests passed.
The existing Add-catalogue, block-selection, file-browser and editor browser
checks also passed. The complete host suite and release gate were not run for
this reference implementation. Generated reference consistency was checked
against all 188 outputs, and `git diff --check` passed.

The native fixture consumes the same ordinary node shape that the browser emits.
No new multi-mode syntax is required by the native runner. The browser test is not
used as evidence that a native selector matches a nonempty dataset.
The follow-up interaction corrections were checked in the browser; they change
authoring and selection-choice state, not native execution. Native checks above
were not repeated for those UI-only changes.
