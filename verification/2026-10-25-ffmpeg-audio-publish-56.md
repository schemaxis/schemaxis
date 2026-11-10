# FFmpeg encodeAudio completion note (allocation 56)

Scope: new `encodeAudio` filter of the existing `schemaxis.ffmpeg/1` route: one captured canonical
PCM16 WAV to a verified AAC-LC/M4A under an exact byte budget and an exact rational mean absolute
sample-error budget. Legacy operations (`encodeFrames`, `encodeSheet`, `encodeVideo`, `muxReview`,
`extractAudio`) are unchanged. Product judgement: it fills the preparation-to-shareable-audio gap
(SoX/eSpeak NG WAV to a small file); demand from customers is not demonstrated. Upstream FFmpeg stays
at 9.0.2; `upstream.json` is untouched and no absorbed version advanced.

New runs below were executed on FFmpeg 9.0.2 (native AAC encoder, mp4 muxer), serial, one machine.

## Checklist

| ID | Result |
| --- | --- |
| registration | Same route and manifest; `encodeAudio` added to `DECLARATIONS`, `plan`, `reusableInputs`, `run`, `verify` dispatch only. Isolated module `publish_audio.py`; reuses same-adaptor `audio.py`/`review.py` helpers; no cross-adaptor import. |
| schema | `file`, `bitrateKbps` (enum 64/96/128/192, required, no default), `maxBytes` (1..32 MiB, required), `maxMeanPCMError` (finite 0..65535, required), `threads`; `deliverable` refused. Booleans, NaN, infinity, strings, floats for integers, out-of-range and unknown keys refused with no run directory and no native process (host test with native entry points replaced by failures). |
| semantics | Source is validated on the host before any directory or native process: canonical 44-byte PCM16 only; 16000/22050/44100/48000 Hz; mono/stereo; <=600 s; <=32 MiB. Budget compared as `Fraction(integer error sum, samples) <= Fraction(str(authored))`; endpoints, 1/3 neighbours, 0, -0.0 and 65535 are tested. |
| native-mapping | Fixed argv: AAC-LC `-b:a Nk`, `+bitexact`, `+faststart`, `-movie_timescale <rate>`, forced `wav`/`mov` demuxers, `-protocol_whitelist file`, no drefs, no filters/rate/channel/trim/pad flags. Decode at source rate/channels. Basis: FFmpeg 9.0.2 n9.0.2 `encoders.texi`/`muxers.texi` fetched by the master (SHA in its `inspection-v2.json`; the official web pages timed out) plus the 472-process feasibility matrix retained privately. |
| execution | Stages version/encode/probe/frames/decode via the shared runner with a digest-binding launcher, rlimits, FSIZE caps (encode capped at `maxBytes` plus slack, decode at the counted size), closed membership, strict JSON. Faults distinguish runtime failure, unsupported source, overflow, budget not met and timeouts. |
| discovery | Capability entry, 4 new search cases with neighbouring-operation exclusions. The node `search-acceptance` suite and CLI search were NOT run here. |
| guidance | `guidance.json`: operation record plus 9 field records, all reviewed; `tools/studio_guidance.py --app ffmpeg --check`: 55 reviewed, 16 from references, 0 pending, 0 stale. |
| help | NOT done by instruction: packaged Help, generated references (`docs/generated`), README and registry were not regenerated. `docs/ffmpeg.md` has the conceptual section. `readiness --app ffmpeg --admission --check` reports `studio.help` and `discovery.acceptance` outstanding until the master regenerates. |
| examples | `examples/schemaxis/ffmpeg-audio-publish.json`, `-invalid.json`; Studio starter `add-encode-audio` (not exercised in the Studio UI tests); fixtures `audio-publish-mono-16k.{wav,m4a}` published by the adaptor. `examples/schemaxis/ffmpeg-audio-publish-workflow.json` (eSpeak NG `en-us` narrate, file artifact 0, to `encodeAudio` at 96 kbit/s, 8 MiB, 2000 sample units: an illustrative budget, not a quality preset) planned on the host with the second step deferred and run natively once (mean error 3317710/119443, about 27.8, `workflow.verify` true). |
| tests | `tests/unit/test_ffmpeg_audio_publish.py`: 34 tests, host and native, pass (after the review-46 repair; 24 before it). Existing FFmpeg suites (`test_ffmpeg_audio/allocation/review/fresh/video_input/h264_readback/frame_cache`): 137 tests OK (82 + 55, serial). Neighbours referencing FFmpeg (`adaptor_kit/readiness`, `parallel_handoff_order`, `schema_storage`, `media_geospatial`): 79 OK. `studio_guidance --app ffmpeg --check`: 55 reviewed, 0 pending, 0 stale. The global suite was not run. |
| qualification | Superseded by the extended acceptance in the repair section below; the earlier record, for its own points: `tools/qualify_ffmpeg_audio_publish.py` (record retained privately): native suite 24/24; geometry matrix 10 cases (16000 mono 1 and 24001 frames, 22050, 44100, 48000, mono/stereo, odd and tiny) published, verified twice, and decoded again independently with every PCM byte equal; 220 actual native children (ffmpeg/ffprobe seen under `/proc`) all exited 0; legacy plans and argv identical to the committed baseline tree; a real eSpeak NG utterance and an `extractAudio` WAV were published and freshly verified. |
| maintenance | No upstream change; the next FFmpeg release needs re-running the qualifier because the container layout, priming and AAC output are checked at byte level. |

## Repair after review 46 (allocation 56, same assignment)

