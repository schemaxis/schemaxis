# Studio GUI acceptance

Implementation: `0c023ee` on `studio-gui`.

## Fresh verification

| Check | Result |
| --- | --- |
| Complete Python unit suite | 1,057 tests: 1,035 passed, 22 skipped; 280.9 seconds |
| Complete frontend/browser suite with both native opt-ins | 126 passed, no skips; 89.2 seconds |
| Final User-mode adaptor-card correction | Both affected light/dark shell tests passed |
| Runnable Studio starter | Both cases bind; all three parameters reach their operations; export digest reproduces |
| Clean wheel build | 427 entries; all packaged source bytes match the working tree; no legacy UI or browser fixtures |
| Installed-wheel smoke check | Studio schema API and all five adaptor template libraries load |
| Whitespace and staged-path checks | Passed; `website/` excluded |

Commands from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/export_input_reference.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
CHROMIUM=/snap/bin/chromium STUDIO_RUN_NATIVE=1 STUDIO_NATIVE=1 \
  STUDIO_SCREENSHOTS=/tmp/studio-release-shots xvfb-run -a \
  node --test --test-concurrency=1 src/schemaxis/studio_ui/tests/*.test.mjs
CHROMIUM=/snap/bin/chromium node --test src/schemaxis/studio_ui/tests/shell.browser.test.mjs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 examples/studio/check.py
```

The browser suite starts actual Studio HTTP servers with temporary workspaces.
It drives Chromium through its debugging protocol, using the real editors,
forms, dialogs, canvas, server APIs, native dispatch and publication verification.
Native checks run serially. Optional native applications remain opt-in for normal
frontend test runs.

## Observed behaviour

- Designer: named ports, connections, persisted layout, loop configuration,
  parameters, output aliases/naming, source editing and sample-data inspection.
- Workbench: schema-driven properties, nested operation editing, template/snippet
  previews, input/schema tabs, four viewers and removable reference chips.
- Schema Editor: multiple schemas, invalid draft retention, open/export/save,
  navigable diagnostics and revision-safe source history.
- Case Runner: exact template identity, typed parameters, protected case saves,
  planning, asynchronous execution/cancellation and verified named publications.
- End-to-end starter: edit sequence start in nested Workbench, save/reload the
  design, export through the Designer dialog, load/edit/save a case, run actual
  Octave, verify four named outputs, and check scaled rows `[1,3]` through `[6,18]`.
- Actual FreeCAD preview supplies live geometry and topology picks. Image picks
  retain the captured pixel value and digest. The GUI/batch launcher distinction
  is handled by the FreeCAD adaptor hook.
- Viewer checks cover real WebGL orbit/pick/section/walk controls, image pan/zoom,
  a 100,000-row by 50-column virtual table, stable sorted/filtered row identities,
  and regex extraction from 200,000 text lines.
- Deterministic delayed-response tests preserve typing across loads, saves and
  history changes. Competing case saves reject the stale baseline. Artifact
  reads/downloads check digests; reference chips retain provenance and mark
  changed revisions/content as stale.

Light/dark screenshots were inspected. Bulk logs and screenshots are retained
locally under the ignored `evidence/studio-2026-10-04/` directory. The built wheel
is under the ignored `.schemaxis/studio-release/` directory.

## Limits

This is bounded serial acceptance of FreeCAD and Octave, not qualification of
every native adaptor, MPI or production deployment. ParaView was not invoked.
Feedback loops remain design/configuration only; executing them and implementing
runtime text/subset operations remain the separate S6 design-review scope.
Viewer chips are evidence references, not universal native selection expressions.
Interface roles are convenience controls on a token-protected local workspace,
not separate authenticated accounts. Saved case history survives on disk; the
current GUI job list does not reconstruct earlier launches.

See [the Studio guide](../docs/visual-console.md) and
[the runnable starter](../examples/studio/README.md) for use and restart commands.
