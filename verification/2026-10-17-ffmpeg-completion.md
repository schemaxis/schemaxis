# FFmpeg existing-video completion review

`encodeVideo` now captures a bounded existing clip, selects a zero-based inclusive
start / exclusive end presentation-frame range, and retimes every selected frame
at the declared output fps. It complements the existing PNG and sprite-sheet
publication routes; multi-clip editing remains Shotcut's scope.

Owner: C FFmpeg worker, Codex Sol. Review date: 17 October 2026. The active
checkout was `main`; existing work was preserved. No shared framework, licence,
installation, PATH or neighbouring repository changes were made by this worker.

| Checklist | Review and retained evidence |
| --- | --- |
| registration | Existing route/runtime, new encodeVideo declaration; accepted video artifact handoff. No audio or timeline-editor claims. Readiness admission passes after root-generated Help. |
| schema | Typed absolute .mp4/.mkv file, startFrame default 0 inclusive, required endFrame exclusive, bounded fps/codec/threads. Schema/parser parity, typed defaults, immutable planning, unknown options and invalid ranges tested. |
| semantics | Entire source validated before selection: exactly one progressive video stream, allowed codec/pixel format/container, fixed dimensions, square/unspecified aspect, no rotation/stream side data, integer uniform zero-origin presentation timestamps. Whole source <=600 frames, 32 MiB input, 192 MiB RGB, 4096 px per side. Native multi-stream and timestamp-offset sources rejected. |
| native-mapping | Fixed public FFmpeg/FFprobe CLI recipes, local file protocol and fixed demuxers only. Default MP4 edit-list presentation honoured identically by probe/decode; explicit noautorotate and metadata rejection. Native stream-copy trim includes an actual `elst` atom and independently matches source presentation indices 2–5. No authored arbitrary native options. |
| execution | Compressed bytes captured before native use; scheduler fingerprints invalidate on changed bytes. Source and output probe/decode launchers bind consumed digests, commands and observations. Every selected output RGB channel compared, source selections rebuilt offline. Shared total deadline/owned cancellation; source POSIX caps 2 GiB address space and bounded output files. Common execution automatically retains shared schema references. |
| discovery | Curated trim-video/existing-clip/frame-range cases, ambiguous encode and negative mix-audio assertions on capability, adaptor selection, Add and Help surfaces. Actual CLI search finds encodeVideo. Production Studio search suite: 76 passed. |
| guidance | Operation and every new literal-schema address reviewed: 27 reviewed, 16 attributed, 0 pending, 0 stale. Explains presentation indices, exclusive end, source bounds, output speed change, defaults, codecs/losses and recovery. |
| help | New docs/ffmpeg.md, contextual operation/field guidance and root-generated references/Help. INVALID_FRAME_RANGE, UNSUPPORTED_VIDEO, RESOURCE_LIMIT and verification recovery documented. Official sources reviewed deliberately; ordinary admission stays offline. |
| examples | Editable baseline/range-rate variant/invalid documents, Studio starter/snippet, deterministic six-frame 32x24 FFV1 fixture (1,677 bytes), literal channel generator. Source placeholder remains honest until bound. Native acceptance also exercises two substantial 72-frame 128x72 clips. |
| tests | Eight new unit tests passed; existing media/geospatial suite: 30 tests, one existing skip. Host conformance and the two current authored/expanded repository corpus tests passed. Python -S planning passes without optional packages. Native qualifier and existing FFmpeg deliverable qualifier pass; detailed scope below. |
| qualification | Fresh source-bound receipt is registered only after the root's shared-source freeze. Earlier records become stale when source changes; tool receipts alone do not establish source freshness. Final receipt status is recorded below. |
| maintenance | Official download page checked 17 October 2026: latest stable 9.0.2, released 18 September 2026. Exact archive signature verified against official fingerprint; isolated gcc13/static-x264 minimal FFmpeg/FFprobe build. Absorbed version remains 9.0.2; acceptance recipe and evidence updated. |

