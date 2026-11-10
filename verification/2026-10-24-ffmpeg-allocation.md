# FFmpeg existing-video source boundary allocation

Scope: `encodeVideo` source handling in `schemaxis.ffmpeg/1`. Host-only repair; no
new native mapping, format or option. Review date: 24 October 2026.

## Problem reproduced before repair

With a failing FFmpeg stand-in (no native runtime needed):

- Empty, text, PNG-as-`.mp4`, Matroska bytes named `.mp4` and MP4 bytes named `.mkv`
  sources were captured and FFprobe was launched; every case surfaced the same
  generic `RUNNER_FAILED`, indistinguishable from a crashed or unavailable runtime
  and with no recovery.
- A source with more than 600 decoded frames was `UNSUPPORTED_VIDEO` with the same
  message as a zero-frame source, although the 600-frame bound is documented with
  the other source resource limits and `RESOURCE_LIMIT` ("requires a smaller
  source") is already used for the RGB bound.

## Repair

- `video.check_source` runs on the captured bytes before any native stage. Empty or
  unrecognised bytes: `INVALID_RESOURCE` (malformed). A recognised Matroska/MP4
  container under the other extension: `UNSUPPORTED_VIDEO`. Both carry
  declared/detected/byte observations and a recovery string. Matching signatures
  proceed to the unchanged native probe; native failure stays `RUNNER_FAILED`.
  The check reads only the leading signature and proves nothing about decodability.
- More than 600 decoded frames: `RESOURCE_LIMIT` with recovery; zero frames stays
  `UNSUPPORTED_VIDEO`.
- Offline `verify()` is unchanged, so genuine retained receipts continue to verify;
  native source-stage input bindings already bind the bytes that were decoded.

## Checklist

| Item | Result |
| --- | --- |
| registration, schema | Unchanged routes and declarations. |
| semantics | Source type and length faults separated into malformed, unsupported and resource-limit; recovery added. |
| native-mapping | No change; no new native API mapping. |
| execution | Gate precedes capture-bound native stages; legacy verification untouched. Native execution not re-run. |
| discovery | No change; no new terms warranted. |
| guidance | `file` explanation updated; audit 27 reviewed, 16 from references, 0 pending, 0 stale. |
| help | `docs/ffmpeg.md` and readiness recovery text updated; root regeneration of references/Help is still required. |
| examples | Existing examples unchanged; the retained `ffmpeg-video-source.mkv` fixture passes the gate. |
| tests | `tests/unit/test_ffmpeg_allocation.py`: 6 tests, 10 failures/1 error before repair, all pass after. Also `test_ffmpeg_video_input.py` (8) and `test_media_geospatial.py` (30, one native skip) pass. Planning also passes under `python3 -S`. |
| qualification | **Native unqualified for this change.** The retained FFmpeg launcher cannot load its libraries and no other runtime was available. The existing registered receipt is not refreshed and becomes stale if the shared source freeze demands it. |
| maintenance | Official release index (ffmpeg.org/releases) checked 24 October 2026: latest tarball 9.0.2, equal to `absorbedVersion`, which is unchanged. |

## Not done

- `assess_deliverable` next-action text still refers to PNGs and sprite durations
  when an `encodeVideo` deliverable is unmet. Changing it alters receipt content and
  needs an exact legacy-text acceptance path; proposed for a later allocation.
- Native acceptance of a real wrong-container file on a current FFmpeg.

[FFmpeg releases](https://ffmpeg.org/download.html#releases) and the
[FFprobe documentation](https://ffmpeg.org/ffprobe.html) remain the version and
command basis.
