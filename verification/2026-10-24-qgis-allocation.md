# QGIS retained-evidence verification boundary

Scope: the offline `verify()` gate for a published QGIS output directory
(`result.gpkg`, `project.qgz`, optional preview, summary tables and receipts). This
is a host-only repair; no operation, native mapping, format or fixture changed.

**Defect reproduced first.** Valid JSON that was not an object in `result.json`,
`verification.json`, `sources.json`, `built.json` or `reopened.json`, a non-finite
number in a retained attribute row (`Infinity`) and deeply nested JSON escaped as raw
`AttributeError`, `OverflowError` or `RecursionError` rather than a structured fault.
Faults also lacked a location and recovery. A downstream workflow handoff therefore
could not tell a damaged receipt from an internal failure.

**Repair.** Every retained JSON receipt is read through one helper. Missing,
non-regular/symlinked, non-JSON and non-object files fail with the stable code
`VERIFICATION_FAILED`, the file name as location and a recovery instruction (restore
the complete original directory or rerun into a fresh one; verification never repairs
evidence). Other malformed retained content reaches the same code at location `$`.
Genuine receipts, check order and every comparison are unchanged, so legacy receipts
continue to verify; nothing was loosened.

| Checklist item | Result |
| --- | --- |
| registration, schema, semantics | Unchanged; no new routes, fields or options. |
| native-mapping | Unchanged; none added. |
| execution | Offline verification now reports malformed retained evidence structurally. A fresh native run was not possible. |
| discovery, guidance, help, examples | Unchanged behaviour; `docs/qgis.md` gained a short verification-fault note. |
| tests | `tests/unit/test_qgis_allocation.py` (4 tests) run against the unrepaired adaptor source: 17 failures and 5 errors (four raw `AttributeError` from non-object `result.json`, one `OverflowError` from `Infinity`, the rest missing file locations/recovery); all pass after repair. With `test_qgis_attributes`, `test_media_geospatial`, readiness and completion suites: 72 tests pass, 1 unrelated FFmpeg native prerequisite skipped. `readiness --app qgis --admission --check` passes. |
| qualification | **Native unqualified for this change.** The retained QGIS launcher cannot import its Qt bindings, so no QGIS ran. The adaptor source changed, so earlier native receipts are stale for the new source until re-registered. |
| maintenance | The official release page identified QGIS 4.2.3 as current on 24 October 2026, equal to the absorbed version. It was not advanced. |

Limits: the repair authenticates structure, not the geometry itself. Offline
verification still cannot detect a coordinated forgery of all native geometry
snapshots, as recorded in the 2026-10-17 attribute note.
