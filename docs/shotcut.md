# Shotcut timeline editing

`schemaxis.shotcut/1` declares one `editTimeline` node with named `assets`, an
ordered `clips` list, integer `fps`, pixel `width`/`height` and `threads`. Each
clip selects `startFrame` (zero-based) and `frameCount` consecutive source frames.
The planner derives contiguous timeline coverage and duration; duplicate ranges
repeat source frames. It rejects missing/duplicate/unused asset identities,
relative source paths and oversized timelines before native execution.

Use the Shotcut portable `melt` wrapper as the application executable. Its matching
`ffmpeg` and `ffprobe` must be beside it. The wrapper supplies its own MLT libraries
without changing your PATH. This is Shotcut's documented MLT project/rendering
interface, not a general native-command or authored XML passthrough.

Sources must contain exactly one silent video stream, progressive square pixels,
zero-based constant timestamps, matching integer fps and matching dimensions.
Rotation, audio, subtitle streams, resizing and frame-rate conversion are rejected.
Every decoded frame must explicitly report `interlaced_frame=0`; unknown stream
field order alone does not establish progressive frames. Absent/unknown sample
aspect metadata is interpreted as square pixels; explicit non-square ratios fail.
Sources are copied before execution; the editable project references captured
`asset-XX.media` companions using relative names. Retain those files beside
`project.mlt` when opening or relocating the project. The project alone is not a
self-contained handoff. The video publication is independently usable.

The run emits stable artifacts: index 0 `video.mkv` (`video`), index 1 `project.mlt`
(`videoProject`), index 2 `project-bundle.zip` (`videoProjectBundle`). The bundle
contains only the native project and all captured media; exact member names,
order, bytes, regular-file layout and bounded size are checked. Extract these
members together for a self-contained editable handoff. General external ZIP
import is unsupported. The project uses Shotcut track metadata and standard MLT profile,
producers and playlist entries. A native MLT XML consumer reloads and serialises
its service graph. The adaptor checks profile, source identities and every range,
then renders both the original and native-reloaded project in fresh processes.
Their complete decoded RGB must match exactly. Every output frame also matches
its independently selected source pixels at fixed per-frame mean error <=3/255
and maximum channel error <=8/255, allowing bounded MLT colour conversion. FFV1
preserves the rendered RGB; this check does not certify perceptual quality or
colour management. GUI editing, native edit reverse synchronisation, audio,
transitions, filters and multiple tracks are outside this qualification.

The maximum is 16 assets, 128 clips and 600 timeline frames, with 192 MiB budgets
for captured source bytes, decoded source RGB and timeline RGB. All native stages
share one elapsed timeout and the framework's cancellation/process ownership.
A failed run retains logs and an unsuccessful result. Verification rechecks
captured inputs, native ranges, both decodes, probes, artifacts, commands and logs.
Each native stage hashes its consumed inputs in a deterministic trusted launcher
immediately before replacing itself with the application process. Final probe and
decode input hashes must match the current video bytes, so refreshing an artifact
manifest hash cannot attach old decoded pixels to a changed video. This is
ordinary evidence integrity; wholesale fabrication of all native evidence is
outside this local trust model. A regular-file check precedes source capture and
nonblocking descriptor validation rejects FIFOs without hanging. The adaptor
never accepts a process exit or file existence as sufficient proof.
Reopening also requires `result.json` to name exactly this run directory's
`video.mkv`, `project.mlt` and `project-bundle.zip` with three artifacts; a result
that says `succeeded` but points elsewhere or miscounts is `VERIFICATION_FAILED`.
Source frame counts are native observations, so a clip that selects frames beyond
its probed source fails as `INVALID_RANGE` right after that asset's probe, before
any decode or render, reporting the asset, clip, requested end and actual source
frames. Shorten the range or supply a longer source, then run in a fresh directory.

`examples/schemaxis/shotcut-timeline.json` is editable and plan-only until its
absolute placeholder is bound. The six-frame fixture contains red, green, blue,
yellow, cyan and magenta at 32x24 and 25 fps. Baseline cuts `[3,6)` then `[0,2)`
produce yellow/cyan/magenta/red/green (five frames, 0.2 s). The variant repeats
`[1,3)` twice, producing green/blue/green/blue (four frames, 0.16 s). A third
400x200 fixture repeats the baseline to qualify ordinary image dimensions.
Independent acceptance checks these literal RGB colours, counts and durations;
it also checks changed artifacts, source ranges and rendering after relocating
only the project and its captured media. The fixtures were generated as lossless FFV1
from literal RGB colours using public FFmpeg CLI; they contain no external media.
Publication uses FFV1 version 1 without a forced slice layout. Full decode and
hash verification establish integrity; no FFV1 version 3 slice-CRC claim is made.

```sh
PYTHONPATH=src python3 tools/qualify_shotcut.py --executable /absolute/Shotcut.app/melt \
  --output-directory evidence/shotcut-acceptance
PYTHONPATH=src python3 -m schemaxis readiness --app shotcut --admission --check
```

Public upstream references: [MLT XML](https://www.mltframework.org/docs/mltxml/),
[Melt CLI](https://www.mltframework.org/docs/melt/),
[Shotcut download](https://www.shotcut.org/download/) and
[Shotcut source](https://github.com/mltframework/shotcut). MLT's `MLT_XML_DEEP`
environment setting requests native service graph serialisation during the reload
stage; it is defined by the public XML producer implementation.
