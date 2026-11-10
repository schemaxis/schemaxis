# pyproj routeStations numeric-range boundary — 24 October 2026

Scope: `schemaxis.pyproj/1` planning only. An authored `spacing_m`, `requirements.totalLength_m.minimum`,
`requirements.totalLength_m.maximum` or `requirements.endpointGap_m.maximum` given as a JSON integer too
large for binary64 raised an unstructured `OverflowError` during planning (and so in `query`,
`reusableInputs`, `retainedInputs` and `run`). It is now refused as `INVALID_ARGUMENT` at the exact field
location with a recovery that states the field's range, before any file access or native work.

## Result against the completion checklist

| Item | Result |
|---|---|
| registration, schema | Unchanged: no declaration, route, schema or publication change. |
| semantics | Added `binary64_screen` in `contract.py`; ordinary values, booleans, NaN/infinity and out-of-range finite numbers keep their earlier faults. |
| native-mapping, execution | No native change: no new mapping, domain, publication or verification rule. |
| discovery, guidance | Unchanged; no new operation, field or meaning. |
| help | `docs/pyproj.md` fault table names the new case. Generated reference and Help are unaffected (no declaration change). |
| examples | Unchanged examples still plan. |
| tests | `tests/unit/test_pyproj_allocation.py` (4 tests): each of the four locations with a positive and negative huge integer, every planning entry point, `run` creates no output, and unchanged ordinary behaviour. Failed with 12 `OverflowError` errors before the repair; passes after. With `test_pyproj.py`, 29 host tests pass. |
| qualification | **Native unavailable here and unqualified for this source revision.** No pyproj runtime was available, so no native run was made. The host change alters `contract.py`, which is part of the recorded implementation fingerprint, so existing source-bound receipts need re-registration by a fresh bounded native run. |
| maintenance | PyPI latest stable pyproj is 3.8.0, the absorbed version; `absorbedVersion` is unchanged. |

## Observed, not changed

- Shared `core/declarations.py` `_finite_number` calls `math.isfinite` on unbounded integers; any other
  adaptor with a numeric option has the same crash. The pyproj screen is an adaptor-owned boundary, not a
  substitute for fixing the shared function.
- A huge-integer document `version` raises `ValueError` in the shared registry.
- Waypoint decimals that underflow to zero and duplicate waypoint names are accepted; no refusal was
  added.
