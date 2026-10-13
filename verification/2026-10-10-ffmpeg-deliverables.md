# FFmpeg media deliverables and evidence checks

The existing `schemaxis.ffmpeg/1` route now accepts an optional `deliverable`
policy for dimensions, frame count, native duration with an absolute tolerance,
encoded byte budget and maximum per-frame mean RGB error. Verification reconstructs
the assessment from authored requirements, actual encoded size, native probe
duration and fully decoded pixels. Correct videos with unmet requirements retain
their native evidence and suggested corrective actions under `DELIVERABLE_NOT_MET`;
they cannot become successful workflow publications. Native failures and invalid
source/policy faults remain separate.

Evidence JSON and native submissions must be regular files. Native commands and
successful stage completion are rechecked; malformed result/probe structures and
forged byte/quality summaries cannot bypass the independent checks. The total
timeout also bounds final verification before publication.

Native qualification exposed a removed FFmpeg option: the Shotcut runtime rejects
`-vsync 0`. New decoding uses `-fps_mode passthrough`, supported by both tested
runtimes. Offline verification also recognises the exact retained legacy decode
recipe, without permitting arbitrary command changes. Native option behaviour was
checked through installed FFmpeg help and actual runs.

New checks on 2026-10-10:

- `tests/unit/test_media_geospatial.py`: 25 tests pass, with one native test skipped
  unless an explicit FFmpeg runtime is selected. Added regressions cover malformed
  policies/evidence, legacy/exact commands, symlinks, forged summaries with matching
  byte hashes, measured duration, deadline exhaustion and explained unmet outcomes.
- FFmpeg admission and host conformance pass. Its conceptual guidance has complete
  field coverage with no pending records.
- Bounded native acceptance passes on `ffmpeg version 6.1.1-3ubuntu5` and Shotcut's
  `ffmpeg version n9.0.2-12-gc867e13549`. On each, two ordered 32×24 PNGs pass
  H.264/FFV1 full decode, an eight-frame sheet preserves 120/200 ms source durations,
  and byte/duration/dimension/strict-lossy-quality requirements produce explained
  unmet outcomes. The lossy case observes maximum mean RGB error
  2.2777777777777777 byte levels; a zero-error H.264 policy fails. Publication and
  stage-completion tamper fail; offline verification survives original source removal.
- Native kit conformance passes all three named cases on both runtimes, including
  publication/authored/plan corruption, timeout and pre-launch cancellation probes.
  The retained source digest is
  `sha256:119366a3f9c11d09a8a4688062532887c2171c3933504b18d6b5836f413453c5`.

Local bulk receipts are retained under
`evidence/adaptor-growth-20261010/ffmpeg-deliverable-{6.1,shotcut}-complete/qualification.json`
and `ffmpeg-native-{6.1,shotcut}/qualification.json`. The repeatable acceptance
recipe is [qualify_ffmpeg_deliverable.py](../tools/qualify_ffmpeg_deliverable.py).
The portable authored fixture is
[ffmpeg-deliverable.json](../examples/schemaxis/ffmpeg-deliverable.json).

These checks qualify the named serial cases and observed runtimes, not audio,
general editing/scaling, automatic encoder search, colour management, perceptual
quality or every upstream release. The bundled development runtime observation
does not change the absorbed stable upstream version. Receipts remain integrity
evidence rather than signed attestations against coordinated forgery.
