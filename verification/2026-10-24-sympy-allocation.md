# SymPy `isolateRealRoots` unavailable-runtime boundary (2026-10-24)

Scope: `schemaxis.sympy/1` only. No new native mapping, format or option; `absorbedVersion` (1.14.0) is unchanged.
Reviewed by the implementing worker; domain review by a person is still outstanding.

## Defect reproduced before repair

Running the route with an interpreter that starts but cannot import SymPy (a launcher using `python -S`) ended in the
shared generic `RUNNER_FAILED`: no SymPy fault code, no recovery text, and a fault location and stderr traceback that
embedded the run directory path. The worker imported SymPy outside its structured-refusal path, so "unavailable" was
indistinguishable from a native crash, although "unsupported release" and "malformed contract" were already distinct.
Native refusals other than the unsupported-release code were also re-raised with no recovery text.

## Repair

- The worker imports SymPy and mpmath under a handler and refuses with `SYMPY_RUNTIME_UNAVAILABLE` (location `$.runtime`,
  `compute-fault.json`, nothing published, `result.json` recorded as failed and unverified).
- The host accepts that code and gives every recognised native refusal an actionable recovery. A native
  invalid-contract or resource-limit refusal of input the host accepted is still `VERIFICATION_FAILED`; an unknown
  refusal code is still treated as malformed.
- The unsupported-release, unavailable and malformed states stay separate. Verification, certification and the
  published table contract are unchanged.
- Worker and adaptor bytes changed, so earlier retained run directories fail `verify` with the existing
  "implementation changed; rerun" fault, and the registered qualification receipt is stale until re-registered.

## Checks run (this session)

- `tests/unit/test_sympy_allocation.py`: 6 new host tests; 3 failed before the repair (generic `RUNNER_FAILED`, path
  in fault, recovery missing) and all pass after. `tests/unit/test_sympy.py`: 19 tests pass unchanged.
- Native, serial, SymPy 1.14.0 with mpmath 1.3.0 on Python 3.14.4 (the latest stable release observed from the official
  GitHub release API on 2026-10-24): `tools/qualify_sympy.py` passed twice without registration; 20 constructed cases,
  32 hostile saved-evidence mutants, refusals, lifecycle and the new unavailable-runtime case. This reruns the
  existing recipe; it adds no native behaviour and is scoped to this runtime and Linux.

## Checklist (changed scope only)

| ID | Result |
| --- | --- |
| semantics, execution | Unavailable runtime is a located structured fault before any computation; failure is recorded. |
| tests | New host tests plus a recipe case in `tools/qualify_sympy.py`. |
| help | `docs/sympy.md` fault table distinguishes unavailable, unsupported and invalid results with recovery. |
| native-mapping, discovery, guidance, examples, maintenance | Unchanged; no mapping or example change. |
| qualification | Receipt for the earlier worker bytes is stale; re-registration is left to the integration owner. |

## Unresolved

- Packaged Help and generated references were not regenerated.
- A SymPy that imports but fails inside the call still surfaces as the generic runner failure.
