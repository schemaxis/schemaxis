# Aseprite exported-evidence verification review — 24 October 2026

Scope: offline `verify()` of a retained run that has been exported to another
directory. No new operation, native mapping, format or option was added.

Defect: a verified run exported with the shared run-relocation contract (the copy's
`publication-metadata.json` records the producing origin) failed with
`VERIFICATION_FAILED: publication manifest differs`. The adaptor compared the
receipt's absolute publication paths with the selected directory instead of
mapping them through the shared owned-path rules used by other adaptors, so
documented export/offline-verification handoffs could not be verified even though
every digest and pixel was intact. Reproduced on a real run before any change.

Repair: `verify()` resolves each recorded publication with the shared `owned_path`
rules and still requires the exact four publications in order, their kinds and
SHA-256 digests. Hand copies without a recorded origin, recorded paths outside the
run, links, and altered names/kinds/digests/membership are rejected; the fault
carries recovery (verify the original directory or copy with `schemaxis export`).
A non-object `result.json` `sha256` now fails at location `result.json`. Receipts,
legacy procedural evidence, worker pinning, capture manifests and independent
pixel/composite checks are unchanged and never rewritten.

| Completion item | Result |
| --- | --- |
| registration, schema, semantics, native-mapping | Unchanged; no declaration, option or native mapping touched. |
| execution | Verification now accepts exported evidence through the recorded origin; all other evidence checks retained. |
| discovery, guidance, examples | Unchanged; no new user-facing operation or field. Existing examples were run natively below. |
| help | Local guide gains a short relocation section with the stable fault and recovery. Shared reference/Help regeneration belongs to the integrator. |
| tests | `tests/unit/test_aseprite_allocation.py`: nine host-only tests on synthetic evidence plus one native export test. Before repair four of the nine host tests failed on the original source (three errors, one test with four failing subtests); all pass after. Existing aseprite host tests pass. |
| qualification | Not re-qualified. The only local runtime is Aseprite 1.3.17.2, older than the absorbed 1.3.18.6, so native qualification is unavailable; no qualification receipt was produced or changed. Supplemental run on 1.3.17.2: 39 aseprite tests passed, including a real run, export and verification. |
| maintenance | Latest stable release observed as v1.3.18.6 (22 September 2026); `absorbedVersion` unchanged. |

Limits: hand-moved directories without a recorded origin remain unverifiable by
design; this is not a native reopen or an attestation against coordinated forgery.
