# Shotcut result membership and source-range boundary review

Route: `schemaxis.shotcut/1`, existing `editTimeline` operation. This review covers
two verifier/runner repairs. It adds no operation, native option, format or mapping.
`absorbedVersion` 26.9.27 is unchanged and was the latest official release on the
GitHub release API on 24 October 2026. Items not listed keep the
[2026-10-10 qualification](2026-10-10-shotcut.json).

## Gaps and repairs

1. Reopening checked only that `result.json` said `succeeded` and verified. With
   every other file intact, a result whose `video`, `project` or `projectBundle`
   pointed elsewhere (or was swapped, missing or non-string) or whose `artifacts`
   count was wrong still verified. The result now must equal the three
   publications of its own run directory, with exact JSON types and no fault keys.
   Genuine runs write exactly that result, so they reopen unchanged.
2. A clip beyond the real source frame count was found only after every asset had
   been natively decoded, with no asset or frame count in the fault. It now fails as
   `INVALID_RANGE` after that asset's probe, before any decode or render, with the
   asset, clip location, requested end and `sourceFrames` observed. The reopen-time
   check remains and carries the same details.

| Item | Result |
| --- | --- |
| semantics, tests | `tests/unit/test_shotcut_allocation.py`: before the repair 7 result-membership subcases failed and the range case failed (launched decode stages, no details); after it all pass. Unchanged-run, unfinished-result (`INCOMPLETE_EXECUTION`) and end-equal-to-source controls pass. A deterministic fake melt/ffmpeg/ffprobe drives the real runner and verifier. |
| execution, qualification | **Native unqualified for this change.** No Shotcut `melt` runtime was available, so no native run was made and `qualification.json` and `tools/qualify_shotcut.py` are untouched. The 2026-10-10 native receipt applies to the earlier source only. |
| native-mapping | No new mapping; fake tools verify host logic only and are not evidence of Shotcut behaviour. |
| maintenance | Latest stable release observed as v26.9.27; not advanced. |
| discovery, guidance, help, examples | No operation or field changed. `docs/shotcut.md` and the route recovery text state the stricter contract. Shared reference/Help were not regenerated. |

## Remaining limits

Run directories remain bound to their absolute path through retained commands, so a
relocated directory does not reopen; only the extracted project and media are
portable. GUI editing, audio, transitions and multiple tracks remain unsupported.
Native requalification with the current portable `melt` is the next action.

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_shotcut tests.unit.test_shotcut_allocation
```

Result: 15 tests passed.