The source protocol does not support native inspection, MPI, native time batching,
live editing or native console Save As; existing explicit unsupported decisions
and reasons are retained. File/resource fields still use normal workflow binding,
composition, planning and schema-storage routes.

Native acceptance on FFmpeg 9.0.2 passed:

- A 72-frame 128x72 FFV1 source at 24 fps: frames [12,60) produce 48 frames at
  12 fps (4 seconds); changed [24,72) produces 48 frames at 24 fps (2 seconds).
- Six-frame 32x24 FFV1 input: [1,4) baseline, [2,6) range/rate variant and a
  changed literal source; H.264 input; actual MP4 edit-list presentation; H.264
  output. Every original source and selected output frame is independently decoded
  and compared by channel: 6,757,632 RGB channel comparisons across eight cases.
- All selected FFV1 outputs are byte-exact against independently decoded source
  frames. H.264 output per-frame mean absolute RGB errors are 1.2504, 0.7882 and
  1.1801 (bound 16/255). H.264 input already contains irreversible loss.
- Native two-stream and non-zero timestamp-origin sources are rejected. Changed
  source bytes invalidate reusable-input fingerprints while retained runs still
  verify after original sources disappear. Dishonest frame-count receipts, source
  bindings/completion, replaced captured bytes with refreshed ordinary hashes, and
  changed authored selection plus matching plan are rejected.
- Total timeout and pre-dispatch cancellation produce RUNNER_TIMED_OUT and
  RUNNER_CANCELLED. Existing deliverable acceptance rechecks H.264/FFV1, timed
  sprites, unmet policies, altered publications/readback and all nine nonuniform
  image shapes. Cancellation of owned processes also follows the common runner;
  this qualifier does not claim a separate mid-codec cancellation stress test.

Retained local evidence (bulk files are intentionally ignored):

```text
evidence/programme-20261017/
  ffmpeg-video-final-source/qualification.json
  ffmpeg-video-final-source.log
  ffmpeg-deliverable-regression/qualification.json
  ffmpeg-conformance-host-final/qualification.json
  ffmpeg-conformance-native/qualification.json
  ffmpeg-video-host.log
  ffmpeg-host-regression.log
  ffmpeg-studio-search.log
  ffmpeg-admission.json
  ffmpeg-dependency-free-plan.json
  ffmpeg-capability-search.json
  runtimes/ffmpeg/upstream-check.json
  runtimes/ffmpeg/ffmpeg-9.0.2/{ffmpeg,ffprobe}
  checkpoints/c-ffmpeg.md
```

Reproduce with `PYTHONPATH=src python3 tools/qualify_ffmpeg_video.py --executable
/absolute/path/ffmpeg --output-directory FRESH-EVIDENCE`. Native source decoding
was qualified on local POSIX with sibling FFprobe, not every operating system,
codec, large-resource boundary or arbitrary edit list. No audio, colour-management,
HDR, fractional frame rate, scaling or general editing qualification is asserted.
Offline evidence checks cannot authenticate a fully fabricated evidence set.

[Official CLI](https://ffmpeg.org/ffmpeg.html),
[FFprobe](https://ffmpeg.org/ffprobe.html), and
[latest stable releases](https://ffmpeg.org/download.html#releases) support the
mapping and version basis. The release PGP fingerprint is
`FCF986EA15E6E293A5644F10B4322F04D67658D8`; signature validity is distinct from a
personal certification of key ownership.

Final source-bound conformance **passed and registered** after the root's shared
source/reference/Help freeze. Receipt source identity:
`sha256:009254cfccbf339d79d7ac50260895377c33e4bbcc47b8ee9268249eb6b7a7de` (recorded `2026-10-17T23:19:38.362556+00:00`). All five cases passed:
frames-baseline, frames-variant, deliverable-baseline, video-range-baseline and
video-range-variant. The common kit also independently checked case expectations,
publication/evidence integrity, timeout and pre-launch cancellation. Admission and
the eight FFmpeg input tests passed again on this frozen source. The current
receipt is retained in `adaptors/ffmpeg/qualification.json`; future shared or
provider-source changes correctly make it stale until requalified.
