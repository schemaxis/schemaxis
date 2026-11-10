# PrusaSlicer stage-gating review (2026-10-24)

Scope: existing route `schemaxis.prusaslicer/1`, operation `sliceModel`. One
host-only repair to native stage ordering. No new native mapping, format or
option; `absorbedVersion` is unchanged.

## Problem

`run()` launched all four native stages (version, info, slice, reopen) and only
then compared the `--help` identity and the `--info` readback with the supported
runtime and the independent STL analysis. An executable that was not PrusaSlicer
2.9.6, or whose reader disagreed with the host analysis, was still asked to slice.
The user saw `NATIVE_EXECUTION_FAILED` ("produced no G-code") instead of the
stable `UNSUPPORTED_RUNTIME` or `VERIFICATION_FAILED` fault.

Reproduced before the repair with fake console executables
(`tests/unit/test_prusaslicer_allocation.py`): three of four tests failed, each
ending in `NATIVE_EXECUTION_FAILED` from the slice stage; the matching-runtime
control passed.

## Change

- The runtime identity is checked right after `version`, and the native model
  readback right after `info`, before `slice`.
- The two faults carry `stage` (`version`, `info`); the `UNSUPPORTED_RUNTIME`
  recovery states that no slice was attempted.
- `checked()` and `verify` repeat both checks from retained bytes, so retained
  evidence verification is unchanged and nothing is weakened.
- A refused attempt keeps its `failed` `result.json` with the fault and the logs
  of the stages that ran, and publishes no G-code.

## Checklist results

| ID | Result |
| --- | --- |
| registration | Unchanged. |
| schema | Unchanged; no declaration changed. |
| semantics | Changed: runtime and native-readback checks gate the slice. |
| native-mapping | Not applicable: no native mapping added or altered. |
| execution | Changed: stage ordering and fault location; verification replay unchanged. |
| discovery | Not applicable: no operation or purpose changed. |
| guidance | Not applicable: no field changed. |
| help | The local guide's fault table and stage-order note are updated. Shared generated Help is not regenerated here. |
| examples | Unchanged. |
| tests | Four host tests with fake executables, plus the existing 16. |
| qualification | **Not native-qualified by this change.** No PrusaSlicer runtime was available. |
| maintenance | Latest stable observed on the upstream release API: 2.9.6, published 2026-06-25, matching `absorbedVersion`. |

## Checks run

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_prusaslicer_allocation tests.unit.test_prusaslicer -v
```

Result: 21 tests, 20 passed, 1 skipped (the native-gated test).

## Limits and remaining gaps

- The fake executables prove stage ordering and fault codes only. The earlier
  2026-10-16 native receipt predates this change and is stale for the current
  source; the route needs a fresh native run on a PrusaSlicer 2.9.6 console.
- Draft/human-review limits are unchanged: the G-code is untested on any
  printer, firmware or material, and no print quality or safety claim is made.
- Candidate for later: truncated or trailing-byte binary STL files whose 80-byte
  header begins with `solid` currently report "ASCII STL must contain only ASCII
  text"; a clearer malformed-binary diagnostic would help.
