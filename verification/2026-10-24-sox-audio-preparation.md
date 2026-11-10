# SoX audio-preparation strengthening review

Route: `schemaxis.sox/1`, existing `assemble` operation. This review covers a
strengthening of the verifier and transcript-handoff summary for preparing an audio
excerpt before transcription. It adds no operation, native option, resampling or
codec, and keeps the frame-exact PCM16 oracle and native command mapping unchanged.
Items not listed below keep the [2026-10-17 review](2026-10-17-sox-completion.md).

## Concrete gaps found and repaired

Each was reproduced as a failing mutant against base `de5ab46`, with ordinary
artifact, evidence and publication-metadata hashes refreshed where a forger could.

| Gap | Repair |
| --- | --- |
| Native outputs (`clip-N.wav`, `audio.wav`) accepted injected `LIST`/`JUNK` chunks. | Outputs must be exactly canonical `fmt `+`data` (44-byte header). |
| Non-zero RIFF pad bytes and `fmt ` after `data` were not rejected by the parser. | Parser rejects both before native use. |
| Extra `.wav`, launcher, input-binding, submission, stdout/stderr files in a run directory were not detected. | Unreferenced files of those kinds fail reopening. |
| `verification.json` could carry extra or malformed fields. | Exact field set `executable`, `runtime`, `artifacts`, `evidence`. |
| `result.json` was unhashed; forged frames/duration/timeline passed. | Retained result must match independent reopening. |
| Retained-capture faults surfaced as input-time codes during verification. | Reported as `VERIFICATION_FAILED` naming the underlying code. |

Already detected before this change and retained as regressions: forged rate or
frame count in output/capture/summary, forged native command, exit code, launcher,
runtime identity, missing/extra evidence members and publication membership.

## Handoff clarity

`audio-summary.json` (verified by rebuilding from captures, plan and native output)
now carries exact `rate`, `channels`, `frames`, `durationExact` (reduced fraction)
and per-clip `segments`: captured source SHA-256, half-open source and output frame
intervals, gain and fades. `timeline.originalTimestampsPreserved` is `false` with the
mapping rule; docs/sox.md has a transcription-handoff section. No claim is made that
original timestamps survive edits, that audio is resampled/normalised to a transcriber
requirement, or that SoX transcribes.

## Checklist results for this change

| Item | Result |
| --- | --- |
| registration, schema, semantics | Unchanged declarations and plan; parser/verifier rules tightened. |
| native-mapping | Unchanged `trim`, `vol`, `fade t`, `--combine concatenate` mapping; native canonical-output behaviour observed for four LIST/JUNK source layouts on the local build. |
| execution | Receipt, result, membership and canonical-output checks above; timeout/cancel and workflow/handoff/composition retained in native qualifier. |
| discovery | Operation keywords `prepare audio for transcription`, `speech excerpt`; reviewed cases `transcription-preparation` (positive) and `negative-transcribe` (SoX does not transcribe). |
| guidance, help | Operation pitfall and source anchor `docs/sox.md#transcription-handoff-and-timeline`; docs fault recovery extended. Shared generated reference/Help regeneration is left to the master. |
| examples | Existing examples unchanged; handoff facts checked on all five native cases and four ancillary-chunk sources. |
| tests | 16 host tests (7 new) including a stdlib analytic SoX stand-in that exercises refreshed-hash mutants without native SoX. |
| qualification | Fresh native receipt registered from the final run; see below. Receipt freshness can still go stale after shared-source generation. |
| maintenance | Latest stable remains SoX 14.4.2 (SourceForge release list, 24 October 2026; `schemaxis updates --app sox` reports current). |

## Native evidence (new this session)

Official `sox-14.4.2.tar.bz2` from SourceForge, SHA-256
`81a6956d4330e75b5827316e44ae381e6f1e8928003c6aa45896da9041ea149c`, built locally
without codec libraries or installation. GCC 15 needed compiler flags only
(`-Wno-error=implicit-function-declaration -include math.h`, `LIBS=-lm`); the
upstream source was not modified. Runtime reported `SoX v14.4.2`.

Serial `tools/qualify_sox.py` passed: five native cases and 37540 independently
checked scalar samples (unchanged), timeline oracle on every case, 21 rejection
probes (seven new, refreshed-hash variants included), four LIST/JUNK source layouts
(56 samples each, canonical output), ten sample-rate boundaries, workflow reuse,
WAV handoff, two-state composition, and in-flight timeout/cancellation.
Observed LIST/JUNK-free output does not make the route an anonymiser; captured
sources retain original bytes. Bounds, single thread and scope are unchanged; no MPI,
resampling, other codecs or other operating systems are claimed. Bulk results are
retained outside the repository.

```sh
PYTHONPATH=src python3 -m unittest tests.unit.test_sox -q
PYTHONPATH=src python3 tools/studio_guidance.py --app sox --check
PYTHONPATH=src python3 -m schemaxis updates --app sox
PYTHONPATH=src python3 tools/qualify_sox.py --sox /absolute/path/to/sox --output-directory /new/empty/directory --register
```

## Master compatibility closeout

A fresh native run created with archived pre-batch de5ab46 source reproduced a
summary-compatibility regression. The verifier now recognises exactly the former
eight-field summary, recomputes every original assertion using current sample and
evidence checks, and returns that smaller assertion set without a timeline claim.
A host regression accepts that historical shape and rejects its forged frame count.
Partially missing new fields remain refused. Native original-source proof and
current-source reopening are retained outside the repository.

Independent Opus review also prompted exact directory membership (including
regular-file checks and only declared metadata sidecars), exact typed JSON result
comparison, and removal of workstation paths from published segment maps. Added
host regressions cover unrecognised audio extensions/sidecars and result boolean,
number-type and extra-field forgeries. Native qualifier timeline oracle was updated
to the path-free publication contract; original paths remain local capture evidence.
