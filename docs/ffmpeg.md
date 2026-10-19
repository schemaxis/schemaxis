# FFmpeg

Publish PNG sequences, timed Aseprite sprite sheets, or a bounded range of frames
from an existing video. Schemaxis runs FFmpeg and its sibling FFprobe as separate
processes, captures inputs, and compares every output frame with the expected RGB
pixels. See [PNG and sprite workflows](media-workflows.md#ffmpeg-publication).

## Trim and retime an existing video

```json
{
  "version": "schemaxis.ffmpeg/1",
  "nodes": [{
    "id": "clip", "filter": "encodeVideo",
    "options": {
      "file": "/absolute/path/source.mkv",
      "startFrame": 1, "endFrame": 4,
      "fps": 12, "codec": "ffv1", "threads": 1
    }
  }],
  "deliverable": {"frames": 3, "durationSeconds": 0.25, "maxMeanRGBError": 0}
}
```

`startFrame` is a zero-based **inclusive** decoded presentation-frame index
(default 0), after FFmpeg applies any MP4 edit list.
`endFrame` is a required **exclusive** index. This example selects indices 1, 2
and 3; endFrame 4 does not include frame 4. The range must be nonempty and fit the
entire source. `fps` sets playback speed of these selected frames, default 25:
three frames at 12 fps last 0.25 seconds. There is no frame interpolation,
duplication, dropping or preservation of original timestamps. Choose the source
rate to preserve playback speed. This is a single clip preparation operation;
use Shotcut for multi-clip timelines and editing.

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/ffmpeg-video-range.json
PYTHONPATH=src python3 -m schemaxis run YOUR-DOCUMENT.json --output-directory outputs/clip --ffmpeg /absolute/tools/ffmpeg
PYTHONPATH=src python3 -m schemaxis verify outputs/clip
```

Replace the absolute source placeholder before execution. The Studio **Existing
video frame range** starter and snippet expose the same document. The baseline
and changed range/rate examples explain their literal expected frame indices.

## Supported sources and losses

Existing-video sources are deliberately limited to `.mkv` Matroska with FFV1
`bgr0`, or `.mp4` with H.264 `yuv420p`. There must be exactly one video stream;
audio, subtitles and data streams are rejected. Sources must be progressive,
constant integer rate 1–120 fps, with zero-origin timestamps at uniform intervals
(up to 1.1 ms container rounding), square or unspecified pixel aspect, no rotation
or other stream side data, and fixed dimensions/pixel format. MP4 edit lists use FFmpeg's default presentation interpretation in both probe and decode; the resulting
presentation timestamps must satisfy this contract. Native acceptance includes a
stream-copy trim whose edit list skips leading frames. Display transforms,
colour-management metadata, HDR and arbitrary timeline editing remain outside the
qualified contract. Non-square pixels,
rotation/side data and interlacing are rejected, never silently transformed.

The **entire** source must contain 1–600 frames, be at most the input byte limit
(32 MiB), have dimensions 1–4096 pixels per side, and decode to at most 192 MiB
of RGB. A source longer than the limit is rejected even when the requested range
is small. Native probing and decoding share the run's total timeout. Only the
local file protocol and fixed demuxers are permitted; no authored CLI options,
filter graph, network source, external subtitle or playlist is accepted.

FFV1 output preserves the selected source **decoded RGB** exactly. An H.264 source
has already lost information; conversion to FFV1 does not recover it. H.264 output
uses YUV420, requires even dimensions, and must stay below 16/255 mean absolute RGB
error **for every frame**. This is a numerical bound, not perceptual certification
or a colour-management guarantee. Output has no audio and uses a constant rate.

## Evidence and failures

The original compressed bytes are copied to `input-0000` before native use;
scheduler reuse hashes the source bytes, so changing a source invalidates reuse.
`source-probe.stdout` retains the decoded source timeline and stream metadata;
`source-decoded.rgb` retains every decoded source frame. Adaptor-owned launchers
bind both native source stages to the captured file digest. Selection is rebuilt
from those retained frames during verification, then every output RGB channel is
compared. Output decode/probe stages separately bind their encoded input digest.
The common execution boundary captures the authored schema in the shared schema
store; there is no adaptor-specific schema-copy mechanism.

`INVALID_FRAME_RANGE` means the selected exclusive range is empty or exceeds the
source; correct the indices and run into a fresh directory. `UNSUPPORTED_VIDEO`
means source codecs, streams, timing or display metadata violate the bounded
contract; prepare a supported silent progressive clip first. `RESOURCE_LIMIT`
requires a smaller source. `VERIFICATION_FAILED` means retained source/native
observations or decoded pixels disagree: retain logs, correct the source or runtime,
and rerun. A successful process or an existing video file is insufficient evidence.

Offline verification uses retained native observations and rejects inconsistent
receipts, changed captured inputs, wrong selections and changed native bindings.
It does not authenticate a fully fabricated collection of evidence. The native
qualification constructs known nonuniform frames and independently checks every
selected output frame, including a changed source/range/rate.

[Official FFmpeg CLI](https://ffmpeg.org/ffmpeg.html) and
[FFprobe API](https://ffmpeg.org/ffprobe.html) define the command mapping.
[FFmpeg releases](https://ffmpeg.org/download.html#releases) identified 9.0.2 as
latest stable on 17 October 2026. See the
[completion review](../verification/2026-10-17-ffmpeg-completion.md) for measured
qualification and its limits.
