# whisper.cpp optional caption review

Route: `schemaxis.whispercpp/1`, `transcribe`, new optional boolean `captionReview`
(default `false`). This strengthens the existing adaptor; it adds no native option and
the native command line is unchanged. Scope: whisper.cpp 1.9.5 (official release
`v1.9.5`, reconfirmed as the latest by the integrating maintainer, not re-fetched in
this session) and WebVTT, which the W3C currently lists as a Candidate Recommendation
Draft (May 2026).

**The report certifies nothing.** It lists where fixed editorial heuristics suggest a
person look first. It never changes words or timing, and zero flags is not a pass:
human review of every caption against the audio is always required.

## Semantics

| Item | Definition |
| --- | --- |
| Publication | `caption-review.json` (`schemaxis.whispercpp.caption-review/1`), written only when the authored plan asks for it and listed fifth in the receipt's artifacts. Segments, transcript, SRT and WebVTT bytes are identical with or without it. |
| Per-cue record | `index`, `startMs`, `endMs`, `durationMs`, `codePoints`, `codePointsPerSecondMilli`, `flags`. Words are not repeated. |
| `short-duration` | `durationMs < 1000` |
| `long-duration` | `durationMs > 7000` |
| `dense-text` | `codePoints * 1000 > 20 * durationMs` (more than 20 code points per second), exact integer arithmetic |
| Length unit | Unicode code points of the published cue text (spaces and punctuation once each). Explicitly not grapheme clusters, not display width, no markup or WebVTT escaping. |
| Rate | `floor(codePoints * 1000000 / durationMs)`, an integer; the report holds no floating point. |
| Thresholds | Our editorial defaults. Not SRT, WebVTT or accessibility requirements; no source is claimed; not authorable. |
| Claims | `passCertified`, `accuracyCertified`, `accessibilityCertified`, `readabilityCertified` are `false`; `humanReviewRequired` is `true`; counts only, no overall verdict. |
| Bounds | At most 2000 cues; a 2000-cue report is far inside the 4 MiB JSON budget (tested). |
| No-option runs | The option is left out of the plan when not authored, so plan, losses, receipt, result and membership are unchanged. A run without it produced by the new code is accepted by the previous release's verifier, and both plan functions return identical plans for the same document. Explicit `false` disables the report but retains that field in the effective plan. |

## Independent verification

`verify` rebuilds the report from the independently checked segments and requires the
retained file to (1) parse as strict JSON (no duplicate keys, BOM or non-finite values),
(2) have the exact member set at every level and strict JSON types (a boolean is not
an integer, an integer is not a float or string), (3) match every metric, flag, count,
policy value and claim, located at the offending cue member, and (4) equal the
canonical bytes. Publication membership is exact in both directions: a report in a run
without the option, or a missing report in a run with it, fails even when every hash,
the authored plan and the effective plan are internally consistent and refreshed. The
result also carries a counts-only `captionReview` object that is recomputed and
compared exactly.

## Evidence

Implementation worker host tests (`tests/unit/test_whispercpp.py`, 32 tests, all passing; 12 are new):

- Pure heuristics: duration, density and rate boundaries including exact equality,
  flag order and independence, code points versus graphemes and display width
  (combining marks, a family emoji, CJK, WebVTT escaping), determinism, purity,
  no floats or verdicts, 2000-cue bound, zero-flag report still requiring review.
- Plan and schema: option omitted, `false` and `true`; non-boolean values and unknown
  threshold keys refused; unchanged native command; schema default `false`, not required.
- Deterministic native test double through the real runner and verifier: no-option
  run keeps the exact four-artifact result shape; review run adds only the report and
  leaves segments, text, captions and native evidence byte-identical; reopening works
  without the original audio or model; a native contract violation publishes no report.
- Adversarial: 40 forged strict-structure cases at the pure level and about 45
  rehashed or receipt-level forgeries on a run (metrics, flags, counts, hash binding,
  policy, claims, unknown or missing keys, type confusion, non-canonical bytes,
  BOM, duplicate key, NaN, oversize, result summary, receipt artifacts, option
  dropped or added with consistent plans). Failure reasons were inspected to confirm
  each case reached the intended check.
- Also run: `tools/studio_guidance.py --check` (whispercpp: 12 reviewed, 0 pending,
  0 stale); `tests.unit.test_adaptor_readiness`, `test_adaptor_completion` and
  `test_adaptor_kit` (40 tests); `schemaxis discover`.

Direct bounded native probe with the official v1.9.5 CPU build (runtime string
`whisper.cpp 1.9.5-dev`), `ggml-base.en` and the public `jfk.wav`, in a private
temporary directory, outside the qualifier. Not the final qualification.

- `captionReview: true`: one cue, 0 to 11000 ms, 107 code points, 9727 milli code
  points per second, flags `["long-duration"]`; result `artifacts: 5` with counts
  only. The same document without the option gave the unchanged four-artifact result.
- The qualifier's new `independent_review` (Fractions and literal thresholds, no
  adaptor parser) reproduced every field; words, timing, transcript, SRT and WebVTT
  matched the plain run. The qualifier's new `negative_review` (27 forgeries including
  refreshed hashes, result forgeries, missing report, report dropped from the receipt and
  option dropped with consistent plans) and its stray-report cases on a plain run were
  all rejected as `VERIFICATION_FAILED`, and both directories verified afterwards.

## Integration verification and limits

The integrating maintainer regenerated shared references, authored/expanded schemas
and packaged Help after the worker completed. Conceptual guidance, documentation
admission and the 33 focused Whisper tests pass. The additional test reproduces an
integer substituted for the retained boolean plan field; the effective plan now uses
a JSON type-preserving comparison and refuses the forgery after hashes are refreshed.
Two genuine pre-change native receipts still verify under the new code.

Fresh serial qualifications pass for three named Whisper cases, five SoX cases and
four Pandoc cases. The Whisper qualifier independently recomputes report metrics
using fractions, checks unchanged publications against the no-option case, and
rejects report/evidence/result forgeries. The registered source digest is refreshed
by the integrating maintainer after metadata integration. A separate named fixture
workflow passes real SoX audio into Whisper with captionReview enabled; a separately
materialised Pandoc report preserves the exact words, millisecond timing, draft
warning and editorial hint, independently reopened from DOCX. This is a named
fixture proof, not a general dynamic publishing transform or visual Word check.

Independent read-only review accepted the core implementation and requested website
integration and evidence/readiness wording repairs. Those are handled during
integration; bulk logs, snapshots and the final host-suite result remain in local
acceptance evidence rather than this compact note.

The 11 s and 8 s qualified recordings each produce a single cue, so real native
evidence exercises only long-duration. Short and dense flags are covered by host
tests, not native recordings. Code point counting does not model display width.
No new recognition, accessibility, readability or cross-language accuracy claim is
made. The full host suite and final checks belong to the integrating maintainer;
consult the batch acceptance record for actual completion, rather than inferring
success from this scope note.