**Defect.** `container()` assumed one `stsc`/`stco` chunk, but FFmpeg 9.0.2's `movenc.c` `build_chunks` splits at 1 MiB, so any output over 1 MiB failed its own verification. Every earlier case was far below that. Reproduced on the unchanged tree with a generated 60 s, 48 kHz stereo source (11520044 bytes), 192 kbit/s, `maxBytes` 32 MiB, `maxMeanPCMError` 65535: `VERIFICATION_FAILED` "all packets must be stored in one chunk" for a 1455618-byte output of 2814 packets.

**Fix.** `publish_audio.chunk_layout` expands `stsc`/`stco` into per-chunk packet counts and byte lengths and requires them to tile the `mdat` payload exactly (details in `docs/ffmpeg.md`, "Chunk accounting"). No limit was changed (32 MiB output, 32 MiB source, 600 s), nothing was clamped or narrowed, and the header, edit-list, constant-packet-size, `stsz`, membership, claims and fresh-native checks are untouched. The same sibling-ffprobe predicate (recorded `ffprobe` must be beside the recorded `ffmpeg`) now applies to the new route and to the existing `extractAudio` receipts in `audio.py`; recorded paths are still never executed.

**Tests.** 32 chunk-table cases (second offset gap, overlap, out of order, swapped later chunks, duplicate, wrong first offset, stray and trailing `mdat`, one byte of slack, `stsc` miscount in both directions, first chunk not 1, run past the last chunk including a 2**32-1 index, sample description 0 and 2, zero-sample and duplicate and decreasing runs, size bounds for 2**32-1 declared entries) each checked to be refused for the stated reason; accepted multi-chunk layouts; a linear-time check at 16500 packets. A native test publishes 46 s of 48 kHz stereo noise (over 1 MiB, several chunks) and verifies it fresh; it fails on the original-56 source with the one-chunk refusal and passes now. Wrong-ffprobe receipts with refreshed digests are refused on both routes without executing the planted path, while genuine receipts match. Exact 600 s and 32 MiB limits are decided on the host (one frame over is `RESOURCE_LIMIT`).

**Test-helper defect found during the repair.** The first version of the "segment starts far past the last chunk" fixture expanded per-chunk lists of about 4.3 billion entries even though explicit offsets were supplied, which exhausted memory on the workstation twice (two Linux OOM kills) before the production parser ran. The parser was not at fault: it rejects that table before expanding anything. The builder now derives geometry only when offsets are not given and only within the fixture's packet count; the far-index table is still encoded as a table value and refused with `VERIFICATION_FAILED`. Under a 299 MiB address-space cap the old builder raised `MemoryError` and the new one builds 1683 bytes.

**Extended native acceptance** (FFmpeg 9.0.2, serial; `tools/qualify_ffmpeg_audio_publish.py`, each case its own supervised child; generated amplitude-modulated partials plus low-level noise, never speech):

| Case | Output | Chunks | Samples compared | Mean error (budget) | Max error |
| --- | --- | --- | --- | --- | --- |
| 60 s, 48 kHz stereo, 192 kbit/s, `maxBytes` 32 MiB | 1455618 B, 2814 packets | 2 | 5760000 of 5760000 | 449875243/5760000, about 78.1 (65535) | 2988 |
| 600 s, 16 kHz mono, 64 kbit/s, source 19200044 B | 4847173 B, 9376 packets | 5 (each under 1 MiB) | 9600000 of 9600000 | 18970697/960000, about 19.76 (3000) | 3699 |

Both were verified twice with a fresh native decode, decoded again by a separate invocation with every PCM byte equal, and had no full-scale samples. 34/34 native-suite cases, the 10-case geometry matrix (220 native children), the legacy-operation plan and argv control (identical to the committed baseline tree), the eSpeak NG and `extractAudio` handoffs, and the workflow example all passed with every native child exiting 0. Twenty genuine allocation-48 `extractAudio` runs verify read-only on the current source with unchanged trees and rows identical to the unchanged-source rows. The earlier short proof remains valid for its own points and is superseded by this extended acceptance; this is bounded named fixtures, not a long-form qualification, and not every length or quality.

**Wording.** The retained `probe.stdout` and `frames.stdout` are hash-bound diagnostic records of the original run. Verification makes its own fresh probe, frame listing and decode and compares the retained decode and summary with them, not those two files; this is deliberate and documented, with no added fidelity criterion.

## Observations worth keeping

* The mp4 muxer always writes `udta/meta`; `+bitexact` empties its item list and drops the encoder tag. The native output has a constant-size `stsz` (no entry table) when all packets are the same size (a one-frame source, silence); an early parser refused this and a test caught it (failed attempt retained privately).
* The encoder clamps by sample rate: 16 kHz mono gave identical bytes at 96/128/192 kbit/s and a larger file at 64 kbit/s, so `bitrateKbps` is documented as a target, never a measurement.
* Observed figures (mean error, bytes) are recipe- and runtime-specific.

## Limits and refused claims

* The error budget is a waveform number; no listening, audibility, recognition or identity claim. No human reviewed any output; the voice is eSpeak NG synthetic and the tones are generated.
* Verification re-decodes; it does not re-encode and does not authenticate the encoder. A coherent rewrite of source, output and summary is not detected. A different FFmpeg build with other float-to-PCM16 rounding fails verification.
* The matrix and the two extended cases are bounded named fixtures, not proof for every length, rate or quality. No MPI claim. No human listened to any output and no recognition or perceptual certification is made.
* Not done: Help/reference/README/registry regeneration, search-acceptance, global suite, commit or push.
