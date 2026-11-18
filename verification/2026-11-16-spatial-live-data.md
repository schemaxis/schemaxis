# Spatial templates and resident Live Data

Copyright (C) 2026 David L. F. Gaden.

## Delivered behaviour

- Linked volumes save before data exists; fixed snapshots still require resolved
  coordinates. Existing core type/dependency checks and cycle detection apply.
- Volume suggestions follow source and adjustment settings until the first user
  edit. Spatial names remain editable; checked expression bindings and document
  references follow renames transactionally, including workflow shadowing.
- Session-owned Live Data retains native processes, upstream handles and measured
  extents across dialogs. A source/derived-node checklist controls explicit loads,
  a top-bar indicator reports resident process memory, and explicit unload frees
  native resources while retaining compatible session observations.
- ParaView Workbench inspection shares resident data with spatial calculation.
  Blender extent loading also retains native objects between requests.
- Console data commands, the Python session API and trusted-local agent requests
  share the core service. Strict MCP preserves its planned-task boundary.
- The adaptor authoring prompt, rubric and open-work entry now require editable
  existing Names in the future node-by-node rollout. This is not that rollout.

## Verification

The focused host regression command passed **271 tests, with 9 skips**:

```sh
PYTHONPATH=src:tests/unit python3 -m unittest \
  test_live_data test_spatial_actions test_studio_server test_schemaxis_console \
  test_console_server test_console_references test_console_session_recovery \
  test_paraview_live test_blender_live test_expressions test_schemaxis_pipeline \
  test_execution_service -q
```

The final browser/model command passed **30 tests**. The native browser test was
run with an explicitly configured ParaView installation:

```sh
node --test \
  src/schemaxis/studio_ui/tests/spatial-live-data.browser.test.mjs \
  src/schemaxis/studio_ui/tests/live-data.browser.test.mjs \
  src/schemaxis/studio_ui/tests/volume.browser.test.mjs \
  src/schemaxis/studio_ui/tests/volume-model.test.mjs \
  src/schemaxis/studio_ui/tests/spatial-stage2.test.mjs \
  src/schemaxis/studio_ui/tests/spatial.browser.test.mjs
```

Earlier spatial Stage 2/3 browser regression coverage also passed (21 browser
tests in that run). The new browser test verifies deferred saving, automatic and
manual Names, consumer-preserving rename, retained data across windows, the memory
indicator, native handle reuse and explicit unload. The selection screenshot was
visually inspected.

Bounded serial native checks passed with ParaView 5.13.3 and Blender 5.2.3:

- ParaView wavelet then surface: same process; only surface created/updated.
- A real VTK PolyData file reader then surface: same process and reader reused;
  dataExtents matched the known triangle bounds. Adding a linked definition and
  unloading native data preserved compatible measured values.
- ParaView resident geometry inspection: same process, nonempty geometry and
  expected counts/bounds; source was not recreated or updated.
- Blender material/sphere then cube: same process; only cube created/updated;
  union bounds were independently checked.

Console list/status/eval/unload and CLI rename help were exercised. Packaged
Studio help was regenerated. `git diff --check` and `tools/release_gate.py` passed.
The full repository host suite and MPI were not run.

## Limits and separate gate

Measurements are session-only. External file changes require explicit unload and
reload. Memory is native-process RSS, not a mesh allocation measurement. Studio
currently previews the first visit; the core API accepts explicit visit indices.
Ordinary production run scheduling is not replaced by Live Data.

A separate MCP regression run had two failures and six errors because the strict
file-admission snapshot no longer matches current route contracts. It refused
execution with MCP_POLICY_DENIED as designed. That review snapshot was not
refreshed. Focused tests confirm that new native Live Data actions remain denied
in strict MCP and are available through the trusted-local service.

## Follow-up: automatic resolution and explicit refresh

Spatial and New volume now resolve missing bounds from already resident sources
by default. The `spatial.autoRefresh` Studio setting permits calculations on
request instead. Core `LiveDataSession.refresh` and the `live_data_refresh`
service action build needed derived nodes without enabling unselected sources.
Refresh reuses memory and does not reread input files. Console `data refresh`
uses the same implementation; `data eval` resolves missing bounds automatically,
with `--cached` for measurement-only evaluation.

Both Studio Live Data entry points open the checklist, including for a single
source. The workbench's older immediate inspection action is separately labelled
**Inspect selected node**. Already-loaded selections disable Enable; refresh
controls explain their operation and are disabled when Live Data is off. Input
inspection retains authored reference identities for shared measurement caching.

New verification for this follow-up:

- 107 focused host tests completed successfully, with 6 native qualification
  tests skipped: `test_live_data`, `test_studio_server`, `test_schemaxis_console`,
  `test_console_server`, `test_paraview_live`, `test_execution_service`.
- 27 browser/model checks passed across `spatial-live-data.browser.test.mjs`,
  `live-data.browser.test.mjs`, `spatial-stage2.test.mjs` and
  `volume.browser.test.mjs`, with the ParaView tests enabled.
- All 16 Stage 2/3 browser regressions passed in the additional combined run.
- The bounded ParaView check verifies automatic derived-volume resolution,
  manual-refresh preference, unchanged native process identity, no source
  updates when only derived nodes are created, unselected sources remaining
  unloaded, values surviving reopening, and cached values surviving unload.
- Settings persistence, strict MCP refusal of `live_data_refresh`, console
  dispatch and trusted-local service dispatch were checked.

These checks extend the earlier receipts; they do not claim full-repository,
MPI or additional Blender qualification for this follow-up.
