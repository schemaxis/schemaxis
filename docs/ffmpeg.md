# FFmpeg

Publish PNG sequences, timed Aseprite sprite sheets, or a bounded range of frames
from an existing video, or combine a silent video, a speech WAV and SRT captions
into one review movie, or decode the AAC audio of an MP4/M4A recording to a PCM16
WAV that SoX, FLAC and whisper.cpp accept. Schemaxis runs FFmpeg and its sibling FFprobe as separate
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
or a colour-management guarantee. These operations write no audio and use a constant rate;
only `muxReview` (adds audio and captions) and `extractAudio` (decodes AAC to WAV), below, handle audio.

H.264 output is `yuv420p` (libx264 High profile, asserted by native qualification) and **declares** the BT.601 limited-range
conversion FFmpeg applies (`color_space` `smpte170m`, `color_range` `tv`). The native
probe must report both, so a player that honours the tags decodes the intended
colours instead of guessing a matrix from the frame size; an undeclared stream
decoded as BT.709 measured 7.4/255 mean error (maximum 53) on a saturated and
gradient 640×360 test pattern against 1.5 (maximum 34) when read as BT.601. FFV1 is unchanged: full-range
RGB `bgr0`. Runs retained before this declaration verify against their exact
earlier untagged recipe. Players that ignore colour tags are outside the contract.

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
contract, or the file is a Matroska/MP4 container under the other extension;
prepare a supported silent progressive clip first. `INVALID_RESOURCE` means the
source bytes are empty, truncated or not Matroska/MP4 at all. Both are decided from
the captured bytes before FFmpeg is started, so they are distinct from an
unavailable or failing runtime (`INTERPRETER_NOT_FOUND`, `RUNNER_FAILED`). The check
reads only the container signature; it does not prove the clip decodes. Separately, errors FFmpeg reports on stderr
while probing or decoding a recognised source (a truncated tail, "partial file" or
corrupt packets would otherwise look like a shorter clip) are `INVALID_RESOURCE`
after the native stage; `observed.stage` and `observed.diagnostics` carry the bounded
messages. Re-export the source and run into a fresh directory. `RESOURCE_LIMIT`
means the whole source exceeds 600 frames, 32 MiB or 192 MiB decoded; trim it first,
because a short `startFrame`/`endFrame` range cannot make a longer source acceptable. `VERIFICATION_FAILED` means retained source/native
observations or decoded pixels disagree: retain logs, correct the source or runtime,
and rerun. A successful process or an existing video file is insufficient evidence.

