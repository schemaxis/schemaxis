# S2b guided authoring verification

Implementation on `studio-gui`, starting at `18db288`.
No S6 work or native ParaView execution is included.

## Baseline

- `git branch --show-current`: `studio-gui`.
- `git log --oneline main..HEAD`: seven commits, ending at `18db288`.
- `git status --short`: only untracked `website/`, left out of scope.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests/unit -q`:
  1,057 tests in 304.309 s, OK, 22 skipped. Log `/tmp/s2b-baseline-python.log`.
- `CHROMIUM=/snap/bin/chromium STUDIO_SCREENSHOTS=/tmp/s2b-baseline-shots node --test --test-concurrency=2 src/schemaxis/studio_ui/tests/*.test.mjs`:
  repeat passed 128 of 129 tests, one opt-in native skip, 49.716 s.
  Log `/tmp/s2b-baseline-node-repeat.log`.
- The first sandboxed browser launch failed because Snap's profile/runtime directories
  were read-only. A run outside the sandbox had one integration CDP timeout;
  that test passed alone in 3.302 s and the subsequent full repeat passed.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 examples/studio/check.py`:
  both cases bind and plan; export digest and output naming checks pass.
- Integrator visually inspected `studio-workbench-light.png` and
  `studio-workbench-dark.png` in `/tmp/s2b-baseline-shots`.

## Implementation checks

### Calm diagnostics

The integrator tested the exact staged diagnostics implementation in an isolated
checkout-index snapshot, before including fill or library changes.

- Full Python suite: 1,057 tests, 22 skipped, OK in 339.241 s.
  Log: `/tmp/s2b-diagnostics-python.log`.
- Full Node and real Chromium suite: 154 tests, 153 passed, one opt-in native
  skip, no failures, 77.808 s. Log: `/tmp/s2b-diagnostics-node-snapshot.log`.
- Integrator inspected editing and settled screenshots in both light and dark
  under `/tmp/s2b-settle-shots`. Typing shows Editing… without adding Problems;
  settled errors use inline diagnostics, and explicit actions group reports.
- A first snapshot under `/tmp` could not upload fixture files through Snap's
  private temporary directory. The successful snapshot used ignored
  `evidence/check-diagnostics`. A shell assertion was updated to account for the
  deliberately reported diagnostics when leaving an invalid draft.

Fill mode, library v2 and expanded catalogues are recorded below.

### Fill mode

- Exact staged fill implementation was tested in ignored `evidence/check-fill`.
- Full Python run: 1,058 tests, 22 skipped, 340.940 s; the sole failure was
  generated `modules.json` drift from the new functions import. Regenerated the
  inventory with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/export_input_reference.py`.
  All 10 schema/reference tests then passed in 68.113 s. Logs:
  `/tmp/s2b-fill-python.log`, `/tmp/s2b-fill-schema.log`.
- Full Node/Chromium repeat: 164 tests, 163 passed, one opt-in native skip,
  no failures, 70.465 s. Log `/tmp/s2b-fill-node-repeat.log`.
- The first browser run exposed an obsolete empty-string completion expectation.
  The replacement test accepts the inserted fill marker through its real picker.
- Integrator inspected `/tmp/studio-fill-shots/fill-light.png` and
  `fill-dark.png`: readable marker chips, anchored forms and remaining-value badge.
  The browser test covers all nine expression forms, validation, keyboard field
  movement, marker persistence, and atomic axis creation/undo.

### Library v2, insertion and execution guards

- Full Python run: 1,078 tests in 327.915 s, 22 skipped. Only the two generated
  module-reference files were stale. Regenerated the reference; all 10
  schema/reference tests passed in 55.977 s. Logs:
  `/tmp/s2b-library-python.log`, `/tmp/s2b-library-schema.log`.
- Independently reran 62 focused tests covering the final loader, every existing
  catalogue item, exact unfilled pointers, binding, design exposure/export and
  Case Runner refusal. All passed. This includes the later @cursor array-slot
  correction and resolved operation identity regression.
- Full Node/Chromium final run: 173 tests, 172 passed, one opt-in native skip,
  no failures, 62.168 s. Log `/tmp/s2b-library-node-final.log`.
- Latest reference-choice filtering and template-category changes: 13 focused
  unit/browser tests passed. Log `/tmp/s2b-library-final-focused.log`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 examples/studio/check.py`
  still passes both exact cases, export reproducibility and naming.
- Integrator inspected library popover/ghost screenshots in both themes under
  `/tmp/schemaxis-library-shots`, and real Workbench screenshots under
  `/tmp/s2b-library-shell-shots`. Corrected an empty section strip found during
  screenshot review; final images are in `/tmp/s2b-library-final-shots`.
- Native launches are prohibited in the generated catalogue harness. Exposed
  draft templates retain marked example case values; they are not falsely
  reported as bound/verified until actual values are supplied.
- Integrator independently reran both Designer browser themes after source-tab
  library/schema integration: 2/2 passed in 15.062 s; log
  `/tmp/s2b-designer-library.log`. The content acceptance test will exercise its
  actual packaged workflow-design catalogue after promotion.

### Expanded catalogues and final integration

All 383 entries are packaged v2 libraries: 326 snippets and 57 templates. The
generated test visits every entry, fills it using its declared defaults/test
values, host-plans the result, and checks exact `UNFILLED_VALUES` records and
pointers for its marked variant. Native process launch is prohibited in this
test. Four retained legacy templates are intentionally concrete; their marked
variant has no missing values. Paths requiring real assets carry prerequisites;
host planning is not evidence that those assets exist or execute successfully.

| Adaptor | Snippets | Templates |
| --- | ---: | ---: |
| ParaView | 100 | 10 |
| FreeCAD | 44 | 6 |
| Blender | 47 | 5 |
| Godot | 22 | 4 |
| Aseprite | 13 | 3 |
| Gmsh | 15 | 4 |
| Octave | 15 | 3 |
| QGIS | 15 | 3 |
| ngspice | 12 | 4 |
| Cantera | 8 | 3 |
| Calc | 8 | 3 |
| FFmpeg | 6 | 2 |
| Case preparation | 6 | 2 |
| Workflow | 10 | 3 |
| Workflow design | 5 | 2 |

Content was checked against the actual registry operation declarations (the
source of `schemaxis describe`) and examples under `examples/schemaxis`. Content
was drafted outside the repository until contract commit `b69ecff`, then promoted
and tested as three disjoint content batches.

Final integration corrections found by testing and review:

- Long composite previews use a bounded scrolling preview surface, preserving
  authored text, caret and scroll position. Every insertion is previewed.
- Linked XYZ markers count and navigate as three fields rather than 36 separate
  occurrences; replacement and undo remain atomic within the insertion scope.
- Gallery cards fit the dialog, and unfinished IDs have readable outline labels.
- Discriminator follow-ups queue through remaining fields; reference choices
  exclude unfinished IDs and tolerate unfinished collections.
- Nested Schema Editor requests namespace fields across the authored root while
  keeping node-ID uniqueness scoped to the relevant operation document.
- Missing numeric intermediate containers preserve their specified index.
- Direct workflow validation now enforces the same unfilled-value guard as
  registry planning, HTTP validation, binding and the Case Runner.
- Live geometry replies carry revision-scoped observations; field-name pickers
  consume real `fields.POINTS/CELLS/ROWS` metadata rather than geometry alone.
  Host and mocked-transport browser tests verify this; no new native acceptance
  is claimed.

Verification commands and outcomes:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests/unit -q`
  passed 1,080 tests (22 skipped) in 301.748 s before the final audit fixes.
  Log `/tmp/s2b-final-python-repeat.log`. The same command after all audit fixes
  passed all 1,082 tests (22 skipped) in 295.901 s, with process exit code zero.
  Final log `/tmp/s2b-final-python-verified.log`.
- The first expanded-content Python run failed five obsolete v1 expectations in
  `test_studio_templates.py`. Replaced the v1-only loader/cross-product assumptions
  with the v2 loader and template planning checks; the generated harness tests
  contextual snippets on their declared bases rather than unrelated templates.
- The first final frontend run passed 177 of 181 tests, with one native skip and
  three failures. All three were physical test clicks below the viewport after
  the expanded sidebar grew. Scrolling the targets and requiring a visible fill
  popover fixed the tests; the full Workbench file then passed six tests, with
  one native skip. Initial full-run log: `/tmp/s2b-final-node.log`.
- Final independent frontend command:
  `CHROMIUM=/snap/bin/chromium STUDIO_SCREENSHOTS=/tmp/s2b-verified-shots node --test --test-concurrency=2 src/schemaxis/studio_ui/tests/*.test.mjs`
  passed 185 of 186 tests, with one opt-in native skip and no failures, in
  93.851 s. Log `/tmp/s2b-final-node-verified.log`. This includes the queued
  discriminator, nested namespace and mocked native-observation regressions.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_studio_catalogue.py -v`
  independently validated all 383 entries in 10.661 s before the final direct
  workflow regression was added. Log `/tmp/s2b-final-catalogue.log`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 examples/studio/check.py`
  passes both cases, export digest reproducibility and collision-free naming.
- `python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/s2b-wheel .`
  succeeded. ZIP inspection found all 15 library JSON files and every referenced
  template, and excluded browser fixtures. Log `/tmp/s2b-wheel.log`; this was a
  packaging check before the final UI corrections, not a released wheel.
- `git diff --check` passes.

Integrator screenshot review covers the full-shell category bar, popover, section
and composite ghosts, template gallery, fill mode, deferred values, calm editing
and settled footer, and exposed draft export in both themes. Images are under
`/tmp/s2b-final-shots`, with the successful final run under
`/tmp/s2b-verified-shots`; final section ghosts were inspected again in both themes.
Additional reviewed discriminator follow-up and observed-field images are under
`/tmp/s2b-fill-followup-shots` and `/tmp/s2b-native-fields-shots`. Bulk screenshots
remain local, outside Git.

Wanted but deliberately omitted because the current adaptor contracts do not
support them:

- ParaView native discovery of latest/source-time ranges and solver-convergence
  judgement; recipes use explicit authored times and measured data.
- FreeCAD arbitrary Sketcher constraints and moving assemblies; Blender arbitrary
  shader graphs and multiple-scene/writer recipes; Godot physics, navigation,
  runtime scripts and animation tracks; Aseprite arbitrary blending and importing
  existing sprite documents.
- Gmsh boundary layers/hexahedra and general CAD graphs; Octave nonlinear fitting
  and arbitrary formula execution; QGIS raster layers, styling and geodesic buffers;
  ngspice arbitrary netlists/nonlinear devices/general transient integration;
  Cantera carbon chemistry, kinetic reactors and multiphase transport.
- Calc arbitrary formulas/layout/charts, FFmpeg audio/filtergraphs/video editing,
  and CFD solver execution or undeclared solver controls.
- Native feedback-loop execution remains S6 and requires a separate design review.
