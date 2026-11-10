# Cantera native fault classification (2026-10-24)

Scope: route `schemaxis.cantera/1`, run boundary only. A Python that cannot import
Cantera, or whose Cantera is not 3.2.x, was reported as `NATIVE_EXECUTION_FAILED`
with no recovery text, the same code as a real native or numerical failure. The
host also accepted whatever code a worker fault record named. No operation, schema,
native mapping, file format, tolerance or plan changed. Other operations are not
re-reviewed.

## Change

- `NATIVE_UNAVAILABLE`: the configured Python cannot import Cantera.
- `UNSUPPORTED_RUNTIME`: Cantera is present but not 3.2.x; `observed.version` names it.
- `NATIVE_EXECUTION_FAILED` and `UNSUPPORTED_STATE` keep their meaning, including a
  mechanism hash mismatch.
- The host accepts only these codes from `native-fault.json`. A malformed record or
  another code becomes `NATIVE_EXECUTION_FAILED`. Every native fault has recovery text.
- `verify` is unchanged: existing receipts still verify offline, and a receipt from
  another Cantera release still fails `VERIFICATION_FAILED`.

## Evidence

- Before: a Python without Cantera gave `NATIVE_EXECUTION_FAILED`, no recovery
  (`tests/unit/test_cantera_allocation.py`: 2 failures, 2 errors on 5 tests).
- After: the same tests pass. They run the real worker through the isolated runner
  with stand-in `cantera` modules (absent, 3.1.1, broken import) and validate the
  record handling directly.
- `PYTHONPATH=src python3 -m unittest tests.unit.test_cantera_allocation tests.unit.test_cantera_admission tests.unit.test_cantera_reactor`: 35 tests OK.
- `tools/studio_guidance.py --app cantera --check`: 38 reviewed, 13 reference, 0 pending, 0 stale.
- Upstream: latest stable Cantera is v3.2.0 (GitHub `releases/latest`, published
  2025-11-18, checked 2026-10-24). `absorbedVersion` stays 3.2.0.

## Checklist

| ID | Result |
| --- | --- |
| registration | Unchanged routes; two fault codes added to the run boundary. |
| schema | Not applicable: no declaration changed. |
| semantics | Not applicable to planning. Fault records are validated before use. |
| native-mapping | No new mapping. Not applicable. |
| execution | Worker classification and host validation described above. |
| discovery | Not applicable: no operation or scope change. |
| guidance | Root pitfall names the three runtime faults; `--check` clean. |
| help | `docs/cantera.md` fault section and `readiness.json` recovery text updated. Generated reference and packaged Help need shared regeneration. |
| examples | Unchanged. |
| tests | `test_cantera_allocation.py` as above. |
| qualification | **Native unqualified for this change.** No Cantera runtime was available. The registered receipt predates the changed worker source and is stale. `qualification.json` was not edited. |
| maintenance | `absorbedVersion` unchanged. |

## Remaining gaps

Requalify natively with `tools/qualify_cantera.py` when a Cantera 3.2.x Python is
available. Shared reference and Help regeneration is pending. A Cantera import that
fails for a reason inside the library (for example a shared-library mismatch) is
reported as `NATIVE_UNAVAILABLE` with the import message.