Verification of `encodeFrames`, `encodeSheet` and `encodeVideo` decodes the published bytes
again; it is no longer offline. It needs a **trusted FFmpeg with `ffprobe` beside it**, taken
from the `executable` argument, the stored or invocation configuration (`schemaxis configure
ffmpeg`, `run --executable` / `--ffmpeg`) or `FFMPEG_EXECUTABLE`; the path in a receipt or
submission and `PATH` are never used. Without one, verification stops with
`INTERPRETER_NOT_FOUND` (also for a missing sibling `ffprobe`); `UNSUPPORTED_RUNTIME` means the
executable does not identify as FFmpeg. `run` resolves the same trusted FFmpeg in the same order
(`--executable` / `--ffmpeg`, stored configuration, then `FFMPEG_EXECUTABLE`) and refuses with
`INTERPRETER_NOT_FOUND` before it creates the output directory or starts any native process,
so a run that could find FFmpeg only on `PATH` fails immediately and leaves nothing
behind. The published file and every captured source are read once within byte bounds (the publication up to 512 MiB), copied to a private temporary
directory that is removed on success, failure, timeout and cancellation, and decoded and
probed there with fixed arguments (local files only, the container demuxer forced from the
declared codec, resource limits, the shared deadline and cancellation). Each stage is bound to
the digest of the held bytes it opened. The decision compares every decoded RGB frame, in
order and count, with the frames the host derives from the captured PNG files (for
`encodeVideo`, from a fresh native decode of the captured source video, selected by the
authored range), and checks dimensions, codec, pixel format, frame rate, duration, the
published frame timeline (index/fps, millisecond rounding allowed), the declared BT.601
colour tags for H.264 and the fidelity budget (FFV1 exact; H.264 mean RGB error 16/255 per
frame). Authored deliverable acceptance is reassessed from the fresh observation. Retained
readbacks, receipt and result are strict (no duplicate keys, `NaN`/`Infinity`, `1e400`; `3`
is not `3.0` or `true`) consistency checks: the retained decode, probe and source readback
must agree with the fresh observation (identically when the same FFmpeg build made them;
within a per-frame mean error of 1/255 when another build did), and `result.json` must equal
the verified outcome exactly. A contradiction is `VERIFICATION_FAILED` with `observed.fresh:
true`, so rewriting the retained decode, probe, bindings, receipt, result and publication
hashes to agree with a changed published file is refused. The answer reports
`freshNativeVerification`, `freshRuntime` and `colourTagged`. Runs retained before explicit
colour tagging (an exact untagged encode recipe recorded in the retained command) verify
without requiring tags and report `colourTagged: false`; the recorded command is inert
data, so this is a disclosed limit, and no genuine untagged receipt was available to
exercise it. Historical `-vsync 0` decode and FFV1 level-3 slice recipes remain accepted retained command
records; the fresh decode always uses the current recipe. The captured copies are the trust anchor and are not
authenticated against the original paths: a coherent rewrite of a capture and all its
evidence, or an equivalent re-encode within the fidelity budget, can verify. This is not a
signed-source or host-offline-decode promise. Native limits:
an MP4 that FFprobe cannot open at all (for example no `moov` atom) is
`RUNNER_FAILED` with FFprobe's stderr retained, because a missing runtime and an
unreadable source cannot be told apart from the exit status; and FFV1 level 1 stores
no checksums, so payload corruption that FFmpeg decodes without any error cannot be
detected: the evidence proves what the file decodes to, not that it is undamaged. The native
qualification constructs known nonuniform frames and independently checks every
selected output frame, including a changed source/range/rate.

**Repeated PNG frames.** When `encodeFrames` lists the same PNG bytes more than once, for
example a held title frame, each distinct held byte string is decoded and composited over
black once per preparation and the result is reused at every position; the sequence order,
count, dimensions, byte and decoded-frame budgets, alpha rule and per-frame checks are
unchanged, and each source is still captured and hashed separately. The reuse is keyed by the
held bytes themselves (a full comparison, never a path, size or timestamp) and lives only
inside one preparation, so the run, its own verification, the fresh native pass and a later
standalone `verify` each prepare their frames again and nothing crosses a run, document or
verification. Native commands and encoder input are unchanged. It only saves host CPU
(on one machine, 80 frames of two distinct 960×320 PNGs went from 80 decodes and about
23 s to 2 decodes and about 0.6 s); encoding and native decoding take the same time, so a
whole workflow improves by less. See [the note](../verification/2026-10-25-ffmpeg-49.md).

## Review movie with audio and captions

`muxReview` publishes one `review.mkv` containing exactly three streams: the
captured FFV1 video, the captured PCM16 audio and a selectable SubRip caption track.
Video and audio are stream-copied, so nothing is re-encoded, trimmed, padded or
resampled; captions are soft (never burned in, so no fonts or libass are involved).
Use it to hand a reviewer or a publishing step one reusable file made from an
`encodeVideo`/`encodeFrames` result, a SoX speech WAV and whisper.cpp captions.

```json
{
  "version": "schemaxis.ffmpeg/1",
  "nodes": [{
    "id": "review", "filter": "muxReview",
    "options": {
      "video": "/absolute/path/silent.mkv",
      "audio": "/absolute/path/speech.wav",
      "captions": "/absolute/path/captions.srt",
      "captionStatus": "machineDraft", "threads": 1
    }
  }]
}
```

