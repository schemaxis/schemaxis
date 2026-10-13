# Typed inspection acceptance — 2026-09-27

M3's second production slice adds text/table/series evidence and trusted workspace
presets to the shared console and agent service. It builds on shared authoring
`1830203`. [Usage](../docs/typed-inspection.md) · [Native evidence](2026-09-27-typed-inspection.json)

## Changed behaviour

- Immutable UTF-8/CSV snapshots carry resource/revision identities, content
  digests, provenance and explicit unknown units. Verified job publications can
  be captured with their producer and receipt links.
- Text spans, table ranges, series intervals and existing native/image picks use
  a common typed envelope, retaining distinct payload meanings. They are historical
  evidence, not replayable authored selectors. Old snapshot selections remain
  inspectable after replacement and are rejected for new current context.
- The console offers Geometry study, Text inspection and Tables and signals.
  Source/history, references and context remain shared. Presentation is stored
  separately from authored document and task state.
- Views and agent replies are bounded. Table values remain strings; plotting
  requires explicit finite numeric columns and strictly increasing x.
- New snapshot inspection lives in `resource_inspection.py`; the existing native
  node inspector remains intact in `inspection.py`.

## Host checks

Final full suite: **703 tests run, 22 skipped, no failures/errors**, 156.151 s.
Log: `evidence/inspection-2026-09-27/unit-final.log`.

The 18 new inspection tests cover exact Unicode/CRLF coordinates, immutable recovery,
stale selections, distinct native/text envelopes, quoted/empty CSV cells, numeric
mapping faults, bounds, blob tampering, response budgets, complete headers,
invalid-source/history/plan preservation through layout changes, console/agent
handover, synthetic labels, explicit recapture and uncertain atomic publication.
They also exercise browser UTF-16/normalised-newline offsets and existing native
inspection dispatch. Execution-service tests cover verified publication provenance,
historical retention after external tampering, and closed service ownership.

The existing fresh-interpreter native-import/process guard now includes CSV capture,
series inspection and workspace switching. JavaScript syntax checks pass for the
changed modules. Public `discover` and all 46 generated-reference checks pass.
An initial full run exposed two stale generated-index assertions; regeneration
resolved that drift before the final run.

## Native numerical acceptance

`tools/qualify_inspection.py` used only public agent subprocess requests:

1. Plan and execute one GNU Octave sequence with five samples, scaled by two.
2. Reverify the job and capture `scaled.csv` as a digest-checked snapshot.
3. Inspect explicit x/y columns: `(0,0), (1,2), (2,4), (3,6), (4,8)`.
4. Retain rows `[1,4)` as a series interval and inspect the exact selected points
   `(1,2), (2,4), (3,6)`, with producer/receipt provenance and unknown units.
5. Switch all three workspace presets and confirm the completed job stays verified.

Native GNU Octave **11.3.0** verified one table and two artifacts. The retained
report records the exact request count and response sizes (poll counts can vary).
This is one serial native case, not extraction qualification, MPI coverage or a
model-provider evaluation. The final report is copied from
`evidence/inspection-2026-09-27/native-final/report.json`.

## Browser checks

The actual loopback console was exercised with the labelled synthetic fixtures:

- Text selection produced a typed chip and exact retained text evidence; saving
  context persisted the reference locally without executing anything.
- Table cells/ranges and explicit numeric column mapping use the shared composer.
  A selected sample interval returned the exact expected values and unknown units.
- Preset switches preserved existing reference chips and authored document identity.
  Refresh after adding a reference preserved the current plot and manual range.
- Retained invalid JSON at revision 2 survived a preset switch with its undo
  group intact. Undo restored valid source at revision 3; snapshot chips stayed current.
- A visual check covered the desktop text/table/plot layout; no narrow/mobile
  acceptance is claimed.

## Boundaries and next work

Extraction stages await the supplied tool contract and representative records.
Workflow graph editing, diagram semantics, reusable authored selectors, YAML input,
custom panel layouts and broader provider/model evaluation remain open. The UI
shows at most 100 resource descriptors and the first 16 CSV columns per table
page; explicit ranges/axes and the agent API can address other columns. Views are
read-only apart from annotations. Only preset/resource focus is durable presentation;
page and plot choices remain transient.
