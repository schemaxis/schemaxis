# FFmpeg bounded inputs and stage-bound readback — 2026-10-10

New source capture and reusable-input fingerprinting reject devices/FIFOs before
opening, recheck the opened descriptor and bound per-file/aggregate byte reads.
This covers both ordered PNG frames and sprite-sheet metadata. NUL paths fail
host planning as a structured invalid-resource fault. No native process is
launched for these invalid sources.

The decode and ffprobe stages now use deterministic adaptor-owned Python launchers
under the shared owned process. Each hashes its actual encoded-video input
immediately before entering the native executable. The receipt records launcher,
input-binding and decoded/probe output digests. Offline verification reconstructs
the trusted launcher and command and requires the binding to match current video
bytes. Replacing an encoded video with same-length bytes and refreshing ordinary
artifact hashes **and** publication metadata cannot reuse stale RGB/probe evidence.

Exact historical direct native command receipts remain verifiable and report
`nativeReadbackBound: false`; new launchers cannot be verified after their binding
is removed. This is stage association and ordinary evidence integrity, not a
signed attestation or protection against coordinated replacement of every native
execution record. Public verification already rejected changing only the ordinary
artifact hash through its publication-metadata relationship; this milestone adds
an independent semantic association after both ordinary records are refreshed.

## Exact stable release and compatibility

The absorbed release is now **FFmpeg 9.0.2**, the exact upstream release identified
by the [official download page](https://ffmpeg.org/download.html), released
18 September 2026. The release archive and ASCII signature were downloaded from
FFmpeg; GPG verification used the published fingerprint
`FCF986EA15E6E293A5644F10B4322F04D67658D8`. The private executable is
`evidence/adaptor-growth-20261010/runtimes/ffmpeg-9.0.2-build/ffmpeg-9.0.2/ffmpeg`,
with ffprobe beside it. Its optimised gcc13 minimal build enables libx264, FFV1,
raw RGB and the required Matroska/MP4 formats, without assembly or networking.
Build transcript: `<local build log>`.
The exact release is qualified separately from Shotcut's derivative bundle.

Retained compatibility uses `evidence/runtime/bin/{ffmpeg,ffprobe}`, observed
`ffmpeg version 6.1.1-3ubuntu5`. No user PATH changes or shared native-command
framework changes were made.

- Expanded acceptance passes on both runtimes at
  `evidence/adaptor-growth-20261010/ffmpeg-bound-{9.0.2,6.1}/qualification.json`.
  H.264 and FFV1 full RGB/frame/timing checks, timed eight-frame sheet, unmet
  deliverable gates, completion/publication tamper and refreshed ordinary
  publication metadata rejection pass. Independent nonuniform FFV1 pixels match
  every row/edge/channel at 2×2, 32×24, 400×200, 1×1, 1×64, 64×1, 3×17, 17×3 and
  640×360, including offline replay after original PNG removal.
- Final source-bound native kits pass three cases plus timeout, cancellation and
  corruption probes on both runtimes at
  `evidence/adaptor-growth-20261010/ffmpeg-bound-final-native-{9.0.2,6.1}/qualification.json`.
  Source digest: `sha256:c04eb52bc3ea63d8d2800cea47f55679ca6d383d4e16a3fa01b5beb9d78d71df`.
- Targeted host suite: 30 tests pass, one optional native test skipped without an
  explicit test runtime. Cases cover FIFO PNG and metadata capture/fingerprinting,
  NUL and excessive sources, binding/launcher corruption/removal, malformed
  native stage evidence and changed video with refreshed publication metadata.
  Host conformance and all 32 conceptual-guidance records pass.

Coverage remains the bounded constant-rate, audio-free PNG/sheet publication
route. FFV1 version1 whole-frame pixels and hashes are verified; no version3 CRC,
perceptual-quality, arbitrary codec/filter or general editing certification.
