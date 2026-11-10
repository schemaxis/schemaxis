# Graphviz retained-evidence boundary — 24 October 2026

Scope: host-side strengthening of reopening/verification of retained Graphviz runs.
No native mapping, option, format or absorbed version changed; `schemaxis.graphviz/1`
authoring is unchanged and genuine 16.1.0 receipts verify as before.

Problems reproduced before repair, using a stand-in `dot` that replays the checked-in
baseline plain/SVG fixtures (host lifecycle only; it is not native evidence):

1. A deeply nested `verification.json`, `plan.json`, `layout.json` or
   `*-submission.json` made verification raise an unstructured `RecursionError`.
2. Retained `version.stderr` text that was not a Graphviz version line reported
   `UNSUPPORTED_NATIVE_VERSION`, conflating malformed evidence with an unsupported release.

Repair: bounded JSON reads convert over-nesting to `VERIFICATION_FAILED` at the file's
location, verification also guards `RecursionError`, and reopening classifies a
malformed identity as `VERIFICATION_FAILED` while a well-formed other Graphviz version
stays `UNSUPPORTED_NATIVE_VERSION`. Running with a non-16.1.0 executable still fails
before layout. Hostile SVG/plain, DOT, launcher, membership and warning checks were
already structured and were not weakened.

| Checklist ID | Result |
| --- | --- |
| registration, schema, semantics | Unchanged. Authoring probes (extra keys, labels, IDs, endpoints, cycles) already gave structured faults. |
| native-mapping, execution | Unchanged. No native API mapping added. Native not run: no Graphviz executable was available. |
| tests | New `tests/unit/test_graphviz_allocation.py`: 4 of its 5 tests failed before repair (4 failing and 12 erroring subtests) and all pass after; with `test_graphviz.py`, 14 tests pass. |
| guidance, help, examples | Guidance audit: 14 reviewed, 0 pending, 0 stale. Recovery text in the guide now separates malformed from unsupported evidence. Examples unchanged. |
| qualification | Not refreshed; native qualification is unavailable for this change and the existing receipt is not relabelled. |
| maintenance | Official stable source listing still shows 16.1.0, equal to `absorbedVersion`; unchanged. |

Known limit: the shared runtime opens a run's `result.json` before the adaptor, and
its `is_common` helper does not catch `RecursionError`, so an over-nested
`result.json` is not yet a structured fault. This belongs to shared code and is
reported to the integrator rather than fixed in this adaptor.

Not changed: labels with trailing or doubled spaces, and duplicate visible labels on
different IDs, remain accepted so legacy inputs keep verifying. Tightening that would
need a versioned migration decision.

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_graphviz_allocation tests.unit.test_graphviz -q
PYTHONPATH=src python3 tools/studio_guidance.py --app graphviz --check
```
