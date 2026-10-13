# Existing-adaptor migration acceptance

All **ten adaptors / twelve document routes** now satisfy the development delivery
contract and common host conformance. All **755 declared operation identifiers**
have selection guidance. ParaView is the largest with **655 identifiers**, followed
by Blender with 37. Identifiers include overlapping native/curated interfaces;
these counts are not independent algorithms or exhaustive native qualification.

The spelling migration is recorded separately in
[consistent adaptor naming](2026-09-28-adaptor-spelling.md). Project-owned names,
paths, classes, manifests and result keys now use adaptor. An external Godot API
call touched by that rename was restored to the spelling required by Godot; native
execution caught the error, and fresh Godot conformance and agent execution pass.

## Delivery and behavioural changes

- Added full route bundles for ParaView, Blender geometry and saved-scene rendering,
  Calc, Godot, Aseprite, QGIS and an experimental case-preparation route. Every route declares use
  cases, assumptions, limitations/recovery, public API basis, lifecycle, artifact
  traits/losses, inspection, authoring, optional features and acceptance cases.
- Added complete operation purpose maps. ParaView retains **594 native identity
  documentation records**, with explicit native-text provenance or reviewed scope
  where help is absent. Curated wrappers reuse the relevant native help. The
  installed public metadata capture was reproduced exactly; no native filters were
  executed to extract documentation. The bundled ParaView licence is retained.
- Replaced the ParaView context example's unresolved time selection with a clear
  host-plannable single-time example. Real CFD execution still requires actual
  case data and inspected time/array availability; no planner check was weakened.
- Added editable examples, independent baseline/variant expectations and a small
  self-contained Blender scene fixture. Its provenance and regeneration procedure
  are documented beside the binary; its bytes participate in receipt freshness.
- ParaView verification now checks retained authored input against the executed
  graph. ParaView, Blender and Aseprite missing/corrupt evidence faults are structured.
  Blender and ParaView expose observed interpreter identity.
- Added catalogue-wide host/native qualification and published-context clients.
  Missing runtimes and failed checks remain failures, never successful skips.

## Fresh native acceptance

**Eleven routes, 22 cases, 216 missing/tampered evidence checks and 22 lifecycle
checks passed.** All eleven registered receipts are source-current. The previously
qualified pilot routes were rerun after the spelling migration; no old digest was
edited to make it appear current.

| Route / recorded runtime | Independent case scope |
| --- | --- |
| ParaView / 5.13.3 | Five-point analytic line; endpoints produce x bounds [-1,1] then [-1,3]; native geometry readback |
| Blender / 5.2.2 | Cubes of side 2 and 3, signed volumes 8 and 27; native scene save/reopen |
| Blender saved scene / 5.2.2 | Persisted cube bounds, nonempty native render/decode at 32×32 then 48×32; geometry unchanged |
| Calc / LibreOffice 26.8.0.3 | Numeric table y = 2,4,6 then 3,6,9; independent workbook formula/cache and CSV round trips |
| Godot / 4.7.2 stable | Analytic box bounds for sizes 2×2×2 and 4×2×2; fresh scene readback |
| Aseprite / 1.3.17.2 | 4×4 red then blue canvas; exact independent RGBA pixel expectations and native layer/frame/sheet verification |
| QGIS / 3.34.4 Prizren | Reproject two known points to EPSG:3857, then clip to retain only the west point; count/CRS and native reopen |
| Octave / 11.3.0 | Analytic derivative 2 then 3 |
| FreeCAD solids / 1.1.3 build 20260725 | Analytic box volumes 1000 then 1500 mm³ and reopened publications |
| FreeCAD assemblies / same build | Three fixed joints, one ground, thickness 5 then 7 mm and saved assembly checks |
| FFmpeg / 6.1.1-3ubuntu5 | Exact decoded 2×2 RGB at 25 then 12 fps, FFV1 |

Aseprite's first integrity probe exposed an unstructured missing-publication error.
Its verifier now preserves the structured failure contract; the repaired run passed
both cases and all publication/evidence/lifecycle checks. Original failed probes
remain under `evidence/adaptor-migration/` alongside the corrected runs.

The experimental case-preparation route, since moved to a separately installed
package, passed host fixtures and public source/property authoring only. Its
isolated native attempt failed with **INTERPRETER_NOT_FOUND** because no launcher
was configured; no native receipt was registered.

## Public context and reuse

`tools/qualify_migrated_context.py` uses only published materials and the public
JSON-lines service: context → source draft → property patch → plan → execute →
verify → bounded publication access. It completed **14 native executions** across
seven newly qualified routes, plus two case-preparation host plans and exact invalid-case
rejection for all eight migrated routes. Saved-scene rendering exercises the
non-node model. The client made 465 requests / 368,910 response bytes; 85 context
requests transferred 93,243 bytes through 16 exact member walks.

This client validates the procedure and digest-checked access to actual artifacts.
Independent numerical/pixel/geometry expectations are checked by the native kit
above; a binary byte sample is not represented as semantic geometry inspection.
The evaluation is deterministic, not a test of an autonomous language model.

## Verification and reproduction

**751 unit tests passed, 22 skipped**, 186.332 seconds. Both capability-protocol
tests passed (53.167 seconds), all 47 generated references passed, and the
whole-catalogue development admission gate passed. Logs: `evidence/adaptor-migration/final-unit.log`, `capability-protocol.log`,
`reference-check.json` and `readiness.json`. The host qualification tool retains
one successful receipt per route under `evidence/adaptor-migration/host/`.

```sh
PYTHONPATH=src python3 -m schemaxis readiness --admission --check
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --output-directory evidence/recheck-host
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --native --app paraview \
  --output-directory evidence/recheck-paraview
PYTHONPATH=src python3 tools/qualify_migrated_context.py \
  --config /path/to/private-config.json --output-directory evidence/recheck-context
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m schemaxis reference --check
```

All tools use fresh output directories. Configure actual runtimes privately; no
user PATH/configuration or licences were changed. Public upstream absorbed versions
remain unchanged. These are bounded serial fixtures on observed runtimes, not claims
about latest releases, every native operation, live editing, all conversions, GPUs
or MPI. The [current audit](../docs/design/adaptor-framework/AUDIT.md) lists the
source-bound receipts and remaining limits. The project can resume adaptor growth.