Each input may also be an earlier verified artifact: `{"$artifact": "clip", "index": 0}`
for an FFmpeg `video` artifact (the `encodeVideo` handoff is exercised natively), or a
SoX WAV / whisper.cpp SRT (`file` artifacts). **The SoX WAV and whisper.cpp SRT handoff
has one limited native proof:** the maintainer ran a single four-job chain once (PNG
frames → FFV1 `encodeVideo`, stereo 44.1 kHz audio → SoX → whisper.cpp SRT → `muxReview`;
one waveform clip of 110 frames at 960×320, 10 fps, 11 s) and `workflow verify` accepted it
read-only after a shared handoff-order fix. That is one clip, not a corpus, and it makes no
recognition-accuracy, human-review or browser-playback claim; other inputs may still be
refused cleanly by the strict WAV and SRT parsers. See
[the workflow example](../examples/schemaxis/ffmpeg-review-workflow.json). The
committed literal fixtures under `examples/schemaxis/fixtures/ffmpeg/` are a
9600-sample 16 kHz WAV and a two-cue SRT for the six-frame 10 fps source
`examples/schemaxis/ffmpeg-video-source.mkv`.

Accepted inputs are deliberately narrow:

- **Video**: the existing silent single-stream Matroska/FFV1 `bgr0` contract (`.mkv`).
  MP4/H.264 and any file with audio or subtitle streams are `UNSUPPORTED_VIDEO`; the
  other operations still refuse extra streams unchanged.
- **Audio**: canonical PCM16 WAV, `fmt ` then `data` chunk only, mono or stereo,
  8000 to 96000 Hz, at most 32 MiB. Other chunks (`LIST`, `fact`), float, 8-bit,
  extensible, compressed, AAC or MP3 audio is `UNSUPPORTED_AUDIO`; a damaged header or
  size mismatch is `INVALID_RESOURCE`.
