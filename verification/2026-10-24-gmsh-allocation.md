# Gmsh native-boundary faults — 2026-10-24

Scope: `schemaxis.gmsh/1`. Failures raised inside the isolated Gmsh worker were all
reported as `NATIVE_EXECUTION_FAILED` with no location or recovery, so a missing
module, an unsupported Gmsh version, a bad STEP, a bad face selector and a size
limit were indistinguishable. No meshing behaviour, native mapping, supported
format or absorbed version changed.

## Change

- The worker raises deliberate refusals with stable codes, a location (for example
  the source file option or the `faceGroups` entry), observed values and recovery:
  `NATIVE_UNAVAILABLE`, `UNSUPPORTED_RUNTIME`, `UNSUPPORTED_RESOURCE`,
  `INVALID_RESOURCE`, `INVALID_SELECTION`, `RESOURCE_LIMIT`. Other exceptions stay
  `NATIVE_EXECUTION_FAILED`, now with the exception type and recovery.
- The host rebuilds the fault from `native-fault.json` only for allow-listed codes
  with plain-text fields; a forged, empty or malformed file becomes
  `NATIVE_EXECUTION_FAILED`. Messages are unchanged.
- Failed runs still record a failed `result.json` and publish nothing; verification
  of retained runs is untouched, so existing receipts are unaffected.

## Checklist

| Item | Result |
| --- | --- |
| registration, schema, semantics | Unchanged; authored input and planning are not altered. |
| native-mapping | None added. |
| execution | Real `native.py` run in a subprocess against a stub `gmsh` module (host-only; not native evidence). |
| discovery | Not applicable: no operation or vocabulary change. |
| guidance, help | Four pitfalls now name the codes; guidance audit 0 pending, 0 stale. Generated reference/Help not regenerated here. |
| examples | Unchanged. |
| tests | `tests/unit/test_gmsh_allocation.py` (8 cases): each code, generic fallback, forged files, no publication. Before the repair 6 of 8 failed; after, all pass with the existing Gmsh host tests. |
| qualification | Native unavailable: no runtime was run, so this change is unqualified natively. `tools/qualify_gmsh.py` now expects the new codes for its multi-solid and face-selector refusals; the stored receipt predates this source and is stale for it. |
| maintenance | Latest upstream release observed as 4.15.2, equal to the absorbed version. |

## Limits

A native STEP read failure and a mesh-generation failure remain
`NATIVE_EXECUTION_FAILED` because their native exception types were not exercised.
