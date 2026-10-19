# SoX audio assembly

The `schemaxis.sox/1` document assembles selected excerpts of recordings into one
PCM WAV. Its edit decisions specify source frames, amplitude gains and short linear
fades, rather than exposing a command string. Use it for repeatable speech excerpt
sequences, measurement recordings or a sequence of stereo takes.

## Requirements and scope

The native runtime is [SoX 14.4.2](https://sourceforge.net/projects/sox/files/sox/14.4.2/),
the latest stable release checked on 17 October 2026. Configure an absolute `sox`
executable using the shared configuration, or pass `--sox` to the run command.
Host planning, discovery and Studio use Python 3.10+ standard library only.
The [official manual](https://sox.sourceforge.net/sox.html) describes `trim`, `vol`,
`fade` and `--combine concatenate`; the release source also distributes `sox.1`.

Sources must be canonical little-endian RIFF WAV, PCM signed 16-bit, one or two
channels, and 8000–192000 Hz. All clips must have identical rate and channels.
Each WAV has one 16-byte `fmt ` chunk and one nonempty `data` chunk; bounded `LIST`
and `JUNK` chunks may occur once each. Their retention or stripping is outside this verified
contract; this route is not an anonymisation tool. RF64, WAVE_FORMAT_EXTENSIBLE,
compressed formats, nonlocal sources and duplicate/truncated chunks are rejected.
No resampling, mixing, crossfades, playback or user-authored effects are supported.

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

## Execution, handoff and verification

The runner captures every source before native execution and retains authored and
effective plans, source metadata/digests, trusted generated argument arrays in
launchers, stage input bindings, native command submissions/stdout/stderr,
per-clip WAVs and `audio.wav`. The output artifact list contains the WAV first and
`audio-summary.json` second. The summary is host inspection, not native readback.
Independent standard-library RIFF/wave/struct inspection checks rate, channels,
frame count and every output sample against the analytic cuts/gains/fades, then
checks exact clip concatenation and retained evidence membership.

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
retain the evidence and rerun from declared input into a fresh directory.
