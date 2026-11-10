# SoX retained-evidence type strictness review

Route: `schemaxis.sox/1`, existing `assemble` operation. This review covers one
verifier repair. It adds no operation, native option, format or mapping and keeps
the SoX 14.4.2 command mapping, limits and legacy-summary acceptance unchanged.
Items not listed keep the [2026-10-17 review](2026-10-17-sox-completion.md) and the
[audio-preparation review](2026-10-24-sox-audio-preparation.md).

## Gap and repair

Reopening compared the retained `plan.json` and `captures.json` with Python `!=`,
so JSON types were loose. With ordinary digests and publication metadata refreshed,
these forgeries verified: a clip's `fadeInFrames` `0` as `false`, `gain` `1` as
`true`, `startFrame` `40` as `40.0`, and capture `bytes`, `info.rate` or
`info.channels` as a float or boolean. Both files now use the same type-preserving
comparison as the summary and result. Wrong values were already rejected and remain
so. `authored.json` and submission exit codes were already strict.

| Item | Result |
| --- | --- |
| semantics, tests | `tests/unit/test_sox_allocation.py`: eight type-forgery subcases failed before the repair and are rejected as `VERIFICATION_FAILED` after; an unchanged-evidence control and wrong-value probes pass. |
| execution | Genuine host-stub and native runs reopen unchanged. |
| native-mapping, qualification | No new mapping. Serial native run of the endpoint example with the observed SoX 14.4.2 build verified and reopened. This is a bounded smoke check, not a re-run of `tools/qualify_sox.py`; the existing qualification receipt is not refreshed here. |
| maintenance | SoX 14.4.2 is the latest release on the official SourceForge list on 24 October 2026; `absorbedVersion` is unchanged. |
| discovery, guidance, help, examples | No operation or field changed. `docs/sox.md` states the stricter evidence contract. Shared reference/Help were not regenerated. |

## Remaining limit

Legacy eight-field summaries remain accepted with their smaller recomputed claim
set. Stripping timeline fields can remove claims, never add unchecked ones. A
consumer requiring a segment map must require those fields; distinguishing the
original historical form would need external trusted provenance and is outside
this change. Receipt signing is not required for the current correctness checks.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_sox*.py'
```

Result: 21 tests passed.
