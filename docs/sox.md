# SoX audio assembly

The `schemaxis.sox/1` document has four operations. `assemble` joins selected excerpts
of recordings into one PCM WAV. Its edit decisions specify source frames, amplitude
gains and short linear fades, rather than exposing a command string. Use it for
repeatable speech excerpt sequences, measurement recordings or a sequence of stereo
takes. `conform` turns one recording into PCM16 mono 16000 Hz, the form speech
recognition tools such as [whisper.cpp](whispercpp.md) accept; see
[Speech conform](#speech-conform). `normalise` scales one recording by a single
measured gain to an explicit peak level, so a recording is left with predictable
headroom for later publishing or encoding without calculating a gain by hand; see
[Peak headroom](#peak-headroom). `mix` overlays a background recording under a
narration with explicit gains and frame placements; see [Two-track mix](#two-track-mix).

## Requirements and scope

The native runtime is [SoX 14.4.2](https://sourceforge.net/projects/sox/files/sox/14.4.2/),
the latest stable release, rechecked against the official SourceForge release list on 24 October 2026. Configure an absolute `sox`
executable using the shared configuration, or pass `--sox` to the run command.
Host planning, discovery and Studio use Python 3.10+ standard library only.
The [official manual](https://sox.sourceforge.net/sox.html) describes `trim`, `vol`,
`fade` and `--combine concatenate`; the release source also distributes `sox.1`.

Sources must be canonical little-endian RIFF WAV, PCM signed 16-bit, one or two
channels, and 8000–192000 Hz. All clips must have identical rate and channels.
Each WAV has one 16-byte `fmt ` chunk before one nonempty `data` chunk; bounded `LIST`
and `JUNK` chunks may occur once each, and odd-sized chunks need a zero pad byte.
RF64, WAVE_FORMAT_EXTENSIBLE, compressed formats, nonlocal sources, other chunk
names, non-zero padding and duplicate/truncated chunks are rejected. Captured
sources retain their original bytes. Verification requires every native output
(`clip-N.wav`, `audio.wav`) to be exactly a canonical 44-byte `fmt `+`data` file; in
the observed SoX 14.4.2 build native output did not carry the `LIST`/`JUNK` chunks of
four tested source layouts. That observation and check are not a metadata-stripping
guarantee, and this route is not an anonymisation tool.
The `assemble` operation supports no resampling, channel conversion, crossfades,
playback or user-authored effects; `conform` is the operation that resamples and
converts channels, and it has no editing controls.

## Edit decisions and timing

Set `operation` to `assemble`. `clips` is an ordered list of one to eight clips.
Each clip provides an absolute `.wav` `source` and positive integer `frameCount`.
`startFrame` defaults to zero. The selected half-open interval is
`[startFrame, startFrame + frameCount)`, which must lie inside the source.
A frame contains one sample per channel; at 48000 Hz, 48000 frames last one second.
No authored decimal-time conversion or sample rounding occurs.

`gain` is a linear amplitude multiplier from zero to four, default one. A value of
0.5 halves amplitude; it does not mean 0.5 dB. Gain runs before the fades, so any
selected sample that would exceed PCM16 range [-32768,32767] at this stage fails
with `AUDIO_CLIPPING`, even if a subsequent fade would reduce it. There is no
implicit normalisation, limiter, dither or automatic gain adjustment.

`fadeInFrames` and `fadeOutFrames` default to zero and may not overlap: their sum
must be at most `frameCount`. For zero-based frame `i`, an N-frame fade-in multiplies
by `i/N`, for `i < N`. An M-frame fade-out multiplies by `(frameCount-i)/M` over
the last M frames. Thus the first fade-in frame is zero, while the last stored
fade-out frame has gain `1/M`. The zero endpoint lies just after the stored clip.
A one-frame fade-out therefore retains its single frame; choose more frames when
you want a visible taper. Both channels use the same envelope.

Each native clip is quantised once to PCM16. Two internal PCM32 effect truncations
plus final nearest-integer PCM16 conversion permit at most 0.5001 PCM16 LSB error
against the analytic envelope. Concatenation must preserve the processed integer
samples exactly; its tolerance does not grow with clip count.

## Examples and Studio

Edit [mono assembly](../examples/schemaxis/sox-assembly.json),
[stereo assembly](../examples/schemaxis/sox-stereo.json), or the
[stereo variant](../examples/schemaxis/sox-stereo-variant.json), replacing source
paths. Repository fixtures under `examples/schemaxis/fixtures/sox/` contain generated
ramps, impulses and independent channels for bounded repeatable checks. The
[boundary-extrema example](../examples/schemaxis/sox-extrema.json) checks 4000
stereo frames at 11025 Hz with literal PCM16 extrema, signed ramps/impulses and
touching 2000-frame fades. The
[endpoint example](../examples/schemaxis/sox-endpoint.json) processes the literal
input `[12000,-12000,12000,-12000,12000,-12000,12000,-12000]` to
`[0,-6000,12000,-12000,12000,-9000,6000,-3000]`.
The [invalid example](../examples/schemaxis/sox-fade-invalid.json) demonstrates
semantic fade-overlap rejection before launching native SoX.

Studio has mono/stereo starters, nested clip property controls and contextual Help.
Replace path placeholders before native execution. Inspect the text summary and
open the WAV in a suitable external audio tool if listening is required.

## Transcription handoff and timeline

Use this route to prepare a recording excerpt before speech transcription. The
published `audio.wav` is exactly the processed, concatenated PCM16 file; no
resampling, channel conversion or loudness normalisation is applied, so supply a
recording whose rate and channels suit the transcription tool. `audio-summary.json`
states the exact handoff facts:

- `rate` (Hz), `channels` and `frames`; a frame holds one sample per channel.
- `durationExact`, the reduced fraction `numerator/denominator` seconds equal to
  `frames/rate`, and its rounded float `durationSeconds`.
- `segments`, one per clip in output order: `clip` (index), `sourceSha256` (the captured
  bytes), `sourceFrames`, half-open source interval `[sourceStartFrame,
  sourceEndFrame)`, half-open output interval `[outputStartFrame, outputEndFrame)`,
  `gain` and fade lengths.
- `timeline.originalTimestampsPreserved`, always `false`, with the mapping rule.

Output time zero is the first frame of `audio.wav`. Excluded source frames vanish and
clips join without gaps, so a transcript timestamp is `frame/rate` seconds from the
start of the edited file, not a time in the original recording. To recover original
time, find the segment whose output interval contains output frame `f`; its source
frame is `sourceStartFrame + (f - outputStartFrame)`, divided by the common rate.
Source and output end-frame values are exclusive: output frame `outputEndFrame` belongs to the next
segment, or lies after the end of the file. Gains and fades change loudness but not
timing. A transcript produced from the edit does not carry these mappings
itself; retain this summary with it. The summary is rebuilt from the captured sources,
plan and native output during verification, so changed or forged values fail it.

## Speech conform

Set `operation` to `conform` to prepare one recording for transcription, or for any
consumer that needs PCM16 mono 16000 Hz: resample it and reduce it to one channel.
`conform` has two fields: `source`, an absolute `.wav` path with the same contract as a
clip `source` (a workflow handoff `{"$artifact":"earlier","index":0}` works at this
field), and the required `channelPolicy`. The output `audio.wav` is always PCM16, one
channel, 16000 Hz. Nothing else is selectable: no other rate, gain, filter, trim or
SoX option exists, and no authored text reaches the command line.

### Channel policy

`channelPolicy` has no default, because choosing a channel is a decision about the
recording.

- `average` mixes every stereo frame as `(left + right + 1) >> 1`, using integer
  arithmetic: the mean of the two samples, with halves rounded up. SoX scales each of
  two mixed channels by 1/2 (official `remix` manual), so the mean can never exceed
  full scale and no gain compensation is applied. A mono source passes through
  unchanged.
- `left` copies the first channel; `right` copies the second.
- A mono source has no right channel: `right` is refused with
  `AUDIO_CHANNEL_POLICY` before native processing. A mono source accepts `average`
  (its only channel) and `left` (its first channel).
- Channels that are out of phase cancel when averaged: a stereo recording whose right
  channel is the inverse of its left averages to silence. The summary raises
  `CHANNEL_CANCELLATION` when averaging removes at least 30 dB of the louder channel
  and `SILENT_OUTPUT` when audible input yields a silent output. Choose `left` or
  `right` in that case. The summary also reports each source channel's peak and RMS.

### What SoX does

The fixed native command is `sox -D --single-threaded -t wav captured-0.wav -t wav -e
signed-integer -b 16 audio.wav remix SPEC rate -v 16000`, where `SPEC` is `-` (documented
mix-down of all input channels to mono), `1` or `2`. `-D` disables automatic dither,
there is no `norm`, `gain` or `-G`, and `rate -v` is SoX's very-high-quality resampler
with linear phase. Output is exactly the canonical 44-byte `fmt `+`data` WAV, as for
`assemble`. The command was observed with SoX 14.4.2; it is the latest release.

When the source is already 16000 Hz the `rate` effect has nothing to do, and the
result is purely integer channel conversion. SoX's manual does not
state its rounding, so it was probed natively. A probe of 200049 random and extreme
stereo pairs with `remix 1,2`, and the acceptance run's 20081 pairs with the `remix -`
Schemaxis actually uses, both gave `(left+right+1)>>1` exactly for `average`, and
exact copies for `left` and `right`.

### Output length and timeline

For a source of `n` frames at `rate` Hz the output has round-half-up of
`n * 16000 / rate` frames. This was observed for every combination of fifteen rates
(8000, 8001, 11025, 12345, 16001, 22050, 24000, 32000, 44100, 44101, 47999, 48000, 88200,
96000, 192000) and twenty-three lengths from 1 to 12345 frames, including the odd and
non-integer ratios. Examples: 66150 frames at 44100 Hz give 24000; 101 frames at 48000 Hz
give 34; 3 frames at 96000 Hz give 1. A source too short to yield one output frame (fewer
than 6 frames at 192000 Hz) is refused with `AUDIO_SOURCE_BOUNDS`.

Conform keeps the time axis. Output frame `f` corresponds to source time `f/16000`
seconds, with no trimming or padding; SoX's resampler adds no offset (observed phase
error zero at every probed rate). Transcript timestamps therefore equal timestamps in
the original recording, to within the declared fidelity limit below.
`timeline.originalTimestampsPreserved` is `true`, unlike `assemble`.

### Bounds

Source files may be at most 32 MiB and 600 seconds of audio, whichever is reached first
(at 44100 Hz stereo, about 190 seconds). These budgets are practical, not arbitrary:
a 32 MiB, 190-second 44100 Hz stereo recording ran and verified in 9.4 seconds
with about 144 MB peak host memory after the projection check was added. SoX itself
used about 4 MB. The host never decodes a recording into a Python list: it reads the captured bytes
once and streams fixed 65536-frame arrays. Each native process keeps the 30-second CPU
and 512 MiB address-space limits, with a 24 MiB output-file limit (600 seconds of
16000 Hz mono is 19.2 MB).

### Verification and its limit

The host reopens the captured source and the native output and checks, independently of
the command line:

- the source and output headers, canonical native layout, exact output rate, channel
  count and frame count;
- that the retained captured source matches its recorded SHA-256, the planned path and the
  digest bound into the native launcher, and still satisfies every source rule;
- at 16000 Hz, **every output sample** against the exact integer rule above;
- otherwise, a loudness bound and a **spot check**, described next;
- that native standard output is empty and standard error holds only SoX's two
  clipping warnings, which are counted;
- exact run-directory membership, the effective plan, receipt, summary and result.

Resampled samples are **not** recomputed bit-exactly, and individual resampled samples
are not certified: there is no independent bit-exact oracle for SoX's filter, and near
the output Nyquist frequency any two correct resamplers legitimately differ (SoX `rate -v`
is about -3 dB at 7600 Hz and removes 8000 Hz and above). The host therefore verifies a
**declared band** instead of whole samples.

Let N be the lower Nyquist frequency, min(source rate, 16000)/2. The host builds one
independent low-pass filter in physical time (Kaiser-windowed sinc, unit gain to 0.6 N,
a nominal 100 dB design attenuation target from 0.8 N; the same continuous kernel at both
rates). It passes the mixed source through it at the source rate and the native output
through it at 16000 Hz, and compares the two at up to 512 interior instants: 256 evenly
spaced and 256 from the loudest parts of the recording. SoX's own transition and stop
band lie inside the filter's stop band, so correct native filter shape there cannot
register as an error. At every compared instant the difference must be at most

    half the L1 norm of the output kernel (output rounding)  + 1 LSB  + 0.004 x source peak

The last term is a chosen leakage margin relative to the source peak. It is not a
proved bound on every SoX pass-band response: the independent filter has a nominal
design target, while the native response is checked by bounded probes. Separate
serial probes observed residuals below 0.7 LSB on tones, chirps and noise across the
recorded rates; those observations do not certify all recordings or future builds.

At compared instants, sufficiently large in-band errors such as silence, polarity
inversion, a wrong channel, a one-frame shift or gain change can be detected. A
changed passage between sampled windows can be missed, as can an error below the
source-peak-relative margin (0.004 of peak, about 48 dB below it). Zeroing a quiet
passage or a gap between the at most 512 sampled windows is therefore not guaranteed
to be detected. The check does not verify:
- anything above 0.6 N. Native removal or alteration of 4800-8000 Hz content is
  accepted; an output whose source content lies only there may be replaced by silence
  (`SILENT_OUTPUT` is then raised, but the band check passes). The mean-square loudness
  bound still limits added energy;
- the rate-dependent kernel margin at either edge (about 2 ms per edge at 44.1 kHz,
  about 4 ms at 8 kHz);
- a source too short to have any interior instant. The threshold depends on its
  rate (181 source frames at 44.1 kHz and66 frames at 8 kHz in the current implementation). Its
  `comparedPositions` is zero and `FIDELITY_NOT_SAMPLED` is raised;
- instants whose output window touches a saturated sample when SoX reported clipping.
  These are counted in `excludedForNativeClipping`, and the `OUTPUT_SATURATION` warning
  says how many were skipped. Saturation without a native clipping warning is compared
  normally. Heavy clipping on every cycle can leave nothing to compare, and then
  `FIDELITY_NOT_SAMPLED` is raised.

A replay of the native command alone is never taken as this evidence.

Resampling can overshoot full-scale material. The output is saturated to PCM16, the
number of saturated output samples is `saturatedSamples`, SoX's own warnings are in
`nativeClippingWarnings`, and `OUTPUT_SATURATION` is raised. Conform never rescales
to avoid this; if it matters, lower the level first (for example with `assemble`'s
gain) and then conform.

### Summary

`audio-summary.json` holds `channelPolicy`, `rate`, `channels`, `frames`,
`durationExact`, a `source` block (SHA-256, bytes, rate, channels, frames, peaks and
RMS per channel), `conversion`, output `peakPCM16`/`rmsPCM16`, the clipping counts,
`fidelity` (method, whether samples were recomputed exactly, compared and clipping-excluded
instant counts, the verified band, the projection filter and the error limit), `warnings` and `timeline`. Floating-point fidelity measurements are
not stored, so a summary reopens identically on any host.

### Examples

[Speech from a 44.1 kHz stereo recording](../examples/schemaxis/sox-conform-speech.json)
averages two channels and resamples to 16 kHz. [Left channel of a 48 kHz
recording](../examples/schemaxis/sox-conform-left.json) shows channel selection. [Same-rate
stereo](../examples/schemaxis/sox-conform-same-rate.json) is verified sample for sample.
[Mono at 8 kHz](../examples/schemaxis/sox-conform-mono.json) is upsampled. The
[invalid policy example](../examples/schemaxis/sox-conform-invalid-policy.json) is
refused with `INVALID_ARGUMENT`. The generated fixtures are described in
`examples/schemaxis/sox-conform-fixtures/README.md`.

To transcribe, run `conform`, then pass its `audio.wav` to
[whisper.cpp](whispercpp.md) as the audio file. Workflow verification rechecks the
original source file, as it does for `assemble`.

## Peak headroom

Set `operation` to `normalise` to scale one recording so that its largest sample has a
level you chose, rather than working out a `gain` for `assemble` by hand. `assemble`'s
`gain` is a manual multiplier from zero to four that does not look at the recording;
`normalise` measures the recording and supplies a repeatable gain. It is **peak
scaling** in PCM16 sample units. It is not loudness mastering: nothing measures RMS,
EBU R128 loudness, true peak or perceived volume.

The document has three required fields, and nothing else is accepted:

- `source`, an absolute `.wav` path with the same contract as `conform` (canonical
  PCM16 mono or stereo, 8000–192000 Hz, at most 32 MiB and 600 seconds). A workflow
  handoff `{"$artifact":"earlier","index":0}` works at this field.
- `targetPeak`, an integer from 1 to 32767: the absolute PCM16 sample magnitude that
  the loudest output sample will have. It is not decibels. 32767 is full scale; 29491
  is about 90 percent of full scale and leaves 3276 sample units of headroom.
- `maxGain`, a finite number from 1 to 16: the largest **boost** you will accept.

### Target peak and boost ceiling

The host reads every sample of every channel and takes the largest absolute value, the
measured `peak`. The exact gain is the fraction `targetPeak/peak`, kept as a reduced
numerator and denominator. Then:

- A **silent** recording (every sample zero) has no peak to scale and is refused with
  `AUDIO_SILENT_SOURCE`.
- If the gain exceeds `maxGain` the job is refused with `AUDIO_GAIN_LIMIT` **before SoX
  starts**. The gain is never capped, the target is never quietly lowered and nothing is
  clipped. Lower `targetPeak`, raise `maxGain` deliberately or choose a louder recording.
  A gain exactly equal to `maxGain` is accepted. `maxGain` is compared as an exact
  fraction of the parsed JSON number's shortest round-trip decimal, not as the binary
  floating-point value: `6.6` means 33/5, so a recording with peak 5 and `targetPeak` 33
  (gain exactly 33/5) is accepted, while `6.599999999999999` (the next smaller
  double-precision value) refuses it. JSON parsing rounds the literal to a double
  *before* this comparison, so a literal with more digits than a double holds, such as
  `6.59999999999999999999999`, is read as the double `6.6` and compared as 33/5; digits
  written beyond a double's precision are not preserved or compared. The host adds no
  epsilon, clamp or further rounding of its own.
- A gain below one is an **attenuation** and is always allowed, since the peak can only
  move away from clipping. A gain of exactly one leaves every sample unchanged (unity).
- One common gain multiplies every channel, so the level balance between the left and
  right channels is preserved. There is no mixing, resampling, trimming, fade, dither,
  limiter or compression.

A boost raises the noise floor, hum and the quantisation noise by the same ratio as the
signal: a recording whose loudest sample is 3000 and whose room noise is at 40 becomes a
recording at 20000 with room noise at about 267. `maxGain` protects your policy about how
far such a recording may be amplified; it cannot tell signal from noise, and a boost
above one raises a `NOISE_FLOOR_AMPLIFIED` warning in the summary.

PCM16 spans [-32768, 32767] and is asymmetric. If the only sample of largest magnitude
is a `-32768`, the measured peak is 32768 and `peakPolarity` is `["negative"]`. Because
`targetPeak` cannot exceed 32767, such a recording is always attenuated (to at most
32767/32768), and the output cannot contain -32768. A recording whose peak is reached
by both a positive and a negative sample reports both polarities.

### What SoX does for normalise

The fixed native command is `sox -D --single-threaded -t wav captured-0.wav -t wav -e
signed-integer -b 16 audio.wav vol GAIN`, where `GAIN` is the exact fraction converted
to a double and written with 17 significant digits. `vol` with no type is the official
manual's amplitude multiplier (a ratio, not decibels). There is no `gain`, `norm`, limiter
or dither (`-D`), and no authored text reaches the command line. The command was observed
with SoX 14.4.2, the latest release, which was rechecked against the official SourceForge
release list on 25 October 2026. The 17-digit double has a relative error of about
1e-16, far below what could move a rounded sample.

### Normalise verification and its limit

The planner reads no file. When the job runs the host first captures the source and
checks its format, its length and the peak/gain rules above; only then is SoX launched.
After SoX returns, the host reopens the captured source and the native output with
`wave`/`struct` and checks, independently of the command line:

- the output is the canonical 44-byte `fmt `+`data` WAV with the source's exact rate,
  channel count and frame count;
- **every scalar sample** of the output against the exact rational
  `sample*targetPeak/peak`: it must be a nearest PCM16 integer (the distance is at most
  one half sample unit; at an exact tie either neighbour is accepted, because SoX's tie
  rule is not documented). The check is exact integer arithmetic, with no floating-point
  tolerance, and is tighter than the 0.5001 unit tolerance used for `assemble`;
- the output peak equals `targetPeak` exactly, so nothing was clipped or left short;
- native standard output and standard error are empty (SoX prints clipping warnings
  there, and none can occur), and the run directory, plan, receipt, summary and result
  contain exactly the declared members and values.

The summary gives the exact `gain` fraction, the source `peakPCM16`, the exact maximum
rounding error as a fraction, `samplesCompared`, `headroom` (output peak and the remaining
positive and negative sample units to full scale), `claims` and `limits`.
`positiveHeadroomPCM16` and `negativeHeadroomPCM16` are both computed from the one overall
absolute output peak (32767 minus the peak and 32768 minus the peak), so they are
conservative bounds for either polarity; they are not separately measured peaks of the
largest positive and largest negative samples, and the room actually left on one side may
be larger. A `description`
block holds the gain as a decimal ratio and in decibels and the headroom in decibels.
Those floats are a convenience for reading; they are not authority and are compared with
a small tolerance, while every other field is compared exactly.

The verification does not certify the recording's content, authenticity or identity,
measure loudness, true peak or inter-sample overshoot (a reconstructed waveform can
exceed the largest sample), or say anything about speech quality or perceived volume.
Sample time is preserved: output frame `f` is source frame `f`, at `f/rate` seconds, so
`timeline.originalTimestampsPreserved` is `true`. That is a statement about sample time
only. The output is the bare canonical 44-byte WAV, so any `LIST`/`INFO` or other metadata
chunks in the source are not carried over.

`tools/qualify_sox_normalise.py` runs the bounded native acceptance with an independent
integer oracle: six sample rates (8, 16, 22.05, 44.1, 48 and 192 kHz) with the channel
count alternating (mono at 8, 22.05 and 48 kHz; stereo at 16, 44.1 and 192 kHz), not all
twelve rate and channel combinations, because the gain mapping does not depend on the
rate; a gain of exactly 16, the decimal ceiling above, a `-32768` peak, and sweeps of
every PCM16 value from -32768 to 32767.
In that run SoX 14.4.2 rounded exact halves toward positive infinity; that observation is
not a documented guarantee, so verification still accepts either neighbour at a tie.

A native run costs one SoX process; the host streams fixed 65536-frame arrays and holds
only distinct (source, output) sample pairs, never a sample list. A genuine native output
gives one output value per source value, so at most 65536 pairs. The verifier allows two
integer outputs per source value (an exact tie) and, for a forged output, one fixed chunk
more before it refuses, so memory is bounded by twice the distinct source values plus one
fixed chunk of 65536 frames.
Each native process has the 30-second CPU and 512 MiB address-space limits and a file
size limit equal to the 32 MiB source limit.

### Examples

[Boost a quiet stereo recording](../examples/schemaxis/sox-normalise-boost.json) to peak
20000 (exact gain 20/3, `maxGain` 8). [Attenuate a loud mono
recording](../examples/schemaxis/sox-normalise-attenuate.json) to peak 16384. The
[negative full-scale example](../examples/schemaxis/sox-normalise-negative-fullscale.json)
shows the PCM16 asymmetry. The [invalid example](../examples/schemaxis/sox-normalise-invalid-target.json)
is refused with `INVALID_ARGUMENT` because `targetPeak` exceeds 32767. The
[workflow example](../examples/schemaxis/sox-normalise-flac-workflow.json) normalises a
recording and archives the verified result as lossless [FLAC](flac.md). Generated fixtures
are described in `examples/schemaxis/sox-normalise-fixtures/README.md`.

## Two-track mix

Set `operation` to `mix` to overlay two recordings in one PCM16 WAV: a `narration` and a
`background` (music or room tone, for example). Nothing here is automatic. The document
chooses each track's gain, where each track starts, and where the result ends, and the
host recomputes every output sample from the captured sources. `assemble` joins clips one
after another, `conform` changes rate and channels and `normalise` sets one recording's
peak; `mix` is the only operation that sums two recordings, and none of the other three
changes.

### Mix tracks

The document has `narration`, `background` and `durationPolicy`, all required, and
nothing else is accepted. Each track is an object with:

- `source`, an absolute `.wav` path with the same canonical PCM16 contract as `assemble`
  (a workflow handoff `{"$artifact":"earlier","index":0}` works at this field);
- `gain`, a number from 0 to 4 with at most four decimal places, default 1;
- `offsetFrames`, an integer from 0 to 262144, default 0.

Both recordings must have the same sample rate and the same channel count (both mono or
both stereo). There is no resampling, channel conversion or silent repair: a difference is
refused with `AUDIO_FORMAT_MISMATCH` before SoX starts, and the recovery is to run
`conform` on one recording, or to record both alike. Budgets are those of `assemble`:
4 MiB of source bytes in total, at most 262144 output frames and 1048576 combined
source/output scalar samples, with each source decoded once on the host.

### Mix placement and duration

`offsetFrames` is a placement on the output timeline. Source frame `k` of a track appears
at output frame `offsetFrames + k`, and the frames before it are exact silence (zero) for
that track. Frames are whole sample frames, so seconds are `offsetFrames / rate`: 8000
frames at 8000 Hz is one second. Placement never trims the source.

`durationPolicy` is required, and has two values:

- `longest`: the output ends with the later track (the greater of `offsetFrames + frames`
  of the two). The earlier-ending track is silent for the rest.
- `narration`: the output ends where the narration ends, at its `offsetFrames` plus its
  frame count. Any background beyond that frame is cut; a shorter background simply
  ends. A background whose `offsetFrames` is at or after the narration end would
  contribute nothing, so it is refused with `AUDIO_SOURCE_BOUNDS`.

The result must span at most 262144 frames (`AUDIO_RESOURCE_LIMIT`, checked on the
untrimmed span). Output time zero is the first output frame. The narration appears at its
`offsetFrames`, so a transcript of the mix is that many frames later than the same words
in the narration recording; `timeline.originalTimestampsPreserved` is `false` and the
summary's `tracks` give each interval. The summary also reports `overlapFrames`,
`overlapStartFrame` and `uncoveredFrames` (output frames with neither track, from a
gap between placed tracks).

### Mix gain and clipping

A track's `gain` is an amplitude ratio (0.25 is a quarter, not decibels), applied to each
sample. The exact mixed value of output sample `n` is `gainN * narrationSample +
gainB * backgroundSample` with a missing track contributing zero. Before SoX starts,
the host computes every exact mixed value with integer arithmetic (a gain is a count of
1/10000 units, which is why more than four decimal places is refused with
`INVALID_ARGUMENT`) and refuses the job with `AUDIO_CLIPPING` if:

- any gained term lies outside -32768..32767 (SoX also saturates a track after its
  own gain, so an out-of-range term cannot be undone by a sum that returns to range), or
- any exact sum lies outside -32768..32767.

There is no limiter, rescaling, dither or saturation policy: reduce a gain or the source
level. The check covers every frame of the untrimmed mix, including background frames
that `durationPolicy: narration` would cut. A gain of 0 mutes a track and is accepted.

Rounding follows from the probed native behaviour: output is the PCM16 integer nearest the
exact sum. SoX 14.4.2 rounded exact halves toward positive infinity (2.5 to 3, -2.5 to
-2) in probes, but the manual does not state this, so verification accepts either
neighbour at an exact tie. With at most four gain decimals a value that is not a tie is at
least 1/10000 from one, larger than the two internal 32-bit roundings of SoX, so a wrong
neighbour at a non-tie fails verification.

### What SoX does for mix

Three fixed native commands run in the same isolated process model as the other
operations, in this order:

    sox -D --single-threaded -t wav captured-0.wav -t wav -e signed-integer -b 16 pad-0.wav pad OFFSETs 0
    sox -D --single-threaded -t wav captured-1.wav -t wav -e signed-integer -b 16 pad-1.wav pad OFFSETs 0
    sox -D --single-threaded -m -v GAIN pad-0.wav -v GAIN pad-1.wav -t wav -e signed-integer -b 16 audio.wav [trim 0 FRAMEs]

`pad` (an official effect) appends no samples at the end and `OFFSET` silent frames
at the start; `-m` is `--combine mix`, which pads the shorter input with silence at the end;
`-v` is the per-input volume (a ratio, written as a double with 17 significant digits). Each
`-v` is explicit, because without it SoX divides each input by the number of inputs. `trim`
appears only for `durationPolicy: narration` and cuts to the narration end. There is no `norm`,
`gain`, limiter, dither (`-D`), effect, script or authored text on any command line. The commands
were observed with SoX 14.4.2, the latest stable release.

### Mix verification and its limit

After SoX returns, the host reopens the captured sources and the native files with
`wave`/`struct` and checks, independently of the command line:

- both captured sources against their recorded SHA-256, the planned paths and the digests
  bound into each launcher, and that they still satisfy every source and no-clipping rule;
- each `pad-N.wav` is exactly `offsetFrames` zero frames followed by the captured samples;
- `audio.wav` is the canonical 44-byte WAV with the shared rate and channels and exactly the
  frame count the policy implies;
- **every output scalar sample** is a nearest PCM16 integer to the exact gained sum, in
  exact integer arithmetic with no floating-point tolerance (ties accepted either way);
- native standard output and standard error of every stage are empty (SoX warns on clipping
  there), and the run directory, plan, receipt, summary and result hold exactly the
  declared members and values, with stale, forged or substituted evidence failing with
  `VERIFICATION_FAILED`.

The summary states `rate`, `channels`, `frames`, `durationExact`, `durationPolicy`, per-track
SHA-256, gains (decimal and exact fraction), placements, included and truncated source
frames, leading and trailing silence, `peakPCM16`, `samplesCompared`, `maxMixErrorExact`
(the largest distance from an exact value, as a reduced fraction, never more than 1/2),
the rounding and clipping rules, the timeline and `limits`.

Verification makes no claim about loudness, intelligibility, quality, balance or how the
result sounds, and does not certify the recordings. The output is a bare canonical WAV, so
source metadata chunks are not carried over.

`tools/qualify_sox_mix.py` runs the bounded native acceptance with its own oracle
(exact `Fraction` arithmetic and its own WAV reader, sharing no code with the adaptor). It covers mono
and stereo at several rates, both policies, offsets including zero and large relative
to the sources, silence padding and gaps, gains of 0, 1, 4 and four-decimal fractions,
every PCM16 extreme, the tie and sign cases, and sweeps of sample pairs; it checks that clipping, rate and channel
mismatch, bounds, over-precise gains and invalid values are refused before
any native process, and that forged or stale evidence, changed sources and timeout/cancellation
are rejected. Fixtures are tiny: a few thousand frames at most, apart from one 65536-frame sweep of every PCM16 value.

### Mix examples

[Baseline](../examples/schemaxis/sox-mix-baseline.json) places a mono narration 200 frames
into a quarter-level mono background (`longest`). The
[narration-policy variant](../examples/schemaxis/sox-mix-narration-policy.json) mixes stereo
tracks with fractional gains and ends with the narration. Two invalid examples are
refused before native processing: [a five-decimal gain](../examples/schemaxis/sox-mix-invalid-gain.json)
(`INVALID_ARGUMENT`) and [a missing durationPolicy](../examples/schemaxis/sox-mix-invalid-policy.json)
(`MISSING_ARGUMENT`). The generated fixtures are described in
`examples/schemaxis/sox-mix-fixtures/README.md`. In Studio, use the mix starter and replace the paths.

## Execution, handoff and verification

This section describes `assemble`; `mix` additionally retains `captured-1.wav` and the `pad-0.wav` and `pad-1.wav` stage files; `conform` and `normalise` retain the same kinds of
evidence (`captures.json`, `captured-0.wav`, `version-*` and `conform-*` or
`normalise-*` stage files, `audio.wav`, `audio-summary.json`, receipt and result) under
the checks above.

The runner captures every source before native execution and retains authored and
effective plans, source metadata/digests, trusted generated argument arrays in
launchers, stage input bindings, native command submissions/stdout/stderr,
per-clip WAVs and `audio.wav`. The output artifact list contains the WAV first and
`audio-summary.json` second. The summary is host inspection, not native readback.
The receipt has exactly the fields `executable`, `runtime`, `artifacts` and
`evidence`. Reopening also fails for unreferenced `.wav`, launcher, input-binding,
submission, stdout or stderr files in the run directory, and the retained
`result.json` summary must match independent reopening.
Independent standard-library RIFF/wave/struct inspection checks rate, channels,
frame count and every output sample against the analytic cuts/gains/fades, then
checks exact clip concatenation, canonical native output headers and retained evidence
membership. Faults in retained captured audio found while reopening are reported as
`VERIFICATION_FAILED`, naming the underlying audio fault.

The workflow profile accepts `file` artifacts; a source still must satisfy this
WAV contract. Use `{"$artifact":"earlier","index":0}` at a clip's `source` for
verified WAV handoff. Common references, expressions and finite parameter studies
resolve before native processing. Same-path source byte changes invalidate reuse.
Shared schema storage captures this route through normal framework execution.

One deadline covers capture, all native stages and final verification. Each native
process has a 30-second CPU limit, 512 MiB address-space limit and 8 MiB file limit;
shared cancellation terminates its owned process group. Native processing uses one
thread. Aggregate captured source bytes cannot exceed 4 MiB; combined decoded source
and output scalar samples cannot exceed 1048576. Total output is at most 262144
frames. These deliberate bounds keep Python sample inspection practical.

An individual native run can be reopened from its captures without its original
source files. The current scheduled workflow verifier additionally rechecks original
source hashes, so workflow verification/reuse still requires those original files. Portability of
shared schema dependencies follows the framework export contract. Audio metadata
and ancillary chunk retention/stripping are not certified. Qualification covers this fixed PCM16
workflow and the observed runtime, not all SoX codecs/effects or operating systems.

## Fault recovery

`INVALID_AUDIO_FADE` means fades overlap: shorten one or both. `AUDIO_SOURCE_BOUNDS`
means the selected half-open interval exceeds source frames: inspect the recording
length. `AUDIO_FORMAT_MISMATCH` means channels or sample rates differ: prepare matching
recordings explicitly. `AUDIO_CLIPPING` means gain overloads before fading: reduce
gain. `INVALID_AUDIO_DATA` means malformed/unsupported PCM WAV; re-export canonical
PCM16. `AUDIO_RESOURCE_LIMIT` means shorten clips or split the work. Missing SoX gives
`INTERPRETER_NOT_FOUND`. An unsuitable version gives `UNSUPPORTED_NATIVE_VERSION`
before processing clips. A changed artifact or evidence gives `VERIFICATION_FAILED`;
retain the evidence and rerun from declared input into a fresh directory. This
includes injected metadata chunks, unreferenced files, forged summaries, receipts or
retained results, even when ordinary file hashes were refreshed.

`conform` faults: `AUDIO_CHANNEL_POLICY` means `right` was chosen for a mono
recording, so choose `average` or `left`. `INVALID_ARGUMENT` or `MISSING_ARGUMENT` at
`channelPolicy` means the policy is absent or not one of `average`, `left`, `right`.
`INVALID_AUDIO_DATA` means unsupported audio (24-bit, float, three or more channels,
rates outside 8000–192000 Hz, compressed or malformed WAV): re-export PCM16.
`AUDIO_RESOURCE_LIMIT` means more than 600 seconds: split the recording.
`INVALID_AUDIO_SOURCE` also covers files over 32 MiB. `AUDIO_SOURCE_BOUNDS` means the
source is too short to give one output frame. `VERIFICATION_FAILED` names the failing
file: `audio.wav` for sample, header or fidelity failures, `conform.stderr` for
unexpected native diagnostics. Rerun from the declared source into a fresh directory.

`normalise` faults: `INVALID_ARGUMENT` or `MISSING_ARGUMENT` at `targetPeak` or `maxGain`
means a value is absent, not an integer (for `targetPeak`) or a finite number, or
outside 1–32767 or 1–16; a boolean, text, a fractional `targetPeak` or a decibel
value is not accepted. `AUDIO_SILENT_SOURCE` means the recording is all zeros.
`AUDIO_GAIN_LIMIT` means the exact gain needed exceeds `maxGain`; the message states the
measured peak and the gain required. `INVALID_AUDIO_DATA`, `INVALID_AUDIO_SOURCE` and
`AUDIO_RESOURCE_LIMIT` have the same meaning as for `conform`. `VERIFICATION_FAILED`
names the failing file: `audio.wav` for any sample, peak or header difference,
`normalise.stderr` or `normalise.stdout` for unexpected native output. Rerun from the
declared source into a fresh directory.

Historical `/1` receipts with exactly the earlier eight-field audio summary
remain verifiable with current sample, command and evidence checks. Verification
compares that smaller assertion set and does not manufacture a timeline claim.
New summaries must contain the complete extended set; partially missing or forged
timeline fields are refused.

Published segment maps identify source clips by index and SHA-256. Original
workstation paths remain in local capture/provenance evidence rather than the
published audio summary. Verification accepts only declared run members and
framework sidecars, and compares the retained effective plan, capture map, summary and
result JSON types and fields exactly: a forged `false` for `0`, `true` for `1` or
`40.0` for `40` fails with `VERIFICATION_FAILED` even when digests were refreshed.
A legacy eight-field summary remains accepted. Removing timeline fields removes
those claims; it cannot add unchecked claims. Consumers that need a segment map
must require the timeline fields, rather than treating a legacy summary as a map.

`mix` faults: `MISSING_ARGUMENT` at `durationPolicy` means the policy is absent; `INVALID_ARGUMENT`
there means it is not `longest` or `narration`. `INVALID_ARGUMENT` at a track `gain` means a
value outside 0–4, not a number, or with more than four decimal places; at `offsetFrames` it
means a non-integer or a value outside 0–262144. `UNKNOWN_ARGUMENT` marks a field of another
operation or an unsupported track field. `AUDIO_FORMAT_MISMATCH` means the two recordings differ in
rate or channel count: run `conform` on one, or record both alike. `AUDIO_CLIPPING` means a gained
term or an exact mixed sample would leave PCM16: reduce a `gain` or the source level; nothing is
clipped for you. `AUDIO_SOURCE_BOUNDS` means that under `narration` the background begins at or after
the narration end. `AUDIO_RESOURCE_LIMIT` means more than 262144 output frames or the byte or sample
budget. `INVALID_AUDIO_SOURCE` and `INVALID_AUDIO_DATA` have the meaning given for `assemble`.
`VERIFICATION_FAILED` names the failing file (`audio.wav` for a sample, header or length difference,
`pad-N.wav` for placement, `mix.stderr` or a `pad-N.stderr` for unexpected native output). Rerun from the declared
sources into a fresh directory.