- **Captions**: strict UTF-8 SubRip, at most 1000 cues, 4 lines and 500 characters per
  cue and 256 KiB. Indices are contiguous from 1; timings are `HH:MM:SS,mmm`
  (no positions), positive, monotonic and non-overlapping; lines carry no leading or
  trailing space (FFmpeg would trim it silently). Markup (`< > { } \`), control,
  format (including bidirectional and zero-width), separator and unassigned characters
  are `UNSUPPORTED_CAPTIONS`; malformed structure is `INVALID_RESOURCE`.

**Duration policy.** With `N` frames at `F` fps and `S` samples at `R` Hz, the audio
and video durations may differ by at most one video frame period:
`|S/R - N/F| <= 1/F`, decided with exact integer arithmetic (no floating point). A
longer difference is `MEDIA_DURATION_MISMATCH`, with the exact rational values in
`observed`; trim or pad the audio (SoX) or select the matching video range first.
Every caption must also end within the video duration (`end_ms * F <= N * 1000`),
otherwise `CAPTIONS_OUT_OF_RANGE`. Within tolerance, each stream keeps its own natural
length; nothing is silently trimmed or padded.

**Caption status.** `captionStatus` is `machineDraft` by default and may be set to
`declaredHumanReviewed`. It is a declaration recorded in the receipt and result with
`recognitionAccuracyCertified: false` and `humanReviewVerified: false`; Schemaxis
verifies the structure, text and timing of the cues, never their accuracy or that a
person reviewed them. Promoting the status in `authored.json` after the run does not
verify.

**Evidence.** The captured inputs are `input-0000` (video), `input-0001` (audio) and
`input-0002` (captions). Source probe/decode stages retain every decoded video frame.
The mux, `ffprobe`, a fresh video decode, a fresh audio decode and a caption
extraction each run under an adaptor-owned launcher that binds the digests of the
exact files the stage opens. Verification requires: exactly three streams in order
video, audio, subtitle with FFV1/`bgr0`, `pcm_s16le` and `subrip`, the captured
dimensions, frame count, rate, sample rate and channels, no chapters, attachments or
tags beyond the container duration; every decoded video frame equal to the captured
source frame (the existing whole-frame FFV1 rule, mean error 0); decoded PCM bytes
equal to the WAV data; and extracted cues equal to the captured cues in text and
millisecond timing. The same bytes come out of two runs with the same inputs and runtime.

**Native audio readback header.** The source WAV contract above does not change. The
audio decode readback (`decoded-audio.wav`) is FFmpeg's own output and is parsed
by a separate strict reader that accepts only the layout this FFmpeg writes: the canonical
16-byte `fmt ` up to and including 48 kHz and, above 48 kHz, the `WAVE_FORMAT_EXTENSIBLE`
PCM16 header (tag 65534, `fmt ` of 40 bytes, 22 extension bytes, 16 valid bits, the exact
integer-PCM sub-format GUID, front-centre mask for mono and front-left/right for stereo).
The other layout at a given rate is refused, as are the usual channel, rate, alignment,
byte-rate, `data`-directly-after-`fmt ` and RIFF/data size defects. Float or other
sub-formats, other valid bits, bit depths or channel masks, extra chunks and truncation are
`VERIFICATION_FAILED` (stage `decode-audio`), not input faults; the decoded PCM must still
equal the captured PCM byte for byte. Sources above 96000 Hz remain `UNSUPPORTED_AUDIO`.
The audio source budget stays 32 MiB, so a 96 kHz source of exactly 32 MiB is accepted: its
extensible readback is 24 bytes longer, and only that readback file's internal size bound
allows 32 MiB plus 24 bytes. The native command and the source and PCM budgets are
unchanged; a source above 32 MiB is still `RESOURCE_LIMIT`.

**Verification decodes the published bytes again.** Standalone `verify` resolves a *trusted* FFmpeg, and the `ffprobe` in the same directory,
from the `executable` argument, then stored configuration (`schemaxis configure ffmpeg`
or a `locations.ffmpeg` entry in the private configuration file), then
`FFMPEG_EXECUTABLE`. It never uses a path from a receipt, submission or launcher and
never searches `PATH`. With none it fails with `INTERPRETER_NOT_FOUND` and a recovery
that names those three routes. Standalone `verify` therefore never falls back to `PATH`;
`run` resolves the runtime by the same rule, before creating its output directory, and
passes that trusted choice to its own verification; it too never searches `PATH`. **A bare `schemaxis verify <directory>` has no
executable flag, so it needs the stored configuration or `FFMPEG_EXECUTABLE`**;
`schemaxis run --ffmpeg` supplies the runtime for that run and its own verification only.

In a private temporary directory outside the submitted directory, the trusted runtime
then runs the fixed source probe and decode on the captured video and the fixed probe,
video decode, audio decode and caption extraction on one bounded read of the published
`review.mkv`, under the shared total timeout and cancellation with the same size
limits; each launch is bound to the digests of the bytes it opened, and the directory
is removed on success, failure, timeout and cancellation. Expectations are derived only
from the captured video, WAV and SRT: the parsed audio and cues, the exact duration
policy, every source frame, the PCM bytes and the exact three-stream membership. The
published file must reproduce them. Retained readbacks do not decide. This defeats a
rewrite of the retained readbacks, bindings, receipt and publication hashes to agree
with a changed `review.mkv` (the earlier offline-only check accepted that).

**Captured sources are the trust anchor.** The three captured copies (`input-0000` to
`input-0002`) are each read once, within a byte bound, and those held bytes are what the
retained pass, the fresh pass and the returned facts all judge; the original authored
paths are never resolved again, and all three captured files and `review.mkv` are
re-checked after the fresh decode. A coherent rewrite of a captured source, its recorded
hash, the receipt, the readbacks and the published file to describe a *different* movie
is therefore not authenticated against the original paths: Schemaxis verifies that the
publication is the movie its captured sources describe, not that those captures are still
what the author supplied. Compare the `sources` hashes with your own copies if that matters.

**Fresh facts must equal retained facts.** The fresh decode derives width, height, frame
count, frame rate, the duration alignment, the cues, audio channels, sample rate, sample
count and byte count, and the digests of the source-decoded video, decoded video, PCM and
cues. Each is compared by exact type with the retained readbacks and with the receipt
rebuilt from the fresh facts, so changing the retained frame count, dimensions or digests
coherently (receipt, readbacks, result and hashes) while the sources and published file
stay the same is refused with the fault tagged `observed.fresh: true`. The returned
`frames` and `duration` come from the fresh facts.

**Timeline.** The source video is constant-rate with no offset, so the published video and
audio must both start at 0 s (strict finite decimal parse; `N/A`, exponents and non-strings
are refused) and the container duration must be within one video frame of the captured
media. A first caption that starts later is allowed; the subtitle stream is not required to
start at 0 (this FFmpeg reports it as 0 anyway, and the first cue's packet carries the time).
A fresh-only video probe (at most 600 frames; no unbounded listing of other streams) must
list exactly the captured number of frames, each with a best-effort timestamp that starts
at 0 and follows index/fps within the millisecond rounding Matroska applies (0.0011 s, as
for the captured source), so 24 and 30 fps clips stay valid. A second fresh-only probe lists
the audio packets (explicit 8 MiB and 32768-packet limits): sizes must be whole PCM16
sample frames and sum to the captured sample count, and each packet must start on the
cumulative sample clock within the same rounding. An audio or video offset is refused. An internal gap or overlap larger than the
1.1 ms rounding bound is also refused even when the PCM bytes, cues, frame count and
stream-level hashes are unchanged. These two probes are not part of the retained receipt,
whose format is unchanged. This checks audio/video timeline consistency of the container,
not the accuracy of the speech.

Retained evidence is still checked for consistency, now with strict JSON (duplicate keys,
`NaN`/`Infinity` and numbers such as `1e400` are refused) and typed comparison (`1` is not
`true`, `3` is not `3.0`): launchers, input bindings, exit codes, the retained readbacks,
the receipt and its publication hashes. `result.json` must equal the verified outcome
exactly, so promoting `humanReviewVerified`, `recognitionAccuracyCertified` or
`captionStatus` there is rejected. A changed captured video, audio or caption file, a
changed published file, a changed stage command or a status promotion is rejected even
when every retained hash was refreshed.

Limits: the published container is judged by what it decodes to and its exact membership
and metadata, not by remuxing it byte for byte, so a change that alters neither (for
example padding) is not detected by the decode check. The three single-video operations now apply the same fresh-decode decision (see above).

Faults: `RESOURCE_NOT_FOUND` (missing input), `RESOURCE_LIMIT` (size, cue, frame or
byte budgets), `INTERPRETER_NOT_FOUND` (no trusted FFmpeg for verification),
`RUNNER_TIMED_OUT` and `RUNNER_CANCELLED` (shared total budget, also during
verification), and `INCOMPLETE_EXECUTION` when `result.json` never reached success.
A failed run records `result.json` as `failed` and removes `review.mkv` on a best-effort
basis (a cancellation or timeout after the mux stage would otherwise leave an unverified
file); if removal itself failed, a file could remain, so only a `succeeded`, verified
result means the file is a verified publication.

```sh
PYTHONPATH=src python3 -m schemaxis plan examples/schemaxis/ffmpeg-review.json
PYTHONPATH=src python3 tools/qualify_ffmpeg_review.py --executable /absolute/tools/ffmpeg --output-directory evidence/ffmpeg-review
```

Not supported here: burn-in, AAC or other lossy audio, H.264 or MP4 output, WebVTT,
mov_text, attachments, metadata, chapters, arbitrary streams or codecs, native flags
and network sources. See the [allocation 39 note](../verification/2026-10-25-ffmpeg-39.md).

[Official FFmpeg CLI](https://ffmpeg.org/ffmpeg.html) and
[FFprobe API](https://ffmpeg.org/ffprobe.html) define the command mapping.
[FFmpeg releases](https://ffmpeg.org/download.html#releases) identified 9.0.2 as
latest stable on 17 October 2026. See the
[completion review](../verification/2026-10-17-ffmpeg-completion.md) and the
[H.264 readback strengthening](../verification/2026-10-25-ffmpeg-34.md) for measured
qualification and its limits.

Unclassified launcher/loader diagnostics or reported allocation failures stop source inspection with `RUNNER_FAILED`; they are not labelled as invalid source bytes. Retained diagnostics identify the stage and next recovery action.

## Extract audio from an MP4/M4A recording

Phone and camera recordings are usually AAC in MP4 or M4A, which the PCM16 WAV
speech adaptors cannot read. `extractAudio` decodes one AAC audio stream into a
canonical 44-byte-header PCM16 WAV and an `audio-summary.json`, so that SoX
`conform` and then whisper.cpp can continue the chain.

```json
{
  "version": "schemaxis.ffmpeg/1",
  "nodes": [{
    "id": "speech", "filter": "extractAudio",
    "options": {"file": "/absolute/path/voice-note.m4a", "streamIndex": 0, "threads": 1}
  }]
}
```

`streamIndex` (0 to 15) is required and is the global stream index as ffprobe numbers
it: 0 for an M4A voice note, usually 1 in a video file whose video comes first. Nothing
is selected implicitly.

Accepted: an intact, non-fragmented, self-contained MP4/M4A (`.mp4` or `.m4a`, at most
64 MiB) with exactly one AAC-LC audio stream (mono or stereo, at an AAC rate from 8000
to 96000 Hz) and optionally one H.264 video stream, decoding to at most 600 seconds
and a 32 MiB WAV. The WAV keeps the stream's sample rate and channel count: no
resampling, mixing, trimming or padding. Refused before or during decoding, with
nothing partial published: additional audio, subtitle, data or cover-art streams,
chapters, HE-AAC and other codecs, surround, a stream that does not start at zero,
gaps or overlaps in the decoded audio frames, external data references, truncated
or damaged files, and anything over the limits.

How the frame count is decided: the encoder's priming and padding follow the container
edit list as FFmpeg applies it, so the count is neither packets x 1024 nor the
container duration. A bounded ffprobe pass lists the decoded audio frames of the
selected stream (timestamps contiguous from zero); their sample total must equal the
native PCM frame count. Both are recorded in the retained evidence.

The probe is bounded, and the bounds are refusals, never truncation: ffprobe output is
capped at 4 MiB (a source carrying a multi-megabyte metadata tag, such as lyrics, is
`RESOURCE_LIMIT`), the frame listing covers at most 17600 packets and 17500 decoded
frames, and a decode larger than the counted frames is refused. The packet bound counts
packets the edit list trims to no frame, so it is the first limit a source with a very
long edit-list lead-in reaches. It covers a mono stream of 960-sample AAC-LC frames
filling the 32 MiB WAV (a 1024-sample stream reaches the WAV limit first); this is not a
claim of exhaustive AAC-LC coverage. These are limits of the bounded probe, not evidence that the
source is invalid.

Fault codes follow the cause. FFmpeg or ffprobe errors that read the recording
(`moov atom not found`, invalid data) are `INVALID_RESOURCE`. A loader, allocation or
unclassified failure, or a stage that exits without producing its output, is
`RUNNER_FAILED`: source validity was not established, so check the retained stage logs
and the runtime and retry in a fresh directory. A stage that reaches its output cap is
`RESOURCE_LIMIT`, decided before any diagnostic is read. Timeouts, cancellation and an
unavailable runtime keep their own codes. While verifying, each of these becomes
`VERIFICATION_FAILED` with the cause retained.

Verification decodes the captured compressed bytes again, in a private directory, with
a trusted FFmpeg and its sibling ffprobe (explicit executable, stored configuration or
`FFMPEG_EXECUTABLE`; never `PATH` or a path in a receipt), with the demuxer forced to
`mov`, the file protocol only and external references disabled. Every PCM byte must
equal the published WAV. Retained launchers, bindings, summary, receipt and result are
checked as strict, typed, closed evidence.

Limits that matter:

- AAC is lossy. The WAV is what FFmpeg's decoder produces, not the uncompressed
  recording that was encoded; no equality with it is claimed. The result is a machine
  draft: no recognition accuracy and no human review is certified.
- The captured file in the run directory is an unauthenticated trust anchor. A
  coherent rewrite of the capture and all evidence is not detected, and no encoder
  history or recording authenticity is claimed.
- Another FFmpeg build that rounds the float-to-PCM16 conversion differently fails
  verification instead of being tolerated.
- Serial runs on one FFmpeg 9.0.2 build were checked; this is not exhaustive codec or
  container coverage.

`examples/schemaxis/ffmpeg-extract-audio-workflow.json` hands the WAV to SoX `conform`.

## Publish a prepared WAV as AAC/M4A

`encodeAudio` turns one prepared canonical PCM16 WAV (for example SoX conform output or an
eSpeak NG utterance) into a shareable AAC-LC `.m4a`, and publishes it only when it meets two
budgets you declare. It fills the gap between a preparation step that produces WAV and a
recipient who needs a small compressed file.

```json
{
  "version": "schemaxis.ffmpeg/1",
  "nodes": [{
    "id": "shareable", "filter": "encodeAudio",
    "options": {
      "file": "/absolute/path/prepared-narration.wav",
      "bitrateKbps": 96, "maxBytes": 8388608, "maxMeanPCMError": 2000, "threads": 1
    }
  }]
}
```

| Option | Meaning |
| --- | --- |
| `file` | Absolute canonical 44-byte PCM16 `.wav`, mono or stereo at 16000, 22050, 44100 or 48000 Hz, at most 600 s and 32 MiB. Captured once. |
| `bitrateKbps` | Required encoder target: 64, 96, 128 or 192. A target, not a measurement. |
| `maxBytes` | Required size budget of `audio.m4a`, 1 to 33554432. A file of exactly this size passes. |
| `maxMeanPCMError` | Required finite number 0 to 65535: mean absolute sample error in signed PCM16 units. |
| `threads` | Optional native thread budget, default 1. |

No codec, filter, trim, rate, channel, normalisation or other native flag is accepted, and
`deliverable` is refused. The fixed recipe is FFmpeg's native AAC-LC encoder, MP4 with
`+faststart`, a movie timescale equal to the sample rate (so the edit list is exact), no
metadata items and no encoder tag.

**What is checked.** The published bytes are probed by FFprobe (one AAC-LC stream, the source
rate and channel count, start at zero, duration equal to the source frame count), a bounded
frame listing must be contiguous from timestamp zero and total exactly the source frames, the
host parses the closed MP4 structure (boxes, edit list with the native priming, sample tables,
`mdat` byte accounting, no external references), and a fresh native decode back to PCM16 at the
source rate and channels must have exactly the source frame count. Every interleaved decoded
sample is compared with the captured WAV; the integer sum of absolute differences divided by
the sample count is compared with `maxMeanPCMError` as an exact rational (the authored decimal
text, never a float epsilon), endpoints included. Anything else — a different count, rate,
channel layout or priming — is refused; nothing is trimmed, padded, resampled or mixed.

**Chunk accounting.** FFmpeg's MP4 muxer starts a new chunk before one would reach 1 MiB, so an
output over 1 MiB has several chunks. The host expands the sample-to-chunk (`stsc`) and
chunk-offset (`stco`) tables into the packet count and byte length of every chunk and requires
them to tile the `mdat` payload exactly: `stsc` runs begin at chunk 1, strictly increase, stay
within the chunk table, hold at least one sample of sample description 1 and place exactly the
listed packets; the first chunk starts at the payload start, each next chunk starts where the
previous one ended (no gap, overlap, duplicate or reordered offset), and the last chunk ends at
the payload end with no trailing `mdat`. Both tables are size-checked against their counts
before any entry is read, and the work is linear in the packet count.

**What is not claimed.** The error budget is a waveform number. It does not measure or certify
listening quality, audibility, speech recognition accuracy or who is speaking, and it bounds the
average only (the largest single-sample error is reported; the decoded waveform can clip at full
scale, and AAC removes high-frequency content). The output is never labelled lossless or high
quality, and no human has reviewed it. `bitrateKbps` is not verified as an achieved rate: the
native encoder clamps by sample rate (a 16 kHz mono tone gave the same file at 96, 128 and 192
kbit/s) and size is not monotonic in the request, so the summary reports the actual size and
average bit rate and `maxBytes` decides.

**Publications.** `audio.m4a` (kind `file`) and `audio-publish-summary.json` (kind `text`). The
summary records the source WAV and PCM hashes, the container geometry (packets, native priming
of 1024 frames, edit list), the decoded PCM hash, the exact mean error as `n/d` and as a float,
the largest sample error, full-scale sample counts, both budget decisions, the losses and the
refused claims. The native decode `decoded.wav` stays in the run directory as internal evidence
and is not a publication.

**Verification** (`schemaxis verify`, or `adaptor.verify`) decodes the published bytes again with
a trusted FFmpeg and sibling FFprobe — explicit executable, stored configuration or
`FFMPEG_EXECUTABLE`, never PATH or a receipt path (the receipt must record an `ffprobe` that is
the sibling of its recorded `ffmpeg`; recorded paths only reconstruct the retained command text
and are never executed; `extractAudio` receipts get the same check) — and judges the held captured WAV, held M4A,
summary, retained decode, launchers, input bindings, receipt, result and exact directory
membership. It does not re-encode: an equivalent legitimate encoding that meets the declared
criteria is accepted, and byte identity with a fresh encode is not claimed. The retained `probe.stdout` and
`frames.stdout` are hash-bound diagnostic records of the original run: verification makes its own
fresh probe, frame listing and decode, and compares the retained decode and summary with them,
not those two files. The captured WAV is an
unauthenticated trust anchor: a coherent rewrite of the source, the M4A and the summary together
is not detected. A different FFmpeg build that rounds the float-to-PCM16 conversion differently
fails verification rather than being tolerated.

**Faults.** `INVALID_ARGUMENT`/`MISSING_ARGUMENT`/`UNKNOWN_ARGUMENT` for authored values (no run
directory and no native process); `UNSUPPORTED_AUDIO` for a WAV outside the supported subset;
`RESOURCE_LIMIT` for size or duration overflow and for output over the probe or decode caps;
`DELIVERABLE_NOT_MET` when a correct file misses `maxBytes` or `maxMeanPCMError` (nothing is
published); `VERIFICATION_FAILED` when the native result differs from the source geometry or
evidence is forged; `RUNNER_FAILED`, `RUNNER_TIMED_OUT` and `INTERPRETER_NOT_FOUND` for the
runtime.

**Native evidence.** FFmpeg 9.0.2 with its native AAC encoder and MP4 muxer, serial, bounded
named fixtures only. The short grid (mono and stereo at the four rates with tiny and odd frame
counts, including one frame) stays valid for those points. It is superseded by the extended
acceptance, which adds 60 s of 48 kHz stereo at 192 kbit/s (output over 1 MiB, several chunks)
and 600 s of 16 kHz mono (the duration limit, a 19.2 MB source, five chunks), each decoded to the
exact source sample count with every sample compared. This does not prove every length, rate or
quality; no human listened to any output. See
`verification/2026-10-25-ffmpeg-audio-publish-56.md` and `tools/qualify_ffmpeg_audio_publish.py`.

`examples/schemaxis/ffmpeg-audio-publish-workflow.json` hands an eSpeak NG `en-us` narration
(file artifact 0) to `encodeAudio` at 96 kbit/s, 8 MiB and 2000 sample units. Those budgets are
an illustration, not a quality preset, and it was run natively once, not over a corpus.
